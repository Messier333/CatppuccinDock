import Sortable from "sortablejs";

export function reorderDirective(onReorder) {
  return {
    mounted(element, binding) {
      element._dockOrder = binding.value;
      element._dockSortable = Sortable.create(element, {
        animation: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 160,
        handle: '.reorder-handle', draggable: '[data-sort-id]',
        forceFallback: true, fallbackOnBody: true, fallbackTolerance: 5,
        delayOnTouchOnly: true, delay: 130, touchStartThreshold: 4,
        ghostClass: 'reorder-ghost', chosenClass: 'reorder-chosen', fallbackClass: 'reorder-floating',
        disabled: !!binding.value.disabled,
        onStart(event) {
          const preview = Sortable.ghost;
          if (!preview) return;
          // The preview lives under body, outside the source's theme/layout scope.
          const styles = getComputedStyle(event.item);
          for (const name of styles) {
            if (name.startsWith('--')) preview.style.setProperty(name, styles.getPropertyValue(name));
          }
          preview.inert = true;
          preview.setAttribute('aria-hidden', 'true');
        },
        onEnd(event) {
          if (event.oldDraggableIndex === event.newDraggableIndex) return;
          const context = element._dockOrder;
          const ids = [...element.children].filter(child => child.dataset.sortId).map(child => child.dataset.sortId);
          // Restore the DOM so Vue can apply the new keyed order itself.
          const sibling = element.children[event.oldIndex + (event.oldIndex > event.newIndex ? 1 : 0)];
          element.insertBefore(event.item, sibling || null);
          onReorder(context.kind, context.parentId, ids);
        },
      });
    },
    updated(element, binding) { element._dockOrder = binding.value; element._dockSortable.option('disabled', !!binding.value.disabled); },
    beforeUnmount(element) { element._dockSortable?.destroy(); },
  };
}
