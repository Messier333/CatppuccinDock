<script setup>
import { computed, nextTick, onBeforeUnmount, ref, useAttrs, useId, watch } from "vue";
import { Check, ChevronDown } from "lucide-vue-next";
defineOptions({ inheritAttrs: false });
const model = defineModel();
const props = defineProps({ options: { type: Array, default: () => [] }, label: { type: String, required: true }, disabled: Boolean, required: Boolean, placeholder: { type: String, default: '선택해 주세요' } });
const emit = defineEmits(['change']);
const attrs = useAttrs();
const id = useId();
const root = ref(null), trigger = ref(null), menu = ref(null), open = ref(false), active = ref(-1);
const position = ref({});
const selected = computed(() => props.options.find(item => item.value === model.value));
let typed = '', typedTimer;
function place() {
  if (!trigger.value || !menu.value) return;
  const rect = trigger.value.getBoundingClientRect();
  if (rect.bottom < 0 || rect.top > innerHeight) { close(); return; }
  const below = innerHeight - rect.bottom - 12;
  const above = rect.top - 12;
  const height = Math.min(280, Math.max(below, above));
  const width = Math.min(Math.max(rect.width, 200), innerWidth - 24);
  position.value = { width: `${width}px`, left: `${Math.max(12, Math.min(rect.left, innerWidth - width - 12))}px`, maxHeight: `${height}px`, top: below >= Math.min(180, above) ? `${rect.bottom + 6}px` : 'auto', bottom: below >= Math.min(180, above) ? 'auto' : `${innerHeight - rect.top + 6}px` };
}
async function reveal() {
  if (props.disabled || !props.options.length) return;
  open.value = true;
  active.value = props.options.findIndex(item => item.value === model.value && !item.disabled);
  if (active.value < 0) active.value = props.options.findIndex(item => !item.disabled);
  await nextTick();
  place();
  menu.value?.showPopover?.();
  scrollActive();
}
function close(restore = false) {
  menu.value?.hidePopover?.(); open.value = false;
  if (restore) trigger.value?.focus();
}
function choose(index) {
  const option = props.options[index];
  if (!option || option.disabled) return;
  model.value = option.value;
  emit('change', option.value);
  close(true);
}
function scrollActive() { nextTick(() => menu.value?.querySelector(`[data-index="${active.value}"]`)?.scrollIntoView({ block: 'nearest' })); }
function move(direction) {
  const available = props.options.map((option,index) => option.disabled ? -1 : index).filter(index => index >= 0);
  if (!available.length) return;
  const current = available.indexOf(active.value);
  active.value = available[(current + direction + available.length) % available.length];
  scrollActive();
}
function keydown(event) {
  if (['ArrowDown','ArrowUp'].includes(event.key)) {
    event.preventDefault(); if (!open.value) reveal(); else move(event.key === 'ArrowDown' ? 1 : -1);
  } else if (['Enter',' '].includes(event.key)) {
    event.preventDefault(); if (open.value) choose(active.value); else reveal();
  } else if (event.key === 'Escape' && open.value) { event.preventDefault(); event.stopPropagation(); close(true); }
  else if (event.key === 'Tab') close();
  else if (open.value && ['Home','End'].includes(event.key)) {
    event.preventDefault(); const available = props.options.map((option,index) => option.disabled ? -1 : index).filter(index => index >= 0);
    active.value = event.key === 'Home' ? available[0] : available.at(-1); scrollActive();
  } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
    typed += event.key.toLocaleLowerCase(); clearTimeout(typedTimer); typedTimer = setTimeout(() => typed = '', 600);
    const index = props.options.findIndex(option => !option.disabled && option.label.toLocaleLowerCase().startsWith(typed));
    if (index >= 0) { if (!open.value) reveal(); active.value = index; scrollActive(); }
  }
}
function outside(event) { if (open.value && !root.value?.contains(event.target)) close(); }
function scroll(event) { if (open.value && !menu.value?.contains(event.target)) place(); }
document.addEventListener('pointerdown', outside, true);
window.addEventListener('resize', place);
window.addEventListener('scroll', scroll, true);
watch(() => props.disabled, value => { if (value) close(); });
onBeforeUnmount(() => { close(); clearTimeout(typedTimer); document.removeEventListener('pointerdown', outside, true); window.removeEventListener('resize', place); window.removeEventListener('scroll', scroll, true); });
</script>
<template><span ref="root" class="theme-select">
  <input v-if="attrs.name" type="hidden" :name="attrs.name" :value="model" />
  <button :id="attrs.id" ref="trigger" type="button" role="combobox" class="theme-select-trigger" :class="{ expanded: open }" :disabled="disabled || !options.length" :aria-label="label" :aria-expanded="open" :aria-controls="`${id}-options`" :aria-activedescendant="open && active >= 0 ? `${id}-option-${active}` : undefined" :aria-required="required" aria-haspopup="listbox" @click="open ? close() : reveal()" @keydown="keydown"><span>{{ selected?.label || placeholder }}</span><ChevronDown :size="16" /></button>
  <span :id="`${id}-options`" ref="menu" popover="manual" class="theme-select-menu" :data-open="open" :style="position" role="listbox" :aria-label="label" @keydown="keydown" @mousedown.prevent>
    <button v-for="(option,index) in options" :id="`${id}-option-${index}`" :key="option.value" type="button" role="option" tabindex="-1" class="theme-select-option" :class="{ highlighted: index === active, selected: option.value === model }" :aria-selected="option.value === model" :aria-disabled="option.disabled || undefined" :disabled="option.disabled" :data-index="index" @pointermove="active = index" @click.stop="choose(index)"><span>{{ option.label }}</span><Check v-if="option.value === model" :size="15" /></button>
    <span v-if="!options.length" class="theme-select-empty">선택할 항목이 없습니다.</span>
  </span>
</span></template>
