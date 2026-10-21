<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Search, Download, ExternalLink } from 'lucide-vue-next';
import ThemeSelect from '../common/ThemeSelect.vue';
import { api } from '../../lib/api.js';

const props = defineProps({ disabled: Boolean, allowImport: { type:Boolean, default:true } });
const emit = defineEmits(['select', 'busy', 'settled']);
const provider = ref('all'), query = ref('pixel art'), results = ref([]), page = ref(0), more = ref(false), unavailable=ref([]);
const searching = ref(false), importing = ref(''), searched = ref(false), error = ref('');
let timer, generation = 0, searchController, importController, composing = false;
const providers = ref([{value:'all',label:'통합 검색'},{value:'gifdb',label:'GIFDB'},{ value: 'alphacoders', label: 'Alpha Coders' }, { value: 'motionbgs', label: 'MotionBgs' }, { value: 'commons', label: 'Wikimedia Commons' }, { value: 'openverse', label: 'Openverse' }]);
const webSearch=computed(()=>`https://giphy.com/search/${encodeURIComponent(query.value.trim())}`);
const itemKey=item=>`${item.source.provider}:${item.id}`;
const themes = [{label:'픽셀 아트',q:'pixel art'},{label:'도시 야경',q:'city'},{label:'자연 풍경',q:'nature'},{label:'숲',q:'forest'},{label:'바다',q:'ocean'},{label:'비 오는 풍경',q:'rain'},{label:'애니 풍경',q:'anime landscape'},{label:'노을',q:'sunset'}];

function reset() {
  clearTimeout(timer); generation++; searchController?.abort();
  results.value = []; page.value = 0; more.value = false; searched.value = false; searching.value = false; error.value = '';
}
function schedule() {
  reset();
  if (query.value.trim() && !composing) timer = setTimeout(() => search(), 650);
}
watch([query, provider], schedule, { flush: 'sync' });
function enter(event) {
  if (event.isComposing || event.keyCode === 229) return;
  event.preventDefault(); search();
}
async function search(append = false) {
  clearTimeout(timer);
  if (props.disabled || importing.value || !query.value.trim() || composing) return;
  searchController?.abort(); searchController = new AbortController();
  const current = ++generation, nextPage = append ? page.value + 1 : 1;
  searching.value = true; error.value = '';
  if (!append) { results.value = []; more.value = false; }
  try {
    const params = new URLSearchParams({ provider: provider.value, q: query.value.trim(), page: String(nextPage) });
    const result = await api(`backgrounds/search?${params}`, { signal: searchController.signal });
    if (current !== generation) return;
    results.value = append ? [...new Map([...results.value, ...result.items].map(item => [itemKey(item), item])).values()] : result.items;
    unavailable.value=result.unavailable||[];
    page.value = nextPage; more.value = result.has_more; searched.value = true;
  } catch (cause) {
    if (current === generation && cause.name !== 'AbortError') error.value = cause.message;
  } finally { if (current === generation) searching.value = false; }
}
async function choose(item) {
  if (props.disabled || importing.value || !props.allowImport) return;
  clearTimeout(timer); searchController?.abort(); generation++; searching.value = false;
  importing.value = itemKey(item); emit('busy', true); error.value = ''; importController = new AbortController();
  try {
    const image = await api('backgrounds/import', { method: 'POST', body: JSON.stringify({ provider: item.source.provider, item_id: item.id }), signal: importController.signal });
    emit('select', image);
  } catch (cause) { if (cause.name !== 'AbortError') error.value = cause.message; }
  finally { importing.value = ''; emit('busy', false); emit('settled'); }
}
onBeforeUnmount(() => { clearTimeout(timer); generation++; searchController?.abort(); importController?.abort(); emit('busy', false); });
onMounted(async()=>{try{const result=await api('backgrounds/providers');if(Array.isArray(result.items))providers.value=result.items;}catch{/* Keep sources that do not require keys. */}search();});
</script>

<template>
  <section class="gif-search" aria-label="GIF 검색">
    <label>GIF 제공처<ThemeSelect v-model="provider" label="GIF 제공처" :options="providers" :disabled="disabled || !!importing" /></label>
    <label>GIF 검색<div class="gif-search-input"><input v-model="query" type="search" aria-label="GIF 검색어" placeholder="ocean, forest, rain…" maxlength="80" :disabled="disabled || !!importing" @keydown.enter="enter" @compositionstart="composing = true" @compositionend="composing = false; schedule()" /><button type="button" class="secondary-button" aria-label="GIF 검색 실행" :disabled="disabled || !!importing || !query.trim()" @click="search()"><Search :size="16" /></button></div></label>
    <div class="gif-themes" aria-label="GIF 주제"><button v-for="theme in themes" :key="theme.q" type="button" :class="{active:query===theme.q}" :disabled="disabled || !!importing" @click="query=theme.q">{{ theme.label }}</button></div>
    <p v-if="provider==='motionbgs'" class="settings-description">MotionBgs는 주제별 GIF 목록을 검색합니다. 도시·자연·숲·비 등의 주제로 찾아보세요.</p>
    <p v-if="provider==='pixabay'" class="settings-description">영상의 처음 20초를 GIF로 변환해 저장합니다.</p>
    <a class="secondary-button" :href="webSearch" target="_blank" rel="noopener noreferrer">GIPHY에서 더 찾기 <ExternalLink :size="13" /></a>
    <p class="settings-description">원본은 최대 100MB까지 가져오며, 큰 GIF는 자동으로 크기를 줄여 서버에 보관합니다. 저장 후에는 원본 사이트에 접속하지 않고 표시합니다.</p>
    <p v-if="searching" class="settings-description" role="status">GIF 검색 중…</p>
    <p v-if="importing" class="settings-description" role="status"><Download :size="14" /> GIF를 다운로드·최적화하는 중…</p>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <p v-if="unavailable.length && !searching" class="settings-description">{{unavailable.join(' · ')}} 응답이 늦어 나머지 제공처의 결과를 표시합니다.</p>
    <div v-if="results.length" class="gif-search-grid">
      <article v-for="item in results" :key="itemKey(item)" class="gif-result">
        <button type="button" :aria-label="`${item.title || '제목 없음'} GIF 선택`" :disabled="disabled || !!importing || !allowImport" @click="choose(item)"><img v-if="!item.preview_failed" :src="item.preview_url" :alt="item.title" loading="lazy" referrerpolicy="no-referrer" @error="item.preview_failed = true" /><span v-else class="gif-preview-empty">미리보기 없음</span><strong>{{ importing === itemKey(item) ? '저장 중…' : item.title || '제목 없음' }}</strong></button>
        <small>{{ providers.find(provider=>provider.value===item.source.provider)?.label }}<template v-if="item.source.author"> · {{ item.source.author }}</template><template v-if="item.media_type==='video'"> · 영상 → GIF</template></small>
        <a :href="item.source.page_url" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ item.source.license || '출처 보기' }} <ExternalLink :size="11" /></a>
      </article>
    </div>
    <p v-else-if="searched && !searching && !error" class="settings-description">검색 결과가 없습니다. 다른 검색어나 제공처를 선택하세요.</p>
    <p v-else-if="!searching && !error" class="settings-description">검색어를 입력하면 GIF를 찾아볼 수 있어요. 영어 검색어도 사용해 보세요.</p>
    <button v-if="more" type="button" class="secondary-button" :disabled="disabled || searching || !!importing" @click="search(true)">더 보기</button>
  </section>
</template>
