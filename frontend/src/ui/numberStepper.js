/**
 * 数字输入框的主题化步进按钮（移植自 legacy/game.js enhanceNumberInputs / handleNumberStepperClick）。
 *
 * 用原生 stepUp()/stepDown() 以遵守 min/max/step，并派发 input 与 change 事件，
 * 以便各 feature 的实时计算逻辑照常触发。
 */
import { html } from './html.js';
import { fragment, on } from './dom.js';

const WRAP_CLASS = 'num-stepper';

const UP_ICON = html`<svg viewBox="0 0 10 6" width="10" height="6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M1 5l4-4 4 4"/></svg>`;
const DOWN_ICON = html`<svg viewBox="0 0 10 6" width="10" height="6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M1 1l4 4 4-4"/></svg>`;

/**
 * 为 root 内所有未包装的 input[type=number] 注入步进按钮。可重复调用（幂等）。
 * @param {ParentNode} [root=document]
 * @returns {number} 本次包装的输入框数量
 */
export function enhanceNumberInputs(root = document) {
  let count = 0;
  root.querySelectorAll('input[type="number"]').forEach((input) => {
    if (input.closest(`.${WRAP_CLASS}`)) return;
    const wrap = document.createElement('div');
    wrap.className = WRAP_CLASS;
    input.after(wrap);
    wrap.appendChild(input);
    wrap.appendChild(
      fragment(html`<div class="num-stepper-btns">
        <button type="button" class="num-step-btn num-step-up" tabindex="-1" aria-label="+">${UP_ICON}</button>
        <button type="button" class="num-step-btn num-step-down" tabindex="-1" aria-label="-">${DOWN_ICON}</button>
      </div>`),
    );
    count++;
  });
  return count;
}

/**
 * 处理一次步进按钮点击（事件委托入口，可单独测试）。
 * @param {Event} event
 * @returns {boolean} 是否命中步进按钮
 */
export function handleStepperClick(event) {
  const target = event.target;
  if (!(target instanceof Element)) return false;
  const btn = target.closest('.num-step-btn');
  if (!btn) return false;
  const input = btn.closest(`.${WRAP_CLASS}`)?.querySelector('input');
  if (!(input instanceof HTMLInputElement) || input.disabled || input.readOnly) return true;
  if (btn.classList.contains('num-step-up')) input.stepUp();
  else input.stepDown();
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
}

/**
 * 启用：注入按钮 + 绑定 document 级点击委托。
 * @param {ParentNode} [root=document]
 * @returns {() => void} 解绑函数
 */
export function initNumberStepper(root = document) {
  enhanceNumberInputs(root);
  return on(document, 'click', handleStepperClick);
}
