<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { api } from '../../lib/api.js';
import ThemeSelect from '../common/ThemeSelect.vue';
const emit = defineEmits(['saved']);
const dialog = ref(null), tabs = ref([]), monitors = ref([]), selected = ref([]);
const selectedBookmarks = ref({});
const tabId = ref(''), categoryId = ref(''), query = ref(''), busy = ref(false), loading = ref(false), error = ref('');
const options = reactive({ interval: 300, allow_private: false });
const urlKey = value => { try { return new URL(value).href; } catch { return value; } };
const registered = computed(() => new Map(monitors.value.map(row => [urlKey(row.link_url), row])));
const capacity = computed(() => Math.min(200, Math.max(0, 1000 - monitors.value.length)));
const categories = computed(() => tabs.value.find(tab => tab.id === tabId.value)?.categories || []);
watch(tabId, () => { categoryId.value = ''; });
const entries = computed(() => {
  const byUrl = new Map();
  for (const tab of tabs.value) for (const category of tab.categories) for (const link of category.links) {
    const url = urlKey(link.url), path = `${tab.name} / ${category.name}`;
    if (!byUrl.has(url)) byUrl.set(url, { id: url, bookmarkId: link.id, name: link.name, url, locations: [], names: [] });
    const item = byUrl.get(url);
    item.locations.push({ tabId: tab.id, categoryId: category.id, path, name: link.name, bookmarkId: link.id });
    item.names.push(link.name);
  }
  return [...byUrl.values()];
});
const visible = computed(() => {
  const term = query.value.trim().toLocaleLowerCase();
  const matches = location => (!tabId.value || location.tabId === tabId.value) && (!categoryId.value || location.categoryId === categoryId.value);
  return entries.value.filter(item => item.locations.some(matches))
    .map(item => { const location = item.locations.find(matches); return { ...item, name: location.name, bookmarkId: location.bookmarkId }; })
    .filter(item => !term || `${item.names.join(' ')} ${item.url} ${item.locations.map(location => location.path).join(' ')}`.toLocaleLowerCase().includes(term));
});
const available = computed(() => visible.value.filter(item => !registered.value.has(item.url)));
const allSelected = computed(() => available.value.length > 0 && available.value.every(item => selected.value.includes(item.id)));
function choose(id, checked) {
  error.value = '';
  if (checked && selected.value.length >= capacity.value) { error.value = `최대 ${capacity.value}개를 추가할 수 있어요.`; return; }
  if (checked) selectedBookmarks.value[id] = visible.value.find(item => item.id === id).bookmarkId;
  selected.value = checked ? [...new Set([...selected.value, id])] : selected.value.filter(value => value !== id);
}
function selectVisible() {
  const ids = new Set(available.value.map(item => item.id));
  if (allSelected.value) selected.value = selected.value.filter(id => !ids.has(id));
  else {
    for (const item of available.value) if (!selected.value.includes(item.id)) selectedBookmarks.value[item.id] = item.bookmarkId;
    selected.value = [...new Set([...selected.value, ...ids])].slice(0, capacity.value);
  }
}
async function open() {
  selected.value = []; selectedBookmarks.value = {}; query.value = ''; tabId.value = ''; categoryId.value = ''; error.value = '';
  options.interval = 300; options.allow_private = false;
  loading.value = true; dialog.value.showModal();
  try { const [portal, configured] = await Promise.all([api('portal'), api('admin/monitors')]); tabs.value = portal.tabs; monitors.value = configured; }
  catch (cause) { error.value = cause.message; }
  finally { loading.value = false; }
}
async function save() {
  if (busy.value || !selected.value.length) return;
  busy.value = true; error.value = '';
  try {
    const result = await api('admin/monitors/bulk', { method: 'POST', body: JSON.stringify({ bookmark_ids: selected.value.map(id => selectedBookmarks.value[id]), interval: Number(options.interval), allow_private: options.allow_private }) });
    dialog.value.close(); emit('saved', result);
  } catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
}
defineExpose({ open });
</script>
<template><dialog ref="dialog" v-dialog-dismiss="busy" class="editor-dialog monitor-bulk-dialog" aria-label="북마크 상태 확인 일괄 등록" @cancel="busy && $event.preventDefault()"><form class="settings-form" @submit.prevent="save">
  <div class="card-heading"><h2>북마크 상태 확인 일괄 등록</h2><button type="button" class="icon-button" aria-label="닫기" :disabled="busy" @click="dialog.close()">×</button></div>
  <p class="settings-description">선택한 북마크의 URL을 상태 확인 주소로 사용합니다. 같은 주소는 하나만 등록하며, 기존 대상의 확인 주소·설정은 유지합니다. 개별 상태 확인 주소는 등록 후 수정할 수 있습니다.</p>
  <p v-if="loading" class="settings-description" role="status">북마크를 불러오는 중…</p>
  <template v-else>
    <div class="monitor-bulk-filters"><label>탭<ThemeSelect v-model="tabId" label="일괄 등록 탭" :disabled="busy" :options="[{ value: '', label: '모든 탭' }, ...tabs.map(tab => ({ value: tab.id, label: tab.name }))]" /></label><label>카테고리<ThemeSelect v-model="categoryId" label="일괄 등록 카테고리" :disabled="busy || !tabId" :options="[{ value: '', label: '모든 카테고리' }, ...categories.map(category => ({ value: category.id, label: category.name }))]" /></label></div>
    <label>북마크 검색<input v-model="query" type="search" :disabled="busy" placeholder="이름·주소·카테고리 검색" /></label>
    <div class="card-heading monitor-bulk-selection"><span>선택 {{ selected.length }}개 · 이번에 최대 {{ capacity }}개 · 등록 {{ monitors.length }}/1000개</span><button type="button" class="secondary-button" :disabled="busy || !available.length || (!allSelected && selected.length >= capacity)" @click="selectVisible">{{ allSelected ? '검색 결과 선택 해제' : '검색 결과 전체 선택' }}</button></div>
    <div class="import-entry-list monitor-bulk-list"><label v-for="item in visible" :key="item.id" class="import-entry"><input type="checkbox" :aria-label="item.name + ' 상태 확인 선택'" :checked="selected.includes(item.id)" :disabled="busy || registered.has(item.url) || (!selected.includes(item.id) && selected.length >= capacity)" @change="choose(item.id, $event.target.checked)" /><span><strong>{{ item.name }}</strong><small>{{ item.url }}</small><small>{{ [...new Set(item.locations.map(location => location.path))].join(' · ') }}</small></span><small v-if="registered.has(item.url)" class="monitor-registered">{{ registered.get(item.url).enabled ? '등록됨' : '등록됨 · 확인 중지' }}</small></label><p v-if="!visible.length" class="settings-empty">조건에 맞는 북마크가 없습니다.</p></div>
    <div class="monitor-bulk-filters"><label>공통 확인 간격 (초)<input v-model="options.interval" type="number" min="60" max="86400" required :disabled="busy" /></label><label class="checkbox-label"><input v-model="options.allow_private" type="checkbox" :disabled="busy" />내부 네트워크 주소 확인 허용</label></div>
    <p class="settings-description">등록하면 상태 확인을 활성화하고 메인 화면에 보일 때 확인합니다. 확인 간격 이내의 결과는 재사용합니다. 필터를 바꿔도 선택은 유지됩니다. 기존에 중지한 대상은 목록에서 개별 수정해 활성화하세요.</p>
  </template>
  <p v-if="error" class="form-error" role="alert">{{ error }}</p><button class="primary-button" :disabled="busy || loading || !selected.length">{{ busy ? '등록 중…' : `선택한 ${selected.length}개 상태 확인 등록` }}</button>
</form></dialog></template>
