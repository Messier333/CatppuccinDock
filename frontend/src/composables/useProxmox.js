import { computed, onMounted, onUnmounted, ref, watch, nextTick } from 'vue';
import { api } from '../lib/api.js';

export function useProxmox(root, layout) {
  const connections = ref([]), selected = ref(null), visible = new Set(), pending = new Set();
  let observer, timer, mounted = false;
  const byBookmark = computed(() => Object.fromEntries(connections.value.filter(row => row.config.enabled).flatMap(row => row.config.bookmark_ids.map(id => [id,row]))));
  function replace(row) {
    connections.value = connections.value.map(current => current.id === row.id ? row : current);
    if (selected.value?.id === row.id) selected.value = row;
  }
  async function refreshVisible() {
    if (document.hidden) return;
    const needed = connections.value.filter(row => row.config.enabled && row.config.bookmark_ids.some(id => visible.has(id)) && (row.refreshing || row.next_check <= Date.now()/1000) && !pending.has(row.id));
    // Bound active requests per browser; the server also coalesces across tabs.
    for (const row of needed.slice(0,2)) {
      pending.add(row.id);
      try {
        const result = await api(`integrations/proxmox/${row.id}/refresh`, {method:'POST'});
        if (mounted) replace(result);
      } catch { /* Existing information stays visible; details show connection errors. */ }
      finally { pending.delete(row.id); }
    }
  }
  async function observe() {
    await nextTick(); observer?.disconnect(); visible.clear();
    if (!mounted || !root.value) return;
    observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        const id = entry.target.dataset.bookmarkId;
        if (entry.isIntersecting) visible.add(id); else visible.delete(id);
      }
      refreshVisible();
    });
    root.value.querySelectorAll('[data-bookmark-id]').forEach(element => observer.observe(element));
  }
  watch(layout, observe, {flush:'post'});
  onMounted(async () => {
    mounted = true;
    try { const response = await api('integrations/proxmox'); if (mounted) { connections.value = response.integrations; await observe(); } }
    catch { /* An optional integration must not prevent opening the portal. */ }
    if (!mounted) return;
    timer = setInterval(refreshVisible, 15_000);
    document.addEventListener('visibilitychange', refreshVisible);
  });
  onUnmounted(() => { mounted = false; observer?.disconnect(); clearInterval(timer); document.removeEventListener('visibilitychange',refreshVisible); });
  return { byBookmark, selected, replace };
}
