import { describe, expect, it } from 'vitest';
import {
  LEGACY_USERS_KEY,
  MAX_IMPORT_BYTES,
  isImportDone,
  markImportDone,
  readLegacyContent,
  shouldOfferBanner,
  validateImportFile,
} from './detect.js';

const memory = (init = {}) => {
  const data = new Map(Object.entries(init));
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    data,
  };
};

describe('readLegacyContent', () => {
  it('returns the raw legacy text or null', () => {
    expect(readLegacyContent(memory({ [LEGACY_USERS_KEY]: 'CIPHER' }))).toBe('CIPHER');
    expect(readLegacyContent(memory({ [LEGACY_USERS_KEY]: '   ' }))).toBeNull();
    expect(readLegacyContent(memory())).toBeNull();
    expect(readLegacyContent(null)).toBeNull();
  });

  it('swallows storage access errors', () => {
    const broken = { getItem: () => { throw new Error('denied'); } };
    expect(readLegacyContent(broken)).toBeNull();
  });
});

describe('import done flag', () => {
  it('is scoped per user id', () => {
    const s = memory();
    markImportDone(s, 'u1');
    expect(isImportDone(s, 'u1')).toBe(true);
    expect(isImportDone(s, 'u2')).toBe(false);
    expect(isImportDone(s, '')).toBe(false);
  });
});

describe('validateImportFile', () => {
  it('enforces the 5MB cap', () => {
    expect(validateImportFile({ size: MAX_IMPORT_BYTES })).toBeNull();
    expect(validateImportFile({ size: MAX_IMPORT_BYTES + 1 })).toBe('notification.importTooLarge');
    expect(validateImportFile({ size: -1 })).toBe('notification.importFailed');
  });
});

describe('shouldOfferBanner', () => {
  const base = { user: { id: 'u' }, content: 'X', done: false, dismissed: false };
  it('offers only when logged in, data exists, and not done or dismissed', () => {
    expect(shouldOfferBanner(base)).toBe(true);
    expect(shouldOfferBanner({ ...base, user: null })).toBe(false);
    expect(shouldOfferBanner({ ...base, content: null })).toBe(false);
    expect(shouldOfferBanner({ ...base, done: true })).toBe(false);
    expect(shouldOfferBanner({ ...base, dismissed: true })).toBe(false);
  });
});
