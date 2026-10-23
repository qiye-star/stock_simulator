import { describe, expect, it } from 'vitest';
import { normalizeSaveList, toSaveCard } from './viewModel.js';
import { renderSaveList } from './view.js';

const t = (key, params = {}) => `${key}${Object.keys(params).length ? JSON.stringify(params) : ''}`;
const env = { lang: 'zh-CN', t, formatMoney: (cents) => `F${cents}` };

describe('toSaveCard', () => {
  it('uses the name when present, otherwise the default name with index', () => {
    expect(toSaveCard({ id: 'a', name: '  局A ', cash_cents: 100 }, 0, env).name).toBe('局A');
    expect(toSaveCard({ id: 'b', name: '' }, 2, env).name).toBe('save.defaultName{"index":3}');
  });

  it('formats cash (integer cents) and falls back to initial fund', () => {
    expect(toSaveCard({ id: 'a', cash_cents: 123456 }, 0, env).info).toContain('F123456');
    expect(toSaveCard({ id: 'a', initial_fund_cents: 50 }, 0, env).info).toContain('F50');
    expect(toSaveCard({ id: 'a' }, 0, env).info).toContain('"fund":"--"');
  });
});

describe('normalizeSaveList', () => {
  it('keeps only objects with a string id', () => {
    expect(normalizeSaveList([{ id: 'x' }, null, 3, { name: 'no id' }])).toEqual([{ id: 'x' }]);
    expect(normalizeSaveList('nope')).toEqual([]);
  });
});

describe('renderSaveList escaping', () => {
  it('escapes user-controlled save names', () => {
    const card = toSaveCard({ id: 'q', name: '<img src=x onerror=alert(1)>' }, 0, env);
    const out = renderSaveList([card], t).value;
    expect(out).not.toContain('<img');
    expect(out).toContain('&lt;img');
  });

  it('renders the empty state', () => {
    expect(renderSaveList([], t).value).toContain('save.empty');
  });
});
