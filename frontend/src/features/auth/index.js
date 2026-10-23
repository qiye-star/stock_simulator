/**
 * 认证模块入口：绑定登录 / 注册 / 登出 / 注销 / 修改密码，绑定主导航，并尝试恢复会话。
 * 视图与校验见 ./view.js、./validators.js；流程见 ./controller.js。
 * 原版参考：legacy/game.js 998-1245、2424-2513；主导航切换见 state/session.js bindMainNav。
 */
import { bindMainNav } from '../../state/session.js';
import { initAuthController, restoreSession } from './controller.js';

/** @param {{ doc?: Document }} [ctx] */
export function mount(ctx = {}) {
  const doc = ctx.doc ?? document;
  const offAuth = initAuthController(doc);
  const offNav = bindMainNav(doc);
  // 启动时探测已有会话（异步，不阻塞其它模块挂载）
  restoreSession(doc);
  return () => {
    offAuth();
    offNav();
  };
}
