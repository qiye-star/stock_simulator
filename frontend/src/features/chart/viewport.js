/**
 * K 线 / 成交量图的视口数学（纯函数，零 DOM，可单测）。
 *
 * 状态 ViewState = { scale, offset }：
 *   - scale  缩放倍数 [1, 10]；可见根数 = max(10, floor(total / scale))，且不超过 total
 *   - offset 视口左端的（可为小数的）K 线下标；null 表示“贴最新”（默认）
 *
 * 坐标约定（CSS 像素，非设备像素）：第 i 根 K 线中心 x = left + (i - offset + 0.5) * slot，
 * slot = width / visible。移植自 legacy/game.js 2584-3113 的缩放/拖拽/框选逻辑，
 * 但数学集中在此处，便于与 legacy 对拍。
 */

export const MIN_SCALE = 1;
export const MAX_SCALE = 10;
export const MIN_VISIBLE = 10;
/** 框选至少需要的像素宽度（legacy: < 20px 忽略）。 */
export const MIN_SELECTION_PX = 20;
/** 框选后至少保留的根数（legacy: newVisibleCount >= 5）。 */
export const MIN_BOX_CANDLES = 5;

/**
 * @typedef {{ scale: number, offset: number | null }} ViewState
 * @typedef {{ total: number, visible: number, maxOffset: number, offset: number, start: number, end: number }} View
 * @typedef {{ min: number, max: number }} PriceRange
 * @typedef {{ left: number, top: number, right: number, bottom: number }} Padding
 * @typedef {{ x: number, y: number, width: number, height: number, cssWidth: number, cssHeight: number, slot: number }} Layout
 */

/** @param {number} v @param {number} lo @param {number} hi */
export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** @returns {ViewState} */
export function initialView() {
  return { scale: MIN_SCALE, offset: null };
}

/** @param {number} scale */
export function clampScale(scale) {
  return Number.isFinite(scale) ? clamp(scale, MIN_SCALE, MAX_SCALE) : MIN_SCALE;
}

/**
 * @param {number} total K 线根数
 * @param {number} scale
 * @returns {number} 可见根数
 */
export function visibleCountFor(total, scale) {
  if (total <= 0) return 0;
  return Math.min(total, Math.max(MIN_VISIBLE, Math.floor(total / clampScale(scale))));
}

/**
 * 解析视口：补全 null 偏移、夹取到合法范围，并给出可见下标区间。
 * @param {number} total
 * @param {ViewState} state
 * @returns {View}
 */
export function resolveView(total, state) {
  const visible = visibleCountFor(total, state.scale);
  const maxOffset = Math.max(0, total - visible);
  const raw = state.offset === null ? maxOffset : state.offset;
  const offset = clamp(Number.isFinite(raw) ? raw : maxOffset, 0, maxOffset);
  const start = Math.floor(offset);
  const end = Math.min(total, Math.ceil(offset + visible));
  return { total, visible, maxOffset, offset, start, end };
}

/**
 * 以视口内的某个比例位置为焦点缩放（焦点下的 K 线保持不动）。
 * @param {number} total
 * @param {ViewState} state
 * @param {number} factor 本次缩放倍数，>1 放大
 * @param {number} focusRatio 焦点在视口内的比例 [0,1]
 * @returns {ViewState}
 */
export function zoomAt(total, state, factor, focusRatio) {
  if (total <= 0) return state;
  const view = resolveView(total, state);
  const scale = clampScale(state.scale * factor);
  if (scale === state.scale) return state;
  const f = clamp(focusRatio, 0, 1);
  const focusIndex = view.offset + f * view.visible;
  const visible = visibleCountFor(total, scale);
  const offset = clamp(focusIndex - f * visible, 0, Math.max(0, total - visible));
  return { scale, offset };
}

/**
 * 从拖拽起点的视口平移（deltaCandles > 0 向右看更新的数据）。
 * @param {number} total
 * @param {ViewState} base 拖拽开始时的状态
 * @param {number} deltaCandles
 * @returns {ViewState}
 */
export function panFrom(total, base, deltaCandles) {
  const view = resolveView(total, base);
  return { scale: base.scale, offset: clamp(view.offset + deltaCandles, 0, view.maxOffset) };
}

/**
 * 框选放大：左右比例（相对绘图区宽度）映射为新的视口。
 * 选区不足 MIN_BOX_CANDLES 根时保持原状态。
 * @param {number} total
 * @param {ViewState} state
 * @param {number} leftRatio
 * @param {number} rightRatio
 * @returns {ViewState}
 */
export function zoomToRange(total, state, leftRatio, rightRatio) {
  if (total <= 0) return state;
  const l = clamp(Math.min(leftRatio, rightRatio), 0, 1);
  const r = clamp(Math.max(leftRatio, rightRatio), 0, 1);
  const view = resolveView(total, state);
  const from = view.offset + l * view.visible;
  const to = view.offset + r * view.visible;
  const count = to - from;
  if (count < MIN_BOX_CANDLES) return state;
  const scale = clampScale(state.scale * (view.visible / count));
  const visible = visibleCountFor(total, scale);
  return { scale, offset: clamp(from, 0, Math.max(0, total - visible)) };
}

/**
 * 当前视口内 K 线的价格区间（含上下 10% 留白；平盘时给出最小跨度）。
 * @param {{ high: number, low: number }[]} candles 可见 K 线
 * @param {number | null} lastPrice 现价（分），纳入区间
 * @returns {PriceRange | null}
 */
export function priceRange(candles, lastPrice) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const c of candles) {
    if (c.low < lo) lo = c.low;
    if (c.high > hi) hi = c.high;
  }
  if (lastPrice !== null && Number.isFinite(lastPrice)) {
    lo = Math.min(lo, lastPrice);
    hi = Math.max(hi, lastPrice);
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
  if (hi - lo < 1) {
    const pad = Math.max(1, Math.round(((hi + lo) / 2) * 0.01));
    return { min: lo - pad, max: hi + pad };
  }
  const pad = (hi - lo) * 0.1;
  return { min: lo - pad, max: hi + pad };
}

/**
 * 绘图区布局（CSS 像素）。
 * @param {number} cssWidth
 * @param {number} cssHeight
 * @param {Padding} pad
 * @param {number} visible
 * @returns {Layout}
 */
export function makeLayout(cssWidth, cssHeight, pad, visible) {
  const width = Math.max(0, cssWidth - pad.left - pad.right);
  const height = Math.max(0, cssHeight - pad.top - pad.bottom);
  return {
    x: pad.left,
    y: pad.top,
    width,
    height,
    cssWidth,
    cssHeight,
    slot: visible > 0 ? width / visible : 0,
  };
}

/**
 * @param {number} index K 线下标（可小数）
 * @param {View} view
 * @param {Layout} layout
 */
export function xOfIndex(index, view, layout) {
  return layout.x + (index - view.offset + 0.5) * layout.slot;
}

/**
 * 像素 x -> 最近的 K 线下标（夹取到 [0, total-1]）。
 * @param {number} px
 * @param {View} view
 * @param {Layout} layout
 */
export function indexAtX(px, view, layout) {
  if (layout.slot <= 0) return 0;
  const raw = Math.round(view.offset + (px - layout.x) / layout.slot - 0.5);
  return clamp(raw, 0, Math.max(0, view.total - 1));
}

/**
 * @param {number} price 分
 * @param {PriceRange} range
 * @param {Layout} layout
 */
export function yOfPrice(price, range, layout) {
  return layout.y + ((range.max - price) / (range.max - range.min)) * layout.height;
}

/**
 * 像素 x 是否落在绘图区内（用于十字线与框选的有效范围）。
 * @param {number} px
 * @param {Layout} layout
 */
export function inPlot(px, layout) {
  return px >= layout.x && px <= layout.x + layout.width;
}
