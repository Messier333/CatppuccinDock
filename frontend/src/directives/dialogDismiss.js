const dialogs = new WeakMap();

// Use the same cancel path as Escape, including the component's busy guards
// and cleanup. Only a press AND release on the backdrop dismisses a dialog.
export const dialogDismiss = {
  mounted(element, binding) {
    const state = { blocked: !!binding.value, pointer: null };
    const onBackdrop = event => {
      if (event.target !== element) return false;
      const bounds = element.getBoundingClientRect();
      return event.clientX < bounds.left || event.clientX > bounds.right ||
        event.clientY < bounds.top || event.clientY > bounds.bottom;
    };
    const reset = () => { state.pointer = null; };
    const press = event => {
      state.pointer = element.open && event.isPrimary && event.button === 0 && onBackdrop(event)
        ? event.pointerId : null;
    };
    const click = event => {
      const dismiss = state.pointer !== null &&
        (event.pointerId === undefined || event.pointerId === state.pointer) &&
        event.button === 0 && onBackdrop(event);
      reset();
      if (!dismiss || !element.open || state.blocked) return;
      if (typeof element.requestClose === 'function') element.requestClose();
      else if (element.dispatchEvent(new Event('cancel', { cancelable: true }))) element.close();
    };
    const cancel = event => { if (state.blocked) event.preventDefault(); };
    const listeners = { pointerdown: press, pointercancel: reset, click, close: reset, cancel };
    for (const [type, listener] of Object.entries(listeners)) element.addEventListener(type, listener);
    dialogs.set(element, { state, listeners });
  },
  updated(element, binding) { dialogs.get(element).state.blocked = !!binding.value; },
  beforeUnmount(element) {
    const context = dialogs.get(element);
    for (const [type, listener] of Object.entries(context.listeners)) element.removeEventListener(type, listener);
    dialogs.delete(element);
  },
};
