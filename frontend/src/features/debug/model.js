/**
 * 调试面板纯逻辑（无 DOM、无 I/O）。仅服务端 ENABLE_DEBUG_API=true 时可用。
 * 原版参考：legacy/game.js 812-824（连续点击 5 次打开）、4450-4830（各调试动作与提示）。
 */
/** 连续点击个人主页头部的判定窗口（ms）与次数（同 legacy：两次点击间隔 > 2s 则重新计数）。 */
export const TAP_WINDOW_MS = 2000;
export const TAP_COUNT = 5;

/** 交易时段（分钟）：上午 9:30-11:30，下午 13:00-15:00（legacy isTradingTime）。 */
export function isTradingMinute(m) {
  return (m >= 570 && m <= 690) || (m >= 780 && m <= 900);
}

/** 预设时间（时, 分）。“随机时间”在控制器中用 Math.random 生成，不在此列。 */
export const TIME_PRESETS = Object.freeze({
  'morning-open': [9, 30],
  early: [9, 35],
  'morning-close': [11, 25],
  late: [11, 35],
  afternoon: [13, 0],
  close: [14, 55],
});

/** 时段状态文案 key 与颜色（沿用 legacy updateDebugTimeDisplay）。 */
export function timeStatus(totalMinutes) {
  const m = totalMinutes;
  if (m >= 570 && m <= 575) return { key: 'marketStatus.earlyBird', color: '#2980b9' };
  if (m >= 695 && m <= 700) return { key: 'marketStatus.nightOwl', color: '#9b59b6' };
  if (m >= 780 && m <= 785) return { key: 'marketStatus.afternoonOpen', color: '#f39c12' };
  if (!isTradingMinute(m)) return { key: 'marketStatus.notTrading', color: '#e74c3c' };
  return { key: 'marketStatus.normal', color: '#27ae60' };
}

/**
 * 连续点击计数。返回新状态与是否应打开面板。
 * @param {{ count: number, last: number }} prev
 * @param {number} now 毫秒时间戳
 * @returns {{ count: number, last: number, open: boolean }}
 */
export function nextTapState(prev, now) {
  const within = now - prev.last <= TAP_WINDOW_MS;
  const count = within ? prev.count + 1 : 1;
  if (count >= TAP_COUNT) return { count: 0, last: now, open: true };
  return { count, last: now, open: false };
}

/**
 * 资金输入（元，最多两位小数，须 > 0）-> 分。
 * @param {unknown} str
 * @returns {{ ok: true, amountCents: number } | { ok: false, key: string }}
 */
export function parseFundInput(str) {
  const s = String(str ?? '').trim();
  const n = s === '' ? NaN : Number(s);
  if (!Number.isFinite(n) || n <= 0) return { ok: false, key: 'debug.invalidFund' };
  const cents = Math.round(n * 100);
  if (Math.abs(cents - n * 100) > 1e-6 || cents <= 0) return { ok: false, key: 'debug.invalidFund' };
  return { ok: true, amountCents: cents };
}

/**
 * 时、分输入校验（整数，时 0-23，分 0-59）。
 * @param {unknown} hourStr
 * @param {unknown} minuteStr
 * @returns {{ ok: true, hour: number, minute: number } | { ok: false, key: string }}
 */
export function parseClockInput(hourStr, minuteStr) {
  const h = String(hourStr ?? '').trim();
  const m = String(minuteStr ?? '').trim();
  if (h === '' || m === '') return { ok: false, key: 'debug.invalidTime' };
  const hour = Number(h);
  const minute = Number(m);
  if (!Number.isInteger(hour) || !Number.isInteger(minute)) return { ok: false, key: 'debug.invalidTime' };
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return { ok: false, key: 'debug.invalidTime' };
  return { ok: true, hour, minute };
}

/** 存档分钟数 -> 时、分。 @param {number} totalMinutes */
export function clockFromMinute(totalMinutes) {
  const h = Math.floor(totalMinutes / 60);
  return { hour: h, minute: totalMinutes - h * 60 };
}

/** @param {number} hour @param {number} minute */
export function formatHM(hour, minute) {
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

/** 成就等级 -> 文案 key（沿用 legacy achievements.js getLevelName）。 */
export const LEVEL_KEYS = Object.freeze({
  bronze: 'profile.levelBronze',
  silver: 'profile.levelSilver',
  gold: 'profile.levelGold',
  legend: 'profile.levelLegend',
});

/**
 * 成就下拉项（value = id，label = 名称 (等级)）。
 * @param {Array<{ id: string, level?: string }>} catalog
 * @param {(k: string, p?: Record<string, string | number>) => string} t
 */
export function achievementOptions(catalog, t) {
  return catalog.map((a) => {
    const level = LEVEL_KEYS[a.level] ? t(LEVEL_KEYS[a.level]) : String(a.level ?? '');
    return { value: a.id, label: `${t(`achievement.${a.id}.name`)} (${level})` };
  });
}

/**
 * 服务端已解锁成就 -> id 列表（兼容字符串数组与 {achievement_id} 对象数组）。
 * @param {unknown} res
 * @returns {string[]}
 */
export function parseUnlocked(res) {
  const list = Array.isArray(res) ? res : res && typeof res === 'object' && Array.isArray(/** @type {any} */ (res).items) ? /** @type {any} */ (res).items : [];
  return list
    .map((x) => (typeof x === 'string' ? x : typeof x?.achievement_id === 'string' ? x.achievement_id : null))
    .filter((x) => typeof x === 'string');
}

/**
 * 成就名称列表（用于确认框 {list}）。
 * @param {string[]} ids
 * @param {(k: string) => string} t
 */
export function achievementNames(ids, t) {
  return ids.map((id) => t(`achievement.${id}.name`)).join('、');
}
