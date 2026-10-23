import { describe, expect, it } from 'vitest';
import {
  holdingRow,
  mergeTrades,
  parseHoldings,
  parseTradePage,
  portfolioSummary,
  signedMoney,
  toneOf,
  tradeRow,
} from './model.js';

describe('portfolio P&L (integer cents)', () => {
  const holdings = [
    { code: '600036', quantity: 1000, avg_price_cents: 1000, total_cost_cents: 1_000_000, market_price_cents: 1200 },
  ];

  it('summary derives assets, value, floating P&L and return from cents', () => {
    const s = portfolioSummary({ cashCents: 500_000, initialFundCents: 2_000_000, holdings }, 'zh-CN');
    expect(s.values).toEqual({ totalAssetsCents: 1_700_000, stockValueCents: 1_200_000, floatingPnlCents: 200_000 });
    expect(s.totalAssetsText).toBe('¥1.70万'); // 17000 元 >= 1 万
    expect(s.floatingPnlText).toBe('+¥2000.00');
    expect(s.floatingTone).toBe('up');
    expect(s.totalReturnText).toBe('-15.00%');
    expect(s.totalReturnTone).toBe('down');
  });

  it('switches to 万 / 亿 for large zh-CN amounts and K/M/B for en-US', () => {
    const big = [{ code: '600036', quantity: 100_000, avg_price_cents: 10_000, total_cost_cents: 1_000_000_000, market_price_cents: 10_000 }];
    const s = portfolioSummary({ cashCents: 0, initialFundCents: 1, holdings: big }, 'zh-CN');
    expect(s.stockValueText).toBe('¥1000.00万'); // 1e7 元
    const en = portfolioSummary({ cashCents: 0, initialFundCents: 1, holdings: big }, 'en-US');
    expect(en.stockValueText).toBe('¥10.00M');
  });

  it('zero initial fund yields zero return instead of dividing by zero', () => {
    const s = portfolioSummary({ cashCents: 100, initialFundCents: 0, holdings: [] });
    expect(s.totalReturnText).toBe('0.00%');
  });

  it('holding row: profit is signed and rate uses total cost', () => {
    const names = new Map([['600036', '招商银行']]);
    const r = holdingRow(holdings[0], names, 'zh-CN');
    expect(r.name).toBe('招商银行');
    expect(r.avgText).toBe('10.00');
    expect(r.priceText).toBe('12.00');
    expect(r.marketValueText).toBe('¥1.20万');
    expect(r.pnlText).toBe('+¥2000.00');
    expect(r.rateText).toBe('+20.00%');
    expect(r.tone).toBe('up');
  });

  it('missing price falls back to cost for valuation and shows a placeholder', () => {
    const r = holdingRow({ code: '600036', quantity: 100, avg_price_cents: 1000, total_cost_cents: 100_000, market_price_cents: null });
    expect(r.priceText).toBe('--');
    expect(r.pnlText).toBe('+¥0.00');
    expect(r.name).toBe('600036');
  });

  it('signedMoney prefixes sign outside the currency symbol', () => {
    expect(signedMoney(-12345, 'zh-CN')).toBe('-¥123.45');
    expect(signedMoney(0, 'zh-CN')).toBe('+¥0.00');
    expect(toneOf(0)).toBe('up');
  });

  it('rejects non-integer unit prices', () => {
    expect(() => tradeRow({ seq: 1, code: '600036', side: 'buy', price_cents: 12.5, quantity: 1, gross_cents: 1, created_at: '2026-01-01T00:00:00Z' })).toThrow(TypeError);
  });
});

describe('trade records', () => {
  const t = (seq, extra = {}) => ({ seq, code: '600036', side: 'buy', price_cents: 1000, quantity: 100, gross_cents: 100_000, created_at: '2026-01-01T00:00:00Z', ...extra });

  it('mergeTrades dedupes by id/seq and keeps newest first', () => {
    const merged = mergeTrades([t(2), t(1)], [t(3), t(2, { quantity: 200 })]);
    expect(merged.map((x) => x.seq)).toEqual([3, 2, 1]);
    expect(merged[1].quantity).toBe(200);
  });

  it('parseTradePage tolerates missing fields', () => {
    expect(parseTradePage({ items: [t(1)], next_cursor: 'abc' })).toEqual({ items: [t(1)], nextCursor: 'abc' });
    expect(parseTradePage({})).toEqual({ items: [], nextCursor: null });
    expect(parseTradePage({ items: [], next_cursor: '' }).nextCursor).toBeNull();
  });

  it('parseHoldings returns an empty list for malformed responses', () => {
    expect(parseHoldings(null)).toEqual([]);
    expect(parseHoldings({ holdings: 'x' })).toEqual([]);
  });

  it('tradeRow maps buy to down tone and sell to up tone, amount from gross cents', () => {
    const buy = tradeRow(t(1), new Map([['600036', '招商银行']]), 'zh-CN');
    expect(buy.sideKey).toBe('common.buy');
    expect(buy.tone).toBe('down');
    expect(buy.name).toBe('招商银行');
    expect(buy.amountText).toBe('¥1000.00');
    expect(buy.priceText).toBe('10.00');
    const sell = tradeRow(t(2, { side: 'sell', gross_cents: -250_000 }), undefined, 'en-US');
    expect(sell.sideKey).toBe('common.sell');
    expect(sell.tone).toBe('up');
    expect(sell.amountText).toBe('¥2.50K');
  });
});
