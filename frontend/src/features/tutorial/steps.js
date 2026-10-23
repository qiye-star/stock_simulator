/**
 * 新手引导的步骤与浮层定位（纯函数，可单测）。
 * 步骤文案 key 见 i18n tutorial.step1..9；selector 为高亮目标（找不到则居中显示）。
 * 移植自 legacy/game.js startTutorial 4256-4276、renderTutorialStep 4296-4381。
 */

/**
 * @typedef {Object} TutorialStep
 * @property {string} key i18n key
 * @property {string | null} selector 高亮的 CSS 选择器
 * @property {string | null} tab 进入该步骤时切换到的主页面（DOM 名）
 */

/** @type {readonly TutorialStep[]} */
export const TUTORIAL_STEPS = Object.freeze([
  { key: 'tutorial.step1', selector: null, tab: null },
  { key: 'tutorial.step2', selector: '.market-sidebar', tab: 'market' },
  { key: 'tutorial.step3', selector: '.detail-quote', tab: 'market' },
  { key: 'tutorial.step4', selector: '.main-nav', tab: null },
  { key: 'tutorial.step5', selector: '.trade-form', tab: 'trade' },
  { key: 'tutorial.step6', selector: '.position-list', tab: 'portfolio' },
  { key: 'tutorial.step7', selector: '.profile-header', tab: 'profile' },
  { key: 'tutorial.step8', selector: null, tab: 'profile' },
  { key: 'tutorial.step9', selector: null, tab: null },
]);

export const TOOLTIP_WIDTH = 320;
export const TOOLTIP_HEIGHT = 150;
export const TOOLTIP_PADDING = 20;
const ARROW_OFFSET = 15;
const ARROW_HALF = 10;

/**
 * @typedef {{ left: number, top: number, width: number, height: number, bottom: number, right: number }} Rect
 * @typedef {{ width: number, height: number }} Viewport
 * @typedef {{
 *   centered: boolean,
 *   tooltip: { left: number, top: number },
 *   highlight: { left: number, top: number, width: number, height: number } | null,
 *   arrow: { left: number, top: number, rotate: number } | null,
 * }} Placement
 */

/**
 * 计算提示框与箭头位置。规则同 legacy：优先放在目标下方，不足则上方，再不足则侧边，最后夹紧到视口内。
 * @param {Rect | null} rect 目标元素矩形；null 表示居中显示
 * @param {Viewport} viewport
 * @returns {Placement}
 */
export function placeTooltip(rect, viewport) {
  if (!rect) {
    return { centered: true, tooltip: { left: 0, top: 0 }, highlight: null, arrow: null };
  }
  const w = TOOLTIP_WIDTH;
  const h = TOOLTIP_HEIGHT;
  const pad = TOOLTIP_PADDING;

  let top = rect.bottom + pad;
  let left = rect.left + (rect.width - w) / 2;

  if (top + h > viewport.height - pad) top = rect.top - h - pad;
  if (top < pad) {
    top = rect.top;
    left = rect.right + pad;
    if (left + w > viewport.width - pad) left = rect.left - w - pad;
  }

  left = Math.max(pad, Math.min(left, viewport.width - w - pad));
  top = Math.max(pad, Math.min(top, viewport.height - h - pad));

  /** @type {{ left: number, top: number, rotate: number }} */
  let arrow;
  if (top > rect.bottom) {
    arrow = { left: rect.left + rect.width / 2 - ARROW_HALF, top: top - ARROW_OFFSET, rotate: 0 };
  } else if (top + h < rect.top) {
    arrow = { left: rect.left + rect.width / 2 - ARROW_HALF, top: top + h, rotate: 180 };
  } else if (left > rect.right) {
    arrow = { left: left - ARROW_OFFSET, top: rect.top + rect.height / 2 - ARROW_HALF, rotate: -90 };
  } else {
    arrow = { left: left + w, top: rect.top + rect.height / 2 - ARROW_HALF, rotate: 90 };
  }

  return {
    centered: false,
    tooltip: { left, top },
    highlight: { left: rect.left - 5, top: rect.top - 5, width: rect.width + 10, height: rect.height + 10 },
    arrow,
  };
}
