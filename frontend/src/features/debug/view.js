/**
 * 调试面板渲染（只返回 html``；写入由 controller 经 setHtml 完成）。
 */
import { html } from '../../ui/html.js';

/** @param {Array<{ value: string, label: string }>} options */
export function renderAchievementOptions(options) {
  return html`${options.map((o) => html`<option value="${o.value}">${o.label}</option>`)}`;
}

/**
 * 取消解锁的多选列表（替代 legacy 的临时弹窗）。
 * @param {Array<{ value: string, label: string }>} rows
 * @param {string} confirmText
 */
export function renderClearList(rows, confirmText) {
  return html`<div id="debug-clear-list" class="debug-clear-list">
    ${rows.map(
      (r) => html`<label class="debug-check"><input type="checkbox" name="debug-clear-ach" value="${r.value}"> ${r.label}</label>`,
    )}
    <button id="debug-clear-selected-confirm" class="btn-danger btn-small">${confirmText}</button>
  </div>`;
}

/**
 * 面板顶部提示（DEBUG_DISABLED / 无存档）。text 为空时输出空标记。
 * @param {string | null} text
 */
export function renderNotice(text) {
  if (!text) return html`<p id="debug-notice" class="debug-notice" hidden></p>`;
  return html`<p id="debug-notice" class="debug-notice warning-text" role="status">${text}</p>`;
}
