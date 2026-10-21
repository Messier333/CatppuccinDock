import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

export function useSidebarResize(username) {
  const key = `catppuccindock:sidebar-width:${username}`;
  const preferred = ref(window.innerWidth <= 1050 ? 214 : 246);
  try {
    const stored = Number(localStorage.getItem(key));
    if (stored >= 200 && stored <= 420) preferred.value = stored;
  } catch { /* Resizing still works when browser storage is unavailable. */ }
  const viewport = ref(window.innerWidth), resizing = ref(false);
  const max = computed(() => Math.max(200, Math.min(420, viewport.value - 480)));
  const width = computed(() => Math.max(200, Math.min(max.value, preferred.value)));
  let startX = 0, startWidth = 0;
  function remember() { try { localStorage.setItem(key, String(preferred.value)); } catch { /* Optional browser preference. */ } }
  function begin(event) {
    if (!event.isPrimary || event.button !== 0 || viewport.value <= 700) return;
    event.preventDefault();
    startX = event.clientX; startWidth = width.value; resizing.value = true;
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event) {
    if (resizing.value) preferred.value = Math.max(200, Math.min(max.value, startWidth + event.clientX - startX));
  }
  function finish() { if (resizing.value) { resizing.value = false; remember(); } }
  function reset() { preferred.value = viewport.value <= 1050 ? 214 : 246; remember(); }
  function keydown(event) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Enter'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'Enter') { reset(); return; }
    preferred.value = event.key === 'Home' ? 200 : event.key === 'End' ? max.value : Math.max(200, Math.min(max.value, width.value + (event.key === 'ArrowRight' ? 16 : -16)));
    remember();
  }
  function resize() { viewport.value = window.innerWidth; if (viewport.value <= 700) finish(); }
  onMounted(() => window.addEventListener('resize', resize));
  onBeforeUnmount(() => window.removeEventListener('resize', resize));
  return { width, max, resizing, begin, move, finish, reset, keydown };
}
