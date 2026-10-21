<script setup>
import ThemeSelect from "../common/ThemeSelect.vue";
import { computed, onMounted, reactive, ref } from "vue";
import { Plus, Pencil, Trash2, Download, RefreshCw } from "lucide-vue-next";
import { api } from "../../lib/api.js";
const sources = ref([]);
const providers = ref([]);
const destination = ref('private');
const categories = ref([]);
const selectedSource = ref("");
const categoryId = ref("");
const scheme = ref("auto");
const publicPort = ref("");
const preview = ref(null);
const selected = ref([]);
const error = ref("");
const notice = ref("");
const busy = ref(false);
const dialog = ref(null);
const target = ref(null);
const customDefaults = () => ({ endpoint: 'api/links', items_path: '', url_field: 'url', name_field: 'name', url_format: 'url', auth_type: 'bearer', auth_header: 'X-API-Key' });
const customAPI = reactive(customDefaults());
const needsToken = computed(() => draft.provider !== 'custom' || customAPI.auth_type !== 'none');
const tokenRequired = computed(() => needsToken.value && (!target.value?.has_token || target.value.provider !== draft.provider || target.value.base_url !== draft.base_url || (target.value.custom_api?.auth_type || 'bearer') !== customAPI.auth_type || (target.value.custom_api?.auth_header || 'X-API-Key') !== customAPI.auth_header));
const draft = reactive({ name: "", provider: "npm", base_url: "", token: "", verify_tls: true });
const providerNames = { npm: 'Nginx Proxy Manager', npg: 'Nginx Proxy Guard', zoraxy: 'Zoraxy', custom: '직접 등록한 API' };
const source = computed(() => sources.value.find(item => item.id === selectedSource.value));
const selectable = computed(() => preview.value?.entries.filter(item => destination.value === 'library' ? !item.published : !item.existing) || []);
function changedDestination() { selected.value = selectable.value.map(item => item.id); }
async function loadSources() { sources.value = await api('admin/proxy-sources'); }
onMounted(async () => {
  try {
    await loadSources();
    providers.value = await api('admin/proxy-sources/providers');
    const portal = await api('portal');
    categories.value = portal.tabs.flatMap(tab => tab.categories.map(group => ({ id: group.id, name: `${tab.name} / ${group.name}` })));
    categoryId.value = categories.value[0]?.id || "";
    selectedSource.value = sources.value[0]?.id || "";
    changedSource();
  } catch (cause) { error.value = cause.message; }
});
function changedSource() { preview.value = null; selected.value = []; scheme.value = source.value?.provider === 'zoraxy' ? 'https' : 'auto'; }
function edit(item = null, provider = "npm") {
  target.value = item; error.value = "";
  Object.assign(draft, { name: item?.name || "", provider: item?.provider || provider, base_url: item?.base_url || "", token: "", verify_tls: item?.verify_tls ?? true });
  Object.assign(customAPI, customDefaults(), item?.custom_api || {});
  dialog.value.showModal();
}
async function saveSource() {
  busy.value = true; error.value = "";
  try {
    const saved = await api(`admin/proxy-sources${target.value ? `/${target.value.id}` : ''}`, { method: target.value ? 'PUT' : 'POST', body: JSON.stringify({ ...draft, token: needsToken.value ? draft.token || null : null, custom_api: draft.provider === 'custom' ? { ...customAPI } : null }) });
    draft.token = ""; dialog.value.close(); await loadSources(); selectedSource.value = saved.id; changedSource(); notice.value = "서비스 연결 정보를 저장했어요. 링크 미리 보기로 연결을 확인하세요.";
  } catch (cause) { error.value = cause.message; } finally { busy.value = false; }
}
async function remove(item) {
  if (!window.confirm(`${item.name} 연결을 삭제할까요? 가져온 북마크는 유지됩니다.`)) return;
  busy.value = true; error.value = "";
  try { await api(`admin/proxy-sources/${item.id}`, { method: 'DELETE' }); await loadSources(); selectedSource.value = sources.value[0]?.id || ""; changedSource(); }
  catch (cause) { error.value = cause.message; } finally { busy.value = false; }
}
async function fetchPreview() {
  busy.value = true; error.value = ""; notice.value = ""; preview.value = null;
  try {
    preview.value = await api(`admin/proxy-sources/${selectedSource.value}/preview`, { method: 'POST', body: JSON.stringify({ scheme: scheme.value, public_port: publicPort.value ? Number(publicPort.value) : null }) });
    selected.value = selectable.value.map(item => item.id);
  } catch (cause) { error.value = cause.message; } finally { busy.value = false; }
}
async function importLinks() {
  busy.value = true; error.value = "";
  try {
    const result = await api(`admin/proxy-sources/${selectedSource.value}/import`, { method: 'POST', body: JSON.stringify({ preview_id: preview.value.preview_id, destination: destination.value, category_id: destination.value === 'private' ? categoryId.value : null, entry_ids: selected.value }) });
    notice.value = destination.value === "library" ? `${result.added}개 링크를 일반 사용자에게 공개했어요.${result.duplicates ? ` 이미 공개된 ${result.duplicates}개는 유지했어요.` : ""}` : `${result.added}개 링크를 내 북마크에 추가했어요.${result.duplicates ? ` 중복 ${result.duplicates}개는 건너뛰었어요.` : ""}`;
    preview.value = null; selected.value = [];
  } catch (cause) { error.value = cause.message; } finally { busy.value = false; }
}
</script>
<template><section class="settings-section">
  <div class="management-toolbar"><p class="settings-description">기본 지원 앱은 카드에서 연결하세요. 다른 앱은 서비스 등록에서 API 주소와 JSON 응답 필드를 직접 지정할 수 있습니다. 내 북마크에 저장하거나 일반 사용자에게 공개할 수 있습니다. 연결 정보는 DB에 저장됩니다.</p><button class="primary-button" :disabled="busy" @click="edit(null, 'custom')"><Plus :size="15" />서비스 등록</button></div>
  <div class="provider-cards"><button v-for="item in providers" :key="item.id" class="provider-card" :disabled="busy" @click="edit(null, item.id)"><strong>{{ item.short_name }}</strong><span>{{ item.name }}</span><small>연결 등록 +</small></button></div>
  <p v-if="error && !dialog?.open" class="form-error" role="alert">{{ error }}</p><p v-if="notice" class="form-notice" role="status">{{ notice }}</p>
  <div v-if="!sources.length" class="settings-card settings-empty">기본 지원 앱을 선택하거나 서비스 등록으로 다른 앱의 링크 목록 API를 연결하세요.</div>
  <div v-else class="settings-card"><h2>연결 서비스</h2>
    <form class="settings-form" @submit.prevent="fetchPreview">
      <label>서비스<ThemeSelect v-model="selectedSource" label="연결 서비스" :disabled="busy" @change="changedSource" :options="sources.map(item => ({ value: item.id, label: `${item.name} · ${providerNames[item.provider]}` }))" /></label>
      <div v-if="source" class="inline-actions"><span class="settings-description">{{ source.base_url }}</span><button class="icon-button" type="button" aria-label="서비스 수정" :disabled="busy" @click="edit(source)"><Pencil :size="15" /></button><button class="icon-button danger" type="button" aria-label="서비스 삭제" :disabled="busy" @click="remove(source)"><Trash2 :size="15" /></button></div>
      <label v-if="source?.provider !== 'custom' || source?.custom_api?.url_format === 'domain'">가져올 링크 프로토콜<ThemeSelect v-model="scheme" label="가져올 링크 프로토콜" :disabled="busy" @change="preview = null" :options="[...(source?.provider !== 'zoraxy' ? [{ value: 'auto', label: source?.provider === 'custom' ? '기본 HTTPS' : '자동 · 호스트의 인증서 설정 사용' }] : []), { value: 'https', label: 'HTTPS' }, { value: 'http', label: 'HTTP' }]" /><small v-if="source?.provider === 'zoraxy'">Zoraxy의 전역 TLS 설정에 맞게 선택하세요. TLS 우회 호스트는 HTTP로 가져옵니다.</small></label>
      <label v-if="source?.provider !== 'custom' || source?.custom_api?.url_format === 'domain'">외부 접속 포트 (선택)<input v-model="publicPort" type="number" min="1" max="65535" placeholder="기본 포트 사용" :disabled="busy" @input="preview = null" /></label>
      <button class="primary-button" :disabled="busy"><RefreshCw :size="15" />{{ busy ? '처리 중…' : '링크 미리 보기' }}</button>
    </form>
  </div>
  <div v-if="preview" class="settings-card"><div class="card-heading"><div><h2>가져올 링크 선택</h2><p>{{ preview.entries.length }}개 링크 · {{ preview.skipped }}개 항목 제외 · 10분 동안 유효</p></div><button class="secondary-button" :disabled="busy" @click="selected = selected.length === selectable.length ? [] : selectable.map(item => item.id)">{{ selected.length === selectable.length ? '선택 해제' : '전체 선택' }}</button></div>
    <div class="settings-form"><label>가져온 링크 사용 방식<ThemeSelect v-model="destination" label="가져온 링크 사용 방식" :disabled="busy" @change="changedDestination" :options="[{ value: 'private', label: '내 북마크에 저장' }, { value: 'library', label: '선택한 링크를 일반 사용자에게 공개' }]" /></label><p class="settings-description">{{ destination === "library" ? "선택한 링크만 공개 목록에 등록됩니다. 사용자는 공개 링크 설정에서 원하는 항목을 메인에 추가합니다." : "선택한 링크를 관리자 본인의 카테고리에 저장합니다." }}</p></div>
    <div class="proxy-preview"><label v-for="entry in preview.entries" :key="entry.id" class="proxy-entry"><input v-model="selected" type="checkbox" :value="entry.id" :disabled="busy || (destination === 'library' ? entry.published : entry.existing)" :aria-label="entry.url" /><span><strong>{{ entry.name }}</strong><small>{{ entry.url }}</small></span><span v-if="destination === 'library' ? entry.published : entry.existing" class="role-badge">{{ destination === 'library' ? '공개 중' : '이미 등록됨' }}</span></label><p v-if="!preview.entries.length" class="settings-empty">가져올 수 있는 호스트가 없습니다.</p></div>
    <form class="settings-form" @submit.prevent="importLinks"><label v-if="destination === 'private'">저장할 카테고리<ThemeSelect v-model="categoryId" label="저장할 카테고리" required :disabled="busy" :options="categories.map(item => ({ value: item.id, label: item.name }))" /><small v-if="!categories.length">내 북마크에서 카테고리를 먼저 추가하세요.</small></label><button class="primary-button" :disabled="busy || !selected.length || (destination === 'private' && !categoryId)"><Download :size="15" />{{ selected.length }}개 {{ destination === 'library' ? '링크 공개' : '링크 가져오기' }}</button></form>
  </div>
  <dialog ref="dialog" v-dialog-dismiss="busy" @close="draft.token = ''" class="editor-dialog"><form class="settings-form" @submit.prevent="saveSource"><div class="card-heading"><h2>{{ target ? '서비스 수정' : draft.provider === 'custom' ? '다른 앱 서비스 등록' : `${providerNames[draft.provider]} 연결 등록` }}</h2><button class="icon-button" type="button" aria-label="닫기" :disabled="busy" @click="dialog.close(); draft.token = ''">×</button></div>
    <label>{{ draft.provider === 'custom' ? '앱 / 서비스 이름' : '연결 이름' }}<input v-model="draft.name" required maxlength="80" placeholder="우리 집 프록시" /></label>
    <p class="settings-description">{{ draft.provider === 'custom' ? 'GET으로 JSON 목록을 제공하는 API를 연결합니다. API 문서의 경로와 필드명을 지정해 주세요. 별도 로그인 흐름이나 GraphQL·다중 페이지 조회가 필요한 API는 전용 연동 개발이 필요합니다.' : providerNames[draft.provider] + '의 호스트 목록 API를 사용합니다.' }}</p>
    <label>관리 서비스 기본 주소<input v-model="draft.base_url" type="url" required maxlength="2048" placeholder="http://192.168.1.10:81" /><small>{{ draft.provider === 'custom' ? 'API를 제공하는 서버 주소입니다. 인증 키를 주소에 넣지 마세요.' : '관리 UI/API의 기본 주소입니다. 앱에 맞는 API 경로가 자동으로 붙습니다.' }}</small></label>
    <template v-if="draft.provider === 'custom'">
      <label>목록 API 경로<input v-model="customAPI.endpoint" required maxlength="1024" placeholder="api/v1/links" /><small>기본 주소에 붙는 GET 경로입니다. 예: api/v1/links?limit=1000 · 키는 인증 헤더로 입력하세요.</small></label>
      <label>목록 배열 경로<input v-model="customAPI.items_path" maxlength="200" placeholder="data.items · 최상위 배열이면 비움" /><small>응답이 {"data":{"items":[…]}}이면 data.items를 입력합니다.</small></label>
      <label>URL 필드 경로<input v-model="customAPI.url_field" maxlength="200" placeholder="url 또는 domain_names" /><small>각 항목의 URL/도메인 필드입니다. 문자열 배열도 지원합니다. 목록 자체가 문자열 배열이면 비워 두세요.</small></label>
      <label>이름 필드 경로 (선택)<input v-model="customAPI.name_field" maxlength="200" placeholder="name · 없으면 도메인 사용" /></label>
      <label>링크 데이터 형식<ThemeSelect v-model="customAPI.url_format" label="링크 데이터 형식" :options="[{ value: 'url', label: '전체 URL · https://app.example.com/path' }, { value: 'domain', label: '도메인 · app.example.com' }]" /></label>
      <label>API 인증 방식<ThemeSelect v-model="customAPI.auth_type" label="API 인증 방식" :options="[{ value: 'bearer', label: 'Bearer 토큰' }, { value: 'header', label: 'API 키 헤더' }, { value: 'none', label: '인증 없음' }]" /></label>
      <label v-if="customAPI.auth_type === 'header'">인증 헤더 이름<input v-model="customAPI.auth_header" required maxlength="80" placeholder="X-API-Key" /><small>X-로 시작하는 헤더 또는 Authorization을 지정하세요. 키 값은 아래 API 토큰에 입력합니다.</small></label>
    </template>
    <label v-if="needsToken">{{ draft.provider === 'zoraxy' ? 'Plugin API 키' : 'API 토큰' }}<input v-model="draft.token" type="password" autocomplete="new-password" :required="tokenRequired" maxlength="8192" :placeholder="target?.has_token ? '비워두면 기존 토큰 유지' : customAPI.auth_type === 'header' && draft.provider === 'custom' ? '헤더에 넣을 키 값' : 'Bearer 접두사 없이 입력'" /><small>{{ draft.provider === 'zoraxy' ? 'Plugin API 키에 /api/proxy/list 읽기 권한을 허용하세요.' : draft.provider === 'npm' ? 'NPM에서 발급한 Bearer 액세스 토큰을 사용하세요. 토큰 만료 시 갱신해야 합니다.' : draft.provider === 'npg' ? '호스트 조회 권한이 있는 ng_ API 토큰을 사용하세요.' : '이 API의 읽기 권한이 있는 토큰을 사용하세요.' }} 토큰은 암호화하여 저장합니다.</small></label>
    <label class="checkbox-label"><input v-model="draft.verify_tls" type="checkbox" />TLS 인증서 검증</label>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p><button class="primary-button" :disabled="busy">연결 정보 저장</button>
  </form></dialog>
</section></template>
