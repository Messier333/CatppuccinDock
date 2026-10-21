import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { isCodeServerProxy, retireProxyPwa } from '../src/lib/pwaPolicy.js';
const manifest = JSON.parse(readFileSync(new URL('../public/manifest.webmanifest',import.meta.url)));
test('installable manifest resolves start, scope and icons within direct and proxy paths', () => {
  for (const base of ['https://portal.test/','https://portal.test/proxy/8090/']) {
    const url = new URL('manifest.webmanifest',base);
    assert.equal(new URL(manifest.start_url,url).href,base);
    assert.equal(new URL(manifest.scope,url).href,base);
    // Manifest IDs resolve against the start URL's origin, not the manifest's directory.
    const identity = new URL(manifest.id, new URL(manifest.start_url,url).origin + '/');
    assert.equal(identity.pathname, '/catppuccindock');
    assert.notEqual(identity.href, new URL(base).origin + '/');
    assert.equal(manifest.display,'standalone');
    for (const size of [192,512]) {
      const icon = manifest.icons.find(item => item.sizes === `${size}x${size}`);
      assert.ok(new URL(icon.src,url).href.startsWith(base));
      const bytes = readFileSync(new URL(`../public/${icon.src}`,import.meta.url));
      assert.equal(bytes.readUInt32BE(16),size);assert.equal(bytes.readUInt32BE(20),size);
    }
  }
});
test('path proxies are excluded while direct ports, domains and normal subpaths can install', () => {
  for (const path of ['/proxy/8090/', '/proxy/8090/admin/', '/absproxy/8090', '/user/alice/proxy/8090/']) {
    assert.equal(isCodeServerProxy('https://ide.test'+path), true);
  }
  for (const base of ['https://portal.test/', 'http://localhost:8090/', 'https://8090.ide.test/', 'https://portal.test/dock/', 'https://portal.test/proxy/settings/']) {
    assert.equal(isCodeServerProxy(base), false);
  }
});
test('legacy proxy cleanup preserves the IDE, other ports, foreign workers and cache entries', async () => {
  const origin = 'https://ide.test', base = origin+'/proxy/8090/';
  const removed=[],cacheRemoved=[];
  const registration = (scope, script, state='active') => ({scope,[state]:{scriptURL:script},unregister:async()=>removed.push(scope)});
  const workers = {getRegistrations:async()=>[
    registration(origin+'/',origin+'/ide-worker.js'),
    registration(origin+'/proxy/8080/',origin+'/proxy/8080/sw.js'),
    registration(base,base+'sw.js','waiting'),
    registration(base,base+'foreign-worker.js'),
    registration(origin+'/',base+'sw.js'),
  ]};
  const storage={keys:async()=>['code-server-cache','catppuccindock-offline-v1'],open:async key=>{
    assert.equal(key,'catppuccindock-offline-v1');return {delete:async url=>cacheRemoved.push(url)};
  }};
  await retireProxyPwa(workers,storage,base);
  assert.deepEqual(removed,[base]);
  assert.deepEqual(cacheRemoved,[base+'offline.html']);
});
test('cleanup is limited to proxy paths and tolerates restricted storage and worker failures', async () => {
  const unavailable={getRegistrations:async()=>{throw new Error('blocked');}};
  const storage={keys:async()=>{throw new Error('blocked');}};
  await assert.doesNotReject(retireProxyPwa(unavailable,storage,'https://ide.test/proxy/8090/'));
  const untouched={getRegistrations:()=>assert.fail('ordinary site must not unregister anything')};
  await retireProxyPwa(untouched,storage,'https://portal.test/');
});
test('service worker never intercepts API requests or caches authenticated pages', async () => {
  const handlers = {}, cached = [];
  const context = {URL,Promise,self:{registration:{scope:'https://portal.test/proxy/8090/'},location:{origin:'https://portal.test'},addEventListener:(name,handler)=>handlers[name]=handler,skipWaiting:()=>{},clients:{claim:()=>{}}},caches:{open:async()=>({add:url=>cached.push(url)}),keys:async()=>[],match:async()=>({offline:true})},fetch:async()=>({network:true})};
  vm.runInNewContext(readFileSync(new URL('../public/sw.js',import.meta.url),'utf8'),context);
  await new Promise((resolve,reject)=>handlers.install({waitUntil:promise=>promise.then(resolve,reject)}));
  assert.deepEqual(cached,['https://portal.test/proxy/8090/offline.html']);
  for (const path of ['api/portal','api/account','api/auth/oidc/callback']) {
    let intercepted=false;
    handlers.fetch({request:{mode:'navigate',url:'https://portal.test/proxy/8090/'+path},respondWith:()=>intercepted=true});
    assert.equal(intercepted,false);
  }
  let reply;
  handlers.fetch({request:{mode:'navigate',url:'https://portal.test/proxy/8090/'},respondWith:promise=>reply=promise});
  assert.deepEqual(await reply,{network:true});
  assert.equal(cached.length,1);
});
