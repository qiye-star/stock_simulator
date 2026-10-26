/** js/lib/predict-math.js：档位+把握分布、argmax、把握范围、分档文案（02 §5.2 用例） */
export default function (SS, assert, t) {
  const PM = SS.predictMath;
  const E = [-600, -200, 200, 600];

  t("probsFromPick 与 02 §5.2 用例一致", () => {
    assert.deepEqual(PM.probsFromPick(3, 70, 5), [7, 7, 8, 70, 8]);
    assert.deepEqual(PM.probsFromPick(1, 80, 2), [20, 80]);
    assert.deepEqual(PM.probsFromPick(2, 20, 5), [20, 20, 20, 20, 20]);
  });

  t("probsFromPick 任意输入合计 100 且 pick 处最大", () => {
    for (const k of [2, 5]) {
      for (let pick = 0; pick < k; pick++) {
        for (let conf = 20; conf <= 100; conf += 5) {
          const p = PM.probsFromPick(pick, conf, k);
          assert.equal(p.reduce((a, b) => a + b, 0), 100);
          assert.equal(p[pick], conf);
          assert.ok(p.every((x) => x >= 0));
        }
      }
    }
  });

  t("argmaxPick：唯一最大返回下标，并列返回 null", () => {
    assert.equal(PM.argmaxPick([7, 7, 8, 70, 8]), 3);
    assert.equal(PM.argmaxPick([20, 20, 20, 20, 20]), null);
    assert.equal(PM.argmaxPick([50, 50]), null);
    assert.equal(PM.argmaxPick([20, 80]), 1);
  });

  t("confRange：方向题 20–100 默认 50，传闻题 50–100 默认 70，步长 5", () => {
    assert.deepEqual(PM.confRange(5), { min: 20, max: 100, step: 5, def: 50 });
    assert.deepEqual(PM.confRange(2), { min: 50, max: 100, step: 5, def: 70 });
  });

  t("bucketLabels：去尾零、负号用 U+2212", () => {
    assert.deepEqual(PM.bucketLabels(E), ["<−6%", "−6~−2", "−2~2", "2~6", "≥6%"]);
    assert.deepEqual(PM.bucketLabels([-250, -100, 100, 250]), ["<−2.5%", "−2.5~−1", "−1~1", "1~2.5", "≥2.5%"]);
  });

  t("bucketRangeText：结算页第 N 档区间", () => {
    assert.equal(PM.bucketRangeText(0, E), "<−6%");
    assert.equal(PM.bucketRangeText(1, E), "−6%~−2%");
    assert.equal(PM.bucketRangeText(3, E), "2%~6%");
    assert.equal(PM.bucketRangeText(4, E), "≥6%");
  });
}
