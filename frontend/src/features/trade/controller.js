/**
 * 下单流程：本地校验 -> POST /saves/{id}/orders -> 价格偏离确认后带 confirm_deviation 重发 -> 刷新账户。
 * 错误码通过 i18n/errors.js 映射显示；T+1、资金不足等由后端返回。
 */
import { placeOrder } from '../../api/endpoints.js';
import { marketStore } from '../market/store.js';
import { ORDER_EVENT } from '../../state/events.js';
import { refreshAccount } from '../market/controller.js';
import { notifyError, notifyKey } from '../market/notify.js';
import { buildOrderBody, isDeviationConfirm, parseQuantity, parseYuanToCents, validateOrder } from './model.js';
import { confirmDeviation } from './confirm.js';

/** @typedef {import('./model.js').Side} Side */
/**
 * @typedef {Object} OrderInput
 * @property {string} code
 * @property {string} priceText
 * @property {string} qtyText
 * @property {boolean} priceDirty
 */

const CANCELLED = Symbol('cancelled');
let inFlight = false;

/**
 * @param {string} id
 * @param {import('../../api/endpoints.js').OrderIn} body
 */
async function send(id, body) {
  try {
    return await placeOrder(id, body);
  } catch (err) {
    if (!isDeviationConfirm(err)) throw err;
    const ok = await confirmDeviation(/** @type {any} */ (err).params ?? {});
    if (!ok) return CANCELLED;
    return placeOrder(id, { ...body, confirm_deviation: true });
  }
}

/**
 * @param {Side} side
 * @param {OrderInput} input
 * @param {(busy: boolean) => void} setBusy
 */
export async function submitOrder(side, input, setBusy) {
  if (inFlight) return;
  const st = marketStore.get();
  const id = st.saveId;
  if (!id) return notifyKey('notification.requireGame');
  const code = input.code.trim();
  if (!code) return notifyKey('trade.incompleteInfo', 'warning');
  if (!st.stockList.some((s) => s.code === code)) return notifyKey('error.STOCK_NOT_FOUND', 'error');

  const unit = st.save?.trade_unit ?? 1;
  const quantity = parseQuantity(input.qtyText);
  const priceCents = parseYuanToCents(input.priceText);
  const problem = validateOrder({ quantity, priceCents, unit });
  if (problem) return notifyKey(problem.key, 'warning', problem.params ?? null);

  const body = buildOrderBody({ code, side, quantity: /** @type {number} */ (quantity), priceCents, priceDirty: input.priceDirty });
  inFlight = true;
  setBusy(true);
  try {
    const result = await send(id, body);
    if (result === CANCELLED) return notifyKey('trade.cancelled');
    if (marketStore.get().saveId !== id) return;
    notifyKey(side === 'buy' ? 'trade.buySuccess' : 'trade.sellSuccess', 'success');
    window.dispatchEvent(new CustomEvent(ORDER_EVENT, { detail: { saveId: id, code, side } }));
    refreshAccount().catch(() => {});
  } catch (err) {
    notifyError(err);
  } finally {
    inFlight = false;
    setBusy(false);
  }
}
