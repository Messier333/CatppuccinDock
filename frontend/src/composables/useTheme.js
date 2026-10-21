import { onMounted, onUnmounted, readonly, ref, watch } from "vue";

const storageKey = "catppuccindock:theme";

function readTheme() {
  try {
    const stored = localStorage.getItem(storageKey);
    if (stored === "latte" || stored === "mocha") return stored;
  } catch {
    // Keep theme switching available when browser storage is blocked.
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "mocha" : "latte";
}

const theme = ref(readTheme());

watch(theme, (value) => {
  document.documentElement.dataset.theme = value;
}, { immediate: true, flush: "sync" });

function setTheme(value) {
  if (value !== "latte" && value !== "mocha") return;
  theme.value = value;
  try {
    localStorage.setItem(storageKey, theme.value);
  } catch {
    // The current page can still use the selected theme without persistence.
  }
}

function toggleTheme() {
  setTheme(theme.value === "mocha" ? "latte" : "mocha");
}

export function useTheme() {
  function refreshTheme() {
    theme.value = readTheme();
  }

  function handleStorage(event) {
    if (event.storageArea === window.localStorage && (event.key === storageKey || event.key === null)) {
      refreshTheme();
    }
  }

  onMounted(() => {
    window.addEventListener("storage", handleStorage);
    window.addEventListener("pageshow", refreshTheme);
  });

  onUnmounted(() => {
    window.removeEventListener("storage", handleStorage);
    window.removeEventListener("pageshow", refreshTheme);
  });

  return { theme: readonly(theme), setTheme, toggleTheme };
}
