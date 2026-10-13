import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

// Exécute le vrai worker avec les frontières Chrome/réseau simulées. Aucune
// session utilisateur ni requête vers un marchand n'est utilisée.
test('capture, envoi et fermeture concernent seulement l’onglet créé', async () => {
  const storage = {config: {origin:'https://faithbook.example', token:'test-token', id:'one'}};
  const listeners = {};
  const calls = [];
  let mode = 'success';
  let assets = {total:1, loaded:1, pending:0, broken:0, fonts_pending:false};
  const event = name => ({addListener: callback => { listeners[name] = callback; }, removeListener: () => {delete listeners[name];}});
  globalThis.chrome = {
    storage: {local: {
      setAccessLevel: async () => {},
      get: async () => structuredClone(storage),
      set: async value => Object.assign(storage, structuredClone(value)),
      remove: async key => {delete storage[key];}
    }},
    alarms: {get: async () => true, create: async () => {}, onAlarm:event('alarm')},
    runtime: {id:'extension', getURL: p=>'chrome-extension://extension/'+p,
      onStartup:event('startup'), onInstalled:event('installed'), onMessage:event('message')},
    action: {onClicked:event('click')},
    tabs: {
      create: async options => {calls.push(['create', options]); return {id:41};},
      get: async () => ({url: mode==='redirect' ? 'https://evil.test/' : 'https://www.academy.com/'}),
      remove: async id => calls.push(['remove',id])
    },
    debugger: {
      onEvent:event('debugger'),
      attach: async target=>calls.push(['attach',target]), detach: async target=>calls.push(['detach',target]),
      sendCommand: async (target, command, params) => {
        calls.push([command,target,params]);
        if(command==='Runtime.evaluate') {
          if(params.expression.includes('document.title')) return {result:{value:{title:'Academy',text: mode==='challenge'?'Robot or human? Please verify you are human.':mode==='missing'?"We couldn’t find this page. Try searching or go to the homepage.":'Outdoor shoes and clothing. '.repeat(10), final_url:'https://www.academy.com/',ready:'complete'}}};
          if(params.expression.includes('document.images')) return {result:{value:structuredClone(assets)}};
          return {result:{value:true}};
        }
        if(command==='Page.navigate') {
          await listeners.debugger({tabId:41},'Fetch.requestPaused',{requestId:'blocked',request:{url:'http://127.0.0.1/'}});
          if (mode==='navigation-error') return {errorText:'net::ERR_CONNECTION_TIMED_OUT'};
        }
        if(command==='Page.getLayoutMetrics') return {cssContentSize:{width:mode==='tall'?2400:1440,
          height:mode==='tall'?16000:mode==='growing' && calls.filter(c=>c[0]==='Page.getLayoutMetrics').length>1?2400:1800}};
        if(command==='Page.captureScreenshot') return {data:'jpeg-base64'};
      }
    },
    scripting: {executeScript: async ({func}) => {
      if(func.toString().includes('document.title')) return [{result:{title:'Academy',text: mode==='challenge'?'Robot or human? Please verify you are human.':'Outdoor shoes and clothing. '.repeat(10), final_url:'https://www.academy.com/',ready:'complete'}}];
      return [{result:true}];
    }}
  };
  let uploads = [];
  let uploadOffline = false;
  let noJobs = false;
  globalThis.fetch = async (url, options) => {
    assert.equal(options.credentials,'omit'); assert.equal(options.redirect,'error');
    if(url.endsWith('/claim')) return {ok:true,json:async()=>({job:noJobs ? null : {target_id:1,url:mode==='forged'?'https://evil.test/':'https://www.academy.com/',slot:'test-1',lease:'nonce'}})};
    if(url.endsWith('/result')) {
      if (uploadOffline) throw new Error('Hors ligne');
      uploads.push(JSON.parse(options.body)); return {ok:true,json:async()=>({run_id:9})};
    }
    return {ok:true,json:async()=>({queued:true})};
  };
  // Éviter les délais de rendu réels ; le code fonctionnel reste inchangé.
  const originalTimeout = globalThis.setTimeout;
  globalThis.setTimeout = callback => originalTimeout(callback,0);
  try {
    await import('./worker.js');
    async function run() {
      return new Promise(resolve => listeners.message({type:'test'}, {id:'extension',url:'chrome-extension://extension/options.html'}, resolve));
    }
    await run();
    assert.equal(uploads[0].status,'success');
    assert.equal(uploads[0].image,'jpeg-base64');
    assert.match(uploads[0].captured_at, /^\d{4}-\d\d-\d\dT.*Z$/);
    assert(calls.some(c=>c[0]==='Fetch.failRequest'));
    assert.equal(calls.find(c=>c[0]==='create')[1].url,'about:blank');
    assert.deepEqual(calls.find(c=>c[0]==='remove'), ['remove',41]);
    assert.equal(storage.outbox,undefined);
    calls.length=0; uploads=[]; mode='challenge';
    await run();
    assert.equal(uploads[0].status,'challenge');
    assert.equal(uploads[0].image,undefined);
    assert.equal(uploads[0].diagnostic_image,'jpeg-base64');
    assert(!calls.some(c=>c[0]==='Page.getLayoutMetrics'));
    calls.length=0; uploads=[]; mode='redirect';
    await run();
    assert.equal(uploads[0].status,'navigation');
    assert.equal(uploads[0].image,undefined);
    assert(!calls.some(c=>c[0]==='Page.getLayoutMetrics'));
    calls.length=0; uploads=[]; mode='navigation-error';
    await run();
    assert.equal(uploads[0].status,'navigation');
    assert.match(uploads[0].reason,/ERR_CONNECTION_TIMED_OUT/);
    assert.match(uploads[0].reason,/hors origine bloqué/);
    assert.equal(uploads[0].image,undefined);
    const diagnosticIndex = calls.findIndex(c=>c[0]==='Page.captureScreenshot');
    assert(diagnosticIndex >= 0 && diagnosticIndex < calls.findIndex(c=>c[0]==='detach'));
    calls.length=0; uploads=[]; mode='missing';
    await run();
    assert.equal(uploads[0].status,'navigation');
    assert.equal(uploads[0].image,undefined);
    calls.length=0; uploads=[]; mode='success'; assets={total:1, loaded:0, pending:1, broken:0, fonts_pending:false};
    await run();
    assert.equal(uploads[0].status,'capture');
    assert.match(uploads[0].reason,/Aucune image principale chargée/);
    assert.equal(uploads[0].image,undefined);
    calls.length=0; uploads=[]; mode='tall'; assets={total:3, loaded:2, pending:0, broken:1, fonts_pending:false};
    await run();
    assert.equal(uploads[0].status,'success');
    assert.match(uploads[0].reason,/10000 px/);
    assert.match(uploads[0].reason,/1 image\(s\) indisponible/);
    assets={total:1, loaded:1, pending:0, broken:0, fonts_pending:false};
    calls.length=0; uploads=[]; mode='growing';
    await run();
    assert.equal(uploads[0].status,'success');
    assert.equal(calls.find(c=>c[0]==='Page.captureScreenshot' && c[2].quality===80)[2].clip.height,2400);
    calls.length=0; mode='forged';
    await run();
    assert(!calls.some(c=>c[0]==='create'));
    assert.equal(listeners.message({type:'test'},{id:'extension',url:'https://evil.test'},()=>{}),undefined);
    // Après coupure, réenvoyer le résultat durable avant de créer un onglet.
    calls.length=0; uploads=[]; mode='success'; uploadOffline=true;
    await run();
    assert(storage.outbox?.payload.image);
    const savedLease = storage.outbox.payload.lease;
    const savedCapturedAt = storage.outbox.payload.captured_at;
    calls.length=0; uploadOffline=false; noJobs=true;
    await run();
    assert.equal(uploads[0].lease,savedLease);
    assert.equal(uploads[0].captured_at,savedCapturedAt);
    assert(!calls.some(c=>c[0]==='create'));
    assert.equal(storage.outbox,undefined);
  } finally {globalThis.setTimeout=originalTimeout;}
});

test('attendre les images et polices visibles puis terminer malgré un chargement bloqué', async () => {
  const {readAssetReadiness} = await import('./worker.js');
  const previousDocument = globalThis.document;
  const previousWindow = globalThis.window;
  const box = {width:300,height:200,top:20,bottom:220,left:10,right:310};
  const image = {complete:false,naturalWidth:0,getBoundingClientRect:()=>box};
  globalThis.document = {images:[image,
    {complete:false,naturalWidth:0,getBoundingClientRect:()=>({...box,width:1,height:1})},
    {complete:false,naturalWidth:0,getBoundingClientRect:()=>({...box,top:1000,bottom:1200})}],
    fonts:{status:'loading'}};
  globalThis.window = {innerWidth:1400,innerHeight:800,scrollY:0};
  try {
    setTimeout(()=>{image.complete=true;image.naturalWidth=600;document.fonts.status='loaded';},20);
    const ready = await readAssetReadiness(90);
    assert.deepEqual(ready,{total:1,loaded:1,pending:0,broken:0,fonts_pending:false});
    document.fonts.status='loading';
    setTimeout(()=>{document.fonts.status='loaded';},20);
    assert.equal((await readAssetReadiness(90)).fonts_pending,false);
    image.complete=false; image.naturalWidth=0;
    const started = Date.now();
    const stuck = await readAssetReadiness(40,500);
    assert.equal(stuck.total,1);
    assert.equal(stuck.pending,1);
    assert(Date.now()-started < 500, 'une image bloquée ne doit pas retenir indéfiniment la capture');
    image.complete=true;
    assert.equal((await readAssetReadiness(40)).broken,1);
  } finally {
    if(previousDocument===undefined) delete globalThis.document; else globalThis.document=previousDocument;
    if(previousWindow===undefined) delete globalThis.window; else globalThis.window=previousWindow;
  }
});

test('route Chrome et paquet installable présents', async () => {
  const manifest = JSON.parse(await readFile(new URL('./manifest.json',import.meta.url)));
  assert(!manifest.permissions.includes('cookies'));
  assert(!manifest.host_permissions.includes('<all_urls>'));
  const routes = await readFile(new URL('../frontend/src/lib.ts',import.meta.url),'utf8');
  assert(routes.includes("'chrome'"));
});
