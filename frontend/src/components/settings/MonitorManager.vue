<script setup>
import { computed,onMounted,onUnmounted,reactive,ref } from 'vue';
import ThemeSelect from '../common/ThemeSelect.vue';
import ServiceStatus from '../common/ServiceStatus.vue';
import { api } from '../../lib/api.js';
import MonitorBulkDialog from './MonitorBulkDialog.vue';
const bulkDialog = ref(null);
async function bulkSaved(result) { try { await load(); notice.value = `${result.added}개 상태 확인 대상을 등록했어요.${result.duplicates ? ` 이미 등록된 ${result.duplicates}개는 건너뛰었어요.` : ''} 메인 화면에 보일 때 확인합니다.`; } catch (cause) { error.value = cause.message; } }
const items=ref([]),bookmarks=ref([]),selected=ref(''),error=ref(''),notice=ref(''),busy=ref(false),dialog=ref(null),target=ref(null);
const batch = ref(null);
let batchTimer, disposed = false;
const batchDone = computed(() => batch.value ? batch.value.ids.filter(id => { const item = items.value.find(row => row.id === id); return !item || !item.enabled || item.checked_at >= batch.value.started; }).length : 0);
const canCheckAll = computed(() => items.value.some(item => item.enabled));
async function pollBatch() {
  if (disposed || !batch.value) return;
  try {
    await load();
    if (batchDone.value === batch.value.ids.length) { notice.value = `전체 상태 확인을 마쳤어요. ${batchDone.value}개 확인 완료.`; batch.value = null; return; }
  } catch (cause) { error.value = cause.message; }
  if (!disposed) batchTimer = setTimeout(pollBatch, 1500);
}
async function checkAll() {
  if (busy.value || batch.value) return;
  busy.value = true; error.value = ''; notice.value = '';
  try {
    const result = await api('admin/monitors/check-all', { method: 'POST' });
    if (!result.queued_ids.length) notice.value = '확인할 활성 대상이 없거나 최근 15초 안에 이미 확인했어요.';
    else { batch.value = { ids: result.queued_ids, started: result.requested_at }; await pollBatch(); }
  } catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
}
onUnmounted(() => { disposed = true; clearTimeout(batchTimer); });
const draft=reactive({name:'',link_url:'https://',check_url:'https://',allow_private:false,enabled:true,interval:300});
async function load(){items.value=await api('admin/monitors');}
onMounted(async()=>{try{await load();const portal=await api('portal');bookmarks.value=portal.tabs.flatMap(tab=>tab.categories.flatMap(cat=>cat.links));}catch(e){error.value=e.message;}});
function edit(item=null){target.value=item;selected.value='';error.value='';Object.assign(draft,{name:item?.name||'',link_url:item?.link_url||'https://',check_url:item?.check_url||'https://',allow_private:item?.allow_private||false,enabled:item?.enabled??true,interval:item?.interval||300});dialog.value.showModal();}
function useBookmark(){const item=bookmarks.value.find(row=>row.id===selected.value);if(item)Object.assign(draft,{name:item.name,link_url:item.url,check_url:item.url});}
async function save(){busy.value=true;error.value='';try{await api('admin/monitors'+(target.value?'/'+target.value.id:''),{method:target.value?'PUT':'POST',body:JSON.stringify({...draft,interval:Number(draft.interval)})});dialog.value.close();await load();notice.value='상태 확인 대상을 저장했어요.';}catch(e){error.value=e.message;}finally{busy.value=false;}}
async function check(item){busy.value=true;error.value='';try{await api(`admin/monitors/${item.id}/check`,{method:'POST'});await load();}catch(e){error.value=e.message;}finally{busy.value=false;}}
async function remove(item){if(!confirm(`‘${item.name}’ 상태 확인을 삭제할까요? 북마크는 유지됩니다.`))return;try{await api('admin/monitors/'+item.id,{method:'DELETE'});await load();}catch(e){error.value=e.message;}}
</script>
<template><section class="settings-section"><div class="management-toolbar"><p class="settings-description">메인 화면에 보이는 등록된 북마크만 확인합니다. 스크롤·탭 전환 시 갱신하며 확인 간격 이내의 결과는 재사용합니다. 초록은 온라인(인증 필요 응답 포함), 빨강은 응답 없음·오류, 회색은 미확인입니다. 등록한 북마크를 볼 수 있는 사용자에게 상태가 표시됩니다.</p><div class="inline-actions"><button class="secondary-button" :disabled="busy || !!batch || !canCheckAll" @click="checkAll">{{ batch ? `전체 확인 중 · ${batchDone}/${batch.ids.length}` : '전체 상태 확인' }}</button><button class="secondary-button" @click="bulkDialog.open()">북마크 일괄 등록</button><button class="primary-button" @click="edit()">상태 확인 대상 추가</button></div></div><p class="settings-description">확인 주소를 내부 서비스의 상태 확인 주소로 지정할 수 있습니다. 로그인 쿠키는 전달하지 않으며 401·403 응답도 온라인으로 표시하고 반복 요청을 줄이기 위해 자동 재확인은 하루 동안 유예합니다. 로그인 화면이 응답하면 온라인으로 표시됩니다.</p><p v-if="error&&!dialog?.open" class="form-error" role="alert">{{ error }}</p><p v-if="batch" class="form-notice" role="status" aria-live="polite">전체 상태 확인 중 · {{ batchDone }}/{{ batch.ids.length }}개 완료. 서버에서 확인하고 있어요.</p><p v-if="notice" class="form-notice" role="status">{{ notice }}</p><div class="settings-card"><article v-for="item in items" :key="item.id" class="editable-link"><ServiceStatus v-if="item.enabled" :status="item" /><div class="operation-row-content"><strong>{{ item.name }}</strong><small>{{ item.link_url }}</small><small>{{ item.enabled?item.detail||'확인 대기 중':'확인 중지' }} {{ item.http_status?'· HTTP '+item.http_status:'' }}</small></div><div class="inline-actions"><button class="secondary-button" :aria-label="item.name+' 지금 확인'" :disabled="busy || !!batch" @click="check(item)">지금 확인</button><button class="secondary-button" :aria-label="item.name+' 상태 수정'" @click="edit(item)">수정</button><button class="secondary-button danger" :aria-label="item.name+' 상태 삭제'" @click="remove(item)">삭제</button></div></article><p v-if="!items.length" class="settings-empty">상태 확인 대상이 없습니다. 상태 확인을 활성화한 북마크에만 오른쪽 상태 도트가 표시됩니다.</p></div>
<dialog ref="dialog" v-dialog-dismiss="busy" class="editor-dialog"><form class="settings-form" @submit.prevent="save"><div class="card-heading"><h2>서비스 상태 확인 설정</h2><button class="icon-button" type="button" aria-label="닫기" :disabled="busy" @click="dialog.close()">×</button></div><label>내 북마크에서 선택 (선택)<ThemeSelect v-model="selected" label="상태 확인 북마크" placeholder="직접 입력하거나 북마크를 선택하세요" @change="useBookmark" :options="bookmarks.map(item=>({value:item.id,label:item.name+' · '+item.url}))" /></label><label>대상 이름<input v-model="draft.name" required maxlength="120" /></label><label>북마크 주소<input v-model="draft.link_url" type="url" required maxlength="2048" /></label><label>상태 확인 주소<input v-model="draft.check_url" type="url" required maxlength="2048" /><small>내부 상태 확인 주소를 지정하면 리버스 프록시 로그인 화면을 거치지 않고 확인할 수 있습니다.</small></label><label>확인 간격 (초)<input v-model="draft.interval" type="number" min="60" max="86400" required /></label><label class="checkbox-label"><input v-model="draft.allow_private" type="checkbox" />내부 네트워크 주소 확인 허용</label><label class="checkbox-label"><input v-model="draft.enabled" type="checkbox" />주기적 확인 사용</label><p v-if="error" class="form-error" role="alert">{{ error }}</p><button class="primary-button" :disabled="busy">상태 확인 설정 저장</button></form></dialog><MonitorBulkDialog ref="bulkDialog" @saved="bulkSaved" /></section></template>
