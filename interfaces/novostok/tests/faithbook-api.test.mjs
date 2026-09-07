import test,{afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {request,api,ApiError,runsPath} from '../lib/faithbook-api.ts';
import {dayInZone,pastWeek,successRate,safeUrl,sourceChannel,readableTime} from '../lib/faithbook-data.ts';
const originalFetch=globalThis.fetch;
afterEach(()=>{globalThis.fetch=originalFetch});
test('requests include session cookie and explicit organization without tokens',async()=>{
 let seen;globalThis.fetch=async(url,init)=>{seen={url,init};return Response.json([])};
 await api.targets(3);assert.equal(seen.url,'/api/targets');assert.equal(seen.init.credentials,'same-origin');assert.equal(seen.init.cache,'no-store');assert.equal(seen.init.headers['X-Organization-ID'],'3');assert.equal(seen.init.headers.Authorization,undefined);
});
test('concurrent organization requests never share mutable organization context',async()=>{
 globalThis.fetch=async(url,init)=>Response.json({org:init.headers['X-Organization-ID']});
 const results=await Promise.all([request('/targets',{organizationId:3}),request('/targets',{organizationId:8})]);assert.deepEqual(results,[{org:'3'},{org:'8'}]);
});
test('authentication requests do not inherit a stale organization',async()=>{
 let init;globalThis.fetch=async(_,options)=>{init=options;return Response.json({id:1})};await api.login('user@example.test','example-password');assert.equal(init.headers['X-Organization-ID'],undefined);assert.equal(init.method,'POST');assert.deepEqual(JSON.parse(init.body),{email:'user@example.test',password:'example-password'});
});
test('expired sessions and denied organization access retain HTTP error codes',async()=>{
 for(const status of [401,403]){globalThis.fetch=async()=>Response.json({detail:'Accès refusé'},{status});await assert.rejects(api.targets(3),e=>e instanceof ApiError&&e.status===status&&e.message==='Accès refusé');}
});
test('an HTML fallback cannot masquerade as valid API data or a capture',async()=>{
 globalThis.fetch=async()=>new Response('<html>Login</html>',{headers:{'content-type':'text/html'}});await assert.rejects(api.me(),e=>e.status===502);await assert.rejects(api.image(3,17),e=>e.status===502);
});
test('capture reads keep tenant header and return image data',async()=>{
 let requestUrl,requestOptions;globalThis.fetch=async(url,init)=>{requestUrl=url;requestOptions=init;return new Response('image',{headers:{'content-type':'image/jpeg'}})};const image=await api.image(8,23);assert.equal(requestUrl,'/api/runs/23/thumbnail');assert.equal(requestOptions.headers['X-Organization-ID'],'8');assert.equal(image.type,'image/jpeg');assert.equal(await image.text(),'image');
});
test('abort on organization switch cancels pending reads',async()=>{
 globalThis.fetch=(_,init)=>new Promise((resolve,reject)=>{if(init.signal.aborted)return reject(new DOMException('aborted','AbortError'));init.signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')))});const controller=new AbortController();const pending=api.targets(3,controller.signal);controller.abort();await assert.rejects(pending,e=>e.name==='AbortError');
});
test('logout accepts empty success response',async()=>{globalThis.fetch=async()=>new Response(null,{status:204});assert.equal(await api.logout(),undefined)});
test('archive pagination and filters are sent to server with a zero offset',()=>{const path=runsPath({capture_date:'2026-09-07',target_id:42,status:'failed',limit:20,offset:0});const p=new URLSearchParams(path.split('?')[1]);assert.equal(p.get('offset'),'0');assert.equal(p.get('target_id'),'42');assert.equal(p.get('status'),'failed');assert.equal(p.get('capture_date'),'2026-09-07')});
test('source links reject executable schemes and credential-bearing URLs',()=>{for(const url of ['javascript:alert(1)','data:text/html,hi','https://user:pass@example.com'])assert.equal(safeUrl(url),null);assert.equal(safeUrl('https://example.com/path'),'https://example.com/path');assert.equal(sourceChannel('https://facebook.com.evil.test'),'Site web');assert.equal(sourceChannel('https://www.facebook.com/group'),'Facebook')});
test('calendar date uses configured timezone near UTC midnight',()=>{assert.equal(dayInZone(new Date('2026-09-07T23:30:00Z'),'Africa/Casablanca'),'2026-09-08');assert.deepEqual(pastWeek('2026-03-02'),['2026-02-24','2026-02-25','2026-02-26','2026-02-27','2026-02-28','2026-03-01','2026-03-02']);assert.equal(readableTime(null,'UTC'),'—')});
test('success rate is absent without finished runs and never invents 100 percent',()=>{assert.equal(successRate(0,0),null);assert.equal(successRate(0,2),0);assert.equal(successRate(55,2),100*55/57)});
