/**
 * 持仓页功能模块入口（自动发现：features/<name>/index.js 导出 mount）。
 * 原版参考：legacy/game.js 3577-3766（updatePortfolio）、3606-3633 右键菜单、6156 全局禁用不移植。
 */
import { createPortfolioController } from './controller.js';

export const PAGE_ID = 'portfolio-page';

/**
 * @param {{ store?: unknown, i18n: import('../../i18n/i18n.js').I18n, doc?: Document }} ctx
 * @returns {() => void} 卸载函数
 */
export function mount(ctx) {
  const doc = ctx.doc ?? document;
  const page = doc.getElementById(PAGE_ID);
  if (!page) return undefined;
  const ctrl = createPortfolioController({ page, i18n: ctx.i18n, doc });
  return () => ctrl.destroy();
}
