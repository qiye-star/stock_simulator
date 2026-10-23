/**
 * 设置模块入口：设置面板（主题 / 刷新速度 / 语言 / 时间控制）与主题切换按钮。
 * 开局参数（手续费、T+0、交易单位）属于存档创建，见 features/saves。
 * 原版参考：legacy/game.js 4428-4447（setTheme/toggleTheme）、709-730（设置事件）。
 */
import { initSettingsController } from './controller.js';

/** @param {{ doc?: Document }} [ctx] */
export function mount(ctx = {}) {
  return initSettingsController(ctx.doc ?? document);
}
