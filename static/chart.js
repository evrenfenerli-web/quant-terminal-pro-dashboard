/* chart.js — Plotly candlestick chart + EMAs + position lines + structure markers
   NOTE: REFRESH_MS is defined in dashboard.js and is not redeclared here. */

const MARKET = document.body.dataset.market;
const SLUG = document.body.dataset.slug;

const EMA_COLORS = { ema9: "#E8A33D", ema21: "#C9C2A8", ema50: "#5B8FBF", ema200: "#8B6FB0" };
const COLOR_BULL = "#4FAE7A";
const COLOR_BEAR = "#D5654F";
const COLOR_ACCENT = "#E8A33D";

let _chartInitialized = false;
let _lastPrice = null;
let _autoFollow = true;
let _userView = null;
let _currentTimeframe = null;
let _plotEventsBound = false;

function captureUserView() {
  const gd = document.getElementById("priceChart");
  if (!gd || !gd.layout) return;
  const xr = gd.layout.xaxis && gd.layout.xaxis.range;
  const yr = gd.layout.yaxis && gd.layout.yaxis.range;
  _userView = {
    x: Array.isArray(xr) ? [...xr] : null,
    y: Array.isArray(yr) ? [...yr] : null,
  };
}

function bindPlotEvents() {
  if (_plotEventsBound) return;
  const gd = document.getElementById("priceChart");
  if (!gd || typeof gd.on !== "function") return;
  gd.on("plotly_relayout", ev => {
    const manual = ev["xaxis.range[0]"] !== undefined || ev["xaxis.range"] ||
                   ev["yaxis.range[0]"] !== undefined || ev["yaxis.range"];
    if (manual) {
      _autoFollow = false;
      captureUserView();
      updateAutoFollowButton();
    }
  });
  _plotEventsBound = true;
}

function updateAutoFollowButton() {
  const btn = document.getElementById("autoFollowBtn");
  const state = document.getElementById("viewState");
  if (btn) {
    btn.textContent = `Auto Follow: ${_autoFollow ? "ON" : "OFF"}`;
    btn.classList.toggle("active", _autoFollow);
  }
  if (state) state.textContent = _autoFollow ? "following latest candle" : "manual zoom preserved";
}

function buildTraces(c) {
  const traces = [
    {
      type: "candlestick",
      x: c.t, open: c.o, high: c.h, low: c.l, close: c.c,
      increasing: { line: { color: COLOR_BULL }, fillcolor: COLOR_BULL },
      decreasing: { line: { color: COLOR_BEAR }, fillcolor: COLOR_BEAR },
      name: "Price",
      showlegend: false,
    },
    { type: "scatter", mode: "lines", x: c.t, y: c.ema9, name: "EMA 9",
      line: { color: EMA_COLORS.ema9, width: 1.3 } },
    { type: "scatter", mode: "lines", x: c.t, y: c.ema21, name: "EMA 21",
      line: { color: EMA_COLORS.ema21, width: 1.1 } },
    { type: "scatter", mode: "lines", x: c.t, y: c.ema50, name: "EMA 50",
      line: { color: EMA_COLORS.ema50, width: 1.1 } },
    { type: "scatter", mode: "lines", x: c.t, y: c.ema200, name: "EMA 200",
      line: { color: EMA_COLORS.ema200, width: 1.3 } },
  ];
  return traces;
}

function buildStructureTrace(markers, timestamps, candles) {
  if (!markers || !markers.length) return null;
  const xs = [], ys = [], symbols = [], colors = [], texts = [];
  markers.forEach(m => {
    const idx = m.idx;
    if (idx < 0 || idx >= timestamps.length) return;
    xs.push(timestamps[idx]);
    const isLong = m.side === "LONG";
    ys.push(isLong ? candles.l[idx] * 0.997 : candles.h[idx] * 1.003);
    symbols.push(isLong ? "triangle-up" : "triangle-down");
    colors.push(isLong ? COLOR_BULL : COLOR_BEAR);
    texts.push(`${m.type} ${m.side} @ ${m.level}`);
  });
  return {
    type: "scatter", mode: "markers", x: xs, y: ys,
    marker: { symbol: symbols, color: colors, size: 9, line: { color: "#0F1115", width: 1 } },
    text: texts, hoverinfo: "text", name: "Structure", showlegend: false,
  };
}

function buildShapesAndAnnotations(position, xRange) {
  if (!position) return { shapes: [], annotations: [] };
  const levels = [
    { key: "entry", label: "ENTRY", color: COLOR_ACCENT, dash: "solid", opacity: 0.9 },
    { key: "sl", label: "SL", color: COLOR_BEAR, dash: "dash", opacity: 0.85 },
    { key: "tp1", label: "TP1", color: COLOR_BULL, dash: "dot", opacity: 0.85 },
    { key: "tp2", label: "TP2", color: COLOR_BULL, dash: "dot", opacity: 0.6 },
    { key: "tp3", label: "TP3", color: COLOR_BULL, dash: "dot", opacity: 0.4 },
  ];
  const shapes = [], annotations = [];
  levels.forEach(l => {
    const y = position[l.key];
    if (y === null || y === undefined) return;
    shapes.push({
      type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: y, y1: y,
      line: { color: l.color, width: 1, dash: l.dash }, opacity: l.opacity,
    });
    annotations.push({
      xref: "paper", x: 1, y, xanchor: "left", yanchor: "middle",
      text: `${l.label} ${y.toFixed(y < 1 ? 6 : y < 100 ? 4 : 2)}`,
      showarrow: false, font: { family: "IBM Plex Mono", size: 10, color: l.color },
      bgcolor: "#0F1115", opacity: 0.95, borderpad: 2,
    });
  });
  return { shapes, annotations };
}

function baseLayout() {
  return {
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { family: "IBM Plex Sans", color: "#8B8F98", size: 11 },
    margin: { l: 50, r: 70, t: 10, b: 34 },
    xaxis: {
      gridcolor: "#23272F", rangeslider: { visible: true, thickness: 0.06, bgcolor: "#0F1115", bordercolor: "#2B303B" },
      showspikes: true, spikemode: "across", spikecolor: "#565B66", spikethickness: 1,
    },
    yaxis: { gridcolor: "#23272F", side: "right", tickfont: { family: "IBM Plex Mono" } },
    legend: { orientation: "h", y: 1.05, font: { size: 10, family: "IBM Plex Mono" }, bgcolor: "transparent" },
    hovermode: "x unified",
    hoverlabel: { bgcolor: "#20242D", bordercolor: "#2B303B", font: { family: "IBM Plex Mono", size: 11 } },
    dragmode: "pan",
    uirevision: "quant-terminal-stable-view",
  };
}

function renderChart(data) {
  const traces = buildTraces(data.candles);
  const structTrace = buildStructureTrace(data.structure_markers, data.candles.t, data.candles);
  if (structTrace) traces.push(structTrace);

  const { shapes, annotations } = buildShapesAndAnnotations(data.position, null);
  const layout = baseLayout();
  layout.shapes = shapes;
  layout.annotations = annotations;
  if (!_autoFollow && _userView) {
    if (_userView.x) {
      layout.xaxis.autorange = false;
      layout.xaxis.range = _userView.x;
    }
    if (_userView.y) {
      layout.yaxis.autorange = false;
      layout.yaxis.range = _userView.y;
    }
  } else {
    layout.xaxis.autorange = true;
    layout.yaxis.autorange = true;
  }

  const config = { displayModeBar: true, displaylogo: false, responsive: true,
    modeBarButtonsToRemove: ["lasso2d", "select2d"] };

  if (!_chartInitialized) {
    Plotly.newPlot("priceChart", traces, layout, config).then(() => { bindPlotEvents(); updateAutoFollowButton(); });
    _chartInitialized = true;
  } else {
    Plotly.react("priceChart", traces, layout, config).then(() => { bindPlotEvents(); if (!_autoFollow) captureUserView(); });
  }
}

function updateStatStrip(data) {
  const priceEl = document.getElementById("statPrice");
  const changeEl = document.getElementById("statChange");
  const regimeEl = document.getElementById("statRegime");
  const adxEl = document.getElementById("statAdx");
  const rsiEl = document.getElementById("statRsi");

  if (_lastPrice !== null && data.last_price !== _lastPrice) {
    flash(priceEl.parentElement, data.last_price > _lastPrice);
  }
  _lastPrice = data.last_price;

  priceEl.textContent = fmtPrice(data.last_price);
  changeEl.textContent = fmtPct(data.last_change_pct);
  changeEl.className = `stat-value mono ${pctClass(data.last_change_pct)}`;
  regimeEl.textContent = data.regime_label;
  regimeEl.style.color = data.regime_color;
  adxEl.textContent = data.adx;
  rsiEl.textContent = data.rsi;

  document.title = `${fmtPrice(data.last_price)} · ${data.symbol} · Quant Terminal`;
}

function renderPositionPanel(position, symbol) {
  const wrap = document.getElementById("positionPanel");
  if (!position) {
    wrap.innerHTML = `<div class="empty-state" style="margin-top:18px;">
      No open position on this symbol — market monitoring only.
    </div>`;
    return;
  }

  const sideClass = position.side === "LONG" ? "side-long" : "side-short";
  const pnlClass = (position.pnl_usd ?? 0) >= 0 ? "up" : "down";

  const tpCell = (label, val, hit) => `
    <div><span class="k">${label}${hit ? " ✓" : ""}</span>
      <span class="v ${hit ? "hit" : ""}" style="${hit ? "" : "color:var(--text-dim);"}">
        ${val !== null && val !== undefined ? fmtPrice(val) : "—"}
      </span>
    </div>`;

  wrap.innerHTML = `
    <div class="pos-panel ${sideClass}">
      <div class="pos-panel__head">
        <span class="pos-panel__title">Open Position · ${position.side}</span>
        <span class="mono ${pnlClass}" style="font-size:16px;font-weight:600;">
          ${position.pnl_usd !== null ? (position.pnl_usd >= 0 ? "+" : "") + position.pnl_usd.toFixed(2) + "$" : "—"}
          <span style="font-size:12px;">(${position.pnl_pct !== null ? fmtPct(position.pnl_pct) : "—"})</span>
        </span>
      </div>
      <div class="pos-grid">
        <div><span class="k">Entry</span><span class="v">${fmtPrice(position.entry)}</span></div>
        <div><span class="k">SL</span><span class="v" style="color:var(--bear);">${fmtPrice(position.sl)}</span></div>
        ${tpCell("TP1", position.tp1, position.tp1_hit)}
        ${tpCell("TP2", position.tp2, position.tp2_hit)}
        ${tpCell("TP3", position.tp3, position.tp3_hit)}
        <div><span class="k">Leverage</span><span class="v">${position.leverage ?? "—"}x</span></div>
        <div><span class="k">Open For</span><span class="v">${position.opened_ago}</span></div>
      </div>
      <div class="snapshot-note">
        Entry-time snapshot (recorded by the bot — not recomputed live):
        regime <strong>${position.regime_at_entry || "—"}</strong>,
        confluence <strong>${position.conf_score_at_entry ?? "—"}</strong>,
        structure <strong>${position.bos_type_at_entry || "—"}</strong>.
        The "Regime" badge above the chart shows the current live regime instead.
      </div>
    </div>`;
}

async function pollChart() {
  try {
    const tf = _currentTimeframe || document.getElementById("timeframeSelect")?.value || "15m";
    const res = await fetch(`/api/chart/${MARKET}/${SLUG}?timeframe=${encodeURIComponent(tf)}`);
    const data = await res.json();
    if (data.status !== "ok") {
      document.getElementById("priceChart").innerHTML =
        `<div class="empty-state">${data.message || "Could not fetch data"}</div>`;
      return;
    }
    renderChart(data);
    updateStatStrip(data);
    renderPositionPanel(data.position, data.symbol);
  } catch (e) {
    console.error("chart poll failed", e);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const tfSelect = document.getElementById("timeframeSelect");
  _currentTimeframe = tfSelect?.value || "15m";

  tfSelect?.addEventListener("change", () => {
    _currentTimeframe = tfSelect.value;
    _autoFollow = true;
    _userView = null;
    updateAutoFollowButton();
    pollChart();
  });

  document.getElementById("autoFollowBtn")?.addEventListener("click", () => {
    _autoFollow = !_autoFollow;
    if (_autoFollow) _userView = null;
    updateAutoFollowButton();
    pollChart();
  });

  document.getElementById("resetViewBtn")?.addEventListener("click", () => {
    _autoFollow = true;
    _userView = null;
    updateAutoFollowButton();
    Plotly.relayout("priceChart", {"xaxis.autorange": true, "yaxis.autorange": true});
  });

  document.getElementById("fullscreenBtn")?.addEventListener("click", async () => {
    const panel = document.getElementById("chartPanel");
    if (!document.fullscreenElement) await panel?.requestFullscreen();
    else await document.exitFullscreen();
    setTimeout(() => Plotly.Plots.resize("priceChart"), 100);
  });

  updateAutoFollowButton();
  pollChart();
  setInterval(pollChart, REFRESH_MS);
});
