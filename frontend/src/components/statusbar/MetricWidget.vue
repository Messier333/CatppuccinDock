<script setup>
import { computed } from 'vue';
import { Activity } from 'lucide-vue-next';
import WidgetPanel from './WidgetPanel.vue';
const props = defineProps({ metric: { type: Object, required: true } });
const stale = computed(() => !props.metric.checked_at || Date.now() / 1000 - props.metric.checked_at > Math.max(180, props.metric.interval * 3));
const available = computed(() => props.metric.result?.available && !stale.value);
const text = computed(() => !available.value ? '—' : props.metric.display === 'status' ? ({ up: '정상', down: '장애', maintenance: '점검', pending: '대기' }[props.metric.result.state] || '대기') : `${Number(props.metric.result.value).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}${props.metric.unit}`);
const segments = computed(() => {
  const points = props.metric.result?.points || [], values = points.filter(Number.isFinite);
  if (!values.length) return [];
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const paths = []; let current = [];
  points.forEach((value, index) => { if (!Number.isFinite(value)) { if (current.length) paths.push(current.join(' ')); current = []; } else current.push(`${(index / Math.max(1, points.length - 1) * 64).toFixed(2)},${(20 - (value - min) / span * 17).toFixed(2)}`); });
  if (current.length) paths.push(current.join(' '));
  return paths;
});
</script>
<template><WidgetPanel :label="`${metric.name} 모니터링`"><template #trigger="{ open, reveal }"><button class="statusbar-widget metric-widget" :aria-label="`${metric.name} · ${text}`" :aria-expanded="open" aria-haspopup="dialog" @click="reveal"><i v-if="metric.display === 'status'" class="metric-dot" :data-state="available ? metric.result.state : 'pending'" /><Activity v-else :size="13" /><span>{{ metric.name }}</span><svg v-if="metric.display === 'sparkline' && available" viewBox="0 0 64 24" class="metric-sparkline" aria-hidden="true"><polyline v-for="(segment, index) in segments" :key="index" :points="segment" /></svg><strong>{{ text }}</strong></button></template><div class="widget-panel-heading"><strong>{{ metric.name }}</strong><small>{{ metric.provider === 'kuma' ? 'Uptime Kuma' : metric.provider === 'grafana' ? 'Grafana' : 'Prometheus' }}</small></div><p class="weather-temperature">{{ text }}</p><svg v-if="available && segments.length" viewBox="0 0 64 24" class="metric-history" aria-label="최근 측정 추이" role="img"><polyline v-for="(segment, index) in segments" :key="index" :points="segment" /></svg><p v-if="!available" class="widget-detail">{{ stale ? '최신 데이터 수신 대기 중' : metric.result?.detail || '데이터 수신 대기 중' }}</p><p class="widget-detail">최근 확인 · {{ metric.checked_at ? new Date(metric.checked_at * 1000).toLocaleString('ko-KR') : '기록 없음' }}</p></WidgetPanel></template>
