/**
 * 自动交易纯逻辑（无 DOM、无 I/O）：表单 -> 请求体校验与映射、配置 <-> 表单、
 * 配置/事件/统计的视图模型。金额一律整数分；百分比为 float（2.5 = 2.5%），与后端 schemas/auto_trade.py 一致。
 * 原版参考：legacy/game.js 5021-5526（表单/校验）、5528-5641（启停）、6041-6100（统计与记录）。
 *
 * 请求体字段（AutoConfigIn，extra 字段会被后端 422 拒绝）：
 *   code, direction, condition_type, condition_operator, condition_value_cents, condition_percent,
 *   quantity, price_type, limit_price_cents, stop_loss_percent, take_profit_percent, max_trades, max_amount_cents
 */
import { errorI18nKey, ERROR_I18N_KEYS } from '../../i18n/errors.js';
import { formatMoney } from '../../ui/format.js';

/** @typedef {(key: string, params?: Record<string, string | number>) => string} TranslateFn */
/** @typedef {'zh-CN' | 'en-US'} Lang */

export const DIRECTIONS = Object.freeze(['buy', 'sell']);
export const CONDITION_TYPES = Object.freeze(['price', 'percentage', 'profit', 'time']);
export const OPERATORS = Object.freeze(['above', 'below', 'equal']);
export const PRICE_TYPES = Object.freeze(['market', 'limit']);
/** 百分比输入范围（百分数，后端 condition_percent 为 0-1000；止损 stop_loss_percent 为 0-100）。 */
export const PERCENT_MIN = 0;
export const PERCENT_MAX = 1000;
export const STOP_LOSS_MAX = 100;
/** 默认全局交易上限（legacy 100）。 */
export const DEFAULT_MAX_TOTAL_TRADES = 100;

export { SELECT_STOCK_EVENT } from '../../state/events.js';

const OPERATOR_KEYS = Object.freeze({
  above: 'auto.operatorAbove',
  below: 'auto.operatorBelow',
  equal: 'auto.operatorEqual',
});

const CONDITION_TEXT_KEYS = Object.freeze({
  price: 'auto.conditionTextPrice',
  percentage: 'auto.conditionTextPercentage',
  profit: 'auto.conditionTextProfit',
  time: 'auto.conditionTextTime',
});

/**
 * @typedef {Object} ConfigForm 表单原始输入（DOM 字符串）
 * @property {string} code
 * @property {string} direction
 * @property {string} conditionType
 * @property {string} operator
 * @property {string} conditionValue
 * @property {string} quantity
 * @property {string} priceType
 * @property {string} limitPrice
 * @property {string} stopLoss
 * @property {string} takeProfit
 * @property {string} maxTrades
 * @property {string} maxAmount
 */

/**
 * @typedef {Object} ValidationContext
 * @property {(code: string) => boolean} stockExists
 * @property {Array<Record<string, unknown>>} configs 已有配置（服务端形状）
 * @property {string | null} editingId 正在编辑的配置 id（排除自身做重复检查）
 * @property {TranslateFn} t
 */

/**
 * 输入框字符串 -> 数值。空串返回 null（未填），非法返回 NaN。
 * @param {unknown} str
 * @returns {number | null}
 */
export function parseNumeric(str) {
  const s = String(str ?? '').trim();
  if (s === '') return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : NaN;
}

/**
 * 元 -> 分。要求最多两位小数，否则返回 NaN（不做静默四舍五入）。
 * @param {number | null} yuan
 * @returns {number | null}
 */
export function yuanToCents(yuan) {
  return scaleExact(yuan, 100);
}

/**
 * 百分数是否至多两位小数（后端以 x100 整数存储）。null 视为未填（返回 null），非法返回 NaN。
 * @param {number | null} percent
 * @returns {number | null}
 */
export function percentPrecision(percent) {
  return scaleExact(percent, 100);
}

/** @param {number | null} n @param {number} factor */
function scaleExact(n, factor) {
  if (n === null) return null;
  if (!Number.isFinite(n)) return NaN;
  const scaled = Math.round(n * factor);
  return Math.abs(scaled - n * factor) < 1e-6 ? scaled : NaN;
}

/** 分 -> 输入框文本（"12.5"、"12"）。 @param {number} cents */
export function centsToText(cents) {
  return String(Number((cents / 100).toFixed(2)));
}

/** 百分数 -> 输入框文本（最多两位小数）。 @param {number} percent */
export function percentToText(percent) {
  return String(Number(percent.toFixed(2)));
}

/** @param {unknown} v @returns {boolean} */
function isPositiveInt(v) {
  return typeof v === 'number' && Number.isInteger(v) && v >= 1;
}

/**
 * 表单 -> 请求体。失败时返回已翻译的提示语（与 legacy alert 文案对应）。
 * @param {ConfigForm} form
 * @param {ValidationContext} ctx
 * @returns {{ ok: true, payload: Record<string, unknown> } | { ok: false, message: string }}
 */
export function buildConfigPayload(form, ctx) {
  const { t } = ctx;
  const fail = (key, params) => ({ ok: false, message: t(key, params) });
  const code = form.code.trim();
  const direction = form.direction;
  const conditionType = form.conditionType;
  const operator = form.operator;

  if (!code) return fail('auto.requireStockCode');
  if (!ctx.stockExists(code)) return fail('auto.stockNotExist');
  if (!DIRECTIONS.includes(direction)) return fail('error.VALIDATION_ERROR');

  const dup = ctx.configs.some(
    (c) => c.code === code && c.direction === direction && String(c.id) !== ctx.editingId,
  );
  if (dup) return fail('auto.duplicateConfig', { direction: t(direction === 'buy' ? 'auto.directionBuy' : 'auto.directionSell') });

  const quantity = parseNumeric(form.quantity);
  if (!isPositiveInt(quantity)) return fail('auto.invalidQuantity');

  if (!CONDITION_TYPES.includes(conditionType)) return fail('error.VALIDATION_ERROR');
  if (conditionType === 'profit' && direction !== 'sell') return fail('auto.profitOnlyForSell');

  const isTime = conditionType === 'time';
  /** @type {Record<string, unknown>} */
  const payload = {
    code,
    direction,
    condition_type: conditionType,
    // time 条件不允许 operator / 阈值（后端 _validate 会拒绝），其余条件必须带 operator
    condition_operator: isTime ? null : OPERATORS.includes(operator) ? operator : 'above',
    condition_value_cents: null,
    condition_percent: null,
    quantity,
    price_type: 'market',
    limit_price_cents: null,
    stop_loss_percent: null,
    take_profit_percent: null,
    max_trades: 0,
    max_amount_cents: null,
  };

  // 触发条件值：time 不需要；percentage 为涨跌幅（%，float）；price/profit 为元 -> 分
  if (!isTime) {
    const raw = parseNumeric(form.conditionValue);
    if (raw === null) return fail('auto.requireConditionValue');
    if (conditionType === 'percentage') {
      const precise = percentPrecision(raw);
      if (!Number.isFinite(precise) || raw < PERCENT_MIN || raw > PERCENT_MAX) return fail('auto.invalidPercent');
      payload.condition_percent = raw;
    } else {
      const cents = yuanToCents(raw);
      if (!Number.isInteger(cents) || cents <= 0) return fail('auto.invalidConditionValue');
      payload.condition_value_cents = cents;
    }
  }

  const priceType = form.priceType;
  if (!PRICE_TYPES.includes(priceType)) return fail('error.VALIDATION_ERROR');
  payload.price_type = priceType;
  if (priceType === 'limit') {
    const raw = parseNumeric(form.limitPrice);
    if (raw === null) return fail('auto.requireLimitPrice');
    const cents = yuanToCents(raw);
    if (!Number.isInteger(cents) || cents <= 0) return fail('auto.invalidLimitPrice');
    payload.limit_price_cents = cents;
  }

  // 风控（占持仓成本的百分比）：止损取绝对值（负号忽略）；0 或留空 = 不设置
  const stop = parseNumeric(form.stopLoss);
  if (stop !== null) {
    const precise = percentPrecision(stop);
    if (!Number.isFinite(precise) || Math.abs(stop) > STOP_LOSS_MAX) return fail('auto.invalidStopLoss');
    if (stop !== 0) payload.stop_loss_percent = Math.abs(stop);
  }

  const take = parseNumeric(form.takeProfit);
  if (take !== null) {
    const precise = percentPrecision(take);
    if (!Number.isFinite(precise) || take < 0 || take > PERCENT_MAX) return fail('auto.invalidTakeProfit');
    if (take > 0) payload.take_profit_percent = take;
  }

  const maxTrades = parseNumeric(form.maxTrades);
  if (maxTrades !== null) {
    if (!isPositiveInt(maxTrades)) return fail('auto.invalidMaxTrades');
    payload.max_trades = maxTrades;
  }

  const maxAmount = parseNumeric(form.maxAmount);
  if (maxAmount !== null) {
    const cents = yuanToCents(maxAmount);
    if (!Number.isInteger(cents) || cents <= 0) return fail('auto.invalidMaxAmount');
    payload.max_amount_cents = cents;
  }

  return { ok: true, payload };
}

/**
 * 全局交易上限输入校验。
 * @param {unknown} str
 * @returns {number | null} 合法整数（>=1）或 null
 */
export function parseMaxTotalTrades(str) {
  const n = parseNumeric(str);
  return isPositiveInt(n) ? /** @type {number} */ (n) : null;
}

/**
 * 服务端配置（AutoConfigOut）-> 表单字符串（编辑回填）。
 * @param {Record<string, any>} c
 * @returns {ConfigForm}
 */
export function configToForm(c) {
  const isPct = c.condition_type === 'percentage';
  let conditionValue = '';
  if (c.condition_type !== 'time') {
    if (isPct && typeof c.condition_percent === 'number') conditionValue = percentToText(c.condition_percent);
    else if (!isPct && Number.isInteger(c.condition_value_cents)) conditionValue = centsToText(c.condition_value_cents);
  }
  const optPercent = (v) => (typeof v === 'number' && v > 0 ? percentToText(v) : '');
  return {
    code: String(c.code ?? ''),
    direction: String(c.direction ?? 'buy'),
    conditionType: String(c.condition_type ?? 'price'),
    operator: String(c.condition_operator ?? 'above'),
    conditionValue,
    quantity: c.quantity ? String(c.quantity) : '',
    priceType: String(c.price_type ?? 'market'),
    limitPrice: Number.isInteger(c.limit_price_cents) ? centsToText(c.limit_price_cents) : '',
    stopLoss: optPercent(c.stop_loss_percent),
    takeProfit: optPercent(c.take_profit_percent),
    maxTrades: c.max_trades > 0 ? String(c.max_trades) : '',
    maxAmount: Number.isInteger(c.max_amount_cents) && c.max_amount_cents > 0 ? centsToText(c.max_amount_cents) : '',
  };
}

/**
 * 条件描述（与 legacy getConditionText 一致的拼接）。
 * @param {Record<string, any>} c
 * @param {TranslateFn} t
 */
export function conditionText(c, t) {
  if (c.condition_type === 'time') return t('auto.conditionTextTime');
  const opKey = OPERATOR_KEYS[c.condition_operator];
  const typeKey = CONDITION_TEXT_KEYS[c.condition_type];
  if (!opKey || !typeKey) {
    return t('auto.conditionUnknown', { value: String(c.condition_value_cents ?? c.condition_percent ?? 0) });
  }
  if (c.condition_type === 'percentage') {
    return `${t(typeKey)}${t(opKey)}${percentToText(c.condition_percent ?? 0)}%`;
  }
  return `${t(typeKey)}${t(opKey)}${centsToText(c.condition_value_cents ?? 0)}${t('auto.unitYuan')}`;
}

/**
 * 配置列表行视图模型。
 * @param {Record<string, any>} c
 * @param {Map<string, string>} names
 * @param {TranslateFn} t
 */
export function configRow(c, names, t) {
  const code = String(c.code ?? '');
  const direction = c.direction === 'sell' ? 'sell' : 'buy';
  return {
    id: String(c.id),
    code,
    name: names.get(code) ?? String(c.name ?? code),
    direction,
    dirText: t(direction === 'buy' ? 'auto.directionBuy' : 'auto.directionSell'),
    conditionText: conditionText(c, t),
    quantityText: String(c.quantity ?? ''),
    priceTypeText: t(c.price_type === 'limit' ? 'auto.limitPriceLabel' : 'auto.marketPriceLabel'),
  };
}

/**
 * 按 reason_code 取文案 key（渲染时翻译，不存译文）。
 * @param {string | null | undefined} code
 * @returns {string}
 */
export function reasonKey(code) {
  if (!code) return ERROR_I18N_KEYS.UNKNOWN;
  return errorI18nKey(code);
}

/**
 * 状态徽标：运行 / 暂停 / 达上限 / 未启动。
 * @param {{ enabled: boolean, paused: boolean } | null} status AutoStatusOut（GET /auto-trade/status）
 * @param {number} remaining 全局剩余额度
 * @returns {{ key: string, tone: string, enabled: boolean, paused: boolean }}
 */
export function statusOf(status, remaining) {
  const enabled = Boolean(status?.enabled);
  const paused = Boolean(status?.paused);
  if (enabled && paused) return { key: 'auto.statusPaused', tone: 'paused', enabled, paused };
  if (enabled && remaining <= 0) return { key: 'auto.statusLimitReached', tone: 'limit', enabled, paused };
  if (enabled) return { key: 'auto.statusRunning', tone: 'running', enabled, paused };
  return { key: 'auto.statusStopped', tone: '', enabled, paused };
}

/**
 * AutoStatusOut -> 统计三元组（成交次数、成功、失败、累计盈亏）。
 * @param {Record<string, any> | null} status
 * @returns {{ total: number, success: number, failed: number, pnlCents: number, maxTotal: number }}
 */
export function readStats(status) {
  const pick = (k) => (Number.isFinite(status?.[k]) ? Number(status?.[k]) : 0);
  return {
    total: pick('total_trades'),
    success: pick('success_trades'),
    failed: pick('failed_trades'),
    pnlCents: pick('total_pnl_cents'),
    maxTotal: Number.isInteger(status?.max_total_trades) ? status?.max_total_trades : DEFAULT_MAX_TOTAL_TRADES,
  };
}

/**
 * 统计卡片视图模型。全局上限只计成功成交（domain 约定），剩余额度 = 上限 - 成功次数。
 * @param {{ total: number, success: number, failed: number, pnlCents: number }} stats
 * @param {number} maxTotal
 * @param {Lang} lang
 */
export function statsView(stats, maxTotal, lang = 'zh-CN') {
  const remaining = Math.max(0, maxTotal - stats.success);
  const pnl = stats.pnlCents;
  return {
    totalText: String(stats.total),
    successText: String(stats.success),
    failedText: String(stats.failed),
    pnlText: `${pnl >= 0 ? '+' : '-'}¥${formatMoney(Math.abs(pnl), lang)}`,
    pnlTone: pnl >= 0 ? 'up' : 'down',
    remaining,
    remainingText: `${remaining} / ${maxTotal}`,
  };
}

/**
 * 事件列表响应归一化：支持数组或 { items }。
 * @param {unknown} res
 * @returns {Array<Record<string, any>>}
 */
export function parseEvents(res) {
  if (Array.isArray(res)) return res;
  const items = res && typeof res === 'object' ? /** @type {any} */ (res).items : null;
  return Array.isArray(items) ? items : [];
}

/**
 * 事件行视图模型。成功写“买入/卖出成功”，失败按 reason_code 在渲染时翻译。
 * @param {Record<string, any>} e
 * @param {Map<string, string>} names
 * @param {TranslateFn} t
 * @param {Lang} lang
 */
export function eventRow(e, names, t, lang = 'zh-CN') {
  const date = new Date(e.created_at);
  const code = String(e.stock_code ?? '');
  const success = Boolean(e.success);
  const direction = e.direction === 'sell' ? 'sell' : 'buy';
  const detail = success
    ? t(direction === 'buy' ? 'auto.buySuccess' : 'auto.sellSuccess')
    : t(reasonKey(e.reason_code));
  const pnl = Number.isInteger(e.pnl_cents) ? e.pnl_cents : 0;
  const typeKey = CONDITION_TEXT_KEYS[e.condition_type];
  return {
    key: String(e.id ?? `${e.created_at}-${code}-${e.tick ?? ''}`),
    timeText: Number.isNaN(date.getTime()) ? '--' : date.toLocaleString(lang),
    name: names.get(code) ?? code,
    code,
    detail,
    success,
    successClass: success ? 'success' : 'failed',
    statusText: t(success ? 'common.statusSuccess' : 'common.statusFailed'),
    triggerText: typeKey ? `${t('auto.conditionTriggerLabel')}: ${t(typeKey)}` : '',
    amountText: pnl !== 0 ? `${pnl > 0 ? '+' : '-'}¥${formatMoney(Math.abs(pnl), lang)}` : '--',
    tone: pnl >= 0 ? 'up' : 'down',
  };
}

/**
 * 按比例计算下单数量（整手）。卖出按持仓，买入按可用资金 / 现价。
 * @param {{ direction: string, ratio: number, holdingQty: number, cashCents: number, priceCents: number | null, unit: number }} p
 * @returns {number} 0 表示无法计算
 */
export function ratioQuantity({ direction, ratio, holdingQty, cashCents, priceCents, unit }) {
  const u = unit > 0 ? unit : 1;
  let max;
  if (direction === 'sell') {
    max = holdingQty > 0 ? holdingQty : 0;
  } else {
    if (!(priceCents && priceCents > 0)) return 0;
    max = Math.floor(cashCents / priceCents / u) * u;
  }
  return Math.floor((max * ratio) / u) * u;
}

/**
 * 从行情响应读取现价（分）。约定字段 price_cents；缺失返回 null。
 * @param {unknown} market
 * @returns {number | null}
 */
export function priceFromMarket(market) {
  const v = market && typeof market === 'object' ? /** @type {any} */ (market).price_cents : undefined;
  return Number.isInteger(v) ? v : null;
}

/**
 * 按“买入/卖出”切换可选触发条件：买入时禁用盈利目标。
 * @param {string} direction
 * @returns {{ profitDisabled: boolean }}
 */
export function directionRules(direction) {
  return { profitDisabled: direction !== 'sell' };
}
