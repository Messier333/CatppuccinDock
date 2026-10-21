<script setup>
import { onMounted,ref } from 'vue';
import { api } from '../../lib/api.js';
const items=ref([]),error=ref(''),notice=ref(''),busy=ref(false);
const labels={tab:'탭',category:'카테고리',bookmark:'북마크',order:'순서 변경',replace:'덮어쓰기 복원',bookmarks:'북마크 일괄 삭제','bookmark-edit':'북마크 일괄 편집'};
async function load(){items.value=await api('trash');}
onMounted(async()=>{try{await load();}catch(e){error.value=e.message;}});
async function act(item,restore){if(!restore&&!confirm(`‘${item.label}’ 항목을 영구 삭제할까요?`))return;busy.value=true;error.value='';try{await api(`trash/${item.id}${restore?'/restore':''}`,{method:restore?'POST':'DELETE'});await load();notice.value=restore?'복원했어요. 메인과 북마크 목록에서 확인할 수 있습니다.':'영구 삭제했어요.';}catch(e){error.value=e.message;}finally{busy.value=false;}}
</script>
<template><section class="settings-section"><p class="settings-description">삭제한 탭·카테고리·북마크와 순서 변경 기록을 30일 동안 최대 100건 보관합니다. 상위 항목을 삭제했다면 상위 항목부터 복원하세요. 덮어쓰기 복원은 이후 편집이 없을 때 되돌릴 수 있습니다.</p><p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="notice" class="form-notice" role="status">{{ notice }}</p><div class="settings-card"><article v-for="item in items" :key="item.id" class="editable-link"><div class="operation-row-content"><strong>{{ item.label }}</strong><small>{{ labels[item.kind]||item.kind }} · {{ new Date(item.created_at*1000).toLocaleString('ko-KR') }}</small><small>{{ new Date(item.expires_at*1000).toLocaleDateString('ko-KR') }}까지 복원 가능</small></div><button class="secondary-button" :aria-label="item.label+' 복원'" :disabled="busy" @click="act(item,true)">{{ ['order','replace','bookmark-edit'].includes(item.kind)?'되돌리기':'복원' }}</button><button class="secondary-button danger" :aria-label="item.label+' 영구 삭제'" :disabled="busy" @click="act(item,false)">영구 삭제</button></article><p v-if="!items.length" class="settings-empty">휴지통이 비어 있습니다.</p></div></section></template>
