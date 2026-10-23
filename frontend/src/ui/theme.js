/**
 * 主题（移植自 legacy/game.js setTheme / toggleTheme）。
 *
 * 通过 <body> 上的类名切换：dark（无类名）/ light -> light-theme / festival -> festival-theme。
 * 与 legacy 不同：只增删对应类名，不覆盖 body 上的其它类名。
 */

/** @typedef {'dark' | 'light' | 'festival'} Theme */

/** @type {Readonly<Record<Theme, string>>} */
export const THEME_CLASS = Object.freeze({
  dark: '',
  light: 'light-theme',
  festival: 'festival-theme',
});

/** 切换顺序（与 legacy toggleTheme 一致）。 */
export const THEME_ORDER = /** @type {const} */ (['dark', 'light', 'festival']);

export const THEME_ICON = Object.freeze({ dark: '🌙', light: '☀️', festival: '🎉' });

/**
 * @param {unknown} value
 * @returns {Theme}
 */
export function normalizeTheme(value) {
  return THEME_ORDER.includes(/** @type {any} */ (value)) ? /** @type {Theme} */ (value) : 'dark';
}

/**
 * @param {Theme} theme
 * @param {HTMLElement} [body=document.body]
 */
export function applyTheme(theme, body = document.body) {
  const t = normalizeTheme(theme);
  for (const cls of Object.values(THEME_CLASS)) {
    if (cls) body.classList.remove(cls);
  }
  const cls = THEME_CLASS[t];
  if (cls) body.classList.add(cls);
  body.dataset.theme = t;
}

/**
 * @param {Theme} theme
 * @returns {Theme} 下一个主题
 */
export function nextTheme(theme) {
  const i = THEME_ORDER.indexOf(normalizeTheme(theme));
  return THEME_ORDER[(i + 1) % THEME_ORDER.length];
}
