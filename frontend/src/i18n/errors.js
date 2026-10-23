/**
 * 错误码 -> i18n key 映射。
 *
 * ErrorCode 必须与 docs/CONTRACT.md「错误契约」及 backend/src/stocksim/core/errors.py 保持一致。
 * 新增错误码时：1) 此处加条目；2) locales/zh-CN.js 与 en-US.js 同时加 error.<CODE>；
 * 3) 测试 src/i18n/i18n.test.js 会校验覆盖率。
 */

/** 后端返回的业务错误码（HTTP 错误体 {code, params}）。 */
export const ErrorCode = Object.freeze({
  AUTH_INVALID_CREDENTIALS: 'AUTH_INVALID_CREDENTIALS',
  AUTH_USERNAME_TAKEN: 'AUTH_USERNAME_TAKEN',
  AUTH_USERNAME_INVALID: 'AUTH_USERNAME_INVALID',
  AUTH_PASSWORD_WEAK: 'AUTH_PASSWORD_WEAK',
  AUTH_REQUIRED: 'AUTH_REQUIRED',
  SAVE_NOT_FOUND: 'SAVE_NOT_FOUND',
  SAVE_LIMIT_REACHED: 'SAVE_LIMIT_REACHED',
  STOCK_NOT_FOUND: 'STOCK_NOT_FOUND',
  TRADE_INSUFFICIENT_FUNDS: 'TRADE_INSUFFICIENT_FUNDS',
  TRADE_INSUFFICIENT_HOLDINGS: 'TRADE_INSUFFICIENT_HOLDINGS',
  TRADE_T1_SELL_BLOCKED: 'TRADE_T1_SELL_BLOCKED',
  TRADE_INVALID_QUANTITY: 'TRADE_INVALID_QUANTITY',
  TRADE_PRICE_OUT_OF_LIMIT: 'TRADE_PRICE_OUT_OF_LIMIT',
  ORDER_LIMIT_NOT_REACHED: 'ORDER_LIMIT_NOT_REACHED',
  MARKET_CLOSED: 'MARKET_CLOSED',
  AUTO_CONFIG_DUPLICATE: 'AUTO_CONFIG_DUPLICATE',
  AUTO_LIMIT_REACHED: 'AUTO_LIMIT_REACHED',
  DEBUG_DISABLED: 'DEBUG_DISABLED',
  LEGACY_IMPORT_INVALID: 'LEGACY_IMPORT_INVALID',
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  TRADE_T1_BUY_BLOCKED: 'TRADE_T1_BUY_BLOCKED',
  TRADE_PRICE_DEVIATION_EXCEEDED: 'TRADE_PRICE_DEVIATION_EXCEEDED',
  TRADE_PRICE_DEVIATION_CONFIRM: 'TRADE_PRICE_DEVIATION_CONFIRM',
  TRADE_CIRCUIT_BREAKER_ACTIVE: 'TRADE_CIRCUIT_BREAKER_ACTIVE',
  AUTO_CONFIG_NOT_FOUND: 'AUTO_CONFIG_NOT_FOUND',
  AUTO_MAX_AMOUNT_EXCEEDED: 'AUTO_MAX_AMOUNT_EXCEEDED',
  INTERNAL_ERROR: 'INTERNAL_ERROR',
});

/** 前端自身产生的错误码（非后端返回）。 */
export const ClientErrorCode = Object.freeze({
  NETWORK: 'NETWORK',
  UNKNOWN: 'UNKNOWN',
});

/** @type {Readonly<Record<string, string>>} */
export const ERROR_I18N_KEYS = Object.freeze({
  ...Object.fromEntries(Object.keys(ErrorCode).map((code) => [code, `error.${code}`])),
  ...Object.fromEntries(Object.keys(ClientErrorCode).map((code) => [code, `error.${code}`])),
});

/**
 * @param {string} code
 * @returns {string} i18n key；未知码回退到 error.UNKNOWN
 */
export function errorI18nKey(code) {
  return Object.prototype.hasOwnProperty.call(ERROR_I18N_KEYS, code)
    ? ERROR_I18N_KEYS[code]
    : ERROR_I18N_KEYS.UNKNOWN;
}

/**
 * 统一的错误文案入口（各功能模块不得再自建错误码映射）。
 * 非 ApiError 的异常一律按 UNKNOWN 处理。
 * @param {unknown} err ApiError（带 code）或其它异常
 * @param {(key: string) => string} t 翻译函数
 * @returns {string}
 */
export function errorMessage(err, t) {
  const code = /** @type {any} */ (err)?.code;
  return t(errorI18nKey(typeof code === 'string' ? code : ClientErrorCode.UNKNOWN));
}
