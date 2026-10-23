/**
 * 行情列表视图：搜索 / 排序 / 自选过滤 + 行级 DOM diff。
 *
 * 不重建整张列表：每行缓存为元素，tick 只更新变化行的价格与涨跌文本；
 * 仅在排序/过滤结果变化时移动节点（insertBefore），从不 innerHTML 全量重绘。
 * 行结构沿用 legacy/index.html 的 .stock-item 样式。
 */
import { html } from '../../ui/html.js';
import { delegate, fragment, on } from '../../ui/dom.js';
import { marketStore } from './store.js';
import { centsText, changeDirection, changeText, nextSort, visibleCodes } from './model.js';
import { setClass, setText, toggleClass } from './dom.js';
import { selectStock, toggleWatchlistMode } from './controller.js';

/** @param {string} code */
const rowTemplate = (code) => html`<div class="stock-item" data-code="${code}">
  <div class="stock-item-info"><div class="name"></div><div class="code">${code}</div></div>
  <div class="stock-item-price"></div>
  <div class="stock-item-change"></div>
</div>`;

/** 自选星标：由 features/watchlist 处理点击（data-watch-toggle）。 */
const badgeTemplate = (title) =>
  html`<span class="watch-badge" data-watch-toggle role="button" tabindex="0" title="${title}">★</span>`;

/**
 * @param {import('../index.js').FeatureContext} ctx
 * @param {Document} [doc]
 * @returns {() => void}
 */
export function initStockList(ctx, doc = document) {
  const listEl = doc.getElementById('stock-list');
  const searchEl = /** @type {HTMLInputElement | null} */ (doc.getElementById('stock-search'));
  const toggleBtn = doc.getElementById('watchlist-toggle-btn');
  const headerEl = doc.querySelector('.stock-list-header');
  if (!listEl) return () => {};

  /** @type {Map<string, HTMLElement>} */
  const rows = new Map();
  /** @type {import('./store.js').StockMeta[] | null} */
  let metaSource = null;
  /** @type {Map<string, import('./store.js').StockMeta>} */
  let metaMap = new Map();

  const refreshMeta = (list) => {
    if (list === metaSource) return;
    metaSource = list;
    metaMap = new Map(list.map((m) => [m.code, m]));
  };

  /** @param {Element} el @param {string} code @param {import('./store.js').StockMeta | undefined} meta */
  function patchRow(el, code, meta, quote, watched, selectedCode) {
    setText(el.querySelector('.name'), meta?.name ?? quote?.name ?? code);
    const dir = quote ? changeDirection(quote.change_bp) : '';
    const priceEl = el.querySelector('.stock-item-price');
    setText(priceEl, centsText(quote?.price_cents));
    setClass(priceEl, dir ? `stock-item-price ${dir}` : 'stock-item-price');
    const changeEl = el.querySelector('.stock-item-change');
    setText(changeEl, quote ? changeText(quote.change_bp) : '--');
    setClass(changeEl, dir ? `stock-item-change ${dir}` : 'stock-item-change');
    toggleClass(el, 'active', code === selectedCode);
    const badge = el.querySelector('[data-watch-toggle]');
    if (watched && !badge) {
      el.appendChild(fragment(badgeTemplate(ctx.i18n.t('market.removeWatch'))));
    } else if (!watched && badge) {
      badge.remove();
    }
  }

  /** 全量同步顺序（过滤/排序/自选变化时）。 */
  function sync() {
    const st = marketStore.get();
    refreshMeta(st.stockList);
    const codes = visibleCodes({
      stockList: st.stockList,
      quotes: st.quotes,
      search: st.search,
      watchlist: st.watchlist,
      watchlistMode: st.watchlistMode,
      sort: st.sort,
    });
    const want = new Set(codes);
    for (const [code, el] of rows) {
      if (!want.has(code)) {
        el.remove();
        rows.delete(code);
      }
    }
    const watched = new Set(st.watchlist);
    let prev = null;
    for (const code of codes) {
      let el = rows.get(code);
      if (!el) {
        el = /** @type {HTMLElement} */ (fragment(rowTemplate(code)).firstElementChild);
        rows.set(code, el);
      }
      patchRow(el, code, metaMap.get(code), st.quotes.get(code), watched.has(code), st.selectedCode);
      const expected = prev ? prev.nextElementSibling : listEl.firstElementChild;
      if (el !== expected) listEl.insertBefore(el, expected);
      prev = el;
    }
    updateHeaders(st.sort);
    updateWatchToggle(st.watchlistMode);
  }

  /** 仅更新 tick 涉及的行（无排序时）。 @param {string[]} codes */
  function patchTick(codes) {
    const st = marketStore.get();
    const watched = new Set(st.watchlist);
    for (const code of codes) {
      const el = rows.get(code);
      if (el) patchRow(el, code, metaMap.get(code), st.quotes.get(code), watched.has(code), st.selectedCode);
    }
  }

  /** @param {import('./model.js').SortState} sort */
  function updateHeaders(sort) {
    doc.querySelectorAll('.stock-list-header .sortable').forEach((header) => {
      const field = /** @type {HTMLElement} */ (header).dataset.sort;
      const active = sort.field === field;
      toggleClass(header, 'sorted', active);
      setText(header.querySelector('.sort-indicator'), active ? (sort.order === 'asc' ? '▲' : '▼') : '');
    });
  }

  /** @param {boolean} on */
  function updateWatchToggle(on) {
    if (!toggleBtn) return;
    setText(toggleBtn, ctx.i18n.t(on ? 'market.allView' : 'market.watchlistView'));
    toggleClass(toggleBtn, 'active', on);
  }

  sync();

  const unsubscribe = marketStore.subscribe((s, prev) => {
    const structural =
      s.quotesVersion !== prev.quotesVersion ||
      s.stockList !== prev.stockList ||
      s.watchlist !== prev.watchlist ||
      s.watchlistMode !== prev.watchlistMode ||
      s.search !== prev.search ||
      s.sort !== prev.sort ||
      s.selectedCode !== prev.selectedCode;
    if (structural || (s.sort.field && s.tickInfo !== prev.tickInfo)) {
      sync();
    } else if (s.tickInfo !== prev.tickInfo && s.tickInfo) {
      patchTick(s.tickInfo.codes);
    }
  });

  const offLang = ctx.i18n.onChange(() => sync());
  const offSearch = searchEl ? on(searchEl, 'input', () => marketStore.set({ search: searchEl.value.trim() })) : () => {};
  const offHeader = headerEl
    ? delegate(headerEl, 'click', '.sortable', (_e, el) => {
        const field = /** @type {HTMLElement} */ (el).dataset.sort;
        if (field === 'name' || field === 'price' || field === 'change') {
          marketStore.set({ sort: nextSort(marketStore.get().sort, field) });
        }
      })
    : () => {};
  const offRow = delegate(listEl, 'click', '.stock-item', (e, el) => {
    if (/** @type {Element} */ (e.target).closest('[data-watch-toggle]')) return;
    selectStock(/** @type {HTMLElement} */ (el).dataset.code ?? '');
  });
  const offToggle = toggleBtn ? on(toggleBtn, 'click', () => toggleWatchlistMode()) : () => {};

  return () => {
    unsubscribe();
    offLang();
    offSearch();
    offHeader();
    offRow();
    offToggle();
  };
}
