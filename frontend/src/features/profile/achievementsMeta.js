/**
 * 成就静态元数据（图标与等级），按成就 id 索引。
 * 名称与描述不在此处：走 i18n 的 achievement.<id>.name / .desc。
 * 数据来源：legacy/achievements.js（由脚本抽取，54 条）。
 * 服务端 /achievements/catalog 若给出 level/icon 则以服务端为准（见 viewModel.js）。
 */

/** @typedef {'bronze' | 'silver' | 'gold' | 'legend'} AchievementLevel */

export const ACHIEVEMENT_META = Object.freeze({
  first_trade: Object.freeze({ level: 'bronze', icon: '🌱' }),
  first_profit: Object.freeze({ level: 'bronze', icon: '💰' }),
  first_loss: Object.freeze({ level: 'bronze', icon: '📉' }),
  hold_5: Object.freeze({ level: 'bronze', icon: '📊' }),
  trade_10: Object.freeze({ level: 'bronze', icon: '🔥' }),
  profit_1k: Object.freeze({ level: 'bronze', icon: '💵' }),
  day_trader: Object.freeze({ level: 'bronze', icon: '⚡' }),
  watchlist_10: Object.freeze({ level: 'bronze', icon: '⭐' }),
  profit_10k: Object.freeze({ level: 'silver', icon: '💎' }),
  trade_50: Object.freeze({ level: 'silver', icon: '📈' }),
  hold_10: Object.freeze({ level: 'silver', icon: '📁' }),
  return_10: Object.freeze({ level: 'silver', icon: '🚀' }),
  profit_streak_3: Object.freeze({ level: 'silver', icon: '🏃' }),
  all_sectors: Object.freeze({ level: 'silver', icon: '🏭' }),
  large_trade: Object.freeze({ level: 'silver', icon: '💼' }),
  maotai_holder: Object.freeze({ level: 'silver', icon: '🍶' }),
  profit_100k: Object.freeze({ level: 'gold', icon: '👑' }),
  return_50: Object.freeze({ level: 'gold', icon: '🦄' }),
  trade_200: Object.freeze({ level: 'gold', icon: '🎯' }),
  profit_streak_10: Object.freeze({ level: 'gold', icon: '🔥' }),
  double_bagger: Object.freeze({ level: 'gold', icon: '📊' }),
  market_beater: Object.freeze({ level: 'gold', icon: '🏆' }),
  diversified: Object.freeze({ level: 'gold', icon: '🌍' }),
  day_trader_pro: Object.freeze({ level: 'gold', icon: '⚡' }),
  profit_1m: Object.freeze({ level: 'legend', icon: '🏰' }),
  return_100: Object.freeze({ level: 'legend', icon: '🐉' }),
  trade_1000: Object.freeze({ level: 'legend', icon: '⚔️' }),
  perfect_game: Object.freeze({ level: 'legend', icon: '💎' }),
  stock_god: Object.freeze({ level: 'legend', icon: '👑' }),
  all_achievements: Object.freeze({ level: 'legend', icon: '🎖️' }),
  standing_guard: Object.freeze({ level: 'bronze', icon: '⛰️' }),
  buy_high_sell_low: Object.freeze({ level: 'bronze', icon: '🙃' }),
  fomo_master: Object.freeze({ level: 'bronze', icon: '😱' }),
  panic_seller: Object.freeze({ level: 'bronze', icon: '😰' }),
  bagholder: Object.freeze({ level: 'silver', icon: '📅' }),
  yo_yo_trader: Object.freeze({ level: 'silver', icon: '🎪' }),
  all_in_gambler: Object.freeze({ level: 'silver', icon: '🎲' }),
  comeback_kid: Object.freeze({ level: 'gold', icon: '🌈' }),
  diamond_hands: Object.freeze({ level: 'gold', icon: '💎' }),
  paper_hands: Object.freeze({ level: 'bronze', icon: '🧻' }),
  lucky_star: Object.freeze({ level: 'silver', icon: '🍀' }),
  unlucky_star: Object.freeze({ level: 'bronze', icon: '🌧️' }),
  weekend_warrior: Object.freeze({ level: 'bronze', icon: '📆' }),
  round_number: Object.freeze({ level: 'bronze', icon: '🔢' }),
  palindrome_profit: Object.freeze({ level: 'silver', icon: '🎨' }),
  tax_payer: Object.freeze({ level: 'silver', icon: '🏛️' }),
  market_crash_survivor: Object.freeze({ level: 'gold', icon: '🛡️' }),
  contrarian: Object.freeze({ level: 'silver', icon: '🦅' }),
  momentum_chaser: Object.freeze({ level: 'silver', icon: '🌊' }),
  value_investor: Object.freeze({ level: 'gold', icon: '📚' }),
  technical_trader: Object.freeze({ level: 'silver', icon: '📐' }),
  news_trader: Object.freeze({ level: 'bronze', icon: '📰' }),
  early_bird: Object.freeze({ level: 'bronze', icon: '🐦' }),
  night_owl: Object.freeze({ level: 'bronze', icon: '🦉' }),
});

/** 成就总数（静态）。 */
export const ACHIEVEMENT_COUNT = 54;
