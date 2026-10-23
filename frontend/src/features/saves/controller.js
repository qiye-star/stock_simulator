/**
 * 存档流程（移植自 legacy/game.js showSaveSelect 1248、renderSaveList 1258-1315、
 * startGame 1322-1386、deleteSave 1560、rename 1567-1636）。
 *
 * 数据全部来自 REST：GET/POST/PATCH/DELETE /saves。列表以 session.savesRev 驱动刷新。
 * 进入存档：GET /saves/{id} -> setCurrentSave -> 主界面。
 */
import * as api from '../../api/endpoints.js';
import { i18n } from '../../i18n/i18n.js';
import { errorMessage } from '../../i18n/errors.js';
import { formatMoney } from '../../ui/format.js';
import { showNotification } from '../../ui/notify.js';
import { closeModal, openModal } from '../../ui/modal.js';
import { delegate, on, setHtml } from '../../ui/dom.js';
import { SCREENS, bumpSaves, session, setCurrentSave, showScreen } from '../../state/session.js';
import { buildCreateSaveRequest, validateSaveName } from './validators.js';
import { normalizeSaveList, toSaveCard } from './viewModel.js';
import { renderSaveList } from './view.js';

const LIST_ID = 'save-list';
const RENAME_MODAL = 'rename-save-modal';

/** @type {Record<string, unknown>[]} 最近一次拉取的存档 */
let saves = [];
let renameTargetId = /** @type {string | null} */ (null);


/** 按当前语言重绘列表（不发请求）。 */
function paint(doc) {
  const listEl = doc.getElementById(LIST_ID);
  if (!listEl) return;
  const env = { lang: i18n.getLanguage(), t: (k, p) => i18n.t(k, p), formatMoney };
  const cards = saves.map((s, i) => toSaveCard(s, i, env));
  setHtml(listEl, renderSaveList(cards, (k) => i18n.t(k)));
}

/** 从服务端拉取并重绘。 */
export async function refreshSaves(doc = document) {
  try {
    saves = normalizeSaveList(await api.listSaves());
  } catch (err) {
    showNotification(errorMessage(err, (k) => i18n.t(k)), 'error');
    return;
  }
  paint(doc);
}

/**
 * 进入存档：拉取最新数据后切到主界面。
 * @param {string} id
 */
export async function enterSave(id, doc = document) {
  try {
    const save = await api.getSave(id);
    setCurrentSave(/** @type {Record<string, unknown>} */ (save));
    showScreen(SCREENS.MAIN, doc);
  } catch (err) {
    showNotification(errorMessage(err, (k) => i18n.t(k)), 'error');
  }
}

/** @param {string} id @param {Document} doc */
function openRename(id, doc) {
  const index = saves.findIndex((s) => s.id === id);
  if (index < 0) return;
  renameTargetId = id;
  const save = saves[index];
  const current = typeof save.name === 'string' && save.name.trim() ? save.name : i18n.t('save.defaultName', { index: index + 1 });
  const input = doc.getElementById('rename-save-input');
  if (input instanceof HTMLInputElement) input.value = current;
  const err = doc.getElementById('rename-save-error');
  if (err) err.textContent = '';
  openModal(RENAME_MODAL);
  setTimeout(() => (input instanceof HTMLInputElement ? input.focus() : undefined), 100);
}

function closeRename() {
  renameTargetId = null;
  closeModal(RENAME_MODAL);
}

async function confirmRename(doc) {
  const input = doc.getElementById('rename-save-input');
  const errEl = doc.getElementById('rename-save-error');
  const result = validateSaveName(input instanceof HTMLInputElement ? input.value : '');
  if ('error' in result) {
    if (errEl) errEl.textContent = i18n.t(result.error);
    return;
  }
  if (!renameTargetId) return closeRename();
  const id = renameTargetId;
  try {
    const updated = await api.updateSave(id, { name: result.name });
    if (session.get().currentSave?.id === id) {
      setCurrentSave({ ...session.get().currentSave, ...(typeof updated === 'object' && updated ? updated : {}), name: result.name });
    }
  } catch (err) {
    if (errEl) errEl.textContent = errorMessage(err, (k) => i18n.t(k));
    return;
  }
  closeRename();
  bumpSaves();
  showNotification(i18n.t('save.renameSuccess'), 'success');
}

async function deleteSave(id) {
  if (!globalThis.confirm?.(i18n.t('save.deleteConfirm'))) return;
  try {
    await api.deleteSave(id);
  } catch (err) {
    showNotification(errorMessage(err, (k) => i18n.t(k)), 'error');
    return;
  }
  if (session.get().currentSave?.id === id) setCurrentSave(null);
  bumpSaves();
}

/** 读取开局表单并创建存档。 */
async function startGame(doc) {
  const checked = (name) => doc.querySelector(`input[name="${name}"]:checked`);
  const fundRadio = checked('fund-type');
  const unitRadio = checked('trade-unit');
  const val = (id) => {
    const el = doc.getElementById(id);
    return el instanceof HTMLInputElement ? el.value : '';
  };
  const t0 = doc.getElementById('t0-mode');

  const built = buildCreateSaveRequest({
    fundType: fundRadio instanceof HTMLInputElement && fundRadio.value === 'custom' ? 'custom' : 'random',
    customWan: val('custom-fund'),
    buyFeePct: val('buy-fee'),
    sellFeePct: val('sell-fee'),
    t0Mode: t0 instanceof HTMLInputElement && t0.checked,
    tradeUnit: unitRadio instanceof HTMLInputElement && unitRadio.value === '100' ? 100 : 1,
  });
  if ('error' in built) {
    showNotification(i18n.t(built.error), 'error');
    return;
  }
  try {
    const save = await api.createSave(built.body);
    setCurrentSave(/** @type {Record<string, unknown>} */ (save));
    bumpSaves();
    showScreen(SCREENS.MAIN, doc);
  } catch (err) {
    showNotification(errorMessage(err, (k) => i18n.t(k)), 'error');
  }
}

/** 自定义资金输入框仅在选中「自定义」时可用（同 legacy）。 */
function syncFundInput(doc) {
  const custom = doc.querySelector('input[name="fund-type"][value="custom"]');
  const input = doc.getElementById('custom-fund');
  if (input instanceof HTMLInputElement) input.disabled = !(custom instanceof HTMLInputElement && custom.checked);
}

/**
 * 绑定存档页事件，并订阅会话变化。返回解绑函数。
 * @param {Document} [doc=document]
 * @returns {() => void}
 */
export function initSavesController(doc = document) {
  const offs = [];
  const bind = (id, type, fn) => {
    const el = doc.getElementById(id);
    if (el) offs.push(on(el, type, fn));
  };

  offs.push(
    delegate(doc.getElementById(LIST_ID) ?? doc, 'click', '[data-action]', (event, el) => {
      event.stopPropagation();
      const id = /** @type {HTMLElement} */ (el).dataset.saveId ?? '';
      const action = /** @type {HTMLElement} */ (el).dataset.action;
      if (action === 'enter') enterSave(id, doc);
      else if (action === 'rename') openRename(id, doc);
      else if (action === 'delete') deleteSave(id);
    }),
  );

  bind('new-game-btn', 'click', () => showScreen(SCREENS.SETUP, doc));
  bind('start-game-btn', 'click', () => startGame(doc));
  bind('setup-back-btn', 'click', () => showScreen(SCREENS.SAVE_SELECT, doc));
  bind('confirm-rename-btn', 'click', () => confirmRename(doc));
  bind('cancel-rename-btn', 'click', closeRename);
  bind('rename-save-input', 'keydown', (e) => {
    if (/** @type {KeyboardEvent} */ (e).key === 'Enter') confirmRename(doc);
  });
  for (const radio of doc.querySelectorAll('input[name="fund-type"]')) {
    offs.push(on(radio, 'change', () => syncFundInput(doc)));
  }
  syncFundInput(doc);

  // 进入存档选择页或存档列表版本变化时拉取；语言变化时仅重绘
  let prev = session.get();
  offs.push(
    session.subscribe((state) => {
      const entered = state.screen !== prev.screen && state.screen === SCREENS.SAVE_SELECT;
      const changed = state.savesRev !== prev.savesRev && state.screen === SCREENS.SAVE_SELECT;
      prev = state;
      if (entered || changed) refreshSaves(doc);
    }),
  );
  offs.push(
    i18n.onChange(() => {
      if (session.get().screen === SCREENS.SAVE_SELECT) paint(doc);
    }),
  );

  // 模块可能晚于会话恢复挂载：若已在存档选择页，立即拉取一次
  if (session.get().screen === SCREENS.SAVE_SELECT) refreshSaves(doc);

  return () => {
    for (const off of offs) off();
  };
}
