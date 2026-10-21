<script setup>
import { computed, onMounted, onBeforeUnmount, ref, useId, watch } from 'vue';
import { Star, Clock3, X, Pencil, Trash2, ChevronLeft, ChevronRight, ChevronDown, ChevronUp } from 'lucide-vue-next';
import BookmarkIcon from '../common/BookmarkIcon.vue';
import ServiceStatus from '../common/ServiceStatus.vue';
import { api } from '../../lib/api.js';
import { bookmarkColor } from '../../lib/bookmarkColors.js';
import { recordBookmarkVisit } from '../../lib/bookmarkActivity.js';
const props = defineProps({portal:Object,statuses:{type:Object,default:()=>({})}});
const emit = defineEmits(['layout-change','clear-recent']);
const collapsed = defineModel('collapsed',{type:Boolean,default:false});
const iconsOnly = computed(() => props.portal.bookmarkShelfDisplay === 'icons');
const links = ref(null), canPrevious = ref(false), canNext = ref(false), stripId = useId();
const position = ref({start:0,end:0,left:0,width:100});
const overflowing = computed(() => canPrevious.value || canNext.value);
const positionLabel = computed(() => `${mode.value === 'favorites' ? '즐겨찾기' : '최근 사용'} ${position.value.start}–${position.value.end} / ${items.value.length}`);
let resizeObserver;
function updateOverflow() {
  const element = links.value;
  canPrevious.value = !!element && element.scrollLeft > 1;
  canNext.value = !!element && element.scrollWidth - element.clientWidth - element.scrollLeft > 1;
  if (!element) { position.value = {start:0,end:0,left:0,width:100}; return; }
  const bounds = element.getBoundingClientRect();
  const visible = [...element.children].map((child,index) => ({index,bounds:child.getBoundingClientRect()}))
    .filter(child => child.bounds.right > bounds.left + 1 && child.bounds.left < bounds.right - 1);
  position.value = {
    start:visible.length ? visible[0].index + 1 : 0,
    end:visible.length ? visible[visible.length - 1].index + 1 : 0,
    left:element.scrollWidth ? Math.max(0,element.scrollLeft) / element.scrollWidth * 100 : 0,
    width:element.scrollWidth ? Math.min(100,element.clientWidth / element.scrollWidth * 100) : 100,
  };
}
function observeStrip() {
  resizeObserver?.disconnect();
  if (links.value) resizeObserver?.observe(links.value);
  updateOverflow();
}
function scrollStrip(direction) {
  links.value?.scrollBy({left:direction * Math.max(24,links.value.clientWidth * .75),behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
}
function selectMode(value) { mode.value = value; }
onMounted(() => { resizeObserver = new ResizeObserver(updateOverflow); observeStrip(); });
onBeforeUnmount(() => resizeObserver?.disconnect());
const mode = ref('favorites'), dialog = ref(null), query = ref(''), limit = ref(60), busy = ref(''), error = ref('');
const all = computed(() => props.portal.tabs.flatMap(tab => tab.categories.flatMap(category => category.links.map((link,index) => ({...link,displayColor:bookmarkColor(link,index),location:`${tab.name} / ${category.name}`})))));
const favorites = computed(() => all.value.filter(link => link.favorite));
const recent = computed(() => (props.portal.recentBookmarks || []).map(id => all.value.find(link => link.id === id)).filter(Boolean));
const items = computed(() => mode.value === 'favorites' ? favorites.value : recent.value);
watch(() => items.value.map(link => link.id).join(','), () => emit('layout-change'), {flush:'post'});
watch([() => items.value.map(link => link.id).join(','),collapsed,iconsOnly],observeStrip,{flush:'post'});
watch(mode, () => { if (links.value) links.value.scrollLeft = 0; updateOverflow(); }, {flush:'post'});
const matches = computed(() => all.value.filter(link => `${link.name} ${link.url} ${link.location}`.toLocaleLowerCase().includes(query.value.toLocaleLowerCase().trim())));
async function toggle(id) {
  if (busy.value) return;
  const link = props.portal.tabs.flatMap(tab => tab.categories.flatMap(category => category.links)).find(link => link.id === id);
  if (!link) return;
  const previous = !!link.favorite; busy.value = id; error.value = ''; link.favorite = !previous;
  try { await api(`bookmark-tools/${id}/favorite`,{method:'PUT',body:JSON.stringify({favorite:link.favorite})}); }
  catch (cause) { link.favorite = previous; error.value = cause.message; } finally { busy.value = ''; }
}
function manage() { query.value = ''; limit.value = 60; dialog.value.showModal(); }
async function clearRecent() { try { await api('bookmark-tools/recent',{method:'DELETE'}); emit('clear-recent'); } catch (cause) { error.value = cause.message; } }
</script>
<template><section class="bookmark-shelf" :class="{'shelf-collapsed':collapsed,'shelf-icons-only':iconsOnly}" aria-label="즐겨찾기와 최근 사용">
  <div class="bookmark-shelf-heading">
    <div class="shelf-modes">
      <button aria-label="즐겨찾기" title="즐겨찾기" :aria-pressed="mode==='favorites'" @click="selectMode('favorites')"><Star :size="13" /><span v-if="!iconsOnly">즐겨찾기</span></button>
      <button aria-label="최근 사용" title="최근 사용" :aria-pressed="mode==='recent'" @click="selectMode('recent')"><Clock3 :size="13" /><span v-if="!iconsOnly">최근 사용</span></button>
    </div>
    <div class="shelf-actions">
      <button v-if="overflowing" class="shelf-scroll-button" :aria-label="mode==='favorites'?'이전 즐겨찾기':'이전 최근 사용'" :disabled="!canPrevious" @click="scrollStrip(-1)"><ChevronLeft :size="14" /></button>
      <button v-if="overflowing" class="shelf-scroll-button" :aria-label="mode==='favorites'?'다음 즐겨찾기':'다음 최근 사용'" :disabled="!canNext" @click="scrollStrip(1)"><ChevronRight :size="14" /></button>
      <button v-if="mode==='favorites'" class="shelf-manage shelf-manage-icon" aria-label="즐겨찾기 관리" title="즐겨찾기 관리" @click="manage"><Pencil :size="13" /></button>
      <button v-else-if="recent.length" class="shelf-manage shelf-clear" aria-label="기록 지우기" title="기록 지우기" @click="clearRecent"><Trash2 v-if="collapsed || iconsOnly" :size="13" /><span v-else>기록 지우기</span></button>
      <button class="shelf-fold-button" :aria-label="collapsed ? '즐겨찾기·최근 사용 펼치기' : '즐겨찾기·최근 사용 접기'" :aria-expanded="!collapsed" :aria-controls="stripId" @click="collapsed=!collapsed"><ChevronDown v-if="collapsed" :size="14" /><ChevronUp v-else :size="14" /></button>
    </div>
  </div>
  <div :id="stripId" class="shelf-strip">
    <div v-if="items.length" ref="links" class="startpage-links shelf-links" tabindex="0" :aria-label="mode==='favorites'?'즐겨찾기 링크 목록':'최근 사용 링크 목록'" @scroll.passive="updateOverflow" @keydown.left.stop @keydown.right.stop>
      <a v-for="link in items" :key="link.id" class="startpage-link" :data-bookmark-id="link.id" :href="link.url" :title="link.name" :aria-label="link.name" target="_blank" rel="noopener noreferrer" @click="recordBookmarkVisit(link.id,$event)" @auxclick="recordBookmarkVisit(link.id,$event)">
        <BookmarkIcon class="bookmark-icon" :name="link.icon" :style="{color:link.displayColor}" /><span v-if="!iconsOnly">{{ link.name }}</span><ServiceStatus v-if="statuses[link.id]" :status="statuses[link.id]" />
      </a>
    </div>
    <p v-else class="shelf-empty">{{ mode==='favorites' ? '즐겨찾기 관리에서 자주 쓰는 링크를 고정하세요.' : '열었던 북마크가 여기에 표시됩니다.' }}</p>
    <div v-if="overflowing" class="shelf-position" role="img" :aria-label="positionLabel" :title="positionLabel"><span :style="{left:`${position.left}%`,width:`${position.width}%`}"></span></div>
  </div>
  <p v-if="error" class="shelf-error" role="alert">{{ error }}</p>
<dialog ref="dialog" v-dialog-dismiss="busy" class="shelf-dialog editor-dialog" aria-label="즐겨찾기 관리"><div class="card-heading"><h2>즐겨찾기 관리</h2><button class="icon-button" aria-label="즐겨찾기 관리 닫기" :disabled="!!busy" @click="dialog.close()"><X :size="18" /></button></div><label class="shelf-search-label">북마크 검색<input v-model="query" type="search" maxlength="120" /></label><p v-if="error" class="form-error" role="alert">{{ error }}</p><div class="shelf-candidates"><button v-for="link in matches.slice(0,limit)" :key="link.id" class="shelf-candidate" :disabled="!!busy" :aria-label="`${link.name} 즐겨찾기 ${link.favorite ? '해제' : '추가'}`" :aria-pressed="!!link.favorite" @click="toggle(link.id)"><BookmarkIcon :name="link.icon" :style="{color:link.displayColor}" /><span><strong>{{ link.name }}</strong><small>{{ link.location }}</small></span><Star :size="16" :fill="link.favorite ? 'currentColor' : 'none'" /></button></div><button v-if="matches.length>limit" class="secondary-button" @click="limit+=60">더 보기</button><p v-if="!matches.length" class="shelf-empty">검색 결과가 없습니다.</p></dialog></section></template>
