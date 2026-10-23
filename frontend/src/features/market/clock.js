/**
 * 游戏时钟显示与暂停 / 跳过按钮（移植自 legacy/game.js updateTimeDisplay 1864-1906 与 time 控制）。
 *
 * 拥有：#market-time #market-status #portfolio-time #portfolio-status #time-pause-btn #time-skip-btn
 */
import { marketStore } from './store.js';
import { clockLabel, clockStatus } from './model.js';
import { setClass, setText } from './dom.js';
import { skipTime, togglePause } from './controller.js';
import { on } from '../../ui/dom.js';

/**
 * @param {import('../index.js').FeatureContext} ctx
 * @param {Document} [doc]
 * @returns {() => void}
 */
export function initClock(ctx, doc = document) {
  const timeEl = doc.getElementById('market-time');
  const statusEl = doc.getElementById('market-status');
  const pTimeEl = doc.getElementById('portfolio-time');
  const pStatusEl = doc.getElementById('portfolio-status');
  const pauseBtn = doc.getElementById('time-pause-btn');
  const skipBtn = doc.getElementById('time-skip-btn');

  function render() {
    const st = marketStore.get();
    const minute = st.saveId ? st.minuteOfDay : null;
    const label = minute === null ? '--:--' : clockLabel(minute);
    const { key, cls } = clockStatus(minute, st.paused);
    const statusText = minute === null ? '--' : ctx.i18n.t(key);
    setText(timeEl, label);
    setText(statusEl, statusText);
    setClass(statusEl, cls);
    setText(pTimeEl, label);
    setText(pStatusEl, statusText);
    setText(pauseBtn, ctx.i18n.t(st.paused ? 'settings.resume' : 'settings.pause'));
  }

  render();
  const unsubscribe = marketStore.subscribe((s, prev) => {
    if (s.minuteOfDay !== prev.minuteOfDay || s.paused !== prev.paused || s.saveId !== prev.saveId) render();
  });
  const offLang = ctx.i18n.onChange(() => render());
  const offPause = pauseBtn ? on(pauseBtn, 'click', () => togglePause()) : () => {};
  const offSkip = skipBtn ? on(skipBtn, 'click', () => skipTime()) : () => {};

  return () => {
    unsubscribe();
    offLang();
    offPause();
    offSkip();
  };
}
