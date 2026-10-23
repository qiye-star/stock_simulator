/**
 * 交易功能入口：股票详情报价区（五档、涨跌停）+ 买卖表单 + 快捷买卖入口。
 * 拥有：#stock-detail 的报价文字区、#buy-xx 与 #sell-xx、#confirm-buy-btn、#confirm-sell-btn、
 *       .trade-tab、#quick-buy-btn、#quick-sell-btn。
 * 图表见 ../chart，自选按钮见 ../watchlist，持仓列表归 portfolio 模块。
 */
import { marketStore } from '../market/store.js';
import { initDetailView } from './detailView.js';
import { initTradeForms } from './form.js';
import { on } from '../../ui/dom.js';
import { showTab } from '../../state/session.js';
import { SELECT_STOCK_EVENT } from '../../state/events.js';

/**
 * @param {import('../index.js').FeatureContext} ctx
 * @returns {() => void}
 */
export function mount(ctx) {
  const doc = document;
  const forms = initTradeForms(ctx, doc);
  const offDetail = initDetailView(doc);

  /** @param {'buy' | 'sell'} side */
  const openSide = (side) => {
    const code = marketStore.get().selectedCode;
    if (!code) return;
    forms.setCode(code);
    forms.setActive(side);
    showTab('trade', doc);
  };

  // 跨功能选股意图（持仓右键“交易”）：填入代码；切页由派发方 showTab 完成
  const onSelect = (/** @type {Event} */ e) => {
    const detail = /** @type {CustomEvent} */ (e).detail;
    if (detail && detail.target === 'trade' && typeof detail.code === 'string') forms.setCode(detail.code);
  };
  window.addEventListener(SELECT_STOCK_EVENT, onSelect);

  const buyBtn = doc.getElementById('quick-buy-btn');
  const sellBtn = doc.getElementById('quick-sell-btn');
  const offBuy = buyBtn ? on(buyBtn, 'click', () => openSide('buy')) : () => {};
  const offSell = sellBtn ? on(sellBtn, 'click', () => openSide('sell')) : () => {};

  return () => {
    window.removeEventListener(SELECT_STOCK_EVENT, onSelect);
    offBuy();
    offSell();
    offDetail();
    forms.dispose();
  };
}
