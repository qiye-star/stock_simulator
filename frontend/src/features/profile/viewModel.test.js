import { describe, expect, it } from 'vitest';
import {
  buildAchievementCards,
  countUnlockedByLevel,
  levelI18nKey,
  needsExpandToggle,
  profileStats,
  unlockedIdsFrom,
} from './viewModel.js';
import { ACHIEVEMENT_COUNT, ACHIEVEMENT_META } from './achievementsMeta.js';
import { renderAchievementCards } from './view.js';

describe('achievementsMeta', () => {
  it('covers all 54 legacy achievements with a valid level', () => {
    expect(Object.keys(ACHIEVEMENT_META)).toHaveLength(ACHIEVEMENT_COUNT);
    expect(ACHIEVEMENT_COUNT).toBe(54);
    for (const m of Object.values(ACHIEVEMENT_META)) {
      expect(['bronze', 'silver', 'gold', 'legend']).toContain(m.level);
      expect(m.icon.length).toBeGreaterThan(0);
    }
  });
});

describe('unlockedIdsFrom', () => {
  it('accepts id strings and SaveAchievement-like objects', () => {
    expect([...unlockedIdsFrom(['first_trade', { achievement_id: 'trade_10' }, { id: 'hold_5' }, 7])].sort())
      .toEqual(['first_trade', 'hold_5', 'trade_10']);
    expect(unlockedIdsFrom(null).size).toBe(0);
  });
});

describe('buildAchievementCards', () => {
  it('falls back to static metadata when the catalog is empty', () => {
    const cards = buildAchievementCards(null, new Set(['first_trade']));
    expect(cards).toHaveLength(ACHIEVEMENT_COUNT);
    expect(cards.find((c) => c.id === 'first_trade').unlocked).toBe(true);
  });

  it('hides hidden achievements until they are unlocked', () => {
    const catalog = [
      { id: 'first_trade', hidden: true },
      { id: 'trade_10', hidden: false, level: 'gold', icon: 'X' },
    ];
    const locked = buildAchievementCards(catalog, new Set());
    expect(locked[0]).toMatchObject({ hidden: true, unlocked: false, level: 'bronze' });
    expect(locked[1]).toMatchObject({ hidden: false, level: 'gold', icon: 'X' });
    const unlocked = buildAchievementCards(catalog, new Set(['first_trade']));
    expect(unlocked[0]).toMatchObject({ hidden: false, unlocked: true });
  });
});

describe('counts and stats', () => {
  it('counts only unlocked achievements by level', () => {
    const cards = buildAchievementCards(null, new Set(['first_trade', 'profit_100k']));
    expect(countUnlockedByLevel(cards)).toEqual({ bronze: 1, silver: 0, gold: 1, legend: 0 });
  });

  it('summarises saves, trades and achievement progress', () => {
    expect(profileStats([{ trade_count: 3 }, { trade_count: -1 }, {}], 2, 54)).toEqual({
      games: 3,
      trades: 3,
      achievements: '2/54',
    });
  });

  it('shows the expand toggle only beyond six cards', () => {
    expect(needsExpandToggle(6)).toBe(false);
    expect(needsExpandToggle(7)).toBe(true);
  });

  it('maps levels to i18n keys with a safe fallback', () => {
    expect(levelI18nKey('legend')).toBe('profile.levelLegend');
    expect(levelI18nKey('nope')).toBe('profile.levelBronze');
  });
});

describe('renderAchievementCards', () => {
  it('renders hidden locked cards without leaking the real name', () => {
    const cards = buildAchievementCards([{ id: 'first_trade', hidden: true }], new Set());
    const out = renderAchievementCards(cards, (k) => k).value;
    expect(out).toContain('profile.hiddenName');
    expect(out).not.toContain('achievement.first_trade.name');
    expect(out).toContain('locked');
  });
});
