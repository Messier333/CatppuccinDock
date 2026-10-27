<script setup>
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { ArrowLeft, Bookmark, Library, Users, ShieldCheck, SlidersHorizontal, Download, Moon, Sun, Archive, FolderDown, UsersRound, Activity, RefreshCw, GripVertical, Pencil, Check, RotateCcw, Search, X, ChevronRight } from "lucide-vue-next";
import { appUrl } from "../lib/navigation.js";
import { useTheme } from "../composables/useTheme.js";
import LogoutButton from "../components/common/LogoutButton.vue";
import { api } from '../lib/api.js';
import { reorderDirective } from '../directives/reorder.js';
import { searchSettings } from '../lib/settingsSearch.js';
import { groupSettingsSections, sectionOrderForGroups } from '../lib/adminNavigation.js';
import { useSidebarResize } from '../composables/useSidebarResize.js';
import "../styles/admin.css";
import "../styles/management.css";

const props = defineProps({ username: String, role: String });
const BookmarkManager = defineAsyncComponent(() => import("../components/bookmarks/BookmarkManager.vue"));
const AccountSecurity = defineAsyncComponent(() => import("../components/settings/AccountSecurity.vue"));
const UserManager = defineAsyncComponent(() => import("../components/settings/UserManager.vue"));
const SiteSettings = defineAsyncComponent(() => import("../components/settings/SiteSettings.vue"));
const ProxyImport = defineAsyncComponent(() => import("../components/settings/ProxyImport.vue"));
const SharedLibrary = defineAsyncComponent(() => import("../components/settings/SharedLibrary.vue"));
const BackupManager = defineAsyncComponent(() => import('../components/settings/BackupManager.vue'));
const TrashManager = defineAsyncComponent(() => import('../components/settings/TrashManager.vue'));
const GroupManager = defineAsyncComponent(() => import('../components/settings/GroupManager.vue'));
const MonitorManager = defineAsyncComponent(() => import('../components/settings/MonitorManager.vue'));
const FooterSettings = defineAsyncComponent(() => import('../components/settings/FooterSettings.vue'));
const ProxySyncManager = defineAsyncComponent(() => import('../components/settings/ProxySyncManager.vue'));
const MediaSettings = defineAsyncComponent(() => import('../components/settings/MediaSettings.vue'));
const ProxmoxSettings = defineAsyncComponent(() => import('../components/settings/ProxmoxSettings.vue'));
const sections = computed(() => [
  { id: "bookmarks", name: "내 북마크", icon: Bookmark, view: BookmarkManager },
  { id: "preferences", name: "개인 설정 · 앱 설치", icon: SlidersHorizontal, view: PersonalSettings },
  { id: "library", name: "공개 링크", icon: Library, view: SharedLibrary },
  { id: "backup", name: "백업 · 가져오기", icon: FolderDown, view: BackupManager },
  { id: "trash", name: "휴지통", icon: Archive, view: TrashManager },
  { id: "security", name: "계정 · 보안", icon: ShieldCheck, view: AccountSecurity },
  { id: "proxmox", name: "내 Proxmox", icon: Activity, view: ProxmoxSettings },
  ...(props.role === "admin" ? [{ id: "backgrounds", name: "GIF · 배경 관리", icon: Library, view: MediaSettings }, { id: "groups", name: "그룹 관리", icon: UsersRound, view: GroupManager }, { id: "footer", name: "하단바 · 모니터링", icon: SlidersHorizontal, view: FooterSettings }, { id: "monitoring", name: "서비스 상태", icon: Activity, view: MonitorManager }, { id: "sync", name: "프록시 변경 감지", icon: RefreshCw, view: ProxySyncManager }, { id: "users", name: "사용자 관리", icon: Users, view: UserManager }, { id: "import", name: "API 링크 가져오기", icon: Download, view: ProxyImport }, { id: "shared", name: "공개 링크 관리", icon: Library, view: SharedLibrary, manage: true }, { id: "settings", name: "포털 공통 설정", icon: SlidersHorizontal, view: SiteSettings, props: { settingsSection: 'portal' } }, { id: "sso", name: "SSO · 로그인", icon: ShieldCheck, view: SiteSettings, props: { settingsSection: 'sso' } }] : []),
]);
const PersonalSettings = defineAsyncComponent(() => import("../components/settings/PersonalSettings.vue"));
const requestedSection = new URLSearchParams(window.location.search).get('section');
const selected = ref(sections.value.some(item => item.id === requestedSection) ? requestedSection : 'bookmarks');
const section = computed(() => sections.value.find(item => item.id === selected.value) || sections.value[0]);
const query = ref(''), content = ref(null), heading = ref(null);
const results = computed(() => searchSettings(orderedSections.value, query.value));
const searching = computed(() => !!query.value.trim());
const sidebar = useSidebarResize(props.username);
let destinationObserver, destinationTimer;
function clearDestination() { destinationObserver?.disconnect(); clearTimeout(destinationTimer); }
async function openResult(result) {
  if (!result) return;
  selectSection(result.section);
  await nextTick();
  heading.value?.focus({ preventScroll: true });
  const reveal = () => {
    const target = result.anchor && content.value?.querySelector(`[data-settings-anchor="${result.anchor}"]`);
    if (!target) return false;
    target.scrollIntoView({ block: 'center', behavior: 'instant' });
    target.querySelector('input,button,select')?.focus({ preventScroll: true });
    target.classList.remove('settings-search-highlight');
    requestAnimationFrame(() => target.classList.add('settings-search-highlight'));
    clearDestination(); return true;
  };
  if (!result.anchor) heading.value?.scrollIntoView({ block: 'start' });
  else if (!reveal()) {
    destinationObserver = new MutationObserver(reveal);
    destinationObserver.observe(content.value, { subtree: true, childList: true });
    destinationTimer = setTimeout(clearDestination, 5_000);
  }
}
const rememberedSections = new Map();
function selectSection(id) {
  clearDestination(); query.value = ''; selected.value = id;
  const group = orderedGroups.value.find(group => group.sections.some(section => section.id === id));
  if (group) rememberedSections.set(group.id, id);
}
function selectGroup(group) {
  if (group.sections.some(item => item.id === section.value.id)) { selectSection(section.value.id); return; }
  selectSection(rememberedSections.get(group.id) || group.sections[0].id);
}
function subsectionKeydown(event) {
  if (event.altKey || event.ctrlKey || event.metaKey || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const items = activeGroup.value.sections;
  const index = items.findIndex(item => item.id === section.value.id);
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length;
  selectSection(items[next].id);
  nextTick(() => content.value?.querySelector(`#settings-tab-${items[next].id}`)?.focus());
}
function searchKeydown(event) {
  if (event.isComposing || event.keyCode === 229) return;
  if (event.key === 'Enter') { event.preventDefault(); openResult(results.value[0]); }
  if (event.key === 'Escape') { event.preventDefault(); query.value = ''; }
}
onBeforeUnmount(clearDestination);
const { theme, toggleTheme } = useTheme();
const menuOrder = ref([]), editingMenu = ref(false), menuBusy = ref(false), menuError = ref('');
const orderedSections = computed(() => {
  const byId = new Map(sections.value.map(item => [item.id, item]));
  return [...menuOrder.value.filter(id => byId.has(id)).map(id => byId.get(id)), ...sections.value.filter(item => !menuOrder.value.includes(item.id))];
});
const orderedGroups = computed(() => groupSettingsSections(orderedSections.value));
const activeGroup = computed(() => orderedGroups.value.find(group => group.sections.some(item => item.id === section.value.id)) || orderedGroups.value[0]);
const groupIcons = { bookmarks: Bookmark, links: Library, preferences: SlidersHorizontal, settings: SlidersHorizontal, backgrounds: Library, accounts: ShieldCheck, users: Users, integrations: Download, monitoring: Activity, footer: SlidersHorizontal, backup: FolderDown, trash: Archive };
onMounted(async () => { try { menuOrder.value = (await api('navigation')).order; } catch (cause) { menuError.value = cause.message; } });
async function reorderMenu(kind, parentId, groupIds) {
  if (menuBusy.value) return;
  menuBusy.value = true; menuError.value = '';
  try {
    const ids = sectionOrderForGroups(orderedGroups.value, groupIds);
    await api('navigation', { method: 'PUT', body: JSON.stringify({ order: ids }) }); menuOrder.value = ids;
  }
  catch (cause) { menuError.value = cause.message; }
  finally { menuBusy.value = false; }
}
function moveMenu(id, delta) { const ids = orderedGroups.value.map(item => item.id), index = ids.indexOf(id), next = index + delta; if (next < 0 || next >= ids.length) return; [ids[index], ids[next]] = [ids[next], ids[index]]; reorderMenu('navigation', null, ids); }
async function resetMenu() {
  menuBusy.value = true; menuError.value = '';
  try { await api('navigation', { method: 'DELETE' }); menuOrder.value = (await api('navigation')).order; }
  catch (cause) { menuError.value = cause.message; }
  finally { menuBusy.value = false; }
}
const vReorder = reorderDirective(reorderMenu);
</script>
<template>
  <div class="dock-shell management-shell" :class="{ 'sidebar-resizing': sidebar.resizing.value }" :style="{ '--sidebar-width': `${sidebar.width.value}px` }">
    <aside class="sidebar">
      <a class="brand" :href="appUrl()" aria-label="CatppuccinDock 메인 페이지"><span class="brand-mark">c.</span><span class="brand-name">Catppuccin<strong>Dock</strong></span></a>
      <div class="settings-search-control"><Search :size="15" aria-hidden="true" /><input v-model="query" type="search" aria-label="설정 기능 검색" placeholder="기능 검색" maxlength="120" @keydown="searchKeydown" /><button v-if="query" aria-label="설정 검색 지우기" @click="query = ''"><X :size="14" /></button></div>
      <div class="navigation-heading"><span>설정 메뉴</span><div class="navigation-edit-controls"><button v-if="editingMenu" class="navigation-edit-button" aria-label="메뉴 기본 순서 복원" :disabled="menuBusy" @click="resetMenu"><RotateCcw :size="13" /></button><button class="navigation-edit-button" :aria-label="editingMenu ? '메뉴 순서 편집 완료' : '메뉴 순서 편집'" :aria-pressed="editingMenu" :disabled="menuBusy" @click="editingMenu = !editingMenu"><Check v-if="editingMenu" :size="13" /><Pencil v-else :size="13" /><span>{{ editingMenu ? '완료' : '순서 편집' }}</span></button></div></div>
      <p v-if="menuError" class="navigation-error" role="alert">{{ menuError }}</p>
      <nav v-reorder="{ kind: 'navigation', disabled: !editingMenu || menuBusy }" class="navigation" :class="{ 'navigation-editing': editingMenu }" aria-label="설정 메뉴"><div v-for="item in orderedGroups" :key="item.id" :data-sort-id="item.id" class="navigation-entry"><button v-if="editingMenu" class="reorder-handle navigation-grip" :aria-label="`${item.name} 메뉴 순서 변경 · 위아래 방향키`" :disabled="menuBusy" @keydown.up.prevent.stop="moveMenu(item.id, -1)" @keydown.down.prevent.stop="moveMenu(item.id, 1)"><GripVertical :size="14" /></button><button class="nav-item" :class="{ active: !searching && activeGroup.id === item.id }" :title="item.name" @click="selectGroup(item)"><component :is="groupIcons[item.id] || item.sections[0].icon" :size="18" /><span>{{ item.name }}</span></button></div></nav>
      <div class="sidebar-bottom"><button class="theme-toggle" @click="toggleTheme"><Sun v-if="theme === 'mocha'" :size="17" /><Moon v-else :size="17" /><span>{{ theme === 'mocha' ? '라이트 모드' : '다크 모드' }}</span></button><span class="sidebar-version">{{ username }} · {{ role === 'admin' ? '관리자' : '일반 사용자' }}</span></div>
      <div class="sidebar-resize-handle" role="separator" tabindex="0" aria-label="설정 메뉴 너비 조절" aria-orientation="vertical" aria-valuemin="200" :aria-valuemax="sidebar.max.value" :aria-valuenow="sidebar.width.value" title="드래그로 너비 조절 · 두 번 클릭으로 초기화" @pointerdown="sidebar.begin" @pointermove="sidebar.move" @pointerup="sidebar.finish" @pointercancel="sidebar.finish" @lostpointercapture="sidebar.finish" @dblclick="sidebar.reset" @keydown="sidebar.keydown"></div>
    </aside>
    <main class="main-content">
      <header class="topbar"><a class="back-to-home" :href="appUrl()"><ArrowLeft :size="16" /><span>메인으로</span></a><span class="management-account">{{ username }} <span class="role-badge">{{ role === 'admin' ? '관리자' : '일반 사용자' }}</span></span><LogoutButton /></header>
      <div class="management-heading"><span class="section-kicker">MAKE IT YOURS</span><h1 id="settings-heading" ref="heading" tabindex="-1">{{ searching ? '설정 검색' : activeGroup.name }}</h1></div>
      <section v-if="searching" class="settings-section settings-search-results" aria-label="설정 검색 결과"><p class="settings-description" role="status">검색 결과 {{ results.length }}개</p><button v-for="result in results" :key="result.section + result.title" class="settings-search-result" @click="openResult(result)"><span><small>{{ result.sectionName }}</small><strong>{{ result.title }}</strong><span>{{ result.description }}</span></span><ChevronRight :size="18" /></button><p v-if="!results.length" class="settings-empty">일치하는 기능이 없습니다. 다른 이름이나 관련 키워드로 검색해 보세요.</p></section>
      <div v-show="!searching" ref="content">
        <div v-if="activeGroup.sections.length > 1" class="settings-subnavigation" role="tablist" aria-label="세부 설정" @keydown="subsectionKeydown"><button v-for="item in activeGroup.sections" :id="`settings-tab-${item.id}`" :key="item.id" type="button" role="tab" :aria-selected="section.id === item.id" :tabindex="section.id === item.id ? 0 : -1" aria-controls="settings-section-panel" @click="selectSection(item.id)"><component :is="item.icon" :size="15" aria-hidden="true" /><span>{{ item.name }}</span></button></div>
        <section id="settings-section-panel" :role="activeGroup.sections.length > 1 ? 'tabpanel' : 'region'" :aria-labelledby="activeGroup.sections.length > 1 ? `settings-tab-${section.id}` : 'settings-heading'" tabindex="0"><component :is="section.view" :key="section.id" v-bind="section.props || {}" :manage="section.manage || false" :is-admin="role === 'admin'" /></section>
      </div>
    </main>
  </div>
</template>
