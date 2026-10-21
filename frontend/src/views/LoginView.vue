<script setup>
import { computed, ref, watch } from "vue";
import { ArrowRight, Eye, EyeOff, KeyRound, LockKeyhole, Moon, Sun } from "lucide-vue-next";
import { api } from "../lib/api.js";
import { appUrl } from "../lib/navigation.js";
import { useTheme } from "../composables/useTheme.js";
import "../styles/login.css";

const props = defineProps({ setupRequired: Boolean, mfaRequired: Boolean, ssoEnabled: Boolean, ssoLabel: String, passwordLoginEnabled: { type: Boolean, default: true } });
const emit = defineEmits(["authenticated"]);
const username = ref("");
const password = ref("");
const confirmation = ref("");
const setupCode = ref("");
const showPassword = ref(false);
const busy = ref(false);
const error = ref("");
const mfa = ref(props.mfaRequired);
const code = ref("");
const showPasswordForm = computed(() => props.setupRequired || mfa.value || props.passwordLoginEnabled);
const showSSO = computed(() => props.ssoEnabled && !props.setupRequired && !mfa.value);
const ssoButtonLabel = computed(() => /로그인\s*$/.test(props.ssoLabel || '') ? props.ssoLabel : `${props.ssoLabel || 'SSO'}로 로그인`);
watch(() => props.mfaRequired, value => { mfa.value = value; });
if (new URLSearchParams(window.location.search).has("sso_error")) {
  error.value = "SSO 로그인에 실패했어요. 연결된 계정과 인증 서비스 설정을 확인해 주세요.";
  const url = new URL(window.location.href);
  url.searchParams.delete("sso_error");
  window.history.replaceState(null, "", url);
}
const { theme, toggleTheme } = useTheme();

async function submit() {
  if (busy.value || !showPasswordForm.value) return;
  error.value = "";
  if (props.setupRequired && password.value !== confirmation.value) {
    error.value = "비밀번호가 일치하지 않아요.";
    return;
  }
  busy.value = true;
  try {
    const result = await api(mfa.value ? "auth/mfa" : props.setupRequired ? "auth/setup" : "auth/login", {
      method: "POST",
      body: JSON.stringify(mfa.value ? { code: code.value.trim() } : { username: username.value, password: password.value, ...(props.setupRequired ? { setup_code: setupCode.value.trim() } : {}) }),
    });
    password.value = "";
    confirmation.value = "";
    setupCode.value = "";
    if (result.mfa_required) { mfa.value = true; code.value = ""; return; }
    emit("authenticated");
  } catch (cause) {
    error.value = cause.message;
  } finally {
    busy.value = false;
  }
}

async function restartLogin() {
  try { await api("auth/logout", { method: "POST" }); mfa.value = false; code.value = ""; error.value = ""; }
  catch (cause) { error.value = cause.message; }
}
</script>

<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="login-title">
      <div class="login-header">
        <div class="login-brand"><span class="login-mark">c<span>.</span></span><span>Catppuccin<strong>Dock</strong></span></div>
        <button class="login-theme" type="button" role="switch" aria-label="다크 모드" :aria-checked="theme === 'mocha'" :title="theme === 'mocha' ? '라이트 모드로 변경' : '다크 모드로 변경'" @click="toggleTheme"><Sun v-if="theme === 'mocha'" :size="18" aria-hidden="true" /><Moon v-else :size="18" aria-hidden="true" /></button>
      </div>
      <span class="login-eyebrow"><span></span> YOUR PERSONAL SPACE</span>
      <h1 id="login-title">{{ mfa ? "2단계 인증" : setupRequired ? "나만의 Dock을 시작해요" : "다시 오신 걸 환영해요" }}</h1>
      <p class="login-description">{{ mfa ? "인증 앱의 코드 또는 저장한 복구 코드를 입력하세요." : setupRequired ? "관리자 계정을 만들고 나만의 공간을 준비하세요." : !passwordLoginEnabled ? "연결된 SSO 계정으로 로그인하세요." : "로그인하고 나만의 공간으로 들어오세요." }}</p>

      <form v-if="showPasswordForm" class="login-form" @submit.prevent="submit">
        <label v-if="mfa" class="login-field">인증 코드 또는 복구 코드<input v-model="code" name="mfa_code" autocomplete="one-time-code" required maxlength="128" placeholder="6자리 코드 또는 복구 코드" :disabled="busy" /></label>
        <template v-else>
        <label v-if="setupRequired" class="login-field">최초 설정 코드<input v-model="setupCode" name="setup_code" type="password" autocomplete="off" required maxlength="256" placeholder="서버 관리자가 받은 설정 코드" :disabled="busy" /><small>최초 계정을 만들 때 한 번만 필요해요.</small></label>
        <label class="login-field">아이디<input v-model="username" name="username" autocomplete="username" required maxlength="64" placeholder="아이디를 입력하세요" :disabled="busy" autocapitalize="none" spellcheck="false" /></label>
        <label class="login-field">비밀번호<span class="password-field"><input v-model="password" name="password" :type="showPassword ? 'text' : 'password'" :autocomplete="setupRequired ? 'new-password' : 'current-password'" required :minlength="setupRequired ? 12 : 1" maxlength="256" :placeholder="setupRequired ? '12자 이상 입력하세요' : '비밀번호를 입력하세요'" :disabled="busy" /><button type="button" :aria-label="showPassword ? '비밀번호 숨기기' : '비밀번호 보기'" :aria-pressed="showPassword" @click="showPassword = !showPassword"><EyeOff v-if="showPassword" :size="18" /><Eye v-else :size="18" /></button></span></label>
        <label v-if="setupRequired" class="login-field">비밀번호 확인<input v-model="confirmation" name="password_confirmation" type="password" autocomplete="new-password" required minlength="12" maxlength="256" placeholder="비밀번호를 다시 입력하세요" :disabled="busy" /></label>
        </template>
        <p v-if="error" class="login-error" role="alert">{{ error }}</p>
        <button class="login-submit" type="submit" :disabled="busy"><span>{{ busy ? "확인하는 중…" : mfa ? "인증하고 로그인" : setupRequired ? "계정 만들고 시작하기" : "로그인" }}</span><ArrowRight :size="18" /></button>
        <button v-if="mfa" class="login-alternative" type="button" :disabled="busy" @click="restartLogin">처음부터 로그인</button>
      </form>
      <div v-if="showSSO && passwordLoginEnabled" class="login-divider"><span>또는 SSO 계정으로</span></div>
      <p v-if="error && !showPasswordForm" class="login-error login-sso-error" role="alert">{{ error }}</p>
      <a v-if="showSSO" class="login-sso" :class="{ 'login-sso-primary': !passwordLoginEnabled }" :href="appUrl('api/auth/oidc/login')"><KeyRound :size="17" aria-hidden="true" /><span>{{ ssoButtonLabel }}</span><ArrowRight v-if="!passwordLoginEnabled" :size="18" aria-hidden="true" /></a>
      <p v-if="!passwordLoginEnabled && !showSSO && !mfa && !setupRequired" class="login-error login-sso-error" role="alert">SSO 연결을 사용할 수 없습니다. 서버 관리자에게 문의해 주세요.</p>
      <p class="login-private"><LockKeyhole :size="13" /> 나만을 위한 작은 정박지</p>
    </section>
    <footer class="login-footer">A LITTLE CALM, EVERY DAY <span>✦</span></footer>
  </main>
</template>
