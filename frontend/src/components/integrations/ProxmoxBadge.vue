<script setup>
import { ChevronRight } from 'lucide-vue-next';
import { metricText } from '../../lib/proxmox.js';
defineProps({ integration: {type:Object,required:true} });
defineEmits(['open']);
</script>
<template><button type="button" class="pve-bookmark-badge" :class="{'pve-stale':!!integration.error}" :aria-label="`${integration.config.name} Proxmox 상세 정보 열기`" :title="integration.error || 'Proxmox 상세 정보'" @click.stop.prevent="$emit('open',integration)"><span v-for="metric in integration.config.metrics" :key="metric">{{ metricText(integration.data.summary,metric) }}</span><ChevronRight v-if="!integration.config.metrics.length" :size="13" /></button></template>
