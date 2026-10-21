<script setup>
import { computed, onMounted, ref } from "vue";
import { api } from "../../lib/api.js";
import LoginDevices from './LoginDevices.vue';

const account = ref(null);
const error = ref("");
const notice = ref("");
const password = ref("");
const newPassword = ref("");
const passwordConfirmation = ref("");
const code = ref("");
const enrollment = ref(null);
const recovery = ref([]);
const working = ref(false), deviceBusy = ref(false);
const busy = computed(() => working.value || deviceBusy.value);
const sessionRevision = ref(0);
async function load() { account.value = await api("account"); }
onMounted(async () => { try { await load(); } catch (cause) { error.value = cause.message; } });
async function action(operation) {
  if (busy.value) return;
  working.value = true; error.value = ""; notice.value = "";
  try { await operation(); } catch (cause) { error.value = cause.message; } finally { working.value = false; }
}
function changePassword() { return action(async () => {
  if (newPassword.value !== passwordConfirmation.value) throw new Error("새 비밀번호가 일치하지 않아요.");
  await api("account/password", { method: "POST", body: JSON.stringify({ current_password: password.value, new_password: newPassword.value }) });
  sessionRevision.value++;
  password.value = ""; newPassword.value = ""; passwordConfirmation.value = ""; notice.value = "비밀번호를 변경하고 다른 로그인 세션을 종료했어요.";
}); }
function enroll() { return action(async () => {
  enrollment.value = await api("account/2fa/enroll", { method: "POST", body: JSON.stringify({ password: password.value }) });
  code.value = "";
}); }
function confirm() { return action(async () => {
  const result = await api("account/2fa/confirm", { method: "POST", body: JSON.stringify({ code: code.value }) });
  sessionRevision.value++;
  recovery.value = result.recovery_codes; enrollment.value = null; code.value = ""; password.value = ""; await load();
}); }
function manageMfa(kind) { return action(async () => {
  const result = await api(`account/2fa/${kind}`, { method: "POST", body: JSON.stringify({ password: password.value, code: code.value }) });
  if (kind === 'disable') sessionRevision.value++;
  if (result.recovery_codes) recovery.value = result.recovery_codes;
  notice.value = kind === "disable" ? "2단계 인증을 해제했어요." : "새 복구 코드를 발급했어요. 이전 코드는 사용할 수 없어요.";
  code.value = ""; password.value = ""; await load();
}); }
function downloadCodes() {
  const blob = new Blob([`CatppuccinDock · ${account.value.username}\n각 코드는 한 번만 사용할 수 있습니다.\n\n${recovery.value.join('\n')}\n`], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a"); link.href = url; link.download = "catppuccindock-recovery-codes.txt"; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
</script>
<template>
  <section class="settings-section">
    <p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="notice" class="form-notice" role="status">{{ notice }}</p>
    <template v-if="account">
      <div class="settings-card"><div class="card-heading"><div><h2>{{ account.username }}</h2><p>{{ account.role === 'admin' ? '관리자' : '일반 사용자' }} 계정</p></div><span class="role-badge">{{ account.totp_enabled ? '2FA 사용 중' : '2FA 사용 안 함' }}</span></div><p v-for="identity in account.identities" :key="identity.id" class="identity-label">SSO 연결 · {{ identity.issuer }}</p></div>
      <LoginDevices :revision="sessionRevision" :disabled="working" @busy="deviceBusy = $event" />
      <div v-if="recovery.length" class="settings-card recovery-card"><h2>복구 코드를 보관하세요</h2><p>인증 앱을 사용할 수 없을 때 로그인하는 코드입니다. 각 코드는 한 번만 사용할 수 있고, 이 화면을 닫으면 다시 볼 수 없어요.</p><div class="recovery-codes"><code v-for="item in recovery" :key="item">{{ item }}</code></div><div class="inline-actions"><button class="primary-button" @click="downloadCodes">파일로 저장</button><button class="secondary-button" @click="recovery = []">복구 코드를 보관했어요</button></div></div>
      <div class="settings-card"><div class="card-heading"><div><h2>2단계 인증</h2><p>인증 앱의 일회용 코드로 계정을 보호하세요.</p></div></div>
        <form v-if="!account.totp_enabled && !enrollment" class="settings-form" @submit.prevent="enroll"><label v-if="account.has_password">현재 비밀번호<input v-model="password" type="password" autocomplete="current-password" required maxlength="256" /></label><p v-else class="settings-description">최근 SSO 로그인 후 10분 안에 설정할 수 있어요.</p><button class="primary-button" :disabled="busy">인증 앱 연결</button></form>
        <form v-else-if="enrollment" class="settings-form" @submit.prevent="confirm"><p>인증 앱에서 QR 코드를 스캔한 뒤 표시되는 6자리 코드를 입력하세요.</p><div class="totp-qr" role="img" aria-label="인증 앱 등록 QR 코드" v-html="enrollment.qr_svg"></div><label>직접 입력할 설정 키<code class="totp-secret">{{ enrollment.secret }}</code></label><label>인증 코드<input v-model="code" name="totp_code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required /></label><div class="inline-actions"><button class="primary-button" :disabled="busy">연결 확인</button><button class="secondary-button" type="button" @click="enrollment = null; code = ''">취소</button></div></form>
        <form v-else class="settings-form" @submit.prevent="manageMfa('recovery-codes')"><p class="settings-description">남은 복구 코드: {{ account.recovery_remaining }}개</p><label v-if="account.has_password">현재 비밀번호<input v-model="password" type="password" autocomplete="current-password" required maxlength="256" /></label><label>인증 코드 또는 복구 코드<input v-model="code" name="security_code" autocomplete="one-time-code" required maxlength="128" /></label><div class="inline-actions"><button class="secondary-button" :disabled="busy">복구 코드 다시 발급</button><button class="secondary-button danger" type="button" :disabled="busy || !code || (account.has_password && !password)" @click="manageMfa('disable')">2단계 인증 해제</button></div></form>
      </div>
      <div v-if="account.has_password" class="settings-card"><h2>비밀번호 변경</h2><form class="settings-form" @submit.prevent="changePassword"><label>현재 비밀번호<input v-model="password" name="current_password" type="password" autocomplete="current-password" required maxlength="256" /></label><label>새 비밀번호<input v-model="newPassword" name="new_password" type="password" autocomplete="new-password" required minlength="12" maxlength="256" /></label><label>새 비밀번호 확인<input v-model="passwordConfirmation" name="new_password_confirmation" type="password" autocomplete="new-password" required minlength="12" maxlength="256" /></label><button class="primary-button" :disabled="busy">비밀번호 변경</button></form></div>
    </template><p v-else-if="!error" role="status">계정 정보를 불러오는 중이에요…</p>
  </section>
</template>
