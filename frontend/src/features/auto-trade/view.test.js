import { describe, expect, it } from 'vitest';
import { renderConfigList, renderEventList } from './view.js';

describe('auto-trade views escape user-controlled text', () => {
  it('config rows escape the stock name and keep the id in data attributes', () => {
    const out = renderConfigList(
      [{ id: 'c1', code: '600036', name: '<img onerror=x>', direction: 'buy', dirText: '买入', conditionText: '价格阈值', quantityText: '100', priceTypeText: '市价' }],
      { emptyText: 'e', quantityLabel: '数量', editText: '编辑', deleteText: '删除' },
    ).value;
    expect(out).not.toContain('<img');
    expect(out).toContain('&lt;img onerror=x&gt;');
    expect(out).toContain('data-action="edit" data-id="c1"');
    expect(out).toContain('class="auto-trade-stock-item buy"');
  });

  it('empty config list shows the empty tip', () => {
    expect(renderConfigList([], { emptyText: 'EMPTY', quantityLabel: '', editText: '', deleteText: '' }).value).toContain('EMPTY');
  });

  it('event rows use the success/failed class and escape the detail text', () => {
    const out = renderEventList(
      [{ successClass: 'failed', timeText: '--', detail: '<script>x</script>', name: 'n', code: '600036', triggerText: '', amountText: '--', tone: 'up', statusText: 's' }],
      'none',
    ).value;
    expect(out).toContain('record-item failed');
    expect(out).not.toContain('<script>');
    expect(out).not.toContain('condition-info');
  });
});
