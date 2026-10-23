/**
 * 持仓页控制器：REST 拉取、轮询刷新、成交记录游标分页、持仓行右键菜单。
 * 端点：GET /saves/{id}/portfolio、GET /saves/{id}/trades?cursor=、GET /stocks（名称映射）。
 *
 * 右键菜单只挂在持仓行上（不做全局 contextmenu 禁用，legacy 6156 的全局禁用不移植）。
 * 跨功能跳转：导航用 session.showTab；选股意图通过 SELECT_STOCK_EVENT 派发给目标功能。
 */
import * as api from '../../api/endpoints.js';
import { errorMessage } from '../../i18n/errors.js';
import { delegate, fragment, on, setHtml } from '../../ui/dom.js';
import { showNotification } from '../../ui/notify.js';
import { SCREENS, session, showTab } from '../../state/session.js';
import { ORDER_EVENT, SELECT_STOCK_EVENT } from '../../state/events.js';
import {
  holdingRow,
  mergeTrades,
  parseHoldings,
  parseTradePage,
  portfolioSummary,
  tradeRow,
} from './model.js';
import { renderContextMenu, renderHoldingRows, renderRecordsFooter, renderTradeRows } from './view.js';

const POLL_MS = 3000;


/**
 * @param {{ page: HTMLElement, i18n: import('../../i18n/i18n.js').I18n, doc?: Document }} env
 * @returns {{ destroy: () => void }}
 */
export function createPortfolioController({ page, i18n, doc = document }) {
  const el = {
    totalAssets: page.querySelector('#total-assets'),
    stockValue: page.querySelector('#stock-value'),
    available: page.querySelector('#available-fund'),
    floating: page.querySelector('#floating-pnl'),
    totalReturn: page.querySelector('#total-return'),
    holdings: page.querySelector('#portfolio-holdings-tbody'),
    records: page.querySelector('#trade-records-tbody'),
    recordsCard: page.querySelector('.portfolio-records'),
  };
  if (!el.holdings || !el.records || !el.recordsCard) return { destroy() {} };

  /** 记录页脚容器（加载更多按钮所在，由本模块创建）。 */
  const footer = doc.createElement('div');
  footer.className = 'portfolio-records-footer';
  el.recordsCard.appendChild(footer);

  const state = {
    saveId: /** @type {string | null} */ (null),
    cashCents: 0,
    initialFundCents: 0,
    holdings: /** @type {any[]} */ ([]),
    trades: /** @type {any[]} */ ([]),
    nextCursor: /** @type {string | null} */ (null),
    loadingMore: false,
    names: /** @type {Map<string, string>} */ (new Map()),
    lastError: /** @type {string | null} */ (null),
    generation: 0,
  };
  /** 正在进行中的刷新所属的存档代次（代次变化后新请求不被旧请求阻塞）。 */
  let inflight = /** @type {number | null} */ (null);
  /** @type {HTMLElement | null} */
  let menuEl = null;
  /** @type {Array<() => void>} */
  let menuCleanup = [];

  // ---------- 数据 ----------

  /** @returns {boolean} 持仓页当前是否可见 */
  function isVisible() {
    const s = session.get();
    return s.screen === SCREENS.MAIN && s.tab === 'portfolio';
  }

  /** @returns {string | null} */
  function currentSaveId() {
    const save = session.get().currentSave;
    return typeof save?.id === 'string' ? save.id : null;
  }

  /** 切换存档时重置本地数据，避免串存档。 */
  function resetFor(saveId) {
    state.generation += 1;
    state.saveId = saveId;
    state.holdings = [];
    state.trades = [];
    state.nextCursor = null;
    state.loadingMore = false;
    state.lastError = null;
    const save = session.get().currentSave;
    state.cashCents = Number.isInteger(save?.cash_cents) ? save.cash_cents : 0;
    state.initialFundCents = Number.isInteger(save?.initial_fund_cents) ? save.initial_fund_cents : 0;
    render();
  }

  function reportError(err) {
    const msg = errorMessage(err, (k) => i18n.t(k));
    if (state.lastError === msg) return; // 轮询中同一错误只提示一次
    state.lastError = msg;
    showNotification(msg, 'error', { doc });
  }

  /** 拉取持仓 + 成交首页（首页合并进已加载的列表，不丢失已翻过的页）。 */
  async function refresh() {
    const saveId = currentSaveId();
    if (saveId !== state.saveId) resetFor(saveId);
    if (!state.saveId || inflight === state.generation) return render();
    const gen = state.generation;
    inflight = gen;
    try {
      const [pf, tradesRes] = await Promise.all([api.getPortfolio(state.saveId), api.listTrades(state.saveId)]);
      if (gen !== state.generation) return;
      const page1 = parseTradePage(tradesRes);
      state.holdings = parseHoldings(pf);
      const pfObj = /** @type {Record<string, unknown>} */ (pf && typeof pf === 'object' ? pf : {});
      if (Number.isInteger(pfObj.cash_cents)) state.cashCents = /** @type {number} */ (pfObj.cash_cents);
      if (Number.isInteger(pfObj.initial_fund_cents)) state.initialFundCents = /** @type {number} */ (pfObj.initial_fund_cents);
      if (state.trades.length === 0) state.nextCursor = page1.nextCursor;
      state.trades = mergeTrades(state.trades, page1.items);
      state.lastError = null;
    } catch (err) {
      if (gen === state.generation) reportError(err);
    } finally {
      if (inflight === gen) inflight = null;
    }
    render();
  }

  async function loadMore() {
    if (!state.saveId || !state.nextCursor || state.loadingMore) return;
    const gen = state.generation;
    state.loadingMore = true;
    render();
    try {
      const res = parseTradePage(await api.listTrades(state.saveId, { cursor: state.nextCursor }));
      if (gen !== state.generation) return;
      state.trades = mergeTrades(state.trades, res.items);
      state.nextCursor = res.nextCursor;
    } catch (err) {
      if (gen === state.generation) reportError(err);
    } finally {
      if (gen === state.generation) state.loadingMore = false;
      render();
    }
  }

  async function loadNames() {
    try {
      const list = await api.listStocks();
      if (Array.isArray(list)) {
        state.names = new Map(
          list.filter((s) => s && typeof s.code === 'string').map((s) => [s.code, String(s.name ?? s.code)]),
        );
        render();
      }
    } catch {
      /* 名称缺失时回退为代码 */
    }
  }

  // ---------- 渲染 ----------

  function render() {
    const lang = i18n.getLanguage();
    const sum = portfolioSummary({ cashCents: state.cashCents, initialFundCents: state.initialFundCents, holdings: state.holdings }, lang);
    if (el.totalAssets) el.totalAssets.textContent = sum.totalAssetsText;
    if (el.stockValue) el.stockValue.textContent = sum.stockValueText;
    if (el.available) el.available.textContent = sum.availableText;
    if (el.floating) {
      el.floating.textContent = sum.floatingPnlText;
      el.floating.className = `value ${sum.floatingTone}`;
    }
    if (el.totalReturn) {
      el.totalReturn.textContent = sum.totalReturnText;
      el.totalReturn.className = `value ${sum.totalReturnTone}`;
    }

    const holdingVMs = state.holdings.map((h) => holdingRow(h, state.names, lang));
    setHtml(el.holdings, renderHoldingRows(holdingVMs, i18n.t('portfolio.noHoldings')));

    const tradeVMs = state.trades.map((t) => {
      const row = tradeRow(t, state.names, lang);
      return { ...row, sideText: i18n.t(row.sideKey) };
    });
    setHtml(el.records, renderTradeRows(tradeVMs, i18n.t('portfolio.noRecords')));

    setHtml(
      footer,
      renderRecordsFooter({
        loading: state.loadingMore,
        hasMore: Boolean(state.nextCursor),
        hasRows: state.trades.length > 0,
        moreText: i18n.t('portfolio.loadMore'),
        allLoadedText: i18n.t('portfolio.allLoaded'),
        loadingText: i18n.t('portfolio.loading'),
      }),
    );
  }

  // ---------- 右键菜单（仅持仓行） ----------

  function closeMenu() {
    for (const off of menuCleanup) off();
    menuCleanup = [];
    menuEl?.remove();
    menuEl = null;
  }

  /** @param {number} x @param {number} y @param {string} code */
  function openMenu(x, y, code) {
    closeMenu();
    const labels = {
      trade: i18n.t('portfolio.contextMenu.trade'),
      autoTrade: i18n.t('portfolio.contextMenu.autoTrade'),
      viewDetail: i18n.t('portfolio.contextMenu.viewDetail'),
    };
    const node = /** @type {HTMLElement} */ (fragment(renderContextMenu(code, labels)).firstElementChild);
    doc.body.appendChild(node);
    const win = doc.defaultView;
    const maxX = (win?.innerWidth ?? 1024) - node.offsetWidth - 8;
    const maxY = (win?.innerHeight ?? 768) - node.offsetHeight - 8;
    node.style.position = 'fixed';
    node.style.left = `${Math.max(0, Math.min(x, maxX))}px`;
    node.style.top = `${Math.max(0, Math.min(y, maxY))}px`;
    menuEl = node;
    menuCleanup = [
      on(doc, 'click', (e) => {
        if (!node.contains(/** @type {Node} */ (e.target))) closeMenu();
      }),
      on(doc, 'keydown', (e) => {
        if (/** @type {KeyboardEvent} */ (e).key === 'Escape') closeMenu();
      }),
      on(win ?? doc, 'resize', closeMenu),
      on(win ?? doc, 'scroll', closeMenu, { capture: true, passive: true }),
    ];
    menuCleanup.push(
      delegate(node, 'click', '.context-menu-item', (e, item) => {
        e.stopPropagation();
        const action = item.getAttribute('data-action');
        const stockCode = item.getAttribute('data-code') ?? code;
        closeMenu();
        runMenuAction(action, stockCode);
      }),
    );
  }

  /** @param {string | null} action @param {string} code */
  function runMenuAction(action, code) {
    const target = action === 'trade' ? 'trade' : action === 'auto-trade' ? 'auto-trade' : 'market';
    showTab(target, doc);
    // 全部跨功能事件派发到 window（监听方：market / trade / auto-trade）
    window.dispatchEvent(new CustomEvent(SELECT_STOCK_EVENT, { detail: { code, target } }));
  }

  // ---------- 生命周期 ----------

  const offMenu = delegate(el.holdings, 'contextmenu', 'tr[data-code]', (e, row) => {
    e.preventDefault();
    const me = /** @type {MouseEvent} */ (e);
    openMenu(me.clientX, me.clientY, row.getAttribute('data-code') ?? '');
  });
  const offMore = delegate(footer, 'click', '#trade-records-more', () => loadMore());

  const unsubSession = session.subscribe((s, prev) => {
    if (s.currentSave !== prev.currentSave || s.tab !== prev.tab || s.screen !== prev.screen) {
      if (currentSaveId() !== state.saveId) resetFor(currentSaveId());
      if (isVisible()) refresh();
    }
  });
  const unsubLang = i18n.onChange(() => render());
  // 下单成功（trade 派发）后立即刷新持仓与成交
  const onOrder = () => refresh();
  window.addEventListener(ORDER_EVENT, onOrder);

  const timer = setInterval(() => {
    if (isVisible() && !doc.hidden) refresh();
  }, POLL_MS);

  resetFor(currentSaveId());
  loadNames();
  if (isVisible()) refresh();

  return {
    destroy() {
      clearInterval(timer);
      closeMenu();
      offMenu();
      offMore();
      unsubSession();
      unsubLang();
      window.removeEventListener(ORDER_EVENT, onOrder);
      footer.remove();
    },
  };
}
