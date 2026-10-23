/**
 * 个人页流程（移植自 legacy/game.js updateProfile 3769-3843、toggleAchievements 3845-3864、
 * exportSave 4840-4849）。数据：GET /me（session.user）、GET /saves、
 * GET /achievements/catalog、GET /saves/{id}/achievements。
 */
import * as api from '../../api/endpoints.js';
import { i18n } from '../../i18n/i18n.js';
import { errorMessage } from '../../i18n/errors.js';
import { session, showScreen, SCREENS } from '../../state/session.js';
import { showNotification } from '../../ui/notify.js';
import { on, setHtml } from '../../ui/dom.js';
import { ACHIEVEMENT_META } from './achievementsMeta.js';
import {
  buildAchievementCards,
  countUnlockedByLevel,
  needsExpandToggle,
  profileStats,
  unlockedIdsFrom,
} from './viewModel.js';
import { renderAchievementCards } from './view.js';

const EXPANDED_KEY = 'achievements-expanded';
/** 收起时列表的高度：6 张卡片 + 5 个间隙（同 legacy）。 */
const CARD_HEIGHT = 80;
const GAP = 15;


function readExpanded() {
  try {
    return globalThis.localStorage?.getItem(EXPANDED_KEY) === 'true';
  } catch {
    return false;
  }
}

function writeExpanded(value) {
  try {
    globalThis.localStorage?.setItem(EXPANDED_KEY, String(value));
  } catch {
    /* 忽略：仅为个人偏好 */
  }
}

/** @param {HTMLElement} listEl @param {number} total @param {boolean} expanded */
function applyListHeight(listEl, total, expanded) {
  const collapsed = CARD_HEIGHT * 6 + GAP * 5;
  const full = CARD_HEIGHT * total + GAP * Math.max(0, total - 1);
  listEl.style.maxHeight = `${expanded ? Math.max(full, collapsed) : collapsed}px`;
}

/** 成就目录缓存（静态，获取一次）。 */
let catalogCache = /** @type {unknown} */ (null);

async function loadCatalog() {
  if (catalogCache) return catalogCache;
  try {
    catalogCache = await api.getAchievementCatalog();
  } catch {
    catalogCache = null; // 回退到静态元数据
  }
  return catalogCache;
}

/** 重绘个人页（用户、统计、成就墙）。 */
export async function renderProfile(doc = document) {
  const user = session.get().user;
  if (!user) return;

  const setText = (id, text) => {
    const el = doc.getElementById(id);
    if (el) el.textContent = text;
  };
  setText('profile-username', user.username);
  setText('reg-time', formatDate(user.created_at));

  let saves = [];
  try {
    const list = await api.listSaves();
    saves = Array.isArray(list) ? list.filter((s) => s && typeof s === 'object') : [];
  } catch (err) {
    showNotification(errorMessage(err, (k) => i18n.t(k)), 'error');
  }

  const save = session.get().currentSave;
  let unlocked = new Set();
  if (save && typeof save.id === 'string') {
    try {
      unlocked = unlockedIdsFrom(await api.getSaveAchievements(save.id));
    } catch (err) {
      showNotification(errorMessage(err, (k) => i18n.t(k)), 'error');
    }
  }

  const catalog = await loadCatalog();
  const cards = buildAchievementCards(catalog, unlocked, ACHIEVEMENT_META);
  const counts = countUnlockedByLevel(cards);
  const stats = profileStats(saves, unlocked.size, cards.length);

  setText('stat-games', String(stats.games));
  setText('stat-trades', String(stats.trades));
  setText('stat-achievements', stats.achievements);
  setText('count-bronze', String(counts.bronze));
  setText('count-silver', String(counts.silver));
  setText('count-gold', String(counts.gold));
  setText('count-legend', String(counts.legend));

  const listEl = doc.getElementById('achievements-list');
  if (listEl) {
    setHtml(listEl, renderAchievementCards(cards, (k) => i18n.t(k)));
    const toggle = doc.getElementById('toggle-achievements-btn');
    const expanded = readExpanded();
    if (toggle) {
      toggle.style.display = needsExpandToggle(cards.length) ? 'block' : 'none';
      toggle.textContent = i18n.t(expanded ? 'profile.collapse' : 'profile.expandAll');
    }
    applyListHeight(listEl, cards.length, expanded);
  }
}

/** @param {string | undefined} iso */
function formatDate(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString(i18n.getLanguage()) : '--';
}

/** 导出当前存档为版本化 JSON（下载 .json；后端导出格式不是旧版文本，不能回灌 legacy 导入）。 */
async function exportCurrentSave(doc) {
  const save = session.get().currentSave;
  const user = session.get().user;
  if (!save || typeof save.id !== 'string' || !user) {
    showNotification(i18n.t('notification.requireGame'), 'warning');
    return;
  }
  let data;
  try {
    data = await api.exportSave(save.id);
  } catch (err) {
    showNotification(errorMessage(err, (k) => i18n.t(k)), 'error');
    return;
  }
  const text = JSON.stringify(data, null, 2);
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
  const a = doc.createElement('a');
  a.href = url;
  a.download = `stock_simulator_save_${user.username}_${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * 绑定个人页按钮并订阅相关状态。返回解绑函数。
 * @param {Document} [doc=document]
 * @returns {() => void}
 */
export function initProfileController(doc = document) {
  const offs = [];
  const bind = (id, type, fn) => {
    const el = doc.getElementById(id);
    if (el) offs.push(on(el, type, fn));
  };

  bind('toggle-achievements-btn', 'click', () => {
    const next = !readExpanded();
    writeExpanded(next);
    const listEl = doc.getElementById('achievements-list');
    const count = listEl ? listEl.children.length : 0;
    if (listEl) applyListHeight(listEl, count, next);
    const toggle = doc.getElementById('toggle-achievements-btn');
    if (toggle) toggle.textContent = i18n.t(next ? 'profile.collapse' : 'profile.expandAll');
  });
  bind('export-save-btn', 'click', () => exportCurrentSave(doc));
  bind('new-game-from-profile', 'click', () => showScreen(SCREENS.SETUP, doc));
  bind('switch-save-btn', 'click', () => showScreen(SCREENS.SAVE_SELECT, doc));

  const isVisible = (s) => s.screen === SCREENS.MAIN && s.tab === 'profile';
  let prev = session.get();
  offs.push(
    session.subscribe((state) => {
      const tabChanged = state.tab !== prev.tab && isVisible(state);
      const saveChanged = state.currentSave !== prev.currentSave && isVisible(state);
      const userChanged = state.user !== prev.user && isVisible(state);
      prev = state;
      if (tabChanged || saveChanged || userChanged) renderProfile(doc);
    }),
  );
  offs.push(
    i18n.onChange(() => {
      if (isVisible(session.get())) renderProfile(doc);
    }),
  );

  return () => {
    for (const off of offs) off();
  };
}

