<script setup>
import { onMounted, ref } from 'vue';
import { api } from '../../lib/api.js';
const state=ref(null),key=ref(''),clearKey=ref(false),busy=ref(false),error=ref(''),notice=ref('');
onMounted(async()=>{try{state.value=await api('admin/backgrounds');}catch(cause){error.value=cause.message;}});
async function save(){
  busy.value=true;error.value='';notice.value='';
  try{
    const config={...state.value};
    delete config.has_pixabay_key;
    state.value=await api('admin/backgrounds',{method:'PUT',body:JSON.stringify({...config,pixabay_key:key.value||null,clear_pixabay_key:clearKey.value})});
    key.value='';clearKey.value=false;notice.value='GIF 제공처와 사용 한도를 저장했어요.';
  }catch(cause){error.value=cause.message;}finally{busy.value=false;}
}
</script>
<template><section class="settings-section"><p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="notice" class="form-notice" role="status">{{ notice }}</p>
<form v-if="state" class="settings-form media-settings-form" @submit.prevent="save">
  <div class="settings-card" data-settings-anchor="gif-providers"><h2>GIF 검색 제공처</h2><p class="settings-description">통합 검색에서 GIFDB·Alpha Coders·MotionBgs를 함께 검색합니다. Pixabay 키를 등록하면 도시·자연 풍경 영상도 검색하며, 선택한 영상의 처음 20초를 GIF로 변환해 서버에 저장합니다.</p>
    <label>Pixabay API 키<input v-model="key" aria-label="Pixabay API 키" type="password" maxlength="256" autocomplete="new-password" :placeholder="state.has_pixabay_key?'등록됨 · 비우면 유지':'API 키 입력'" /><small><a href="https://pixabay.com/api/docs/" target="_blank" rel="noopener noreferrer">Pixabay에서 API 키 발급</a> · 키는 서버에 암호화하여 저장합니다.</small></label>
    <label v-if="state.has_pixabay_key" class="checkbox-label"><input v-model="clearKey" type="checkbox" />등록한 Pixabay 키 제거</label>
  </div>
  <div class="settings-card" data-settings-anchor="gif-member-limits"><h2>일반 사용자 GIF 추가</h2><p class="settings-description">카테고리·탭 추가와 저장된 GIF 선택은 계속 사용할 수 있습니다. 아래 제한은 새 GIF를 가져오거나 직접 업로드할 때 적용됩니다. 실패한 요청도 횟수와 실제 받은 용량에 포함되며, 파일 삭제·재로그인·서버 재시작으로 초기화되지 않습니다.</p>
    <label class="checkbox-label"><input v-model="state.member_import" type="checkbox" />일반 사용자의 외부 GIF 가져오기 허용</label>
    <label class="checkbox-label"><input v-model="state.member_upload" type="checkbox" />일반 사용자의 GIF 업로드 허용</label>
    <div class="media-policy-grid"><label>분당 추가 횟수<input v-model.number="state.member_per_minute" type="number" min="1" max="10" required /></label><label>하루 추가 횟수<input v-model.number="state.member_per_day" type="number" min="1" max="100" required /></label><label>하루 원본 용량 (MB)<input v-model.number="state.member_daily_mb" type="number" min="1" max="2000" required /></label><label>사용자별 저장 용량 (MB)<input v-model.number="state.member_storage_mb" type="number" min="10" max="200" required /></label></div>
  </div>
  <div class="settings-card" data-settings-anchor="gif-server-limits"><h2>서버 전체 GIF 한도</h2><p class="settings-description">관리자를 포함한 전체 계정에 적용됩니다. 새 파일은 다운로드 전에 저장 공간과 남은 사용량을 검사하고, 한 번에 하나씩 처리합니다. 일일 한도는 공통 시계의 시간대에서 자정에 초기화됩니다.</p>
    <div class="media-policy-grid"><label>하루 전체 추가 횟수<input v-model.number="state.server_per_day" type="number" min="1" max="5000" required /></label><label>하루 전체 원본 용량 (MB)<input v-model.number="state.server_daily_mb" type="number" min="1" max="50000" required /></label><label>전체 저장 용량 (MB)<input v-model.number="state.server_storage_mb" type="number" min="10" max="100000" required /></label></div>
  </div>
  <button class="primary-button" :disabled="busy">{{busy?'저장 중…':'GIF 설정 저장'}}</button>
</form></section></template>
