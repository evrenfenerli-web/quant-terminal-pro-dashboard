const REFRESH_MS_ANALYTICS = Math.max(10, parseInt(document.body.dataset.refresh || "30", 10)) * 1000;
const COLORS = { bull: "#4FAE7A", bear: "#D5654F", accent: "#E8A33D", dim: "#8B8F98", grid: "#23272F" };

function val(v, digits=2) { return v === null || v === undefined ? "N/A" : Number(v).toFixed(digits); }
function pf(v) { return v === null || v === undefined ? "N/A" : Number(v).toFixed(2); }
function pct(v) { return v === null || v === undefined ? "N/A" : `${Number(v).toFixed(1)}%`; }

function tableFromObject(obj, columns) {
  const rows = Object.entries(obj || {});
  if (!rows.length) return '<div class="empty-state">No data yet.</div>';
  return `<div class="table-scroll"><table class="postable"><thead><tr>${columns.map(c=>`<th>${c.label}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(([key,d])=>`<tr>${columns.map(c=>`<td class="${c.className||""}">${c.render ? c.render(key,d) : (c.key === "_key" ? key : d[c.key] ?? "—")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function plot(id, traces, layout={}) {
  const base = {
    paper_bgcolor: "transparent", plot_bgcolor: "transparent",
    font: { color: COLORS.dim, family: "IBM Plex Mono", size: 10 },
    margin: {l:48,r:18,t:12,b:42}, hovermode: "x unified",
    xaxis: {gridcolor: COLORS.grid}, yaxis: {gridcolor: COLORS.grid},
    showlegend: false, uirevision: `analytics-${id}`,
  };
  Plotly.react(id, traces, {...base, ...layout}, {displaylogo:false, responsive:true, modeBarButtonsToRemove:["lasso2d","select2d"]});
}

function renderKpis(d) {
  const items = [
    ["Trades", d.total_trades],
    ["Net R", val(d.equity.net_r, 3)],
    ["Max DD", `${val(d.equity.max_drawdown_r, 3)}R`],
    ["Avg Lost", d.opportunity_lost.avg_lost_r === null ? "N/A" : `${val(d.opportunity_lost.avg_lost_r,3)}R`],
    ["Capture", d.capture_ratio.avg === null ? "N/A" : pct(d.capture_ratio.avg*100)],
    ["Counter Share", pct(d.counter_trend.share_pct)],
    ["Rejected", d.rejected.total],
    ["Near Exits", d.near_exit.stats.count || 0],
  ];
  document.getElementById("kpiGrid").innerHTML = items.map(([k,v]) => `<div class="kpi"><span>${k}</span><strong>${v}</strong></div>`).join("");
}

function renderAnalytics(d) {
  renderKpis(d);
  const curve = d.equity.curve || [];
  plot("equityChart", [{type:"scatter",mode:"lines",x:curve.map(x=>x.x),y:curve.map(x=>x.equity_r),line:{color:COLORS.accent,width:2}}], {yaxis:{gridcolor:COLORS.grid,title:"R"}});
  plot("drawdownChart", [{type:"scatter",mode:"lines",fill:"tozeroy",x:curve.map(x=>x.x),y:curve.map(x=>x.drawdown_r),line:{color:COLORS.bear,width:1.5}}], {yaxis:{gridcolor:COLORS.grid,title:"R"}});

  const perfCols = [
    {label:"Name",key:"_key",className:"mono"},
    {label:"Trades",key:"count"},
    {label:"WR",render:(k,d)=>pct(d.win_rate)},
    {label:"PF",render:(k,d)=>pf(d.profit_factor)},
    {label:"Avg R",render:(k,d)=>val(d.avg_r,3)},
  ];
  document.getElementById("regimeTable").innerHTML = tableFromObject(d.regime, perfCols);
  document.getElementById("coinTable").innerHTML = tableFromObject(d.coin, perfCols);

  const exitCols = [
    {label:"Exit",key:"_key"},
    {label:"N",key:"count"},
    {label:"WR",render:(k,d)=>pct(d.win_rate)},
    {label:"Exit R",render:(k,d)=>val(d.avg_exit_r,3)},
    {label:"Lost R",render:(k,d)=>val(d.avg_lost_r,3)},
    {label:"Capture",render:(k,d)=>d.avg_capture_ratio===null?"N/A":pct(d.avg_capture_ratio*100)},
  ];
  document.getElementById("exitTable").innerHTML = tableFromObject(d.exit, exitCols);
  document.getElementById("smartExitTable").innerHTML = tableFromObject(d.smart_exit, exitCols);

  const exits = Object.entries(d.exit || {}).sort((a,b)=>b[1].avg_lost_r-a[1].avg_lost_r);
  plot("lostChart", [{type:"bar",x:exits.map(x=>x[0]),y:exits.map(x=>x[1].avg_lost_r),marker:{color:COLORS.bear}}], {yaxis:{gridcolor:COLORS.grid,title:"Lost R"}});
  plot("captureChart", [{type:"bar",x:exits.map(x=>x[0]),y:exits.map(x=>x[1].avg_capture_ratio===null?0:x[1].avg_capture_ratio*100),marker:{color:COLORS.bull}}], {yaxis:{gridcolor:COLORS.grid,title:"%"}});

  document.getElementById("counterPanel").innerHTML = `
    <div class="compare-grid">
      <div class="compare-card"><span>Counter</span><strong>${d.counter_trend.counter.count}</strong><small>WR ${pct(d.counter_trend.counter.win_rate)} · PF ${pf(d.counter_trend.counter.profit_factor)} · Avg ${val(d.counter_trend.counter.avg_r,3)}R</small></div>
      <div class="compare-card"><span>Aligned / Other</span><strong>${d.counter_trend.aligned.count}</strong><small>WR ${pct(d.counter_trend.aligned.win_rate)} · PF ${pf(d.counter_trend.aligned.profit_factor)} · Avg ${val(d.counter_trend.aligned.avg_r,3)}R</small></div>
    </div>`;

  const rejected = Object.entries(d.rejected.by_reason || {}).slice(0,15);
  plot("rejectedChart", [{type:"bar",orientation:"h",y:rejected.map(x=>x[0]).reverse(),x:rejected.map(x=>x[1]).reverse(),marker:{color:COLORS.accent}}], {margin:{l:145,r:18,t:12,b:35},xaxis:{gridcolor:COLORS.grid,title:"Count"}});

  const cp = d.near_exit.checkpoints || {};
  document.getElementById("nearExitPanel").innerHTML = `
    <div class="compare-grid">
      <div class="compare-card"><span>Near exits</span><strong>${d.near_exit.stats.count || 0}</strong><small>Avg exit ${val(d.near_exit.stats.avg_exit_r,3)}R · Lost ${val(d.near_exit.stats.avg_lost_r,3)}R</small></div>
      ${Object.entries(cp).map(([bars,s])=>`<div class="compare-card"><span>${bars} bars later</span><strong>${pct(s.continued_pct)}</strong><small>continued favorably · avg move ${val(s.avg_move_pct,3)}%</small></div>`).join("")}
    </div>`;

  const tradeRows = (d.trades || []).slice().reverse();
  document.getElementById("tradeExplorer").innerHTML = tradeRows.length ? `<div class="table-scroll"><table class="postable"><thead><tr>
    <th>Closed</th><th>Symbol</th><th>Side</th><th>Regime</th><th>Exit</th><th>Exit R</th><th>MFE</th><th>MAE</th><th>Lost R</th><th>Capture</th>
  </tr></thead><tbody>${tradeRows.map(t=>`<tr>
    <td class="dim">${t.closed_at ? new Date(t.closed_at*1000).toLocaleString() : "—"}</td>
    <td>${t.symbol||"—"}</td><td class="${t.signal==="LONG"?"up":"down"}">${t.signal||"—"}</td>
    <td>${t.regime||"—"}</td><td>${t.exit_reason||"—"}</td><td>${val(t.exit_r,3)}</td>
    <td>${val(t.mfe_r,3)}</td><td>${val(t.mae_r,3)}</td><td>${val(t.lost_r,3)}</td>
    <td>${t.capture_ratio===null||t.capture_ratio===undefined?"N/A":pct(t.capture_ratio*100)}</td>
  </tr>`).join("")}</tbody></table></div>` : '<div class="empty-state">No trades yet.</div>';
}

async function loadAnalytics() {
  const bot = document.getElementById("analyticsBot").value;
  const sample = document.getElementById("analyticsSample").value;
  const qs = sample ? `?last_n=${encodeURIComponent(sample)}` : "";
  try {
    const res = await fetch(`/api/analytics/${bot}${qs}`);
    const payload = await res.json();
    if (payload.status !== "ok") throw new Error(payload.message || "Analytics unavailable");
    renderAnalytics(payload.data);
    document.getElementById("analyticsSync").textContent = new Date().toLocaleTimeString([], {hour12:false});
    document.getElementById("csvExport").href = `/api/analytics/${bot}/export.csv`;
    document.getElementById("jsonExport").href = `/api/analytics/${bot}/export.json`;
  } catch (err) {
    console.error(err);
    document.getElementById("kpiGrid").innerHTML = `<div class="empty-state">Analytics error: ${err.message}</div>`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("refreshAnalytics").addEventListener("click", loadAnalytics);
  document.getElementById("analyticsBot").addEventListener("change", loadAnalytics);
  document.getElementById("analyticsSample").addEventListener("change", loadAnalytics);
  loadAnalytics();
  setInterval(loadAnalytics, REFRESH_MS_ANALYTICS);
});