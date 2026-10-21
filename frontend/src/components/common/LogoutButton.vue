<script setup>
import { ref } from "vue";
import { LogOut } from "lucide-vue-next";
import { logout } from "../../lib/api.js";

const props = defineProps({ compact: Boolean });
const busy = ref(false);
const error = ref("");
async function submit() {
  busy.value = true;
  error.value = "";
  try { await logout(); }
  catch { error.value = "로그아웃하지 못했어요. 다시 시도해 주세요."; busy.value = false; }
}
</script>
<template>
  <button class="logout-button" :class="{ 'logout-compact': props.compact }" :disabled="busy" aria-label="로그아웃" :title="error || '로그아웃'" @click="submit"><LogOut :size="16" /><span v-if="!compact">{{ busy ? "로그아웃 중…" : "로그아웃" }}</span></button>
  <span v-if="error" class="logout-error" role="alert">{{ error }}</span>
</template>
