/**
 * 情报卡抽屉（SS.intelSheet）：
 *   open({edgeId})   产业链边：L1 揭示强度（price_l1）；L2 揭示强度 + 滞后（price_l2，已有 L1 则补差价）。购买后刷新产业链。
 *   open({eventId})  传闻真假提示（price rumor_hint，每存档每事件一次，准确率 80%）。已揭晓的传闻不可购买。
 * 价格一律读 IntelStateOut.prices；余额与今日剩余来自同一响应。错误走 store.notifyError（ERROR_TEXT 的 POINTS_INSUFFICIENT / INTEL_*）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const store = () => SS.store;

  const left = (intel) => Math.max(0, intel.daily_limit - intel.used_today);

  function open(opts) {
    if (opts && opts.edgeId) return openEdge(opts.edgeId);
    if (opts && opts.eventId) return openEvent(opts.eventId);
  }

  // ---------- 产业链边 ----------
  async function openEdge(edgeId) {
    let chain;
    let intel;
    try {
      [chain, intel] = await Promise.all([store().loadSupplyChain(), store().loadIntel()]);
    } catch (err) {
      return store().notifyError(err);
    }
    let edge = (chain.edges || []).find((e) => e.id === edgeId);
    if (!edge) return SS.toast("产业链关系不存在", { icon: null, duration: 1800 });
    let picked = edge.revealed_level === 0 ? 1 : 2;
    let result = null;
    let busy = false;

    SS.sheet.open({
      title: "情报卡",
      render(body) {
        const paint = () => {
          const RELATION = SS.newsModel.RELATION_TEXT;
          const lvl = edge.revealed_level || 0;
          const p = intel.prices;
          const price1 = p.edge_l1;
          const price2 = lvl === 0 ? p.edge_l2 : p.edge_l2 - p.edge_l1;
          const options = lvl === 0 ? [[1, "强度", price1], [2, "强度 + 滞后", price2]] : lvl === 1 ? [[2, "补差价看滞后", price2]] : [];
          const current = lvl >= 1 ? `强度 ${edge.strength}${lvl >= 2 && edge.lag_days != null ? ` · 滞后 ${edge.lag_days} 天` : ""}` : "未揭示";
          if (picked && !options.some((o) => o[0] === picked)) picked = options.length ? options[0][0] : 0;
          const sel = options.find((o) => o[0] === picked);
          SS.mount(
            body,
            html`<div class="intel">
              <div class="intel__target">
                <span class="intel__name">${edge.from_industry} → ${edge.to_industry}</span>
                <span class="t2 xs">${RELATION[edge.relation] || edge.relation}</span>
              </div>
              <p class="t2 sm">当前：<span class="num">${current}</span></p>
              ${options.length
                ? html`<div class="seg seg--inline-full intel__seg" role="group" aria-label="揭示层级">
                    ${options.map(([v, t, pr]) => html`<button type="button" data-level="${v}" class="${picked === v ? "is-active" : ""}" aria-pressed="${String(picked === v)}">${t} <span class="num">${pr}</span></button>`)}
                  </div>
                  <p class="t3 xs">强度决定两个行业之间传导的力度；滞后是消息隔几天才传到下游。</p>
                  <button type="button" class="btn btn-primary btn-block" data-role="buy" ${busy || !sel ? "disabled" : ""}>花 ${sel ? sel[2] : 0} 积分查看</button>`
                : html`<p class="t2 sm">这条关系已全部揭示</p>`}
              <p class="t3 xs num">余额 ${SS.fmt.qty(intel.balance)} 分 · 今日剩余 ${left(intel)} / ${intel.daily_limit} 次</p>
              ${result ? html`<p class="intel__result" role="status">${result}</p>` : ""}
            </div>`
          );
          SS.$$("[data-level]", body).forEach((b) =>
            b.addEventListener("click", () => {
              picked = Number(b.dataset.level);
              SS.haptic(5);
              paint();
            })
          );
          const buy = SS.$('[data-role="buy"]', body);
          if (buy)
            buy.addEventListener("click", async () => {
              if (busy || !sel) return;
              busy = true;
              paint();
              try {
                const out = await store().buyEdgeReveal(edge.id, picked);
                const e2 = out.edge || {};
                result = out.charged ? `已揭示：强度 ${e2.strength}${e2.lag_days != null ? ` · 滞后 ${e2.lag_days} 天` : ""}（花 ${out.charged} 分）` : "这条关系已揭示";
                intel = await store().loadIntel();
                chain = await store().loadSupplyChain({ force: true });
                edge = (chain.edges || []).find((e) => e.id === edgeId) || edge; // 刷新“当前”与按钮档位
                store().emitLocal("intel", out);
                SS.toast("情报已解锁", { duration: 1600 });
              } catch (err) {
                store().notifyError(err);
              } finally {
                busy = false;
                if (SS.$(".intel", body)) paint();
              }
            });
        };
        paint();
      },
    });
  }

  // ---------- 传闻真假提示 ----------
  async function openEvent(eventId) {
    let detail;
    let intel;
    try {
      [detail, intel] = await Promise.all([store().loadEvent(eventId), store().loadIntel()]);
    } catch (err) {
      return store().notifyError(err);
    }
    let hint = (intel.rumor_hints || []).find((h) => h.event_id === eventId) || null;
    let busy = false;
    const resolved = detail.rumor_status && detail.rumor_status !== "unresolved";

    SS.sheet.open({
      title: "情报卡",
      render(body) {
        const paint = () => {
          const p = intel.prices;
          let state;
          if (hint) {
            state = html`<p class="intel__result" role="status">${hint.hint === "likely_true" ? "可能为真" : "可能为假"} · 准确率 ${hint.accuracy_pct}%</p>`;
          } else if (resolved) {
            state = html`<p class="t2 sm">这条传闻已经揭晓，无需情报。</p>`;
          } else {
            state = html`<button type="button" class="btn btn-primary btn-block" data-role="buy" ${busy ? "disabled" : ""}>花 ${p.rumor_hint} 积分查看</button>`;
          }
          SS.mount(
            body,
            html`<div class="intel">
              <div class="intel__target"><span class="intel__name">${detail.title}</span><span class="t2 xs">传闻真假提示</span></div>
              <p class="t2 sm">告诉你这条传闻更可能真还是假，准确率 80%。</p>
              ${state}
              <p class="t3 xs num">余额 ${SS.fmt.qty(intel.balance)} 分 · 今日剩余 ${left(intel)} / ${intel.daily_limit} 次</p>
            </div>`
          );
          const buy = SS.$('[data-role="buy"]', body);
          if (buy)
            buy.addEventListener("click", async () => {
              if (busy) return;
              busy = true;
              paint();
              try {
                const out = await store().buyRumorHint(eventId);
                hint = out.hint;
                intel = await store().loadIntel();
                store().emitLocal("intel", out);
              } catch (err) {
                store().notifyError(err);
              } finally {
                busy = false;
                if (SS.$(".intel", body)) paint();
              }
            });
        };
        paint();
      },
    });
  }

  SS.intelSheet = { open };
})();
