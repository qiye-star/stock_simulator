import { describe, expect, it } from 'vitest';
import { formatMoney, formatPercent, formatVolume } from './format.js';

describe('formatMoney (integer cents)', () => {
  it('zh-CN uses 万 / 亿 thresholds', () => {
    expect(formatMoney(123456, 'zh-CN')).toBe('1234.56');
    expect(formatMoney(100000000, 'zh-CN')).toBe('100.00万');
    expect(formatMoney(1000000 * 100, 'zh-CN')).toBe('100.00万');
    expect(formatMoney(10000000000, 'zh-CN')).toBe('1.00亿');
  });

  it('en-US uses K / M / B thresholds', () => {
    expect(formatMoney(123456, 'en-US')).toBe('1.23K');
    expect(formatMoney(250000000, 'en-US')).toBe('2.50M');
    expect(formatMoney(300000000000, 'en-US')).toBe('3.00B');
    expect(formatMoney(5, 'en-US')).toBe('0.05');
  });

  it('keeps sign for negative amounts', () => {
    expect(formatMoney(-150, 'zh-CN')).toBe('-1.50');
    expect(formatMoney(-1000000 * 100, 'en-US')).toBe('-1.00M');
  });

  it('rejects non-integer cents', () => {
    expect(() => formatMoney(12.5, 'zh-CN')).toThrow(TypeError);
    expect(() => formatMoney(Number.NaN, 'zh-CN')).toThrow(TypeError);
  });
});

describe('formatPercent', () => {
  it('converts ratio to percent with 2 digits by default', () => {
    expect(formatPercent(0.1234)).toBe('12.34%');
    expect(formatPercent(-0.05)).toBe('-5.00%');
    expect(formatPercent(0)).toBe('0.00%');
  });

  it('supports digits and signed output', () => {
    expect(formatPercent(0.0512, { digits: 1 })).toBe('5.1%');
    expect(formatPercent(0.02, { signed: true })).toBe('+2.00%');
    expect(formatPercent(-0.02, { signed: true })).toBe('-2.00%');
  });

  it('rejects non-finite input', () => {
    expect(() => formatPercent(Number.POSITIVE_INFINITY)).toThrow(TypeError);
  });
});

describe('formatVolume', () => {
  it('zh-CN uses 万 / 亿 for share counts', () => {
    expect(formatVolume(999, 'zh-CN')).toBe('999');
    expect(formatVolume(12345, 'zh-CN')).toBe('1.23万');
    expect(formatVolume(200000000, 'zh-CN')).toBe('2.00亿');
  });

  it('en-US uses K / M / B', () => {
    expect(formatVolume(1500, 'en-US')).toBe('1.50K');
    expect(formatVolume(3000000, 'en-US')).toBe('3.00M');
    expect(formatVolume(4000000000, 'en-US')).toBe('4.00B');
  });
});
