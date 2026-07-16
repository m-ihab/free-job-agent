/* Shared pointer, touch, wheel, and reset wiring for local graph surfaces. */
(function () {
  "use strict";

  const DRAG_THRESHOLD = 5;
  const point = (event) => ({ x: event.clientX, y: event.clientY });
  const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  const center = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });

  function bindSurface(surface, handlers = {}) {
    const pointers = new Map();
    let drag = null, pinch = null, suppressClick = false, lastTap = null;

    surface.addEventListener("pointerdown", (event) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      const current = point(event);
      pointers.set(event.pointerId, current);
      surface.setPointerCapture?.(event.pointerId);
      if (pointers.size === 1) {
        drag = { origin: current, last: current, moved: false, pointerType: event.pointerType };
        handlers.onDragStart?.(current, event);
      } else if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinch = { distance: Math.max(1, distance(a, b)) };
        if (drag) drag.moved = true;
      }
    });

    surface.addEventListener("pointermove", (event) => {
      if (!pointers.has(event.pointerId)) return;
      const current = point(event);
      pointers.set(event.pointerId, current);
      if (pointers.size >= 2) {
        const [a, b] = [...pointers.values()];
        const nextDistance = Math.max(1, distance(a, b));
        handlers.onPinch?.(nextDistance / pinch.distance, center(a, b), event);
        pinch.distance = nextDistance;
        suppressClick = true;
        event.preventDefault();
        return;
      }
      if (!drag) return;
      const total = distance(current, drag.origin);
      drag.moved = drag.moved || total > DRAG_THRESHOLD;
      const dx = current.x - drag.last.x, dy = current.y - drag.last.y;
      drag.last = current;
      if (drag.moved) {
        handlers.onDrag?.(dx, dy, current, event);
        event.preventDefault();
      }
    });

    function endPointer(event) {
      if (!pointers.has(event.pointerId)) return;
      const current = point(event);
      const wasPinch = Boolean(pinch);
      const moved = Boolean(drag?.moved || wasPinch);
      pointers.delete(event.pointerId);
      if (surface.hasPointerCapture?.(event.pointerId)) surface.releasePointerCapture(event.pointerId);
      if (pointers.size) {
        const remaining = [...pointers.values()][0];
        drag = { origin: remaining, last: remaining, moved: true, pointerType: event.pointerType };
        pinch = null;
        return;
      }
      handlers.onDragEnd?.({ moved, point: current, event });
      if (moved) suppressClick = true;
      if (!moved) {
        const now = window.performance.now();
        const doubleTap = event.pointerType !== "mouse" && lastTap
          && now - lastTap.time < 320 && distance(current, lastTap.point) < 24;
        if (doubleTap) {
          suppressClick = true;
          lastTap = null;
          handlers.onDoubleActivate?.(current, event);
        } else {
          lastTap = { time: now, point: current };
          handlers.onTap?.(current, event);
        }
      }
      drag = null;
      pinch = null;
    }

    surface.addEventListener("pointerup", endPointer);
    surface.addEventListener("pointercancel", endPointer);
    surface.addEventListener("wheel", (event) => {
      handlers.onWheel?.(event.deltaY, point(event), event);
      event.preventDefault();
    }, { passive: false });
    surface.addEventListener("dblclick", (event) => {
      event.preventDefault();
      handlers.onDoubleActivate?.(point(event), event);
    });
    surface.addEventListener("keydown", (event) => handlers.onKey?.(event));
    surface.addEventListener("click", (event) => {
      if (!suppressClick) return;
      suppressClick = false;
      event.preventDefault();
      event.stopPropagation();
    }, true);
  }

  window.JobAgentGraphGestures = { bindSurface, DRAG_THRESHOLD };
})();
