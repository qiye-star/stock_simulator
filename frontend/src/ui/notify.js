/**
 * 轻量通知条（移植自 legacy/game.js showNotification，并修复其忽略 type 参数的问题）。
 *
 * 文本一律通过 textContent 写入，不接受 HTML。
 * 样式：class="notification notification-<type>"，颜色见 styles/components/notification-types.css。
 */

/** @typedef {'info' | 'success' | 'warning' | 'error'} NotifyType */

export const NOTIFY_TYPES = Object.freeze(['info', 'success', 'warning', 'error']);
export const NOTIFY_SHOW_DELAY_MS = 10;
export const NOTIFY_VISIBLE_MS = 2000;
export const NOTIFY_REMOVE_DELAY_MS = 300;

/**
 * @param {unknown} type
 * @returns {NotifyType}
 */
export function normalizeNotifyType(type) {
  return NOTIFY_TYPES.includes(/** @type {any} */ (type)) ? /** @type {NotifyType} */ (type) : 'info';
}

/**
 * 显示一条通知。
 * @param {string} message 纯文本
 * @param {NotifyType} [type='info']
 * @param {{ duration?: number, doc?: Document }} [opts]
 * @returns {() => void} 立即关闭的函数
 */
export function showNotification(message, type = 'info', opts = {}) {
  const doc = opts.doc ?? document;
  const kind = normalizeNotifyType(type);
  const duration = opts.duration ?? NOTIFY_VISIBLE_MS;

  const el = doc.createElement('div');
  el.className = `notification notification-${kind}`;
  el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  el.dataset.type = kind;
  el.textContent = String(message);
  doc.body.appendChild(el);

  let removeTimer = 0;
  const showTimer = setTimeout(() => el.classList.add('show'), NOTIFY_SHOW_DELAY_MS);
  const hideTimer = setTimeout(close, duration);

  function close() {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    el.classList.remove('show');
    removeTimer = setTimeout(() => el.remove(), NOTIFY_REMOVE_DELAY_MS);
  }

  return () => {
    clearTimeout(removeTimer);
    close();
  };
}
