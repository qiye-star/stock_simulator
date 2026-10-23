/**
 * 新手引导浮层的渲染（只更新 index.html 中已有节点的文本与样式）。
 */

/**
 * @param {Document} doc
 * @param {{
 *   text: string,
 *   index: number,
 *   total: number,
 *   placement: import('./steps.js').Placement ,
 * }} view
 */
export function renderStep(doc, { text, index, total, placement }) {
  const overlay = doc.getElementById('tutorial-overlay');
  if (!overlay) return;
  const highlight = /** @type {HTMLElement | null} */ (overlay.querySelector('.tutorial-highlight'));
  const tooltip = /** @type {HTMLElement | null} */ (overlay.querySelector('.tutorial-tooltip'));
  const arrow = /** @type {HTMLElement | null} */ (overlay.querySelector('.tutorial-arrow'));

  const textEl = doc.getElementById('tutorial-text');
  if (textEl) textEl.textContent = text;
  const numEl = doc.getElementById('tutorial-step-num');
  if (numEl) numEl.textContent = String(index + 1);
  const totalEl = doc.getElementById('tutorial-step-total');
  if (totalEl) totalEl.textContent = String(total);
  overlay.classList.add('active');

  if (!tooltip) return;
  if (placement.centered) {
    if (highlight) highlight.style.display = 'none';
    if (arrow) arrow.style.display = 'none';
    tooltip.style.left = '50%';
    tooltip.style.top = '50%';
    tooltip.style.transform = 'translate(-50%, -50%)';
    return;
  }

  tooltip.style.transform = '';
  tooltip.style.left = `${placement.tooltip.left}px`;
  tooltip.style.top = `${placement.tooltip.top}px`;

  if (highlight && placement.highlight) {
    const h = placement.highlight;
    highlight.style.left = `${h.left}px`;
    highlight.style.top = `${h.top}px`;
    highlight.style.width = `${h.width}px`;
    highlight.style.height = `${h.height}px`;
    highlight.style.display = 'block';
  }
  if (arrow && placement.arrow) {
    const a = placement.arrow;
    arrow.style.display = 'block';
    arrow.style.left = `${a.left}px`;
    arrow.style.top = `${a.top}px`;
    arrow.style.transform = `rotate(${a.rotate}deg)`;
  }
}

/** @param {Document} doc */
export function hideOverlay(doc) {
  doc.getElementById('tutorial-overlay')?.classList.remove('active');
}
