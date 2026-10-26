/**
 * 每日挑战（⑦ C）的注册入口。
 *   routes：/challenge（挑战页）、/challenge/board（排行榜）、/challenge/:id/review（复盘）；均为二级页（tab null）
 *   挂载点：play（order 10，每日挑战卡）、market.banner（order 10，挑战存档横幅）
 *   WS：ws:challenge → 重拉今日挑战与回合卡（SS.challengeFlow.refresh）
 *   交易状态栏：挑战存档内 SS.tradeBar.setOverlay("challenge", …)（优先级 30）：运行中为全服暂停 / 快放中 / 最后一段 + hint、不带按钮（入口是顶部横幅），结算后为“回到我的存档”，覆盖暂停与跳过动作
 *   初始化：进入就绪态后拉一次今日挑战（mock 与真实一致）。
 * 挑战存档内不出单人预测卡与情报卡（B 的 CardPolicy 对 challenge 模式关闭），由后端保证。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const store = () => SS.store;
  const M = () => SS.challengeModel;

  let lastOverlay = null;
  /**
   * 挑战存档内：状态栏整体换成挑战口径（08 §5.7），覆盖“暂停 / 跳过 / 继续”动作（挑战中不能暂停或跳速）。
   *   运行中：statusText 全服暂停 / 快放中 / 最后一段，nextSub = tl.hint（停顿时间保密时不给倒计时），无动作（进挑战页用顶部横幅）；
   *   其它（已结算、未同步）：statusText 挑战已结算 / 挑战存档，动作“回到我的存档”。
   * 普通存档：撤掉 overlay。值没变就不重绘（状态栏每秒才会变）。
   */
  function refreshOverlay() {
    const s = store().state;
    const inCh = !!(s.save && s.save.mode === "challenge");
    if (!inCh) {
      if (lastOverlay !== null) SS.tradeBar.setOverlay("challenge", null);
      lastOverlay = null;
      return;
    }
    const ch = s.challenge.today;
    let spec;
    if (ch && ch.status === "running") {
      const tl = M().timeline(ch, s.challenge.skew, Date.now());
      const statusText = ch.phase === "hold" ? "全服暂停" : ch.phase === "final" ? "最后一段" : "快放中";
      // 入口只留顶部“挑战中”横幅（market.banner），状态栏不再放第二个“挑战”按钮；action:null 只隐藏动作区
      spec = { statusText, nextSub: tl.hint || "", action: null };
    } else {
      spec = {
        statusText: ch && ch.status === "settled" ? "挑战已结算" : "挑战存档",
        nextSub: ch && ch.status === "settled" ? "本场成绩见复盘" : "挑战中不能暂停或调速",
        action: { label: "回到我的存档", run: () => SS.challengeFlow.leave() },
      };
    }
    const key = `${spec.statusText}|${spec.nextSub}|${spec.action ? spec.action.label : ""}`;
    if (key === lastOverlay) return;
    lastOverlay = key;
    SS.tradeBar.setOverlay("challenge", { priority: 30, ...spec });
  }

  SS.features = SS.features || {};
  SS.features.challenge = {
    routes: [
      ["/challenge", SS.pages.challenge],
      ["/challenge/board", SS.pages.challengeBoard],
      ["/challenge/:id/review", SS.pages.challengeReview],
    ],
    init() {
      SS.slots.register("play", { id: "challenge", order: 10, mount: SS.challengeCard.mount });
      SS.slots.register("market.banner", { id: "challenge-banner", order: 10, mount: SS.challengeCard.mountBanner });
      store().on("ws:challenge", () => SS.challengeFlow.refresh());
      store().on("challenge:update", refreshOverlay);
      store().on("save", () => {
        store().resetChallenge();
        lastOverlay = null;
        SS.challengeFlow.refresh();
      });
      setInterval(refreshOverlay, 1000);
      SS.challengeFlow.refresh();
    },
  };
})();
