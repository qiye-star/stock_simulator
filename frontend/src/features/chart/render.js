/**
 * K 线与成交量的 Canvas 绘制（只读取 viewport.js 的几何结果）。
 *
 * HiDPI：每次绘制先 setTransform(dpr,0,0,dpr,0,0)，之后全部坐标使用 CSS 像素。
 * 修复 legacy 的问题：legacy 用 canvas.width/height（设备像素）参与布局计算，
 * 在 dpr≠1 时网格、价格线与时间标签会错位。
 */
import { formatVolume } from '../../ui/format.js';
import { indexAtX, inPlot, makeLayout, priceRange, xOfIndex, yOfPrice } from './viewport.js';

export const KLINE_PAD = Object.freeze({ left: 56, top: 12, right: 12, bottom: 22 });
export const VOLUME_PAD = Object.freeze({ left: 56, top: 8, right: 12, bottom: 18 });

const UP = '#ff4d4f';
const DOWN = '#52c41a';
const GRID = 'rgba(128, 128, 128, 0.2)';
const AXIS = '#888888';
const LAST = '#58a6ff';
const SEL_FILL = 'rgba(88, 166, 255, 0.2)';
const SEL_STROKE = 'rgba(88, 166, 255, 0.8)';
const CROSS = 'rgba(200, 200, 200, 0.5)';

/**
 * @typedef {{ x0: number, x1: number, y0: number, y1: number }} Selection
 * @typedef {{ x: number, y: number }} Hover
 * @typedef {Object} Frame
 * @property {{ date: string, open: number, high: number, low: number, close: number, volume: number }[]} candles
 * @property {import('./viewport.js').View} view
 * @property {number | null} lastPrice 分
 * @property {Hover | null} hover
 * @property {Selection | null} selection
 * @property {'zh-CN' | 'en-US'} lang
 */

/**
 * 读取 canvas 父容器的 CSS 尺寸（整数像素）。
 * @param {HTMLCanvasElement} canvas
 * @returns {{ w: number, h: number } | null}
 */
export function cssSize(canvas) {
  const parent = canvas.parentElement;
  if (!parent) return null;
  const rect = parent.getBoundingClientRect();
  const w = Math.floor(rect.width);
  const h = Math.floor(rect.height);
  return w > 0 && h > 0 ? { w, h } : null;
}

/**
 * 按 DPR 调整 canvas 像素尺寸与 CSS 尺寸，并清空。
 * @param {HTMLCanvasElement} canvas
 * @returns {{ ctx: CanvasRenderingContext2D, w: number, h: number } | null}
 */
export function prepareCanvas(canvas) {
  const size = cssSize(canvas);
  if (!size) return null;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  const dpr = globalThis.devicePixelRatio || 1;
  const pw = Math.round(size.w * dpr);
  const ph = Math.round(size.h * dpr);
  if (canvas.width !== pw) canvas.width = pw;
  if (canvas.height !== ph) canvas.height = ph;
  canvas.style.width = `${size.w}px`;
  canvas.style.height = `${size.h}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, size.w, size.h);
  return { ctx, w: size.w, h: size.h };
}

/** @param {number} cents @returns {string} */
const priceLabel = (cents) => (cents / 100).toFixed(2);

/**
 * 时间轴标签（MM-DD），每约 1/5 个可见区间一个。
 * @param {CanvasRenderingContext2D} ctx
 * @param {Frame} f
 * @param {import('./viewport.js').Layout} layout
 * @param {number} baseline
 */
function drawTimeAxis(ctx, f, layout, baseline) {
  const { view, candles } = f;
  ctx.fillStyle = AXIS;
  ctx.font = '10px Arial';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'alphabetic';
  const step = Math.max(1, Math.floor(view.visible / 5));
  for (let i = view.start; i < view.end; i += step) {
    const x = xOfIndex(i, view, layout);
    if (x < layout.x || x > layout.x + layout.width) continue;
    const date = candles[i]?.date ?? '';
    ctx.fillText(date ? date.slice(5) : String(i + 1), x, baseline);
  }
}

/**
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} w
 * @param {number} h
 * @param {Frame} f
 */
export function drawKLine(ctx, w, h, f) {
  const layout = makeLayout(w, h, KLINE_PAD, f.view.visible);
  const { view, candles } = f;
  const visible = candles.slice(view.start, view.end);
  const range = priceRange(visible, f.lastPrice);
  if (!range) return;
  const toY = (p) => yOfPrice(p, range, layout);

  // 网格与价格刻度
  ctx.lineWidth = 1;
  ctx.font = '12px Arial';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let i = 0; i <= 5; i++) {
    const y = layout.y + (layout.height / 5) * i;
    ctx.strokeStyle = GRID;
    ctx.beginPath();
    ctx.moveTo(layout.x, y);
    ctx.lineTo(layout.x + layout.width, y);
    ctx.stroke();
    const price = range.max - ((range.max - range.min) / 5) * i;
    ctx.fillStyle = AXIS;
    ctx.fillText(priceLabel(Math.round(price)), layout.x - 6, y);
  }

  // 绘图区裁剪：K 线与现价线只画在绘图区内
  ctx.save();
  ctx.beginPath();
  ctx.rect(layout.x, layout.y, layout.width, layout.height);
  ctx.clip();

  const bodyWidth = Math.max(2, layout.slot * 0.7);
  const last = Math.min(candles.length, Math.ceil(view.offset + view.visible) + 1);
  for (let i = Math.max(0, view.start - 1); i < last; i++) {
    const c = candles[i];
    const x = xOfIndex(i, view, layout);
    const color = c.close >= c.open ? UP : DOWN;
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, toY(c.high));
    ctx.lineTo(x, toY(c.low));
    ctx.stroke();
    const top = Math.min(toY(c.open), toY(c.close));
    const height = Math.max(1, Math.abs(toY(c.close) - toY(c.open)));
    ctx.fillRect(x - bodyWidth / 2, top, bodyWidth, height);
  }

  if (f.lastPrice !== null) {
    const y = toY(f.lastPrice);
    ctx.strokeStyle = LAST;
    ctx.lineWidth = 2;
    ctx.setLineDash([5, 5]);
    ctx.beginPath();
    ctx.moveTo(layout.x, y);
    ctx.lineTo(layout.x + layout.width, y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.lineWidth = 1;
  }
  ctx.restore();

  if (f.selection) {
    const s = f.selection;
    const x = Math.min(s.x0, s.x1);
    const y = Math.min(s.y0, s.y1);
    const sw = Math.abs(s.x1 - s.x0);
    const sh = Math.abs(s.y1 - s.y0);
    ctx.fillStyle = SEL_FILL;
    ctx.strokeStyle = SEL_STROKE;
    ctx.fillRect(x, y, sw, sh);
    ctx.strokeRect(x, y, sw, sh);
  }

  drawTimeAxis(ctx, f, layout, h - 6);

  if (f.hover && inPlot(f.hover.x, layout)) drawCrosshair(ctx, f, layout, range);
}

/**
 * 十字线 + 悬停 K 线的 OHLC 提示。
 * @param {CanvasRenderingContext2D} ctx
 * @param {Frame} f
 * @param {import('./viewport.js').Layout} layout
 * @param {import('./viewport.js').PriceRange} range
 */
function drawCrosshair(ctx, f, layout, range) {
  const hover = /** @type {Hover} */ (f.hover);
  const idx = indexAtX(hover.x, f.view, layout);
  const c = f.candles[idx];
  const cx = xOfIndex(idx, f.view, layout);
  ctx.strokeStyle = CROSS;
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(cx, layout.y);
  ctx.lineTo(cx, layout.y + layout.height);
  if (hover.y >= layout.y && hover.y <= layout.y + layout.height) {
    ctx.moveTo(layout.x, hover.y);
    ctx.lineTo(layout.x + layout.width, hover.y);
  }
  ctx.stroke();
  ctx.setLineDash([]);
  if (c) {
    ctx.fillStyle = AXIS;
    ctx.font = '11px Arial';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    const text = `${c.date || idx + 1}  O ${priceLabel(c.open)}  H ${priceLabel(c.high)}  L ${priceLabel(c.low)}  C ${priceLabel(c.close)}`;
    ctx.fillText(text, layout.x + 4, layout.y + 2);
  }
}

/**
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} w
 * @param {number} h
 * @param {Frame} f
 */
export function drawVolume(ctx, w, h, f) {
  const layout = makeLayout(w, h, VOLUME_PAD, f.view.visible);
  const { view, candles } = f;
  const visible = candles.slice(view.start, view.end);
  if (!visible.length) return;
  const maxVolume = Math.max(1, ...visible.map((c) => c.volume));

  ctx.lineWidth = 1;
  ctx.font = '11px Arial';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let i = 0; i <= 3; i++) {
    const y = layout.y + (layout.height / 3) * i;
    ctx.strokeStyle = GRID;
    ctx.beginPath();
    ctx.moveTo(layout.x, y);
    ctx.lineTo(layout.x + layout.width, y);
    ctx.stroke();
    const vol = Math.round((maxVolume / 3) * (3 - i));
    ctx.fillStyle = AXIS;
    ctx.fillText(formatVolume(vol, f.lang), layout.x - 6, y);
  }

  ctx.save();
  ctx.beginPath();
  ctx.rect(layout.x, layout.y, layout.width, layout.height);
  ctx.clip();
  const barWidth = Math.max(2, layout.slot * 0.7);
  for (let i = view.start; i < view.end; i++) {
    const c = candles[i];
    const x = xOfIndex(i, view, layout);
    const barH = (c.volume / maxVolume) * layout.height;
    ctx.fillStyle = c.close >= c.open ? UP : DOWN;
    ctx.fillRect(x - barWidth / 2, layout.y + layout.height - barH, barWidth, barH);
  }
  ctx.restore();

  drawTimeAxis(ctx, f, layout, h - 4);
}
