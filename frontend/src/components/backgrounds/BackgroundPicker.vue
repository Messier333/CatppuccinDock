<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Check, ImageOff, Trash2, Upload, Search } from 'lucide-vue-next';
import { api } from '../../lib/api.js';
import { backgroundUrl } from '../../lib/backgrounds.js';
import GifSearch from './GifSearch.vue';

const model = defineModel({ default: null });
const banner = defineModel('banner', { default: 'none' });
const emit = defineEmits(['busy']);
const items = ref([]), loading = ref(true), busy = ref(false), error = ref(''), notice = ref('');
const usage=ref(null);
const dailyLimit=computed(()=>usage.value?.daily_count_limit!=null && usage.value.today_count>=usage.value.daily_count_limit);
const canImport=computed(()=>usage.value?.allow_import!==false && !dailyLimit.value && items.value.length<limits.value.max_files);
const canUpload=computed(()=>usage.value?.allow_upload!==false && !dailyLimit.value && items.value.length<limits.value.max_files);
const input = ref(null), previewError = ref(false);
const failedPreviews = ref(new Set());
const searchOpen = ref(false);
const limits = ref({ max_bytes: 10 * 1024 * 1024, max_input_bytes: 100 * 1024 * 1024, max_files: 20 });
const selected = computed(() => items.value.find(item => item.id === model.value));
const preview = computed(() => backgroundUrl({ banner: banner.value, background_id: model.value }));
watch(preview, () => previewError.value = false);
watch(busy, value => emit('busy', value), { flush: 'sync' });
let controller;
onMounted(async () => {
  try { const result = await api('backgrounds'); items.value = result.items; limits.value = { ...limits.value, ...result.limits }; usage.value=result.usage; }
  catch (cause) { error.value = cause.message; }
  finally { loading.value = false; }
});
onBeforeUnmount(() => { controller?.abort(); emit('busy', false); });
function size(bytes) { return bytes < 1024 * 1024 ? `${Math.ceil(bytes / 1024)}KB` : `${(bytes / 1024 / 1024).toFixed(1)}MB`; }
function selectSaved(id) {
  if (busy.value || loading.value) return;
  model.value = id; banner.value = 'none'; notice.value = '';
}
async function refreshUsage(){try{usage.value=(await api('backgrounds')).usage;}catch{/* The next open refreshes usage again. */}}
function choose(image) {
  items.value = [image, ...items.value.filter(item => item.id !== image.id)];
  model.value = image.id; banner.value = 'none';
  notice.value = 'GIF를 서버에 저장했어요. 아래 저장 버튼을 누르면 탭에 적용됩니다.';
}
async function upload(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file || busy.value || !canUpload.value) return;
  error.value = ''; notice.value = '';
  if (file.size > limits.value.max_input_bytes) { error.value = '원본 GIF는 최대 100MB까지 업로드할 수 있어요.'; return; }
  if (!file.size || (!/\.gif$/i.test(file.name) && file.type !== 'image/gif')) { error.value = 'GIF 파일을 선택해 주세요.'; return; }
  busy.value = true; controller = new AbortController();
  try {
    const result = await api('backgrounds', { method: 'POST', body: file, headers: { 'Content-Type': 'image/gif', 'X-File-Name': encodeURIComponent(Array.from(file.name).slice(0, 120).join('')) }, signal: controller.signal });
    choose(result);
    notice.value = 'GIF를 선택했어요. 아래 저장 버튼을 누르면 메인에 적용됩니다.';
  } catch (cause) { if (cause.name !== 'AbortError') error.value = cause.message; }
  finally { busy.value = false; refreshUsage(); }
}
async function remove() {
  const image = selected.value;
  if (!image || image.used_by || busy.value || !window.confirm(`‘${image.name}’ GIF를 삭제할까요?`)) return;
  busy.value = true; error.value = ''; notice.value = '';
  try {
    await api(`backgrounds/${image.id}`, { method: 'DELETE' });
    items.value = items.value.filter(item => item.id !== image.id);
    model.value = null;
    notice.value = '사용하지 않는 GIF를 삭제했어요.';
  } catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
}
</script>
<template>
  <div class="background-picker">
    <fieldset class="background-field" :disabled="busy || loading">
      <legend>메뉴 제목 배경</legend>
      <p v-if="loading" class="settings-description" role="status">저장된 GIF를 불러오는 중이에요…</p>
      <div class="background-library">
        <button type="button" class="background-choice" :aria-pressed="!model" @click="selectSaved(null)">
          <span class="background-thumbnail background-thumbnail-empty"><ImageOff :size="24" aria-hidden="true" /></span>
          <span class="background-choice-name">배경 없음</span>
          <Check v-if="!model" class="background-choice-check" :size="16" aria-hidden="true" />
        </button>
        <button v-for="image in items" :key="image.id" type="button" class="background-choice" :aria-pressed="model === image.id" :aria-label="`${image.name} 배경 선택`" :title="image.name" @click="selectSaved(image.id)">
          <span v-if="failedPreviews.has(image.id)" class="background-thumbnail background-thumbnail-empty"><ImageOff :size="20" aria-hidden="true" /><span>미리보기 없음</span></span>
          <img v-else class="background-thumbnail" :src="backgroundUrl({ background_id: image.id })" alt="" loading="lazy" decoding="async" @error="failedPreviews.add(image.id)" />
          <span class="background-choice-name">{{ image.name }}</span>
          <Check v-if="model === image.id" class="background-choice-check" :size="16" aria-hidden="true" />
        </button>
      </div>
    </fieldset>
    <div class="background-preview"><span v-if="!preview">배경 없음</span><img v-else-if="!previewError" :src="preview" alt="선택한 메뉴 배경 미리보기" @error="previewError = true" /><span v-else>배경을 불러오지 못했어요.</span></div>
    <div class="background-actions"><button type="button" class="secondary-button" :disabled="busy || loading || usage?.allow_import===false" :aria-expanded="searchOpen" @click="searchOpen = !searchOpen"><Search :size="15" />GIF 검색·선택</button><button type="button" class="secondary-button" :disabled="busy || loading || !canUpload" @click="input.click()"><Upload :size="15" />{{ busy ? '처리 중…' : 'GIF 업로드' }}</button><span>{{ items.length }} / {{ limits.max_files }}개 · 원본 최대 100MB</span><input ref="input" type="file" name="gif_background" accept="image/gif,.gif" aria-label="GIF 파일 선택" hidden @change="upload" /></div>
    <p v-if="usage?.daily_count_limit!=null" class="settings-description">오늘 GIF 추가 {{usage.today_count}} / {{usage.daily_count_limit}}회 · 원본 {{size(usage.today_bytes)}} / {{size(usage.daily_bytes_limit)}} · {{usage.timezone}} 기준</p>
    <p v-if="dailyLimit" class="settings-description">오늘의 GIF 추가 횟수를 모두 사용했어요. 저장된 GIF는 계속 선택할 수 있습니다.</p>
    <p v-if="usage && !usage.allow_import && !usage.allow_upload" class="settings-description">관리자가 새 GIF 추가를 비활성화했어요. 저장된 GIF를 선택해 주세요.</p>
    <GifSearch v-if="searchOpen" :disabled="busy || loading" :allow-import="canImport" @busy="busy = $event" @select="choose" @settled="refreshUsage" />
    <div v-if="selected" class="background-details"><span><strong>{{ selected.name }}</strong><small>{{ selected.width }} × {{ selected.height }} · {{ size(selected.byte_size) }} · {{ selected.used_by ? `${selected.used_by}개 탭에서 사용 중` : '아직 사용하지 않음' }}</small></span><button type="button" class="icon-button danger" aria-label="선택한 GIF 삭제" :disabled="busy || !!selected.used_by" @click="remove"><Trash2 :size="15" /></button></div>
    <p v-if="selected?.used_by" class="settings-description">사용 중인 GIF는 탭의 배경을 다른 것으로 바꾸고 저장한 뒤 삭제할 수 있어요.</p>
    <p v-if="selected?.source" class="settings-description">{{ selected.source.author }} · <a :href="selected.source.page_url" target="_blank" rel="noopener noreferrer">{{ selected.source.title }} · {{ selected.source.license || '출처' }}</a><template v-if="selected.source.license_url"> · <a :href="selected.source.license_url" target="_blank" rel="noopener noreferrer">라이선스</a></template></p>
    <p class="settings-description">큰 GIF는 애니메이션을 유지하며 해상도·프레임·색상 수를 조절해 10MB 이하로 저장합니다. 메인에서는 메뉴 제목 뒤를 가운데 기준으로 채웁니다.</p>
    <p v-if="busy" class="settings-description" role="status">GIF를 확인하고 필요한 경우 크기를 줄이는 중이에요…</p>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="form-notice" role="status">{{ notice }}</p>
  </div>
</template>
