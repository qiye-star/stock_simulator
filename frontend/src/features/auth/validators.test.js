import { describe, expect, it } from 'vitest';
import {
  validateChangePassword,
  validateLogin,
  validatePassword,
  validateRegister,
  validateUsername,
} from './validators.js';

describe('validateUsername', () => {
  it('enforces 2-20 length', () => {
    expect(validateUsername('a')).toBe('auth.regError.usernameLength');
    expect(validateUsername('ab')).toBeNull();
    expect(validateUsername('a'.repeat(20))).toBeNull();
    expect(validateUsername('a'.repeat(21))).toBe('auth.regError.usernameLength');
  });

  it('allows CJK, letters, digits, underscore and hyphen only', () => {
    expect(validateUsername('张三_1-x')).toBeNull();
    expect(validateUsername('bad name')).toBe('auth.regError.usernameInvalidChars');
    expect(validateUsername('a.b')).toBe('auth.regError.usernameInvalidChars');
  });

  it('rejects reserved prototype names', () => {
    expect(validateUsername('__proto__')).toBe('auth.regError.usernameInvalidChars');
    expect(validateUsername('constructor')).toBe('auth.regError.usernameInvalidChars');
  });
});

describe('validatePassword', () => {
  it('requires 6-20 characters', () => {
    expect(validatePassword('12345')).toBe('auth.regError.passwordLength');
    expect(validatePassword('123456')).toBeNull();
    expect(validatePassword('x'.repeat(21))).toBe('auth.regError.passwordLength');
    expect(validatePassword('')).toBe('auth.regError.passwordLength');
  });
});

describe('validateLogin', () => {
  it('requires both fields, trimming username only', () => {
    expect(validateLogin({ username: '  ', password: 'x' })).toBe('auth.loginError.empty');
    expect(validateLogin({ username: 'bob', password: '' })).toBe('auth.loginError.empty');
    expect(validateLogin({ username: ' bob ', password: 'pw' })).toBeNull();
  });
});

describe('validateRegister', () => {
  const ok = { username: 'bob', password: '123456', confirm: '123456' };
  it('passes a valid form', () => {
    expect(validateRegister(ok)).toBeNull();
  });
  it('reports mismatched confirmation', () => {
    expect(validateRegister({ ...ok, confirm: '654321' })).toBe('auth.regError.passwordMismatch');
  });
  it('checks username before password', () => {
    expect(validateRegister({ username: 'x', password: '1', confirm: '2' })).toBe('auth.regError.usernameLength');
  });
});

describe('validateChangePassword', () => {
  it('walks the legacy checks in order', () => {
    expect(validateChangePassword({ current: '', next: 'abcdef', confirm: 'abcdef' })).toBe('password.requireCurrent');
    expect(validateChangePassword({ current: 'old1', next: 'abc', confirm: 'abc' })).toBe('password.invalidNewLength');
    expect(validateChangePassword({ current: 'old1', next: 'abcdef', confirm: 'abcdeg' })).toBe('password.mismatch');
    expect(validateChangePassword({ current: 'abcdef', next: 'abcdef', confirm: 'abcdef' })).toBe('password.sameAsCurrent');
    expect(validateChangePassword({ current: 'old1', next: 'newpass', confirm: 'newpass' })).toBeNull();
  });
});
