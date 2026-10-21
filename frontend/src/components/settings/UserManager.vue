<script setup>
import ThemeSelect from "../common/ThemeSelect.vue";
import { onMounted, reactive, ref } from "vue";
import { Plus, Pencil, Link2, Trash2 } from "lucide-vue-next";
import { api } from "../../lib/api.js";
const users = ref([]);
const error = ref("");
const notice = ref("");
const busy = ref(false);
const dialog = ref(null);
const mode = ref("user");
const target = ref(null);
const issuer = ref("");
const sso = ref(null);
const subject = ref("");
const draft = reactive({ username: "", password: "", role: "member", active: true, login_type: "local", oidc_subject: "" });
async function load() { users.value = await api("admin/users"); }
onMounted(async () => { try { await load(); sso.value = await api('admin/sso'); issuer.value = sso.value.issuer; } catch (cause) { error.value = cause.message; } });
function edit(user = null) {
  target.value = user; mode.value = "user"; error.value = "";
  Object.assign(draft, { username: user?.username || "", password: "", role: user?.role || "member", active: user?.active ?? true, login_type: "local", oidc_subject: "" });
  dialog.value.showModal();
}
function identity(user) { target.value = user; mode.value = "identity"; subject.value = ""; error.value = ""; dialog.value.showModal(); }
async function save() {
  busy.value = true; error.value = "";
  try {
    if (mode.value === "identity") await api(`admin/users/${target.value.id}/identities`, { method: "POST", body: JSON.stringify({ issuer: issuer.value, subject: subject.value }) });
    else {
      const data = { username: draft.username, role: draft.role, active: draft.active, password: draft.password || null };
      if (!target.value) {
        data.login_type = draft.login_type;
        if (draft.login_type === 'oidc') { data.password = null; data.oidc_subject = draft.oidc_subject; }
      }
      await api(`admin/users${target.value ? `/${target.value.id}` : ''}`, { method: target.value ? "PUT" : "POST", body: JSON.stringify(data) });
    }
    dialog.value.close(); draft.password = ""; notice.value = "저장했어요."; await load();
  } catch (cause) { error.value = cause.message; } finally { busy.value = false; }
}
async function unlink(user, identity) {
  if (!window.confirm(`${user.username} 계정의 SSO 연결을 해제할까요?`)) return;
  try { await api(`admin/users/${user.id}/identities/${identity.id}`, { method: "DELETE" }); await load(); } catch (cause) { error.value = cause.message; }
}
</script>
<template>
  <section class="settings-section"><div class="management-toolbar"><p class="settings-description">사용자별 권한과 로그인 상태를 관리하세요. 계정 변경 시 해당 사용자의 세션이 종료됩니다.</p><button class="primary-button" @click="edit()"><Plus :size="15" />사용자 추가</button></div><p v-if="error && !dialog?.open" class="form-error" role="alert">{{ error }}</p><p v-if="notice" class="form-notice" role="status">{{ notice }}</p>
    <p v-if="sso?.enabled && sso.login_mode === 'sso_only'" class="settings-description">현재 포털은 SSO 로그인만 허용합니다. 일반 계정도 현재 인증 서비스의 SSO 연결이 있어야 로그인할 수 있습니다.</p>
    <div class="settings-card user-list"><article v-for="user in users" :key="user.id" class="user-row"><div class="user-row-heading"><div><strong>{{ user.username }}</strong><div class="user-badges"><span class="role-badge">{{ user.role === 'admin' ? '관리자' : '일반 사용자' }}</span><span :class="{ danger: !user.active }">{{ user.active ? '활성' : '비활성' }}</span><span>{{ user.has_password ? '일반' : '' }}{{ user.has_password && user.identities.length ? ' + ' : '' }}{{ user.identities.length ? 'OIDC' : '' }}</span><span>{{ user.totp_enabled ? '2FA 사용' : '2FA 미설정' }}</span></div></div><div class="inline-actions"><button class="icon-button" :aria-label="`${user.username} 수정`" title="사용자 수정" @click="edit(user)"><Pencil :size="16" /></button><button class="icon-button" :aria-label="`${user.username} SSO 연결`" title="SSO 연결" @click="identity(user)"><Link2 :size="16" /></button></div></div><div v-for="item in user.identities" :key="item.id" class="identity-row"><span>{{ item.issuer }} · {{ item.subject }}</span><button class="icon-button danger" aria-label="SSO 연결 해제" @click="unlink(user, item)"><Trash2 :size="14" /></button></div></article></div>
    <dialog ref="dialog" v-dialog-dismiss="busy" @close="draft.password = ''" class="editor-dialog"><form class="settings-form" @submit.prevent="save"><div class="card-heading"><h2>{{ mode === 'identity' ? `${target?.username} · SSO 연결` : target ? '사용자 수정' : '사용자 추가' }}</h2><button class="icon-button" type="button" aria-label="닫기" :disabled="busy" @click="dialog.close()">×</button></div>
      <template v-if="mode === 'identity'"><p class="settings-description">인증 서비스의 Issuer와 해당 사용자의 고유 Subject를 연결하세요. 이메일이나 아이디만으로 계정을 자동 연결하지 않습니다.</p><label>Issuer URL<input v-model="issuer" name="issuer" type="url" required maxlength="1024" /></label><label>Subject<input v-model="subject" name="subject" required maxlength="256" /></label></template>
      <template v-else>
        <label v-if="!target">로그인 방식<ThemeSelect v-model="draft.login_type" name="login_type" label="로그인 방식" :options="[{ value: 'local', label: '일반 계정 · 아이디와 비밀번호' }, { value: 'oidc', label: `OIDC 계정 · ${sso?.label || 'SSO'}`, disabled: !sso?.configured }]" /><small v-if="!sso?.configured">OIDC 계정은 계정 · 보안 → SSO · 로그인에서 인증 서비스를 먼저 등록해 주세요.</small></label>
        <label>아이디<input v-model="draft.username" name="username" required maxlength="64" autocomplete="off" /><small v-if="!target && draft.login_type === 'oidc'">포털에서 표시할 아이디입니다.</small></label>
        <label v-if="target || draft.login_type === 'local'">{{ target ? '새 비밀번호 (변경할 때만 입력)' : '비밀번호' }}<input v-model="draft.password" name="password" type="password" autocomplete="new-password" :required="!target" minlength="12" maxlength="256" /></label>
        <template v-else><p class="settings-description">인증 서비스: {{ sso?.issuer }}</p><label>OIDC Subject<input v-model="draft.oidc_subject" name="oidc_subject" required maxlength="256" autocomplete="off" /><small>인증 서비스가 발급하는 사용자의 고유 sub 값입니다. 이메일과 다를 수 있습니다.</small></label></template>
        <label>권한<ThemeSelect v-model="draft.role" name="role" label="권한" :options="[{ value: 'member', label: '일반 사용자 · 본인 북마크 관리' }, { value: 'admin', label: '관리자 · 링크·계정·서비스 설정 관리' }]" /></label><label class="checkbox-label"><input v-model="draft.active" type="checkbox" />계정 활성화</label>
      </template>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p><button class="primary-button" :disabled="busy">{{ busy ? '저장 중…' : '저장' }}</button>
    </form></dialog>
  </section>
</template>
