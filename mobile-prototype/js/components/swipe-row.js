/**
 * 左滑操作行（自选列表用）：左滑露出「买入 / 卖出」两个快捷按钮。
 * 结构：
 *   <div class="swipe-row" data-code>
 *     <div class="swipe-row__actions"><button data-action="buy">…</button><button data-action="sell">…</button></div>
 *     <div class="swipe-row__main">…行内容…</div>
 *   </div>
 * 行为：
 *   - 水平拖动超过 1/3 吸附展开，否则回弹；同一时刻只展开一行；
 *   - 展开状态下点行内容 = 收起（不触发进入详情）；
 *   - touch-action: pan-y，保证竖向滚动不受影响；鼠标同样可拖。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const OPEN_W = 144; // 两个 72px 按钮

  SS.swipeRows = function (container, { onAction, onOpen }) {
    let openRow = null;
    const setX = (row, x, animate) => {
      const main = SS.$(".swipe-row__main", row);
      main.style.transition = animate ? "" : "none";
      main.style.transform = x ? `translateX(${x}px)` : "";
      row.classList.toggle("is-open", x !== 0);
    };
    const closeOpen = () => {
      if (openRow) setX(openRow, 0, true);
      openRow = null;
    };

    let st = null; // 当前手势状态
    container.addEventListener("pointerdown", (e) => {
      const row = e.target.closest(".swipe-row");
      if (!row || e.target.closest(".swipe-row__actions")) return;
      if (openRow && openRow !== row) closeOpen();
      st = { row, x0: e.clientX, y0: e.clientY, base: row === openRow ? -OPEN_W : 0, dx: 0, lock: null, id: e.pointerId };
    });
    container.addEventListener("pointermove", (e) => {
      if (!st || e.pointerId !== st.id) return;
      const dx = e.clientX - st.x0;
      const dy = e.clientY - st.y0;
      if (!st.lock) {
        if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
        st.lock = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
        if (st.lock === "x") st.row.setPointerCapture(e.pointerId);
      }
      if (st.lock !== "x") return;
      st.dx = dx;
      let x = st.base + dx;
      if (x > 0) x = x * 0.2; // 右侧阻尼
      if (x < -OPEN_W) x = -OPEN_W + (x + OPEN_W) * 0.25; // 过度左滑阻尼
      setX(st.row, x, false);
    });
    const end = () => {
      if (!st) return;
      const { row, lock, base, dx } = st;
      st = null;
      if (lock !== "x") return;
      row._justSwiped = true;
      setTimeout(() => (row._justSwiped = false), 50);
      const x = base + dx;
      if (x < -OPEN_W / 3) {
        setX(row, -OPEN_W, true);
        if (openRow !== row) SS.haptic(6);
        openRow = row;
        onOpen && onOpen(row);
      } else {
        setX(row, 0, true);
        if (openRow === row) openRow = null;
      }
    };
    container.addEventListener("pointerup", end);
    container.addEventListener("pointercancel", end);

    // 点击：动作按钮 / 收起 / 交给调用方（进入详情）
    container.addEventListener(
      "click",
      (e) => {
        const btn = e.target.closest(".swipe-row__actions [data-action]");
        const row = e.target.closest(".swipe-row");
        if (btn) {
          e.stopPropagation();
          SS.haptic();
          onAction(btn.dataset.action, row.dataset.code);
          closeOpen();
          return;
        }
        if (row && row._justSwiped) {
          // 拖动结束后浏览器补发的 click：吞掉，不改变展开状态
          e.stopPropagation();
          e.preventDefault();
        } else if (row && row === openRow) {
          e.stopPropagation();
          e.preventDefault();
          closeOpen();
        }
      },
      true
    );

    /** 首次进入的“露一下”提示：第一行轻轻左移再回弹 */
    function peek() {
      const first = SS.$(".swipe-row", container);
      if (!first || SS.reducedMotion()) return;
      const main = SS.$(".swipe-row__main", first);
      main.classList.add("is-peek");
      main.addEventListener("animationend", () => main.classList.remove("is-peek"), { once: true });
    }
    return { close: closeOpen, peek };
  };
})();
