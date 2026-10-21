<script setup>
import { onMounted, onUnmounted, ref } from 'vue';
import { CloudSun, RefreshCw } from 'lucide-vue-next';
import { api } from '../../lib/api.js';
import WidgetPanel from './WidgetPanel.vue';
const props = defineProps({ config: { type: Object, required: true } });
const weather = ref(null), loading = ref(false);
let timer, disposed = false;
async function load(manual = false) {
  if (loading.value) return;
  loading.value = true;
  const started = Date.now();
  try { weather.value = await api(manual ? 'weather/refresh' : 'weather', manual ? { method: 'POST' } : {}); }
  catch { weather.value = { available: false, message: '온도를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.' }; }
  finally {
    // Keep the refresh feedback perceptible even when the response is cached.
    if (manual && Date.now() - started < 400) await new Promise(resolve => setTimeout(resolve, 400 - (Date.now() - started)));
    loading.value = false;
    clearTimeout(timer);
    if (!disposed) timer = setTimeout(() => load(), weather.value?.available ? 600_000 : 60_000);
  }
}
onMounted(() => load());
onUnmounted(() => { disposed = true; clearTimeout(timer); });
</script>
<template><WidgetPanel label="날씨 정보" class="weather-anchor"><template #trigger="{ open, reveal }"><button class="statusbar-widget weather-widget" aria-label="날씨 새로고침" :aria-expanded="open" aria-haspopup="dialog" :aria-busy="loading" :disabled="loading" @click="reveal(); load(true)"><CloudSun :size="16" /><span aria-live="polite">{{ config.location }} · {{ loading && !weather ? '조회 중…' : weather?.available ? `${Math.round(weather.temperature)}°${weather.scale}` : '조회 불가' }}</span><RefreshCw :size="13" :class="{ 'widget-spinning': loading }" /></button></template>
  <div class="widget-panel-heading"><strong>날씨</strong><CloudSun :size="18" /></div><p class="weather-location">{{ weather?.resolved_location || config.location }}</p><p class="weather-temperature">{{ weather?.available ? `${Math.round(weather.temperature)}°${weather.scale}` : '조회 불가' }}</p><p v-if="!weather?.available" class="widget-detail">{{ weather?.message || '온도를 조회하고 있어요.' }}</p><p v-if="weather?.observed_at" class="widget-detail">관측 시간 · {{ weather.observed_at.replace('T', ' ') }} (현지)</p><p class="widget-detail">10분마다 자동 갱신 · 수동 갱신은 1분 간격</p><button class="calendar-reset" :disabled="loading" @click="load(true)"><RefreshCw :size="13" :class="{ 'widget-spinning': loading }" />{{ loading ? '새로고침 중…' : '지금 새로고침' }}</button><p class="widget-attribution"><a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Open-Meteo</a> · <a href="https://www.geonames.org/" target="_blank" rel="noopener noreferrer">GeoNames</a></p>
</WidgetPanel></template>
