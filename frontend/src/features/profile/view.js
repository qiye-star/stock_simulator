/**
 * 个人页成就墙的渲染（html`` 默认转义）。
 * 隐藏成就未解锁时显示为锁定的占位（名称与描述使用 profile.hidden*）。
 */
import { html } from '../../ui/html.js';
import { levelI18nKey } from './viewModel.js';

/**
 * @param {import('./viewModel.js').AchievementCard[]} cards
 * @param {(key: string) => string} t
 */
export function renderAchievementCards(cards, t) {
  return html`${cards.map((c) => {
    const name = c.hidden ? t('profile.hiddenName') : t(`achievement.${c.id}.name`);
    const desc = c.hidden ? t('profile.hiddenDesc') : t(`achievement.${c.id}.desc`);
    const icon = c.hidden ? '❔' : c.icon;
    return html`<div class="achievement-card ${c.unlocked ? 'unlocked' : 'locked'}" data-achievement-id="${c.id}">
      <div class="achievement-icon-small">${icon}</div>
      <div class="achievement-info">
        <h4>${name}</h4>
        <p>${desc}</p>
      </div>
      <span class="achievement-level-badge ${c.level}">${t(levelI18nKey(c.level))}</span>
    </div>`;
  })}`;
}
