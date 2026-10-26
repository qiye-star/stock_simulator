/**
 * 预测卡 / 积分 / 情报卡 / 称号（⑥ B）的注册入口。
 *   routes：/predictions（我的预测）、/prediction/:id（预测揭晓）
 *   挂载点：me.badges（称号）、me.cards（积分 10 / 校准 20 / 情报 30）、me.rows（预测记录 10 / 预测卡模式 20）、
 *           news.majorFooter、event.intel、event.footer、chain.edgeAction、closeSummary.extra
 *   守卫：resume（有待答卡时继续行情前确认）
 *   WS：ws:prediction（opened → 弹卡；answered/expired/void → 刷新并必要时关闭；settled → 积分 toast）、ws:title（称号 toast）
 *   情报按钮：document 委托 [data-intel-edge] / [data-intel-event] → 情报卡抽屉
 *   mock 模式：快讯 ws:news 推送到 e48-6（重大突发）时出卡并截停行情（SS.mockFeatures.predict.sim.open）
 * 只在事件模式存档里出卡；非事件存档的挂件隐藏或显示“即将开放”。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const store = () => SS.store;

  const refreshCard = (id) => store().loadPrediction(id).catch(() => null);
  const refreshOverlay = () => SS.predictionCard.refreshOverlay();

  function onPrediction(msg) {
    const st = store();
    if (!st.predictEnabled()) return;
    if (msg.op === "opened") {
      refreshCard(msg.card_id).then(() => SS.predictionCard.open(msg.card_id));
    } else {
      refreshCard(msg.card_id).then(() => {
        if (msg.op === "settled") {
          if (msg.balance != null && st.state.predict.points) st.state.predict.points.balance = msg.balance;
          SS.toast(msg.points ? `+${msg.points} 积分` : "预测已揭晓", { duration: 2000 });
        }
        if (msg.op === "answered" || msg.op === "expired" || msg.op === "void") {
          if (SS.predictionCard.isOpen(msg.card_id)) SS.predictionCard.close(msg.card_id);
        }
        refreshOverlay();
      });
    }
    st.emitLocal("predict:update", msg);
  }

  function onTitle(msg) {
    const st = store();
    st.state.predict.titles = null;
    (msg.ids || []).forEach((id) => {
      const t = SS.predictTitles.byId(id);
      SS.toast(`解锁称号：${t ? t.name : id}`, { duration: 2400 });
    });
  }

  function startMockTrigger() {
    store().on("ws:news", (msg) => {
      for (const it of msg.items || []) {
        if (it.major && it.stage === "publish") SS.mockFeatures.predict.sim.open(it.event_id);
      }
    });
  }

  SS.features = SS.features || {};
  SS.features.predict = {
    routes: [
      ["/predictions", SS.pages.predictions],
      ["/prediction/:id", SS.pages.prediction],
    ],
    init() {
      const st = store();
      const W = SS.predictWidgets;
      const S = SS.predictSlots;
      SS.slots.register("me.badges", { id: "predict-titles", order: 10, mount: W.mountBadges });
      SS.slots.register("me.cards", { id: "predict-points", order: 10, mount: W.mountPoints });
      SS.slots.register("me.cards", { id: "predict-calib", order: 20, mount: W.mountCalib });
      SS.slots.register("me.cards", { id: "predict-intel", order: 30, mount: W.mountIntel });
      SS.slots.register("me.rows", { id: "predict-records", order: 10, mount: W.mountRecords });
      SS.slots.register("me.rows", { id: "predict-mode", order: 20, mount: W.mountMode });
      SS.slots.register("news.majorFooter", { id: "predict-major", html: S.majorFooter });
      SS.slots.register("event.intel", { id: "predict-intel", html: S.eventIntel });
      SS.slots.register("event.footer", { id: "predict-footer", mount: S.eventFooter });
      SS.slots.register("chain.edgeAction", { id: "predict-edge", html: S.chainEdge });
      SS.slots.register("closeSummary.extra", { id: "predict-pending", order: 20, mount: S.closeExtra });

      SS.guards.add("resume", async () => {
        const open = (st.state.predict.openCards || []).filter((c) => c.status === "open");
        if (!open.length || !st.predictEnabled()) return true;
        return window.confirm("继续将放弃本张预测卡，确定继续？");
      });

      st.on("ws:prediction", onPrediction);
      st.on("ws:title", onTitle);
      st.on("save", () => {
        SS.predictionCard.close();
        st.resetPredict();
        if (st.predictEnabled()) {
          st.ensureCards({ force: true }).then(refreshOverlay).catch(() => {});
          st.loadIntel().catch(() => {});
        }
        refreshOverlay();
      });

      // 情报按钮：委托处理（产业链行内、事件详情锁提示）
      document.addEventListener("click", (e) => {
        const edge = e.target.closest("[data-intel-edge]");
        if (edge) return SS.intelSheet.open({ edgeId: edge.dataset.intelEdge });
        const ev = e.target.closest("[data-intel-event]");
        if (ev) return SS.intelSheet.open({ eventId: ev.dataset.intelEvent });
      });

      if (st.predictEnabled()) {
        st.ensureCards().then(refreshOverlay).catch(() => {});
        st.loadIntel().catch(() => {});
      }
      refreshOverlay();
      if (SS.isMock) startMockTrigger();
    },
  };
})();
