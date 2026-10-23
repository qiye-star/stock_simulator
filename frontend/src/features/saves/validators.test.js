import { describe, expect, it } from 'vitest';
import {
  buildCreateSaveRequest,
  parseCustomFundCents,
  percentToRateString,
  randomFundCents,
  validateSaveName,
} from './validators.js';

describe('validateSaveName', () => {
  it('trims and accepts CJK, letters, digits and common punctuation', () => {
    expect(validateSaveName('  我的局 1 ')).toEqual({ name: '我的局 1' });
    expect(validateSaveName('A-b_c.d（测试）')).toEqual({ name: 'A-b_c.d（测试）' });
  });
  it('rejects empty, too long, and invalid characters', () => {
    expect(validateSaveName('   ')).toEqual({ error: 'rename.error.empty' });
    expect(validateSaveName('a'.repeat(21))).toEqual({ error: 'rename.error.length' });
    expect(validateSaveName('bad<tag>')).toEqual({ error: 'rename.error.invalid' });
  });
});

describe('randomFundCents', () => {
  it('maps the random source onto 50-199 wan, in integer cents', () => {
    expect(randomFundCents(() => 0)).toBe(50 * 1_000_000);
    expect(randomFundCents(() => 0.999999)).toBe(199 * 1_000_000);
    expect(Number.isInteger(randomFundCents(() => 0.5))).toBe(true);
  });
});

describe('parseCustomFundCents', () => {
  it('converts 万元 to integer cents within 10-10000 wan', () => {
    expect(parseCustomFundCents('10')).toBe(10_000_000);
    expect(parseCustomFundCents('12.5')).toBe(12_500_000);
    expect(parseCustomFundCents('9.99')).toBeNull();
    expect(parseCustomFundCents('10001')).toBeNull();
    expect(parseCustomFundCents('abc')).toBeNull();
  });
});

describe('percentToRateString', () => {
  it('converts percent input to a 6-decimal ratio string without float drift', () => {
    expect(percentToRateString('0.03')).toBe('0.000300');
    expect(percentToRateString('0.13')).toBe('0.001300');
    expect(percentToRateString('0')).toBe('0.000000');
    expect(percentToRateString('1')).toBe('0.010000');
    expect(percentToRateString('0.001')).toBe('0.000010');
  });
  it('rejects out-of-range or non-numeric input', () => {
    expect(percentToRateString('-0.1')).toBeNull();
    expect(percentToRateString('1.5')).toBeNull();
    expect(percentToRateString('')).toBeNull();
  });
});

describe('buildCreateSaveRequest', () => {
  const base = { fundType: 'custom', customWan: '100', buyFeePct: '0.03', sellFeePct: '0.13', t0Mode: true, tradeUnit: 100 };

  it('builds the POST /saves body with cents and rate strings', () => {
    expect(buildCreateSaveRequest(base)).toEqual({
      body: {
        initial_fund_cents: 100_000_000,
        buy_fee_rate: '0.000300',
        sell_fee_rate: '0.001300',
        t0_mode: true,
        trade_unit: 100,
      },
    });
  });

  it('uses a random fund when requested', () => {
    const res = buildCreateSaveRequest({ ...base, fundType: 'random' }, () => 0.1);
    expect('body' in res && res.body.initial_fund_cents).toBe(65 * 1_000_000);
  });

  it('reports invalid custom fund, fee and trade unit', () => {
    expect(buildCreateSaveRequest({ ...base, customWan: '5' })).toEqual({ error: 'setup.fundInvalid' });
    expect(buildCreateSaveRequest({ ...base, sellFeePct: '2' })).toEqual({ error: 'setup.feeInvalid' });
    expect(buildCreateSaveRequest({ ...base, tradeUnit: 10 })).toEqual({ error: 'error.VALIDATION_ERROR' });
  });
});
