/**
 * 自选功能入口：详情区 “+自选 / -自选” 按钮，以及列表中星标的点击切换。
 * 拥有：#add-watch-btn；列表星标由 market/view.js 渲染（.watch-badge[data-watch-toggle]），点击在此处理。
 */
import { marketStore } from '../market/store.js';
import { toggleWatchlist } from './controller.js';
import { on, delegate } from '../../ui/dom.js';
import { setText, toggleClass } from '../market/dom.js';

/**
 * @param {import('../index.js').FeatureContext} ctx
 * @returns {() => void}
 */
export function mount(ctx) {
  const doc = document;
  const addBtn = doc.getElementById('add-watch-btn');
  const list = doc.getElementById('stock-list');

  function renderButton() {
    if (!addBtn) return;
    const st = marketStore.get();
    const watched = !!st.selectedCode && st.watchlist.includes(st.selectedCode);
    setText(addBtn, ctx.i18n.t(watched ? 'market.removeWatch' : 'market.addWatch'));
    toggleClass(addBtn, 'active', watched);
    addBtn.disabled = !st.selectedCode;
  }

  renderButton();
  const unsubscribe = marketStore.subscribe((s, prev) => {
    if (s.watchlist !== prev.watchlist || s.selectedCode !== prev.selectedCode) renderButton();
  });
  const offLang = ctx.i18n.onChange(() => renderButton());

  const offAdd = addBtn
    ? on(addBtn, 'click', () => {
        const code = marketStore.get().selectedCode;
        if (code) toggleWatchlist(code);
      })
    : () => {};

  const offStar = list
    ? delegate(list, 'click', '[data-watch-toggle]', (e, el) => {
        e.stopPropagation();
        const row = /** @type {HTMLElement | null} */ (el.closest('.stock-item'));
        const code = row?.dataset.code;
        if (code) toggleWatchlist(code);
      })
    : () => {};

  return () => {
    unsubscribe();
    offLang();
    offAdd();
    offStar();
  };
}
