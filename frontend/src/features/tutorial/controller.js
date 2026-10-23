/**
 * 新手引导流程（移植自 legacy/game.js startTutorial / showTutorialStep / nextTutorial / endTutorial）。
 *
 * - 进入主界面且用户 tutorial_completed=false 时自动开始（每个用户每次页面加载只开始一次）。
 * - 完成或跳过都会 PATCH /me {tutorial_completed: true}。
 * - 离开主界面时隐藏浮层但不标记完成，下次进入会继续。
 */
import * as api from '../../api/endpoints.js';
import { i18n } from '../../i18n/i18n.js';
import { errorMessage } from '../../i18n/errors.js';
import { SCREENS, session, setUser, showTab } from '../../state/session.js';
import { showNotification } from '../../ui/notify.js';
import { on } from '../../ui/dom.js';
import { TUTORIAL_STEPS, placeTooltip } from './steps.js';
import { hideOverlay, renderStep } from './view.js';

/** 每个用户本页面加载周期内只自动开始一次（按 user.id 记录）。 */
const startedFor = new Set();

/** @type {{ index: number, active: boolean }} */
const state = { index: 0, active: false };


/**
 * @param {Document} doc
 */
function showStep(doc) {
  const step = TUTORIAL_STEPS[state.index];
  if (!step) return end(doc);
  if (step.tab) showTab(step.tab, doc);
  // 等待页面切换渲染完成后再定位
  setTimeout(() => {
    if (!state.active) return;
    const el = step.selector ? doc.querySelector(step.selector) : null;
    const visible = el instanceof HTMLElement && el.offsetParent !== null;
    const rect = visible ? el.getBoundingClientRect() : null;
    const placement = placeTooltip(rect, { width: globalThis.innerWidth, height: globalThis.innerHeight });
    renderStep(doc, {
      text: i18n.t(step.key),
      index: state.index,
      total: TUTORIAL_STEPS.length,
      placement,
    });
  }, 100);
}

/** @param {Document} doc */
export function startTutorial(doc = document) {
  state.index = 0;
  state.active = true;
  showStep(doc);
}

/** @param {Document} doc */
export function nextStep(doc = document) {
  if (!state.active) return;
  state.index += 1;
  showStep(doc);
}

/**
 * 结束引导并把 tutorial_completed 写回服务端。
 * @param {Document} doc
 */
export async function end(doc = document) {
  const wasActive = state.active;
  state.active = false;
  hideOverlay(doc);
  if (!wasActive) return;
  const user = session.get().user;
  if (!user || user.tutorial_completed) return;
  try {
    const updated = await api.updateMe({ tutorial_completed: true });
    setUser(updated);
  } catch (err) {
    showNotification(errorMessage(err, (k) => i18n.t(k)), 'error');
  }
}

/**
 * 绑定浮层按钮，并订阅会话以自动开始 / 隐藏。返回解绑函数。
 * @param {Document} [doc=document]
 * @returns {() => void}
 */
export function initTutorialController(doc = document) {
  const offs = [];
  const skip = doc.getElementById('skip-tutorial');
  const next = doc.getElementById('next-tutorial');
  if (skip) offs.push(on(skip, 'click', () => end(doc)));
  if (next) offs.push(on(next, 'click', () => nextStep(doc)));
  offs.push(on(globalThis, 'resize', () => {
    if (state.active) showStep(doc);
  }));

  const maybeStart = (s) => {
    const user = s.user;
    if (s.screen !== SCREENS.MAIN || !user || user.tutorial_completed) return;
    if (startedFor.has(user.id)) return;
    startedFor.add(user.id);
    setTimeout(() => {
      if (session.get().screen === SCREENS.MAIN) startTutorial(doc);
    }, 0);
  };

  let prev = session.get();
  offs.push(
    session.subscribe((s) => {
      // 离开主界面：隐藏浮层（不标记完成）
      if (s.screen !== prev.screen && s.screen !== SCREENS.MAIN && state.active) {
        state.active = false;
        hideOverlay(doc);
      }
      if (s.screen !== prev.screen || s.user !== prev.user) maybeStart(s);
      prev = s;
    }),
  );

  // 初次挂载时若已经在主界面（例如热重载），也尝试一次
  maybeStart(session.get());

  return () => {
    for (const off of offs) off();
  };
}
