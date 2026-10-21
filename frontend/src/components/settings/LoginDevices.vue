<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { LogOut, Monitor, RefreshCw, Smartphone, Tablet } from 'lucide-vue-next';
import { api } from '../../lib/api.js';
import { appUrl } from '../../lib/navigation.js';

const props = defineProps({ revision: { type: Number, default: 0 }, disabled: Boolean });
const emit = defineEmits(['busy']);
const data = ref(null), loading = ref(false), busy = ref(false), error = ref(''), notice = ref('');
const offset = ref(0), confirmAll = ref(false);
const pageSize = 5;
const rows = computed(() => [
  ...(data.value?.current_session ? [{ ...data.value.current_session, current: true }] : []),
  ...(data.value?.items || []),
]);
const totalOthers = computed(() => data.value?.total_others || 0);
const canAct = computed(() => !busy.value && !loading.value && !props.disabled);
watch(() => busy.value || loading.value, value => emit('busy', value), { flush: 'sync' });
const icons = { desktop: Monitor, mobile: Smartphone, tablet: Tablet, unknown: Monitor };
let controller, timer, version = 0;
function formatTime(value) { return value ? new Date(value * 1000).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }) : '기록 없음'; }
function isoTime(value) { return value ? new Date(value * 1000).toISOString() : undefined; }
async function load(nextOffset = offset.value) {
  controller?.abort();
  controller = new AbortController();
  const current = ++version;
  loading.value = true; error.value = '';
  try {
    const result = await api(`account/sessions?offset=${nextOffset}&limit=${pageSize}`, { signal: controller.signal });
    if (current !== version) return;
    if (nextOffset > 0 && !(result.items || []).length) return await load(0);
    data.value = result; offset.value = nextOffset;
  } catch (cause) { if (current === version && cause.name !== 'AbortError') error.value = cause.message; }
  finally { if (current === version) loading.value = false; }
}
async function revoke(id) {
  if (!canAct.value) return;
  busy.value = true; notice.value = ''; error.value = ''; confirmAll.value = false;
  try {
    const result = await api(`account/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (result.current_revoked) { window.location.replace(appUrl('login/')); return; }
    notice.value = '선택한 기기를 로그아웃했어요.';
    await load();
  } catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
}
async function revokeOthers() {
  if (!canAct.value) return;
  busy.value = true; notice.value = ''; error.value = '';
  try {
    await api('account/sessions/revoke-others', { method: 'POST' });
    confirmAll.value = false; notice.value = '현재 기기를 제외한 모든 기기를 로그아웃했어요.';
    await load(0);
  } catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
}
function refreshVisible() { if (document.visibilityState === 'visible' && canAct.value) load(); }
watch(() => props.revision, () => { notice.value = ''; confirmAll.value = false; load(0); });
onMounted(() => { load(); timer = setInterval(refreshVisible, 60_000); document.addEventListener('visibilitychange', refreshVisible); });
onBeforeUnmount(() => { version++; controller?.abort(); clearInterval(timer); document.removeEventListener('visibilitychange', refreshVisible); emit('busy', false); });
</script>

<template>
  <section class="settings-card login-devices" data-settings-anchor="sessions" aria-labelledby="login-devices-heading">
    <div class="card-heading">
      <div><h2 id="login-devices-heading">로그인 기기 관리</h2><p>브라우저별 로그인과 최근 활동을 확인하고 원격으로 로그아웃하세요.</p></div>
      <button type="button" class="icon-button" aria-label="로그인 기기 목록 새로고침" :disabled="!canAct" @click="load()"><RefreshCw :size="16" :class="{ spinning: loading }" aria-hidden="true" /></button>
    </div>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="form-notice" role="status">{{ notice }}</p>
    <p v-if="!data && loading" class="settings-description" role="status">로그인 기기를 불러오는 중이에요…</p>
    <template v-if="data">
      <ul class="device-list" :aria-busy="loading">
        <li v-for="session in rows" :key="session.id" class="login-device" :class="{ 'current-device': session.current }" :data-session-id="session.id">
          <span class="device-icon"><component :is="icons[session.kind] || Monitor" :size="20" aria-hidden="true" /></span>
          <div class="device-info">
            <div class="device-name"><strong>{{ session.label }}</strong><span v-if="session.current" class="role-badge">현재 기기</span></div>
            <p>접속 IP <span>{{ session.ip_address || '기록 없음' }}</span></p>
            <p>최근 활동 <time :datetime="isoTime(session.last_seen_at)">{{ formatTime(session.last_seen_at) }}</time></p>
            <p>로그인 <time :datetime="isoTime(session.created_at)">{{ formatTime(session.created_at) }}</time><span class="device-expiry"> · 만료 {{ formatTime(session.expires_at) }}</span></p>
          </div>
          <button type="button" class="secondary-button device-logout" :aria-label="session.current ? '현재 기기 로그아웃' : `${session.label} 기기 로그아웃`" :disabled="!canAct" @click="revoke(session.id)"><LogOut :size="14" aria-hidden="true" />로그아웃</button>
        </li>
      </ul>
      <div v-if="totalOthers > pageSize" class="device-pagination"><span>다른 기기 {{ offset + 1 }}–{{ Math.min(offset + pageSize, totalOthers) }} / {{ totalOthers }}개</span><div class="inline-actions"><button type="button" class="secondary-button" aria-label="로그인 기기 이전 페이지" :disabled="!canAct || !offset" @click="load(Math.max(0, offset - pageSize))">이전</button><button type="button" class="secondary-button" aria-label="로그인 기기 다음 페이지" :disabled="!canAct || offset + pageSize >= totalOthers" @click="load(offset + pageSize)">다음</button></div></div>
      <p v-if="!totalOthers" class="settings-description device-empty">다른 기기에 로그인되어 있지 않아요.</p>
      <div v-else class="device-bulk">
        <template v-if="confirmAll"><p>현재 기기를 제외한 다른 기기를 모두 로그아웃할까요?</p><div class="inline-actions"><button type="button" class="secondary-button" :disabled="!canAct" @click="confirmAll = false">취소</button><button type="button" class="primary-button" :disabled="!canAct" @click="revokeOthers">다른 기기 로그아웃 확인</button></div></template>
        <button v-else type="button" class="secondary-button" :disabled="!canAct" @click="confirmAll = true"><LogOut :size="14" aria-hidden="true" />다른 기기 모두 로그아웃<span>({{ totalOthers }})</span></button>
      </div>
      <p class="settings-description device-note">최근 활동은 최대 1분 간격으로 기록합니다. SSO 서비스의 로그인은 해당 서비스에서 별도로 관리합니다.</p>
    </template>
  </section>
</template>

<style scoped>
.login-devices .card-heading { flex-direction: row; align-items: flex-start; }
.login-devices .icon-button { font-size: inherit; }
.device-list { display: grid; gap: 10px; list-style: none; padding: 0; margin: 0; }
.login-device { display: flex; align-items: center; gap: 14px; padding: 16px; border: 1px solid var(--border); border-radius: 10px; min-width: 0; }
.current-device { border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); background: color-mix(in srgb, var(--accent) 5%, transparent); }
.device-icon { display: grid; place-items: center; width: 36px; height: 36px; flex: 0 0 auto; border-radius: 9px; color: var(--accent); background: var(--surface-raised); }
.device-info { flex: 1; min-width: 0; }
.device-name { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: 13px; }
.device-info p { margin: 5px 0 0; color: var(--subtext); font-size: 11px; line-height: 1.7; overflow-wrap: anywhere; }
.device-info p > span, .device-info time { color: var(--text); }
.device-info .device-expiry { color: var(--subtext); }
.device-logout { flex: 0 0 auto; }
.device-pagination { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-top: 14px; color: var(--subtext); font-size: 12px; }
.device-empty, .device-note { margin-top: 16px; }
.device-bulk { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border); }
.device-bulk p { margin: 0 0 12px; font-size: 12px; }
.spinning { animation: device-spin 1s linear infinite; }
@keyframes device-spin { to { transform: rotate(360deg); } }
@media (max-width: 600px) { .login-device { flex-wrap: wrap; gap: 10px; padding: 12px; } .device-icon { align-self: flex-start; } .device-info { flex-basis: calc(100% - 46px); } .device-logout { margin-left: auto; } .device-expiry { display: block; } }
</style>
