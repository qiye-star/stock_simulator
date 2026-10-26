/**
 * BottomSheet 底部抽屉 + Toast + 分段控件 + 数量步进器。
 *
 * SS.sheet.open({ title, render(body, api), onClose }) → api
 *   api.close() / api.el / api.body
 * 交互：
 *   - 点击遮罩、按 Esc、下拉把手（或内容已滚到顶时下拉）超过阈值/速度即关闭；
 *   - 打开时锁定焦点在抽屉内的第一个可聚焦元素，关闭后焦点回到触发元素。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const open = new Set();
  // 等待“没有任何抽屉打开”再执行的任务（如交易说明的首次自动弹出，让位于预测卡）
  const idleQueue = [];
  function drainIdle() {
    while (open.size === 0 && idleQueue.length) idleQueue.shift()();
  }

  function openSheet({ title = "", render, onClose, className = "" }) {
    const host = SS.$(".app");
    const lastFocus = document.activeElement;
    const wrap = SS.el(SS.html`<div class="sheet-layer ${className}">
      <div class="sheet-scrim"></div>
      <section class="sheet" tabindex="-1" role="dialog" aria-modal="true" aria-label="${title}">
        <div class="sheet__grab"><span class="sheet__handle"></span></div>
        ${title ? SS.html`<header class="sheet__head"><h2 class="sheet__title">${title}</h2>
          <button class="icon-btn sheet__close" aria-label="关闭">${SS.icon("close")}</button></header>` : ""}
        <div class="sheet__body"></div>
      </section>
    </div>`);
    host.appendChild(wrap);
    const sheet = SS.$(".sheet", wrap);
    const body = SS.$(".sheet__body", wrap);
    let closed = false;

    const api = {
      el: sheet,
      body,
      close() {
        if (closed) return;
        closed = true;
        open.delete(api);
        wrap.classList.remove("is-open");
        sheet.style.transform = "";
        const done = () => wrap.remove();
        if (SS.reducedMotion()) done();
        else setTimeout(done, 320);
        document.removeEventListener("keydown", onKey);
        onClose && onClose();
        if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true });
        drainIdle(); // 焦点还原之后再开排队的抽屉，焦点落在新抽屉里
      },
    };
    open.add(api);
    render(body, api);

    const onKey = (e) => e.key === "Escape" && api.close();
    document.addEventListener("keydown", onKey);
    SS.$(".sheet-scrim", wrap).addEventListener("click", api.close);
    const closeBtn = SS.$(".sheet__close", wrap);
    if (closeBtn) closeBtn.addEventListener("click", api.close);

    // ---------- 拖拽关闭 ----------
    let startY = 0;
    let dy = 0;
    let lastY = 0;
    let lastT = 0;
    let v = 0;
    let dragging = false;
    const canDrag = (e) =>
      e.target.closest(".sheet__grab, .sheet__head") || (body.scrollTop <= 0 && !e.target.closest("input, select, button, .stepper, .seg"));
    sheet.addEventListener("pointerdown", (e) => {
      if (!canDrag(e)) return;
      dragging = true;
      startY = lastY = e.clientY;
      lastT = performance.now();
      dy = 0;
      v = 0;
    });
    sheet.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      dy = Math.max(0, e.clientY - startY);
      if (dy > 6 && !sheet.hasPointerCapture(e.pointerId)) sheet.setPointerCapture(e.pointerId);
      const now = performance.now();
      v = (e.clientY - lastY) / Math.max(1, now - lastT);
      lastY = e.clientY;
      lastT = now;
      if (dy > 0) {
        sheet.classList.add("is-dragging");
        sheet.style.transform = `translateY(${dy}px)`;
      }
    });
    const end = () => {
      if (!dragging) return;
      dragging = false;
      sheet.classList.remove("is-dragging");
      if (dy > Math.min(140, sheet.offsetHeight * 0.3) || v > 0.6) api.close();
      else sheet.style.transform = "";
    };
    sheet.addEventListener("pointerup", end);
    sheet.addEventListener("pointercancel", end);

    requestAnimationFrame(() => {
      wrap.classList.add("is-open");
      // 不自动聚焦输入框（手机上会弹出键盘），只把焦点移入对话框
      const f = SS.$("[data-autofocus]", sheet) || sheet;
      f && f.focus({ preventScroll: true });
    });
    return api;
  }

  SS.sheet = {
    open: openSheet,
    closeAll: () => Array.from(open).forEach((a) => a.close()),
    /** 当前是否有抽屉/弹层打开 */
    hasOpen: () => open.size > 0,
    /** 没有抽屉打开时立即执行 fn，否则排队，等最后一个抽屉关闭后再执行（一次只执行一个，执行中又开了抽屉则其余继续等） */
    whenIdle(fn) {
      if (open.size === 0) return fn();
      idleQueue.push(fn);
    },
  };

  // ---------- Toast ----------
  SS.toast = function (msg, { icon = "check", duration = 2000 } = {}) {
    const host = SS.$(".app");
    SS.$$(".toast", host).forEach((t) => t.remove());
    const t = SS.el(SS.html`<div class="toast" role="status">${icon ? SS.icon(icon) : ""}<span>${msg}</span></div>`);
    host.appendChild(t);
    requestAnimationFrame(() => t.classList.add("is-in"));
    setTimeout(() => {
      t.classList.remove("is-in");
      setTimeout(() => t.remove(), 300);
    }, duration);
  };

  // ---------- 分段控件 ----------
  /** el 为 .seg 容器，子按钮带 data-value；选中项强调色底板滑动 */
  SS.segmented = function (el, onChange) {
    const btns = SS.$$("button[data-value]", el);
    const set = (val, fire) => {
      btns.forEach((b, i) => {
        const on = b.dataset.value === val;
        b.classList.toggle("is-active", on);
        b.setAttribute("aria-pressed", on);
        if (on) {
          el.style.setProperty("--seg-i", i);
          el.style.setProperty("--seg-n", btns.length);
        }
      });
      el.dataset.value = val;
      if (fire && onChange) onChange(val);
    };
    el.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-value]");
      if (!b || b.disabled || b.dataset.value === el.dataset.value) return;
      SS.haptic(6);
      set(b.dataset.value, true);
    });
    const init = (btns.find((b) => b.classList.contains("is-active")) || btns[0]).dataset.value;
    set(init, false);
    return { set: (v) => set(v, false), get: () => el.dataset.value };
  };

  // ---------- 步进器 ----------
  /**
   * el 为 .stepper 容器（含 [data-step=-1|1] 按钮与 input）。
   * get/set 以整数为单位（数量=股，价格=分）；display/parse 负责与输入框文本互转。
   */
  SS.stepper = function (el, { value, step = 1, min = 0, max = Infinity, display = String, parse = Number, onChange }) {
    const input = SS.$("input", el);
    let cur = value;
    const clamp = (v) => Math.min(max, Math.max(min, v));
    const write = () => (input.value = display(cur));
    const set = (v, fire = true) => {
      cur = clamp(v);
      write();
      if (fire && onChange) onChange(cur);
    };
    let holdT = null;
    const bump = (d) => set(Math.round((cur + d * step) / step) * step);
    SS.$$("[data-step]", el).forEach((b) => {
      const d = Number(b.dataset.step);
      // 长按连续步进
      b.addEventListener("pointerdown", () => {
        bump(d);
        SS.haptic(4);
        let delay = 380;
        const loop = () => {
          bump(d);
          delay = Math.max(60, delay * 0.8);
          holdT = setTimeout(loop, delay);
        };
        holdT = setTimeout(loop, delay);
      });
      ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => b.addEventListener(ev, () => clearTimeout(holdT)));
    });
    input.addEventListener("change", () => {
      const v = parse(input.value);
      if (v == null || Number.isNaN(v)) write();
      else set(v);
    });
    input.addEventListener("focus", () => input.select());
    write();
    return { get: () => cur, set, setMax: (m) => ((max = m), set(cur, false)) };
  };
})();
