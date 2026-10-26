/**
 * 注册机制：让新玩法（js/features/<name>/）不改核心页面也能挂内容。
 *
 *   SS.features        各功能 index.js 写入 { routes: [[pattern, page], …], init() }，由 app.js 统一注册/初始化
 *   SS.slots           挂载点：页面声明 slot，功能注册 provider
 *   SS.guards          动作拦截（如 "resume"：继续行情前由预测卡确认）
 *   SS.marketLists     行情页分段（自选/全部之外的列表，⑤ 起使用）
 *   SS.assertSameKeys  断言 store 的 mock/real 两套方法名一致
 *
 * provider 抛错不影响宿主页面：mount 时 console.warn 并移除该子容器。
 */
(function () {
  const SS = (window.SS = window.SS || {});

  SS.features = SS.features || {};

  // ---------- slots ----------
  const providers = new Map(); // name → provider[]
  const sorted = (name) => (providers.get(name) || []).slice().sort((a, b) => a.order - b.order);

  SS.slots = {
    /** provider = { id, order = 100, mount?(host, ctx) → cleanup, html?(ctx) → SafeHtml|"" }；同 id 重复注册会覆盖 */
    register(name, provider) {
      const p = { order: 100, ...provider };
      const list = (providers.get(name) || []).filter((x) => x.id !== p.id);
      list.push(p);
      providers.set(name, list);
    },
    /** 为每个带 mount 的 provider 建 <div class="slot"> 子容器（按 order 排序，style.order 同值，便于宿主用 flex 与占位穿插），返回 cleanup */
    mount(name, container, ctx = {}) {
      const cleanups = [];
      for (const p of sorted(name)) {
        if (typeof p.mount !== "function") continue;
        const child = document.createElement("div");
        child.className = "slot";
        child.dataset.slot = name;
        child.dataset.slotId = p.id;
        child.style.order = String(p.order);
        container.appendChild(child);
        try {
          const c = p.mount(child, ctx);
          if (typeof c === "function") cleanups.push(c);
        } catch (e) {
          console.warn(`slot ${name}/${p.id} 挂载失败`, e);
          child.remove();
        }
      }
      return () =>
        cleanups.forEach((f) => {
          try {
            f();
          } catch (e) {
            console.warn(`slot ${name} 清理失败`, e);
          }
        });
    },
    /** 同步装饰器：拼接所有 provider.html(ctx)（用于列表行内的小部件）；字符串会被转义，SafeHtml 原样 */
    html(name, ctx = {}) {
      const parts = [];
      for (const p of sorted(name)) {
        if (typeof p.html !== "function") continue;
        try {
          parts.push(p.html(ctx) || "");
        } catch (e) {
          console.warn(`slot ${name}/${p.id} html 失败`, e);
        }
      }
      return SS.html`${parts}`;
    },
    has(name, id) {
      return (providers.get(name) || []).some((p) => p.id === id);
    },
  };

  // ---------- guards ----------
  const guards = new Map(); // action → fn[]
  SS.guards = {
    /** fn: async () => boolean（false = 拦截） */
    add(action, fn) {
      guards.set(action, [...(guards.get(action) || []), fn]);
    },
    /** 依次执行，任一返回 false 即 false；guard 自己抛错视为放行（不能因为附加功能出错卡住核心操作） */
    async check(action) {
      for (const fn of guards.get(action) || []) {
        try {
          if ((await fn()) === false) return false;
        } catch (e) {
          console.warn(`guard ${action} 出错，放行`, e);
        }
      }
      return true;
    },
  };

  // ---------- 行情页分段 ----------
  const lists = [];
  SS.marketLists = {
    /** { value, label, order, visible() → bool, load() → Promise<{items: Quote[], notes?: {[code]: string}}> } */
    register(def) {
      const i = lists.findIndex((x) => x.value === def.value);
      const item = { order: 100, visible: () => true, ...def };
      if (i >= 0) lists[i] = item;
      else lists.push(item);
    },
    /** 当前可见的分段，按 order 排序 */
    list() {
      return lists
        .filter((x) => {
          try {
            return x.visible();
          } catch (_) {
            return false;
          }
        })
        .sort((a, b) => a.order - b.order);
    },
  };

  /** 断言两套实现的方法名一致（不一致 console.error，不抛错） */
  SS.assertSameKeys = function assertSameKeys(label, a, b) {
    const ka = new Set(Object.keys(a));
    const kb = new Set(Object.keys(b));
    const miss = [...ka].filter((k) => !kb.has(k)).map((k) => `real 缺 ${k}`);
    const extra = [...kb].filter((k) => !ka.has(k)).map((k) => `mock 缺 ${k}`);
    if (miss.length || extra.length) console.error(`[${label}] mock/real 方法名不一致：`, [...miss, ...extra].join("，"));
  };
})();
