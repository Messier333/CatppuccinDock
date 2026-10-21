<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { Check, GripVertical, Moon, Pencil, RotateCcw, Settings2, Sun } from 'lucide-vue-next';
import { useTheme } from '../../composables/useTheme.js';
import { reorderDirective } from '../../directives/reorder.js';
import { appUrl } from '../../lib/navigation.js';
import { api } from '../../lib/api.js';
import LogoutButton from '../common/LogoutButton.vue';
import CalendarClock from './CalendarClock.vue';
import WeatherWidget from './WeatherWidget.vue';
import MetricWidget from './MetricWidget.vue';
import favicon from '../../assets/favicon.png';
const props = defineProps({ portal: { type: Object, required: true }, activeTab: Number, now: Date });
const emit = defineEmits(['select-tab']);
const editing = defineModel('editing', { default: false });
const { theme, toggleTheme } = useTheme();
const config = ref({ order: ['fastlink', 'tabs', 'weather', 'clock', 'theme', 'settings', 'logout', 'edit'], hidden: [], metrics: [] });
const error = ref(''), busy = ref(false);
const visible = computed(() => config.value.order.filter(key => !config.value.hidden.includes(key)));
let interval;
async function load() { try { const result = await api('footer'); if (!busy.value) config.value = result; } catch (cause) { error.value = cause.message; } }
async function reorder(kind, parentId, ids) {
  if (busy.value) return;
  const remaining = [...ids];
  const order = config.value.order.map(key => config.value.hidden.includes(key) ? key : remaining.shift());
  const previous = config.value.order;
  config.value.order = order;
  busy.value = true; error.value = '';
  try { await api('footer/order', { method: 'PUT', body: JSON.stringify({ order }) }); }
  catch (cause) { config.value.order = previous; error.value = cause.message; }
  finally { busy.value = false; }
}
function move(key, offset) { const ids = [...visible.value], index = ids.indexOf(key), target = index + offset; if (target < 0 || target >= ids.length) return; [ids[index], ids[target]] = [ids[target], ids[index]]; reorder('footer', null, ids); }
async function reset() { try { await api('footer/order', { method: 'DELETE' }); await load(); } catch (cause) { error.value = cause.message; } }
const vReorder = reorderDirective(reorder);
const label = key => ({ fastlink: '빠른 링크', tabs: '탭 선택', weather: '날씨', clock: '시계', theme: '테마', settings: '설정', logout: '로그아웃', edit: '화면 순서 편집' }[key] || config.value.metrics.find(item => 'metric:' + item.id === key)?.name || '모니터링');
onMounted(() => { load(); interval = setInterval(load, 30_000); });
onUnmounted(() => clearInterval(interval));
</script>
<template><footer class="startpage-statusbar" :class="{ 'footer-editing': editing }" aria-label="하단바">
  <p v-if="error" class="footer-error" role="alert">{{ error }}</p>
  <div v-reorder="{ kind: 'footer', disabled: !editing || busy }" class="footer-items">
    <div v-for="key in visible" :key="key" :data-sort-id="key" class="footer-item" :class="{ 'footer-tabs-item': key === 'tabs' }">
      <button v-if="editing" class="reorder-handle footer-grip" :aria-label="`${label(key)} 순서 변경 · 좌우 방향키`" @keydown.left.prevent.stop="move(key, -1)" @keydown.right.prevent.stop="move(key, 1)"><GripVertical :size="12" /></button>
      <a v-if="key === 'fastlink'" class="statusbar-fastlink" :href="portal.fastlink" target="_blank" rel="noopener noreferrer" aria-label="빠른 링크" @click="editing && $event.preventDefault()"><img :src="favicon" alt="" /></a>
      <div v-else-if="key === 'tabs'" class="statusbar-tabs" aria-label="탭 선택"><button v-for="(tab, index) in portal.tabs" :key="tab.id" :class="{ active: index === activeTab }" :aria-label="`${tab.name} 탭`" @click="emit('select-tab', index)">{{ tab.name }}</button></div>
      <WeatherWidget :inert="editing" v-else-if="key === 'weather'" :config="portal.temperature" />
      <CalendarClock :inert="editing" v-else-if="key === 'clock'" :clock="portal.clock" :now="now" />
      <button v-else-if="key === 'theme'" class="statusbar-widget theme-button" :aria-label="theme === 'mocha' ? '라이트 테마로 변경' : '다크 테마로 변경'" @click="toggleTheme"><Sun v-if="theme === 'mocha'" :size="16" /><Moon v-else :size="16" /></button>
      <a v-else-if="key === 'settings'" class="statusbar-widget admin-link" :href="appUrl('admin/')" aria-label="설정"><Settings2 :size="16" /></a>
      <LogoutButton v-else-if="key === 'logout'" compact />
      <template v-else-if="key === 'edit'"><button v-if="editing" class="statusbar-widget" aria-label="하단바 기본 순서 복원" :disabled="busy" @click="reset"><RotateCcw :size="14" /></button><button class="statusbar-widget footer-edit-button" :class="{ active: editing }" :aria-pressed="editing" :aria-label="editing ? '화면 편집 완료' : '화면 순서 편집'" @click="editing = !editing"><Check v-if="editing" :size="15" /><Pencil v-else :size="15" /></button></template>
      <MetricWidget :inert="editing" v-else-if="key.startsWith('metric:') && config.metrics.find(item => 'metric:' + item.id === key)" :metric="config.metrics.find(item => 'metric:' + item.id === key)" />
    </div>
  </div>
</footer></template>
