/**
 * 默认转义的 tagged template。
 *
 *   html`<span>${userName}</span>`   // userName 自动转义
 *   html`<ul>${items.map(i => html`<li>${i}</li>`)}</ul>`   // 嵌套 SafeHtml 原样插入
 *   html`${raw(trustedSvg)}`         // 显式 opt-out，仅用于受控的静态标记
 *
 * 插值规则：
 *   - SafeHtml（html`` 或 raw() 的结果）：原样插入
 *   - 数组：逐项按同样规则处理后拼接
 *   - null / undefined / false：输出空字符串
 *   - 其它：String(v) 后做 HTML 转义
 *
 * 页面层只接受 SafeHtml（见 dom.js 的 setHtml / fragment），
 * 因此不经 html`` 的字符串无法写入 DOM。
 */

/** 已确认安全的 HTML 标记包装。请勿直接构造，使用 html`` 或 raw()。 */
export class SafeHtml {
  /** @param {string} value */
  constructor(value) {
    this.value = value;
  }

  toString() {
    return this.value;
  }
}

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const ESCAPE_RE = /[&<>"']/g;

/**
 * 转义 HTML 特殊字符。
 * @param {unknown} value
 * @returns {string}
 */
export function escapeHtml(value) {
  if (value === null || value === undefined || value === false) return '';
  return String(value).replace(ESCAPE_RE, (ch) => ESCAPES[ch]);
}

/**
 * opt-out：标记为安全，不再转义。仅用于受控的静态标记。
 * @param {string} value
 * @returns {SafeHtml}
 */
export function raw(value) {
  return new SafeHtml(value === null || value === undefined ? '' : String(value));
}

/** @param {unknown} v @returns {v is SafeHtml} */
export function isSafeHtml(v) {
  return v instanceof SafeHtml;
}

/**
 * @param {unknown} value
 * @returns {string}
 */
function interpolate(value) {
  if (isSafeHtml(value)) return value.value;
  if (Array.isArray(value)) return value.map(interpolate).join('');
  return escapeHtml(value);
}

/**
 * 默认转义的模板字符串标签。
 * @param {TemplateStringsArray} strings
 * @param {...unknown} values
 * @returns {SafeHtml}
 */
export function html(strings, ...values) {
  let out = strings[0];
  for (let i = 0; i < values.length; i++) {
    out += interpolate(values[i]) + strings[i + 1];
  }
  return new SafeHtml(out);
}
