/**
 * 会话状态与屏幕/标签切换（移植自 legacy/game.js showScreen 4960-4985、switchTab 4987-5019）。
 *
 * 这是跨功能共享的唯一会话入口，sibling 功能模块只能通过这里读写以下 key：
 *   - user         当前用户（GET /me 的 UserOut），未登录为 null
 *   - currentSave  当前存档（GET /saves/{id} 的结果），未进入存档为 null
 *   - screen       当前屏幕 id（如 'main-screen'）
 *   - tab          当前主页面的 DOM 名（'market' | 'trade' | 'auto-trade' | 'portfolio' | 'profile'）
 *   - savesRev     存档列表版本号；存档被增删改时 bumpSaves() 递增，驱动列表刷新
 *
 * 订阅：session.subscribe((state, prev) => ...)；读取：session.get()。
 * 注意：user 与 appStore.user 同步（见 setUser）；currentSave 与 appStore.currentSaveId 同步。
 */
import { appStore, createStore } from './store.js';

/** 屏幕 id（与 index.html 的 .screen 元素 id 一致）。 */
export const SCREENS = Object.freeze({
  AUTH: 'auth-screen',
  SAVE_SELECT: 'save-select-screen',
  SETUP: 'game-setup-screen',
  MAIN: 'main-screen',
});

/** 需要登录才能访问的屏幕；未登录时强制回到登录页（同 legacy）。 */
export const PROTECTED_SCREENS = Object.freeze([SCREENS.MAIN, SCREENS.SAVE_SELECT, SCREENS.SETUP]);

/** 内部别名 -> DOM 页面名（legacy 的 'position' 对应持仓页 portfolio）。 */
export const TAB_ALIASES = Object.freeze({ position: 'portfolio' });

/** 主导航页面（index.html 中 .nav-btn[data-page] 与 #<page>-page）。 */
export const TABS = Object.freeze(['market', 'trade', 'auto-trade', 'portfolio', 'profile']);

/**
 * @typedef {Object} SessionState
 * @property {import('../api/endpoints.js').UserOut | null} user
 * @property {Record<string, unknown> | null} currentSave
 * @property {string} screen
 * @property {string} tab
 * @property {number} savesRev
 */

/** @type {ReturnType<typeof createStore<SessionState>>} */
export const session = createStore(/** @type {SessionState} */ ({
  user: null,
  currentSave: null,
  screen: SCREENS.AUTH,
  tab: 'market',
  savesRev: 0,
}));

/** @returns {SessionState} */
export function getSession() {
  return session.get();
}

/**
 * 设置当前用户（null 表示登出）。同步 appStore.user。
 * @param {import('../api/endpoints.js').UserOut | null} user
 */
export function setUser(user) {
  session.set({ user: user ?? null });
  appStore.set({ user: user ? { id: user.id, username: user.username } : null });
}

/**
 * 设置当前存档（null 表示离开存档）。同步 appStore.currentSaveId。
 * @param {Record<string, unknown> | null} save
 */
export function setCurrentSave(save) {
  session.set({ currentSave: save ?? null });
  const id = save && typeof save.id === 'string' ? save.id : null;
  appStore.set({ currentSaveId: id });
}

/** 存档列表已变化（新增/重命名/删除/导入），通知列表重新拉取。 */
export function bumpSaves() {
  session.set((s) => ({ savesRev: s.savesRev + 1 }));
}

/**
 * 切换屏幕。未登录访问受保护屏幕时回退到登录页。
 * @param {string} name 屏幕 id，见 SCREENS
 * @param {Document} [doc=document]
 * @returns {string} 实际显示的屏幕 id
 */
export function showScreen(name, doc = document) {
  let target = name;
  if (PROTECTED_SCREENS.includes(target) && !session.get().user) {
    target = SCREENS.AUTH;
  }

  const prev = session.get().screen;
  doc.querySelectorAll('.screen').forEach((el) => el.classList.remove('active'));
  const el = doc.getElementById(target);
  if (el) el.classList.add('active');
  else console.error('[session] screen not found:', target);

  session.set({ screen: target });

  // 登录页入栈一条历史记录，避免浏览器后退把用户带回已登出的界面（同 legacy）。
  if (target === SCREENS.AUTH && prev !== SCREENS.AUTH) {
    try {
      globalThis.history?.pushState({ screen: 'auth', loggedOut: true }, '', '#login');
    } catch {
      /* 非浏览器环境忽略 */
    }
  }
  return target;
}

/**
 * 切换主导航页面。
 * @param {string} name 内部名或 DOM 名（'position' 会映射为 'portfolio'）
 * @param {Document} [doc=document]
 * @returns {string} 规范化后的 DOM 页面名
 */
export function showTab(name, doc = document) {
  const dom = TAB_ALIASES[name] ?? name;
  doc.querySelectorAll('.nav-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.page === dom);
  });
  doc.querySelectorAll('.page').forEach((p) => p.classList.remove('active'));
  doc.getElementById(`${dom}-page`)?.classList.add('active');
  session.set({ tab: dom });
  return dom;
}

/**
 * 绑定主导航（.main-nav 内的 .nav-btn[data-page]）到 showTab。返回解绑函数。
 * 由 features/auth 挂载时调用一次（应用入口）；其它模块只订阅 session.tab。
 * @param {Document} [doc=document]
 * @returns {() => void}
 */
export function bindMainNav(doc = document) {
  const nav = doc.querySelector('.main-nav');
  if (!nav) return () => {};
  const handler = (/** @type {Event} */ e) => {
    const btn = /** @type {HTMLElement} */ (e.target).closest?.('.nav-btn[data-page]');
    if (btn && nav.contains(btn)) showTab(/** @type {HTMLElement} */ (btn).dataset.page ?? 'market', doc);
  };
  nav.addEventListener('click', handler);
  return () => nav.removeEventListener('click', handler);
}

/**
 * 纯函数：屏幕是否需要登录（便于测试）。
 * @param {string} name
 */
export function isProtectedScreen(name) {
  return PROTECTED_SCREENS.includes(name);
}
