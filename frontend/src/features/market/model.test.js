import { describe, expect, it } from 'vitest';
import {
  changeText,
  clockLabel,
  clockStatus,
  limitPrices,
  mergeQuote,
  nextSort,
  normalizeDetail,
  normalizeQuote,
  normalizeSnapshot,
  normalizeTick,
  parseClock,
  roundHalfUpDiv,
  visibleCodes,
} from './model.js';

describe('clock', () => {
  it('formats and parses minute-of-day', () => {
    expect(clockLabel(570)).toBe('09:30');
    expect(clockLabel(0)).toBe('00:00');
    expect(parseClock(570)).toBe(570);
    expect(parseClock('13:05')).toBe(785);
    expect(parseClock(1440)).toBeNull();
    expect(parseClock('25:00')).toBeNull();
    expect(parseClock(null)).toBeNull();
  });

  it('status priority: paused > windows > not trading > normal', () => {
    expect(clockStatus(600, true).key).toBe('marketStatus.paused');
    expect(clockStatus(570, false).key).toBe('marketStatus.earlyBird');
    expect(clockStatus(575, false).key).toBe('marketStatus.earlyBird');
    expect(clockStatus(576, false).key).toBe('marketStatus.normal');
    expect(clockStatus(697, false).key).toBe('marketStatus.nightOwl');
    expect(clockStatus(782, false).key).toBe('marketStatus.afternoonOpen');
    expect(clockStatus(600, false).key).toBe('marketStatus.normal');
    expect(clockStatus(0, false)).toEqual({ key: 'marketStatus.notTrading', cls: 'status' });
    expect(clockStatus(null, false).key).toBe('');
  });
});

describe('quotes', () => {
  it('normalizes WebSocket tick rows (positional q)', () => {
    const t = normalizeTick({
      t: 'tick',
      tick: 42,
      advanced: 1,
      clock: { minute: 600, trading_day: 3, paused: false, trading: true },
      full: false,
      q: [['600036', 12345, -150, 9000], ['bad']],
    });
    expect(t).toEqual({
      tick: 42,
      minuteOfDay: 600,
      paused: false,
      quotes: [{ code: '600036', price_cents: 12345, change_bp: -150, volume: 9000, prev_close_cents: null }],
    });
    expect(normalizeTick({ t: 'ping' })).toBeNull();
  });

  it('derives change_bp from prev close when absent, rounding half up', () => {
    const q = normalizeQuote({ code: 'X', price_cents: 1105, prev_close_cents: 1000 });
    expect(q?.change_bp).toBe(1050);
    expect(normalizeQuote({ code: 'X' })).toBeNull();
  });

  it('merges quotes keeping name and prev close', () => {
    const prev = { code: 'X', price_cents: 100, change_bp: 0, volume: 1, prev_close_cents: 100, name: '甲' };
    const merged = mergeQuote(prev, { code: 'X', price_cents: 110, change_bp: 1000, volume: 5, prev_close_cents: null });
    expect(merged).toMatchObject({ name: '甲', price_cents: 110, prev_close_cents: 100, volume: 5 });
  });

  it('normalizes snapshot in array or wrapped form', () => {
    const a = normalizeSnapshot({ stocks: [{ code: 'A', price_cents: 1 }] });
    const b = normalizeSnapshot({
      tick: 3,
      trading_day: 2,
      clock_minute: 585,
      paused: true,
      stocks: [
        { code: 'A', price_cents: 1, watchlisted: true },
        { code: 'B', price_cents: 2, watchlisted: false },
      ],
    });
    expect(a.quotes).toHaveLength(1);
    expect(normalizeSnapshot([{ code: 'A', price_cents: 1 }]).quotes).toHaveLength(0);
    expect(b).toMatchObject({ tick: 3, tradingDay: 2, minuteOfDay: 585, paused: true, watchlist: ['A'] });
    expect(b.quotes).toHaveLength(2);
  });

  it('formats change text with sign like legacy', () => {
    expect(changeText(0)).toBe('+0.00%');
    expect(changeText(-1234)).toBe('-12.34%');
    expect(changeText(250)).toBe('+2.50%');
  });
});

describe('limits and rounding', () => {
  it('limit prices are +/-10% rounded half up to cents', () => {
    expect(limitPrices(1000)).toEqual({ up: 1100, down: 900 });
    expect(limitPrices(1234)).toEqual({ up: 1357, down: 1111 }); // 1357.4 / 1110.6
    expect(roundHalfUpDiv(5, 2)).toBe(3);
    expect(roundHalfUpDiv(-5, 2)).toBe(-3);
  });
});

describe('sorting and filtering', () => {
  const stockList = [
    { code: '600036', name: '招商银行', industry: '', profile: '' },
    { code: '601398', name: '工商银行', industry: '', profile: '' },
    { code: '000001', name: '平安', industry: '', profile: '' },
  ];
  const quotes = new Map([
    ['600036', { code: '600036', price_cents: 3000, change_bp: 100, volume: 1, prev_close_cents: null }],
    ['601398', { code: '601398', price_cents: 500, change_bp: -300, volume: 1, prev_close_cents: null }],
    ['000001', { code: '000001', price_cents: 900, change_bp: 50, volume: 1, prev_close_cents: null }],
  ]);
  const base = { stockList, quotes, search: '', watchlist: [], watchlistMode: false, sort: { field: null, order: 'asc' } };

  it('keeps pool order without sort', () => {
    expect(visibleCodes(base)).toEqual(['600036', '601398', '000001']);
  });

  it('sorts by price and change in both directions', () => {
    expect(visibleCodes({ ...base, sort: { field: 'price', order: 'asc' } })).toEqual(['601398', '000001', '600036']);
    expect(visibleCodes({ ...base, sort: { field: 'change', order: 'desc' } })).toEqual(['600036', '000001', '601398']);
  });

  it('filters by code or name and by watchlist', () => {
    expect(visibleCodes({ ...base, search: '银行' })).toEqual(['600036', '601398']);
    expect(visibleCodes({ ...base, search: ' 0000 ' })).toEqual(['000001']);
    expect(visibleCodes({ ...base, watchlist: ['000001'], watchlistMode: true })).toEqual(['000001']);
  });

  it('cycles sort state asc -> desc -> off', () => {
    let s = nextSort({ field: null, order: 'asc' }, 'price');
    expect(s).toEqual({ field: 'price', order: 'asc' });
    s = nextSort(s, 'price');
    expect(s).toEqual({ field: 'price', order: 'desc' });
    s = nextSort(s, 'price');
    expect(s).toEqual({ field: null, order: 'asc' });
  });
});

describe('detail and watchlist normalization', () => {
  it('normalizes order book levels (nearest first) and history', () => {
    const d = normalizeDetail({
      code: '600036',
      name: '招商银行',
      price_cents: 1000,
      prev_close_cents: 1000,
      order_book: {
        bids: [{ price_cents: 999, volume: 5 }],
        asks: [{ price_cents: 1001, volume: 6 }, { price_cents: 1002, volume: 7 }],
      },
      candles: [
        { trading_day: 0, date: '2026-01-02', open_cents: 1, high_cents: 2, low_cents: 1, close_cents: 2, volume: 3 },
        { open_cents: 'x' },
      ],
    });
    expect(d?.bids).toEqual([{ price_cents: 999, volume: 5 }]);
    expect(d?.asks[1]).toEqual({ price_cents: 1002, volume: 7 });
    expect(d?.limit_up_cents).toBe(1100);
    expect(d?.history).toEqual([{ date: '2026-01-02', open: 1, high: 2, low: 1, close: 2, volume: 3 }]);
  });
});
