/**
 * 校准曲线（SS.predictChart.calibration）：内部生成的 SVG，只输出 class，颜色由 css/features/predict.css 决定。
 *   calibration(bins, w, h) → SafeHtml（无可画的点时返回空字符串，由调用方决定文案）
 * 横轴：声称把握；纵轴：实际命中率；虚线为对角线（完美校准）；点半径 3 + 2·n/maxN。几何见 SS.predictModel.calibrationPoints。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const M = SS.predictModel;

  function calibration(bins, w = 320, h = 150) {
    const g = M.calibrationPoints(bins, w, h);
    if (!g.pts.length) return "";
    const { l, t, b } = g.P;
    const x0 = l;
    const x1 = l + g.iw;
    const y0 = t + g.ih; // 0%
    const y1 = t; // 100%
    const pts = g.pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
    const dots = g.pts.map((p) => `<circle class="calib-dot" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${p.r.toFixed(1)}"><title>${p.n} 张</title></circle>`).join("");
    const svg = `<svg class="calib-chart" viewBox="0 0 ${w} ${h}" width="100%" role="img" aria-label="校准曲线：声称把握与实际命中率">
      <line class="calib-axis" x1="${x0}" y1="${y0}" x2="${x1}" y2="${y0}"></line>
      <line class="calib-axis" x1="${x0}" y1="${y1}" x2="${x0}" y2="${y0}"></line>
      <line class="calib-diag" x1="${x0}" y1="${y0}" x2="${x1}" y2="${y1}"></line>
      <polyline class="calib-line" points="${pts}"></polyline>
      ${dots}
      <text class="calib-label" x="${x0 - 6}" y="${y0 + 4}" text-anchor="end">0%</text>
      <text class="calib-label" x="${x0 - 6}" y="${y1 + 4}" text-anchor="end">100%</text>
      <text class="calib-label" x="${x0}" y="${h - 4}" text-anchor="start">把握 0%</text>
      <text class="calib-label" x="${x1}" y="${h - 4}" text-anchor="end">100%</text>
    </svg>`;
    return SS.raw(svg);
  }

  SS.predictChart = { calibration };
})();
