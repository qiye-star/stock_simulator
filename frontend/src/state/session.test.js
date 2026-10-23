import { describe, expect, it, beforeEach } from 'vitest';
import { appStore } from './store.js';
import {
  PROTECTED_SCREENS,
  SCREENS,
  TAB_ALIASES,
  bumpSaves,
  getSession,
  isProtectedScreen,
  session,
  setCurrentSave,
  setUser,
  showScreen,
  showTab,
} from './session.js';

/** 最小 DOM 替身：只实现 showScreen / showTab 用到的接口。 */
function fakeDoc(ids, classes = {}) {
  const nodes = new Map();
  const make = (id) => ({
    id,
    classes: new Set(classes[id] ?? []),
    classList: {
      add(c) { nodes.get(id).classes.add(c); },
      remove(c) { nodes.get(id).classes.delete(c); },
      toggle(c, on) { const s = nodes.get(id).classes; on === undefined ? (s.has(c) ? s.delete(c) : s.add(c)) : (on ? s.add(c) : s.delete(c)); },
      contains(c) { return nodes.get(id).classes.has(c); },
    },
    dataset: {},
  });
  for (const id of ids) nodes.set(id, make(id));
  const navs = [...nodes.values()].filter((n) => n.id.endsWith('-nav'));
  return {
    nodes,
    getElementById: (id) => nodes.get(id) ?? null,
    querySelectorAll: (sel) => {
      if (sel === '.screen') return ids.filter((i) => i.endsWith('-screen')).map((i) => nodes.get(i));
      if (sel === '.page') return ids.filter((i) => i.endsWith('-page')).map((i) => nodes.get(i));
      if (sel === '.nav-btn') return navs;
      return [];
    },
  };
}

describe('showScreen', () => {
  beforeEach(() => {
    setUser(null);
    setCurrentSave(null);
  });

  it('redirects protected screens to auth when logged out', () => {
    const doc = fakeDoc(['auth-screen', 'main-screen', 'save-select-screen']);
    expect(showScreen(SCREENS.MAIN, doc)).toBe(SCREENS.AUTH);
    expect(doc.nodes.get('auth-screen').classes.has('active')).toBe(true);
    expect(getSession().screen).toBe(SCREENS.AUTH);
  });

  it('shows protected screens once a user is set', () => {
    const doc = fakeDoc(['auth-screen', 'main-screen']);
    setUser({ id: 'u1', username: 'bob' });
    expect(showScreen(SCREENS.MAIN, doc)).toBe(SCREENS.MAIN);
    expect(doc.nodes.get('main-screen').classes.has('active')).toBe(true);
    expect(doc.nodes.get('auth-screen').classes.has('active')).toBe(false);
  });

  it('lists exactly the protected screens', () => {
    expect(PROTECTED_SCREENS).toEqual(['main-screen', 'save-select-screen', 'game-setup-screen']);
    expect(isProtectedScreen('auth-screen')).toBe(false);
  });
});

describe('showTab', () => {
  it('maps the legacy position alias to portfolio and toggles the page', () => {
    const doc = fakeDoc(['market-page', 'portfolio-page'], {});
    expect(TAB_ALIASES.position).toBe('portfolio');
    expect(showTab('position', doc)).toBe('portfolio');
    expect(doc.nodes.get('portfolio-page').classes.has('active')).toBe(true);
    expect(session.get().tab).toBe('portfolio');
  });
});

describe('store sync', () => {
  it('mirrors user and current save into appStore', () => {
    setUser({ id: 'u9', username: 'zoe', theme: 'dark' });
    expect(appStore.get().user).toEqual({ id: 'u9', username: 'zoe' });
    setCurrentSave({ id: 's1' });
    expect(appStore.get().currentSaveId).toBe('s1');
    setCurrentSave(null);
    expect(appStore.get().currentSaveId).toBeNull();
  });

  it('bumpSaves increments the list revision', () => {
    const before = session.get().savesRev;
    bumpSaves();
    expect(session.get().savesRev).toBe(before + 1);
  });
});
