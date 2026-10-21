<script setup>
import { nextTick, onBeforeUnmount, ref } from 'vue';
import { activateWidgetPanel, releaseWidgetPanel } from '../../lib/widgetPanels.js';
defineProps({ label: { type: String, required: true } });
const root = ref(null), panel = ref(null), open = ref(false), pinned = ref(false), position = ref({});
let restoringFocus = false, revealVersion = 0;
function place() {
  if (!open.value || !root.value || !panel.value) return;
  const anchor = root.value.getBoundingClientRect(), box = panel.value.getBoundingClientRect();
  const width = Math.min(304, innerWidth - 24);
  const above = Math.max(0, anchor.top - 12), below = Math.max(0, innerHeight - anchor.bottom - 12);
  const showAbove = above >= Math.min(box.height, below);
  // Touch the anchor so moving into the panel needs no delayed dismissal.
  position.value = {
    width: `${width}px`, left: `${Math.max(12, Math.min(anchor.right - width, innerWidth - width - 12))}px`,
    top: showAbove ? 'auto' : `${anchor.bottom}px`, bottom: showAbove ? `${innerHeight - anchor.top}px` : 'auto',
    maxHeight: `${showAbove ? above : below}px`,
  };
}
async function reveal() {
  if (open.value) return;
  activateWidgetPanel(close);
  const version = ++revealVersion;
  open.value = true;
  await nextTick();
  if (!open.value || version !== revealVersion) return;
  panel.value?.showPopover?.();
  place();
}
function close() { revealVersion++; panel.value?.hidePopover?.(); open.value = false; pinned.value = false; releaseWidgetPanel(close); }
function togglePin() {
  if (pinned.value) { close(); return; }
  pinned.value = true;
  reveal();
}
function leave(event) { if (!pinned.value && !root.value?.contains(event.relatedTarget)) close(); }
function focusin(event) { if (!restoringFocus && !root.value?.contains(event.relatedTarget)) reveal(); }
function focusout(event) { if (!root.value?.contains(event.relatedTarget)) close(); }
function outside(event) { if (!root.value?.contains(event.target)) close(); }
function keydown(event) {
  if (event.key !== 'Escape') return;
  event.preventDefault(); event.stopPropagation();
  close();
  restoringFocus = true;
  root.value?.querySelector('button')?.focus({ preventScroll: true });
  restoringFocus = false;
}
document.addEventListener('pointerdown', outside, true);
window.addEventListener('resize', place);
window.addEventListener('scroll', place, true);
onBeforeUnmount(() => { close(); document.removeEventListener('pointerdown', outside, true); window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); });
</script>
<template><div ref="root" class="widget-anchor" @mouseenter="reveal" @mouseleave="leave" @focusin="focusin" @focusout="focusout" @keydown="keydown">
  <slot name="trigger" :open="open" :pinned="pinned" :reveal="reveal" :toggle-pin="togglePin" />
  <section ref="panel" popover="manual" class="widget-panel" :data-open="open" :style="position" role="dialog" :aria-label="label" @mouseleave="leave" @keydown.stop="keydown"><slot v-if="open" :close="close" /></section>
</div></template>
