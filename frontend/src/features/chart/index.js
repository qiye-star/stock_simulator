/**
 * K 线与成交量图功能入口（移植自 legacy/game.js 2584-3113）。
 *
 * 数据来自 market/store 的 detail.history（日 K，最多 60 根）与 detail.price_cents（现价线）。
 * 切换股票时重置视口；每次 detail 变化（含 tick 带来的现价变化）合并到下一帧重绘。
 * 拥有：#kline-canvas #volume-canvas #chart-zoom-in #chart-zoom-out #chart-reset
 */
import { marketStore } from '../market/store.js';
import { cssSize, drawKLine, drawVolume, KLINE_PAD, prepareCanvas } from './render.js';
import { attachInteraction } from './interact.js';
import { initialView, makeLayout, resolveView, zoomAt } from './viewport.js';
import { on } from '../../ui/dom.js';

const ZOOM_STEP = 1.2;

/**
 * @param {import('../index.js').FeatureContext} ctx
 * @returns {() => void}
 */
export function mount(ctx) {
  const doc = document;
  const klineCanvas = /** @type {HTMLCanvasElement | null} */ (doc.getElementById('kline-canvas'));
  const volumeCanvas = /** @type {HTMLCanvasElement | null} */ (doc.getElementById('volume-canvas'));
  if (!klineCanvas || !volumeCanvas) return () => {};

  const st = {
    /** @type {import('./viewport.js').ViewState} */
    view: initialView(),
    /** @type {{ x: number, y: number } | null} */
    hover: null,
    /** @type {{ x0: number, x1: number, y0: number, y1: number } | null} */
    selection: null,
    queued: false,
  };

  function draw() {
    st.queued = false;
    const { detail } = marketStore.get();
    const candles = detail?.history ?? [];
    const kPrep = prepareCanvas(klineCanvas);
    const vPrep = prepareCanvas(volumeCanvas);
    if (!candles.length) return;
    const view = resolveView(candles.length, st.view);
    const lastPrice = detail ? detail.price_cents : null;
    const lang = ctx.i18n.getLanguage();
    if (kPrep) {
      drawKLine(kPrep.ctx, kPrep.w, kPrep.h, { candles, view, lastPrice, hover: st.hover, selection: st.selection, lang });
    }
    if (vPrep) {
      drawVolume(vPrep.ctx, vPrep.w, vPrep.h, { candles, view, lastPrice, hover: null, selection: null, lang });
    }
  }

  /** 合并同一帧内的多次变更为一次绘制。 */
  function schedule() {
    if (st.queued) return;
    st.queued = true;
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(draw);
    else setTimeout(draw, 16);
  }

  /** @type {import('./interact.js').ChartHost} */
  const host = {
    geometry() {
      const total = marketStore.get().detail?.history.length ?? 0;
      if (!total) return null;
      const size = cssSize(klineCanvas);
      if (!size) return null;
      const view = resolveView(total, st.view);
      const layout = makeLayout(size.w, size.h, KLINE_PAD, view.visible);
      return { total, state: st.view, view, layout };
    },
    setView(next) {
      st.view = next;
      schedule();
    },
    setHover(h) {
      st.hover = h;
      schedule();
    },
    setSelection(s) {
      st.selection = s;
      schedule();
    },
    getSelection: () => st.selection,
  };

  const detachInteraction = attachInteraction(klineCanvas, host);

  const unsubscribe = marketStore.subscribe((s, prev) => {
    if (s.selectedCode !== prev.selectedCode) {
      st.view = initialView();
      st.hover = null;
      st.selection = null;
      schedule();
    } else if (s.detail !== prev.detail) {
      schedule();
    }
  });

  /** @param {number} factor */
  const zoomBy = (factor) => {
    const g = host.geometry();
    if (g) host.setView(zoomAt(g.total, g.state, factor, 0.5));
  };
  const zoomInBtn = doc.getElementById('chart-zoom-in');
  const zoomOutBtn = doc.getElementById('chart-zoom-out');
  const resetBtn = doc.getElementById('chart-reset');
  const offIn = zoomInBtn ? on(zoomInBtn, 'click', () => zoomBy(ZOOM_STEP)) : () => {};
  const offOut = zoomOutBtn ? on(zoomOutBtn, 'click', () => zoomBy(1 / ZOOM_STEP)) : () => {};
  const offReset = resetBtn ? on(resetBtn, 'click', () => host.setView(initialView())) : () => {};

  const onResize = () => schedule();
  globalThis.addEventListener?.('resize', onResize);
  /** @type {ResizeObserver | null} */
  let observer = null;
  if (typeof ResizeObserver === 'function') {
    observer = new ResizeObserver(onResize);
    if (klineCanvas.parentElement) observer.observe(klineCanvas.parentElement);
    if (volumeCanvas.parentElement) observer.observe(volumeCanvas.parentElement);
  }
  const offLang = ctx.i18n.onChange(() => schedule());

  schedule();

  return () => {
    unsubscribe();
    detachInteraction();
    offIn();
    offOut();
    offReset();
    offLang();
    globalThis.removeEventListener?.('resize', onResize);
    observer?.disconnect();
  };
}

