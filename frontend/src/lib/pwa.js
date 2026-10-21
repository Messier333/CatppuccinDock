import { computed, ref, shallowRef } from 'vue';
import { appUrl } from './navigation.js';
import { isCodeServerProxy, retireProxyPwa } from './pwaPolicy.js';
const proxy = isCodeServerProxy(appUrl());
const pending = shallowRef(null);
const installed = ref(!proxy && (window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true));
const busy = ref(false);
const available = computed(() => !proxy && !!pending.value && !installed.value);
let started = false;
export function initializePwa() {
  if (started) return;
  started = true;
  const icon = document.createElement('link'); icon.rel = 'icon'; icon.href = appUrl('app-icons/icon-192.png'); document.head.append(icon);
  if (proxy) {
    void retireProxyPwa(navigator.serviceWorker, window.caches, appUrl());
    return;
  }
  const manifest = document.createElement('link'); manifest.rel = 'manifest'; manifest.crossOrigin = 'use-credentials'; manifest.href = appUrl('manifest.webmanifest'); document.head.append(manifest);
  const apple = document.createElement('link'); apple.rel = 'apple-touch-icon'; apple.href = appUrl('app-icons/icon-192.png'); document.head.append(apple);
  window.addEventListener('beforeinstallprompt', event => { event.preventDefault(); pending.value = event; });
  window.addEventListener('appinstalled', () => { installed.value = true; pending.value = null; });
  if (window.isSecureContext && 'serviceWorker' in navigator) {
    navigator.serviceWorker.register(appUrl('sw.js'),{scope:appUrl(),updateViaCache:'none'}).catch(() => {});
  }
}
async function install() {
  if (!pending.value || busy.value) return;
  busy.value = true;
  const prompt = pending.value; pending.value = null;
  try { await prompt.prompt(); const choice = await prompt.userChoice; if (choice.outcome === 'accepted') installed.value = true; }
  catch { /* Browser menus remain available when a prompt expires or is blocked. */ }
  finally { busy.value = false; }
}
export function usePwaInstall() { return {available,installed,busy,install,secure:window.isSecureContext,proxy}; }
