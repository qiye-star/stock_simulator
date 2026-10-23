import { describe, expect, it } from 'vitest';
import {
  DEVIATION_CODE,
  buildOrderBody,
  estimateOrder,
  feeCents,
  isDeviationConfirm,
  maxBuyQuantity,
  parseQuantity,
  parseYuanToCents,
  ratioQuantity,
  sellableOf,
  validateOrder,
} from './model.js';

describe('parsing (integer cents)', () => {
  it('parses yuan strings to cents exactly', () => {
    expect(parseYuanToCents('12.34')).toBe(1234);
    expect(parseYuanToCents('12.3')).toBe(1230);
    expect(parseYuanToCents('0.1')).toBe(10);
    expect(parseYuanToCents('7')).toBe(700);
    expect(parseYuanToCents('0.005')).toBeNull();
    expect(parseYuanToCents('-1')).toBeNull();
    expect(parseYuanToCents('')).toBeNull();
    // 浮点陷阱：0.29 * 100 = 28.999999999999996
    expect(parseYuanToCents('0.29')).toBe(29);
  });

  it('parses quantities as positive integers only', () => {
    expect(parseQuantity('300')).toBe(300);
    expect(parseQuantity('1.5')).toBeNull();
    expect(parseQuantity('-100')).toBeNull();
    expect(parseQuantity('')).toBeNull();
  });
});

describe('fees and estimates', () => {
  it('rounds fee half up to the cent using exact decimal rates', () => {
    // 1000 分 * 0.0003 = 0.3 分 -> 0
    expect(feeCents(1000, '0.0003')).toBe(0);
    // 5000 分 * 0.0003 = 1.5 分 -> 2（半数向上）
    expect(feeCents(5000, '0.0003')).toBe(2);
    // 1234567 * 0.0013 = 1604.9371 -> 1605
    expect(feeCents(1234567, '0.0013')).toBe(1605);
    expect(feeCents(100, '0')).toBe(0);
  });

  it('buy adds fee, sell subtracts fee', () => {
    const buy = estimateOrder({ side: 'buy', priceCents: 1000, quantity: 1000, buyRate: '0.0003', sellRate: '0.0013' });
    expect(buy).toEqual({ amount_cents: 1000000, fee_cents: 300, total_cents: 1000300 });
    const sell = estimateOrder({ side: 'sell', priceCents: 1000, quantity: 1000, buyRate: '0.0003', sellRate: '0.0013' });
    expect(sell.total_cents).toBe(1000000 - 1300);
  });
});

describe('quantities and ratios', () => {
  it('max buy respects cash including fee and trade unit', () => {
    // 资金 100000 分，价 1000 分，单位 100：100000/1000=100 股，但含费超出，需减一手
    const q = maxBuyQuantity({ cashCents: 100000, priceCents: 1000, unit: 100, buyRate: '0.0003' });
    expect(q).toBe(0);
    const q2 = maxBuyQuantity({ cashCents: 1000000, priceCents: 1000, unit: 100, buyRate: '0.0003' });
    expect(q2).toBe(900);
    expect(maxBuyQuantity({ cashCents: 0, priceCents: 1000, unit: 1, buyRate: '0' })).toBe(0);
  });

  it('ratio quantities are floored to the unit', () => {
    expect(ratioQuantity(950, 0.5, 100)).toBe(400);
    expect(ratioQuantity(950, 1, 100)).toBe(900);
    expect(ratioQuantity(7, 0.25, 1)).toBe(1);
  });

  it('sellable comes from the account holdings', () => {
    const account = { cash_cents: 0, holdings: [{ code: '600036', sellable_quantity: 200 }] };
    expect(sellableOf(account, '600036')).toBe(200);
    expect(sellableOf(account, '000001')).toBe(0);
    expect(sellableOf(null, '600036')).toBe(0);
  });
});

describe('validation and request bodies', () => {
  it('rejects bad price, quantity and unit mismatch', () => {
    expect(validateOrder({ quantity: 100, priceCents: null, unit: 1 })?.key).toBe('trade.invalidPrice');
    expect(validateOrder({ quantity: 0, priceCents: 100, unit: 1 })?.key).toBe('trade.invalidQuantity');
    expect(validateOrder({ quantity: 150, priceCents: 100, unit: 100 })).toEqual({
      key: 'trade.invalidQuantityUnit',
      params: { unit: 100 },
    });
    expect(validateOrder({ quantity: 200, priceCents: 100, unit: 100 })).toBeNull();
  });

  it('untouched price means market order; user-edited price means limit order', () => {
    expect(buildOrderBody({ code: '600036', side: 'buy', quantity: 100, priceCents: 1000, priceDirty: false })).toEqual({
      code: '600036',
      side: 'buy',
      quantity: 100,
      price_type: 'market',
    });
    expect(buildOrderBody({ code: '600036', side: 'sell', quantity: 100, priceCents: 1050, priceDirty: true })).toEqual({
      code: '600036',
      side: 'sell',
      quantity: 100,
      price_type: 'limit',
      limit_price_cents: 1050,
    });
  });

  it('recognises the price deviation confirm code', () => {
    expect(isDeviationConfirm({ code: DEVIATION_CODE })).toBe(true);
    expect(isDeviationConfirm({ code: 'TRADE_INSUFFICIENT_FUNDS' })).toBe(false);
    expect(isDeviationConfirm(undefined)).toBe(false);
  });
});
