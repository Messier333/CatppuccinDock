<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { ExternalLink, GripVertical, Pencil, RefreshCw, Search, Server, X } from 'lucide-vue-next';
import ThemeSelect from '../common/ThemeSelect.vue';
import { api } from '../../lib/api.js';
import { actionLabels, bytes, cell, columnLabels, metricLabels, metricText, presentation, sectionLabels } from '../../lib/proxmox.js';
import { reorderDirective } from '../../directives/reorder.js';
import '../../styles/proxmox.css';
const props = defineProps({ integration: { type: Object, required: true } });
const emit = defineEmits(['close', 'updated']);
const dialog = ref(null), busy = ref(false), error = ref(''), notice = ref(''), query = ref(''), filter = ref('all');
const editing = ref(false), layout = ref(presentation(props.integration.config));
const chosen = ref(null), details = ref(null), action = ref(''), parameters = ref({}), intent = ref(null), confirmation = ref('');
const tasks = ref([]);
const base = computed(() => `integrations/proxmox/${props.integration.id}`);
const sections = computed(() => (editing.value ? layout.value.sections : props.integration.config.sections).filter(section => editing.value || section.visible));
const columns = computed(() => editing.value ? layout.value.columns : props.integration.config.columns);
const guests = computed(() => (props.integration.data.guests || []).filter(row => (filter.value === 'all' || row.type === filter.value || row.status === filter.value) && `${row.name} ${row.vmid} ${row.node}`.toLocaleLowerCase().includes(query.value.toLocaleLowerCase().trim())));
const guestPage = ref(0);
const pageCount = computed(() => Math.max(1,Math.ceil(guests.value.length/25)));
const pagedGuests = computed(() => guests.value.slice(Math.min(guestPage.value,pageCount.value-1)*25,(Math.min(guestPage.value,pageCount.value-1)+1)*25));
watch([query,filter],() => guestPage.value = 0);
const actionOptions = computed(() => (details.value?.actions || []).filter(key => !['snapshot_delete', 'rollback'].includes(key) || details.value?.snapshots.length).map(value => ({ value, label: actionLabels[value] })));
const storageOptions = computed(() => (props.integration.data.storage || []).filter(row => row.node === chosen.value?.node).map(row => ({value:row.storage, label:row.storage})));
const nodeOptions = computed(() => (props.integration.data.nodes || []).filter(row => row.node !== chosen.value?.node && row.status === 'online').map(row => ({value:row.node,label:row.node})));
const snapshotOptions = computed(() => (details.value?.snapshots || []).map(row => ({value:row.name,label:row.name})));
const working = computed(() => busy.value);
let timer, mounted = true;
function publish(row) { if (mounted) emit('updated', row); }
async function refresh() {
  if (busy.value || document.hidden) return;
  busy.value = true; error.value = '';
  try { publish(await api(base.value + '/refresh', {method:'POST'})); await loadTasks(); }
  catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
}
async function loadTasks() { tasks.value = await api(base.value + '/tasks'); }
async function tick() {
  if (!mounted || document.hidden || busy.value) return;
  try {
    for (const task of tasks.value.filter(task => task.state === 'running').slice(0, 8)) {
      const updated = await api(`${base.value}/tasks/${task.id}/refresh`, {method:'POST'});
      const index = tasks.value.findIndex(item => item.id === updated.id);
      if (index >= 0) tasks.value[index] = updated;
    }
    if (props.integration.refreshing || props.integration.next_check <= Date.now() / 1000) await refresh();
  } catch (cause) { error.value = cause.message; }
}
onMounted(async () => { dialog.value.showModal(); await refresh(); if (mounted) timer = setInterval(tick, 5_000); });
onBeforeUnmount(() => { mounted = false; clearInterval(timer); dialog.value?.close(); });
watch(action, () => { parameters.value = {}; intent.value = null; confirmation.value = ''; });
watch(() => props.integration.id, () => { chosen.value = null; details.value = null; editing.value = false; layout.value = presentation(props.integration.config); });
async function choose(resource) {
  if (busy.value || editing.value) return;
  chosen.value = resource; details.value = null; action.value = ''; intent.value = null; confirmation.value = ''; error.value = '';
  busy.value = true;
  try { details.value = await api(`${base.value}/resource?resource=${encodeURIComponent(resource.id)}`); }
  catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
  await nextTick(); dialog.value?.querySelector('.pve-resource-detail')?.scrollIntoView({block:'nearest'});
}
async function preview() {
  busy.value = true; error.value = '';
  try { intent.value = await api(base.value + '/intents', {method:'POST',body:JSON.stringify({resource:chosen.value.id,action:action.value,parameters:parameters.value})}); confirmation.value = ''; }
  catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
}
async function execute() {
  if (!intent.value || confirmation.value !== intent.value.confirmation) return;
  busy.value = true; error.value = '';
  try {
    const result = await api(base.value + '/execute', {method:'POST',body:JSON.stringify({intent:intent.value.intent,confirmation:confirmation.value})});
    intent.value = null; action.value = ''; chosen.value = null; details.value = null;
    notice.value = result.state === 'running' ? '작업을 접수했어요. 작업 내역에서 진행 상황을 확인할 수 있습니다.' : result.state === 'ok' ? '작업을 완료했어요.' : result.detail;
    await loadTasks(); publish(await api(base.value + '/refresh', {method:'POST'}));
  } catch (cause) { error.value = cause.message; intent.value = null; }
  finally { busy.value = false; }
}
function beginEdit() { layout.value = presentation(props.integration.config); editing.value = true; chosen.value = null; }
function reorder(_kind, _parent, ids) {
  const rows = new Map(layout.value.sections.map(section => [section.id, section]));
  layout.value.sections = ids.map(id => rows.get(id));
}
function move(id, offset) {
  const ids = layout.value.sections.map(section => section.id), index = ids.indexOf(id), next = index + offset;
  if (next < 0 || next >= ids.length) return;
  [ids[index],ids[next]] = [ids[next],ids[index]]; reorder('', '', ids);
}
const vReorder = reorderDirective(reorder);
async function saveLayout() {
  busy.value = true; error.value = '';
  try { publish(await api(base.value + '/presentation', {method:'PUT', body:JSON.stringify(layout.value)})); editing.value = false; notice.value = '패널 구성을 저장했어요.'; }
  catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
}
function stateLabel(state) { return ({submitting:'요청 전송 중',running:'진행 중',ok:'완료',failed:'실패',unknown:'결과 확인 필요'})[state] || state; }
</script>
<template>
  <Teleport to="body"><dialog ref="dialog" v-dialog-dismiss="working" class="pve-drawer" aria-labelledby="pve-panel-title" @close="emit('close')">
    <header class="pve-header"><div><span class="pve-kicker">PROXMOX · 내 서비스</span><h2 id="pve-panel-title">{{ integration.config.name }}</h2></div><div class="pve-actions"><button class="icon-button" :disabled="busy || editing" aria-label="상세 패널 편집" @click="beginEdit"><Pencil :size="17" /></button><a class="icon-button" :href="integration.config.base_url" target="_blank" rel="noopener noreferrer" aria-label="Proxmox 열기"><ExternalLink :size="17" /></a><button class="icon-button" :disabled="busy" aria-label="Proxmox 패널 닫기" @click="dialog.close()"><X :size="20" /></button></div></header>
    <div class="pve-drawer-body">
      <p v-if="integration.error" class="pve-warning" role="status">{{ integration.error }}<span v-if="integration.checked_at"> 마지막으로 확인한 정보를 표시합니다.</span></p>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="notice" class="form-notice" role="status">{{ notice }}</p>
      <div v-if="editing" class="pve-edit-toolbar"><strong>패널 편집</strong><span>카드 손잡이를 드래그하거나 위아래 방향키로 이동하세요.</span><fieldset class="pve-fieldset"><legend>북마크 요약</legend><div class="pve-checks"><label v-for="(label,key) in metricLabels" :key="key"><input v-model="layout.metrics" type="checkbox" :value="key" :disabled="!layout.metrics.includes(key) && layout.metrics.length >= 3" />{{ label }}</label></div></fieldset><fieldset class="pve-fieldset"><legend>게스트 목록 열</legend><div class="pve-checks"><label v-for="(label,key) in columnLabels" :key="key"><input v-model="layout.columns" type="checkbox" :value="key" />{{ label }}</label></div></fieldset><div class="pve-actions"><button class="secondary-button" :disabled="busy" @click="editing = false">취소</button><button class="primary-button" :disabled="busy" @click="saveLayout">구성 저장</button></div></div>
      <section v-if="chosen && !editing" class="pve-resource-detail settings-card" aria-label="리소스 관리"><div class="pve-header"><h3>{{ chosen.name }} <small>{{ chosen.id }}</small></h3><button class="icon-button" :disabled="busy" aria-label="리소스 관리 닫기" @click="chosen = null"><X :size="16" /></button></div><p v-if="!details">리소스와 권한을 확인하고 있어요…</p>
        <template v-else><div v-if="details.snapshots.length" class="pve-snapshots"><span v-for="snapshot in details.snapshots" :key="snapshot.name">{{ snapshot.name }}</span></div><p v-if="!actionOptions.length" class="settings-description">현재 권한과 상태에서 실행할 수 있는 작업이 없습니다.</p>
        <form v-else class="pve-operation" @submit.prevent="preview"><label>작업<ThemeSelect v-model="action" label="Proxmox 작업" :options="actionOptions" :disabled="busy || !!intent" /></label>
          <template v-if="action && !intent">
            <label v-if="action === 'snapshot'">스냅샷 이름<input v-model="parameters.snapname" required maxlength="40" pattern="[a-zA-Z][a-zA-Z0-9_.-]*" placeholder="before-update" /></label>
            <label v-if="['snapshot_delete','rollback'].includes(action)">스냅샷<ThemeSelect v-model="parameters.snapname" label="스냅샷" :options="snapshotOptions" /></label>
            <label v-if="['backup','clone'].includes(action)">스토리지<ThemeSelect v-model="parameters.storage" label="대상 스토리지" :options="storageOptions" /></label>
            <template v-if="action === 'clone'"><label>새 VM ID<input v-model="parameters.newid" required type="number" min="100" max="999999999" /></label><label>새 이름<input v-model="parameters.name" required maxlength="128" pattern="[a-zA-Z0-9_.-]+" /></label></template>
            <label v-if="action === 'migrate'">대상 노드<ThemeSelect v-model="parameters.target" label="대상 노드" :options="nodeOptions" /></label>
            <label v-if="['cpu','memory'].includes(action)">{{ action === 'cpu' ? 'CPU 코어 수 (1–128)' : '메모리 MiB (16–1048576)' }}<input v-model="parameters.value" required type="number" :min="action === 'cpu' ? 1 : 16" :max="action === 'cpu' ? 128 : 1048576" /></label>
            <label v-if="action === 'onboot'">호스트 부팅 시 자동 시작<ThemeSelect v-model="parameters.value" label="자동 시작" :options="[{value:1,label:'켜기'},{value:0,label:'끄기'}]" /></label>
            <p v-if="action === 'migrate'" class="settings-description">실행 중인 VM은 온라인 이동합니다. 실행 중인 LXC는 재시작하며 이동합니다.</p><p v-if="['cpu','memory'].includes(action)" class="settings-description">일부 변경은 게스트를 종료한 뒤 다시 시작해야 적용됩니다.</p>
            <button class="primary-button" :disabled="busy">작업 확인</button>
          </template>
        </form>
        <form v-if="intent" class="pve-confirm" @submit.prevent="execute"><strong>{{ intent.target }} · {{ intent.label }}</strong><p>{{ intent.dangerous ? '데이터 손실이나 서비스 중단이 발생할 수 있습니다.' : '선택한 리소스에 작업을 실행합니다.' }}</p><dl v-if="Object.keys(intent.parameters).length"><template v-for="(value,key) in intent.parameters" :key="key"><dt>{{ ({snapname:'스냅샷',storage:'스토리지',newid:'새 VM ID',name:'새 이름',target:'대상 노드',value:'설정값'})[key] || key }}</dt><dd>{{ value }}</dd></template></dl><label>대상 ID <strong>{{ intent.confirmation }}</strong> 입력<input v-model="confirmation" required autocomplete="off" :disabled="busy" /></label><div class="pve-actions"><button type="button" class="secondary-button" :disabled="busy" @click="intent = null">취소</button><button :class="intent.dangerous ? 'danger-button' : 'primary-button'" :disabled="busy || confirmation !== intent.confirmation">{{ busy ? '요청 중…' : '실행' }}</button></div></form>
        </template>
      </section>
      <div v-reorder="{ kind:'pve-cards', disabled: !editing || busy }" class="pve-panel-sections">
        <section v-for="section in sections" :key="section.id" :data-sort-id="section.id" class="pve-card" :class="{'pve-half':section.width === 'half', 'pve-section-hidden':!section.visible}">
          <header class="pve-card-heading"><button v-if="editing" class="reorder-handle icon-button" :aria-label="`${sectionLabels[section.id]} 카드 순서 변경 · 위아래 방향키`" @keydown.up.prevent.stop="move(section.id,-1)" @keydown.down.prevent.stop="move(section.id,1)"><GripVertical :size="16" /></button><h3>{{ sectionLabels[section.id] }}</h3><template v-if="editing"><label><input v-model="section.visible" type="checkbox" />표시</label><ThemeSelect v-model="section.width" :label="`${sectionLabels[section.id]} 카드 너비`" :options="[{value:'full',label:'전체 너비'},{value:'half',label:'절반 너비'}]" /></template></header>
          <template v-if="section.visible">
          <div v-if="section.id === 'overview'" class="pve-overview"><div v-for="(label,key) in metricLabels" :key="key"><span>{{ label }}</span><strong>{{ metricText(integration.data.summary,key) }}</strong></div></div>
          <div v-else-if="section.id === 'nodes'" class="pve-node-list"><button v-for="node in integration.data.nodes" :key="node.id" class="pve-node" :disabled="busy || editing" @click="choose(node)"><span><Server :size="16" /><strong>{{ node.name }}</strong><i class="pve-dot" :class="node.status === 'online' ? 'up' : 'down'" /></span><small>CPU {{ (node.cpu * 100).toFixed(1) }}% · {{ bytes(node.mem) }} / {{ bytes(node.maxmem) }}</small><meter :value="node.maxmem ? node.mem/node.maxmem : 0" min="0" max="1" aria-label="메모리 사용량" /></button><p v-if="!integration.data.nodes?.length" class="pve-empty">조회 가능한 노드가 없습니다.</p></div>
          <template v-else-if="section.id === 'guests'"><div class="pve-guest-filters"><label class="pve-search"><Search :size="15" /><input v-model="query" type="search" placeholder="이름 · ID · 노드 검색" aria-label="Proxmox 게스트 검색" /></label><ThemeSelect v-model="filter" label="게스트 필터" :options="[{value:'all',label:'전체'},{value:'qemu',label:'VM'},{value:'lxc',label:'LXC'},{value:'running',label:'가동'},{value:'stopped',label:'중지'}]" /></div><div class="pve-table-wrap"><table class="pve-table"><thead><tr><th scope="col">이름</th><th v-for="key in columns" :key="key" scope="col">{{ columnLabels[key] }}</th></tr></thead><tbody><tr v-for="guest in pagedGuests" :key="guest.id"><th scope="row"><button :disabled="busy || editing" @click="choose(guest)"><span>{{ guest.name }}</span><small>{{ guest.type === 'qemu' ? 'VM' : 'LXC' }} {{ guest.vmid }}{{ guest.template ? ' · 템플릿' : '' }}</small></button></th><td v-for="key in columns" :key="key"><i v-if="key === 'status'" class="pve-dot" :class="guest.status === 'running' ? 'up' : 'idle'" />{{ cell(guest,key) }}</td></tr></tbody></table><p v-if="!guests.length" class="pve-empty">일치하는 게스트가 없습니다.</p></div><nav v-if="pageCount > 1" class="pve-pagination" aria-label="게스트 목록 페이지"><button class="secondary-button" :disabled="guestPage === 0" @click="guestPage--">이전</button><span>{{ Math.min(guestPage+1,pageCount) }} / {{ pageCount }} · {{ guests.length }}개</span><button class="secondary-button" :disabled="guestPage >= pageCount-1" @click="guestPage++">다음</button></nav></template>
          <div v-else-if="section.id === 'storage'" class="pve-storage-list"><div v-for="storage in integration.data.storage" :key="storage.id"><span><strong>{{ storage.storage }}</strong><small>{{ storage.node }}</small></span><span>{{ bytes(storage.disk) }} / {{ bytes(storage.maxdisk) }}</span><meter :value="storage.maxdisk ? storage.disk/storage.maxdisk : 0" min="0" max="1" aria-label="스토리지 사용량" /></div><p v-if="!integration.data.storage?.length" class="pve-empty">조회 가능한 스토리지가 없습니다.</p></div>
          <div v-else-if="section.id === 'tasks'" class="pve-task-list"><article v-for="task in tasks" :key="task.id"><span><strong>{{ actionLabels[task.action] }} · {{ task.target }}</strong><small>{{ new Date(task.created_at*1000).toLocaleString() }}</small><small v-if="task.detail">{{ task.detail }}</small></span><span class="pve-task-state" :data-state="task.state">{{ stateLabel(task.state) }}</span></article><p v-if="!tasks.length" class="pve-empty">이 앱에서 실행한 작업이 없습니다.</p></div>
          </template>
        </section>
      </div>
    </div>
    <footer class="pve-panel-footer"><span>{{ integration.checked_at ? `최근 확인 ${new Date(integration.checked_at*1000).toLocaleTimeString()}` : '확인한 정보 없음' }}</span><button class="secondary-button" :disabled="busy || !integration.config.enabled" @click="refresh"><RefreshCw :size="14" :class="{'pve-spinning':busy}" />{{ busy ? '확인 중…' : '새로고침' }}</button></footer>
  </dialog></Teleport>
</template>
