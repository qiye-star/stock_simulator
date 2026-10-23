/**
 * 调试面板控制器：连续点击个人主页 5 次打开；所有动作经 POST /saves/{id}/debug/*。
 * 服务端未开启（DEBUG_DISABLED）时，面板顶部给出明确提示并禁用动作。
 * 原版参考：legacy/game.js 812-824（打开）、4450-4830（动作）。
 */
import * as api from '../../api/endpoints.js';
import { ErrorCode, errorMessage } from '../../i18n/errors.js';
import { delegate, on, setHtml } from '../../ui/dom.js';
import { closeModal, openModal } from '../../ui/modal.js';
import { showNotification } from '../../ui/notify.js';
import { session, setCurrentSave } from '../../state/session.js';
import {
  TIME_PRESETS,
  achievementNames,
  achievementOptions,
  clockFromMinute,
  formatHM,
  nextTapState,
  parseClockInput,
  parseFundInput,
  parseUnlocked,
  timeStatus,
} from './model.js';
import { renderAchievementOptions, renderClearList, renderNotice } from './view.js';

export const MODAL_ID = 'debug-modal';
const PROFILE_HEADER = '.profile-header';

/**
 * @param {{ i18n: import('../../i18n/i18n.js').I18n, doc?: Document }} env
 * @returns {{ destroy: () => void }}
 */
export function createDebugController({ i18n, doc = document }) {
  const modal = doc.getElementById(MODAL_ID);
  if (!modal) return { destroy() {} };
  const q = (id) => /** @type {HTMLElement | null} */ (doc.getElementById(id));
  const el = {
    fund: /** @type {HTMLInputElement | null} */ (q('debug-fund')),
    setFund: q('set-fund-btn'),
    achievement: /** @type {HTMLSelectElement | null} */ (q('debug-achievement')),
    unlockOne: q('unlock-achievement-btn'),
    unlockAll: q('unlock-all-achievements-btn'),
    clearAll: q('clear-all-achievements-btn'),
    clearSelected: q('clear-selected-achievements-btn'),
    currentTime: q('debug-current-time'),
    timeStatus: q('debug-time-status'),
    hour: /** @type {HTMLInputElement | null} */ (q('debug-hour')),
    minute: /** @type {HTMLInputElement | null} */ (q('debug-minute')),
    setTime: q('set-time-btn'),
    resetMarket: q('reset-market-btn'),
    clearGame: q('clear-game-btn'),
    close: q('close-debug'),
  };
  const presetIds = Object.keys(TIME_PRESETS).concat('random').map((n) => `time-preset-${n}`);
  const presetBtns = presetIds.map((id) => q(id)).filter(Boolean);
  const actionEls = [
    el.fund, el.setFund, el.achievement, el.unlockOne, el.unlockAll, el.clearAll, el.clearSelected,
    el.hour, el.minute, el.setTime, el.resetMarket, el.clearGame, ...presetBtns,
  ].filter(Boolean);

  // 顶部提示与“取消解锁”列表的宿主节点（由本模块创建，插在面板内）。
  const noticeHost = doc.createElement('div');
  noticeHost.id = 'debug-notice-host';
  const title = modal.querySelector('h3');
  if (title) title.after(noticeHost);
  else modal.querySelector('.modal-content')?.prepend(noticeHost);
  const clearHost = doc.createElement('div');
  clearHost.id = 'debug-clear-host';
  el.clearSelected?.parentElement?.appendChild(clearHost);

  const t = (key, params) => i18n.t(key, params);

  const state = {
    disabled: false, // 服务端返回 DEBUG_DISABLED 后置 true，本页面生命周期内不再发请求
    /** @type {Array<{ id: string, level?: string }> | null} */
    catalog: null,
    tap: { count: 0, last: 0 },
  };

  // ---------- 通用 ----------

  /** @returns {string | null} */
  function currentSaveId() {
    const save = session.get().currentSave;
    return typeof save?.id === 'string' ? save.id : null;
  }

  function notify(msg, type = 'info') {
    showNotification(msg, type, { doc });
  }

  /** @param {unknown} err */
  function handleError(err) {
    if (/** @type {any} */ (err)?.code === ErrorCode.DEBUG_DISABLED) {
      state.disabled = true;
      refreshNotice();
      applyDisabled();
      notify(t('debug.disabled'), 'error');
      return;
    }
    notify(errorMessage(err, t), 'error');
  }

  /** 回读存档，保证时间与资金显示与服务端一致。 @param {string} saveId */
  async function syncSave(saveId) {
    try {
      const fresh = await api.getSave(saveId);
      if (currentSaveId() === saveId) setCurrentSave(/** @type {Record<string, unknown>} */ (fresh));
    } catch {
      /* 回读失败不影响已完成的调试动作 */
    }
  }

  /**
   * 执行一个调试动作：检查存档与可用性，失败统一提示。
   * @param {(saveId: string) => Promise<unknown>} fn
   * @param {(res: unknown) => void} [onOk]
   */
  async function run(fn, onOk) {
    const saveId = currentSaveId();
    if (!saveId) return notify(t('debug.noSave'), 'warning');
    if (state.disabled) return notify(t('debug.disabled'), 'warning');
    try {
      const res = await fn(saveId);
      onOk?.(res);
      await syncSave(saveId);
    } catch (err) {
      handleError(err);
    }
  }

  // ---------- 渲染 ----------

  function refreshNotice() {
    const text = state.disabled ? t('debug.disabled') : currentSaveId() ? null : t('debug.noSave');
    setHtml(noticeHost, renderNotice(text));
  }

  function applyDisabled() {
    const off = state.disabled || !currentSaveId();
    for (const node of actionEls) {
      /** @type {HTMLButtonElement} */ (node).disabled = off;
    }
  }

  function refreshTime() {
    const save = session.get().currentSave;
    const minute = Number.isInteger(save?.clock_minute) ? /** @type {number} */ (save?.clock_minute) : null;
    if (minute === null) {
      if (el.currentTime) el.currentTime.textContent = '--:--';
      if (el.timeStatus) el.timeStatus.textContent = '--';
      return;
    }
    const { hour, minute: min } = clockFromMinute(minute);
    if (el.currentTime) el.currentTime.textContent = formatHM(hour, min);
    const st = timeStatus(minute);
    if (el.timeStatus) {
      el.timeStatus.textContent = t(st.key);
      el.timeStatus.style.color = st.color;
    }
    if (el.hour && doc.activeElement !== el.hour) el.hour.value = String(hour);
    if (el.minute && doc.activeElement !== el.minute) el.minute.value = String(min);
  }

  /** 成就下拉（目录缓存；语言切换时重绘）。 */
  async function loadCatalog() {
    if (!state.catalog) {
      const list = await api.getAchievementCatalog();
      state.catalog = Array.isArray(list) ? /** @type {any[]} */ (list) : [];
    }
    if (el.achievement) {
      const current = el.achievement.value;
      setHtml(el.achievement, renderAchievementOptions(achievementOptions(state.catalog, t)));
      if (current) el.achievement.value = current;
    }
    return state.catalog;
  }

  // ---------- 动作 ----------

  async function setFund() {
    const parsed = parseFundInput(el.fund?.value);
    if (!parsed.ok) return notify(t(parsed.key), 'warning');
    const cents = parsed.amountCents;
    await run((saveId) => api.debugFund(saveId, { cash_cents: cents }), () => notify(t('debug.fundModified'), 'success'));
  }

  /** @param {number} hour @param {number} minute */
  async function applyTime(hour, minute) {
    await run((saveId) => api.debugTime(saveId, { minute_of_day: hour * 60 + minute }), () =>
      notify(t('debug.timeSet', { time: formatHM(hour, minute) }), 'success'),
    );
  }

  async function setTime() {
    const parsed = parseClockInput(el.hour?.value, el.minute?.value);
    if (!parsed.ok) return notify(t(parsed.key), 'warning');
    await applyTime(parsed.hour, parsed.minute);
  }

  /** @param {string} name 预设名（不含前缀） */
  async function applyPreset(name) {
    let hour;
    let minute;
    if (name === 'random') {
      hour = Math.floor(Math.random() * 24);
      minute = Math.floor(Math.random() * 60);
    } else {
      [hour, minute] = TIME_PRESETS[name];
    }
    if (el.hour) el.hour.value = String(hour);
    if (el.minute) el.minute.value = String(minute);
    await applyTime(hour, minute);
  }

  async function unlockOne() {
    const id = el.achievement?.value;
    if (!id) return;
    await run((saveId) => api.debugAchievements(saveId, { action: 'unlock', ids: [id] }), () =>
      notify(t('debug.unlockOneSuccess'), 'success'),
    );
  }

  /** 读取已解锁列表（失败抛出，由调用方统一提示）。 @param {string} saveId */
  async function unlockedIds(saveId) {
    return parseUnlocked(await api.getSaveAchievements(saveId));
  }

  async function unlockAll() {
    const saveId = currentSaveId();
    if (!saveId) return notify(t('debug.noSave'), 'warning');
    if (state.disabled) return notify(t('debug.disabled'), 'warning');
    try {
      const catalog = await loadCatalog();
      const unlocked = await unlockedIds(saveId);
      const locked = catalog.map((a) => a.id).filter((id) => !unlocked.includes(id));
      if (locked.length === 0) return notify(t('debug.allUnlocked'), 'info');
      const list = achievementNames(locked, t);
      const win = doc.defaultView;
      if (win && !win.confirm(t('debug.unlockAllConfirm', { count: locked.length, list }))) return;
      await api.debugAchievements(saveId, { action: 'unlock_all' });
      notify(t('debug.unlockAllSuccess', { count: locked.length, list }), 'success');
      await syncSave(saveId);
    } catch (err) {
      handleError(err);
    }
  }

  async function clearAll() {
    const saveId = currentSaveId();
    if (!saveId) return notify(t('debug.noSave'), 'warning');
    if (state.disabled) return notify(t('debug.disabled'), 'warning');
    try {
      const unlocked = await unlockedIds(saveId);
      if (unlocked.length === 0) return notify(t('debug.noUnlocked'), 'info');
      const win = doc.defaultView;
      if (win && !win.confirm(t('debug.clearAllConfirm', { count: unlocked.length }))) return;
      await api.debugAchievements(saveId, { action: 'clear_all' });
      notify(t('debug.clearAllSuccess'), 'success');
      await syncSave(saveId);
    } catch (err) {
      handleError(err);
    }
  }

  /** 打开“取消解锁所选”列表（复选框 + 确认按钮）。 */
  async function openClearSelected() {
    const saveId = currentSaveId();
    if (!saveId) return notify(t('debug.noSave'), 'warning');
    if (state.disabled) return notify(t('debug.disabled'), 'warning');
    try {
      const unlocked = await unlockedIds(saveId);
      if (unlocked.length === 0) return notify(t('debug.noUnlocked'), 'info');
      const catalog = await loadCatalog();
      const byId = new Map(catalog.map((a) => [a.id, a]));
      const opts = unlocked.map((id) => ({ id, level: byId.get(id)?.level }));
      const rows = achievementOptions(opts, t);
      setHtml(clearHost, renderClearList(rows, t('debug.confirmClear')));
    } catch (err) {
      handleError(err);
    }
  }

  async function confirmClearSelected() {
    const saveId = currentSaveId();
    if (!saveId) return;
    const ids = Array.from(clearHost.querySelectorAll('input[name="debug-clear-ach"]:checked')).map((n) => /** @type {HTMLInputElement} */ (n).value);
    if (ids.length === 0) return notify(t('debug.requireSelect'), 'warning');
    const win = doc.defaultView;
    if (win && !win.confirm(t('debug.clearSelectedConfirm', { count: ids.length }))) return;
    try {
      await api.debugAchievements(saveId, { action: 'lock', ids });
      clearHost.replaceChildren();
      notify(t('debug.clearSelectedSuccess', { count: ids.length }), 'success');
      await syncSave(saveId);
    } catch (err) {
      handleError(err);
    }
  }

  async function resetMarket() {
    await run((saveId) => api.debugResetMarket(saveId), () => notify(t('debug.marketReset'), 'success'));
  }

  async function clearGame() {
    const win = doc.defaultView;
    if (win && !win.confirm(t('debug.clearGameConfirm'))) return;
    await run((saveId) => api.debugClear(saveId), () => notify(t('debug.gameCleared'), 'success'));
  }

  // ---------- 打开 / 关闭 ----------

  function openPanel() {
    refreshNotice();
    refreshTime();
    applyDisabled();
    openModal(modal);
    if (currentSaveId() && !state.disabled) {
      loadCatalog().catch(handleError);
    }
  }

  // ---------- 绑定 ----------

  const offTap = on(doc, 'click', (e) => {
    const target = /** @type {Event} */ (e).target;
    if (!(target instanceof Element) || !target.closest(PROFILE_HEADER)) return;
    state.tap = nextTapState(state.tap, Date.now());
    if (state.tap.open) openPanel();
  });
  /** @param {HTMLElement | null} node */
  const bind = (node, type, fn) => (node ? on(node, type, fn) : () => {});
  const offs = [
    bind(el.setFund, 'click', () => setFund()),
    bind(el.unlockOne, 'click', () => unlockOne()),
    bind(el.unlockAll, 'click', () => unlockAll()),
    bind(el.clearAll, 'click', () => clearAll()),
    bind(el.clearSelected, 'click', () => openClearSelected()),
    bind(el.setTime, 'click', () => setTime()),
    bind(el.resetMarket, 'click', () => resetMarket()),
    bind(el.clearGame, 'click', () => clearGame()),
    bind(el.close, 'click', () => closeModal(modal)),
    delegate(clearHost, 'click', '#debug-clear-selected-confirm', () => confirmClearSelected()),
    ...presetBtns.map((btn) => bind(btn, 'click', () => applyPreset(String(btn.id).replace(/^time-preset-/, '')))),
  ];
  const unsubSession = session.subscribe((s, prev) => {
    if (s.currentSave !== prev.currentSave) {
      refreshTime();
      refreshNotice();
      applyDisabled();
    }
  });
  const unsubLang = i18n.onChange(() => {
    refreshTime();
    refreshNotice();
    if (state.catalog && el.achievement) loadCatalog().catch(() => {});
  });

  refreshNotice();
  applyDisabled();

  return {
    destroy() {
      offTap();
      offs.forEach((off) => off());
      unsubSession();
      unsubLang();
      noticeHost.remove();
      clearHost.remove();
    },
  };
}
