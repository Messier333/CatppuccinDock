<script setup>
import ThemeSelect from "../common/ThemeSelect.vue";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { Plus, Pencil } from "lucide-vue-next";
import { api } from "../../lib/api.js";
import BookmarkIcon from "../common/BookmarkIcon.vue";
import IconPicker from "../bookmarks/IconPicker.vue";
import IconColorPicker from "../bookmarks/IconColorPicker.vue";
import { bookmarkColor } from "../../lib/bookmarkColors.js";
const props = defineProps({ manage: { type: Boolean, default: false } });
const links = ref([]), tabs = ref([]), tabId = ref(''), query = ref(''), error = ref(''), notice = ref(''), busy = ref(false), categoryId = ref(''), dialog = ref(null), target = ref(null);
const loading = ref(true), selected = ref([]);
const available = computed(() => visible.value.filter(link => !link.added));
const allVisibleSelected = computed(() => available.value.length > 0 && available.value.every(link => selected.value.includes(link.id)));
function toggleVisible() {
  const ids = new Set(available.value.map(link => link.id));
  selected.value = allVisibleSelected.value ? selected.value.filter(id => !ids.has(id)) : [...new Set([...selected.value, ...ids])];
}
async function refresh() {
  loading.value = true; error.value = '';
  try { await load(); selected.value = selected.value.filter(id => links.value.some(link => link.id === id && !link.added)); }
  catch (cause) { error.value = cause.message; } finally { loading.value = false; }
}
const editorSequence = ref(0);
const users = ref([]), groups = ref([]);
const iconBusy = ref(false);
const draft = reactive({ name: '', icon: 'world', icon_color: 'auto', published: false, access_mode: 'all', user_ids: [], group_ids: [] });
const visible = computed(() => links.value.filter(item => `${item.name} ${item.url} ${item.source_name}`.toLowerCase().includes(query.value.trim().toLowerCase())));
const categories = computed(() => tabs.value.find(tab => tab.id === tabId.value)?.categories || []);
const selectedCategory = computed(() => categories.value.find(category => category.id === categoryId.value));
watch(tabId, () => { categoryId.value = ''; });
async function load() { links.value = await api(props.manage ? 'admin/library' : 'library'); }
onMounted(async () => {
  try {
    await load();
    if (props.manage) [users.value, groups.value] = await Promise.all([api('admin/users'), api('admin/groups')]);
    if (!props.manage) {
      const portal = await api('portal');
      tabs.value = portal.tabs;
    }
  } catch (cause) { error.value = cause.message; } finally { loading.value = false; }
});
function edit(link) { editorSequence.value++; target.value = link; Object.assign(draft, { name: link.name, icon: link.icon, icon_color: link.icon_color, published: link.published, access_mode: link.access_mode || 'all', user_ids: [...(link.user_ids || [])], group_ids: [...(link.group_ids || [])] }); error.value = ''; dialog.value.showModal(); }
async function save() {
  if (busy.value || iconBusy.value) return;
  busy.value = true; error.value = '';
  try { await api(`admin/library/${target.value.id}`, { method: 'PUT', body: JSON.stringify(draft) }); dialog.value.close(); await load(); notice.value = '공개 링크 설정을 저장했어요.'; }
  catch (cause) { error.value = cause.message; } finally { busy.value = false; }
}
async function addMany(ids) {
  if (!selectedCategory.value || busy.value || !ids.length) return;
  busy.value = true; error.value = ''; notice.value = '';
  try {
    const result = await api('library/add', { method: 'POST', body: JSON.stringify({ category_id: categoryId.value, link_ids: ids }) });
    selected.value = selected.value.filter(id => !ids.includes(id));
    await load(); notice.value = `${result.added}개 링크를 내 메인 패널에 추가했어요.${result.duplicates ? ` 이미 추가한 ${result.duplicates}개는 건너뛰었어요.` : ''}`;
  } catch (cause) { error.value = cause.message; } finally { busy.value = false; }
}
</script>
<template><section class="settings-section">
  <p class="settings-description">{{ manage ? 'API 링크 가져오기에서 선택한 링크만 공개됩니다. 공개 해제 시 이 목록에서 추가한 사용자의 메인 패널에서도 숨겨집니다.' : '관리자가 허용한 링크 중 필요한 것만 내 카테고리에 추가하세요. 추가한 링크의 이름과 아이콘은 내 북마크에서 바꿀 수 있습니다.' }}</p>
  <p v-if="error && !dialog?.open" class="form-error" role="alert">{{ error }}</p><p v-if="notice" class="form-notice" role="status">{{ notice }}</p>
  <div class="settings-card">
    <div class="card-heading"><div><h2>{{ manage ? '공개 링크 관리 목록' : '허용된 공개 링크 목록' }}</h2><p>{{ loading ? '목록을 불러오는 중…' : manage ? `전체 ${links.length}개 · 공개 중 ${links.filter(link => link.published).length}개` : `공개 ${links.length}개 · 내 메인에 추가됨 ${links.filter(link => link.added).length}개` }}</p></div><button class="secondary-button" :disabled="busy || loading" @click="refresh">새로고침</button></div>
    <div class="settings-form"><label>공개 링크 검색<input v-model="query" type="search" aria-label="공개 링크 검색" maxlength="120" /></label></div>
    <div v-if="!manage && available.length" class="card-heading library-selection"><span>{{ selected.length }}개 선택 · 검색 결과 {{ visible.length }}개</span><button class="secondary-button" :disabled="busy" @click="toggleVisible">{{ allVisibleSelected ? '목록 선택 해제' : '목록 전체 선택' }}</button></div>
    <div class="editable-links" :aria-busy="loading"><article v-for="link in visible" :key="link.id" class="editable-link">
      <input v-if="!manage" v-model="selected" type="checkbox" :value="link.id" :disabled="busy || link.added" :aria-label="`${link.name} 선택`" />
      <BookmarkIcon :name="link.icon" :style="{ color: bookmarkColor(link) }" />
      <a :href="link.url" target="_blank" rel="noopener noreferrer"><strong>{{ link.name }}</strong><small>{{ link.url }}</small><small>{{ link.source_name }}</small></a>
      <span v-if="manage" class="role-badge">{{ !link.published ? '비공개' : link.access_mode === 'restricted' ? '대상 지정 공개' : '전체 공개' }}</span>
      <button v-if="manage" class="icon-button" :aria-label="`${link.name} 공개 설정`" @click="edit(link)"><Pencil :size="16" /></button>
      <button v-else class="secondary-button" :disabled="busy || link.added || !selectedCategory" :aria-label="`${link.name} ${link.added ? '추가됨' : '메인에 추가'}`" @click="addMany([link.id])"><Plus v-if="!link.added" :size="14" />{{ link.added ? '추가됨' : '메인에 추가' }}</button>
    </article></div>
    <p v-if="!loading && !visible.length" class="settings-empty">{{ links.length ? '검색 결과가 없습니다. 검색어를 지우면 전체 목록이 표시됩니다.' : manage ? '아직 등록된 공개 링크가 없습니다. API 링크 가져오기에서 사용 방식을 공개로 선택하고 공개할 항목을 가져와 주세요.' : '관리자가 허용한 공개 링크가 아직 없습니다. 관리자가 API 링크 가져오기에서 선택한 링크를 공개하면 여기에 표시됩니다.' }}</p>
  </div>
  <div v-if="!manage" class="settings-card"><h2>선택한 링크를 메인에 추가</h2><div class="library-controls settings-form">
    <label>카테고리<ThemeSelect v-model="tabId" label="카테고리" placeholder="카테고리를 선택해 주세요" :disabled="busy" :options="tabs.map(item => ({ value: item.id, label: item.name }))" /><small v-if="!tabs.length">내 북마크에서 카테고리를 먼저 추가하세요.</small></label>
    <label>세부 카테고리<ThemeSelect v-model="categoryId" label="세부 카테고리" :placeholder="!tabId ? '카테고리를 먼저 선택해 주세요' : categories.length ? '세부 카테고리를 선택해 주세요' : '세부 카테고리가 없습니다'" :disabled="busy || !tabId || !categories.length" :options="categories.map(item => ({ value: item.id, label: item.name }))" /><small v-if="tabId && !categories.length">선택한 카테고리에 세부 카테고리가 없어요. 내 북마크에서 먼저 추가해 주세요.</small></label>
  </div><button class="primary-button" :disabled="busy || loading || !selected.length || !selectedCategory" @click="addMany([...selected])"><Plus :size="15" />선택한 {{ selected.length }}개 메인에 추가</button></div>
  <dialog ref="dialog" v-dialog-dismiss="busy || iconBusy" class="editor-dialog" @cancel="iconBusy && $event.preventDefault()"><form class="settings-form" @submit.prevent="save"><div class="card-heading"><h2>공개 링크 설정</h2><button class="icon-button" type="button" aria-label="닫기" :disabled="busy || iconBusy" @click="dialog.close()">×</button></div><label>링크 이름<input v-model="draft.name" required maxlength="120" /></label><p class="settings-description">{{ target?.url }}</p><IconPicker :key="editorSequence" v-model="draft.icon" :search-term="draft.name" :color="bookmarkColor(draft)" :disabled="busy" @busy="iconBusy = $event" /><IconColorPicker v-if="!draft.icon?.startsWith('upload:')" v-model="draft.icon_color" /><label class="checkbox-label"><input v-model="draft.published" type="checkbox" />일반 사용자에게 공개</label><label>공개 대상<ThemeSelect v-model="draft.access_mode" label="공개 대상" :options="[{value:'all',label:'모든 사용자'},{value:'restricted',label:'선택한 사용자·그룹만'}]" /></label><template v-if="draft.access_mode==='restricted'"><span class="field-label">허용할 사용자</span><div class="selection-list"><label v-for="user in users" :key="user.id" class="checkbox-label"><input v-model="draft.user_ids" type="checkbox" :value="user.id" />{{ user.username }}</label></div><span class="field-label">허용할 그룹</span><div class="selection-list"><label v-for="group in groups" :key="group.id" class="checkbox-label"><input v-model="draft.group_ids" type="checkbox" :value="group.id" />{{ group.name }}</label><small v-if="!groups.length">그룹 관리에서 그룹을 먼저 추가하세요.</small></div><small>사용자 또는 그룹 중 하나에 해당하면 허용됩니다. 관리자는 모든 공개 링크를 확인할 수 있습니다.</small></template><p v-if="error" class="form-error" role="alert">{{ error }}</p><button class="primary-button" :disabled="busy || iconBusy">공개 설정 저장</button></form></dialog>
</section></template>
