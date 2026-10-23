import { describe, expect, it } from 'vitest';
import {
  TAP_COUNT,
  achievementNames,
  achievementOptions,
  clockFromMinute,
  formatHM,
  isTradingMinute,
  nextTapState,
  parseClockInput,
  parseFundInput,
  parseUnlocked,
  timeStatus,
} from './model.js';

const t = (k, p) => (p ? `${k}${JSON.stringify(p)}` : k);

describe('hidden entry: five taps within the window', () => {
  it('opens on the fifth tap and resets', () => {
    let st = { count: 0, last: 0 };
    const opened = [];
    for (let i = 0; i < TAP_COUNT; i++) {
      st = nextTapState(st, 1000 + i * 300);
      opened.push(st.open);
    }
    expect(opened).toEqual([false, false, false, false, true]);
    expect(st.count).toBe(0);
  });

  it('a gap longer than 2s restarts the count (legacy timer semantics)', () => {
    let st = { count: 0, last: 0 };
    for (let i = 0; i < 4; i++) st = nextTapState(st, 1000 + i * 100);
    st = nextTapState(st, 1000 + 3000); // 间隔 > 2s
    expect(st.count).toBe(1);
    expect(st.open).toBe(false);
  });
});

describe('time helpers', () => {
  it('trading sessions follow legacy isTradingTime', () => {
    expect(isTradingMinute(570)).toBe(true);
    expect(isTradingMinute(690)).toBe(true);
    expect(isTradingMinute(691)).toBe(false);
    expect(isTradingMinute(780)).toBe(true);
    expect(isTradingMinute(900)).toBe(true);
    expect(isTradingMinute(901)).toBe(false);
  });

  it('status key and colour (early bird / night owl / afternoon / closed / normal)', () => {
    expect(timeStatus(572)).toEqual({ key: 'marketStatus.earlyBird', color: '#2980b9' });
    expect(timeStatus(697).key).toBe('marketStatus.nightOwl');
    expect(timeStatus(782).key).toBe('marketStatus.afternoonOpen');
    expect(timeStatus(60).key).toBe('marketStatus.notTrading');
    expect(timeStatus(600).key).toBe('marketStatus.normal');
  });

  it('minute <-> clock conversion', () => {
    expect(clockFromMinute(14 * 60 + 55)).toEqual({ hour: 14, minute: 55 });
    expect(formatHM(9, 5)).toBe('09:05');
  });

  it('clock input must be integers within range', () => {
    expect(parseClockInput('9', '30')).toEqual({ ok: true, hour: 9, minute: 30 });
    expect(parseClockInput('24', '0')).toEqual({ ok: false, key: 'debug.invalidTime' });
    expect(parseClockInput('1', '60')).toEqual({ ok: false, key: 'debug.invalidTime' });
    expect(parseClockInput('', '5')).toEqual({ ok: false, key: 'debug.invalidTime' });
    expect(parseClockInput('9.5', '0')).toEqual({ ok: false, key: 'debug.invalidTime' });
  });
});

describe('fund input', () => {
  it('converts yuan to integer cents and rejects non-positive or over-precise values', () => {
    expect(parseFundInput('100000')).toEqual({ ok: true, amountCents: 10_000_000 });
    expect(parseFundInput('12.34')).toEqual({ ok: true, amountCents: 1234 });
    expect(parseFundInput('0')).toEqual({ ok: false, key: 'debug.invalidFund' });
    expect(parseFundInput('-5')).toEqual({ ok: false, key: 'debug.invalidFund' });
    expect(parseFundInput('1.005')).toEqual({ ok: false, key: 'debug.invalidFund' });
    expect(parseFundInput('')).toEqual({ ok: false, key: 'debug.invalidFund' });
  });
});

describe('achievement helpers', () => {
  it('options use achievement names and level labels', () => {
    const opts = achievementOptions([{ id: 'first_trade', level: 'bronze' }, { id: 'x', level: 'legend' }], t);
    expect(opts).toEqual([
      { value: 'first_trade', label: 'achievement.first_trade.name (profile.levelBronze)' },
      { value: 'x', label: 'achievement.x.name (profile.levelLegend)' },
    ]);
    expect(achievementNames(['a', 'b'], t)).toBe('achievement.a.name、achievement.b.name');
  });

  it('parseUnlocked accepts string arrays and {achievement_id} items', () => {
    expect(parseUnlocked(['a', 'b'])).toEqual(['a', 'b']);
    expect(parseUnlocked([{ achievement_id: 'c', unlocked_at: 'x' }, null])).toEqual(['c']);
    expect(parseUnlocked({ items: ['d'] })).toEqual(['d']);
    expect(parseUnlocked(undefined)).toEqual([]);
  });
});
