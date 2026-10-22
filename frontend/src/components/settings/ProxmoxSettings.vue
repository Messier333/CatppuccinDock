<script setup>
import { onMounted, ref } from 'vue';
import { Plus, Server, Pencil, Trash2, RefreshCw, X } from 'lucide-vue-next';
import { api } from '../../lib/api.js';
import { defaults } from '../../lib/proxmox.js';
import ProxmoxLayoutEditor from '../integrations/ProxmoxLayoutEditor.vue';
import ProxmoxPanel from '../integrations/ProxmoxPanel.vue';
import '../../styles/proxmox.css';
const integrations = ref([]), bookmarks = ref([]), busy = ref(false), error = ref(''), notice = ref('');
const editor = ref(null), removeDialog = ref(null), deleting = ref(null), selected = ref(null), draft = ref(defaults()), editingId = ref(''), nodeNames = ref('');
async function load() {
  try {
    const [list, portal] = await Promise.all([api('integrations/proxmox'), api('portal')]);
    integrations.value = list.integrations;
    bookmarks.value = portal.tabs.flatMap(tab => tab.categories.flatMap(category => category.links.map(link => ({...link, category: `${tab.name} / ${category.name}`}))));
  } catch (cause) { error.value = cause.message; }
}
onMounted(load);
function edit(row) {
  editingId.value = row?.id || ''; draft.value = row ? {...JSON.parse(JSON.stringify(row.config)), token: ''} : defaults();
  nodeNames.value = draft.value.nodes.join(', '); error.value = ''; editor.value.showModal();
}
async function save() {
  busy.value = true; error.value = '';
  try {
    const payload = {...draft.value, token: draft.value.token || null, nodes: nodeNames.value.split(',').map(name => name.trim()).filter(Boolean)};
    const row = await api('integrations/proxmox' + (editingId.value ? '/' + editingId.value : ''), { method: editingId.value ? 'PUT' : 'POST', body: JSON.stringify(payload) });
    draft.value.token = ''; editor.value.close(); notice.value = '내 Proxmox 연결을 저장했어요.';
    await load(); await refresh(row);
  } catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
}
async function refresh(row) {
  busy.value = true; error.value = '';
  try {
    const updated = await api(`integrations/proxmox/${row.id}/refresh`, { method: 'POST' });
    replace(updated); if (updated.error) error.value = updated.error;
  } catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
}
function replace(row) {
  const index = integrations.value.findIndex(item => item.id === row.id);
  if (index >= 0) integrations.value[index] = row;
  if (selected.value?.id === row.id) selected.value = row;
}
async function remove() {
  busy.value = true; error.value = '';
  try { await api('integrations/proxmox/' + deleting.value.id, {method:'DELETE'}); removeDialog.value.close(); await load(); }
  catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
}
</script>
<template>
  <section class="settings-section pve-settings" data-settings-anchor="proxmox">
    <div class="settings-section-heading"><p class="settings-description">내 Proxmox 서버의 상태와 제어 기능을 북마크에 연결합니다. 등록한 계정에서만 조회·설정·제어할 수 있습니다.</p><button class="primary-button" @click="edit()"><Plus :size="15" />Proxmox 추가</button></div>
    <p v-if="error && !editor?.open" class="form-error" role="alert">{{ error }}</p><p v-if="notice" class="form-notice" role="status">{{ notice }}</p>
    <p v-if="!integrations.length" class="settings-empty">등록한 연동이 없습니다. API 토큰을 준비하고 Proxmox를 추가하세요.</p>
    <article v-for="row in integrations" :key="row.id" class="settings-card pve-connection-row"><Server :size="22" /><div class="pve-grow"><h3>{{ row.config.name }}</h3><p>{{ row.config.base_url }}</p><small>{{ row.error || (row.checked_at ? '연결 확인됨' : '연결 확인 전') }} · {{ row.config.controls ? '제어 허용' : '조회 전용' }} · {{ row.config.enabled ? '사용 중' : '꺼짐' }}</small></div><div class="pve-actions"><button class="secondary-button" :disabled="busy || !row.config.enabled" @click="refresh(row)"><RefreshCw :size="14" />연결 확인</button><button class="secondary-button" @click="selected = row">패널 열기</button><button class="icon-button" :aria-label="`${row.config.name} 수정`" @click="edit(row)"><Pencil :size="16" /></button><button class="icon-button danger" :aria-label="`${row.config.name} 삭제`" @click="deleting = row; removeDialog.showModal()"><Trash2 :size="16" /></button></div></article>
    <dialog ref="editor" v-dialog-dismiss="busy" class="editor-dialog pve-editor" aria-labelledby="pve-editor-title" @close="draft.token = ''"><form @submit.prevent="save"><header class="pve-header"><h2 id="pve-editor-title">{{ editingId ? 'Proxmox 수정' : 'Proxmox 추가' }}</h2><button type="button" class="icon-button" aria-label="닫기" :disabled="busy" @click="editor.close()"><X :size="18" /></button></header>
      <p class="settings-description">Proxmox에서 사용자와 API 토큰을 만든 뒤 유효 권한을 부여하세요. 조회에는 VM.Audit / Sys.Audit / Datastore.Audit, 조작에는 해당 작업의 권한이 필요합니다.</p>
      <div class="pve-form-grid"><label>이름<input v-model="draft.name" required maxlength="80" placeholder="내 홈랩" /></label><label>Proxmox 주소<input v-model="draft.base_url" required type="url" placeholder="https://pve.example:8006" /></label><label>API Token ID<input v-model="draft.token_id" required maxlength="256" placeholder="dock@pve!portal" autocomplete="off" /></label><label>Token Secret<input v-model="draft.token" type="password" :required="!editingId" maxlength="1024" autocomplete="new-password" :placeholder="editingId ? '비워 두면 유지 · 주소나 ID 변경 시 다시 입력' : 'API 토큰 Secret'" /></label><label>갱신 간격 (초)<input v-model.number="draft.interval" type="number" min="30" max="3600" required /></label><label>노드 범위<input v-model="nodeNames" placeholder="비우면 권한이 있는 모든 노드 · 쉼표로 구분" /></label></div>
      <label class="pve-ca">사용자 CA 인증서 (선택)<textarea v-model="draft.ca_certificate" rows="3" maxlength="32768" placeholder="자체 서명 인증서는 Proxmox CA의 PEM 내용을 입력하세요. TLS 검증은 항상 적용됩니다." /></label>
      <div class="pve-checks"><label><input v-model="draft.enabled" type="checkbox" />연동 활성화</label><label><input v-model="draft.allow_private" type="checkbox" />사설 네트워크 연결 허용</label><label><input v-model="draft.controls" type="checkbox" />서버 제어 허용</label></div>
      <p class="settings-description">토큰 권한이 없는 작업은 숨깁니다. 제어는 실행 전 대상과 입력값을 확인합니다. 루프백·링크 로컬 주소는 연결할 수 없습니다.</p>
      <ProxmoxLayoutEditor v-model="draft" :bookmarks="bookmarks" show-bindings :disabled="busy" />
      <p v-if="error" class="form-error" role="alert">{{ error }}</p><footer class="pve-actions"><button type="button" class="secondary-button" :disabled="busy" @click="editor.close()">취소</button><button class="primary-button" :disabled="busy">{{ busy ? '저장 중…' : '저장 · 연결 확인' }}</button></footer>
    </form></dialog>
    <dialog ref="removeDialog" v-dialog-dismiss="busy" class="editor-dialog" aria-labelledby="pve-remove-title"><h2 id="pve-remove-title">Proxmox 연결 삭제</h2><p>{{ deleting?.config.name }} 연결과 앱의 작업 내역을 삭제합니다. Proxmox 서버와 실행 중인 작업은 유지됩니다.</p><div class="pve-actions"><button class="secondary-button" :disabled="busy" @click="removeDialog.close()">취소</button><button class="danger-button" :disabled="busy" @click="remove">연결 삭제</button></div><p v-if="error" role="alert">{{ error }}</p></dialog>
    <ProxmoxPanel v-if="selected" :integration="selected" @close="selected = null" @updated="replace" />
  </section>
</template>
