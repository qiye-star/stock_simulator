/**
 * market 共享状态（行情、存档快照、详情、列表视图设置）。
 * market / chart / trade / watchlist 通过此 store 通信，禁止跨模块直接改 DOM。
 *
 * 约定：
 *   - quotes 是 Map，原地更新；每次变更同时递增 quotesVersion（全量）或设置 tickInfo（增量）。
 *   - tickInfo = { tick, codes }，每个 tick 都是新对象，监听方据此做行级 diff。
 *   - detail 每次刷新都是新对象（不可变），图表与交易面板据此重绘。
 */
import { createStore } from '../../state/store.js';

/**
 * @typedef {import('./model.js').Quote} Quote
 * @typedef {import('./model.js').Detail} Detail
 * @typedef {import('./model.js').StockMeta} StockMeta
 * @typedef {import('./model.js').SortState} SortState
 *
 * @typedef {Object} SaveInfo 存档字段（GET /saves/{id} 的子集，金额为分）
 * @property {string} id
 * @property {number} cash_cents
 * @property {number} trade_unit 1 或 100
 * @property {string} buy_fee_rate 小数字符串，如 "0.0003"
 * @property {string} sell_fee_rate
 * @property {boolean} t0_mode
 * @property {boolean} paused
 *
 * @typedef {Object} Holding
 * @property {string} code
 * @property {string} name
 * @property {number} quantity
 * @property {number} sellable_quantity 当前可卖股数（T+1 已扣除当日买入）
 * @property {number} avg_cost_cents
 *
 * @typedef {Object} Account
 * @property {number} cash_cents
 * @property {Holding[]} holdings
 */

export const marketStore = createStore({
  /** @type {string | null} 当前存档 id */
  saveId: null,
  /** @type {SaveInfo | null} */
  save: null,
  /** @type {Account | null} */
  account: null,
  /** @type {string[]} 自选代码 */
  watchlist: [],
  paused: false,
  skipping: false,
  /** @type {number | null} 游戏分钟（0-1439） */
  minuteOfDay: null,
  /** @type {number | null} */
  tradingDay: null,
  /** @type {number | null} */
  tick: null,
  /** @type {{ tick: number | null, codes: string[] } | null} */
  tickInfo: null,
  quotesVersion: 0,
  /** @type {'closed' | 'connecting' | 'open' | 'reconnecting'} */
  wsStatus: 'closed',
  /** @type {StockMeta[]} */
  stockList: [],
  /** @type {Map<string, Quote>} */
  quotes: new Map(),
  /** @type {string | null} */
  selectedCode: null,
  /** @type {Detail | null} */
  detail: null,
  search: '',
  /** @type {SortState} */
  sort: { field: null, order: 'asc' },
  watchlistMode: false,
});

/** @returns {SaveInfo | null} */
export const currentSaveInfo = () => marketStore.get().save;
