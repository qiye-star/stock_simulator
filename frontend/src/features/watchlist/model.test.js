import { describe, expect, it } from 'vitest';
import { toggleWatch } from './model.js';

describe('toggleWatch', () => {
  it('adds a missing code and removes an existing one without mutating input', () => {
    const list = ['600036'];
    expect(toggleWatch(list, '601398')).toEqual({ next: ['600036', '601398'], added: true });
    expect(toggleWatch(list, '600036')).toEqual({ next: [], added: false });
    expect(list).toEqual(['600036']);
  });
});
