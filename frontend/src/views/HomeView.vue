<script setup>
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from "vue";
import { Check, GripVertical, Search, Undo2, Plus } from "lucide-vue-next";
import QuickAddDialog from '../components/bookmarks/QuickAddDialog.vue';
import BookmarkShelf from '../components/bookmarks/BookmarkShelf.vue';
import AppInstall from '../components/common/AppInstall.vue';
import { recordBookmarkVisit } from '../lib/bookmarkActivity.js';
import '../styles/management.css';
import ServiceStatus from "../components/common/ServiceStatus.vue";
import BookmarkIcon from "../components/common/BookmarkIcon.vue";
import { backgroundUrl } from "../lib/backgrounds.js";
import BackgroundArtwork from '../components/backgrounds/BackgroundArtwork.vue';
import { api } from "../lib/api.js";
import { bookmarkColor } from "../lib/bookmarkColors.js";
import { formatDate } from "../lib/clock.js";
import FooterBar from "../components/statusbar/FooterBar.vue";
import { reorderDirective } from "../directives/reorder.js";
import { useVisibleBookmarkStatus } from "../composables/useVisibleBookmarkStatus.js";
import { useProxmox } from '../composables/useProxmox.js';
import ProxmoxBadge from '../components/integrations/ProxmoxBadge.vue';
import '../styles/proxmox.css';
import "../styles/home.css";
import "../styles/statusbar.css";

const props = defineProps({ startpage: { type: Object, required: true }, username: String });
const startpage = props.startpage;
const quickAdd = ref(null), quickNotice = ref('');
const shelfStorageKey = `catppuccindock:shelf-collapsed:${props.username}`;
const shelfCollapsed = ref(false);
try { shelfCollapsed.value = localStorage.getItem(shelfStorageKey) === 'true'; } catch { /* Optional browser preference. */ }
watch(shelfCollapsed, value => { try { localStorage.setItem(shelfStorageKey,String(value)); } catch { /* Keep folding usable without storage. */ } });
const animationMode = computed(() => startpage.animationMode || (startpage.tabAnimation === false ? 'off' : 'system'));
function bookmarkAdded(link) {
  const target = startpage.tabs.find(tab => tab.categories.some(category => category.id === link.category_id));
  target?.categories.find(category => category.id === link.category_id)?.links.push(link);
  if (target) selectTab(startpage.tabs.indexOf(target));
  quickNotice.value = `‘${link.name}’ 북마크를 추가했어요.`;
}
function visited(event) {
  const id = event.detail?.id;
  if (!startpage.tabs.some(tab => tab.categories.some(category => category.links.some(link => link.id === id)))) return;
  startpage.recentBookmarks = [id,...(startpage.recentBookmarks || []).filter(value => value !== id)].slice(0,12);
}

function readStoredTab() {
  if (!startpage.openLastVisitedTab) return 0;
  const stored = Number(localStorage.getItem("lastVisitedTab"));
  return Number.isInteger(stored) && stored >= 0 && stored < startpage.tabs.length ? stored : 0;
}

const activeTabIndex = ref(readStoredTab());
const slideDirection = ref("next");
const activeTab = computed(() => startpage.tabs[activeTabIndex.value] ?? startpage.tabs[0]);
const titleCharacters = computed(() => Array.from(activeTab.value.name));
const titleHeight = computed(() => Math.max(
  250,
  titleCharacters.value.reduce((height, character) => height + (character === " " ? 15 : 33), 0) + 32,
));
const panelHeight = computed(() => Math.max(450, titleHeight.value + 64));
const editUrl = new URL(window.location.href);
const editing = ref(editUrl.searchParams.get('edit') === '1'), reorderBusy = ref(false), reorderError = ref(''), undoId = ref('');
if (editing.value) { editUrl.searchParams.delete('edit'); window.history.replaceState(window.history.state, '', editUrl); }
async function reorderMain(kind, parentId, ids) {
  if (reorderBusy.value) return;
  const currentId = activeTab.value.id;
  const list = kind === 'tabs' ? startpage.tabs : kind === 'categories' ? startpage.tabs.find(tab => tab.id === parentId).categories : startpage.tabs.flatMap(tab => tab.categories).find(category => category.id === parentId).links;
  const previous = [...list], rows = new Map(list.map(item => [item.id, item]));
  list.splice(0, list.length, ...ids.map(id => rows.get(id)));
  activeTabIndex.value = startpage.tabs.findIndex(tab => tab.id === currentId);
  reorderBusy.value = true; reorderError.value = '';
  try {
    const result = await api('reorder', { method: 'POST', body: JSON.stringify({ kind, parent_id: parentId, ids }) });
    undoId.value = result.undo_id;
  } catch (cause) {
    list.splice(0, list.length, ...previous);
    activeTabIndex.value = startpage.tabs.findIndex(tab => tab.id === currentId);
    reorderError.value = cause.message;
  } finally { reorderBusy.value = false; }
}
function moveMain(kind, parentId, list, id, offset) { const ids = list.map(item => item.id), index = ids.indexOf(id), next = index + offset; if (next < 0 || next >= ids.length) return; [ids[index], ids[next]] = [ids[next], ids[index]]; reorderMain(kind, parentId, ids); }
async function undoOrder() { try { await api('trash/' + undoId.value + '/restore', { method: 'POST' }); location.reload(); } catch (cause) { reorderError.value = cause.message; } }
const vReorder = reorderDirective(reorderMain);
const searchOpen = ref(false);
const PortalSearch = defineAsyncComponent(() => import("../components/search/PortalSearch.vue"));
const currentTime = ref(new Date());
const main = ref(null), shelfLayout = ref(0);
const statusLayout = computed(() => `${activeTab.value.id}:${editing.value}:${shelfCollapsed.value}:${shelfLayout.value}:${activeTab.value.categories.map(category => category.links.map(link => link.id).join(',')).join(';')}`);
const serviceStatus = useVisibleBookmarkStatus(main, statusLayout);
const { byBookmark: proxmoxByBookmark, selected: proxmoxSelected, replace: updateProxmox } = useProxmox(main, statusLayout);
const ProxmoxPanel = defineAsyncComponent(() => import('../components/integrations/ProxmoxPanel.vue'));
const banner = computed(() => backgroundUrl(activeTab.value));
const tabFlavours = ["var(--green)", "var(--peach)", "var(--red)", "var(--blue)", "var(--mauve)"];
const activeFlavour = computed(() => tabFlavours[activeTabIndex.value % tabFlavours.length]);
const formattedDate = computed(() => formatDate(currentTime.value, startpage.clock));

function selectTab(index) {
  const next = (index + startpage.tabs.length) % startpage.tabs.length;
  if (next === activeTabIndex.value) return;
  slideDirection.value = index > activeTabIndex.value ? "next" : "previous";
  activeTabIndex.value = next;
}

function hideLeavingPanel(element) {
  element.inert = true;
  element.setAttribute("aria-hidden", "true");
}

function showEnteringPanel(element) {
  element.inert = false;
  element.removeAttribute("aria-hidden");
}

function openSearch() { searchOpen.value = true; }
function closeSearch() { searchOpen.value = false; }

function handleKeydown(event) {
  if (event.defaultPrevented || event.isComposing || event.altKey || event.ctrlKey || event.metaKey) return;
  const focused = document.activeElement;
  const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(focused?.tagName) || focused?.isContentEditable;
  if (event.key === "Escape" && searchOpen.value) {
    closeSearch();
    return;
  }
  if (focused?.closest('dialog')) return;
  if (editing.value && !typing && !searchOpen.value && event.key.toLowerCase() === 'n') { event.preventDefault(); quickAdd.value.open(); return; }
  if (!typing && !searchOpen.value && !event.shiftKey && ["ArrowLeft", "ArrowRight"].includes(event.key)) {
    event.preventDefault();
    selectTab(activeTabIndex.value + (event.key === "ArrowRight" ? 1 : -1));
    return;
  }
  if (!typing && !searchOpen.value && event.key.toLowerCase() === "s") {
    event.preventDefault();
    openSearch();
    return;
  }
  if (!typing && !searchOpen.value && /^[1-9]$/.test(event.key)) {
    const index = Number(event.key) - 1;
    if (index < startpage.tabs.length) selectTab(index);
  }
}

let clockInterval;
onMounted(() => {
  window.addEventListener("keydown", handleKeydown);
  window.addEventListener('dock:bookmark-visited',visited);
  clockInterval = window.setInterval(() => (currentTime.value = new Date()), 1_000);
});

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeydown);
  window.removeEventListener('dock:bookmark-visited',visited);
  window.clearInterval(clockInterval);
});

watch(activeTabIndex, (index) => {
  if (startpage.openLastVisitedTab) localStorage.setItem("lastVisitedTab", String(index));
});
</script>

<template>
  <main ref="main" class="startpage" :data-motion="animationMode" :style="{ '--tab-flavour': activeFlavour, '--panel-height': `${panelHeight}px` }">
    <div class="startpage-stage">
      <button class="panel-navigation panel-navigation-previous" aria-label="이전 메뉴" aria-keyshortcuts="ArrowLeft" title="이전 메뉴 (←)" @click="selectTab(activeTabIndex - 1)">
        <span aria-hidden="true"></span>
      </button>
      <div class="startpage-panel">
        <Transition :name="`panel-slide-${slideDirection}`" :css="animationMode !== 'off'" @before-leave="hideLeavingPanel" @before-enter="showEnteringPanel">
        <section :key="activeTab.id" class="startpage-content" :style="{ '--tab-wallpaper': banner ? `url(${banner})` : 'none', '--tab-flavour': activeFlavour, '--title-height': titleHeight }">
          <BackgroundArtwork :source="activeTab.background_source">
            <span class="startpage-art-title" aria-hidden="true">
              <span v-for="(character, index) in titleCharacters" :key="`${character}-${index}`" :class="{ 'title-space': character === ' ' }">
                {{ character === " " ? "\u00a0" : character }}
              </span>
            </span>
          </BackgroundArtwork>

          <div class="startpage-main">
            <header class="startpage-heading">
              <div>
                <span class="startpage-eyebrow">CatppuccinDock</span>
                <h1>{{ activeTab.name }}</h1>
                <p>{{ formattedDate }}</p>
              </div>
              <div class="home-heading-actions"><AppInstall /><button v-if="editing" class="search-launch" aria-label="북마크 빠른 추가" title="북마크 추가 (N)" @click="quickAdd.open()"><Plus :size="19" /></button><button class="search-launch" aria-label="검색 열기" title="검색" @click="openSearch">
                <Search :size="19" />
              </button></div>
            </header>

            <p v-if="quickNotice" class="quick-add-notice" role="status">{{ quickNotice }}</p>
            <BookmarkShelf v-if="!editing" v-model:collapsed="shelfCollapsed" :portal="startpage" :statuses="serviceStatus" @layout-change="shelfLayout++" @clear-recent="startpage.recentBookmarks = []" />

            <div v-reorder="{ kind: 'categories', parentId: activeTab.id, disabled: !editing || reorderBusy }" class="startpage-categories">
              <section v-for="category in activeTab.categories" :key="category.id" :data-sort-id="category.id" class="startpage-category">
                <h2><button v-if="editing" class="reorder-handle home-grip" :aria-label="`${category.name} 카테고리 순서 변경 · 위아래 방향키`" @keydown.up.prevent.stop="moveMain('categories', activeTab.id, activeTab.categories, category.id, -1)" @keydown.down.prevent.stop="moveMain('categories', activeTab.id, activeTab.categories, category.id, 1)"><GripVertical :size="13" /></button>{{ category.name }}</h2>
                <div v-reorder="{ kind: 'bookmarks', parentId: category.id, disabled: !editing || reorderBusy }" class="startpage-links">
                  <component :is="editing || proxmoxByBookmark[link.id] ? 'div' : 'a'"
                    v-for="(link, linkIndex) in category.links"
                    :key="link.id"
                    :data-sort-id="link.id"
                    :data-bookmark-id="link.id"
                    class="startpage-link"
                    :class="{'pve-linked-bookmark': !editing && proxmoxByBookmark[link.id]}"
                    :href="editing || proxmoxByBookmark[link.id] ? undefined : link.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    :title="editing ? undefined : link.name"
                    @click="editing ? $event.preventDefault() : !proxmoxByBookmark[link.id] && recordBookmarkVisit(link.id,$event)"
                    @auxclick="!editing && !proxmoxByBookmark[link.id] && recordBookmarkVisit(link.id,$event)"
                  >
                    <button v-if="editing" class="reorder-handle home-grip" :aria-label="`${link.name} 북마크 순서 변경 · 좌우 방향키`" @click.stop.prevent @keydown.left.prevent.stop="moveMain('bookmarks', category.id, category.links, link.id, -1)" @keydown.right.prevent.stop="moveMain('bookmarks', category.id, category.links, link.id, 1)"><GripVertical :size="12" /></button>
                    <a v-if="!editing && proxmoxByBookmark[link.id]" class="pve-bookmark-link" :href="link.url" target="_blank" rel="noopener noreferrer" @click="recordBookmarkVisit(link.id,$event)" @auxclick="recordBookmarkVisit(link.id,$event)"><BookmarkIcon class="bookmark-icon" :name="link.icon" :style="{color:bookmarkColor(link,linkIndex)}" /><span>{{ link.name }}</span></a>
                    <template v-else><BookmarkIcon class="bookmark-icon" :name="link.icon" :style="{ color: bookmarkColor(link, linkIndex) }" /><span>{{ link.name }}</span></template>
                    <ProxmoxBadge v-if="!editing && proxmoxByBookmark[link.id]" :integration="proxmoxByBookmark[link.id]" @open="proxmoxSelected = $event" />
                    <ServiceStatus v-if="serviceStatus[link.id]" :status="serviceStatus[link.id]" />
                  </component>
                </div>
              </section>
            </div>
          </div>
        </section>
        </Transition>
      </div>
      <button class="panel-navigation panel-navigation-next" aria-label="다음 메뉴" aria-keyshortcuts="ArrowRight" title="다음 메뉴 (→)" @click="selectTab(activeTabIndex + 1)">
        <span aria-hidden="true"></span>
      </button>
    </div>

    <div v-if="editing" class="home-edit-toolbar" role="region" aria-label="화면 편집"><button class="statusbar-widget" aria-label="화면 편집 종료" @click="editing = false"><Check :size="14" />편집 완료</button><span>손잡이를 드래그하거나 방향키로 순서를 변경하세요. 변경 즉시 저장됩니다.</span><div v-reorder="{ kind: 'tabs', disabled: reorderBusy }" class="home-tab-order"><span v-for="tab in startpage.tabs" :key="tab.id" :data-sort-id="tab.id"><button class="reorder-handle home-grip" :aria-label="`${tab.name} 탭 순서 변경 · 좌우 방향키`" @keydown.left.prevent.stop="moveMain('tabs', null, startpage.tabs, tab.id, -1)" @keydown.right.prevent.stop="moveMain('tabs', null, startpage.tabs, tab.id, 1)"><GripVertical :size="12" />{{ tab.name }}</button></span></div><button v-if="undoId" class="statusbar-widget" @click="undoOrder"><Undo2 :size="14" />순서 변경 취소</button><p v-if="reorderError" role="alert">{{ reorderError }}</p></div>
    <FooterBar v-model:editing="editing" :portal="startpage" :active-tab="activeTabIndex" :now="currentTime" @select-tab="selectTab" />

    <PortalSearch v-if="searchOpen" :portal="startpage" @close="closeSearch" />
    <QuickAddDialog ref="quickAdd" :portal="startpage" :active-tab="activeTab.id" @saved="bookmarkAdded" />
    <ProxmoxPanel v-if="proxmoxSelected" :integration="proxmoxSelected" @close="proxmoxSelected = null" @updated="updateProxmox" />

  </main>
</template>
