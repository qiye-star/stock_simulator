/**
 * 数值格式化（移植自 legacy/game.js formatMoney 4938-4958 与成交量格式化 2866-2873）。
 *
 * - formatMoney 入参为**整数分**（API 约定 *_cents 字段），输出为元的数值字符串，无货币符号。
 * - 中文：万 / 亿；英文：K / M / B。
 */
import { i18n } from '../i18n/i18n.js';

/** @typedef {'zh-CN' | 'en-US'} Lang */

/**
 * @param {number} value
 * @param {string} label
 */
function assertInteger(value, label) {
  if (!Number.isInteger(value)) {
    throw new TypeError(`${label} must be an integer, got ${value}`);
  }
}

/**
 * 金额（整数分）格式化。
 * @param {number} cents 整数分，如 123456 -> 1234.56
 * @param {Lang} [lang]
 * @returns {string}
 */
export function formatMoney(cents, lang = i18n.getLanguage()) {
  assertInteger(cents, 'cents');
  const yuan = cents / 100;
  const abs = Math.abs(yuan);
  if (lang === 'en-US') {
    if (abs >= 1e9) return (yuan / 1e9).toFixed(2) + 'B';
    if (abs >= 1e6) return (yuan / 1e6).toFixed(2) + 'M';
    if (abs >= 1e3) return (yuan / 1e3).toFixed(2) + 'K';
    return yuan.toFixed(2);
  }
  if (abs >= 1e8) return (yuan / 1e8).toFixed(2) + '亿';
  if (abs >= 1e4) return (yuan / 1e4).toFixed(2) + '万';
  return yuan.toFixed(2);
}

/**
 * 比例格式化：0.1234 -> "12.34%"。
 * @param {number} ratio 小数比例（非百分数）
 * @param {{ digits?: number, signed?: boolean }} [opts] signed=true 时正数前加 "+"
 * @returns {string}
 */
export function formatPercent(ratio, opts = {}) {
  const { digits = 2, signed = false } = opts;
  if (!Number.isFinite(ratio)) throw new TypeError(`ratio must be finite, got ${ratio}`);
  const text = (ratio * 100).toFixed(digits) + '%';
  return signed && ratio > 0 ? '+' + text : text;
}

/**
 * 成交量（股数）格式化。
 * @param {number} shares 股数（整数）
 * @param {Lang} [lang]
 * @returns {string}
 */
export function formatVolume(shares, lang = i18n.getLanguage()) {
  assertInteger(shares, 'shares');
  if (lang === 'en-US') {
    if (shares >= 1e9) return (shares / 1e9).toFixed(2) + 'B';
    if (shares >= 1e6) return (shares / 1e6).toFixed(2) + 'M';
    if (shares >= 1e3) return (shares / 1e3).toFixed(2) + 'K';
    return shares.toFixed(0);
  }
  if (shares >= 1e8) return (shares / 1e8).toFixed(2) + '亿';
  if (shares >= 1e4) return (shares / 1e4).toFixed(2) + '万';
  return shares.toFixed(0);
}
