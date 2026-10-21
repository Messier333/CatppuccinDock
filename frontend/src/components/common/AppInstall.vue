<script setup>
import { Download } from 'lucide-vue-next';
import { usePwaInstall } from '../../lib/pwa.js';
defineProps({details:Boolean});
const {available,installed,busy,install,secure,proxy} = usePwaInstall();
</script>
<template><div v-if="details || available" class="app-install" data-settings-anchor="install"><button v-if="available" :class="details ? 'primary-button' : 'search-launch'" :disabled="busy" aria-label="CatppuccinDock 앱 설치" title="앱으로 설치" @click="install"><Download :size="18" /><span v-if="details">앱으로 설치</span></button><p v-if="details" class="settings-description">{{ proxy ? 'code-server 프록시에서는 앱 설치를 지원하지 않습니다. 포털의 별도 HTTPS 주소에서 설치해 주세요.' : installed ? 'CatppuccinDock 앱이 설치되어 있습니다.' : !secure ? 'HTTPS 주소로 접속하면 크롬·Edge에서 앱으로 설치할 수 있습니다. localhost 접속도 지원합니다.' : available ? '설치하면 바탕화면·시작 메뉴에서 포털을 독립된 앱 창으로 열 수 있습니다.' : '크롬 메뉴의 ‘전송, 저장 및 공유 → 페이지를 앱으로 설치’에서 설치할 수 있습니다. 설치 가능한 브라우저에서는 설치 버튼도 표시됩니다.' }}</p></div></template>
