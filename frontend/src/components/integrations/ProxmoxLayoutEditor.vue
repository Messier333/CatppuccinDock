<script setup>
import { GripVertical } from 'lucide-vue-next';
import ThemeSelect from '../common/ThemeSelect.vue';
import { reorderDirective } from '../../directives/reorder.js';
import { metricLabels, sectionLabels, columnLabels } from '../../lib/proxmox.js';
const model = defineModel({ required: true });
const props = defineProps({ bookmarks: { type: Array, default: () => [] }, showBindings: Boolean, disabled: Boolean });
function reorder(_kind, _parent, ids) {
  const byId = new Map(model.value.sections.map(section => [section.id, section]));
  model.value.sections = ids.map(id => byId.get(id));
}
function move(id, offset) {
  const ids = model.value.sections.map(section => section.id), index = ids.indexOf(id), next = index + offset;
  if (next < 0 || next >= ids.length) return;
  [ids[index], ids[next]] = [ids[next], ids[index]]; reorder('', '', ids);
}
const vReorder = reorderDirective(reorder);
</script>
<template>
  <fieldset class="pve-fieldset" :disabled="disabled">
    <legend>북마크 오른쪽 요약 정보</legend>
    <div class="pve-checks"><label v-for="(label,key) in metricLabels" :key="key"><input v-model="model.metrics" type="checkbox" :value="key" :disabled="!model.metrics.includes(key) && model.metrics.length >= 3" />{{ label }}</label></div>
    <p class="settings-description">최대 3개를 표시합니다. 모두 해제하면 상세 보기 버튼만 표시합니다.</p>
  </fieldset>
  <fieldset v-if="showBindings" class="pve-fieldset" :disabled="disabled"><legend>연결할 내 북마크</legend>
    <div class="pve-bookmark-choices"><label v-for="bookmark in bookmarks" :key="bookmark.id"><input v-model="model.bookmark_ids" type="checkbox" :value="bookmark.id" />{{ bookmark.name }}<small>{{ bookmark.category }}</small></label><p v-if="!bookmarks.length" class="settings-description">내 북마크에서 링크를 추가한 뒤 연결할 수 있습니다.</p></div>
  </fieldset>
  <fieldset class="pve-fieldset" :disabled="disabled"><legend>상세 패널 구성</legend>
    <p class="settings-description">손잡이를 드래그하거나 위아래 방향키로 이동합니다. 항목 표시와 너비도 바꿀 수 있습니다.</p>
    <div v-reorder="{ kind: 'pve-sections', disabled: props.disabled }" class="pve-layout-list">
      <div v-for="section in model.sections" :key="section.id" :data-sort-id="section.id" class="pve-layout-row"><button type="button" class="reorder-handle icon-button" :aria-label="`${sectionLabels[section.id]} 순서 변경 · 위아래 방향키`" @keydown.up.prevent.stop="move(section.id, -1)" @keydown.down.prevent.stop="move(section.id, 1)"><GripVertical :size="16" /></button><label><input v-model="section.visible" type="checkbox" />{{ sectionLabels[section.id] }}</label><ThemeSelect v-model="section.width" :label="`${sectionLabels[section.id]} 너비`" :disabled="disabled" :options="[{value:'full',label:'전체 너비'}, {value:'half',label:'절반 너비'}]" /></div>
    </div>
  </fieldset>
  <fieldset class="pve-fieldset" :disabled="disabled"><legend>VM·컨테이너 목록 열</legend><div class="pve-checks"><label v-for="(label,key) in columnLabels" :key="key"><input v-model="model.columns" type="checkbox" :value="key" />{{ label }}</label></div></fieldset>
</template>
