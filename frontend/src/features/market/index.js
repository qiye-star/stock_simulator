/**
 * 行情功能入口：股票列表、游戏时钟与暂停/跳过、存档会话绑定（行情连接的唯一所有者）。
 *
 * 其它模块（chart / trade / watchlist）只读写 ./store.js 的 marketStore，不建立连接。
 */
import { initStockList } from './view.js';
import { initClock } from './clock.js';
import { bindSession, loadStockList, selectStock, teardown } from './controller.js';
import { notifyError } from './notify.js';
import { SELECT_STOCK_EVENT } from '../../state/events.js';

/**
 * @param {import('../index.js').FeatureContext} ctx
 * @returns {() => void}
 */
export function mount(ctx) {
  // 跨功能选股意图（持仓右键菜单）：target 为 market 时选中该股票并刷新详情
  const onSelect = (/** @type {Event} */ e) => {
    const detail = /** @type {CustomEvent} */ (e).detail;
    if (detail && detail.target === 'market' && typeof detail.code === 'string') selectStock(detail.code);
  };
  window.addEventListener(SELECT_STOCK_EVENT, onSelect);
  const disposers = [initStockList(ctx), initClock(ctx), bindSession(), () => window.removeEventListener(SELECT_STOCK_EVENT, onSelect)];
  loadStockList().catch((err) => notifyError(err));
  return () => {
    for (const dispose of disposers) dispose();
    teardown();
  };
}
