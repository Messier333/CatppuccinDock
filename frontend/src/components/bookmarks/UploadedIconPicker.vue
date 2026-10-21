<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Trash2, Upload } from 'lucide-vue-next';
import { api } from '../../lib/api.js';
import BookmarkIcon from '../common/BookmarkIcon.vue';

const props = defineProps({ selected: String, disabled: Boolean });
const emit = defineEmits(['select', 'busy']);
const items = ref([]), query = ref(''), loading = ref(true), busy = ref(false), error = ref('');
const input = ref(null), pendingDelete = ref(null);
const filtered = computed(() => items.value.filter(item => item.name.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())));
const unavailable = computed(() => props.disabled || busy.value || loading.value);
let controller;
watch(busy, value => emit('busy', value), { flush: 'sync' });
onMounted(async () => {
  controller = new AbortController();
  try { items.value = (await api('uploaded-icons', { signal: controller.signal })).items; }
  catch (cause) { if (cause.name !== 'AbortError') error.value = cause.message; }
  finally { loading.value = false; }
});
onBeforeUnmount(() => { controller?.abort(); emit('busy', false); });
async function upload(event) {
  const file = event.target.files?.[0]; event.target.value = '';
  if (!file || unavailable.value) return;
  error.value = '';
  if (file.size > 5*1024*1024) { error.value = '아이콘 원본은 최대 5MB까지 업로드할 수 있어요.'; return; }
  busy.value = true; controller = new AbortController();
  try {
    const item = await api('uploaded-icons', { method: 'POST', body: file, signal: controller.signal,
      headers: { 'Content-Type': file.type || 'application/octet-stream', 'X-File-Name': encodeURIComponent(Array.from(file.name).slice(0, 120).join('')) } });
    items.value = [item, ...items.value.filter(value => value.id !== item.id)];
    emit('select', item);
  } catch (cause) { if (cause.name !== 'AbortError') error.value = cause.message; }
  finally { busy.value = false; }
}
async function remove() {
  if (!pendingDelete.value || unavailable.value) return;
  const item = pendingDelete.value;
  busy.value = true; error.value = '';
  try {
    await api('uploaded-icons/'+encodeURIComponent(item.id), { method: 'DELETE' });
    items.value = items.value.filter(value => value.id !== item.id); pendingDelete.value = null;
    if (props.selected === item.icon) emit('select', { icon: 'world' });
  } catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
}
</script>

<template>
  <div class="uploaded-icon-picker">
    <div class="inline-actions"><button type="button" class="secondary-button" :disabled="unavailable || items.length >= 100" @click="input.click()"><Upload :size="15" aria-hidden="true" />{{ busy ? '처리 중…' : '아이콘 파일 업로드' }}</button><span class="settings-description">{{ items.length }} / 100개</span></div>
    <input ref="input" type="file" accept=".png,.jpg,.jpeg,.webp,.svg,.ico,.gif,image/png,image/jpeg,image/webp,image/svg+xml,image/x-icon,image/vnd.microsoft.icon,image/gif" aria-label="아이콘 파일 선택" hidden @change="upload" />
    <label>내 업로드 아이콘 검색<input v-model="query" type="search" maxlength="80" placeholder="파일 이름으로 검색" /></label>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="settings-description" role="status">업로드 아이콘을 불러오는 중이에요…</p>
    <div class="uploaded-icon-grid">
      <div v-for="item in filtered" :key="item.id" class="uploaded-icon-tile">
        <button type="button" class="uploaded-icon-choice" :aria-label="`${item.name} 업로드 아이콘 선택`" :aria-pressed="selected === item.icon" :disabled="unavailable" :title="item.name" @click="emit('select', item)"><BookmarkIcon :name="item.icon" /><span>{{ item.name }}</span></button>
        <button type="button" class="icon-button uploaded-icon-delete" :aria-label="`${item.name} 업로드 아이콘 삭제`" :title="item.used_by || item.in_trash ? '북마크·공개 링크·휴지통에서 사용 중' : '아이콘 삭제'" :disabled="unavailable || !!item.used_by || item.in_trash" @click="pendingDelete = item"><Trash2 :size="12" aria-hidden="true" /></button>
      </div>
    </div>
    <div v-if="pendingDelete" class="uploaded-icon-confirm"><p>‘{{ pendingDelete.name }}’ 아이콘을 삭제할까요?</p><div class="inline-actions"><button type="button" class="secondary-button" :disabled="busy" @click="pendingDelete = null">취소</button><button type="button" class="secondary-button danger" :disabled="unavailable" @click="remove">아이콘 삭제 확인</button></div></div>
    <p v-if="!loading && !filtered.length && !error" class="settings-description">{{ query ? '이름에 맞는 업로드 아이콘이 없어요.' : '이미지를 업로드하면 이곳에서 다시 선택할 수 있어요.' }}</p>
    <p class="settings-description">PNG·JPG·WebP·SVG·ICO·GIF · 최대 5MB<br />128px PNG로 최적화하고 원래 색상을 사용합니다. GIF는 첫 프레임을 사용합니다.</p>
  </div>
</template>

<style scoped>
.uploaded-icon-picker { display: grid; gap: 12px; min-width: 0; }
.uploaded-icon-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(94px, 1fr)); gap: 8px; max-height: 310px; overflow: auto; padding: 2px; }
.uploaded-icon-tile { position: relative; min-width: 0; }
.uploaded-icon-choice { display: grid; width: 100%; min-height: 100px; justify-items: center; align-content: center; gap: 10px; padding: 20px 8px 10px; border: 1px solid var(--border); border-radius: 8px; color: var(--text); background: var(--surface-raised); cursor: pointer; }
.uploaded-icon-choice[aria-pressed="true"], .uploaded-icon-choice:hover { border-color: var(--accent); }
.uploaded-icon-choice .dock-bookmark-icon { width: 36px; height: 36px; }
.uploaded-icon-choice > span:last-child { width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; }
.uploaded-icon-delete { position: absolute; top: 4px; right: 4px; min-width: 24px; height: 24px; padding: 0; background: var(--surface); }
.uploaded-icon-delete:disabled { opacity: .35; cursor: default; }
.uploaded-icon-confirm { padding: 12px; border: 1px solid var(--border); border-radius: 8px; }
.uploaded-icon-confirm p { margin: 0 0 10px; overflow-wrap: anywhere; font-size: 12px; }
</style>
