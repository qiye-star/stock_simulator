/**
 * 弹窗开关（沿用 legacy 约定：.modal 元素加 / 去 .active 类）。
 * 不负责弹窗内容，内容由各 feature 的 view.js 渲染。
 */

/**
 * @param {string | Element} target 元素或 id
 * @returns {Element | null}
 */
function resolve(target) {
  if (typeof target !== 'string') return target;
  return document.getElementById(target);
}

/**
 * @param {string | Element} target
 * @returns {boolean} 元素是否存在
 */
export function openModal(target) {
  const el = resolve(target);
  if (!el) return false;
  el.classList.add('active');
  return true;
}

/** @param {string | Element} target */
export function closeModal(target) {
  resolve(target)?.classList.remove('active');
}

/**
 * @param {string | Element} target
 * @returns {boolean}
 */
export function isModalOpen(target) {
  return Boolean(resolve(target)?.classList.contains('active'));
}
