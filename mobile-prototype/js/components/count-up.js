/**
 * CountUp —— 复刻 React Bits「CountUp」（TextAnimations/CountUp）的 count 模式。
 * 原组件基于 motion 的 animate + easeOut 三次贝塞尔；这里用 rAF + easeOutCubic 实现同等观感。
 *
 * 用法：SS.countUp(el, toCents, { format, duration })
 *   - 元素上记住上一次的值（el._cuValue），再次调用会从旧值滚到新值（适合实时行情更新）；
 *   - prefers-reduced-motion 时直接写入终值。
 * 迁移到 React 时可直接替换为 <CountUp to={...} /> 并传入格式化函数。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const easeOut = (t) => 1 - Math.pow(1 - t, 3);

  SS.countUp = function countUp(el, to, opts = {}) {
    const format = opts.format || ((v) => String(Math.round(v)));
    const duration = opts.duration ?? 1200;
    const from = el._cuValue ?? opts.from ?? 0;
    el._cuValue = to;
    el.classList.add("count-up");
    cancelAnimationFrame(el._cuRaf);
    if (SS.reducedMotion() || from === to || duration <= 0) {
      el.textContent = format(to);
      return;
    }
    const t0 = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - t0) / duration);
      el.textContent = format(from + (to - from) * easeOut(t));
      if (t < 1) el._cuRaf = requestAnimationFrame(tick);
    };
    el._cuRaf = requestAnimationFrame(tick);
  };
})();
