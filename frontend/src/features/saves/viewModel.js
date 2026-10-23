/**
 * 存档列表的视图模型（纯函数）。金额为整数分，显示时经 formatMoney 转换。
 * 字段名沿用服务端 snake_case；缺失字段时给出安全回退，不抛错。
 */

/**
 * @typedef {Object} SaveCard
 * @property {string} id
 * @property {string} name
 * @property {string} info 「资金: ¥x | 创建于 y」
 */

/**
 * @param {Record<string, unknown>} save 服务端 SaveOut
 * @param {number} index 列表下标（用于默认名 "存档 N"）
 * @param {{ lang: 'zh-CN' | 'en-US', t: (key: string, params?: Record<string, string | number>) => string, formatMoney: (cents: number, lang: string) => string }} env
 * @returns {SaveCard}
 */
export function toSaveCard(save, index, { lang, t, formatMoney }) {
  const rawName = typeof save.name === 'string' ? save.name.trim() : '';
  const name = rawName || t('save.defaultName', { index: index + 1 });

  const cents = Number.isInteger(save.cash_cents) ? save.cash_cents : save.initial_fund_cents;
  const fund = Number.isInteger(cents) ? formatMoney(/** @type {number} */ (cents), lang) : '--';

  const created = typeof save.created_at === 'string' ? new Date(save.created_at) : null;
  const date = created && !Number.isNaN(created.getTime()) ? created.toLocaleDateString(lang) : '--';

  return {
    id: String(save.id ?? ''),
    name,
    info: t('save.info', { fund, date }),
  };
}

/**
 * @param {unknown} list 服务端返回的数组
 * @returns {Record<string, unknown>[]} 过滤掉非对象项
 */
export function normalizeSaveList(list) {
  if (!Array.isArray(list)) return [];
  return list.filter((s) => s && typeof s === 'object' && typeof s.id === 'string');
}
