import { appUrl } from "./navigation.js";

export async function api(path, options = {}) {
  const response = await fetch(appUrl(`api/${path}`), {
    credentials: "same-origin",
    cache: "no-store",
    ...options,
    headers: { "Content-Type": "application/json", "X-CatppuccinDock": "1", ...options.headers },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("auth/")) {
      window.dispatchEvent(new Event("dock:session-expired"));
    }
    const error = new Error(typeof data.detail === "string" ? data.detail : "요청을 처리하지 못했어요. 입력 내용을 확인해 주세요.");
    error.status = response.status;
    throw error;
  }
  return data;
}

export async function logout() {
  await api("auth/logout", { method: "POST" });
  window.location.replace(appUrl("login/"));
}
