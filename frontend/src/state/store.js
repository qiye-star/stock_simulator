/**
 * 极简发布订阅 store（无依赖）。
 *
 *   const store = createStore({ count: 0 });
 *   const off = store.subscribe((state, prev) => render(state));
 *   store.set({ count: 1 });            // 浅合并；仅当某个字段 !Object.is 时通知
 *   store.set(s => ({ count: s.count + 1 }));
 *   store.get();                        // 当前快照（只读约定，请勿修改返回值）
 */

/**
 * @template T
 * @typedef {(state: T, prev: T) => void} Listener
 */

/**
 * @template {Record<string, unknown>} T
 * @param {T} initial
 */
export function createStore(initial) {
  /** @type {T} */
  let state = { ...initial };
  /** @type {Set<Listener<T>>} */
  const listeners = new Set();

  return {
    /** @returns {T} */
    get() {
      return state;
    },

    /**
     * @param {Partial<T> | ((s: T) => Partial<T>)} patch
     */
    set(patch) {
      const change = typeof patch === 'function' ? patch(state) : patch;
      const prev = state;
      let changed = false;
      for (const key of Object.keys(change)) {
        if (!Object.is(prev[key], change[key])) {
          changed = true;
          break;
        }
      }
      if (!changed) return;
      state = { ...prev, ...change };
      for (const fn of [...listeners]) {
        try {
          fn(state, prev);
        } catch (err) {
          console.error('[store] listener failed:', err);
        }
      }
    },

    /**
     * @param {Listener<T>} fn
     * @returns {() => void} 取消订阅
     */
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}

/**
 * 应用级状态。字段与服务端 /me 对齐的部分以 API 为准。
 * @typedef {{ user: null | { id: string, username: string }, lang: 'zh-CN' | 'en-US', theme: 'dark' | 'light' | 'festival', currentSaveId: string | null }} AppState
 */

/** @type {AppState} */
const INITIAL_APP_STATE = {
  user: null,
  lang: 'zh-CN',
  theme: 'dark',
  currentSaveId: null,
};

export const appStore = createStore(INITIAL_APP_STATE);
