/**
 * 个人页模块入口：用户信息、统计、成就墙（GET /achievements/catalog 与 /saves/{id}/achievements），
 * 以及导出 / 开局 / 切换存档按钮。修改密码、退出、注销由 features/auth 绑定。
 * 原版参考：legacy/game.js 3768-3864。
 */
import { initProfileController } from './controller.js';

/** @param {{ doc?: Document }} [ctx] */
export function mount(ctx = {}) {
  return initProfileController(ctx.doc ?? document);
}
