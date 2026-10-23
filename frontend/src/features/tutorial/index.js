/**
 * 新手引导模块入口：主界面首次进入时自动开始，完成 / 跳过后写回 tutorial_completed。
 * 步骤与定位见 ./steps.js。原版参考：legacy/game.js 4256-4425。
 */
import { initTutorialController } from './controller.js';

/** @param {{ doc?: Document }} [ctx] */
export function mount(ctx = {}) {
  return initTutorialController(ctx.doc ?? document);
}
