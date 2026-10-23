/**
 * market 模块共享的错误提示：ApiError.code -> i18n 文案，经 showNotification 显示。
 */
import { i18n } from '../../i18n/i18n.js';
import { errorI18nKey, ClientErrorCode } from '../../i18n/errors.js';
import { showNotification } from '../../ui/notify.js';

/**
 * @param {unknown} err
 * @returns {string} 业务错误码（非 ApiError 时为 UNKNOWN）
 */
export function errorCodeOf(err) {
  const code = /** @type {any} */ (err)?.code;
  return typeof code === 'string' ? code : ClientErrorCode.UNKNOWN;
}

/**
 * @param {unknown} err
 * @param {{ doc?: Document }} [opts]
 */
export function notifyError(err, opts = {}) {
  showNotification(i18n.t(errorI18nKey(errorCodeOf(err))), 'error', opts);
}

/**
 * @param {string} key i18n key
 * @param {'info' | 'success' | 'warning' | 'error'} [type]
 * @param {Record<string, string | number>} [params]
 */
export function notifyKey(key, type = 'info', params = null) {
  showNotification(i18n.t(key, params), type);
}
