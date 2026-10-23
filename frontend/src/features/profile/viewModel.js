/**
 * 个人页与成就墙的视图模型（纯函数，可单测）。
 */
import { ACHIEVEMENT_META } from './achievementsMeta.js';

/** 默认只展示前 N 个成就，其余需展开（同 legacy toggleAchievements 的 6 卡片高度）。 */
export const COLLAPSED_VISIBLE_COUNT = 6;

/** @typedef {'bronze' | 'silver' | 'gold' | 'legend'} AchievementLevel */
/** @typedef {{ id: string, level: AchievementLevel, icon: string, hidden: boolean, unlocked: boolean }} AchievementCard */

const LEVELS = /** @type {const} */ (['bronze', 'silver', 'gold', 'legend']);

/**
 * 从 GET /saves/{id}/achievements 的返回值取出已解锁的成就 id。
 * 兼容两种形态：字符串数组，或 SaveAchievement 对象数组（achievement_id 字段）。
 * @param {unknown} list
 * @returns {Set<string>}
 */
export function unlockedIdsFrom(list) {
  const out = new Set();
  if (!Array.isArray(list)) return out;
  for (const item of list) {
    if (typeof item === 'string') out.add(item);
    else if (item && typeof item === 'object') {
      const id = /** @type {Record<string, unknown>} */ (item).achievement_id ?? /** @type {Record<string, unknown>} */ (item).id;
      if (typeof id === 'string') out.add(id);
    }
  }
  return out;
}

/**
 * 合并目录（服务端）与静态元数据，得到成就卡片列表。
 * 目录为空或失败时回退到静态元数据，保证成就墙始终可渲染。
 * @param {unknown} catalog GET /achievements/catalog 的返回值
 * @param {Set<string>} unlocked
 * @param {Record<string, { level: AchievementLevel, icon: string }>} [meta]
 * @returns {AchievementCard[]}
 */
export function buildAchievementCards(catalog, unlocked, meta = ACHIEVEMENT_META) {
  const entries = Array.isArray(catalog) && catalog.length > 0
    ? catalog.filter((c) => c && typeof c === 'object' && typeof (/** @type {any} */ (c)).id === 'string')
    : Object.keys(meta).map((id) => ({ id }));

  return entries.map((raw) => {
    const item = /** @type {Record<string, unknown>} */ (raw);
    const id = /** @type {string} */ (item.id);
    const m = meta[id];
    const level = normalizeLevel(item.level ?? m?.level);
    const icon = typeof item.icon === 'string' && item.icon ? item.icon : (m?.icon ?? '🏆');
    const unlockedNow = unlocked.has(id);
    return {
      id,
      level,
      icon,
      hidden: item.hidden === true && !unlockedNow,
      unlocked: unlockedNow,
    };
  });
}

/**
 * @param {unknown} level
 * @returns {AchievementLevel}
 */
export function normalizeLevel(level) {
  return LEVELS.includes(/** @type {any} */ (level)) ? /** @type {AchievementLevel} */ (level) : 'bronze';
}

/**
 * 已解锁成就按等级计数（青铜/白银/黄金/传说）。
 * @param {AchievementCard[]} cards
 */
export function countUnlockedByLevel(cards) {
  /** @type {Record<AchievementLevel, number>} */
  const counts = { bronze: 0, silver: 0, gold: 0, legend: 0 };
  for (const c of cards) if (c.unlocked) counts[c.level]++;
  return counts;
}

/**
 * 是否需要展开按钮（超过默认可见数量）。
 * @param {number} total
 */
export function needsExpandToggle(total) {
  return total > COLLAPSED_VISIBLE_COUNT;
}

/**
 * 个人页统计：局数、交易数（各存档 trade_count 之和，缺失按 0）、成就进度。
 * @param {Record<string, unknown>[]} saves
 * @param {number} unlockedCount
 * @param {number} total
 */
export function profileStats(saves, unlockedCount, total) {
  const trades = saves.reduce((sum, s) => {
    const n = Number(s.trade_count);
    return sum + (Number.isInteger(n) && n > 0 ? n : 0);
  }, 0);
  return {
    games: saves.length,
    trades,
    achievements: `${unlockedCount}/${total}`,
  };
}

/** @param {AchievementLevel} level @returns {string} i18n key */
export function levelI18nKey(level) {
  return {
    bronze: 'profile.levelBronze',
    silver: 'profile.levelSilver',
    gold: 'profile.levelGold',
    legend: 'profile.levelLegend',
  }[normalizeLevel(level)];
}
