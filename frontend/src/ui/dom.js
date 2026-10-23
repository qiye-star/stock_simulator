/**
 * DOM 小工具。所有写入 HTML 的操作只接受 SafeHtml（来自 html``），
 * 这是项目唯一允许使用 innerHTML / template.innerHTML 的地方。
 */
import { isSafeHtml } from './html.js';

/**
 * @template {Element} [T=Element]
 * @param {string} selector
 * @param {ParentNode} [root=document]
 * @returns {T | null}
 */
export function $(selector, root = document) {
  return /** @type {T | null} */ (root.querySelector(selector));
}

/**
 * @template {Element} [T=Element]
 * @param {string} selector
 * @param {ParentNode} [root=document]
 * @returns {T[]}
 */
export function $$(selector, root = document) {
  return /** @type {T[]} */ (Array.from(root.querySelectorAll(selector)));
}

/**
 * 绑定事件，返回解绑函数。
 * @param {EventTarget} target
 * @param {string} type
 * @param {EventListenerOrEventListenerObject} handler
 * @param {AddEventListenerOptions | boolean} [options]
 * @returns {() => void}
 */
export function on(target, type, handler, options) {
  target.addEventListener(type, handler, options);
  return () => target.removeEventListener(type, handler, options);
}

/**
 * 事件委托：事件目标位于 root 内且命中 selector 时调用 handler(event, matchedEl)。
 * @param {EventTarget & ParentNode} root
 * @param {string} type
 * @param {string} selector
 * @param {(event: Event, el: Element) => void} handler
 * @returns {() => void} 解绑函数
 */
export function delegate(root, type, selector, handler) {
  return on(root, type, (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const el = target.closest(selector);
    if (el && root.contains?.(el)) handler(event, el);
  });
}

/**
 * 用安全标记替换元素的子节点。
 * @param {Element} el
 * @param {unknown} safe 必须是 html`` / raw() 的结果
 */
export function setHtml(el, safe) {
  assertSafe(safe);
  el.innerHTML = safe.value;
}

/**
 * 把安全标记解析为文档片段。
 * @param {unknown} safe 必须是 html`` / raw() 的结果
 * @returns {DocumentFragment}
 */
export function fragment(safe) {
  assertSafe(safe);
  const tpl = document.createElement('template');
  tpl.innerHTML = safe.value;
  return tpl.content;
}

/** @param {unknown} safe @returns {asserts safe is import('./html.js').SafeHtml} */
function assertSafe(safe) {
  if (!isSafeHtml(safe)) {
    throw new TypeError('Expected SafeHtml: use html`...` (or raw() for trusted markup)');
  }
}
