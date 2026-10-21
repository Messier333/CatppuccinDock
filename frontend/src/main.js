import { createApp } from "vue";
import App from "./App.vue";
import "./styles/base.css";
import "./styles/controls.css";
import { initializePwa } from './lib/pwa.js';
import { dialogDismiss } from './directives/dialogDismiss.js';

initializePwa();
createApp(App).directive('dialog-dismiss', dialogDismiss).mount("#app");
