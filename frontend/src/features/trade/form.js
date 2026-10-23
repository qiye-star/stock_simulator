/**
 * 买入 / 卖出表单（移植自 legacy/index.html #buy-panel #sell-panel 与 game.js 3115-3205）。
 *
 * 价格规则（修复 legacy 的覆盖问题）：价格框只在“未被用户编辑”时跟随市价刷新；
 * 用户输入过价格（input 事件）后，tick 不再覆盖，直到更换股票代码。
 * 金额全部整数分；预估与可用资金在每次变化时重算。
 */
import { marketStore } from '../market/store.js';
import { centsText } from '../market/model.js';
import { setText, toggleClass } from '../market/dom.js';
import { formatMoney } from '../../ui/format.js';
import { on } from '../../ui/dom.js';
import {
  estimateOrder,
  maxBuyQuantity,
  parseQuantity,
  parseYuanToCents,
  ratioQuantity,
  sellableOf,
} from './model.js';
import { submitOrder } from './controller.js';

/** @typedef {import('./model.js').Side} Side */

/**
 * @param {import('../index.js').FeatureContext} ctx
 * @param {Document} [doc]
 */
export function initTradeForms(ctx, doc = document) {
  /** @type {Record<Side, ReturnType<typeof createSide>>} */
  const sides = { buy: createSide('buy', ctx, doc), sell: createSide('sell', ctx, doc) };

  const unsubscribe = marketStore.subscribe((s, prev) => {
    for (const side of /** @type {Side[]} */ (['buy', 'sell'])) sides[side]?.onStore(s, prev);
  });

  const tabOffs = [...doc.querySelectorAll('.trade-tab[data-trade]')].map((btn) =>
    on(btn, 'click', () => setActive(/** @type {HTMLElement} */ (btn).dataset.trade === 'sell' ? 'sell' : 'buy')),
  );

  /** @param {Side} side */
  function setActive(side) {
    doc.querySelectorAll('.trade-tab[data-trade]').forEach((t) => {
      toggleClass(t, 'active', /** @type {HTMLElement} */ (t).dataset.trade === side);
    });
    for (const s of /** @type {Side[]} */ (['buy', 'sell'])) {
      toggleClass(doc.getElementById(`${s}-panel`), 'active', s === side);
    }
  }

  /** 把同一只股票填入买卖两个表单（同 legacy 快捷入口）。 @param {string} code */
  function setCode(code) {
    for (const side of /** @type {Side[]} */ (['buy', 'sell'])) sides[side]?.setCode(code);
  }

  return {
    setActive,
    setCode,
    dispose() {
      unsubscribe();
      tabOffs.forEach((off) => off());
      sides.buy?.dispose();
      sides.sell?.dispose();
    },
  };
}

/**
 * @param {Side} side
 * @param {import('../index.js').FeatureContext} ctx
 * @param {Document} doc
 */
function createSide(side, ctx, doc) {
  const $ = (/** @type {string} */ id) => doc.getElementById(id);
  const panel = $(`${side}-panel`);
  const el = {
    code: /** @type {HTMLInputElement | null} */ ($(`${side}-code`)),
    name: $(`${side}-name`),
    price: /** @type {HTMLInputElement | null} */ ($(`${side}-price`)),
    qty: /** @type {HTMLInputElement | null} */ ($(`${side}-quantity`)),
    available: $(`${side}-available`),
    estimate: $(`${side}-estimate`),
    submit: /** @type {HTMLButtonElement | null} */ ($(`confirm-${side}-btn`)),
  };
  if (!el.code || !el.price || !el.qty) return null;
  const codeEl = el.code;
  const priceEl = el.price;
  const qtyEl = el.qty;
  const ratioButtons = panel ? [...panel.querySelectorAll('[data-ratio]')] : [];

  /** 用户是否手动改过价格（改过则 tick 不再覆盖）。 */
  let priceDirty = false;
  /** 当前表单绑定的股票代码（用于判断代码是否真的变化）。 */
  let boundCode = '';

  const currentCode = () => codeEl.value.trim();

  function refresh() {
    const st = marketStore.get();
    const code = currentCode();
    const quote = st.quotes.get(code);

    if (!priceDirty) {
      const text = quote ? centsText(quote.price_cents) : '';
      if (priceEl.value !== text) priceEl.value = text;
    }

    const meta = st.stockList.find((s) => s.code === code);
    setText(el.name, meta ? meta.name : code.length === 6 ? ctx.i18n.t('trade.stockNotExist') : '');

    const unit = st.save?.trade_unit ?? 1;
    if (qtyEl.step !== String(unit)) qtyEl.step = String(unit);
    if (qtyEl.min !== String(unit)) qtyEl.min = String(unit);

    if (side === 'buy') {
      setText(el.available, st.account ? `¥${formatMoney(st.account.cash_cents)}` : '--');
    } else {
      setText(el.available, String(sellableOf(st.account, code)));
    }

    const priceCents = parseYuanToCents(priceEl.value);
    const quantity = parseQuantity(qtyEl.value);
    if (priceCents && quantity && st.save) {
      const e = estimateOrder({
        side,
        priceCents,
        quantity,
        buyRate: st.save.buy_fee_rate,
        sellRate: st.save.sell_fee_rate,
      });
      setText(
        el.estimate,
        ctx.i18n.t('trade.estimateWithFee', {
          total: formatMoney(e.total_cents),
          fee: (e.fee_cents / 100).toFixed(2),
        }),
      );
    } else {
      setText(el.estimate, '--');
    }
  }

  /** @param {string} code */
  function setCode(code) {
    codeEl.value = code;
    boundCode = code;
    priceDirty = false;
    refresh();
  }

  /** @param {number} ratio */
  function applyRatio(ratio) {
    const st = marketStore.get();
    const code = currentCode();
    const unit = st.save?.trade_unit ?? 1;
    const quote = st.quotes.get(code);
    const priceCents = parseYuanToCents(priceEl.value) ?? quote?.price_cents ?? null;
    let maxQty = 0;
    if (side === 'buy') {
      if (priceCents && st.account && st.save) {
        maxQty = maxBuyQuantity({
          cashCents: st.account.cash_cents,
          priceCents,
          unit,
          buyRate: st.save.buy_fee_rate,
        });
      }
    } else {
      maxQty = sellableOf(st.account, code);
    }
    const q = ratioQuantity(maxQty, ratio, unit);
    qtyEl.value = q > 0 ? String(q) : '';
    refresh();
  }

  const offs = [
    on(codeEl, 'input', () => {
      const code = currentCode();
      if (code !== boundCode) {
        boundCode = code;
        priceDirty = false;
      }
      refresh();
    }),
    on(priceEl, 'input', () => {
      priceDirty = true;
      refresh();
    }),
    on(qtyEl, 'input', () => refresh()),
    ...ratioButtons.map((btn) =>
      on(btn, 'click', () => applyRatio(Number(/** @type {HTMLElement} */ (btn).dataset.ratio))),
    ),
    el.submit
      ? on(el.submit, 'click', () =>
          submitOrder(
            side,
            { code: currentCode(), priceText: priceEl.value, qtyText: qtyEl.value, priceDirty },
            (busy) => {
              if (el.submit) el.submit.disabled = busy;
            },
          ),
        )
      : () => {},
  ];

  refresh();

  return {
    setCode,
    /** @param {any} s @param {any} prev */
    onStore(s, prev) {
      const tickHit = s.tickInfo !== prev.tickInfo && s.tickInfo?.codes.includes(currentCode());
      if (tickHit || s.quotesVersion !== prev.quotesVersion || s.account !== prev.account || s.save !== prev.save || s.stockList !== prev.stockList) {
        refresh();
      }
    },
    dispose() {
      offs.forEach((off) => off());
    },
  };
}
