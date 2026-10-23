/**
 * 设置面板与主题按钮的渲染（只更新已有节点的属性与文本）。
 */
import { THEME_ICON } from '../../ui/theme.js';

/**
 * @param {{ theme: string, refreshRate: number, lang: string }} values
 * @param {Document} [doc]
 */
export function syncSettingsForm({ theme, refreshRate, lang }, doc = document) {
  const themeSelect = doc.getElementById('theme-select');
  if (themeSelect instanceof HTMLSelectElement) themeSelect.value = theme;
  const refresh = doc.getElementById('refresh-rate');
  if (refresh instanceof HTMLSelectElement) refresh.value = String(refreshRate);
  const langSelect = doc.getElementById('language-select');
  if (langSelect instanceof HTMLSelectElement) langSelect.value = lang;
}

/**
 * @param {string} theme
 * @param {Document} [doc]
 */
export function setThemeToggleIcon(theme, doc = document) {
  const btn = doc.getElementById('theme-toggle');
  if (btn) btn.textContent = THEME_ICON[/** @type {keyof typeof THEME_ICON} */ (theme)] ?? THEME_ICON.dark;
}

/**
 * @param {string} label 已翻译文案
 * @param {Document} [doc]
 */
export function setPauseLabel(label, doc = document) {
  const btn = doc.getElementById('time-pause-btn');
  if (btn) btn.textContent = label;
}
