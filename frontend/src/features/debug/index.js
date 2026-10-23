/**
 * 调试面板功能模块入口。隐藏入口：个人主页连续点击 5 次（见 controller.js）。
 * 原版参考：legacy/game.js 812-824、4450-4830。
 */
import { createDebugController } from './controller.js';

/**
 * @param {{ store?: unknown, i18n: import('../../i18n/i18n.js').I18n, doc?: Document }} ctx
 * @returns {() => void} 卸载函数
 */
export function mount(ctx) {
  const ctrl = createDebugController({ i18n: ctx.i18n, doc: ctx.doc ?? document });
  return () => ctrl.destroy();
}
