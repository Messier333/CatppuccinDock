<script setup>
import { computed, ref, watch } from "vue";
import { Globe2 } from "lucide-vue-next";
import { icons } from "../../lib/icons.js";
import { appUrl } from "../../lib/navigation.js";
const props = defineProps({ name: { type: String, default: 'world' } });
const uploaded = computed(() => /^upload:[0-9a-f-]{36}$/.test(props.name));
const broken = ref(false);
watch(() => props.name, () => broken.value = false);
const remote = computed(() => /^[a-z0-9-]+:[a-z0-9-]+$/.test(props.name));
const maskStyle = computed(() => {
  const url = appUrl(`api/icons/${encodeURIComponent(props.name)}.svg`);
  return { maskImage: `url("${url}")`, WebkitMaskImage: `url("${url}")` };
});
</script>
<template><span class="dock-bookmark-icon" aria-hidden="true"><img v-if="uploaded && !broken" :src="appUrl(`api/uploaded-icons/${encodeURIComponent(name.slice(7))}/content`)" alt="" loading="lazy" decoding="async" @error="broken = true" /><Globe2 v-else-if="uploaded" :size="20" /><span v-else-if="remote" class="dock-icon-mask" :style="maskStyle"></span><span v-else-if="icons[name]" v-html="icons[name]"></span><Globe2 v-else :size="20" /></span></template>
<style>
.dock-bookmark-icon { display: inline-flex; width: 20px; height: 20px; flex: 0 0 auto; align-items: center; justify-content: center; }
.dock-bookmark-icon svg { display: block; width: 100%; height: 100%; }
.dock-bookmark-icon > span { display: block; width: 100%; height: 100%; }
.dock-bookmark-icon > img { display: block; width: 100%; height: 100%; object-fit: contain; }
.dock-icon-mask { background-color: currentColor; mask-size: contain; mask-position: center; mask-repeat: no-repeat; -webkit-mask-size: contain; -webkit-mask-position: center; -webkit-mask-repeat: no-repeat; }
</style>
