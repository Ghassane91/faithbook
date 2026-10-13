import {backendOrigin, readableText} from './policy.mjs';
const status = document.querySelector('#status');
async function refresh() {
  const {lastStatus, lastAt} = await chrome.storage.local.get(['lastStatus', 'lastAt']);
  status.textContent = lastStatus ? `${readableText(lastStatus)} — ${new Date(lastAt).toLocaleString('fr-FR')}` : 'Aucune capture reçue pour le moment.';
}
const {config} = await chrome.storage.local.get('config');
if (config) { document.querySelector('#origin').value = config.origin; document.querySelector('#token').value = config.token; }
document.querySelector('#config').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    const origin = backendOrigin(document.querySelector('#origin').value.trim());
    const token = document.querySelector('#token').value.trim();
    if (!/^[A-Za-z0-9_-]{40,64}$/.test(token)) throw new Error('Code d’appairage invalide.');
    // Appel direct dans le geste utilisateur requis par Chrome.
    const permission = await chrome.permissions.request({origins: [origin + '/*']});
    if (!permission) throw new Error('Accès à FaithBook non accordé.');
    const {outbox} = await chrome.storage.local.get('outbox');
    if (outbox) throw new Error('Un envoi est en attente. Réessayez après sa réception.');
    await chrome.storage.local.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'});
    await chrome.storage.local.set({config: {origin, token, id: crypto.randomUUID()}});
    document.querySelector('#token').value = '';
    status.textContent = 'Appairage enregistré. Vérification de la connexion…';
    await chrome.runtime.sendMessage({type: 'wake'});
    await refresh();
  } catch (error) { status.textContent = readableText(error.message); }
});
document.querySelector('#test').addEventListener('click', async () => {
  status.textContent = 'Test demandé. Les résultats seront visibles dans l’historique FaithBook.';
  await chrome.runtime.sendMessage({type: 'test'});
  await refresh();
});
chrome.storage.onChanged.addListener(() => { void refresh(); });
await refresh();
