/**
 * 预测市场（⑧ D）的注册入口。
 *   routes：/pm（列表）、/pm/records（记录，必须先于 /pm/:id）、/pm/:id（合约详情）；均为二级页（tab null）
 *   挂载点：play（order 20，玩法页的预测市场分区）
 *   WS：页面存活期间由 store 连接 /ws/prediction-markets（见 store.js），离开即关闭；不在 init 里常驻连接。
 *   mock：列表页与详情页存活期间每 4 s 模拟一次全服成交（store.js 的 mock 定时器）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  SS.features = SS.features || {};
  SS.features.pm = {
    routes: [
      ["/pm", SS.pages.pmList],
      ["/pm/records", SS.pages.pmRecords],
      ["/pm/:id", SS.pages.pmDetail],
    ],
    init() {
      SS.slots.register("play", { id: "pm", order: 20, mount: SS.pmPlayCard.mount });
    },
  };
})();
