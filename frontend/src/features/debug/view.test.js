import { describe, expect, it } from 'vitest';
import { isSafeHtml } from '../../ui/html.js';
import { renderAchievementOptions, renderClearList, renderNotice } from './view.js';

describe('debug views', () => {
  it('every renderer returns SafeHtml so it can be passed to setHtml', () => {
    expect(isSafeHtml(renderAchievementOptions([]))).toBe(true);
    expect(isSafeHtml(renderAchievementOptions([{ value: 'a', label: 'A' }]))).toBe(true);
    expect(isSafeHtml(renderClearList([], 'OK'))).toBe(true);
    expect(isSafeHtml(renderNotice(null))).toBe(true);
  });

  it('option labels are escaped', () => {
    const out = renderAchievementOptions([{ value: '"x', label: '<i>n</i>' }]).value;
    expect(out).toContain('value="&quot;x"');
    expect(out).toContain('&lt;i&gt;n&lt;/i&gt;');
  });

  it('notice is hidden when there is no text and visible with text', () => {
    expect(renderNotice(null).value).toContain('hidden');
    const shown = renderNotice('DISABLED').value;
    expect(shown).toContain('DISABLED');
    expect(shown).not.toContain('hidden');
  });
});
