/**
 * 偏好设置的纯函数（无 DOM、无 I/O）。
 * 偏好字段与 PATCH /me 对齐：theme / lang / refresh_rate_ms / tutorial_completed。
 */

/** 行情刷新速度选项（毫秒），与 index.html #refresh-rate 的 option 值一致。 */
export const REFRESH_RATE_OPTIONS = Object.freeze([1000, 3000, 5000]);

/** 后端 MePatch 的 refresh_rate_ms 取值范围。 */
export const REFRESH_RATE_MIN = 500;
export const REFRESH_RATE_MAX = 60000;

/**
 * 只保留与当前用户不同的字段，避免无意义的 PATCH。
 * @param {Partial<Record<'theme' | 'lang' | 'refresh_rate_ms' | 'tutorial_completed', unknown>>} current
 * @param {Partial<Record<'theme' | 'lang' | 'refresh_rate_ms' | 'tutorial_completed', unknown>>} patch
 * @returns {Record<string, unknown>}
 */
export function diffPreferences(current, patch) {
  /** @type {Record<string, unknown>} */
  const out = {};
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) continue;
    if (current[key] !== value) out[key] = value;
  }
  return out;
}

/**
 * 解析刷新速度输入。
 * @param {string | number} raw
 * @returns {number | null} 合法整数毫秒，否则 null
 */
export function parseRefreshRate(raw) {
  const n = typeof raw === 'number' ? raw : Number.parseInt(String(raw), 10);
  if (!Number.isInteger(n) || n < REFRESH_RATE_MIN || n > REFRESH_RATE_MAX) return null;
  return n;
}

/**
 * 暂停按钮文案的 i18n key（暂停中显示「继续」）。
 * @param {boolean} paused
 * @returns {'settings.resume' | 'settings.pause'}
 */
export function clockButtonKey(paused) {
  return paused ? 'settings.resume' : 'settings.pause';
}
