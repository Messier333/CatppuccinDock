// Hover, focus and pinned panels share the same active slot.
let activeClose = null;

export function activateWidgetPanel(close) {
  if (activeClose !== close) activeClose?.();
  activeClose = close;
}

export function releaseWidgetPanel(close) {
  if (activeClose === close) activeClose = null;
}
