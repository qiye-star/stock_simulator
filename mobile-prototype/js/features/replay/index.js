/**
 * 真实复盘（⑨ E）的注册入口。
 *   routes：/replay（选关）、/replay/:id（会话）、/replay/:id/reveal（揭示）；均为二级页（tab null，隐藏 Dock）
 *   挂载点：play（order 30，真实复盘分区，替换玩法页的占位）
 *   不订阅 WS，不切换当前存档；复盘存档不出现在存档列表。
 */
(function () {
  const SS = (window.SS = window.SS || {});

  SS.features = SS.features || {};
  SS.features.replay = {
    routes: [
      ["/replay", SS.pages.replayList],
      ["/replay/:id", SS.pages.replaySession],
      ["/replay/:id/reveal", SS.pages.replayReveal],
    ],
    init() {
      SS.slots.register("play", { id: "replay", order: 30, mount: SS.replayCard.mount });
    },
  };
})();
