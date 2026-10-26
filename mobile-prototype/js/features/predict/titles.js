/**
 * 称号目录（用户级，02 §8）。判定在后端；这里只有展示用的名称、等级与条件说明。
 *   SS.predictTitles.list        按目录顺序的 [{id, name, level, desc}]
 *   SS.predictTitles.byId(id)    取一项（未知 id 返回 null）
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const list = [
    { id: "forecaster_1", name: "初试预言", level: "bronze", desc: "作答第 1 张预测卡" },
    { id: "forecaster_20", name: "常驻预言家", level: "silver", desc: "作答 20 张预测卡" },
    { id: "forecaster_100", name: "百卦不倦", level: "gold", desc: "作答 100 张预测卡" },
    { id: "bullseye", name: "正中靶心", level: "silver", desc: "方向题拿到 100 分 1 次" },
    { id: "chain_reader", name: "读链人", level: "silver", desc: "排序题拿到 100 分 3 次" },
    { id: "rumor_buster", name: "辟谣达人", level: "silver", desc: "传闻题命中 5 次" },
    { id: "streak_10", name: "稳定发挥", level: "gold", desc: "连续 10 张卡的平均基线分为正" },
    { id: "calibrated", name: "校准大师", level: "gold", desc: "概率题 40 个样本以上，校准误差不超过 8%" },
    { id: "analyst", name: "首席分析师", level: "legend", desc: "作答 50 张卡且平均基线分不低于 30" },
    { id: "intel_buyer", name: "情报贩子", level: "bronze", desc: "购买 5 次情报卡" },
    { id: "points_10k", name: "积分大亨", level: "gold", desc: "累计获得 10000 积分" },
  ];
  const byIdMap = Object.fromEntries(list.map((t) => [t.id, t]));
  SS.predictTitles = { list, byId: (id) => byIdMap[id] || null };
})();
