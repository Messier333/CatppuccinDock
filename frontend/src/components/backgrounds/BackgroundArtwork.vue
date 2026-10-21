<script setup>
import { nextTick, onBeforeUnmount, ref, useId } from 'vue';
import { ExternalLink, Info } from 'lucide-vue-next';
import { activateWidgetPanel, releaseWidgetPanel } from '../../lib/widgetPanels.js';

defineProps({ source: Object });
const credit = ref(null), panel = ref(null);
const open = ref(false), dismissed = ref(false), position = ref({});
const panelId = useId();
let version = 0;
function place() {
  if (!open.value || !credit.value || !panel.value) return;
  const anchor = credit.value.getBoundingClientRect();
  const width = Math.min(320, innerWidth - 24);
  const below = innerHeight - anchor.bottom - 12;
  const above = anchor.top - 12;
  const showBelow = below >= Math.min(panel.value.scrollHeight, above);
  position.value = {
    width: `${width}px`, left: `${Math.max(12, Math.min(anchor.left, innerWidth - width - 12))}px`,
    top: showBelow ? `${anchor.bottom}px` : 'auto',
    bottom: showBelow ? 'auto' : `${innerHeight - anchor.top}px`,
    maxHeight: `${Math.max(0, showBelow ? below : above)}px`,
  };
}
async function reveal() {
  if (dismissed.value || open.value) return;
  activateWidgetPanel(close);
  const current = ++version;
  open.value = true;
  await nextTick();
  if (!open.value || current !== version) return;
  panel.value?.showPopover?.();
  place();
}
function close() {
  version++;
  panel.value?.hidePopover?.();
  open.value = false;
  releaseWidgetPanel(close);
}
function dismiss(event) {
  // A new tab preserves :hover and focus in the opener. Hide until a fresh
  // pointer entry or keyboard focus, rather than waiting for an outside click.
  dismissed.value = true;
  close();
  if (event.detail > 0) event.currentTarget.blur();
}
function focus() { dismissed.value = false; reveal(); }
function leave(event) { if (!credit.value?.contains(event.relatedTarget)) close(); }
function outside(event) { if (!credit.value?.contains(event.target)) close(); }
function escape(event) {
  if (event.key !== 'Escape') return;
  event.preventDefault();
  close();
  dismissed.value = true;
  credit.value?.querySelector('a')?.focus({ preventScroll: true });
  // The focus handler may reopen; Escape always wins.
  dismissed.value = true;
  close();
}
document.addEventListener('pointerdown', outside, true);
window.addEventListener('resize', place);
window.addEventListener('scroll', place, true);
onBeforeUnmount(() => {
  close();
  document.removeEventListener('pointerdown', outside, true);
  window.removeEventListener('resize', place);
  window.removeEventListener('scroll', place, true);
});
</script>

<template>
  <div class="startpage-art" @pointerenter="dismissed = false">
    <slot />
    <div v-if="source" ref="credit" class="background-credit" :data-dismissed="dismissed" @pointerenter="reveal" @pointerleave="leave" @focusout="leave" @keydown.stop="escape">
      <a class="background-credit-trigger" :href="source.page_url" target="_blank" rel="noopener noreferrer" aria-label="GIF 출처와 라이선스 보기 · 새 탭" :aria-describedby="open ? panelId : undefined" @focus="focus" @click="dismiss"><Info :size="13" aria-hidden="true" /><span>출처</span></a>
      <section :id="panelId" ref="panel" popover="manual" class="background-credit-panel" :data-open="open" :style="position" aria-label="GIF 출처 정보">
        <strong>{{ source.title || 'GIF 배경' }}</strong>
        <dl>
          <div><dt>작성자</dt><dd>{{ source.author || '제공된 작성자 정보 없음' }}</dd></div>
          <div><dt>라이선스</dt><dd><a v-if="source.license_url" :href="source.license_url" target="_blank" rel="noopener noreferrer" @click="dismiss">{{ source.license || '라이선스 확인' }} <ExternalLink :size="11" aria-hidden="true" /></a><span v-else>{{ source.license || '이용 조건 확인 필요' }}</span></dd></div>
          <div><dt>표시 방식</dt><dd>메뉴 배경에 맞춰 가운데 영역을 표시합니다. 저장 과정에서 크기·프레임·색상 조정 또는 영상의 GIF 변환이 적용되었을 수 있습니다.</dd></div>
        </dl>
        <a :href="source.page_url" target="_blank" rel="noopener noreferrer" @click="dismiss">원본 정보 페이지 <ExternalLink :size="12" aria-hidden="true" /></a>
      </section>
    </div>
  </div>
</template>

<style scoped>
.background-credit { position: absolute; right: 8px; bottom: 8px; opacity: 0; pointer-events: none; }
.startpage-art:hover .background-credit, .startpage-art:focus-within .background-credit { opacity: 1; pointer-events: auto; }
.startpage-art .background-credit[data-dismissed="true"] { opacity: 0; pointer-events: none; }
.background-credit-trigger { display: inline-flex; align-items: center; gap: 4px; padding: 6px 8px; border: 1px solid var(--control-border); border-radius: 6px; color: var(--text); background: color-mix(in srgb, var(--base) 90%, transparent); font-size: 10px; text-decoration: none; }
.background-credit-trigger:hover, .background-credit-trigger:focus-visible { color: var(--accent); outline: 2px solid var(--accent); outline-offset: 2px; }
.background-credit-panel { position: fixed; inset: auto; margin: 0; box-sizing: border-box; max-width: calc(100vw - 24px); overflow: auto; padding: 14px; border: 1px solid var(--control-border); border-radius: 10px; background: var(--surface); color: var(--text); box-shadow: var(--menu-shadow); font: 12px/1.6 'Nunito', 'Noto Sans KR', sans-serif; overflow-wrap: anywhere; }
.background-credit-panel:not([data-open="true"]) { display: none; }
.background-credit-panel strong { font-size: 13px; }
.background-credit-panel dl { display: grid; gap: 8px; margin: 12px 0; }
.background-credit-panel dl > div { display: grid; grid-template-columns: 62px minmax(0, 1fr); gap: 8px; }
.background-credit-panel dt { color: var(--subtext); }
.background-credit-panel dd { margin: 0; }
.background-credit-panel a { color: var(--accent); text-underline-offset: 3px; }
.background-credit-panel svg { display: inline; vertical-align: middle; }
@media (hover: none) { .background-credit { opacity: 1; pointer-events: auto; } }
</style>
