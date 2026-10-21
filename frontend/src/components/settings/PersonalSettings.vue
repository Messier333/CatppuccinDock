<script setup>
import { onMounted, reactive, ref } from 'vue';
import ThemeSelect from '../common/ThemeSelect.vue';
import AppInstall from '../common/AppInstall.vue';
import { api } from '../../lib/api.js';
const data = ref(null), draft = reactive({}), busy = ref(false), error = ref(''), notice = ref('');
function assign(result) {
  data.value = result;
  for (const key of Object.keys(result.defaults)) draft[key] = result.overrides[key] ?? null;
}
onMounted(async () => { try { assign(await api('account/preferences')); } catch (cause) { error.value = cause.message; } });
async function save(reset = false) {
  busy.value = true; error.value = ''; notice.value = '';
  try { assign(await api('account/preferences', { method:'PUT', body:JSON.stringify(reset ? {} : draft) })); notice.value = reset ? '관리자 기본값을 따르도록 초기화했어요.' : '개인 설정을 저장했어요. 메인 페이지에 적용됩니다.'; }
  catch (cause) { error.value = cause.message; } finally { busy.value = false; }
}
function options(key, items) { return [{value:null,label:`관리자 기본값 · ${items.find(item => item.value === data.value?.defaults[key])?.label || data.value?.defaults[key]}`}, ...items]; }
const engines = [{value:'g',label:'Google'},{value:'d',label:'DuckDuckGo'},{value:'y',label:'Yandex'},{value:'p',label:'Perplexity'}];
const formats = [{value:'24h',label:'24시간'},{value:'12h',label:'12시간 · AM/PM'}];
const animations = [{value:'system',label:'기기 설정 따르기'},{value:'on',label:'항상 켜기'},{value:'off',label:'끄기'}];
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
</script>
<template><section class="settings-section"><p class="settings-description">내 계정에만 적용됩니다. 관리자 기본값을 선택하거나 입력란을 비우면 공통 설정을 따릅니다.</p><p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="notice" class="form-notice" role="status">{{ notice }}</p>
<div v-if="data" class="settings-card" data-settings-anchor="personal"><h2>내 화면 설정</h2><form class="settings-form" @submit.prevent="save()">
<label>내 검색 엔진<ThemeSelect v-model="draft.search_engine" label="내 검색 엔진" :options="options('search_engine',engines)" /></label>
<label>내 시간 표시 형식<ThemeSelect v-model="draft.clock_format" label="내 시간 표시 형식" :options="options('clock_format',formats)" /></label>
<label>내 시간대<input :value="draft.timezone || ''" maxlength="100" :placeholder="data.defaults.timezone" @input="draft.timezone = $event.target.value.trim() || null" /></label>
<label>내 날씨 위치<input :value="draft.weather_location || ''" maxlength="80" :placeholder="data.defaults.weather_location" @input="draft.weather_location = $event.target.value.trim() || null" /></label>
<label>내 온도 단위<ThemeSelect v-model="draft.temperature_scale" label="내 온도 단위" :options="options('temperature_scale',[{value:'C',label:'섭씨 °C'},{value:'F',label:'화씨 °F'}])" /></label>
<label data-settings-anchor="personal-animation">내 슬라이드 효과<ThemeSelect v-model="draft.animation_mode" label="내 슬라이드 효과" :options="options('animation_mode',animations)" /><small>{{ reduced ? '현재 기기는 동작 줄이기를 사용 중입니다. 항상 켜기를 선택하면 이 포털의 슬라이드는 표시됩니다.' : '기기 설정 따르기는 운영체제의 동작 줄이기를 반영합니다.' }}</small></label>
<div class="inline-actions"><button class="primary-button" :disabled="busy">개인 설정 저장</button><button class="secondary-button" type="button" :disabled="busy" @click="save(true)">관리자 기본값으로 초기화</button></div>
</form></div><div class="settings-card"><h2>앱으로 설치</h2><AppInstall details /></div></section></template>
