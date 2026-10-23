/**
 * 小型视觉效果（复刻 React Bits 的若干组件，均为原生 JS + CSS）：
 *   - SpotlightCard（Components/SpotlightCard）：.spotlight-card，指针/手指位置的强调色光斑 + 边缘高光
 *   - AnimatedList（Components/AnimatedList）：.animated-list，子项进入视口时 "pop" 入场（错峰）
 *   - BlurText（TextAnimations/BlurText）：SS.blurText(text) 按字拆分，模糊 → 清晰逐字出现
 *   - ShinyText（TextAnimations/ShinyText）：纯 CSS 类 .shiny-text（见 components.css）
 *   - Aurora（Backgrounds/Aurora）：纯 CSS 类 .aurora（极淡强调色光晕，见 components.css）
 * 迁移到 React 时，这些类名与 React Bits 组件一一对应。
 */
(function () {
  const SS = (window.SS = window.SS || {});

  // ---------- SpotlightCard：全局委托，任何 .spotlight-card 自动生效 ----------
  function spot(e) {
    const card = e.target.closest && e.target.closest(".spotlight-card");
    if (!card) return;
    const r = card.getBoundingClientRect();
    card.style.setProperty("--mx", `${e.clientX - r.left}px`);
    card.style.setProperty("--my", `${e.clientY - r.top}px`);
    card.classList.add("is-lit");
    clearTimeout(card._spotT);
    // 触屏没有 hover：按下后保留 0.9s 再淡出
    if (e.pointerType !== "mouse") card._spotT = setTimeout(() => card.classList.remove("is-lit"), 900);
  }
  document.addEventListener("pointermove", spot, { passive: true });
  document.addEventListener("pointerdown", spot, { passive: true });
  document.addEventListener(
    "pointerout",
    (e) => {
      const card = e.target.closest && e.target.closest(".spotlight-card");
      if (card && e.pointerType === "mouse" && !card.contains(e.relatedTarget)) card.classList.remove("is-lit");
    },
    { passive: true }
  );

  // ---------- AnimatedList ----------
  const io =
    "IntersectionObserver" in window
      ? new IntersectionObserver(
          (entries) =>
            entries.forEach((en) => {
              if (en.isIntersecting) {
                en.target.classList.add("is-in");
                io.unobserve(en.target);
              }
            }),
          { threshold: 0.15 }
        )
      : null;

  /** 让容器内的 .animated-list__item 错峰入场；start 用于“加载更多”时从新项开始计数 */
  SS.animatedList = function (container, start = 0) {
    const items = SS.$$(".animated-list__item:not(.is-in)", container);
    items.forEach((it, i) => {
      it.style.setProperty("--d", `${Math.min(i, 10) * 45}ms`);
      if (!io || SS.reducedMotion()) it.classList.add("is-in");
      else io.observe(it);
    });
    return items.length + start;
  };

  // ---------- BlurText ----------
  /** 返回 SafeHtml：逐字 span，带递增延迟 */
  SS.blurText = function (text, cls = "") {
    const chars = Array.from(text);
    return SS.html`<span class="blur-text ${cls}" aria-label="${text}">${chars.map(
      (c, i) => SS.html`<span aria-hidden="true" style="--d:${i * 40}ms">${c === " " ? SS.raw("&nbsp;") : c}</span>`
    )}</span>`;
  };
})();
