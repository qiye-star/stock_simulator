import { describe, expect, it } from 'vitest';
import { TUTORIAL_STEPS, placeTooltip, TOOLTIP_HEIGHT, TOOLTIP_WIDTH } from './steps.js';

const rect = (left, top, width, height) => ({ left, top, width, height, right: left + width, bottom: top + height });

describe('TUTORIAL_STEPS', () => {
  it('has nine steps with i18n keys tutorial.step1..9', () => {
    expect(TUTORIAL_STEPS).toHaveLength(9);
    expect(TUTORIAL_STEPS[8].key).toBe('tutorial.step9');
  });
});

describe('placeTooltip', () => {
  const vp = { width: 1200, height: 800 };

  it('centres the tooltip when there is no target', () => {
    expect(placeTooltip(null, vp)).toMatchObject({ centered: true, highlight: null, arrow: null });
  });

  it('prefers placing below the target with the arrow pointing up', () => {
    const p = placeTooltip(rect(100, 100, 200, 40), vp);
    expect(p.centered).toBe(false);
    expect(p.tooltip.top).toBe(140 + 20);
    expect(p.arrow.rotate).toBe(0);
    expect(p.highlight).toEqual({ left: 95, top: 95, width: 210, height: 50 });
  });

  it('flips above when there is no room below', () => {
    const p = placeTooltip(rect(100, 700, 200, 40), vp);
    expect(p.tooltip.top).toBe(700 - TOOLTIP_HEIGHT - 20);
    expect(p.arrow.rotate).toBe(180);
  });

  it('keeps the tooltip inside the viewport', () => {
    const p = placeTooltip(rect(1190, 10, 10, 10), vp);
    expect(p.tooltip.left).toBeLessThanOrEqual(vp.width - TOOLTIP_WIDTH - 20);
    expect(p.tooltip.left).toBeGreaterThanOrEqual(20);
    expect(p.tooltip.top).toBeGreaterThanOrEqual(20);
  });
});
