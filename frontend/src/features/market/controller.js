/**
 * market 控制器：存档切换 -> 拉取快照 -> 建立 WebSocket -> 逐 tick 更新共享 store。
 * 也负责详情（日K + 五档）按 tick 合并刷新、选股、暂停/继续/跳过。
 *
 * 并发约定：每次切换存档 generation+1，所有异步回调先比对 generation，过期结果直接丢弃。
 * 参考：legacy/game.js startMarketSimulation / skipTime / togglePause（1752-2007）。
 */
import * as api from '../../api/endpoints.js';
import { createSaveSocket } from '../../api/ws.js';
import { marketStore } from './store.js';
import {
  applyQuoteToDetail,
  mergeQuote,
  normalizeDetail,
  normalizeSnapshot,
  normalizeStockMeta,
  normalizeTick,
  parseClock,
} from './model.js';
import { notifyError, notifyKey } from './notify.js';
import { session } from '../../state/session.js';

let generation = 0;
/** @type {ReturnType<typeof createSaveSocket> | null} */
let socket = null;
let hasConnected = false;
let detailInFlight = false;
let detailPending = false;

/**
 * @param {unknown} v 存档对象或 id
 * @returns {string | null}
 */
export function saveIdOf(v) {
  if (!v) return null;
  if (typeof v === 'string') return v;
  const id = /** @type {any} */ (v).id;
  return typeof id === 'string' ? id : null;
}

/** 当前存档 id（供其它模块使用）。 */
export const currentSaveId = () => marketStore.get().saveId;

/**
 * 绑定会话：currentSave 变化时切换行情连接。返回取消订阅函数。
 * @returns {() => void}
 */
export function bindSession() {
  const sync = () => {
    const id = saveIdOf(session.get().currentSave);
    if (id !== marketStore.get().saveId) switchSave(id);
  };
  sync();
  return session.subscribe(sync);
}

/**
 * 释放全部资源（模块卸载时调用）。
 */
export function teardown() {
  generation++;
  closeSocket();
  marketStore.set({ saveId: null, wsStatus: 'closed' });
}

function closeSocket() {
  const s = socket;
  socket = null;
  s?.close();
}

/** @param {string | null} id */
function switchSave(id) {
  closeSocket();
  generation++;
  hasConnected = false;
  detailPending = false;
  marketStore.set({
    saveId: id,
    save: null,
    account: null,
    watchlist: [],
    paused: false,
    skipping: false,
    minuteOfDay: null,
    tradingDay: null,
    tick: null,
    tickInfo: null,
    quotes: new Map(),
    quotesVersion: marketStore.get().quotesVersion + 1,
    selectedCode: null,
    detail: null,
    wsStatus: id ? 'connecting' : 'closed',
  });
  if (!id) return;
  const gen = generation;
  connect(id, gen);
  loadAll(id, gen).catch((err) => notifyError(err));
}

/**
 * @param {string} id
 * @param {number} gen
 */
function connect(id, gen) {
  socket = createSaveSocket(id, {
    onMessage: (msg) => {
      if (gen === generation) handleMessage(msg);
    },
    onStatus: (status) => {
      if (gen !== generation) return;
      marketStore.set({ wsStatus: status });
      if (status === 'open') {
        // 重连后补一次快照，避免断线期间的 tick 丢失
        if (hasConnected) loadAll(id, gen).catch(() => {});
        hasConnected = true;
      }
    },
  });
}

/**
 * 拉取存档、市场快照与持仓；全部成功后一次性写入 store。
 * @param {string | null} [id]
 * @param {number} [gen]
 */
export async function loadAll(id = marketStore.get().saveId, gen = generation) {
  if (!id) return;
  const [saveRaw, snapRaw, portfolio] = await Promise.all([
    api.getSave(id),
    api.getMarket(id),
    api.getPortfolio(id),
  ]);
  if (gen !== generation) return;
  applySave(saveRaw, portfolio);
  const snap = normalizeSnapshot(snapRaw);
  const quotes = new Map();
  for (const q of snap.quotes) quotes.set(q.code, mergeQuote(marketStore.get().quotes.get(q.code), q));
  const st = marketStore.get();
  marketStore.set({
    quotes,
    quotesVersion: st.quotesVersion + 1,
    tick: snap.tick ?? st.tick,
    tradingDay: snap.tradingDay ?? st.tradingDay,
    minuteOfDay: snap.minuteOfDay ?? st.minuteOfDay,
    paused: snap.paused ?? marketStore.get().paused,
    watchlist: snap.watchlist,
  });
  refreshDetail();
}

/**
 * 仅刷新存档与持仓（下单后调用）。
 */
export async function refreshAccount() {
  const id = marketStore.get().saveId;
  if (!id) return;
  const gen = generation;
  const [saveRaw, portfolio] = await Promise.all([api.getSave(id), api.getPortfolio(id)]);
  if (gen !== generation) return;
  applySave(saveRaw, portfolio);
}

/**
 * @param {any} saveRaw
 * @param {any} portfolio
 */
function applySave(saveRaw, portfolio) {
  const save = normalizeSave(saveRaw);
  const holdings = normalizeHoldings(portfolio?.holdings, save.t0_mode);
  marketStore.set({
    save,
    paused: save.paused,
    account: {
      cash_cents: Number.isInteger(portfolio?.cash_cents) ? portfolio.cash_cents : save.cash_cents,
      holdings,
    },
  });
}

/**
 * @param {any} raw
 * @returns {import('./store.js').SaveInfo}
 */
export function normalizeSave(raw) {
  const rate = (v, fallback) => (v === undefined || v === null ? fallback : String(v));
  return {
    id: String(raw?.id ?? marketStore.get().saveId ?? ''),
    cash_cents: Number.isInteger(raw?.cash_cents) ? raw.cash_cents : 0,
    trade_unit: raw?.trade_unit === 100 ? 100 : 1,
    buy_fee_rate: rate(raw?.buy_fee_rate, '0.0003'),
    sell_fee_rate: rate(raw?.sell_fee_rate, '0.0013'),
    t0_mode: raw?.t0_mode === true,
    paused: raw?.paused === true,
  };
}

/**
 * @param {unknown} raw
 * @param {boolean} t0
 * @returns {import('./store.js').Holding[]}
 */
function normalizeHoldings(raw, t0) {
  const list = Array.isArray(raw) ? raw : raw && typeof raw === 'object' ? Object.values(raw) : [];
  const out = [];
  for (const h of list) {
    const x = /** @type {any} */ (h);
    if (!x || typeof x.code !== 'string') continue;
    const quantity = Number.isInteger(x.quantity) ? x.quantity : 0;
    const sellable = t0
      ? quantity
      : Number.isInteger(x.sellable_quantity)
        ? x.sellable_quantity
        : Number.isInteger(x.available_quantity)
          ? x.available_quantity
          : quantity;
    out.push({
      code: x.code,
      name: typeof x.name === 'string' ? x.name : x.code,
      quantity,
      sellable_quantity: Math.max(0, Math.min(quantity, sellable)),
      avg_cost_cents: Number.isInteger(x.avg_price_cents) ? x.avg_price_cents : 0,
    });
  }
  return out;
}

/** @param {any} msg */
function handleMessage(msg) {
  const t = normalizeTick(msg);
  if (!t) return;
  const st = marketStore.get();
  const map = st.quotes;
  const codes = [];
  for (const q of t.quotes) {
    map.set(q.code, mergeQuote(map.get(q.code), q));
    codes.push(q.code);
  }
  const patch = {
    tickInfo: { tick: t.tick, codes },
    tick: t.tick ?? st.tick,
    minuteOfDay: t.minuteOfDay ?? st.minuteOfDay,
    ...(t.paused !== null ? { paused: t.paused } : {}),
  };
  let touchesDetail = false;
  if (st.detail && codes.includes(st.detail.code)) {
    const q = map.get(st.detail.code);
    if (q) patch.detail = applyQuoteToDetail(st.detail, q);
    touchesDetail = true;
  }
  marketStore.set(patch);
  if (touchesDetail) refreshDetail();
}

/**
 * 刷新当前选中股票的详情（日K、五档、涨跌停）。同一时刻最多一个在途请求，
 * 期间到来的 tick 合并为一次补拉。
 */
export function refreshDetail() {
  const st = marketStore.get();
  const id = st.saveId;
  const code = st.selectedCode;
  if (!id || !code) return;
  if (detailInFlight) {
    detailPending = true;
    return;
  }
  detailInFlight = true;
  const gen = generation;
  api
    .getStockMarket(id, code)
    .then((raw) => {
      if (gen !== generation || marketStore.get().selectedCode !== code) return;
      const detail = normalizeDetail(raw);
      if (detail) marketStore.set({ detail: detail.name === detail.code ? { ...detail, name: stockName(code) } : detail });
    })
    .catch((err) => {
      if (err?.name !== 'AbortError') console.warn('[market] detail refresh failed:', err);
    })
    .finally(() => {
      detailInFlight = false;
      if (detailPending) {
        detailPending = false;
        refreshDetail();
      }
    });
}

/** @param {string} code */
function stockName(code) {
  return marketStore.get().stockList.find((s) => s.code === code)?.name ?? code;
}

/**
 * 选中股票（列表点击 / 交易页快捷入口）。
 * @param {string} code
 */
export function selectStock(code) {
  if (marketStore.get().selectedCode === code) return;
  marketStore.set({ selectedCode: code, detail: null });
  refreshDetail();
}

/** 加载股票池（与存档无关，只需一次）。 @returns {Promise<void>} */
export async function loadStockList() {
  const raw = await api.listStocks();
  const list = Array.isArray(raw) ? raw.map(normalizeStockMeta).filter(Boolean) : [];
  marketStore.set({ stockList: /** @type {any} */ (list) });
}

/** 暂停 / 继续游戏时间。 */
export async function togglePause() {
  const st = marketStore.get();
  const id = st.saveId;
  if (!id) return notifyKey('notification.requireGame');
  const gen = generation;
  const next = !st.paused;
  marketStore.set({ paused: next });
  try {
    const res = await (next ? api.pauseClock(id) : api.resumeClock(id));
    if (gen !== generation) return;
    const r = /** @type {any} */ (res);
    if (typeof r?.paused === 'boolean') marketStore.set({ paused: r.paused });
    const m = parseClock(r?.clock_minute);
    if (m !== null) marketStore.set({ minuteOfDay: m });
    notifyKey(next ? 'notification.timePaused' : 'notification.timeResumed', 'success');
  } catch (err) {
    if (gen === generation) marketStore.set({ paused: !next });
    notifyError(err);
  }
}

/** 跳过时间（服务端推进，完成后整体重新同步）。 */
export async function skipTime() {
  const st = marketStore.get();
  const id = st.saveId;
  if (!id) return notifyKey('notification.requireGame');
  if (st.skipping) return notifyKey('notification.skipping');
  const gen = generation;
  marketStore.set({ skipping: true });
  try {
    const res = /** @type {any} */ (await api.skipClock(id));
    if (gen !== generation) return;
    // ClockOut.skipped_ticks：0 表示当前已是下一个关键时点，无需跳过
    if (res?.skipped_ticks === 0) notifyKey('notification.noSkipNeeded');
    else notifyKey('notification.skipCompleted', 'success');
    await loadAll(id, gen);
  } catch (err) {
    if (gen === generation) notifyError(err);
  } finally {
    if (gen === generation) marketStore.set({ skipping: false });
  }
}

/**
 * 切换自选列表过滤。
 */
export function toggleWatchlistMode() {
  const on = !marketStore.get().watchlistMode;
  marketStore.set({ watchlistMode: on });
  notifyKey(on ? 'notification.switchToWatchlist' : 'notification.switchToAll', 'success');
}

