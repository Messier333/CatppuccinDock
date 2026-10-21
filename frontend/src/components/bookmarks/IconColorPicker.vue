<script setup>
import { computed } from "vue";
const model = defineModel({ type: String, default: 'auto' });
const custom = computed({
  get: () => /^#[a-f\d]{6}$/i.test(model.value || ''),
  set: value => { model.value = value ? '#89b4fa' : 'auto'; },
});
</script>
<template><div class="icon-color-picker">
  <label class="checkbox-label"><input v-model="custom" type="checkbox" />아이콘 색상 직접 지정</label>
  <label v-if="custom">아이콘 색상<input v-model="model" type="color" /></label>
  <p v-else class="settings-description">카테고리 안의 순서에 따라 초록 → 분홍 → 빨강 → 파랑 → 보라로 반복됩니다. 라이트·다크 테마에 맞춰 자동으로 바뀝니다.</p>
</div></template>
