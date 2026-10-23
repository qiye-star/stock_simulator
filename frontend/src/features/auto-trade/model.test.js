import { describe, expect, it } from 'vitest';
import {
  buildConfigPayload,
  centsToText,
  configRow,
  configToForm,
  conditionText,
  eventRow,
  parseEvents,
  parseMaxTotalTrades,
  parseNumeric,
  percentPrecision,
  percentToText,
  priceFromMarket,
  ratioQuantity,
  readStats,
  reasonKey,
  statsView,
  statusOf,
  yuanToCents,
} from './model.js';

/** 测试用翻译：返回 key 与参数，便于断言“渲染时才翻译”。 */
const t = (key, params) => (params ? `${key}${JSON.stringify(params)}` : key);

const STOCKS = new Set(['600036', '601398']);
const baseForm = {
  code: '600036',
  direction: 'buy',
  conditionType: 'price',
  operator: 'above',
  conditionValue: '12.5',
  quantity: '100',
  priceType: 'market',
  limitPrice: '',
  stopLoss: '',
  takeProfit: '',
  maxTrades: '',
  maxAmount: '',
};
const ctx = (over = {}) => ({
  stockExists: (c) => STOCKS.has(c),
  configs: [],
  editingId: null,
  t,
  ...over,
});
const build = (over = {}, c = {}) => buildConfigPayload({ ...baseForm, ...over }, ctx(c));

describe('money and percent parsing (integer units, no float drift)', () => {
  it('yuan -> cents exactly, rejects more than two decimals', () => {
    expect(yuanToCents(12.34)).toBe(1234);
    expect(yuanToCents(1.1)).toBe(110);
    expect(yuanToCents(0.07)).toBe(7);
    expect(yuanToCents(0.001)).toBeNaN();
    expect(yuanToCents(null)).toBeNull();
    expect(yuanToCents(Infinity)).toBeNaN();
  });

  it('percent precision: at most two decimals (backend stores x100 integers)', () => {
    expect(percentPrecision(2.5)).toBe(250);
    expect(percentPrecision(-3.25)).toBe(-325);
    expect(percentPrecision(1.234)).toBeNaN();
    expect(percentPrecision(null)).toBeNull();
  });

  it('parseNumeric: empty -> null, garbage -> NaN', () => {
    expect(parseNumeric('  ')).toBeNull();
    expect(parseNumeric('abc')).toBeNaN();
    expect(parseNumeric('-5')).toBe(-5);
  });

  it('text helpers round-trip without trailing zeros', () => {
    expect(centsToText(1250)).toBe('12.5');
    expect(centsToText(1200)).toBe('12');
    expect(percentToText(2.5)).toBe('2.5');
    expect(percentToText(2)).toBe('2');
  });
});

describe('buildConfigPayload: form -> request body', () => {
  it('price condition in yuan becomes condition_value_cents and nulls unused fields', () => {
    const r = build();
    expect(r).toEqual({
      ok: true,
      payload: {
        code: '600036',
        direction: 'buy',
        condition_type: 'price',
        condition_operator: 'above',
        condition_value_cents: 1250,
        condition_percent: null,
        quantity: 100,
        price_type: 'market',
        limit_price_cents: null,
        stop_loss_percent: null,
        take_profit_percent: null,
        max_trades: 0,
        max_amount_cents: null,
      },
    });
  });

  it('percentage condition is sent as float percent (condition_percent), never bp', () => {
    const r = build({ conditionType: 'percentage', operator: 'below', conditionValue: '3.5' });
    expect(r.ok).toBe(true);
    expect(r.payload.condition_percent).toBe(3.5);
    expect(r.payload.condition_value_cents).toBeNull();
    expect(r.payload.condition_operator).toBe('below');
    // 后端 condition_percent 范围 0-1000，负值由后端拒绝，前端同样拦截
    expect(build({ conditionType: 'percentage', conditionValue: '-3.5' }).message).toBe('auto.invalidPercent');
  });

  it('time condition sends no operator and no value (backend rejects both)', () => {
    const r = build({ conditionType: 'time', conditionValue: '' });
    expect(r.ok).toBe(true);
    expect(r.payload.condition_operator).toBeNull();
    expect(r.payload.condition_value_cents).toBeNull();
    expect(r.payload.condition_percent).toBeNull();
  });

  it('profit condition is sell-only and maps to cents', () => {
    expect(build({ conditionType: 'profit', conditionValue: '500' })).toEqual({ ok: false, message: 'auto.profitOnlyForSell' });
    const ok = build({ direction: 'sell', conditionType: 'profit', conditionValue: '500' });
    expect(ok.ok).toBe(true);
    expect(ok.payload.condition_value_cents).toBe(50000);
  });

  it('limit orders require a positive limit price in cents', () => {
    expect(build({ priceType: 'limit', limitPrice: '' })).toEqual({ ok: false, message: 'auto.requireLimitPrice' });
    expect(build({ priceType: 'limit', limitPrice: '0' })).toEqual({ ok: false, message: 'auto.invalidLimitPrice' });
    const ok = build({ priceType: 'limit', limitPrice: '9.99' });
    expect(ok.payload.limit_price_cents).toBe(999);
    expect(ok.payload.price_type).toBe('limit');
  });

  it('risk controls are percentages of cost: stop-loss absolute value, zero means unset, max_trades 0 = unlimited', () => {
    const r = build({ stopLoss: '-5', takeProfit: '20', maxTrades: '3', maxAmount: '5000' });
    expect(r.payload.stop_loss_percent).toBe(5);
    expect(r.payload.take_profit_percent).toBe(20);
    expect(r.payload.max_trades).toBe(3);
    expect(r.payload.max_amount_cents).toBe(500000);
    const none = build({ stopLoss: '0', takeProfit: '', maxTrades: '', maxAmount: '' });
    expect(none.payload.stop_loss_percent).toBeNull();
    expect(none.payload.take_profit_percent).toBeNull();
    expect(none.payload.max_trades).toBe(0);
    expect(none.payload.max_amount_cents).toBeNull();
  });

  it('rejects invalid numbers with the matching message key', () => {
    expect(build({ quantity: '0' }).message).toBe('auto.invalidQuantity');
    expect(build({ quantity: '1.5' }).message).toBe('auto.invalidQuantity');
    expect(build({ conditionValue: '' }).message).toBe('auto.requireConditionValue');
    expect(build({ conditionValue: '1.005' }).message).toBe('auto.invalidConditionValue');
    expect(build({ conditionType: 'percentage', conditionValue: '2000' }).message).toBe('auto.invalidPercent');
    expect(build({ stopLoss: 'x' }).message).toBe('auto.invalidStopLoss');
    expect(build({ stopLoss: '150' }).message).toBe('auto.invalidStopLoss');
    expect(build({ takeProfit: '-1' }).message).toBe('auto.invalidTakeProfit');
    expect(build({ maxTrades: '0' }).message).toBe('auto.invalidMaxTrades');
    expect(build({ maxAmount: '-5' }).message).toBe('auto.invalidMaxAmount');
  });

  it('checks stock existence and duplicates (excluding the config being edited)', () => {
    expect(build({ code: '' }).message).toBe('auto.requireStockCode');
    expect(build({ code: '999999' }).message).toBe('auto.stockNotExist');
    const existing = [{ id: 'a', code: '600036', direction: 'buy' }];
    const dup = buildConfigPayload({ ...baseForm }, ctx({ configs: existing }));
    expect(dup.ok).toBe(false);
    expect(dup.message).toContain('auto.duplicateConfig');
    expect(dup.message).toContain('auto.directionBuy');
    // 同代码不同方向允许
    expect(buildConfigPayload({ ...baseForm, direction: 'sell' }, ctx({ configs: existing })).ok).toBe(true);
    // 编辑自身不算重复
    expect(buildConfigPayload({ ...baseForm }, ctx({ configs: existing, editingId: 'a' })).ok).toBe(true);
  });
});

describe('configToForm round-trip', () => {
  it('server config maps back to editable inputs and rebuilds the same payload', () => {
    const payload = build({ priceType: 'limit', limitPrice: '9.5', stopLoss: '5', maxAmount: '2000', maxTrades: '4' }).payload;
    // 服务端 AutoConfigOut：只有 *_percent / condition_value_cents，没有 *_bp / *_cents 风控字段
    const server = { id: 'cfg1', name: '招商银行', ...payload, stop_loss_percent: 5, take_profit_percent: null, condition_percent: null };
    const form = configToForm(server);
    expect(form.conditionValue).toBe('12.5');
    expect(form.limitPrice).toBe('9.5');
    expect(form.stopLoss).toBe('5');
    expect(form.maxAmount).toBe('2000');
    expect(form.maxTrades).toBe('4');
    const again = buildConfigPayload(form, ctx({ editingId: 'cfg1' }));
    expect(again).toEqual({ ok: true, payload });
  });

  it('percentage configs show condition_percent as text', () => {
    const form = configToForm({ code: '600036', direction: 'sell', condition_type: 'percentage', condition_operator: 'above', condition_percent: 2.5, quantity: 100, price_type: 'market' });
    expect(form.conditionValue).toBe('2.5');
  });
});

describe('view models', () => {
  it('conditionText follows legacy wording', () => {
    expect(conditionText({ condition_type: 'time' }, t)).toBe('auto.conditionTextTime');
    expect(conditionText({ condition_type: 'price', condition_operator: 'below', condition_value_cents: 1250 }, t)).toBe(
      'auto.conditionTextPrice' + 'auto.operatorBelow' + '12.5' + 'auto.unitYuan',
    );
    expect(conditionText({ condition_type: 'percentage', condition_operator: 'above', condition_percent: 2.5 }, t)).toBe(
      'auto.conditionTextPercentage' + 'auto.operatorAbove' + '2.5%',
    );
    expect(conditionText({ condition_type: 'weird', condition_operator: 'above', condition_value_cents: 1 }, t)).toMatch(/^auto\.conditionUnknown/);
  });

  it('configRow resolves names and direction labels', () => {
    const row = configRow({ id: 'x', code: '600036', direction: 'sell', condition_type: 'time', quantity: 200, price_type: 'limit' }, new Map([['600036', '招商银行']]), t);
    expect(row).toMatchObject({ id: 'x', name: '招商银行', direction: 'sell', dirText: 'auto.directionSell', priceTypeText: 'auto.limitPriceLabel' });
  });

  it('status: stopped / running / paused / limit reached', () => {
    expect(statusOf({ enabled: false, paused: false }, 100).key).toBe('auto.statusStopped');
    expect(statusOf({ enabled: true, paused: false }, 5)).toMatchObject({ key: 'auto.statusRunning', tone: 'running', enabled: true });
    expect(statusOf({ enabled: true, paused: true }, 5)).toMatchObject({ key: 'auto.statusPaused', paused: true });
    expect(statusOf({ enabled: true, paused: false }, 0).key).toBe('auto.statusLimitReached');
    expect(statusOf(null, 0).key).toBe('auto.statusStopped');
  });

  it('stats come from AutoStatusOut; remaining counts successful trades only', () => {
    const stats = readStats({ enabled: true, paused: false, max_total_trades: 10, total_trades: 7, success_trades: 4, failed_trades: 3, total_pnl_cents: -12345 });
    expect(stats).toEqual({ total: 7, success: 4, failed: 3, pnlCents: -12345, maxTotal: 10 });
    expect(readStats(null)).toMatchObject({ total: 0, success: 0, maxTotal: 100 });
    const sv = statsView(stats, stats.maxTotal, 'zh-CN');
    expect(sv.remainingText).toBe('6 / 10');
    expect(sv.pnlText).toBe('-¥123.45');
    expect(sv.pnlTone).toBe('down');
    expect(statsView({ total: 0, success: 12, failed: 0, pnlCents: 0 }, 10).remaining).toBe(0);
  });

  it('parseMaxTotalTrades accepts positive integers only', () => {
    expect(parseMaxTotalTrades('50')).toBe(50);
    expect(parseMaxTotalTrades('0')).toBeNull();
    expect(parseMaxTotalTrades('2.5')).toBeNull();
    expect(parseMaxTotalTrades('')).toBeNull();
  });
});

describe('events: reason codes are localized at render time', () => {
  it('reasonKey maps every event reason to error.* (no feature-local mapping)', () => {
    expect(reasonKey('TRADE_INSUFFICIENT_FUNDS')).toBe('error.TRADE_INSUFFICIENT_FUNDS');
    expect(reasonKey('AUTO_MAX_AMOUNT_EXCEEDED')).toBe('error.AUTO_MAX_AMOUNT_EXCEEDED');
    expect(reasonKey('SOMETHING_NEW')).toBe('error.UNKNOWN');
    expect(reasonKey(null)).toBe('error.UNKNOWN');
  });

  it('a failed event stores only the code and is translated by the translator passed at render time', () => {
    const e = { id: 'e1', stock_code: '600036', direction: 'buy', condition_type: 'price', success: false, reason_code: 'AUTO_LIMIT_REACHED', pnl_cents: 0, created_at: '2026-01-01T01:02:03Z' };
    const zh = eventRow(e, new Map([['600036', '招商银行']]), (k, p) => `[zh]${k}${p ? JSON.stringify(p) : ''}`, 'zh-CN');
    const en = eventRow(e, new Map(), (k, p) => `[en]${k}${p ? JSON.stringify(p) : ''}`, 'en-US');
    expect(zh.detail).toBe('[zh]error.AUTO_LIMIT_REACHED');
    expect(en.detail).toBe('[en]error.AUTO_LIMIT_REACHED');
    expect(zh.name).toBe('招商银行');
    expect(en.name).toBe('600036');
    expect(zh.statusText).toBe('[zh]common.statusFailed');
    expect(zh.amountText).toBe('--');
  });

  it('successful events use the buy/sell success text and show signed pnl', () => {
    const e = { id: 'e2', stock_code: '600036', direction: 'sell', condition_type: 'profit', success: true, reason_code: null, pnl_cents: -20050, created_at: 'bad' };
    const row = eventRow(e, new Map(), t);
    expect(row.detail).toBe('auto.sellSuccess');
    expect(row.timeText).toBe('--');
    expect(row.amountText).toBe('-¥200.50');
    expect(row.tone).toBe('down');
    expect(row.triggerText).toBe('auto.conditionTriggerLabel: auto.conditionTextProfit');
  });

  it('parseEvents accepts arrays and {items}', () => {
    expect(parseEvents([{ id: 1 }])).toEqual([{ id: 1 }]);
    expect(parseEvents({ items: [{ id: 2 }] })).toEqual([{ id: 2 }]);
    expect(parseEvents(null)).toEqual([]);
  });
});

describe('quantity helpers', () => {
  it('sell ratio uses holdings and rounds down to the lot size', () => {
    expect(ratioQuantity({ direction: 'sell', ratio: 0.5, holdingQty: 350, cashCents: 0, priceCents: null, unit: 100 })).toBe(100);
    expect(ratioQuantity({ direction: 'sell', ratio: 1, holdingQty: 350, cashCents: 0, priceCents: null, unit: 1 })).toBe(350);
  });

  it('buy ratio uses cash / price (cents) and needs a price', () => {
    // 10000 元 / 12.50 元 = 800 股，按 100 股一手 1/2 -> 400
    expect(ratioQuantity({ direction: 'buy', ratio: 0.5, holdingQty: 0, cashCents: 1_000_000, priceCents: 1250, unit: 100 })).toBe(400);
    expect(ratioQuantity({ direction: 'buy', ratio: 1, holdingQty: 0, cashCents: 1_000_000, priceCents: null, unit: 100 })).toBe(0);
  });

  it('priceFromMarket reads integer price_cents only', () => {
    expect(priceFromMarket({ price_cents: 1234 })).toBe(1234);
    expect(priceFromMarket({ price_cents: 12.3 })).toBeNull();
    expect(priceFromMarket(null)).toBeNull();
  });
});
