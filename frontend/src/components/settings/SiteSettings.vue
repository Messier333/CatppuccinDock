<script setup>
import ThemeSelect from "../common/ThemeSelect.vue";
import { computed, onMounted, ref } from "vue";
import { api } from "../../lib/api.js";
import { appUrl } from "../../lib/navigation.js";
const props = defineProps({ settingsSection: { type: String, default: 'all' } });
const settings = ref(null);
const sso = ref(null);
const secret = ref("");
const error = ref("");
const notice = ref("");
const busy = ref(false);
const loginPolicy = computed({
  get: () => !sso.value?.enabled ? 'local' : sso.value.login_mode === 'sso_only' ? 'sso_only' : 'both',
  set: value => { sso.value.enabled = value !== 'local'; sso.value.login_mode = value === 'sso_only' ? 'sso_only' : 'both'; },
});
onMounted(async () => {
  try {
    [settings.value, sso.value] = await Promise.all([
      props.settingsSection !== 'sso' ? api('admin/settings') : null,
      props.settingsSection !== 'portal' ? api('admin/sso') : null,
    ]);
    if (sso.value && !sso.value.redirect_uri) sso.value.redirect_uri = appUrl('api/auth/oidc/callback');
  } catch (cause) { error.value = cause.message; }
});
async function save(kind) {
  busy.value = true; error.value = ""; notice.value = "";
  try {
    if (kind === 'sso') {
      const { enabled, login_mode, label, issuer, client_id, redirect_uri } = sso.value;
      sso.value = await api('admin/sso', { method: 'PUT', body: JSON.stringify({ enabled, login_mode, label, issuer, client_id, redirect_uri, client_secret: secret.value || null }) });
      secret.value = ""; notice.value = "SSO 설정을 저장했어요. 로그인 화면에 바로 적용됩니다.";
    } else {
      await api('admin/settings', { method: 'PUT', body: JSON.stringify(settings.value) }); notice.value = "포털 설정을 저장했어요.";
    }
  } catch (cause) { error.value = cause.message; } finally { busy.value = false; }
}
</script>
<template><section class="settings-section"><p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="notice" class="form-notice" role="status">{{ notice }}</p>
  <div v-if="settings" class="settings-card"><h2>공통 포털 설정</h2><p class="settings-description">모든 사용자에게 적용됩니다.</p><form class="settings-form" @submit.prevent="save('portal')"><label data-settings-anchor="search">기본 검색 엔진<ThemeSelect v-model="settings.search_engine" label="기본 검색 엔진" :options="[{ value: 'd', label: 'DuckDuckGo' }, { value: 'g', label: 'Google' }, { value: 'p', label: 'Perplexity' }, { value: 'y', label: 'Yandex' }]" /></label><label data-settings-anchor="search-window">웹 검색 결과 열기<ThemeSelect v-model="settings.search_open_mode" label="웹 검색 결과 열기" :options="[{ value: 'same_tab', label: '현재 탭에서 열기' }, { value: 'new_tab', label: '새 탭에서 열기' }]" /><small>웹 검색·자동완성·검색 엔진 버튼에 적용합니다.</small></label><label data-settings-anchor="clock">시간 표시 형식<ThemeSelect v-model="settings.clock_format" label="시간 표시 형식" :options="[{ value: '24h', label: '24시간 · 18:30' }, { value: '12h', label: '12시간 · 06:30 PM' }]" /></label><label>시간대<input v-model="settings.timezone" required placeholder="Asia/Seoul" maxlength="100" /><small>한국은 Asia/Seoul을 사용하세요. 날짜와 시계가 이 시간대에 맞춰 표시됩니다.</small></label><label data-settings-anchor="weather">날씨 위치<input v-model="settings.weather_location" required maxlength="80" placeholder="Seoul 또는 서울" /><small>도시명을 입력하세요. 동명이면 국가를 함께 입력하세요. 예: Seoul, KR</small></label><label>온도 단위<ThemeSelect v-model="settings.temperature_scale" label="온도 단위" :options="[{ value: 'C', label: '섭씨 °C' }, { value: 'F', label: '화씨 °F' }]" /></label><label data-settings-anchor="bookmark-shelf">즐겨찾기·최근 사용 표시<ThemeSelect v-model="settings.bookmark_shelf_display" label="즐겨찾기·최근 사용 표시" :options="[{ value: 'labels', label: '아이콘 + 이름' }, { value: 'icons', label: '아이콘만' }]" /><small>아이콘만 표시하면 버튼과 링크 이름을 숨기고, 마우스를 올렸을 때 이름을 보여줍니다.</small></label><p class="settings-description">날씨: <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Open-Meteo</a> · 위치 정보: <a href="https://www.geonames.org/" target="_blank" rel="noopener noreferrer">GeoNames</a>. 온도는 10분마다 갱신됩니다.</p><button class="primary-button" :disabled="busy">포털 설정 저장</button></form></div>
  <div v-if="sso" class="settings-card" data-settings-anchor="sso"><div class="card-heading"><h2>SSO · OpenID Connect</h2><span class="role-badge">{{ sso.enabled ? '활성' : '비활성' }}</span></div><p class="settings-description">Authentik·Keycloak 등 OIDC 서비스를 등록하세요. 저장하면 서버 재시작 없이 적용됩니다. 사용자 관리에서 추가하거나 연결한 계정만 로그인할 수 있습니다.</p>
    <form class="settings-form" @submit.prevent="save('sso')">
      <label>로그인 허용 방식<ThemeSelect v-model="loginPolicy" label="로그인 허용 방식" :disabled="busy" :options="[{ value: 'local', label: '아이디·비밀번호만' }, { value: 'both', label: '아이디·비밀번호 + SSO' }, { value: 'sso_only', label: 'SSO만' }]" /><small>{{ loginPolicy === 'sso_only' ? '로그인 화면에는 SSO 버튼만 표시하며 비밀번호 로그인도 서버에서 차단합니다.' : loginPolicy === 'both' ? '로그인 화면에서 비밀번호와 SSO 중 선택할 수 있습니다.' : '로그인 화면에 아이디와 비밀번호 입력창을 표시합니다.' }}</small></label>
      <p v-if="loginPolicy === 'sso_only'" class="settings-description">먼저 사용자 관리에서 활성 관리자에게 현재 Issuer의 SSO 계정을 연결하세요. 로그인 가능한 관리자가 없는 설정은 저장할 수 없습니다. 이미 로그인한 세션은 유지됩니다.</p>
      <label>로그인 버튼 이름<input v-model="sso.label" required maxlength="60" placeholder="회사 계정으로 로그인" /></label>
      <label>Issuer URL<input v-model="sso.issuer" type="url" :required="sso.enabled" maxlength="1024" placeholder="https://auth.example.com/realms/portal" /><small>인증 서비스가 제공하는 Issuer 주소를 그대로 입력하세요.</small></label>
      <label>Client ID<input v-model="sso.client_id" :required="sso.enabled" maxlength="256" autocomplete="off" /></label>
      <label>Client Secret<input v-model="secret" type="password" autocomplete="new-password" :required="sso.enabled && !sso.has_secret" maxlength="4096" :placeholder="sso.has_secret ? '등록됨 · 비워두면 기존 값 유지' : '인증 서비스의 Client Secret'" /><small>암호화하여 저장하며, 저장한 값은 다시 표시하지 않습니다.</small></label>
      <label>Callback URL<input v-model="sso.redirect_uri" type="url" :required="sso.enabled" maxlength="2048" /><small>인증 서비스에도 같은 주소를 허용된 Redirect URI로 등록하세요.</small></label>
      <button class="primary-button" :disabled="busy">SSO 설정 저장</button>
    </form>
  </div>
</section></template>
