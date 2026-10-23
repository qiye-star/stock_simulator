/**
 * 设置流程（移植自 legacy/game.js setTheme 4428、toggleTheme 4441、
 * 设置面板事件 709-730、时间控制 1890-2004 的 REST 版）。
 *
 * - 主题 / 语言 / 刷新速度 / 教程标记：PATCH /me（仅登录后；未登录只作用于本地）。
 * - 主题应用：写入 appStore.theme，由 main.js 的订阅调用 applyTheme。
 * - 时间暂停 / 跳过：POST /saves/{id}/clock/{pause|resume|skip}。
 */
import * as api from '../../api/endpoints.js';
import { i18n, isSupportedLang } from '../../i18n/i18n.js';
import { errorMessage } from '../../i18n/errors.js';
import { appStore } from '../../state/store.js';
import { session, setCurrentSave, setUser } from '../../state/session.js';
import { normalizeTheme, nextTheme } from '../../ui/theme.js';
import { showNotification } from '../../ui/notify.js';
import { closeModal, openModal } from '../../ui/modal.js';
import { on } from '../../ui/dom.js';
import { clockButtonKey, diffPreferences, parseRefreshRate } from './prefs.js';
import { setPauseLabel, setThemeToggleIcon, syncSettingsForm } from './view.js';

const MODAL = 'settings-modal';


/**
 * 登录状态下把偏好写回服务端；未登录只改本地。
 * @param {Partial<Record<'theme' | 'lang' | 'refresh_rate_ms' | 'tutorial_completed', unknown>>} patch
 */
export async function savePreference(patch) {
  const user = session.get().user;
  if (!user) return;
  const changes = diffPreferences(/** @type {Record<string, unknown>} */ (user), patch);
  if (Object.keys(changes).length === 0) return;
  try {
    const updated = await api.updateMe(/** @type {import('../../api/endpoints.js').MePatch} */ (changes));
    setUser(updated);
  } catch (err) {
    showNotification(errorMessage(err, (k) => i18n.t(k)), 'error');
  }
}

/** @param {string} raw */
export function setTheme(raw) {
  const theme = normalizeTheme(raw);
  appStore.set({ theme });
  setThemeToggleIcon(theme);
  savePreference({ theme });
}

/** @param {string} raw */
function setLanguage(raw) {
  if (isSupportedLang(raw)) i18n.setLanguage(raw);
}

function syncFromUser(doc) {
  const user = session.get().user;
  const theme = normalizeTheme(appStore.get().theme);
  syncSettingsForm(
    {
      theme,
      refreshRate: user?.refresh_rate_ms ?? 3000,
      lang: i18n.getLanguage(),
    },
    doc,
  );
  refreshClockLabel();
}

function refreshClockLabel() {
  const save = session.get().currentSave;
  setPauseLabel(i18n.t(clockButtonKey(Boolean(save?.paused))));
}

async function toggleClock() {
  const save = session.get().currentSave;
  if (!save || typeof save.id !== 'string') {
    showNotification(i18n.t('notification.requireGame'), 'warning');
    return;
  }
  const wasPaused = Boolean(save.paused);
  try {
    const res = wasPaused ? await api.resumeClock(save.id) : await api.pauseClock(save.id);
    const paused = res && typeof res === 'object' && typeof res.paused === 'boolean' ? res.paused : !wasPaused;
    setCurrentSave({ ...save, paused });
  } catch (err) {
    showNotification(errorMessage(err, (k) => i18n.t(k)), 'error');
    return;
  }
  refreshClockLabel();
  showNotification(i18n.t(wasPaused ? 'notification.timeResumed' : 'notification.timePaused'), 'success');
}

async function skipClock() {
  const save = session.get().currentSave;
  if (!save || typeof save.id !== 'string') {
    showNotification(i18n.t('notification.requireGame'), 'warning');
    return;
  }
  try {
    await api.skipClock(save.id);
  } catch (err) {
    showNotification(errorMessage(err, (k) => i18n.t(k)), 'error');
    return;
  }
  showNotification(i18n.t('notification.skipCompleted'), 'success');
}

/**
 * 绑定设置面板与主题按钮。返回解绑函数。
 * @param {Document} [doc=document]
 * @returns {() => void}
 */
export function initSettingsController(doc = document) {
  const offs = [];
  const bind = (id, type, fn) => {
    const el = doc.getElementById(id);
    if (el) offs.push(on(el, type, fn));
  };

  bind('settings-btn', 'click', () => {
    syncFromUser(doc);
    openModal(MODAL);
  });
  bind('close-settings', 'click', () => closeModal(MODAL));
  bind('theme-toggle', 'click', () => setTheme(nextTheme(normalizeTheme(appStore.get().theme))));
  bind('theme-select', 'change', (e) => setTheme(/** @type {HTMLSelectElement} */ (e.target).value));
  bind('refresh-rate', 'change', (e) => {
    const rate = parseRefreshRate(/** @type {HTMLSelectElement} */ (e.target).value);
    if (rate !== null) savePreference({ refresh_rate_ms: rate });
  });
  bind('language-select', 'change', (e) => setLanguage(/** @type {HTMLSelectElement} */ (e.target).value));
  bind('time-pause-btn', 'click', toggleClock);
  bind('time-skip-btn', 'click', skipClock);

  // 主题变化（含登录后由 applyUserPreferences 写入）同步按钮图标与下拉框
  offs.push(
    appStore.subscribe((state, prev) => {
      if (state.theme !== prev.theme) {
        setThemeToggleIcon(normalizeTheme(state.theme));
        syncSettingsForm({ theme: normalizeTheme(state.theme), refreshRate: session.get().user?.refresh_rate_ms ?? 3000, lang: i18n.getLanguage() }, doc);
      }
    }),
  );

  // 语言变化：同步下拉框、时间按钮文案，并写回服务端（仅在与用户记录不同时）
  offs.push(
    i18n.onChange((lang) => {
      const select = doc.getElementById('language-select');
      if (select instanceof HTMLSelectElement) select.value = lang;
      refreshClockLabel();
      savePreference({ lang });
    }),
  );

  // 登录用户或当前存档变化时刷新时间按钮文案
  let prev = session.get();
  offs.push(
    session.subscribe((state) => {
      if (state.currentSave !== prev.currentSave) refreshClockLabel();
      prev = state;
    }),
  );

  setThemeToggleIcon(normalizeTheme(appStore.get().theme), doc);
  return () => {
    for (const off of offs) off();
  };
}
