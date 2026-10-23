/**
 * 持仓页渲染（只返回 html``，不触碰 DOM；写入由 controller 经 ui/dom.js setHtml 完成）。
 * 所有用户数据（股票名、代码）经 html`` 默认转义。
 */
import { html } from '../../ui/html.js';

/**
 * @typedef {ReturnType<typeof import('./model.js').holdingRow>} HoldingVM
 * @typedef {ReturnType<typeof import('./model.js').tradeRow>} TradeVM
 */

/**
 * @param {HoldingVM[]} rows
 * @param {string} emptyText
 */
export function renderHoldingRows(rows, emptyText) {
  if (rows.length === 0) {
    return html`<tr><td colspan="7" style="text-align:center;padding:30px;">${emptyText}</td></tr>`;
  }
  const body = rows.map(
    (r) => html`<tr data-code="${r.code}" style="cursor: pointer;">
      <td>${r.name}<br><small>${r.code}</small></td>
      <td>${r.quantityText}</td>
      <td>¥${r.avgText}</td>
      <td>¥${r.priceText}</td>
      <td>${r.marketValueText}</td>
      <td class="${r.tone}">${r.pnlText}</td>
      <td class="${r.tone}">${r.rateText}</td>
    </tr>`,
  );
  return html`${body}`;
}

/**
 * @param {TradeVM[]} rows
 * @param {string} emptyText
 */
export function renderTradeRows(rows, emptyText) {
  if (rows.length === 0) {
    return html`<tr><td colspan="6" style="text-align:center;padding:30px;">${emptyText}</td></tr>`;
  }
  const body = rows.map(
    (r) => html`<tr>
      <td>${r.timeText}</td>
      <td>${r.name}<br><small>${r.code}</small></td>
      <td class="${r.tone}">${r.sideText}</td>
      <td>¥${r.priceText}</td>
      <td>${r.quantityText}</td>
      <td>${r.amountText}</td>
    </tr>`,
  );
  return html`${body}`;
}

/**
 * 成交记录底部：加载中 / 加载更多按钮 / 已全部加载。
 * @param {{ loading: boolean, hasMore: boolean, hasRows: boolean, moreText: string, allLoadedText: string, loadingText: string }} s
 */
export function renderRecordsFooter(s) {
  if (s.loading) return html`<p class="records-footer">${s.loadingText}</p>`;
  if (s.hasMore) {
    return html`<div class="records-footer"><button id="trade-records-more" class="btn-secondary btn-small">${s.moreText}</button></div>`;
  }
  if (s.hasRows) return html`<p class="records-footer">${s.allLoadedText}</p>`;
  return html``;
}

/**
 * 持仓行右键菜单（浮层，挂在 body 下；由 controller 定位与关闭）。
 * @param {string} code
 * @param {{ trade: string, autoTrade: string, viewDetail: string }} labels
 */
export function renderContextMenu(code, labels) {
  return html`<div class="context-menu" role="menu" data-code="${code}">
    <div class="context-menu-item" role="menuitem" data-action="trade" data-code="${code}">${labels.trade}</div>
    <div class="context-menu-item" role="menuitem" data-action="auto-trade" data-code="${code}">${labels.autoTrade}</div>
    <div class="context-menu-item" role="menuitem" data-action="view-detail" data-code="${code}">${labels.viewDetail}</div>
  </div>`;
}
