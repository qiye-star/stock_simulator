/**
 * 认证相关的纯校验函数（无 DOM、无 I/O，可单测）。
 *
 * 规则与后端 services/auth.py 保持一致（用户名 2-20 位、字符集、保留名；密码 6-20 位）。
 * 各函数返回 i18n key（成功返回 null），由 controller 用 i18n.t 翻译。
 * 移植自 legacy/game.js login 1000-1250 / register / changePassword 2442-2513。
 */

export const USERNAME_MIN_LEN = 2;
export const USERNAME_MAX_LEN = 20;
export const PASSWORD_MIN_LEN = 6;
export const PASSWORD_MAX_LEN = 20;

/** 与 legacy USERNAME_PATTERN 及后端 USERNAME_PATTERN 一致。 */
export const USERNAME_PATTERN = /^[一-龥a-zA-Z0-9_-]+$/;

/** 与后端 RESERVED_USERNAMES 一致（防原型链污染）。 */
export const RESERVED_USERNAMES = new Set([
  '__proto__',
  'constructor',
  'prototype',
  'hasOwnProperty',
  'toString',
  'valueOf',
  '__defineGetter__',
  '__defineSetter__',
]);

/**
 * @param {string} username 已 trim
 * @returns {string | null} i18n key 或 null
 */
export function validateUsername(username) {
  if (username.length < USERNAME_MIN_LEN || username.length > USERNAME_MAX_LEN) {
    return 'auth.regError.usernameLength';
  }
  if (!USERNAME_PATTERN.test(username) || RESERVED_USERNAMES.has(username)) {
    return 'auth.regError.usernameInvalidChars';
  }
  return null;
}

/**
 * @param {string} password
 * @returns {string | null}
 */
export function validatePassword(password) {
  if (!password || password.length < PASSWORD_MIN_LEN || password.length > PASSWORD_MAX_LEN) {
    return 'auth.regError.passwordLength';
  }
  return null;
}

/**
 * 登录表单：用户名会 trim，密码原样。
 * @param {{ username: string, password: string }} input
 * @returns {string | null}
 */
export function validateLogin({ username, password }) {
  if (!username.trim() || !password) return 'auth.loginError.empty';
  return null;
}

/**
 * 注册表单。
 * @param {{ username: string, password: string, confirm: string }} input
 * @returns {string | null}
 */
export function validateRegister({ username, password, confirm }) {
  const name = username.trim();
  const userErr = validateUsername(name);
  if (userErr) return userErr;
  const pwErr = validatePassword(password);
  if (pwErr) return pwErr;
  if (password !== confirm) return 'auth.regError.passwordMismatch';
  return null;
}

/**
 * 修改密码表单。
 * @param {{ current: string, next: string, confirm: string }} input
 * @returns {string | null}
 */
export function validateChangePassword({ current, next, confirm }) {
  if (!current) return 'password.requireCurrent';
  if (!next || next.length < PASSWORD_MIN_LEN || next.length > PASSWORD_MAX_LEN) {
    return 'password.invalidNewLength';
  }
  if (next !== confirm) return 'password.mismatch';
  if (next === current) return 'password.sameAsCurrent';
  return null;
}
