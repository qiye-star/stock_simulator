import { describe, expect, it } from 'vitest';
import {
  MAX_SCALE,
  clampScale,
  indexAtX,
  initialView,
  makeLayout,
  panFrom,
  priceRange,
  resolveView,
  visibleCountFor,
  xOfIndex,
  yOfPrice,
  zoomAt,
  zoomToRange,
} from './viewport.js';

describe('visible count and resolve', () => {
  it('defaults to showing the latest candles', () => {
    const v = resolveView(60, initialView());
    expect(v.visible).toBe(60);
    expect(v.offset).toBe(0);
    expect(v.maxOffset).toBe(0);
  });

  it('scales visible count with clamp to [10, total]', () => {
    expect(visibleCountFor(60, 2)).toBe(30);
    expect(visibleCountFor(60, 10)).toBe(10);
    expect(visibleCountFor(60, 100)).toBe(10); // clamped scale 10
    expect(visibleCountFor(5, 1)).toBe(5); // never more than total
    expect(visibleCountFor(0, 1)).toBe(0);
    expect(clampScale(NaN)).toBe(1);
    expect(clampScale(99)).toBe(MAX_SCALE);
  });

  it('keeps explicit offsets inside bounds and derives [start,end)', () => {
    const v = resolveView(60, { scale: 2, offset: 40 });
    expect(v.maxOffset).toBe(30);
    expect(v.offset).toBe(30);
    expect(v.start).toBe(30);
    expect(v.end).toBe(60);
    expect(resolveView(60, { scale: 2, offset: -5 }).offset).toBe(0);
  });
});

describe('zoom keeps focus candle fixed', () => {
  it('zooming in at the right edge pins to the newest candles', () => {
    const next = zoomAt(60, { scale: 1, offset: null }, 2, 1);
    const v = resolveView(60, next);
    expect(v.visible).toBe(30);
    expect(v.end).toBe(60);
  });

  it('zoom at a centre focus keeps the candle under the focus', () => {
    const total = 100;
    const state = { scale: 1, offset: 0 };
    const before = resolveView(total, state);
    const focus = 0.5;
    const focusIndexBefore = before.offset + focus * before.visible;
    const after = resolveView(total, zoomAt(total, state, 2, focus));
    const focusIndexAfter = after.offset + focus * after.visible;
    expect(focusIndexAfter).toBeCloseTo(focusIndexBefore, 6);
  });

  it('returns the same state when already at a scale bound', () => {
    const s = { scale: MAX_SCALE, offset: 0 };
    expect(zoomAt(100, s, 2, 0.5)).toBe(s);
    expect(zoomAt(0, s, 2, 0.5)).toBe(s);
  });
});

describe('pan and box zoom', () => {
  it('drag right moves to older candles and clamps at zero', () => {
    const base = { scale: 2, offset: 10 };
    expect(panFrom(60, base, -3).offset).toBe(7);
    expect(panFrom(60, base, -50).offset).toBe(0);
    expect(panFrom(60, base, 999).offset).toBe(30);
  });

  it('box zoom maps the selection to a narrower viewport', () => {
    const next = zoomToRange(100, { scale: 1, offset: 0 }, 0.5, 1);
    const v = resolveView(100, next);
    expect(v.visible).toBe(50);
    expect(v.offset).toBe(50);
  });

  it('ignores selections smaller than the minimum candle count', () => {
    const s = { scale: 1, offset: 0 };
    expect(zoomToRange(100, s, 0.5, 0.52)).toBe(s);
  });
});

describe('price range and coordinates', () => {
  it('pads the visible range by 10% and includes the last price', () => {
    const r = priceRange([{ high: 1100, low: 1000 }], 1200);
    expect(r).toEqual({ min: 1000 - 20, max: 1200 + 20 });
  });

  it('gives a non-zero span for flat prices', () => {
    const r = priceRange([{ high: 1000, low: 1000 }], null);
    expect(r && r.max - r.min).toBeGreaterThan(0);
    expect(priceRange([], null)).toBeNull();
  });

  it('maps indices and prices to CSS pixels consistently', () => {
    const layout = makeLayout(400, 300, { left: 50, top: 10, right: 10, bottom: 20 }, 10);
    expect(layout.width).toBe(340);
    expect(layout.height).toBe(270);
    expect(layout.slot).toBeCloseTo(34, 6);
    const view = resolveView(10, { scale: 1, offset: null });
    const x0 = xOfIndex(0, view, layout);
    expect(x0).toBeCloseTo(50 + 17, 6);
    expect(indexAtX(x0, view, layout)).toBe(0);
    expect(indexAtX(50 + 340 + 100, view, layout)).toBe(9);
    const range = { min: 0, max: 100 };
    expect(yOfPrice(100, range, layout)).toBe(10);
    expect(yOfPrice(0, range, layout)).toBe(280);
  });
});
