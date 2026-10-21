<script setup>
import { computed } from 'vue';
const props=defineProps({status:Object});
const labels={up:'온라인',down:'응답 없음',pending:'미확인'};
const state=computed(()=>props.status?.state==='auth'?'up':props.status?.state||'pending');
const label=computed(()=>labels[state.value]||labels.pending);
const title=computed(()=>`${label.value}${props.status?.detail?' · '+props.status.detail:''}${props.status?.checked_at?' · '+new Date(props.status.checked_at*1000).toLocaleString('ko-KR'):''}`);
</script>
<template><i class="service-status-dot" :class="`service-status-${state}`" role="img" :aria-label="label" :title="title"></i></template>
<style>
.service-status-dot{display:inline-block;flex:0 0 6px;width:6px;height:6px;border-radius:50%;background:var(--muted);font-style:normal;}
.service-status-up{background:var(--green);box-shadow:0 0 6px color-mix(in srgb,var(--green) 30%,transparent);}
.service-status-down{background:var(--red);}
</style>
