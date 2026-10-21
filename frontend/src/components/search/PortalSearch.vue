<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ArrowUpRight, Globe2, Search, X } from "lucide-vue-next";
import BookmarkIcon from "../common/BookmarkIcon.vue";
import { api } from "../../lib/api.js";
import { findBookmarks, isUrl, parseQuery, suggestionProvider, webUrl } from "../../lib/search.js";
import { recordBookmarkVisit } from "../../lib/bookmarkActivity.js";
const props = defineProps({ portal: { type: Object, required: true } });
const emit = defineEmits(['close']);
const dialog = ref(null), input = ref(null), query = ref(''), active = ref(-1), limit = ref(8), suggestions = ref([]);
const composing = ref(false);
function updateQuery(event) { query.value = event.target.value; }
function finishComposition(event) { composing.value = false; updateQuery(event); }
const engines = props.portal.search.engines;
const webTarget = computed(() => props.portal.search.openMode === 'new_tab' ? '_blank' : '_self');
const parsed = computed(() => parseQuery(query.value, engines, props.portal.search.default || 'd'));
const provider = computed(() => suggestionProvider(parsed.value.engine));
const matches = computed(() => findBookmarks(props.portal.tabs, parsed.value.query));
const bookmarks = computed(() => matches.value.slice(0, limit.value));
const validQuery = computed(() => !!parsed.value.query);
const directUrl = computed(() => !parsed.value.explicit && isUrl(parsed.value.query) ? (/^https?:\/\//i.test(parsed.value.query) ? parsed.value.query : 'https://'+parsed.value.query) : '');
const actions = computed(() => [
  ...bookmarks.value.map(item => ({ type: 'bookmark', key: item.id, url: item.url, ...item })),
  ...(validQuery.value ? [{ type: 'web', key: 'web', url: directUrl.value || webUrl(engines, parsed.value.engine, parsed.value.query) }] : []),
  ...suggestions.value.map((text,index) => ({ type: 'suggestion', key: `suggestion-${index}`, text, url: webUrl(engines, provider.value, text) })),
]);
const webIndex = computed(() => bookmarks.value.length);
const firstSuggestionIndex = computed(() => bookmarks.value.length + (validQuery.value ? 1 : 0));
let timer, request, generation = 0;
const opener = document.activeElement;
onMounted(async () => { dialog.value.showModal(); await nextTick(); input.value.focus(); });
onBeforeUnmount(() => { clearTimeout(timer); request?.abort(); generation++; dialog.value?.close(); opener?.focus(); });
function close() { emit('close'); }
// eslint-disable-next-line no-control-regex -- Control characters must never be sent to suggestion providers.
function canComplete(text) { return text.length >= 2 && text.length <= 120 && !/[./:@?#\\\x00-\x1f]/.test(text) && !text.toLowerCase().startsWith('localhost'); }
watch([query, provider], () => {
  active.value = -1; limit.value = 8; suggestions.value = [];
  clearTimeout(timer); request?.abort(); generation++;
  const text = parsed.value.query;
  const engine = provider.value;
  if (!engine || !canComplete(text)) return;
  const revision = generation;
  timer = setTimeout(async () => {
    request = new AbortController();
    try {
      const data = await api('search/suggestions', { method: 'POST', body: JSON.stringify({ query: text, provider: engine }), signal: request.signal });
      if (revision !== generation) return;
      suggestions.value = data.available ? data.suggestions.filter(item => item.toLocaleLowerCase() !== text.toLocaleLowerCase()) : [];
    } catch { /* Suggestions are optional; bookmark and web search remain available. */ }
  }, 350);
});
function navigate(action) {
  if (!action) return;
  if (action.type === 'bookmark') recordBookmarkVisit(action.id);
  const newTab = action.type === 'bookmark' || (webTarget.value === '_blank' && !(action.type === 'web' && directUrl.value));
  if (newTab) window.open(action.url, '_blank', 'noopener,noreferrer');
  else window.location.assign(action.url);
}
function submit() { navigate(active.value >= 0 ? actions.value[active.value] : actions.value.find(item => item.type === 'web')); }
function keydown(event) {
  if (event.isComposing || composing.value || event.keyCode === 229) return;
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    if (!actions.value.length) return;
    active.value = active.value < 0 ? (event.key === 'ArrowDown' ? 0 : actions.value.length - 1) : (active.value + (event.key === 'ArrowDown' ? 1 : -1) + actions.value.length) % actions.value.length;
    nextTick(() => dialog.value.querySelector(`#dock-search-option-${active.value}`)?.scrollIntoView({ block: 'nearest' }));
  } else if (event.key === 'Enter') { event.preventDefault(); submit(); }
}
</script>
<template><dialog ref="dialog" v-dialog-dismiss class="portal-search" aria-label="북마크·웹 통합 검색" @cancel.prevent="close">
  <div class="portal-search-header"><Search :size="21" /><input ref="input" :value="query" @input="updateQuery" @compositionstart="composing = true" @compositionend="finishComposition" type="search" role="combobox" spellcheck="false" autocomplete="off" maxlength="200" placeholder="북마크 이름·주소 또는 웹 검색어" aria-label="검색어" aria-autocomplete="list" aria-controls="dock-search-results" aria-expanded="true" :aria-activedescendant="active >= 0 ? `dock-search-option-${active}` : undefined" @keydown="keydown" /><button type="button" class="search-close" aria-label="검색 닫기" @click="close"><X :size="19" /></button></div>
  <div id="dock-search-results" class="portal-search-results" role="listbox" aria-label="검색 결과">
    <div class="portal-search-section"><span>{{ parsed.query ? '내 북마크' : '빠른 북마크' }}</span><small>{{ matches.length }}개{{ matches.length > bookmarks.length ? ` 중 ${bookmarks.length}개` : '' }}</small></div>
    <a v-for="(link,index) in bookmarks" :id="`dock-search-option-${index}`" :key="link.id" class="portal-search-row" :class="{ active: active === index }" role="option" :aria-selected="active === index" :href="link.url" target="_blank" rel="noopener noreferrer" @pointermove="active = index" @click="recordBookmarkVisit(link.id,$event)" @auxclick="recordBookmarkVisit(link.id,$event)"><BookmarkIcon :name="link.icon" :style="{ color: link.displayColor }" /><span><strong>{{ link.name }}</strong><small>{{ link.url }}</small><span class="search-location">{{ link.tabName }} / {{ link.categoryName }}</span></span><ArrowUpRight :size="14" /></a>
    <p v-if="!matches.length" class="search-empty">일치하는 북마크가 없어요. 아래에서 웹으로 검색할 수 있습니다.</p>
    <button v-if="matches.length > bookmarks.length" class="search-more" type="button" @click="limit += 12">북마크 더 보기</button>
    <template v-if="validQuery"><div class="portal-search-section"><span>웹 검색</span><small v-if="active < 0">Enter로 검색</small></div>
      <a :id="`dock-search-option-${webIndex}`" class="portal-search-row search-web-action" :class="{ active: active === webIndex }" role="option" :aria-selected="active === webIndex" :href="directUrl || webUrl(engines, parsed.engine, parsed.query)" :target="directUrl ? '_self' : webTarget" :rel="!directUrl && webTarget === '_blank' ? 'noopener noreferrer' : undefined" @pointermove="active = webIndex"><Globe2 :size="19" /><span><strong>{{ directUrl ? '주소로 이동' : `${engines[parsed.engine][1]}에서 검색` }}</strong><small>{{ parsed.query }}</small></span><ArrowUpRight :size="14" /></a>
      <div class="search-engine-shortcuts"><a v-for="(engine,key) in engines" :key="key" :href="webUrl(engines,key,parsed.query)" :target="webTarget" :rel="webTarget === '_blank' ? 'noopener noreferrer' : undefined">{{ engine[1] }}<small>!{{ key }}</small></a></div>
    </template>
    <template v-if="suggestions.length"><div class="portal-search-section"><span>{{ engines[provider][1] }} 자동완성</span></div>
      <a v-for="(text,index) in suggestions" :id="`dock-search-option-${firstSuggestionIndex + index}`" :key="text" role="option" :aria-selected="active === firstSuggestionIndex + index" class="portal-search-row" :class="{ active: active === firstSuggestionIndex + index }" :href="webUrl(engines,provider,text)" :target="webTarget" :rel="webTarget === '_blank' ? 'noopener noreferrer' : undefined" @pointermove="active = firstSuggestionIndex + index"><Search :size="17" /><span><strong>{{ text }}</strong></span><ArrowUpRight :size="14" /></a>
    </template>
  </div>
  <footer class="portal-search-footer"><small>{{ engines[parsed.engine][1] }}</small><span class="search-keyboard-hint">↑↓ 선택 · Enter 실행 · Esc 닫기</span></footer>
</dialog></template>
