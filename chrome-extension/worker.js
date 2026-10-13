import {URLS, publicProductURL, backendOrigin, sameSite, verdict, clipSize, captureWarnings} from './policy.mjs';

const ALARM = 'faithbook-check';
let busy = false;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function setup() {
  await chrome.storage.local.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'});
  if (!await chrome.alarms.get(ALARM)) await chrome.alarms.create(ALARM, {periodInMinutes: 1, delayInMinutes: 1});
}

async function api(config, path, payload = {}) {
  const response = await fetch(backendOrigin(config.origin) + '/api/browser-capture/' + path, {
    method: 'POST', headers: {'Content-Type': 'application/json', Authorization: `Bearer ${config.token}`, 'X-FaithBook-Capture-Version': '2'},
    body: JSON.stringify(payload), credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(25000)
  });
  if (!response.ok) {
    const error = new Error(`FaithBook : erreur ${response.status}. Vérifiez l’appairage ou l’historique.`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function inPage(tabId, func, args = []) {
  const result = await chrome.debugger.sendCommand({tabId}, 'Runtime.evaluate', {
    expression: `(${func.toString()})(${args.map(value => JSON.stringify(value)).join(',')})`, returnByValue: true, awaitPromise: true
  });
  if (result.exceptionDetails) throw new Error('Page illisible.');
  return result.result?.value;
}

export async function readAssetReadiness(maxMs, height = null) {
  const started = Date.now();
  const visibleImages = () => [...document.images].filter(image => {
    const box = image.getBoundingClientRect();
    const top = height === null ? box.top : box.top + window.scrollY;
    const bottom = height === null ? box.bottom : box.bottom + window.scrollY;
    // Ignore tracking pixels, hidden icons and images beyond the captured area.
    return box.width >= 80 && box.height >= 60 && box.right > 0 && box.left < window.innerWidth &&
      bottom > 0 && top < (height === null ? window.innerHeight : height);
  });
  let state;
  // Bound both elapsed time and iterations, including pages with a stuck asset.
  for (let check = 0; check < 24; check++) {
    const images = visibleImages();
    state = {total: images.length, loaded: 0, pending: 0, broken: 0,
      fonts_pending: document.fonts?.status === 'loading'};
    for (const image of images) {
      if (!image.complete) state.pending++;
      else if (image.naturalWidth > 0) state.loaded++;
      else state.broken++;
    }
    if ((!state.pending && !state.fonts_pending) || Date.now() - started >= maxMs) break;
    await new Promise(resolve => setTimeout(resolve, Math.min(250, Math.max(1, maxMs - (Date.now() - started)))));
  }
  return state;
}

async function waitForAssets(tabId, maxMs, height = null) {
  return inPage(tabId, readAssetReadiness, [maxMs, height]);
}

async function pageInfo(tabId) {
  const value = await inPage(tabId, () => ({
    title: document.title.slice(0, 500), text: (document.body?.innerText || '').slice(0, 100000),
    final_url: location.href, ready: document.readyState
  }));
  if (!value) throw new Error('Page illisible.');
  return value;
}

async function capture(job) {
  if (!(job.kind === 'product' ? publicProductURL(job.url) : URLS.has(job.url))) throw new Error('Cible non autorisée.');
  const tab = await chrome.tabs.create({url: 'about:blank', active: false});
  const target = {tabId: tab.id};
  let attached = false;
  let blockedOrigin = '';
  const guard = (source, method, params) => {
    if (source.tabId !== tab.id || method !== 'Fetch.requestPaused') return;
    const allowed = sameSite(job.url, params.request.url);
    if (!allowed) {
      try { blockedOrigin = new URL(params.request.url).origin; } catch { blockedOrigin = 'URL invalide'; }
    }
    void chrome.debugger.sendCommand(target, allowed ? 'Fetch.continueRequest' : 'Fetch.failRequest',
      allowed ? {requestId: params.requestId} : {requestId: params.requestId, errorReason: 'BlockedByClient'}).catch(() => {});
  };
  const failureResult = async (status, reason, page = {}) => {
    const failure = {...page, status, reason: String(reason || '').slice(0, 300)};
    try {
      const view = await chrome.debugger.sendCommand(target, 'Page.captureScreenshot', {format: 'jpeg', quality: 60});
      if (view.data.length < 3000000) failure.diagnostic_image = view.data;
    } catch {}
    return failure;
  };
  try {
    // Seul l’onglet créé par cette exécution est attaché ou fermé.
    await chrome.debugger.attach(target, '1.3');
    attached = true;
    await chrome.debugger.sendCommand(target, 'Page.enable');
    chrome.debugger.onEvent.addListener(guard);
    await chrome.debugger.sendCommand(target, 'Fetch.enable', {patterns: [{urlPattern: '*', resourceType: 'Document', requestStage: 'Request'}]});
    const navigation = await chrome.debugger.sendCommand(target, 'Page.navigate', {url: job.url});
    if (navigation?.errorText) {
      return await failureResult('navigation', `Navigation Chrome : ${navigation.errorText}${blockedOrigin ? ' ; document hors origine bloqué : ' + blockedOrigin : ''}`);
    }
    let page;
    const until = Date.now() + 45000;
    while (Date.now() < until) {
      const current = await chrome.tabs.get(tab.id);
      if (current.url && !sameSite(job.url, current.url) && current.url !== 'about:blank') return await failureResult('navigation', 'Redirection vers un autre site bloquée : ' + new URL(current.url).hostname);
      try { page = await pageInfo(tab.id); } catch { await delay(1000); continue; }
      if (verdict(page) === 'challenge') break;
      if (page.ready === 'complete' && page.text.length >= 50) break;
      await delay(1000);
    }
    if (!page || !sameSite(job.url, page.final_url)) return await failureResult('navigation', page ? 'Redirection hors du site prévu.' : 'Page non chargée après 45 s.', page);
    await delay(3000);
    page = await pageInfo(tab.id);
    if (!sameSite(job.url, page.final_url)) return await failureResult('navigation', 'Redirection hors du site prévu.', page);
    let status = verdict(page);
    if (status !== 'success') return await failureResult(status, status === 'navigation' ? 'Page introuvable ou lien obsolète.' : '', page);
    // Chargement différé borné ; jamais de clic sur les vérifications humaines.
    for (let step = 0; step < 30; step++) {
      const bottom = await inPage(tab.id, () => {
        window.scrollBy(0, window.innerHeight * .85);
        return window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 5;
      });
      await delay(500);
      await waitForAssets(tab.id, 1200);
      if (bottom) break;
    }
    await inPage(tab.id, () => window.scrollTo(0, 0));
    await delay(500);
    page = await pageInfo(tab.id);
    status = verdict(page);
    if (!sameSite(job.url, page.final_url)) return await failureResult('navigation', 'Redirection hors du site prévu.', page);
    if (status !== 'success') return await failureResult(status, status === 'navigation' ? 'Page introuvable ou lien obsolète.' : '', page);
    const metrics = await chrome.debugger.sendCommand(target, 'Page.getLayoutMetrics');
    const size = metrics.cssContentSize;
    let {truncated, ...clip} = clipSize(size.width, size.height);
    let assets = await waitForAssets(tab.id, 5000, clip.height);
    // Fonts and images may change the document height while we wait. Use the
    // refreshed layout rather than silently cutting it at the previous height.
    const settled = await chrome.debugger.sendCommand(target, 'Page.getLayoutMetrics');
    const settledClip = clipSize(settled.cssContentSize.width, settled.cssContentSize.height);
    if (settledClip.height !== clip.height || settledClip.width !== clip.width) {
      ({truncated, ...clip} = settledClip);
      assets = await waitForAssets(tab.id, 1000, clip.height);
    }
    if (assets?.total > 0 && assets.loaded === 0) {
      return await failureResult('capture', 'Aucune image principale chargée. ' + captureWarnings({truncated, height: clip.height}, assets), page);
    }
    const shot = await chrome.debugger.sendCommand(target, 'Page.captureScreenshot', {
      format: 'jpeg', quality: 80, captureBeyondViewport: true, clip
    });
    const capturedAt = new Date().toISOString();
    const after = await pageInfo(tab.id);
    if (!sameSite(job.url, after.final_url)) return await failureResult('navigation', 'Redirection hors du site prévu.', after);
    status = verdict(after);
    if (status !== 'success') return await failureResult(status, status === 'navigation' ? 'Page introuvable ou lien obsolète.' : '', after);
    if (shot.data.length > 8000000) return await failureResult('capture', 'Image trop lourde (> 8 Mo).', after);
    return {...after, status: 'success', image: shot.data, captured_at: capturedAt,
      reason: captureWarnings({truncated, height: clip.height}, assets)};
  } catch (error) {
    // Diagnostic : ce que Chrome affichait au moment de l'échec (écran visible
    // uniquement) et la raison exacte, au lieu d'un échec muet.
    let page = {};
    try { page = await pageInfo(tab.id); } catch {}
    return await failureResult('capture', String(error?.message || error), page);
  } finally {
    chrome.debugger.onEvent.removeListener(guard);
    if (attached) await chrome.debugger.detach(target).catch(() => {});
    await chrome.tabs.remove(tab.id).catch(() => {});
  }
}

async function flush(config) {
  const {outbox} = await chrome.storage.local.get('outbox');
  if (!outbox) return;
  if (outbox.configId !== config.id) throw new Error('Résultat en attente pour un autre appairage.');
  try {
    const result = await api(config, 'result', outbox.payload);
    await chrome.storage.local.remove('outbox');
    await chrome.storage.local.set({lastStatus: `Reçu par FaithBook : exécution #${result.run_id}`, lastAt: new Date().toISOString()});
  } catch (error) {
    // Une réservation expirée ne peut plus être importée. Garder le message,
    // libérer la boîte d’envoi et laisser le serveur décider du rattrapage.
    if ([409, 413, 422].includes(error.status)) await chrome.storage.local.remove('outbox');
    throw error;
  }
}

async function tick(test = false) {
  if (busy) return;
  busy = true;
  try {
    await setup();
    const {config} = await chrome.storage.local.get('config');
    if (!config) return;
    await flush(config);
    if (test) await api(config, 'test');
    // Un onglet à la fois ; la prochaine alarme traite la cible suivante.
    const {job} = await api(config, 'claim');
    if (!job) return;
    let result;
    try { result = await capture(job); } catch (error) { result = {status: 'capture', reason: String(error?.message || error).slice(0, 300)}; }
    const payload = {target_id: job.target_id, slot: job.slot, lease: job.lease, ...result};
    delete payload.ready;
    await chrome.storage.local.set({outbox: {configId: config.id, payload}});
    await flush(config);
  } catch (error) {
    await chrome.storage.local.set({lastStatus: error.message, lastAt: new Date().toISOString()});
  } finally { busy = false; }
}

chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === ALARM) void tick(); });
chrome.runtime.onStartup.addListener(() => { void tick(); });
chrome.runtime.onInstalled.addListener(() => { void setup(); });
chrome.action.onClicked.addListener(() => { void chrome.runtime.openOptionsPage(); });
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL('options.html')) return;
  if (message.type === 'test') { tick(true).then(() => reply({ok: true})); return true; }
  if (message.type === 'wake') { tick().then(() => reply({ok: true})); return true; }
});
void setup();
