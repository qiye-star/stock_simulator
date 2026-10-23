/**
 * 自动交易控制器：配置增删改（表单 -> payload 经 model.buildConfigPayload 校验）、启停控制、
 * 统计与事件日志轮询。端点见 api/endpoints.js「自动交易」段。
 *
 * 事件的失败文案在渲染时经 i18n/errors.js 翻译（不存译文）。
 * 原版参考：legacy/game.js 5021-5641、6041-6100。
 */
import * as api from '../../api/endpoints.js';
import { errorMessage } from '../../i18n/errors.js';
import { delegate, fragment, on, setHtml } from '../../ui/dom.js';
import { showNotification } from '../../ui/notify.js';
import { SCREENS, session, showTab } from '../../state/session.js';
import {
  SELECT_STOCK_EVENT,
  buildConfigPayload,
  configRow,
  configToForm,
  directionRules,
  eventRow,
  parseEvents,
  priceFromMarket,
  ratioQuantity,
  readStats,
  statsView,
  statusOf,
} from './model.js';
import { renderConfigList, renderEventList, renderProfitTip } from './view.js';

const POLL_MS = 3000;


/**
 * @param {{ page: HTMLElement, i18n: import('../../i18n/i18n.js').I18n, doc?: Document }} env
 * @returns {{ destroy: () => void }}
 */
export function createAutoTradeController({ page, i18n, doc = document }) {
  const q = (sel) => page.querySelector(sel);
  const el = {
    statusText: q('#auto-trade-status-text'),
    indicator: q('#auto-trade-status-indicator'),
    tabs: page.querySelectorAll('.auto-trade-tab[data-tab]'),
    container: q('#auto-trade-stocks-container'),
    resetBtn: q('#reset-auto-trade-config-btn'),
    code: /** @type {HTMLInputElement | null} */ (q('#auto-code')),
    name: q('#auto-name'),
    conditionType: /** @type {HTMLSelectElement | null} */ (q('#auto-condition-type')),
    operator: /** @type {HTMLSelectElement | null} */ (q('#auto-condition-operator')),
    conditionValue: /** @type {HTMLInputElement | null} */ (q('#auto-condition-value')),
    quantity: /** @type {HTMLInputElement | null} */ (q('#auto-quantity')),
    priceType: /** @type {HTMLSelectElement | null} */ (q('#auto-price-type')),
    limitPrice: /** @type {HTMLInputElement | null} */ (q('#auto-limit-price')),
    stopLoss: /** @type {HTMLInputElement | null} */ (q('#auto-stop-loss')),
    takeProfit: /** @type {HTMLInputElement | null} */ (q('#auto-take-profit')),
    maxTrades: /** @type {HTMLInputElement | null} */ (q('#auto-max-trades')),
    maxAmount: /** @type {HTMLInputElement | null} */ (q('#auto-max-amount')),
    maxTotal: /** @type {HTMLInputElement | null} */ (q('#auto-max-total-trades')),  // 后端无设置接口，只读展示
    addBtn: q('#add-auto-stock-btn'),
    ratioBox: q('.quantity-btns'),
    stats: {
      total: q('#auto-total-trades'),
      success: q('#auto-success-trades'),
      failed: q('#auto-failed-trades'),
      pnl: q('#auto-total-pnl'),
      remaining: q('#auto-remaining-trades'),
    },
    eventsList: q('#auto-trade-records-list'),
    startBtn: /** @type {HTMLButtonElement | null} */ (q('#start-auto-trade-btn')),
    pauseBtn: /** @type {HTMLButtonElement | null} */ (q('#pause-auto-trade-btn')),
    stopBtn: /** @type {HTMLButtonElement | null} */ (q('#stop-auto-trade-btn')),
    profitOption: /** @type {HTMLOptionElement | null} */ (q('#auto-condition-type option[value="profit"]')),
  };
  if (!el.container || !el.eventsList || !el.code || !el.addBtn || !el.startBtn) {
    return { destroy() {} };
  }

  const t = (key, params) => i18n.t(key, params);
  const lang = () => i18n.getLanguage();

  const state = {
    saveId: /** @type {string | null} */ (null),
    save: /** @type {Record<string, any> | null} */ (null),
    /** @type {import('../../api/endpoints.js').AutoStatusOut | null} */
    status: null,
    configs: /** @type {Array<Record<string, any>>} */ ([]),
    events: /** @type {Array<Record<string, any>>} */ ([]),
    names: /** @type {Map<string, string>} */ (new Map()),
    stockCodes: /** @type {Set<string>} */ (new Set()),
    editingId: /** @type {string | null} */ (null),
    generation: 0,
    polling: false,
    lastError: /** @type {string | null} */ (null),
  };

  // ---------- 通用 ----------

  function isVisible() {
    const s = session.get();
    return s.screen === SCREENS.MAIN && s.tab === 'auto-trade';
  }

  /** @returns {string | null} */
  function currentSaveId() {
    const save = session.get().currentSave;
    return typeof save?.id === 'string' ? save.id : null;
  }

  function notify(msg, type = 'info') {
    showNotification(msg, type, { doc });
  }

  function notifyError(err) {
    notify(errorMessage(err, t), 'error');
  }

  /** @param {string} message 确认框（legacy 使用 confirm）。 */
  function confirmAction(message) {
    const win = doc.defaultView;
    return win && typeof win.confirm === 'function' ? win.confirm(message) : true;
  }

  // ---------- 数据加载 ----------

  async function loadNames() {
    try {
      const list = await api.listStocks();
      if (!Array.isArray(list)) return;
      state.names = new Map(list.filter((s) => s && typeof s.code === 'string').map((s) => [s.code, String(s.name ?? s.code)]));
      state.stockCodes = new Set(state.names.keys());
      renderAll();
    } catch {
      /* 名称缺失时回退为代码 */
    }
  }

  async function loadConfigs() {
    const saveId = state.saveId;
    if (!saveId) return;
    const gen = state.generation;
    try {
      const list = await api.listAutoTradeConfigs(saveId);
      if (gen !== state.generation) return;
      state.configs = Array.isArray(list?.items) ? list.items : [];
      renderConfigs();
    } catch (err) {
      if (gen === state.generation) notifyError(err);
    }
  }

  /** 存档 + 运行状态/统计 + 事件，一次轮询。 */
  async function poll() {
    if (!state.saveId || state.polling) return renderAll();
    state.polling = true;
    const gen = state.generation;
    try {
      const [save, status, events] = await Promise.all([
        api.getSave(state.saveId),
        api.getAutoTradeStatus(state.saveId),
        api.listAutoTradeEvents(state.saveId),
      ]);
      if (gen !== state.generation) return;
      state.save = /** @type {Record<string, any>} */ (save ?? {});
      state.status = status;
      state.events = parseEvents(events);
      state.lastError = null;
    } catch (err) {
      if (gen === state.generation) {
        const msg = errorMessage(err, t);
        if (msg !== state.lastError) notify(msg, 'error');
        state.lastError = msg;
      }
    } finally {
      state.polling = false;
    }
    renderAll();
  }

  /** @param {string | null} saveId */
  function resetFor(saveId) {
    state.generation += 1;
    state.saveId = saveId;
    state.save = session.get().currentSave ?? null;
    state.status = null;
    state.configs = [];
    state.events = [];
    state.editingId = null;
    state.lastError = null;
    resetForm();
    renderAll();
  }

  // ---------- 渲染 ----------

  function renderAll() {
    renderStatusAndStats();
    renderConfigs();
    renderEvents();
    renderEditState();
    renderProfitOption();
  }

  function renderStatusAndStats() {
    const save = state.save;
    const stats = readStats(state.status);
    const sv = statsView(stats, stats.maxTotal, lang());
    const st = statusOf(state.status, sv.remaining);

    if (el.statusText) el.statusText.textContent = t(st.key);
    if (el.indicator) el.indicator.className = `status-indicator${st.tone ? ` ${st.tone}` : ''}`;
    if (el.startBtn) el.startBtn.disabled = !save?.id || st.enabled;
    if (el.pauseBtn) {
      el.pauseBtn.disabled = !st.enabled;
      el.pauseBtn.textContent = t(st.paused ? 'auto.resume' : 'auto.pause');
    }
    if (el.stopBtn) el.stopBtn.disabled = !st.enabled;
    if (el.resetBtn) el.resetBtn.disabled = !save?.id;

    if (el.stats.total) el.stats.total.textContent = sv.totalText;
    if (el.stats.success) el.stats.success.textContent = sv.successText;
    if (el.stats.failed) el.stats.failed.textContent = sv.failedText;
    if (el.stats.pnl) {
      el.stats.pnl.textContent = sv.pnlText;
      el.stats.pnl.className = `stat-value ${sv.pnlTone}`;
    }
    if (el.stats.remaining) el.stats.remaining.textContent = sv.remainingText;
    if (el.maxTotal) {
      el.maxTotal.value = String(stats.maxTotal);
      el.maxTotal.disabled = true; // 后端暂无设置全局上限的接口（见 frontend/src/features/auto-trade/CLAUDE.md）
    }
  }

  function renderConfigs() {
    const rows = state.configs.map((c) => configRow(c, state.names, t));
    setHtml(
      /** @type {HTMLElement} */ (el.container),
      renderConfigList(rows, {
        emptyText: t('auto.emptyTip'),
        quantityLabel: t('auto.quantityLabel'),
        editText: t('common.edit'),
        deleteText: t('common.delete'),
      }),
    );
  }

  function renderEvents() {
    const rows = state.events.map((e) => eventRow(e, state.names, t, lang()));
    setHtml(/** @type {HTMLElement} */ (el.eventsList), renderEventList(rows, t('auto.noRecords')));
  }

  function renderEditState() {
    if (!el.addBtn) return;
    const editing = state.editingId !== null;
    el.addBtn.textContent = t(editing ? 'common.saveEdit' : 'auto.addStockBtn');
    el.addBtn.dataset.editing = String(editing);
  }

  /** 买入时禁用“盈利目标”选项并显示提示；卖出时恢复（沿用 legacy onAutoTradeDirectionChange）。 */
  function renderProfitOption() {
    if (!el.profitOption || !el.conditionType) return;
    const rules = directionRules(readDirection());
    el.profitOption.disabled = rules.profitDisabled;
    el.profitOption.textContent = t(rules.profitDisabled ? 'auto.profitDisabledOption' : 'auto.conditionTypeProfit');
    const tipHost = el.conditionType.parentElement;
    const tip = doc.getElementById('profit-tip');
    if (rules.profitDisabled) {
      if (!tip && tipHost) tipHost.appendChild(fragment(renderProfitTip(t('auto.profitTip'))));
    } else {
      tip?.remove();
    }
  }

  // ---------- 表单 ----------

  function readDirection() {
    const checked = page.querySelector('input[name="auto-direction"]:checked');
    return /** @type {HTMLInputElement | null} */ (checked)?.value === 'sell' ? 'sell' : 'buy';
  }

  function readForm() {
    const v = (node) => (node?.value ?? '');
    return {
      code: v(el.code).trim(),
      direction: readDirection(),
      conditionType: v(el.conditionType) || 'price',
      operator: v(el.operator) || 'above',
      conditionValue: v(el.conditionValue),
      quantity: v(el.quantity),
      priceType: v(el.priceType) || 'market',
      limitPrice: v(el.limitPrice),
      stopLoss: v(el.stopLoss),
      takeProfit: v(el.takeProfit),
      maxTrades: v(el.maxTrades),
      maxAmount: v(el.maxAmount),
    };
  }

  /** @param {ReturnType<typeof configToForm>} f */
  function fillForm(f) {
    const radio = page.querySelector(`input[name="auto-direction"][value="${f.direction}"]`);
    if (radio instanceof HTMLInputElement) radio.checked = true;
    renderProfitOption();
    if (el.code) el.code.value = f.code;
    updateName();
    if (el.conditionType) el.conditionType.value = f.conditionType;
    if (el.operator) el.operator.value = f.operator;
    if (el.conditionValue) el.conditionValue.value = f.conditionValue;
    if (el.quantity) el.quantity.value = f.quantity;
    if (el.priceType) el.priceType.value = f.priceType;
    if (el.limitPrice) {
      el.limitPrice.value = f.limitPrice;
      el.limitPrice.disabled = f.priceType !== 'limit';
    }
    if (el.stopLoss) el.stopLoss.value = f.stopLoss;
    if (el.takeProfit) el.takeProfit.value = f.takeProfit;
    if (el.maxTrades) el.maxTrades.value = f.maxTrades;
    if (el.maxAmount) el.maxAmount.value = f.maxAmount;
  }

  /** 清空股票相关输入（保留方向与条件类型等下拉，同 legacy）。 */
  function resetForm() {
    if (el.code) el.code.value = '';
    updateName();
    for (const node of [el.quantity, el.conditionValue, el.limitPrice, el.stopLoss, el.takeProfit, el.maxTrades, el.maxAmount]) {
      if (node) node.value = '';
    }
  }

  function updateName() {
    if (!el.name) return;
    const code = el.code?.value.trim() ?? '';
    el.name.textContent = state.stockCodes.has(code) ? state.names.get(code) ?? '' : '';
  }

  function cancelEdit() {
    state.editingId = null;
    resetForm();
    renderEditState();
  }

  /** @param {string} name condition | risk | history */
  function switchTab(name) {
    page.querySelectorAll('.auto-trade-tab').forEach((b) => b.classList.toggle('active', b.getAttribute('data-tab') === name));
    page.querySelectorAll('.auto-trade-form').forEach((p) => p.classList.toggle('active', p.id === `${name}-panel`));
  }

  // ---------- 动作 ----------

  async function submitConfig() {
    const saveId = state.saveId;
    if (!saveId) return notify(t('auto.saveFailedNoSave'), 'error');
    const result = buildConfigPayload(readForm(), {
      stockExists: (code) => state.stockCodes.has(code),
      configs: state.configs,
      editingId: state.editingId,
      t,
    });
    if (!result.ok) return notify(result.message, 'warning');
    const editing = state.editingId;
    try {
      if (editing) {
        await api.updateAutoTradeConfig(saveId, editing, result.payload);
        notify(t('auto.configUpdated'), 'success');
      } else {
        await api.createAutoTradeConfig(saveId, result.payload);
        notify(t('auto.stockAdded'), 'success');
      }
    } catch (err) {
      return notifyError(err);
    }
    cancelEdit();
    await loadConfigs();
    await poll();
  }

  /** @param {string} id */
  function startEdit(id) {
    const config = state.configs.find((c) => String(c.id) === id);
    if (!config) return;
    fillForm(configToForm(config));
    state.editingId = id;
    renderEditState();
    notify(t('auto.editLoaded'));
  }

  /** @param {string} id */
  async function deleteConfig(id) {
    if (!state.saveId) return;
    try {
      await api.deleteAutoTradeConfig(state.saveId, id);
    } catch (err) {
      return notifyError(err);
    }
    if (state.editingId === id) cancelEdit();
    notify(t('auto.stockRemoved'));
    await loadConfigs();
  }

  async function startAuto() {
    const saveId = state.saveId;
    if (!saveId) return;
    if (state.configs.length === 0) return notify(t('auto.requireStock'), 'warning');
    if (!confirmAction(t('auto.startConfirm', { count: state.configs.length }))) return;
    try {
      await api.startAutoTrade(saveId);
    } catch (err) {
      return notifyError(err);
    }
    notify(t('auto.started', { count: state.configs.length }), 'success');
    await poll();
  }

  async function togglePause() {
    const saveId = state.saveId;
    if (!saveId || !state.status) return;
    const paused = Boolean(state.status?.paused);
    try {
      state.status = paused ? await api.resumeAutoTrade(saveId) : await api.pauseAutoTrade(saveId);
    } catch (err) {
      return notifyError(err);
    }
    notify(t(paused ? 'auto.resumed' : 'auto.paused'));
    await poll();
  }

  async function stopAuto() {
    const saveId = state.saveId;
    if (!saveId) return;
    if (!confirmAction(t('auto.stopConfirm'))) return;
    try {
      await api.stopAutoTrade(saveId);
    } catch (err) {
      return notifyError(err);
    }
    notify(t('auto.stopped'));
    await poll();
  }

  async function resetAll() {
    const saveId = state.saveId;
    if (!saveId) return notify(t('auto.resetFailedNoSave'), 'error');
    if (!confirmAction(t('auto.resetConfirm'))) return;
    try {
      await api.resetAutoTrade(saveId);
    } catch (err) {
      return notifyError(err);
    }
    cancelEdit();
    notify(t('auto.configReset'), 'success');
    await loadConfigs();
    await poll();
  }

  /** 按比例填入数量（1/4、1/2、全仓）。 @param {number} ratio */
  async function applyRatio(ratio) {
    const saveId = state.saveId;
    const code = readForm().code;
    const direction = readDirection();
    if (!saveId || !state.stockCodes.has(code)) return notify(t('auto.requireStockCode'), 'warning');
    let holdingQty = 0;
    let cashCents = Number.isInteger(state.save?.cash_cents) ? state.save?.cash_cents : 0;
    let priceCents = null;
    try {
      const [pf, market] = await Promise.all([
        api.getPortfolio(saveId),
        direction === 'buy' ? api.getStockMarket(saveId, code) : Promise.resolve(null),
      ]);
      const pfObj = /** @type {Record<string, any>} */ (pf ?? {});
      const holding = Array.isArray(pfObj.holdings) ? pfObj.holdings.find((h) => h.code === code) : null;
      holdingQty = Number.isFinite(holding?.quantity) ? holding.quantity : 0;
      if (Number.isInteger(pfObj.cash_cents)) cashCents = pfObj.cash_cents;
      priceCents = priceFromMarket(market);
    } catch (err) {
      return notifyError(err);
    }
    const unit = Number.isInteger(state.save?.trade_unit) ? state.save?.trade_unit : 1;
    const qty = ratioQuantity({ direction, ratio, holdingQty, cashCents: cashCents ?? 0, priceCents, unit });
    if (direction === 'buy' && priceCents === null) return notify(t('auto.ratioNoData'), 'warning');
    if (el.quantity) el.quantity.value = qty > 0 ? String(qty) : '';
  }

  // ---------- 轮询与生命周期 ----------

  const tick = setInterval(() => {
    if (isVisible() && !doc.hidden) poll();
  }, POLL_MS);

  const offTabs = delegate(page, 'click', '.auto-trade-tab[data-tab]', (_e, btn) => {
    switchTab(btn.getAttribute('data-tab') ?? 'condition');
  });
  const offDirection = delegate(page, 'change', 'input[name="auto-direction"]', () => renderProfitOption());
  const offRatio = delegate(page, 'click', '.quantity-btns [data-ratio]', (_e, btn) => applyRatio(Number(btn.getAttribute('data-ratio'))));
  const offList = delegate(el.container, 'click', '[data-action]', (_e, btn) => {
    const id = btn.getAttribute('data-id') ?? '';
    if (btn.getAttribute('data-action') === 'edit') startEdit(id);
    else if (btn.getAttribute('data-action') === 'delete') deleteConfig(id);
  });
  const offCode = on(el.code, 'input', updateName);
  const offPrice = el.priceType ? on(el.priceType, 'change', () => {
    if (el.limitPrice) {
      el.limitPrice.disabled = el.priceType?.value !== 'limit';
      if (el.limitPrice.disabled) el.limitPrice.value = '';
    }
  }) : () => {};
  const offAdd = on(el.addBtn, 'click', () => submitConfig());
  const offReset = el.resetBtn ? on(el.resetBtn, 'click', () => resetAll()) : () => {};
  const offStart = on(el.startBtn, 'click', () => startAuto());
  const offPause = el.pauseBtn ? on(el.pauseBtn, 'click', () => togglePause()) : () => {};
  const offStop = el.stopBtn ? on(el.stopBtn, 'click', () => stopAuto()) : () => {};
  const offSelect = on(globalThis, SELECT_STOCK_EVENT, (e) => {
    const detail = /** @type {CustomEvent} */ (e).detail;
    if (!detail || detail.target !== 'auto-trade' || typeof detail.code !== 'string') return;
    if (el.code) el.code.value = detail.code;
    updateName();
    switchTab('condition');
  });

  const unsubSession = session.subscribe((s, prev) => {
    if (s.currentSave !== prev.currentSave || s.tab !== prev.tab || s.screen !== prev.screen) {
      if (currentSaveId() !== state.saveId) {
        resetFor(currentSaveId());
        loadConfigs();
        if (isVisible()) poll();
      } else if (s.currentSave !== prev.currentSave) {
        state.save = s.currentSave ?? null;
        renderAll();
      } else if (isVisible()) {
        poll();
      }
    }
  });
  const unsubLang = i18n.onChange(() => renderAll());

  resetFor(currentSaveId());
  loadNames();
  loadConfigs();
  if (isVisible()) poll();

  return {
    destroy() {
      clearInterval(tick);
      offTabs();
      offDirection();
      offRatio();
      offList();
      offCode();
      offPrice();
      offAdd();
      offReset();
      offStart();
      offPause();
      offStop();
      offSelect();
      unsubSession();
      unsubLang();
      doc.getElementById('profit-tip')?.remove();
    },
  };
}
