// Only the public offline page is cached. Authenticated pages and APIs stay on the network.
const CACHE = 'catppuccindock-offline-v1';
const offline = new URL('offline.html',self.registration.scope).href;
self.addEventListener('install',event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.add(offline)).then(() => self.skipWaiting()));
});
self.addEventListener('activate',event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('catppuccindock-offline-') && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch',event => {
  const url = new URL(event.request.url);
  if (event.request.mode !== 'navigate' || url.origin !== self.location.origin || !url.href.startsWith(self.registration.scope) || url.pathname.includes('/api/')) return;
  event.respondWith(fetch(event.request).catch(() => caches.match(offline)));
});
