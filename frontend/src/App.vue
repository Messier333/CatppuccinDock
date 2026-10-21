<script setup>
import { defineAsyncComponent, onMounted, onUnmounted, ref } from "vue";
import { api } from "./lib/api.js";
import { appUrl, isAdminPath } from "./lib/navigation.js";
import { useTheme } from "./composables/useTheme.js";
import { backgroundUrl } from "./lib/backgrounds.js";
import './styles/reorder.css';

const HomeView = defineAsyncComponent(() => import("./views/HomeView.vue"));
const AdminView = defineAsyncComponent(() => import("./views/AdminView.vue"));
const LoginView = defineAsyncComponent(() => import("./views/LoginView.vue"));
const state = ref("loading");
const session = ref(null);
const portal = ref(null);
const error = ref("");
useTheme();

async function loadSession() {
  state.value = "loading";
  error.value = "";
  try {
    session.value = await api("auth/status");
    if (!session.value.authenticated) {
      portal.value = null;
      state.value = "login";
      return;
    }
    if (/\/login(?:\/|$)/.test(window.location.pathname)) {
      window.location.replace(appUrl());
      return;
    }
    if (!isAdminPath) {
      portal.value = await api("portal");
      let initialIndex = 0;
      try { if (portal.value.openLastVisitedTab) initialIndex = Number(localStorage.getItem('lastVisitedTab')); } catch { /* Start at the first tab when browser storage is unavailable. */ }
      const image = new Image();
      image.fetchPriority = "high";
      image.src = backgroundUrl(portal.value.tabs[initialIndex] || portal.value.tabs[0]);
    }
    else await api("account");
    state.value = "ready";
  } catch (cause) {
    if (cause.status === 401) {
      session.value = { ...session.value, authenticated: false, setup_required: false, mfa_required: false };
      state.value = "login";
    } else {
      error.value = "서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.";
      state.value = "error";
    }
  }
}

function expireSession() {
  portal.value = null;
  session.value = { ...session.value, authenticated: false, setup_required: false, mfa_required: false };
  state.value = "login";
}

let sessionInterval;

async function recheckSession(event) {
  if (event.type === "pageshow" && !event.persisted) return;
  if (document.visibilityState === "hidden" || state.value !== "ready") return;
  try {
    const latest = await api("auth/status");
    if (!latest.authenticated) expireSession();
  } catch { /* Keep the current view usable during a temporary connection loss. */ }
}

onMounted(() => {
  loadSession();
  window.addEventListener("dock:session-expired", expireSession);
  window.addEventListener("pageshow", recheckSession);
  document.addEventListener("visibilitychange", recheckSession);
  sessionInterval = window.setInterval(() => recheckSession({ type: "interval" }), 60_000);
});
onUnmounted(() => {
  window.removeEventListener("dock:session-expired", expireSession);
  window.removeEventListener("pageshow", recheckSession);
  document.removeEventListener("visibilitychange", recheckSession);
  window.clearInterval(sessionInterval);
});
</script>

<template>
  <div v-if="state === 'loading'" class="app-status" role="status"><span class="app-spinner"></span><p>Dock을 불러오는 중이에요</p></div>
  <div v-else-if="state === 'error'" class="app-status" role="alert"><p>{{ error }}</p><button @click="loadSession">다시 시도</button></div>
  <LoginView v-else-if="state === 'login'" :setup-required="session.setup_required" :mfa-required="session.mfa_required" :sso-enabled="session.sso_enabled" :sso-label="session.sso_label" :password-login-enabled="session.password_login_enabled !== false" @authenticated="loadSession" />
  <AdminView v-else-if="isAdminPath" :username="session.username" :role="session.role" />
  <HomeView v-else :startpage="portal" :username="session.username" />
</template>
