/**
 * 轻量 SVG 图表（无依赖）。
 *
 * 做法：SVG 使用固定 viewBox + preserveAspectRatio="none" 自适应宽度，
 * 线条加 vector-effect="non-scaling-stroke" 保持粗细；文字标签放在 HTML 层，避免被拉伸。
 * 颜色只通过 class（up/down/flat/accent）继承 currentColor，不在这里写死色值。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const fmt = () => SS.fmt;

  const pts = (arr) => arr.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  let gid = 0;

  /** 迷你走势线：series 为分时价格数组（分），以昨收为基线 */
  function sparkline(series, prevClose, w = 64, h = 28) {
    const n = series.length;
    const total = Math.max(n, 2); // 迷你图铺满宽度，只看形态
    const lo = Math.min(prevClose, ...series);
    const hi = Math.max(prevClose, ...series);
    const span = hi - lo || 1;
    const y = (v) => h - 2 - ((v - lo) / span) * (h - 4);
    const line = series.map((v, i) => [(i / (total - 1)) * w, y(v)]);
    const cls = fmt().trend(series[n - 1] - prevClose);
    const by = y(prevClose).toFixed(2);
    return `<svg class="spark ${cls}" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">
      <line x1="0" x2="${w}" y1="${by}" y2="${by}" class="baseline"/>
      <polyline points="${pts(line)}" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>`;
  }

  /** 分时图：x 轴固定 241 个交易分钟（9:30-11:30 + 13:00-15:00），y 轴以昨收对称 */
  function intraday(series, prevClose, W = 343, H = 180) {
    const total = 241;
    const dev = Math.max(...series.map((v) => Math.abs(v - prevClose)), prevClose * 0.01);
    const lo = prevClose - dev;
    const hi = prevClose + dev;
    const y = (v) => 4 + (1 - (v - lo) / (hi - lo)) * (H - 8);
    const x = (i) => (i / (total - 1)) * W;
    const line = series.map((v, i) => [x(i), y(v)]);
    const cls = fmt().trend(series[series.length - 1] - prevClose);
    const id = "ga" + ++gid;
    const area = `0,${H} ${pts(line)} ${x(series.length - 1).toFixed(2)},${H}`;
    // 均价线（灰色，用简单累计均值近似）
    let acc = 0;
    const avg = series.map((v, i) => [x(i), y((acc += v) / (i + 1))]);
    const svg = `<svg class="chart-svg ${cls}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <defs><linearGradient id="${id}" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" stop-color="currentColor" stop-opacity="0.22"/>
        <stop offset="1" stop-color="currentColor" stop-opacity="0"/>
      </linearGradient></defs>
      <line class="grid" x1="0" x2="${W}" y1="${H / 2}" y2="${H / 2}" vector-effect="non-scaling-stroke" stroke-dasharray="3 4"/>
      <line class="grid" x1="${W / 2}" x2="${W / 2}" y1="0" y2="${H}" vector-effect="non-scaling-stroke"/>
      <polygon points="${area}" fill="url(#${id})"/>
      <polyline class="avg" points="${pts(avg)}" fill="none" vector-effect="non-scaling-stroke"/>
      <polyline points="${pts(line)}" fill="none" stroke="currentColor" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
      <circle class="live-dot" cx="${x(series.length - 1)}" cy="${y(series[series.length - 1])}" r="2.5" fill="currentColor"/>
    </svg>`;
    return { svg, lo, hi, x, y, total, W, H };
  }

  /** 日 K：candles 为 CandleOut[]（最后一根可为今日实时），附成交量与 MA5 */
  function kline(candles, W = 343, H = 180, VH = 44) {
    const n = candles.length;
    const lo = Math.min(...candles.map((c) => c.low_cents));
    const hi = Math.max(...candles.map((c) => c.high_cents));
    const pad = (hi - lo) * 0.06 || 1;
    const y = (v) => ((hi + pad - v) / (hi - lo + 2 * pad)) * H;
    const slot = W / n;
    const bw = Math.max(1.5, slot * 0.62);
    const vmax = Math.max(...candles.map((c) => c.volume));
    let bodies = "";
    let vols = "";
    candles.forEach((c, i) => {
      const cx = i * slot + slot / 2;
      const cls = c.close_cents >= c.open_cents ? "up" : "down";
      const top = y(Math.max(c.open_cents, c.close_cents));
      const bh = Math.max(0.8, Math.abs(y(c.open_cents) - y(c.close_cents)));
      bodies += `<g class="${cls}"><line x1="${cx}" x2="${cx}" y1="${y(c.high_cents)}" y2="${y(c.low_cents)}" stroke="currentColor" vector-effect="non-scaling-stroke"/>
        <rect x="${cx - bw / 2}" y="${top}" width="${bw}" height="${bh}" fill="currentColor"/></g>`;
      const vh = (c.volume / vmax) * (VH - 4);
      vols += `<rect class="${cls}" x="${cx - bw / 2}" y="${VH - vh}" width="${bw}" height="${vh}" fill="currentColor" opacity="0.45"/>`;
    });
    const ma = [];
    candles.forEach((c, i) => {
      if (i < 4) return;
      const s = candles.slice(i - 4, i + 1).reduce((a, k) => a + k.close_cents, 0) / 5;
      ma.push([i * slot + slot / 2, y(s)]);
    });
    const svg = `<svg class="chart-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <line class="grid" x1="0" x2="${W}" y1="${H / 2}" y2="${H / 2}" vector-effect="non-scaling-stroke" stroke-dasharray="3 4"/>
      ${bodies}
      <polyline class="avg" points="${pts(ma)}" fill="none" vector-effect="non-scaling-stroke"/>
    </svg>`;
    const volSvg = `<svg class="chart-vol" viewBox="0 0 ${W} ${VH}" preserveAspectRatio="none" aria-hidden="true">${vols}</svg>`;
    return { svg, volSvg, lo, hi, slot, W, H };
  }

  /** 资产曲线：强调色单线 + 渐隐面积 */
  function area(values, W = 343, H = 120) {
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    const span = hi - lo || 1;
    const x = (i) => (i / (values.length - 1)) * W;
    const y = (v) => 6 + (1 - (v - lo) / span) * (H - 12);
    const line = values.map((v, i) => [x(i), y(v)]);
    const id = "gq" + ++gid;
    const svg = `<svg class="chart-svg accent" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <defs><linearGradient id="${id}" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" stop-color="currentColor" stop-opacity="0.2"/>
        <stop offset="1" stop-color="currentColor" stop-opacity="0"/>
      </linearGradient></defs>
      <polygon points="0,${H} ${pts(line)} ${W},${H}" fill="url(#${id})"/>
      <polyline class="draw" points="${pts(line)}" fill="none" stroke="currentColor" stroke-width="1.8" vector-effect="non-scaling-stroke" stroke-linejoin="round" pathLength="1"/>
    </svg>`;
    return { svg, x, y, W, H, lo, hi };
  }

  /**
   * 十字线交互：在 host（相对定位）上拖动手指/鼠标，回调当前索引；松手回调 null。
   * count 为数据点数量，total 为 x 轴总槽位（分时为 241）。
   */
  function crosshair(host, { count, total = count, slotMode = false, onMove }) {
    const line = document.createElement("div");
    line.className = "crosshair";
    host.appendChild(line);
    const pick = (e) => {
      const r = host.getBoundingClientRect();
      const fx = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
      let i = slotMode ? Math.floor(fx * total) : Math.round(fx * (total - 1));
      i = Math.min(count - 1, Math.max(0, i));
      const px = slotMode ? ((i + 0.5) / total) * r.width : (i / (total - 1)) * r.width;
      line.style.transform = `translateX(${px}px)`;
      line.classList.add("on");
      onMove(i);
    };
    const end = () => {
      line.classList.remove("on");
      onMove(null);
    };
    host.addEventListener("pointerdown", (e) => {
      host.setPointerCapture(e.pointerId);
      pick(e);
    });
    host.addEventListener("pointermove", (e) => {
      if (e.pointerType === "mouse" || host.hasPointerCapture(e.pointerId)) pick(e);
    });
    host.addEventListener("pointerup", end);
    host.addEventListener("pointercancel", end);
    host.addEventListener("pointerleave", (e) => e.pointerType === "mouse" && end());
  }

  SS.chart = { sparkline, intraday, kline, area, crosshair };
})();
