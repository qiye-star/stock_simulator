/**
 * 自动交易功能模块入口（自动发现：导出 mount）。
 * 原版参考：legacy/game.js 5021-5641（表单、启停）、6041-6100（统计与记录）。
 */
import { createAutoTradeController } from './controller.js';

export const PAGE_ID = 'auto-trade-page';

/**
 * @param {{ store?: unknown, i18n: import('../../i18n/i18n.js').I18n, doc?: Document }} ctx
 * @returns {() => void} 卸载函数
 */
export function mount(ctx) {
  const doc = ctx.doc ?? document;
  const page = doc.getElementById(PAGE_ID);
  if (!page) return undefined;
  const ctrl = createAutoTradeController({ page, i18n: ctx.i18n, doc });
  return () => ctrl.destroy();
}
