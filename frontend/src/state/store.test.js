import { describe, expect, it, vi } from 'vitest';
import { createStore } from './store.js';

describe('createStore', () => {
  it('shallow-merges patches and returns snapshots', () => {
    const s = createStore({ a: 1, b: 2 });
    s.set({ a: 3 });
    expect(s.get()).toEqual({ a: 3, b: 2 });
  });

  it('accepts an updater function', () => {
    const s = createStore({ n: 1 });
    s.set((st) => ({ n: st.n + 1 }));
    expect(s.get().n).toBe(2);
  });

  it('notifies only when a field actually changes', () => {
    const s = createStore({ a: 1 });
    const fn = vi.fn();
    s.subscribe(fn);
    s.set({ a: 1 });
    expect(fn).not.toHaveBeenCalled();
    s.set({ a: 2 });
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn.mock.calls[0][0]).toEqual({ a: 2 });
    expect(fn.mock.calls[0][1]).toEqual({ a: 1 });
  });

  it('unsubscribe stops notifications and a failing listener does not break others', () => {
    const s = createStore({ a: 0 });
    const bad = vi.fn(() => {
      throw new Error('boom');
    });
    const good = vi.fn();
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    s.subscribe(bad);
    const off = s.subscribe(good);
    s.set({ a: 1 });
    expect(good).toHaveBeenCalledTimes(1);
    off();
    s.set({ a: 2 });
    expect(good).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });
});
