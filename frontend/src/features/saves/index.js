/**
 * 存档模块入口：存档选择页（列表 / 开局 / 进入 / 重命名 / 删除）。
 * 原版参考：legacy/game.js 1248-1636。
 */
import { initSavesController } from './controller.js';

/** @param {{ doc?: Document }} [ctx] */
export function mount(ctx = {}) {
  return initSavesController(ctx.doc ?? document);
}
