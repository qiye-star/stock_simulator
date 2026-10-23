/**
 * market 模块内的小型 DOM 工具：只在值真正变化时写入，避免无谓的重排。
 */

/**
 * @param {Element | null} el
 * @param {string} text
 */
export function setText(el, text) {
  if (el && el.textContent !== text) el.textContent = text;
}

/**
 * 设置 class（整串替换），仅在不同时写入。
 * @param {Element | null} el
 * @param {string} className
 */
export function setClass(el, className) {
  if (el && el.className !== className) el.className = className;
}

/**
 * 切换 class 集合中的某一个，仅在状态变化时写入。
 * @param {Element | null} el
 * @param {string} name
 * @param {boolean} on
 */
export function toggleClass(el, name, on) {
  if (el && el.classList.contains(name) !== on) el.classList.toggle(name, on);
}
