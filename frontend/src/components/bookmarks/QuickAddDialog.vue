<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { X, RefreshCw } from 'lucide-vue-next';
import ThemeSelect from '../common/ThemeSelect.vue';
import IconPicker from './IconPicker.vue';
import { api } from '../../lib/api.js';
const props = defineProps({ portal:Object, activeTab:String });
const emit = defineEmits(['saved','close']);
const dialog = ref(null), urlInput = ref(null), tabId = ref(''), busy = ref(false), previewing = ref(false), error = ref(''), notice = ref(''), open = ref(false);
const iconBusy = ref(false);
const draft = reactive({url:'',name:'',icon:'world',category_id:''});
const categories = computed(() => props.portal.tabs.find(tab => tab.id === tabId.value)?.categories || []);
let timer, request, generation = 0, guessedName = '', guessedIcon = 'world';
watch(tabId, () => { draft.category_id = categories.value[0]?.id || ''; });
function show() {
  Object.assign(draft,{url:'',name:'',icon:'world',category_id:''}); guessedName = ''; guessedIcon = 'world';
  tabId.value = props.activeTab || props.portal.tabs[0]?.id || ''; draft.category_id = categories.value[0]?.id || '';
  error.value = ''; notice.value = ''; open.value = true; dialog.value.showModal(); nextTick(() => urlInput.value.focus());
}
function close() { if (busy.value || iconBusy.value) return; open.value = false; clearTimeout(timer); request?.abort(); generation++; previewing.value = false; dialog.value.close(); emit('close'); }
function normalizedUrl() { const value = draft.url.trim(); return /^https?:\/\//i.test(value) ? value : 'https://' + value; }
async function preview() {
  clearTimeout(timer); request?.abort(); const version = ++generation;
  if (!draft.url.trim() || !open.value) return;
  let url;
  try { url = new URL(normalizedUrl()); if (!url.hostname || !['https:','http:'].includes(url.protocol)) return; } catch { return; }
  request = new AbortController(); previewing.value = true; error.value = ''; notice.value = '';
  try {
    const result = await api('bookmark-tools/preview', {method:'POST',body:JSON.stringify({url:url.href}),signal:request.signal});
    if (version !== generation || !open.value) return;
    if (!draft.name || draft.name === guessedName) draft.name = result.name;
    if (draft.icon === guessedIcon) draft.icon = result.icon;
    guessedName = result.name; guessedIcon = result.icon; notice.value = result.notice;
  } catch (cause) { if (version === generation && cause.name !== 'AbortError') notice.value = '자동으로 불러오지 못했어요. 이름과 아이콘을 직접 지정할 수 있습니다.'; }
  finally { if (version === generation) previewing.value = false; }
}
watch(() => draft.url, () => { clearTimeout(timer); request?.abort(); generation++; previewing.value = false; if (open.value && draft.url.trim()) timer = setTimeout(preview,650); });
async function save() {
  if (busy.value || iconBusy.value) return;
  busy.value = true; error.value = '';
  try {
    const category = categories.value.find(item => item.id === draft.category_id);
    const result = await api('bookmarks',{method:'POST',body:JSON.stringify({...draft,url:normalizedUrl(),position:Math.min(10000,Math.max(-1,...(category?.links || []).map(item => item.position))+1)})});
    busy.value = false; close(); emit('saved',result);
  } catch (cause) { error.value = cause.message; } finally { busy.value = false; }
}
onBeforeUnmount(() => { clearTimeout(timer); request?.abort(); generation++; dialog.value?.close(); });
defineExpose({open:show});
</script>
<template><dialog ref="dialog" v-dialog-dismiss="busy || iconBusy" class="quick-add-dialog editor-dialog" aria-label="북마크 빠른 추가" @cancel.prevent="close"><form class="settings-form" @submit.prevent="save"><div class="card-heading"><h2>북마크 빠른 추가</h2><button class="icon-button" type="button" aria-label="빠른 추가 닫기" :disabled="busy || iconBusy" @click="close"><X :size="18" /></button></div>
<label>북마크 URL<input ref="urlInput" v-model="draft.url" required maxlength="2048" placeholder="https://example.com" autocomplete="url" /></label><button class="secondary-button" type="button" :disabled="previewing || !draft.url" @click="preview"><RefreshCw :size="14" :class="{'widget-spinning':previewing}" />{{ previewing ? '제목·아이콘 불러오는 중…' : '제목·아이콘 다시 불러오기' }}</button>
<p v-if="notice" class="settings-description" role="status">{{ notice }}</p><label>북마크 이름<input v-model="draft.name" required maxlength="120" /></label>
<label>추가할 탭<ThemeSelect v-model="tabId" label="빠른 추가 탭" :options="portal.tabs.map(tab => ({value:tab.id,label:tab.name}))" /></label><label>추가할 카테고리<ThemeSelect v-model="draft.category_id" label="빠른 추가 카테고리" :disabled="!categories.length" required :options="categories.map(category => ({value:category.id,label:category.name}))" /></label><p v-if="!categories.length" class="settings-description">설정의 내 북마크에서 카테고리를 먼저 추가해 주세요.</p>
<IconPicker v-model="draft.icon" :search-term="draft.name" :disabled="busy" @busy="iconBusy = $event" /><p v-if="error" class="form-error" role="alert">{{ error }}</p><button class="primary-button" :disabled="busy || iconBusy || !draft.category_id">{{ busy ? '저장 중…' : '북마크 저장' }}</button></form></dialog></template>
