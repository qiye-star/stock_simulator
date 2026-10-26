import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import zhCN from './locales/zh-CN.js';
import enUS from './locales/en-US.js';
import { ERROR_I18N_KEYS, ErrorCode, errorI18nKey } from './errors.js';
import { I18n } from './i18n.js';

const CONTRACT = fileURLToPath(new URL('../../../docs/CONTRACT.md', import.meta.url));
const BACKEND_ERRORS = fileURLToPath(new URL('../../../backend/src/stocksim/core/errors.py', import.meta.url));

/** 从契约「错误契约」章节的完整列表行提取所有 ErrorCode。 */
function contractErrorCodes() {
  const text = readFileSync(CONTRACT, 'utf-8');
  const start = text.indexOf('## 错误契约');
  const end = text.indexOf('## REST API');
  expect(start).toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(start);
  const section = text.slice(start, end);
  // 「完整列表：」后的逗号分隔行（避免把正文里提到的 ERROR_STATUS 等标识符误当错误码）
  const listLine = section.split('\n').find((l) => l.startsWith('AUTH_INVALID_CREDENTIALS,'));
  expect(listLine).toBeTruthy();
  return listLine.split(',').map((s) => s.match(/[A-Z][A-Z0-9_]*/)?.[0]).filter(Boolean);
}

describe('locale key alignment', () => {
  it('zh-CN and en-US have identical key sets', () => {
    const zh = Object.keys(zhCN).sort();
    const en = Object.keys(enUS).sort();
    const onlyZh = zh.filter((k) => !(k in enUS));
    const onlyEn = en.filter((k) => !(k in zhCN));
    expect({ onlyZh, onlyEn }).toEqual({ onlyZh: [], onlyEn: [] });
  });

  it('no locale value is empty', () => {
    for (const [name, msgs] of [['zh-CN', zhCN], ['en-US', enUS]]) {
      const empty = Object.entries(msgs).filter(([, v]) => typeof v !== 'string' || v.trim() === '').map(([k]) => k);
      expect(empty, name).toEqual([]);
    }
  });
});

/** 从后端 core/errors.py 的 ErrorCode(StrEnum) 提取枚举名（文本解析，不依赖 Python 运行时）。 */
function backendErrorCodes() {
  const text = readFileSync(BACKEND_ERRORS, 'utf-8');
  const start = text.indexOf('class ErrorCode(StrEnum):');
  expect(start).toBeGreaterThan(-1);
  const end = text.indexOf('\n\n\n', start);
  const body = text.slice(start, end > start ? end : undefined);
  return [...body.matchAll(/^\s+([A-Z][A-Z0-9_]*) = "\1"$/gm)].map((m) => m[1]);
}

describe('backend/frontend error code parity', () => {
  it('frontend ErrorCode = backend ErrorCode + INTERNAL_ERROR (+ client codes live in ClientErrorCode)', () => {
    const backend = backendErrorCodes();
    expect(backend.length).toBeGreaterThan(50);
    // INTERNAL_ERROR 由全局异常处理器直接写出，不在后端枚举内（见 docs/CONTRACT.md）
    const frontend = Object.keys(ErrorCode).filter((c) => c !== 'INTERNAL_ERROR');
    expect({
      onlyBackend: backend.filter((c) => !frontend.includes(c)),
      onlyFrontend: frontend.filter((c) => !backend.includes(c)),
    }).toEqual({ onlyBackend: [], onlyFrontend: [] });
    expect(Object.keys(ErrorCode)).toContain('INTERNAL_ERROR');
  });
});

describe('error code mapping', () => {
  it('ErrorCode covers every code listed in docs/CONTRACT.md', () => {
    const contract = contractErrorCodes();
    expect(contract.length).toBeGreaterThanOrEqual(20);
    expect(Object.keys(ErrorCode).sort()).toEqual([...contract].sort());
  });

  it('every ErrorCode maps to an i18n key present in both locales', () => {
    for (const code of Object.keys(ErrorCode)) {
      const key = errorI18nKey(code);
      expect(key, code).toBe(`error.${code}`);
      expect(zhCN, code).toHaveProperty([key]);
      expect(enUS, code).toHaveProperty([key]);
    }
  });

  it('unknown codes fall back to error.UNKNOWN', () => {
    expect(errorI18nKey('SOMETHING_NEW')).toBe(ERROR_I18N_KEYS.UNKNOWN);
    expect(errorI18nKey('__proto__')).toBe(ERROR_I18N_KEYS.UNKNOWN);
    expect(zhCN).toHaveProperty([ERROR_I18N_KEYS.UNKNOWN]);
  });
});

describe('I18n', () => {
  const makeI18n = (storage = null) => new I18n({ 'zh-CN': { a: '甲 {n}', only: '中' }, 'en-US': { a: 'A {n}' } }, { storage, doc: null });

  it('interpolates params and falls back to zh-CN then key', () => {
    const i = makeI18n();
    expect(i.t('a', { n: 3 })).toBe('甲 3');
    i.setLanguage('en-US', { applyDOM: false, persist: false });
    expect(i.t('a', { n: 3 })).toBe('A 3');
    expect(i.t('only')).toBe('中');
    expect(i.t('missing.key')).toBe('missing.key');
  });

  it('persists and restores language from storage', () => {
    const store = new Map();
    const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
    const i = makeI18n(storage);
    i.setLanguage('en-US', { applyDOM: false });
    expect(store.get('stock_simulator_lang')).toBe('en-US');
    const j = makeI18n(storage);
    j.init();
    expect(j.getLanguage()).toBe('en-US');
  });

  it('notifies listeners on change and supports unsubscribe', () => {
    const i = makeI18n();
    const calls = [];
    const off = i.onChange((lang, prev) => calls.push([lang, prev]));
    i.setLanguage('en-US', { applyDOM: false, persist: false });
    off();
    i.setLanguage('zh-CN', { applyDOM: false, persist: false });
    expect(calls).toEqual([['en-US', 'zh-CN']]);
  });
});
