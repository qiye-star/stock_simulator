/**
 * 存档选择页与重命名弹窗的渲染（html`` 默认转义；文本经模板插值，不拼接字符串）。
 */
import { html } from '../../ui/html.js';

/**
 * @param {import('./viewModel.js').SaveCard[]} cards
 * @param {(key: string) => string} t
 */
export function renderSaveList(cards, t) {
  if (cards.length === 0) {
    return html`<p style="text-align:center;color:var(--text-secondary);padding:40px;">${t('save.empty')}</p>`;
  }
  return html`${cards.map(
    (card) => html`<div class="save-item" data-save-id="${card.id}">
      <div class="save-info">
        <h4>${card.name}</h4>
        <p>${card.info}</p>
      </div>
      <div class="save-actions">
        <button type="button" class="btn-enter" data-action="enter" data-save-id="${card.id}">${t('common.enter')}</button>
        <button type="button" class="btn-rename" data-action="rename" data-save-id="${card.id}">${t('common.rename')}</button>
        <button type="button" class="btn-delete" data-action="delete" data-save-id="${card.id}">${t('common.delete')}</button>
      </div>
    </div>`,
  )}`;
}
