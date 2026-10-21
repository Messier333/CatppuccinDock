import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { api } from '../lib/api.js';

// Observe the viewport, including clipping by the panel's own scroll containers.
// Requests return cached results immediately while the server queues stale checks.
export function useVisibleBookmarkStatus(root, layout) {
  const statuses = ref({});
  const visible = new Set();
  let observer, timer, request, stopped = false, busy = false, changed = false;

  function currentIds() {
    return [...visible].filter(element => element.isConnected && !element.closest('[inert]'))
      .map(element => element.dataset.bookmarkId);
  }
  function schedule(delay = 120) {
    clearTimeout(timer);
    // A response for the previous viewport must not overwrite a pending scroll/tab refresh.
    if (busy) { changed = true; return; }
    if (!stopped && !document.hidden && currentIds().length) timer = setTimeout(refresh, delay);
  }
  async function refresh() {
    if (stopped || document.hidden) return;
    if (busy) { changed = true; return; }
    const ids = [...new Set(currentIds())];
    if (!ids.length) return;
    busy = true; changed = false;
    request = new AbortController();
    let refreshing = false;
    try {
      for (let offset = 0; offset < ids.length; offset += 200) {
        if (stopped || document.hidden) break;
        const current = new Set(currentIds());
        const batch = ids.slice(offset, offset + 200).filter(id => current.has(id));
        if (!batch.length) continue;
        const result = await api('bookmark-status/refresh', {
          method: 'POST', body: JSON.stringify({ bookmark_ids: batch }), signal: request.signal,
        });
        if (stopped) break;
        // Keep other tabs' cached colors. Only remove dots explicitly absent in this batch.
        const next = { ...statuses.value };
        for (const id of batch) {
          if (result.statuses[id]) next[id] = result.statuses[id];
          else delete next[id];
        }
        statuses.value = next;
        refreshing ||= result.refreshing;
      }
    } catch { /* Keep the last known colors when offline or when a request is cancelled. */ }
    finally {
      busy = false;
      schedule(changed ? 120 : refreshing ? 1_500 : 60_000);
    }
  }
  function observe() {
    observer?.disconnect(); visible.clear(); clearTimeout(timer);
    if (!root.value || !observer) return;
    root.value.querySelectorAll('.startpage-content:not([inert]) [data-bookmark-id]')
      .forEach(element => observer.observe(element));
  }
  function visibilityChanged() {
    clearTimeout(timer);
    if (document.hidden) request?.abort();
    else schedule(0);
  }
  watch(layout, observe, { flush: 'post' });
  onMounted(() => {
    observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (entry.isIntersecting && entry.intersectionRatio > 0 && !entry.target.closest('[inert]')) visible.add(entry.target);
        else visible.delete(entry.target);
      }
      schedule();
    });
    observe();
    document.addEventListener('visibilitychange', visibilityChanged);
  });
  onBeforeUnmount(() => {
    stopped = true; clearTimeout(timer); observer?.disconnect(); request?.abort();
    document.removeEventListener('visibilitychange', visibilityChanged);
  });
  return statuses;
}
