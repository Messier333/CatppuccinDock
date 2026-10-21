import { api } from './api.js';
export function recordBookmarkVisit(id, event) {
  if (event && event.type === 'auxclick' && event.button !== 1) return;
  window.dispatchEvent(new CustomEvent('dock:bookmark-visited',{detail:{id}}));
  api(`bookmark-tools/${encodeURIComponent(id)}/visit`,{method:'POST',keepalive:true}).catch(() => {});
}
