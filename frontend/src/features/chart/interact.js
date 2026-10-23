/**
 * K 线交互：滚轮缩放、鼠标/触摸拖拽平移、双指缩放、右键或 Shift 框选放大、悬停十字线。
 * 使用 Pointer Events 同时覆盖鼠标与触摸（canvas 设 touch-action:none）。
 *
 * 本模块不持有视口状态：通过 host 读取几何信息并提交新状态，
 * 视口数学见 ./viewport.js。
 */
import { clamp, MIN_SELECTION_PX, inPlot, panFrom, zoomAt, zoomToRange } from './viewport.js';

/**
 * @typedef {import('./viewport.js').ViewState} ViewState
 * @typedef {{ total: number, state: ViewState, view: import('./viewport.js').View, layout: import('./viewport.js').Layout }} Geometry
 * @typedef {{
 *   geometry: () => Geometry | null,
 *   setView: (s: ViewState) => void,
 *   setHover: (h: { x: number, y: number } | null) => void,
 *   setSelection: (s: { x0: number, x1: number, y0: number, y1: number } | null) => void,
 *   getSelection: () => { x0: number, x1: number, y0: number, y1: number } | null,
 * }} ChartHost
 */

const WHEEL_IN = 1.1;
const WHEEL_OUT = 0.9;

/**
 * @param {HTMLCanvasElement} canvas
 * @param {ChartHost} host
 * @returns {() => void} 解绑
 */
export function attachInteraction(canvas, host) {
  canvas.style.touchAction = 'none';
  /** @type {Map<number, { x: number, y: number }>} */
  const pointers = new Map();
  /** @type {{ mode: 'pan', startX: number, base: ViewState } | { mode: 'select', x0: number, y0: number } | null} */
  let drag = null;
  /** @type {{ dist: number } | null} */
  let pinch = null;

  /** @param {PointerEvent | WheelEvent} e */
  const local = (e) => {
    const r = canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  /** @param {{ x: number, y: number }} a @param {{ x: number, y: number }} b */
  const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

  /** @param {WheelEvent} e */
  const onWheel = (e) => {
    const g = host.geometry();
    if (!g) return;
    e.preventDefault();
    const focus = clamp((local(e).x - g.layout.x) / g.layout.width, 0, 1);
    host.setView(zoomAt(g.total, g.state, e.deltaY > 0 ? WHEEL_OUT : WHEEL_IN, focus));
  };

  /** @param {PointerEvent} e */
  const onDown = (e) => {
    const g = host.geometry();
    if (!g) return;
    const p = local(e);
    canvas.setPointerCapture?.(e.pointerId);
    pointers.set(e.pointerId, p);
    host.setHover(null);
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = { dist: Math.max(1, dist(a, b)) };
      drag = null;
      host.setSelection(null);
      return;
    }
    if (e.button === 2 || e.shiftKey) {
      drag = { mode: 'select', x0: p.x, y0: p.y };
      host.setSelection({ x0: p.x, x1: p.x, y0: p.y, y1: p.y });
    } else {
      drag = { mode: 'pan', startX: p.x, base: g.state };
    }
  };

  /** @param {PointerEvent} e */
  const onMove = (e) => {
    const p = local(e);
    const g = host.geometry();
    canvas.classList.toggle('shift-key', e.shiftKey);
    if (pointers.has(e.pointerId)) pointers.set(e.pointerId, p);
    if (!g) return;

    if (pointers.size >= 2 && pinch) {
      const [a, b] = [...pointers.values()];
      const d = Math.max(1, dist(a, b));
      const focus = clamp(((a.x + b.x) / 2 - g.layout.x) / g.layout.width, 0, 1);
      const factor = d / pinch.dist;
      pinch.dist = d;
      if (factor !== 1) host.setView(zoomAt(g.total, g.state, factor, focus));
      return;
    }
    if (drag?.mode === 'pan' && pointers.size === 1) {
      const dx = p.x - drag.startX;
      host.setView(panFrom(g.total, drag.base, -dx / Math.max(g.layout.slot, 1e-9)));
      return;
    }
    if (drag?.mode === 'select') {
      host.setSelection({ x0: drag.x0, x1: p.x, y0: drag.y0, y1: p.y });
      return;
    }
    if (pointers.size === 0) {
      const inside = inPlot(p.x, g.layout) && p.y >= g.layout.y && p.y <= g.layout.y + g.layout.height;
      host.setHover(inside ? p : null);
    }
  };

  /** @param {PointerEvent} e */
  const onUp = (e) => {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (pointers.size > 0) return;
    if (drag?.mode === 'select') {
      const sel = host.getSelection();
      const g = host.geometry();
      if (g && sel && Math.abs(sel.x1 - sel.x0) >= MIN_SELECTION_PX) {
        const left = (Math.min(sel.x0, sel.x1) - g.layout.x) / g.layout.width;
        const right = (Math.max(sel.x0, sel.x1) - g.layout.x) / g.layout.width;
        host.setView(zoomToRange(g.total, g.state, left, right));
      }
      host.setSelection(null);
    }
    drag = null;
  };

  const onLeave = () => {
    if (pointers.size === 0) host.setHover(null);
  };
  const onContext = (/** @type {Event} */ e) => e.preventDefault();

  canvas.addEventListener('wheel', onWheel, { passive: false });
  canvas.addEventListener('pointerdown', onDown);
  canvas.addEventListener('pointermove', onMove);
  canvas.addEventListener('pointerup', onUp);
  canvas.addEventListener('pointercancel', onUp);
  canvas.addEventListener('pointerleave', onLeave);
  canvas.addEventListener('contextmenu', onContext);

  return () => {
    canvas.removeEventListener('wheel', onWheel);
    canvas.removeEventListener('pointerdown', onDown);
    canvas.removeEventListener('pointermove', onMove);
    canvas.removeEventListener('pointerup', onUp);
    canvas.removeEventListener('pointercancel', onUp);
    canvas.removeEventListener('pointerleave', onLeave);
    canvas.removeEventListener('contextmenu', onContext);
  };
}
