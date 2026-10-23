/**
 * 交易纯逻辑（无 DOM / 网络，可单测）。所有金额为整数分；费率为十进制字符串，用 BigInt 精确计算。
 *
 * 规则来源：docs/CONTRACT.md「领域规则」；手续费先单独四舍五入到分（半数向上）。
 * 移植参考：legacy/game.js updateTradeEstimate 3140-3160、setTradeQuantity 3163-3180。
 *
 * @typedef {'buy' | 'sell'} Side
 * @typedef {{ key: string, params?: Record<string, string | number> }} Problem
 */

/** 价格偏离需确认时后端返回的错误码（不在 ErrorCode 枚举内，前端单独识别）。 */
export const DEVIATION_CODE = 'TRADE_PRICE_DEVIATION_CONFIRM';

/** 快捷比例（同 legacy 1/4、1/2、全仓）。 */
export const RATIOS = Object.freeze({ quarter: 0.25, half: 0.5, full: 1 });

/**
 * 严格解析元为分（最多两位小数）。非法输入返回 null。
 * @param {unknown} text
 * @returns {number | null}
 */
export function parseYuanToCents(text) {
  const m = /^(\d+)(?:\.(\d{1,2}))?$/.exec(String(text ?? '').trim());
  if (!m) return null;
  return Number(m[1]) * 100 + Number((m[2] ?? '').padEnd(2, '0'));
}

/**
 * 解析股数（正整数）。非法返回 null。
 * @param {unknown} text
 * @returns {number | null}
 */
export function parseQuantity(text) {
  const s = String(text ?? '').trim();
  if (!/^\d+$/.test(s)) return null;
  const n = Number(s);
  return Number.isSafeInteger(n) ? n : null;
}

/**
 * 十进制费率字符串 -> 分数（BigInt）。非法输入视为 0。
 * @param {string} rate
 * @returns {{ num: bigint, den: bigint }}
 */
export function rateFraction(rate) {
  const m = /^(\d+)(?:\.(\d+))?$/.exec(String(rate ?? '').trim());
  if (!m) return { num: 0n, den: 1n };
  const frac = m[2] ?? '';
  return { num: BigInt(m[1] + frac), den: 10n ** BigInt(frac.length) };
}

/**
 * 手续费（分）= round_half_up(amount * rate)。
 * @param {number} amountCents 非负整数分
 * @param {string} rate
 * @returns {number}
 */
export function feeCents(amountCents, rate) {
  const { num, den } = rateFraction(rate);
  const n = BigInt(amountCents) * num;
  return Number((2n * n + den) / (2n * den));
}

/**
 * 预估金额：买入 = 金额 + 手续费；卖出 = 金额 - 手续费。
 * @param {{ side: Side, priceCents: number, quantity: number, buyRate: string, sellRate: string }} input
 * @returns {{ amount_cents: number, fee_cents: number, total_cents: number }}
 */
export function estimateOrder({ side, priceCents, quantity, buyRate, sellRate }) {
  const amount = priceCents * quantity;
  const fee = feeCents(amount, side === 'buy' ? buyRate : sellRate);
  const total = side === 'buy' ? amount + fee : amount - fee;
  return { amount_cents: amount, fee_cents: fee, total_cents: total };
}

/**
 * 在现金允许范围内的最大买入股数（含手续费，按交易单位向下取整）。
 * @param {{ cashCents: number, priceCents: number, unit: number, buyRate: string }} input
 * @returns {number}
 */
export function maxBuyQuantity({ cashCents, priceCents, unit, buyRate }) {
  if (priceCents <= 0 || cashCents <= 0 || unit <= 0) return 0;
  let q = Math.floor(cashCents / priceCents / unit) * unit;
  while (q > 0) {
    const total = estimateOrder({ side: 'buy', priceCents, quantity: q, buyRate, sellRate: buyRate }).total_cents;
    if (total <= cashCents) break;
    q -= unit;
  }
  return Math.max(0, q);
}

/**
 * 比例下单量：floor(max * ratio / unit) * unit。
 * @param {number} maxQty
 * @param {number} ratio
 * @param {number} unit
 */
export function ratioQuantity(maxQty, ratio, unit) {
  return Math.max(0, Math.floor((maxQty * ratio) / unit) * unit);
}

/**
 * 当前可卖股数（T+1 已由后端扣除当日买入；T+0 模式下即持仓）。
 * @param {{ holdings: { code: string, sellable_quantity: number }[] } | null} account
 * @param {string} code
 */
export function sellableOf(account, code) {
  return account?.holdings.find((h) => h.code === code)?.sellable_quantity ?? 0;
}

/**
 * 下单前的本地校验（价格范围、涨跌停由后端裁决）。
 * @param {{ quantity: number | null, priceCents: number | null, unit: number }} input
 * @returns {Problem | null}
 */
export function validateOrder({ quantity, priceCents, unit }) {
  if (priceCents === null || priceCents <= 0) return { key: 'trade.invalidPrice' };
  if (quantity === null || quantity <= 0) return { key: 'trade.invalidQuantity' };
  if (quantity % unit !== 0) return { key: 'trade.invalidQuantityUnit', params: { unit } };
  return null;
}

/**
 * 构造 POST /saves/{id}/orders 请求体。价格未被用户改动时视为市价单（跟随行情），
 * 用户手动输入过价格则为限价单。
 * @param {{ code: string, side: Side, quantity: number, priceCents: number | null, priceDirty: boolean }} input
 * @returns {import('../../api/endpoints.js').OrderIn}
 */
export function buildOrderBody({ code, side, quantity, priceCents, priceDirty }) {
  if (priceDirty && priceCents !== null) {
    return { code, side, quantity, price_type: 'limit', limit_price_cents: priceCents };
  }
  return { code, side, quantity, price_type: 'market' };
}

/**
 * @param {unknown} err
 * @returns {boolean}
 */
export function isDeviationConfirm(err) {
  return /** @type {any} */ (err)?.code === DEVIATION_CODE;
}
