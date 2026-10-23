/**
 * ============================================================
 * 功能模块注册表（feature registry）
 *
 * 新增功能：在下方 FEATURES 中追加一行，例如
 *   { name: 'auth', load: () => import('./auth/index.js') },
 * 约定见 ./README.md 与 ./CLAUDE.md。
 * ============================================================
 */

/**
 * @typedef {Object} FeatureContext
 * @property {{ get: () => object, set: (patch: object) => void, subscribe: (fn: Function) => () => void }} store 实际为 appStore（见 state/store.js）
 * @property {import('../i18n/i18n.js').I18n} i18n
 * @property {Document} doc
 */

/**
 * @typedef {Object} FeatureModule
 * @property {(ctx: FeatureContext) => (void | (() => void))} mount 挂载；可返回卸载函数
 */

/**
 * @typedef {Object} FeatureEntry
 * @property {string} name 模块名，与 features/<name>/ 目录一致
 * @property {() => Promise<FeatureModule>} load 动态导入，按需加载
 */

/** @type {FeatureEntry[]} 在此登记功能模块（当前为空：各功能逐步移植） */
// 自动发现：任何 features/<name>/index.js 都会被登记，无需手工修改本文件。
const modules = import.meta.glob('./*/index.js');
export const FEATURES = Object.entries(modules)
  .sort(([a], [b]) => a.localeCompare(b))
  .map(([path, load]) => ({ name: path.split('/')[1], load }));

/**
 * 依次挂载所有已登记的功能模块。单个模块失败不影响其它模块。
 * @param {FeatureContext} ctx
 * @returns {() => void} 卸载全部
 */
export function mountFeatures(ctx) {
  const disposers = [];
  for (const entry of FEATURES) {
    entry
      .load()
      .then((mod) => {
        const dispose = mod.mount(ctx);
        if (typeof dispose === 'function') disposers.push(dispose);
      })
      .catch((err) => {
        console.error(`[features] failed to mount "${entry.name}":`, err);
      });
  }
  return () => {
    while (disposers.length) disposers.pop()?.();
  };
}
