/**
 * 价格偏离确认弹窗（沿用 .modal 样式）。返回 Promise<boolean>：确认 true，取消或 Esc false。
 */
import { html } from '../../ui/html.js';
import { fragment } from '../../ui/dom.js';
import { i18n } from '../../i18n/i18n.js';
import { centsText } from '../market/model.js';

/**
 * @param {Record<string, unknown>} params 后端 params：price_cents 或 price，percent
 * @returns {string}
 */
export function deviationMessage(params) {
  const price =
    typeof params.price_cents === 'number' ? centsText(params.price_cents) : String(params.price ?? '--');
  const percent = String(params.percent ?? params.deviation_percent ?? '--');
  return i18n.t('trade.priceDeviationWarn', { price, percent });
}

/**
 * @param {Record<string, unknown>} params
 * @param {Document} [doc]
 * @returns {Promise<boolean>}
 */
export function confirmDeviation(params, doc = document) {
  return new Promise((resolve) => {
    const root = /** @type {HTMLElement} */ (
      fragment(html`<div class="modal active" role="dialog" aria-modal="true">
        <div class="modal-content">
          <h3>${i18n.t('trade.deviationTitle')}</h3>
          <p>${deviationMessage(params)}</p>
          <div class="form-row" style="justify-content:flex-end;gap:8px">
            <button type="button" class="btn-secondary" data-act="cancel">${i18n.t('common.cancel')}</button>
            <button type="button" class="btn-primary" data-act="ok">${i18n.t('common.confirm')}</button>
          </div>
        </div>
      </div>`).firstElementChild
    );
    doc.body.appendChild(root);

    const finish = (ok) => {
      doc.removeEventListener('keydown', onKey);
      root.remove();
      resolve(ok);
    };
    /** @param {KeyboardEvent} e */
    const onKey = (e) => {
      if (e.key === 'Escape') finish(false);
    };
    root.addEventListener('click', (e) => {
      const act = /** @type {HTMLElement} */ (e.target).closest?.('[data-act]')?.getAttribute('data-act');
      if (act === 'ok') finish(true);
      else if (act === 'cancel' || e.target === root) finish(false);
    });
    doc.addEventListener('keydown', onKey);
    root.querySelector('[data-act="ok"]')?.focus?.();
  });
}
