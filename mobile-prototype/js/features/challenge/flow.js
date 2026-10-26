/**
 * 每日挑战的流程动作（SS.challengeFlow）：刷新今日挑战与本人回合卡、参加、退出挑战存档。
 * 页面与挂件都经这里走，错误码在这里转成提示（toast）或状态（state.challenge.error），页面只负责画。
 *   refresh()        GET today（+ 运行中时拉回合卡）→ 写 state.challenge → emit "challenge:update"
 *   enter(id)        参加；真实版同时切到挑战存档（store.enterChallenge）
 *   leave()          退出挑战存档，回到参加前的普通存档
 *   needsRefresh(tl, lastAt, now)  倒计时到点后重拉（节流 3 秒）；快放段（tl.fast，停顿时刻保密）每 5 秒轮询一次，
 *                                  与后端 CHALLENGE_HOLD_POLL_MS 一致，WS 断开时也能发现停顿与结算
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const store = () => SS.store;

  const ENTER_TEXT = {
    CHALLENGE_ENTRY_CLOSED: "今日挑战已停止报名",
    CHALLENGE_ENDED: "挑战已结束",
    CHALLENGE_NOT_STARTED: "挑战尚未开始",
  };

  async function refresh() {
    const s = store().state.challenge;
    try {
      const ch = await store().loadTodayChallenge();
      s.error = null;
      if (ch.status === "running") await store().loadChallengeRounds(ch.id).catch(() => {});
    } catch (err) {
      s.error = (err && err.code) || "NETWORK";
    }
    s.loaded = true;
    store().emitLocal("challenge:update", {});
  }

  async function enter(id) {
    try {
      const entry = await store().enterChallenge(id);
      // 后端报名总会建挑战存档；eligible=false 只表示不计入排名（账号注册时间未满门槛），仍可体验
      if (entry.eligible === false) SS.toast("本场不计入排名（账号未满门槛），可以先体验", { icon: null, duration: 2600 });
      else SS.toast("已参加今日挑战", { duration: 1600 });
      await refresh();
      return entry;
    } catch (err) {
      if (err && ENTER_TEXT[err.code]) SS.toast(ENTER_TEXT[err.code], { icon: null, duration: 2000 });
      else store().notifyError(err);
      await refresh();
      return null;
    }
  }

  async function leave() {
    try {
      await store().leaveChallenge();
      SS.toast("已回到我的存档", { duration: 1600 });
    } catch (err) {
      store().notifyError(err);
    }
    await refresh();
  }

  /** tl 为 SS.challengeModel.timeline 的结果；lastAt 为上次拉取的毫秒（判定在 model.refreshDue） */
  const needsRefresh = (tl, lastAt, now) => SS.challengeModel.refreshDue(tl, lastAt, now);

  SS.challengeFlow = { refresh, enter, leave, needsRefresh };
})();
