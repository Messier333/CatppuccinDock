<script setup>
import ThemeSelect from "../common/ThemeSelect.vue";
import { computed, onUnmounted, ref, watch } from "vue";
import { api } from "../../lib/api.js";
import { icons } from "../../lib/icons.js";
import BookmarkIcon from "../common/BookmarkIcon.vue";
import UploadedIconPicker from './UploadedIconPicker.vue';
import { Upload } from 'lucide-vue-next';
const model = defineModel({ type: String, default: 'world' });
const props = defineProps({ color: { type: String, default: 'var(--green)' }, searchTerm: { type: String, default: '' }, disabled: Boolean });
const emit = defineEmits(['busy']);
const assetBusy = ref(false), uploadedName = ref(''), uploadVersion = ref(0);
const currentLabel = computed(() => model.value.startsWith('upload:') ? uploadedName.value || '업로드한 아이콘' : model.value);
function assetState(value) { assetBusy.value = value; emit('busy', value); }
function chooseUpload(item) { uploadedName.value = item.name || ''; model.value = item.icon; }
async function showUploads() {
  if (assetBusy.value || props.disabled) return;
  if (open.value && collection.value === 'uploaded') { open.value = false; return; }
  uploadVersion.value++;
  collection.value = 'uploaded'; open.value = true; error.value = '';
  try { if (!collections.value.length) collections.value = await api('icons/collections'); }
  catch { /* Uploading does not depend on the bundled search collections. */ }
}
const open = ref(false);
const collections = ref([]);
const collection = ref('tabler');
const query = ref('');
const results = ref([]);
const total = ref(0);
const more = ref(false);
const busy = ref(false);
const error = ref('');
let timer, generation = 0;
const license = computed(() => collections.value.find(item => item.id === collection.value)?.license);
async function load(append = false) {
  const current = ++generation;
  busy.value = true; error.value = '';
  try {
    if (collection.value === 'uploaded') { results.value = []; more.value = false; return; }
    if (collection.value === 'local') {
      const names = [...new Set(['world', ...Object.keys(icons)])].sort().filter(name => name.includes(query.value.trim().toLowerCase()));
      results.value = names; total.value = names.length; more.value = false;
    } else {
      const params = new URLSearchParams({ collection: collection.value, q: query.value.trim(), offset: String(append ? results.value.length : 0) });
      const data = await api('icons?'+params);
      if (current !== generation) return;
      results.value = append ? [...results.value, ...data.icons] : data.icons;
      total.value = data.total; more.value = data.has_more;
    }
  } catch (cause) { if (current === generation) error.value = cause.message; }
  finally { if (current === generation) busy.value = false; }
}
async function toggle() {
  if (assetBusy.value || props.disabled) return;
  if (collection.value === 'uploaded') { collection.value = 'tabler'; open.value = true; }
  else open.value = !open.value;
  if (!open.value) return;
  query.value = props.searchTerm.trim().slice(0, 80);
  try {
    if (!collections.value.length) collections.value = await api('icons/collections');
    if (!open.value) return;
    clearTimeout(timer);
    await load();
  } catch (cause) { error.value = cause.message; }
}
watch([query, collection], () => {
  clearTimeout(timer); generation++; results.value = []; more.value = false;
  if (open.value) timer = setTimeout(() => load(), 250);
}, { flush: 'sync' });
onUnmounted(() => { clearTimeout(timer); generation++; emit('busy', false); });
function choose(name) { model.value = name; open.value = false; }
</script>
<template><div class="icon-picker"><span class="field-label">아이콘</span><div class="inline-actions icon-picker-actions"><button class="secondary-button icon-picker-current" type="button" :aria-expanded="open && collection !== 'uploaded'" :disabled="assetBusy || props.disabled" @click="toggle"><BookmarkIcon :name="model" :style="{ color: props.color }" /><span>{{ currentLabel }}</span><span>아이콘 검색·선택</span></button><button type="button" class="secondary-button" :aria-expanded="open && collection === 'uploaded'" :disabled="assetBusy || props.disabled" @click="showUploads"><Upload :size="14" />내 아이콘·업로드</button></div>
  <div v-if="open" class="icon-picker-panel"><label>아이콘 컬렉션<ThemeSelect v-model="collection" label="아이콘 컬렉션" :disabled="assetBusy || props.disabled" :options="[{ value: 'uploaded', label: '내 업로드 아이콘' }, { value: 'local', label: '기존 아이콘' }, ...collections.map(item => ({ value: item.id, label: `${item.name} (${item.total.toLocaleString()})` }))]" /></label>
    <UploadedIconPicker v-if="collection === 'uploaded'" :key="uploadVersion" :selected="model" :disabled="props.disabled" @busy="assetState" @select="chooseUpload" />
    <template v-else>
    <label>아이콘 검색<input v-model="query" type="search" aria-label="아이콘 검색" placeholder="docker, server, home, 서버…" maxlength="80" /></label>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p><p class="settings-description">{{ busy ? '검색 중…' : `${total.toLocaleString()}개 아이콘` }}</p>
    <div class="icon-picker-grid"><button v-for="name in results" :key="name" type="button" class="icon-choice" :class="{ selected: name === model }" :aria-label="`아이콘 ${name}`" :aria-pressed="name === model" :title="name" @click="choose(name)"><BookmarkIcon :name="name" :style="{ color: props.color }" /><small>{{ name.split(':').pop() }}</small></button></div>
    <button v-if="more" class="secondary-button" type="button" :disabled="busy" @click="load(true)">더 보기</button><p v-if="!busy && !results.length && !error" class="settings-description">검색 결과가 없습니다. 다른 단어나 컬렉션을 선택하세요.</p>
    <p class="settings-description">Iconify 제공 · 서버에서 제공하는 아이콘 목록<span v-if="license"> · <a :href="license.url" target="_blank" rel="noopener noreferrer">{{ license.title }}</a></span></p>
    </template>
  </div>
</div></template>
<style scoped>
.icon-picker-actions > .icon-picker-current { flex: 1 1 200px; width: auto; min-width: 0; }
</style>
