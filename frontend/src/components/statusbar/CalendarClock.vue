<script setup>
import { computed, ref } from 'vue';
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-vue-next';
import WidgetPanel from './WidgetPanel.vue';
import ThemeSelect from '../common/ThemeSelect.vue';
import { formatClock, formatDate } from '../../lib/clock.js';
import { calendarDate, monthDays } from '../../lib/calendar.js';
const props = defineProps({ clock: { type: Object, default: () => ({}) }, now: { type: Date, required: true } });
const today = computed(() => calendarDate(props.now, props.clock.timezone));
const year = ref(today.value.year), month = ref(today.value.month), selected = ref(null);
const days = computed(() => monthDays(year.value, month.value));
const years = Array.from({ length: 301 }, (_, index) => ({ value: 1900 + index, label: `${1900 + index}년` }));
const months = Array.from({ length: 12 }, (_, index) => ({ value: index + 1, label: `${index + 1}월` }));
function move(delta) { const next = new Date(Date.UTC(year.value, month.value - 1 + delta, 1)); if (next.getUTCFullYear() < 1900 || next.getUTCFullYear() > 2200) return; year.value = next.getUTCFullYear(); month.value = next.getUTCMonth() + 1; }
function reset() { year.value = today.value.year; month.value = today.value.month; selected.value = null; }
function choose(day) { if (day.year < 1900 || day.year > 2200) return; selected.value = day.key; year.value = day.year; month.value = day.month; }
</script>
<template><WidgetPanel label="달력"><template #trigger="{ open, pinned, togglePin }"><button class="statusbar-widget clock-widget" :aria-expanded="open" :aria-pressed="pinned" aria-haspopup="dialog" aria-label="시계 · 달력 열기" @click="togglePin"><CalendarDays :size="14" /><time>{{ formatClock(now, clock) }}</time></button></template>
  <div class="widget-panel-heading"><strong>달력</strong><small>{{ clock.timezone || 'Asia/Seoul' }}</small></div>
  <p class="calendar-today">{{ formatDate(now, clock) }}</p>
  <div class="calendar-navigation"><button aria-label="이전 달" @click="move(-1)"><ChevronLeft :size="16" /></button><ThemeSelect v-model="year" label="달력 연도" :options="years" /><ThemeSelect v-model="month" label="달력 월" :options="months" /><button aria-label="다음 달" @click="move(1)"><ChevronRight :size="16" /></button></div>
  <div class="calendar-grid"><span v-for="name in ['일', '월', '화', '수', '목', '금', '토']" :key="name" class="calendar-weekday">{{ name }}</span><button v-for="day in days" :key="day.key" :class="{ 'other-month': day.month !== month, today: day.year === today.year && day.month === today.month && day.day === today.day, selected: selected === day.key }" :aria-label="`${day.year}년 ${day.month}월 ${day.day}일`" :aria-current="day.year === today.year && day.month === today.month && day.day === today.day ? 'date' : undefined" :aria-pressed="selected === day.key" @click="choose(day)">{{ day.day }}</button></div>
  <button class="calendar-reset" @click="reset">오늘로 돌아가기</button>
</WidgetPanel></template>
