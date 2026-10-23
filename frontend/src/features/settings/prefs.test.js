import { describe, expect, it } from 'vitest';
import { clockButtonKey, diffPreferences, parseRefreshRate } from './prefs.js';

describe('diffPreferences', () => {
  it('keeps only fields that differ from the current user', () => {
    const current = { theme: 'dark', lang: 'zh-CN', refresh_rate_ms: 3000, tutorial_completed: false };
    expect(diffPreferences(current, { theme: 'dark', lang: 'en-US' })).toEqual({ lang: 'en-US' });
    expect(diffPreferences(current, { theme: 'dark' })).toEqual({});
    expect(diffPreferences(current, { tutorial_completed: undefined })).toEqual({});
  });
});

describe('parseRefreshRate', () => {
  it('accepts integers within the API range 500-60000', () => {
    expect(parseRefreshRate('1000')).toBe(1000);
    expect(parseRefreshRate(500)).toBe(500);
    expect(parseRefreshRate(499)).toBeNull();
    expect(parseRefreshRate(60001)).toBeNull();
    expect(parseRefreshRate('1.5')).toBeNull();
  });
});

describe('clockButtonKey', () => {
  it('shows resume while paused', () => {
    expect(clockButtonKey(true)).toBe('settings.resume');
    expect(clockButtonKey(false)).toBe('settings.pause');
  });
});
