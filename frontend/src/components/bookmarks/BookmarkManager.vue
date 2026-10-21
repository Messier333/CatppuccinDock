<script setup>
import ThemeSelect from "../common/ThemeSelect.vue";
import { computed, nextTick, onMounted, reactive, ref } from "vue";
import { Plus, Pencil, Trash2, GripVertical, Star } from "lucide-vue-next";
import { api } from "../../lib/api.js";
import BookmarkIcon from "../common/BookmarkIcon.vue";
import IconPicker from "./IconPicker.vue";
import IconColorPicker from "./IconColorPicker.vue";
import BackgroundPicker from "../backgrounds/BackgroundPicker.vue";
import { reorderDirective } from "../../directives/reorder.js";
import { bookmarkColor } from "../../lib/bookmarkColors.js";

import BookmarkBulkEditor from './BookmarkBulkEditor.vue';
const portal = ref(null);
async function toggleFavorite(link) {
  const previous = !!link.favorite; link.favorite = !previous;
  try { await api(`bookmark-tools/${link.id}/favorite`,{method:'PUT',body:JSON.stringify({favorite:link.favorite})}); }
  catch (cause) { link.favorite = previous; error.value = cause.message; }
}

const selectedTab = ref("");
const selectedCategory = ref("");
const error = ref("");
const notice = ref("");
const undoId = ref("");
const busy = ref(false);
const savingOrder = ref(false);
const backgroundBusy = ref(false);
const dialog = ref(null);
const editor = reactive({ type: "bookmark", id: "", sequence: 0 });
const draft = reactive({});
const tab = computed(() => portal.value?.tabs.find(item => item.id === selectedTab.value));
const categories = computed(() => tab.value?.categories || []);
const category = computed(() => categories.value.find(item => item.id === selectedCategory.value));
const allCategories = computed(() => portal.value?.tabs.flatMap(item => item.categories.map(group => ({ ...group, label: `${item.name} / ${group.name}` }))) || []);
const draftColor = computed(() => {
  const destination = allCategories.value.find(item => item.id === draft.category_id);
  const existingIndex = destination?.links.findIndex(item => item.id === editor.id) ?? -1;
  const index = destination?.links.filter(item => item.id !== editor.id && item.position <= Number(draft.position)).length ?? 0;
  return bookmarkColor(draft, existingIndex >= 0 && Number(draft.position) === destination.links[existingIndex].position ? existingIndex : index);
});
const resource = { tab: "tabs", category: "categories", bookmark: "bookmarks" };
const labels = { tab: "탭", category: "카테고리", bookmark: "북마크" };

async function load() {
  portal.value = await api("portal");
  if (!portal.value.tabs.some(item => item.id === selectedTab.value)) selectedTab.value = portal.value.tabs[0]?.id || "";
  if (!categories.value.some(item => item.id === selectedCategory.value)) selectedCategory.value = categories.value[0]?.id || "";
}

function orderItems(kind, parentId) {
  if (kind === 'tabs') return portal.value.tabs;
  if (kind === 'categories') return portal.value.tabs.find(item => item.id === parentId)?.categories;
  return portal.value.tabs.flatMap(item => item.categories).find(item => item.id === parentId)?.links;
}
async function reorder(kind, parentId, ids) {
  if (savingOrder.value || busy.value) return;
  const items = orderItems(kind, parentId);
  if (!items || items.every((item,index) => item.id === ids[index])) return;
  const previous = [...items];
  const byId = new Map(items.map(item => [item.id, item]));
  if (ids.some(id => !byId.has(id))) return;
  items.splice(0, items.length, ...ids.map(id => byId.get(id)));
  savingOrder.value = true; error.value = ''; notice.value = '순서를 저장하는 중이에요…';
  try {
    const result = await api('reorder', { method: 'POST', body: JSON.stringify({ kind, parent_id: parentId || null, ids }) });
    undoId.value = result.undo_id || '';
    items.forEach((item,index) => item.position = index);
    notice.value = '순서를 저장했어요. 메인 패널에도 반영됩니다.';
  } catch (cause) {
    items.splice(0, items.length, ...previous); error.value = cause.message; notice.value = '';
    try { await load(); } catch { /* Keep the restored local order if reconnecting also fails. */ }
  } finally { savingOrder.value = false; }
}
const vReorder = reorderDirective(reorder);
function moveKey(event, kind, parentId, index) {
  const direction = ['ArrowUp','ArrowLeft'].includes(event.key) ? -1 : ['ArrowDown','ArrowRight'].includes(event.key) ? 1 : 0;
  if (!direction) return;
  event.preventDefault();
  const items = orderItems(kind, parentId);
  const target = index + direction;
  if (!items || target < 0 || target >= items.length || savingOrder.value) return;
  const ids = items.map(item => item.id);
  [ids[index], ids[target]] = [ids[target], ids[index]];
  const handle = event.currentTarget;
  reorder(kind, parentId, ids).then(() => nextTick(() => handle.focus()));
}

onMounted(async () => { try { await load(); } catch (cause) { error.value = cause.message; } });
function selectTab(id) { selectedTab.value = id; selectedCategory.value = categories.value[0]?.id || ""; }
function edit(type, item = null) {
  if (savingOrder.value || busy.value || backgroundBusy.value) return;
  error.value = "";
  editor.type = type;
  editor.id = item?.id || "";
  editor.sequence++;
  Object.assign(draft, { name: item?.name || "", url: item?.url || "https://", tab_id: item?.tab_id || selectedTab.value, category_id: item?.category_id || selectedCategory.value || allCategories.value[0]?.id || "", banner: "none", background_id: item?.background_id || null, icon: item?.icon || "world", icon_color: item?.icon_color || "auto", managed: item?.managed || false, position: item?.position ?? (type === "tab" ? portal.value.tabs.length : type === "category" ? categories.value.length : category.value?.links.length || 0) });
  dialog.value.showModal();
}
async function undo() {
  if (!undoId.value || busy.value || savingOrder.value) return;
  busy.value = true; error.value = '';
  try { await api(`trash/${undoId.value}/restore`, { method: 'POST' }); undoId.value = ''; await load(); notice.value = '이전 상태로 되돌렸어요.'; }
  catch (cause) { error.value = cause.message; } finally { busy.value = false; }
}
async function save() {
  if (busy.value || backgroundBusy.value) return;
  busy.value = true;
  error.value = "";
  const data = { name: draft.name, position: Number(draft.position) };
  if (editor.type === "tab") Object.assign(data, { banner: draft.banner, background_id: draft.background_id || null });
  if (editor.type === "category") data.tab_id = draft.tab_id;
  if (editor.type === "bookmark") Object.assign(data, { category_id: draft.category_id, url: draft.url, icon: draft.icon, icon_color: draft.icon_color });
  try {
    await api(`${resource[editor.type]}${editor.id ? `/${editor.id}` : ""}`, { method: editor.id ? "PUT" : "POST", body: JSON.stringify(data) });
    await load();
    dialog.value.close();
    notice.value = "저장했어요. 메인 페이지에도 반영됩니다.";
  } catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
}
async function remove(type, item) {
  if (savingOrder.value) return;
  if (!window.confirm(`‘${item.name}’ ${labels[type]}을 삭제할까요?${type !== "bookmark" ? " 포함된 북마크도 삭제됩니다." : ""}`)) return;
  error.value = "";
  try { const result = await api(`${resource[type]}/${item.id}`, { method: "DELETE" }); undoId.value = result.trash_id || ""; await load(); notice.value = "휴지통으로 이동했어요."; }
  catch (cause) { error.value = cause.message; }
}
</script>
<template>
  <section class="settings-section">
    <p class="settings-description">손잡이를 드래그해 탭·카테고리·북마크 순서를 바꾸세요. 놓으면 자동 저장됩니다. 손잡이에서 방향키로도 이동할 수 있어요.</p>
    <p v-if="error && !dialog?.open" class="form-error" role="alert">{{ error }}</p><p v-if="notice" class="form-notice" role="status">{{ notice }} <button v-if="undoId" class="secondary-button" :disabled="busy || savingOrder" @click="undo">실행 취소</button></p>
    <template v-if="portal"><BookmarkBulkEditor :portal="portal" @changed="load" />
      <div class="management-toolbar"><div class="tab-pills sortable-pills" v-reorder="{ kind: 'tabs', disabled: savingOrder || busy }"><div v-for="(item,index) in portal.tabs" :key="item.id" :data-sort-id="item.id" class="sortable-pill" :class="{ selected: item.id === selectedTab }"><button class="reorder-handle" :aria-label="`${item.name} 탭 순서 이동`" title="드래그 또는 방향키로 이동" :disabled="savingOrder || busy" @keydown="moveKey($event, 'tabs', null, index)"><GripVertical :size="13" /></button><button @click="selectTab(item.id)">{{ item.name }}</button></div></div><button class="secondary-button" @click="edit('tab')"><Plus :size="15" />탭 추가</button></div>
      <div v-if="tab" class="settings-card">
        <div class="card-heading"><div><h2>{{ tab.name }}</h2><p>탭과 카테고리를 구성하세요.</p></div><div class="inline-actions"><button class="icon-button" aria-label="탭 수정" title="탭 수정" @click="edit('tab', tab)"><Pencil :size="16" /></button><button class="icon-button danger" aria-label="탭 삭제" title="탭 삭제" @click="remove('tab', tab)"><Trash2 :size="16" /></button></div></div>
        <div class="management-toolbar"><div class="tab-pills sortable-pills" v-reorder="{ kind: 'categories', parentId: selectedTab, disabled: savingOrder || busy }"><div v-for="(item,index) in categories" :key="item.id" :data-sort-id="item.id" class="sortable-pill" :class="{ selected: item.id === selectedCategory }"><button class="reorder-handle" :aria-label="`${item.name} 카테고리 순서 이동`" title="드래그 또는 방향키로 이동" :disabled="savingOrder || busy" @keydown="moveKey($event, 'categories', selectedTab, index)"><GripVertical :size="13" /></button><button @click="selectedCategory = item.id">{{ item.name }}</button></div></div><button class="secondary-button" @click="edit('category')"><Plus :size="15" />카테고리 추가</button></div>
        <template v-if="category">
          <div class="card-heading category-heading"><h3>{{ category.name }}</h3><div class="inline-actions"><button class="icon-button" aria-label="카테고리 수정" @click="edit('category', category)"><Pencil :size="15" /></button><button class="icon-button danger" aria-label="카테고리 삭제" @click="remove('category', category)"><Trash2 :size="15" /></button><button class="primary-button" @click="edit('bookmark')"><Plus :size="15" />북마크 추가</button></div></div>
          <div class="editable-links sortable-bookmarks" v-reorder="{ kind: 'bookmarks', parentId: selectedCategory, disabled: savingOrder || busy }"><div v-for="(link,index) in category.links" :key="link.id" :data-sort-id="link.id" class="editable-link"><button class="reorder-handle" :aria-label="`${link.name} 북마크 순서 이동`" title="드래그 또는 방향키로 이동" :disabled="savingOrder || busy" @keydown="moveKey($event, 'bookmarks', selectedCategory, index)"><GripVertical :size="17" /></button><span class="editable-link-icon" :style="{ color: bookmarkColor(link, index) }"><BookmarkIcon :name="link.icon" /></span><a :href="link.url" target="_blank" rel="noopener noreferrer"><strong>{{ link.name }}</strong><small>{{ link.url }}</small></a><div class="inline-actions"><button class="icon-button favorite-toggle" :class="{'is-favorite':link.favorite}" :aria-label="`${link.name} 즐겨찾기 ${link.favorite ? '해제' : '추가'}`" :aria-pressed="!!link.favorite" @click="toggleFavorite(link)"><Star :size="15" :fill="link.favorite ? 'currentColor' : 'none'" /></button><button class="icon-button" :aria-label="`${link.name} 수정`" @click="edit('bookmark', link)"><Pencil :size="16" /></button><button class="icon-button danger" :aria-label="`${link.name} 삭제`" @click="remove('bookmark', link)"><Trash2 :size="16" /></button></div></div></div>
          <p v-if="!category.links.length" class="settings-empty">아직 북마크가 없어요. 첫 링크를 추가해 보세요.</p>
        </template><p v-else class="settings-empty">카테고리를 추가하면 북마크를 저장할 수 있어요.</p>
      </div>
    </template><p v-else-if="!error" role="status">북마크를 불러오는 중이에요…</p>
    <dialog ref="dialog" v-dialog-dismiss="busy || backgroundBusy" class="editor-dialog" @cancel="backgroundBusy || busy ? $event.preventDefault() : error = ''"><form class="settings-form" @submit.prevent="save"><div class="card-heading"><h2>{{ labels[editor.type] }} {{ editor.id ? '수정' : '추가' }}</h2><button class="icon-button" type="button" aria-label="닫기" :disabled="busy || backgroundBusy" @click="dialog.close()">×</button></div>
      <label>이름<input v-model="draft.name" name="name" required :maxlength="editor.type === 'bookmark' ? 120 : 80" /></label>
      <template v-if="editor.type === 'bookmark'"><label>주소<input v-model="draft.url" name="url" type="url" required maxlength="2048" :readonly="draft.managed" /></label><label>카테고리<ThemeSelect v-model="draft.category_id" label="카테고리" required :options="allCategories.map(item => ({ value: item.id, label: item.label }))" /></label><p v-if="draft.managed" class="settings-description">공개 링크의 주소는 관리자가 관리합니다. 이름·아이콘·카테고리를 바꿀 수 있습니다.</p><IconPicker :key="editor.sequence" v-model="draft.icon" :search-term="draft.name" :color="draftColor" :disabled="busy" @busy="backgroundBusy = $event" /><IconColorPicker v-if="!draft.icon?.startsWith('upload:')" v-model="draft.icon_color" /></template>
      <label v-if="editor.type === 'category'">탭<ThemeSelect v-model="draft.tab_id" label="탭" required :options="(portal?.tabs || []).map(item => ({ value: item.id, label: item.name }))" /></label>
      <BackgroundPicker v-if="editor.type === 'tab'" :key="editor.sequence" v-model="draft.background_id" v-model:banner="draft.banner" @busy="backgroundBusy = $event" />
      <label>표시 순서<input v-model="draft.position" type="number" min="0" max="10000" required /><small>작은 숫자가 먼저 표시됩니다. 목록에서 드래그로도 바꿀 수 있어요.</small></label><p v-if="error" class="form-error" role="alert">{{ error }}</p><button class="primary-button" :disabled="busy || backgroundBusy">{{ busy ? '저장 중…' : '저장' }}</button>
    </form></dialog>
  </section>
</template>
