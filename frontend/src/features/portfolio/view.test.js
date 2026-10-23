import { describe, expect, it } from 'vitest';
import { renderHoldingRows, renderRecordsFooter, renderTradeRows } from './view.js';

describe('portfolio views escape user-controlled text', () => {
  it('holding rows escape name and code', () => {
    const out = renderHoldingRows(
      [{ code: '"><img>', name: '<b>x</b>', quantityText: '1', avgText: '1.00', priceText: '1.00', marketValueText: '¥1', pnlText: '+¥0', rateText: '+0.00%', tone: 'up' }],
      'empty',
    ).value;
    expect(out).not.toContain('<img>');
    expect(out).not.toContain('<b>x</b>');
    expect(out).toContain('&lt;b&gt;x&lt;/b&gt;');
    expect(out).toContain('data-code="&quot;&gt;&lt;img&gt;"');
  });

  it('empty states render a single placeholder row', () => {
    expect(renderHoldingRows([], 'none').value).toContain('colspan="7"');
    expect(renderTradeRows([], 'none').value).toContain('colspan="6"');
  });

  it('footer shows the load-more button only when more pages exist', () => {
    const base = { loading: false, hasRows: true, moreText: 'MORE', allLoadedText: 'ALL', loadingText: 'LOAD' };
    expect(renderRecordsFooter({ ...base, hasMore: true }).value).toContain('id="trade-records-more"');
    expect(renderRecordsFooter({ ...base, hasMore: false }).value).toContain('ALL');
    expect(renderRecordsFooter({ ...base, hasMore: false, loading: true }).value).toContain('LOAD');
  });
});
