/**
 * 认证与账户流程（移植自 legacy/game.js login 1000-1085、register 1087-1155、
 * logout 1157-1205、deleteAccount 1207-1245、changePassword 2442-2513）。
 *
 * 会话由服务端 Cookie 维持：登录/注册成功即已登录（后端同时下发 session cookie）。
 * 所有错误经 ApiError.code -> i18n/errors.js 翻译。
 */
import { ApiError } from '../../api/http.js';
import * as api from '../../api/endpoints.js';
import { i18n, isSupportedLang } from '../../i18n/i18n.js';
import { ErrorCode, errorMessage } from '../../i18n/errors.js';
import { appStore } from '../../state/store.js';
import { SCREENS, setUser, showScreen } from '../../state/session.js';
import { normalizeTheme } from '../../ui/theme.js';
import { showNotification } from '../../ui/notify.js';
import { closeModal, openModal } from '../../ui/modal.js';
import { on, delegate } from '../../ui/dom.js';
import {
  clearAuthForms,
  readValue,
  resetChangePasswordForm,
  setAuthTab,
  setChangePasswordError,
  setErrorText,
} from './view.js';
import {
  validateChangePassword,
  validateLogin,
  validateRegister,
} from './validators.js';

/** 上次登录用户名（per-viewer 便利项，同 legacy stock_simulator_last_user）。 */
export const LAST_USER_KEY = 'stock_simulator_last_user';
export const DELETE_CONFIRM_TEXT = 'DELETE';


/**
 * 把服务端用户偏好应用到前端：主题（appStore -> main.js applyTheme）与语言（i18n）。
 * 不回写服务端（应用偏好不触发 PATCH）。
 * @param {import('../../api/endpoints.js').UserOut} user
 */
export function applyUserPreferences(user) {
  appStore.set({ theme: normalizeTheme(user.theme) });
  if (isSupportedLang(user.lang) && i18n.getLanguage() !== user.lang) {
    i18n.setLanguage(user.lang);
  }
}

/** 登录成功后的统一入口：记录用户、应用偏好、进入存档选择。 */
export function enterApp(user, doc = document) {
  setUser(user);
  applyUserPreferences(user);
  try {
    globalThis.localStorage?.setItem(LAST_USER_KEY, user.username);
  } catch {
    /* 隐私模式可能不可写 */
  }
  clearAuthForms(doc);
  showScreen(SCREENS.SAVE_SELECT, doc);
}

/** 登出后的本地清理（服务端会话已由调用方吊销或失效）。 */
export function resetToAuth(doc = document) {
  setUser(null);
  clearAuthForms(doc);
  showScreen(SCREENS.AUTH, doc);
}

/** 启动时恢复会话：有有效 Cookie 则直接进入存档选择，否则停留在登录页。 */
export async function restoreSession(doc = document) {
  try {
    const user = await api.getMe();
    enterApp(user, doc);
    return true;
  } catch (err) {
    // 未登录（AUTH_REQUIRED）是常态，静默；其它错误（如网络）提示。
    const unauthenticated = err instanceof ApiError && (err.code === ErrorCode.AUTH_REQUIRED || err.status === 401);
    if (!unauthenticated) showNotification(errorMessage(err, (k) => i18n.t(k)), 'error');
    return false;
  }
}

/** 登录页预填上次用户名。 */
function prefillLastUser(doc) {
  let last = null;
  try {
    last = globalThis.localStorage?.getItem(LAST_USER_KEY) ?? null;
  } catch {
    last = null;
  }
  const input = doc.getElementById('login-username');
  if (last && input instanceof HTMLInputElement && !input.value) input.value = last;
}

async function doLogin(doc) {
  const input = { username: readValue('login-username', doc).trim(), password: readValue('login-password', doc) };
  const errKey = validateLogin(input);
  if (errKey) {
    setErrorText('login-error', i18n.t(errKey), doc);
    return;
  }
  try {
    const user = await api.login(input);
    setErrorText('login-error', '', doc);
    enterApp(user, doc);
  } catch (err) {
    setErrorText('login-error', errorMessage(err, (k) => i18n.t(k)), doc);
  }
}

async function doRegister(doc) {
  const input = {
    username: readValue('reg-username', doc),
    password: readValue('reg-password', doc),
    confirm: readValue('reg-confirm', doc),
  };
  const errKey = validateRegister(input);
  if (errKey) {
    setErrorText('reg-error', i18n.t(errKey), doc);
    return;
  }
  try {
    // 后端注册即登录（下发 session Cookie），直接进入存档选择。
    const user = await api.register({ username: input.username.trim(), password: input.password });
    setErrorText('reg-error', '', doc);
    showNotification(i18n.t('auth.regSuccess'), 'success');
    enterApp(user, doc);
  } catch (err) {
    setErrorText('reg-error', errorMessage(err, (k) => i18n.t(k)), doc);
  }
}

/** 登出（需确认）。 */
export async function doLogout(doc = document) {
  if (!globalThis.confirm?.(i18n.t('logout.confirm'))) return;
  try {
    await api.logout();
  } catch (err) {
    // 服务端失败也要清理本地状态，否则用户无法退出。
    console.warn('[auth] logout request failed:', err);
  }
  resetToAuth(doc);
  showNotification(i18n.t('auth.logoutSuccess'), 'success');
}

/** 注销账户：需输入 DELETE 并二次确认（同 legacy）。 */
export async function doDeleteAccount(doc = document) {
  const typed = globalThis.prompt?.(i18n.t('deleteAccount.confirmText'));
  if (typed !== DELETE_CONFIRM_TEXT) {
    if (typed !== null) showNotification(i18n.t('deleteAccount.inputMismatch'), 'warning');
    return;
  }
  if (!globalThis.confirm?.(i18n.t('deleteAccount.warning'))) return;
  try {
    await api.deleteMe();
  } catch (err) {
    showNotification(errorMessage(err, (k) => i18n.t(k)), 'error');
    return;
  }
  resetToAuth(doc);
  showNotification(i18n.t('deleteAccount.success'), 'success');
}

function openChangePassword(doc) {
  resetChangePasswordForm(doc);
  openModal('change-password-modal');
}

async function doChangePassword(doc) {
  const input = {
    current: readValue('current-password', doc),
    next: readValue('new-password', doc),
    confirm: readValue('confirm-password', doc),
  };
  const errKey = validateChangePassword(input);
  if (errKey) {
    setChangePasswordError(i18n.t(errKey), doc);
    return;
  }
  try {
    await api.changePassword({ current_password: input.current, new_password: input.next });
  } catch (err) {
    let msg = errorMessage(err, (k) => i18n.t(k));
    if (err instanceof ApiError && err.code === ErrorCode.AUTH_INVALID_CREDENTIALS) msg = i18n.t('password.wrongCurrent');
    setChangePasswordError(msg, doc);
    return;
  }
  setChangePasswordError('', doc);
  closeModal('change-password-modal');
  showNotification(i18n.t('password.success'), 'success');
}

/**
 * 绑定认证页与账户相关按钮。返回解绑函数。
 * @param {Document} [doc=document]
 * @returns {() => void}
 */
export function initAuthController(doc = document) {
  const offs = [];
  const bind = (el, type, fn) => {
    if (el) offs.push(on(el, type, fn));
  };

  // 登录 / 注册切换（限定在 .auth-tabs 内，避免与自动交易页的 data-tab 冲突）
  offs.push(
    delegate(doc.querySelector('.auth-tabs') ?? doc, 'click', '.tab-btn', (_e, el) => {
      setAuthTab(/** @type {HTMLElement} */ (el).dataset.tab ?? 'login', doc);
    }),
  );

  bind(doc.getElementById('login-btn'), 'click', () => doLogin(doc));
  bind(doc.getElementById('register-btn'), 'click', () => doRegister(doc));
  for (const id of ['login-username', 'login-password']) {
    bind(doc.getElementById(id), 'keydown', (e) => {
      if (/** @type {KeyboardEvent} */ (e).key === 'Enter') doLogin(doc);
    });
  }
  for (const id of ['reg-username', 'reg-password', 'reg-confirm']) {
    bind(doc.getElementById(id), 'keydown', (e) => {
      if (/** @type {KeyboardEvent} */ (e).key === 'Enter') doRegister(doc);
    });
  }

  // 登录页语言切换（登录后同步到服务端由 settings 模块负责）
  bind(doc.getElementById('auth-lang-toggle'), 'click', () => i18n.toggleLanguage());

  // 存档选择页 / 个人页的账户按钮
  bind(doc.getElementById('logout-btn'), 'click', () => doLogout(doc));
  bind(doc.getElementById('logout-from-profile-btn'), 'click', () => doLogout(doc));
  bind(doc.getElementById('delete-account-btn'), 'click', () => doDeleteAccount(doc));
  bind(doc.getElementById('change-password-btn'), 'click', () => openChangePassword(doc));
  bind(doc.getElementById('submit-password-change'), 'click', () => doChangePassword(doc));
  bind(doc.getElementById('cancel-password-change'), 'click', () => closeModal('change-password-modal'));

  prefillLastUser(doc);

  return () => {
    for (const off of offs) off();
  };
}
