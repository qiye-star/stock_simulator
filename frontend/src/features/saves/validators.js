/**
 * 存档相关的纯函数：名称校验、开局表单 -> 请求体（金额整数分、费率字符串）。
 * 无 DOM、无 I/O，可单测。移植自 legacy/game.js startGame 1322-1386、renameSave 1592-1636。
 *
 * 费率：页面输入为百分比（0.03 表示 0.03%），服务端为 Numeric(8,6) 小数比例，
 * 以字符串传输（如 "0.000300"），用整数运算完成换算，避免浮点误差。
 */

export const SAVE_NAME_MAX_LEN = 20;

/** 与 legacy 重命名校验一致：中英文、数字、空白与常用标点。 */
export const SAVE_NAME_PATTERN = /^[\u4e00-\u9fa5a-zA-Z0-9\s\-_\.，。！？、：""''（）【】]+$/;

export const FUND_MIN_WAN = 10;
export const FUND_MAX_WAN = 10000;
/** 随机开局资金区间（万元），与 legacy floor(rand*150+50) 一致。 */
export const RANDOM_FUND_MIN_WAN = 50;
export const RANDOM_FUND_SPAN_WAN = 150;
/** 1 万元 = 10^4 元 = 10^6 分。 */
export const CENTS_PER_WAN = 1_000_000;

/**
 * @param {string} raw 用户输入（已 trim 前的原始值）
 * @returns {{ name: string } | { error: string }} error 为 i18n key
 */
export function validateSaveName(raw) {
  const name = String(raw ?? '').trim();
  if (!name) return { error: 'rename.error.empty' };
  if (name.length < 1 || name.length > SAVE_NAME_MAX_LEN) return { error: 'rename.error.length' };
  if (!SAVE_NAME_PATTERN.test(name)) return { error: 'rename.error.invalid' };
  return { name };
}

/**
 * 随机开局资金（分）。rand 可注入以便测试。
 * @param {() => number} [rand=Math.random]
 * @returns {number}
 */
export function randomFundCents(rand = Math.random) {
  const wan = Math.floor(rand() * RANDOM_FUND_SPAN_WAN) + RANDOM_FUND_MIN_WAN;
  return wan * CENTS_PER_WAN;
}

/**
 * 自定义资金（万元，允许小数）-> 整数分。越界或非法返回 null。
 * @param {string | number} raw
 * @returns {number | null}
 */
export function parseCustomFundCents(raw) {
  const wan = typeof raw === 'number' ? raw : Number.parseFloat(String(raw).trim());
  if (!Number.isFinite(wan) || wan < FUND_MIN_WAN || wan > FUND_MAX_WAN) return null;
  return Math.round(wan * CENTS_PER_WAN);
}

/**
 * 百分比输入（如 "0.03"）-> 小数比例字符串（"0.000300"）。越界返回 null。
 * 允许 0 ~ 1（即 0% ~ 1%），与 legacy 输入框 min=0 max=1 一致。
 * @param {string | number} raw
 * @returns {string | null}
 */
export function percentToRateString(raw) {
  const pct = typeof raw === 'number' ? raw : Number.parseFloat(String(raw).trim());
  if (!Number.isFinite(pct) || pct < 0 || pct > 1) return null;
  // 比例的 1e-6 单位整数：pct% = pct/100 = pct*1e4 * 1e-6
  const units = Math.round(pct * 1e4);
  const digits = String(units).padStart(7, '0');
  return `${digits.slice(0, -6)}.${digits.slice(-6)}`;
}

/**
 * @typedef {Object} NewGameForm
 * @property {'random' | 'custom'} fundType
 * @property {string} customWan
 * @property {string} buyFeePct
 * @property {string} sellFeePct
 * @property {boolean} t0Mode
 * @property {1 | 100} tradeUnit
 */

/**
 * 开局表单 -> POST /saves 请求体。
 * @param {NewGameForm} form
 * @param {() => number} [rand]
 * @returns {{ body: Record<string, unknown> } | { error: string }} error 为 i18n key
 */
export function buildCreateSaveRequest(form, rand = Math.random) {
  let fund;
  if (form.fundType === 'random') {
    fund = randomFundCents(rand);
  } else {
    fund = parseCustomFundCents(form.customWan);
    if (fund === null) return { error: 'setup.fundInvalid' };
  }

  const buy = percentToRateString(form.buyFeePct);
  const sell = percentToRateString(form.sellFeePct);
  if (buy === null || sell === null) return { error: 'setup.feeInvalid' };

  if (form.tradeUnit !== 1 && form.tradeUnit !== 100) return { error: 'error.VALIDATION_ERROR' };

  return {
    body: {
      initial_fund_cents: fund,
      buy_fee_rate: buy,
      sell_fee_rate: sell,
      t0_mode: Boolean(form.t0Mode),
      trade_unit: form.tradeUnit,
    },
  };
}
