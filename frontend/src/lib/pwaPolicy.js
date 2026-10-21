// A path proxy shares the IDE's origin and installed-app scope.
export function isCodeServerProxy(baseUrl) {
  return /\/(?:proxy|absproxy)\/\d+(?:\/|$)/.test(new URL(baseUrl).pathname);
}

// Only remove this portal's exact registration and offline entry. Never clear
// the origin's other workers, caches, cookies or IDE storage.
export async function retireProxyPwa(serviceWorker, cacheStorage, baseUrl) {
  const base = new URL(baseUrl).href;
  if (!isCodeServerProxy(base)) return;
  const script = new URL('sw.js', base).href;
  try {
    const registrations = await serviceWorker?.getRegistrations() || [];
    await Promise.allSettled(registrations.filter(registration =>
      registration.scope === base &&
      [registration.active, registration.waiting, registration.installing].some(worker => worker?.scriptURL === script)
    ).map(registration => registration.unregister()));
  } catch { /* Proxy browsing remains usable when worker access is unavailable. */ }
  try {
    const offline = new URL('offline.html', base).href;
    const keys = await cacheStorage?.keys() || [];
    await Promise.allSettled(keys.filter(key => key === 'catppuccindock-offline-v1')
      .map(async key => (await cacheStorage.open(key)).delete(offline)));
  } catch { /* Private browsing may disable Cache Storage. */ }
}
