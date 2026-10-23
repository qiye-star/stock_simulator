/**
 * 自动交易渲染（只返回 html``；写入由 controller 经 ui/dom.js setHtml 完成）。
 * 所有配置字段（股票名、条件文案）均经默认转义。
 */
import { html } from '../../ui/html.js';

/**
 * @param {ReturnType<typeof import('./model.js').configRow>[]} rows
 * @param {{ emptyText: string, quantityLabel: string, editText: string, deleteText: string }} labels
 */
export function renderConfigList(rows, labels) {
  if (rows.length === 0) return html`<p class="empty-tip">${labels.emptyText}</p>`;
  const body = rows.map(
    (r) => html`<div class="auto-trade-stock-item ${r.direction}" data-id="${r.id}">
      <div class="auto-trade-stock-info">
        <div class="stock-code">${r.name} (${r.code}) - ${r.dirText}</div>
        <div class="stock-condition">${r.conditionText} | ${labels.quantityLabel}: ${r.quantityText} | ${r.priceTypeText}</div>
      </div>
      <div class="auto-trade-stock-actions">
        <button class="btn-edit" data-action="edit" data-id="${r.id}">${labels.editText}</button>
        <button class="btn-delete" data-action="delete" data-id="${r.id}">${labels.deleteText}</button>
      </div>
    </div>`,
  );
  return html`${body}`;
}

/**
 * @param {ReturnType<typeof import('./model.js').eventRow>[]} rows
 * @param {string} emptyText
 */
export function renderEventList(rows, emptyText) {
  if (rows.length === 0) {
    return html`<p style="text-align:center;color:var(--text-secondary);padding:20px;">${emptyText}</p>`;
  }
  const body = rows.map(
    (r) => html`<div class="record-item ${r.successClass}">
      <div class="record-info">
        <div class="time">${r.timeText}</div>
        <div class="details">${r.detail}</div>
        <div class="stock-info">${r.name} (${r.code})</div>
        ${r.triggerText ? html`<div class="condition-info">${r.triggerText}</div>` : null}
      </div>
      <div class="record-result">
        <div class="amount ${r.tone}">${r.amountText}</div>
        <div class="status">${r.statusText}</div>
      </div>
    </div>`,
  );
  return html`${body}`;
}

/** 买入时的盈利目标提示（沿用 legacy #profit-tip）。 @param {string} text */
export function renderProfitTip(text) {
  return html`<div id="profit-tip" class="form-tip">${text}</div>`;
}
