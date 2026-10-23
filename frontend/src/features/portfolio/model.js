/**
 * 持仓页纯逻辑（无 DOM、无 I/O，可在 node 下单测）。所有金额为整数分。
 * 原版参考：legacy/game.js updatePortfolio 3577-3766（P&L 公式与阈值保持一致）。
 */
import { formatMoney, formatPercent } from '../../ui/format.js';

/** @typedef {'zh-CN' | 'en-US'} Lang */

export { SELECT_STOCK_EVENT } from '../../state/events.js';

/**
 * @typedef {Object} HoldingIn 服务端 GET /saves/{id}/portfolio 的 HoldingOut（子集）
 * @property {string} code
 * @property {string} name
 * @property {number} quantity 股数
 * @property {number} sellable_quantity 可卖股数（T+1 已扣除）
 * @property {number} avg_price_cents 成本均价（分）
 * @property {number} total_cost_cents 总成本（分）
 * @property {number} market_price_cents 现价（分）
 */

/**
 * @typedef {Object} TradeIn 服务端 GET /saves/{id}/trades 的 TradeOut（子集）
 * @property {string} id
 * @property {number} seq
 * @property {string} code
 * @property {'buy' | 'sell'} side
 * @property {number} price_cents
 * @property {number} quantity
 * @property {number} gross_cents 成交金额（分，不含手续费）
 * @property {string} created_at ISO 8601 UTC
 */

/** @param {number} c 盈亏/金额（分） @returns {'up' | 'down'} 与 legacy 一致：>=0 为 up */
export function toneOf(c) {
  return c >= 0 ? 'up' : 'down';
}

/**
 * 单价（分）-> 元字符串，两位小数（与 legacy toFixed(2) 一致，不使用 万/亿 缩写）。
 * @param {number} cents
 */
export function formatUnitPrice(cents) {
  if (!Number.isInteger(cents)) throw new TypeError(`price must be integer cents, got ${cents}`);
  return (cents / 100).toFixed(2);
}

/**
 * 带符号金额：>=0 前加 "+"，负数前加 "-"，统一带 ¥ 前缀。
 * @param {number} cents
 * @param {Lang} [lang]
 */
export function signedMoney(cents, lang = 'zh-CN') {
  const abs = '¥' + formatMoney(Math.abs(cents), lang);
  return cents >= 0 ? '+' + abs : '-' + abs;
}

/** 持仓的估值价：服务端 market_price_cents（行情缺失时后端回落到成本价）。 @param {HoldingIn} h */
function valuationPrice(h) {
  return Number.isInteger(h.market_price_cents) ? h.market_price_cents : h.avg_price_cents;
}

/**
 * 单条持仓的展示模型。
 * @param {HoldingIn} h
 * @param {Map<string, string>} names 代码 -> 名称
 * @param {Lang} [lang]
 */
export function holdingRow(h, names = new Map(), lang = 'zh-CN') {
  const price = valuationPrice(h);
  const marketValue = price * h.quantity;
  const pnl = marketValue - h.total_cost_cents;
  const rate = h.total_cost_cents > 0 ? pnl / h.total_cost_cents : 0;
  return {
    code: h.code,
    name: names.get(h.code) ?? h.name ?? h.code,
    quantityText: String(h.quantity),
    avgText: formatUnitPrice(h.avg_price_cents),
    priceText: Number.isInteger(h.market_price_cents) ? formatUnitPrice(h.market_price_cents) : '--',
    marketValueText: '¥' + formatMoney(marketValue, lang),
    pnlText: signedMoney(pnl, lang),
    rateText: (pnl >= 0 ? '+' : '') + formatPercent(rate),
    tone: toneOf(pnl),
  };
}

/**
 * 账户摘要（总资产、市值、可用资金、浮动盈亏、总收益率）。
 * @param {{ cashCents: number, initialFundCents: number, holdings: HoldingIn[] }} input
 * @param {Lang} [lang]
 */
export function portfolioSummary({ cashCents, initialFundCents, holdings }, lang = 'zh-CN') {
  let stockValue = 0;
  let totalCost = 0;
  for (const h of holdings) {
    stockValue += valuationPrice(h) * h.quantity;
    totalCost += h.total_cost_cents;
  }
  const totalAssets = cashCents + stockValue;
  const floating = stockValue - totalCost;
  const ret = initialFundCents > 0 ? (totalAssets - initialFundCents) / initialFundCents : 0;
  return {
    totalAssetsText: '¥' + formatMoney(totalAssets, lang),
    stockValueText: '¥' + formatMoney(stockValue, lang),
    availableText: '¥' + formatMoney(cashCents, lang),
    floatingPnlText: signedMoney(floating, lang),
    floatingTone: toneOf(floating),
    totalReturnText: formatPercent(ret),
    totalReturnTone: toneOf(ret),
    values: { totalAssetsCents: totalAssets, stockValueCents: stockValue, floatingPnlCents: floating },
  };
}

/**
 * 成交记录单条展示模型（买 -> down 样式，卖 -> up 样式，与 legacy 一致）。
 * @param {TradeIn} t
 * @param {Map<string, string>} names
 * @param {Lang} [lang]
 */
export function tradeRow(t, names = new Map(), lang = 'zh-CN') {
  const date = new Date(t.created_at);
  const buy = t.side === 'buy';
  return {
    key: String(t.id ?? t.seq),
    timeText: Number.isNaN(date.getTime()) ? '--' : date.toLocaleString(lang),
    code: t.code,
    name: names.get(t.code) ?? t.code,
    sideKey: buy ? 'common.buy' : 'common.sell',
    tone: buy ? 'down' : 'up',
    priceText: formatUnitPrice(t.price_cents),
    quantityText: String(t.quantity),
    amountText: '¥' + formatMoney(Math.abs(t.gross_cents), lang),
  };
}

/**
 * 合并成交记录（按 id/seq 去重，seq 降序 = 最新在前）。用于轮询刷新首页与“加载更多”。
 * @param {TradeIn[]} existing
 * @param {TradeIn[]} incoming
 * @returns {TradeIn[]}
 */
export function mergeTrades(existing, incoming) {
  const byKey = new Map();
  for (const t of [...existing, ...incoming]) byKey.set(t.id ?? String(t.seq), t);
  return [...byKey.values()].sort((a, b) => (b.seq ?? 0) - (a.seq ?? 0));
}

/**
 * 归一化成交分页响应：{ items, next_cursor }。
 * @param {unknown} res
 * @returns {{ items: TradeIn[], nextCursor: string | null }}
 */
export function parseTradePage(res) {
  const obj = /** @type {Record<string, unknown>} */ (res && typeof res === 'object' ? res : {});
  const items = Array.isArray(obj.items) ? /** @type {TradeIn[]} */ (obj.items) : [];
  const cursor = typeof obj.next_cursor === 'string' && obj.next_cursor ? obj.next_cursor : null;
  return { items, nextCursor: cursor };
}

/**
 * 从 /saves/{id}/portfolio 响应读取 HoldingIn 列表（缺失时为空数组）。
 * @param {unknown} res
 * @returns {HoldingIn[]}
 */
export function parseHoldings(res) {
  const list = res && typeof res === 'object' ? /** @type {Record<string, unknown>} */ (res).holdings : null;
  return Array.isArray(list) ? /** @type {HoldingIn[]} */ (list) : [];
}
