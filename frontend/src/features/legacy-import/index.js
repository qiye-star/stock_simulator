/**
 * 旧版存档导入模块入口：检测 localStorage 中的旧版数据并提供一键上传；
 * 个人页「导入存档」按钮选择 .txt 文件上传。接口：POST /import/legacy {content}。
 * 原版参考：legacy/game.js importSave 4851-4935。
 */
import { initLegacyImportController } from './controller.js';

/** @param {{ doc?: Document }} [ctx] */
export function mount(ctx = {}) {
  return initLegacyImportController(ctx.doc ?? document);
}
