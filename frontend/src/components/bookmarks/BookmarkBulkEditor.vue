<script setup>
import { computed, ref, watch } from 'vue';
import { api } from '../../lib/api.js';
import ThemeSelect from '../common/ThemeSelect.vue';
import IconPicker from './IconPicker.vue';
import IconColorPicker from './IconColorPicker.vue';
const props = defineProps({portal:Object});
const emit = defineEmits(['changed']);
const query = ref(''), tab = ref(''), category = ref(''), selected = ref([]), action = ref('move'), destinationTab = ref(''), destination = ref(''), icon = ref('world'), color = ref('auto'), busy = ref(false), error = ref(''), notice = ref(''), undoId = ref(''), groups = ref(null), duplicateOnly = ref(false), limit = ref(60);
const iconBusy = ref(false);
const all = computed(() => props.portal.tabs.flatMap(tab => tab.categories.flatMap(category => category.links.map(link => ({...link,tabId:tab.id,location:`${tab.name} / ${category.name}`})))));
const categories = computed(() => props.portal.tabs.find(item => item.id === tab.value)?.categories || []);
const destinations = computed(() => props.portal.tabs.find(item => item.id === destinationTab.value)?.categories || []);
const duplicateIds = computed(() => new Set((groups.value || []).flatMap(group => group.bookmarks.map(link => link.id))));
const visible = computed(() => all.value.filter(link => (!tab.value || link.tabId === tab.value) && (!category.value || link.category_id === category.value) && (!duplicateOnly.value || duplicateIds.value.has(link.id)) && `${link.name} ${link.url} ${link.location}`.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())));
const allSelected = computed(() => visible.value.length>0 && visible.value.every(link => selected.value.includes(link.id)));
watch(tab, () => { category.value = ''; limit.value = 60; });
watch(destinationTab, () => { destination.value = ''; });
watch([query,category,duplicateOnly], () => { limit.value = 60; });
watch(() => props.portal, () => { selected.value = selected.value.filter(id => all.value.some(link => link.id === id)); groups.value = null; duplicateOnly.value = false; });
function selectVisible() {
  if (allSelected.value) { const ids = new Set(visible.value.map(link => link.id)); selected.value = selected.value.filter(id => !ids.has(id)); }
  else selected.value = [...new Set([...selected.value,...visible.value.map(link => link.id)])].slice(0,500);
}
async function findDuplicates() {
  busy.value = true; error.value = ''; notice.value = '';
  try { groups.value = await api('bookmark-tools/duplicates'); duplicateOnly.value = true; query.value = ''; tab.value = ''; category.value = ''; selected.value = groups.value.flatMap(group => group.bookmarks.slice(1).map(link => link.id)).slice(0,500); notice.value = `중복 주소 ${groups.value.length}개를 찾았어요. 주소마다 첫 항목을 남기고 나머지를 선택했습니다. 선택을 확인한 뒤 작업을 적용하세요.`; }
  catch (cause) { error.value = cause.message; } finally { busy.value = false; }
}
async function apply() {
  if (busy.value || iconBusy.value) return;
  if (action.value === 'delete' && !window.confirm(`선택한 북마크 ${selected.value.length}개를 휴지통으로 이동할까요?`)) return;
  busy.value = true; error.value = ''; notice.value = '';
  try {
    const result = await api('bookmark-tools/bulk',{method:'POST',body:JSON.stringify({ids:selected.value,action:action.value,...(action.value==='move'?{category_id:destination.value}:action.value==='icon'?{icon:icon.value,icon_color:color.value}:{})})});
    undoId.value = result.undo_id; selected.value = []; notice.value = `${result.changed}개 북마크를 ${action.value==='move'?'이동했어요.':action.value==='icon'?'변경했어요.':'휴지통으로 이동했어요.'}`; emit('changed');
  } catch (cause) { error.value = cause.message; } finally { busy.value = false; }
}
async function undo() {
  busy.value = true; error.value = '';
  try { await api(`trash/${undoId.value}/restore`,{method:'POST'}); undoId.value = ''; notice.value = '일괄 작업을 되돌렸어요.'; emit('changed'); }
  catch (cause) { error.value = cause.message; } finally { busy.value = false; }
}
</script>
<template><details class="settings-card bulk-bookmark-editor" data-settings-anchor="bulk"><summary>여러 북마크 편집 · 중복 URL 정리</summary><p class="settings-description">탭·카테고리·검색으로 선택한 북마크를 한 번에 최대 500개까지 편집합니다. 공개 링크도 내 배치의 이름·아이콘·위치만 변경됩니다.</p><p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="notice" class="form-notice" role="status">{{ notice }} <button v-if="undoId" class="secondary-button" :disabled="busy" @click="undo">일괄 작업 실행 취소</button></p>
<div class="bulk-filter-grid settings-form"><label>편집할 탭<ThemeSelect v-model="tab" label="일괄 편집 탭" :options="[{value:'',label:'모든 탭'},...portal.tabs.map(item => ({value:item.id,label:item.name}))]" /></label><label>편집할 카테고리<ThemeSelect v-model="category" label="일괄 편집 카테고리" :disabled="!tab" :options="[{value:'',label:tab?'모든 카테고리':'탭을 먼저 선택하세요'},...categories.map(item => ({value:item.id,label:item.name}))]" /></label><label>북마크 검색<input v-model="query" type="search" maxlength="120" /></label><button class="secondary-button" :disabled="busy" @click="findDuplicates">중복 URL 찾기</button></div>
<label v-if="groups" class="checkbox-label bulk-duplicate-toggle"><input v-model="duplicateOnly" type="checkbox" />중복 주소만 표시</label><div class="card-heading bulk-selection-heading"><span>{{ selected.length }}개 선택 · 검색 결과 {{ visible.length }}개</span><div class="inline-actions"><button class="secondary-button" :disabled="busy || !visible.length" @click="selectVisible">{{ allSelected?'검색 결과 선택 해제':'검색 결과 전체 선택' }}</button><button class="secondary-button" :disabled="busy || iconBusy || !selected.length" @click="selected=[]">모두 선택 해제</button></div></div>
<div class="bulk-bookmark-list"><label v-for="link in visible.slice(0,limit)" :key="link.id" class="import-entry"><input v-model="selected" type="checkbox" :value="link.id" :disabled="busy || (!selected.includes(link.id) && selected.length>=500)" :aria-label="`${link.name} 일괄 편집 선택`" /><span><strong>{{ link.name }}</strong><small>{{ link.location }} · {{ link.url }}</small></span><small v-if="link.favorite">즐겨찾기</small></label><p v-if="!visible.length" class="settings-empty">선택할 북마크가 없습니다.</p></div><button v-if="visible.length>limit" class="secondary-button" @click="limit+=60">목록 더 보기</button>
<div class="settings-form"><label>일괄 작업<ThemeSelect v-model="action" label="일괄 작업" :disabled="busy" :options="[{value:'move',label:'카테고리 이동'},{value:'icon',label:'아이콘·색상 변경'},{value:'delete',label:'휴지통으로 이동'}]" /></label><template v-if="action==='move'"><label>이동할 탭<ThemeSelect v-model="destinationTab" label="일괄 이동할 탭" :options="portal.tabs.map(item => ({value:item.id,label:item.name}))" /></label><label>이동할 카테고리<ThemeSelect v-model="destination" label="일괄 이동할 카테고리" :disabled="!destinationTab" :options="destinations.map(item => ({value:item.id,label:item.name}))" /></label></template><template v-if="action==='icon'"><IconPicker v-model="icon" :disabled="busy" @busy="iconBusy = $event" /><IconColorPicker v-if="!icon.startsWith('upload:')" v-model="color" /></template><button class="primary-button" :disabled="busy || iconBusy || !selected.length || (action==='move' && !destination)" @click="apply">선택한 {{ selected.length }}개에 적용</button></div></details></template>
