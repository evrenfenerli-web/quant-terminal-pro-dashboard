const EXIT_REFRESH_MS = Math.max(10, parseInt(document.body.dataset.refresh || "30", 10)) * 1000;
const EXIT_COLORS = {bull:"#4FAE7A", bear:"#D5654F", accent:"#E8A33D", blue:"#5B8DB8", dim:"#8B8F98", grid:"#23272F"};

function eNum(v, digits=2) { return v === null || v === undefined ? "N/A" : Number(v).toFixed(digits); }
function ePct(v) { return v === null || v === undefined ? "N/A" : `${Number(v).toFixed(1)}%`; }
function eEsc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function ePlot(id, traces, layout={}) {
  const base = {
    paper_bgcolor:"transparent", plot_bgcolor:"transparent",
    font:{color:EXIT_COLORS.dim,family:"IBM Plex Mono",size:10},
    margin:{l:50,r:18,t:12,b:42}, hovermode:"closest",
    xaxis:{gridcolor:EXIT_COLORS.grid}, yaxis:{gridcolor:EXIT_COLORS.grid},
    showlegend:false, uirevision:`exit-${id}`,
  };
  Plotly.react(id, traces, {...base,...layout}, {displaylogo:false,responsive:true,modeBarButtonsToRemove:["lasso2d","select2d"]});
}
function eTable(obj, columns) {
  const rows = Object.entries(obj || {});
  if (!rows.length) return '<div class="empty-state">No exit data yet.</div>';
  return `<div class="table-scroll"><table class="postable"><thead><tr>${columns.map(c=>`<th>${c.label}</th>`).join("")}</tr></thead>
  <tbody>${rows.map(([key,row])=>`<tr>${columns.map(c=>`<td>${c.render?c.render(key,row):(c.key==="_key"?eEsc(key):eEsc(row[c.key]??"—"))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function renderExitKpis(d) {
  const s = d.summary;
  const items = [
    ["Trades",s.trades],["Avg Exit",s.avg_exit_r===null?"N/A":`${eNum(s.avg_exit_r,3)}R`],
    ["Avg MFE",s.avg_mfe_r===null?"N/A":`${eNum(s.avg_mfe_r,3)}R`],
    ["Avg MAE",s.avg_mae_r===null?"N/A":`${eNum(s.avg_mae_r,3)}R`],
    ["Total Lost",`${eNum(s.total_lost_r,3)}R`],
    ["Capture",s.avg_capture_ratio===null?"N/A":ePct(s.avg_capture_ratio*100)],
    ["Exit Quality",s.exit_quality_score===null?"N/A":`${eNum(s.exit_quality_score,1)}/100`],
    ["TP3 Hit",ePct(d.tp_funnel.tp3.rate)],
  ];
  document.getElementById("exitKpis").innerHTML=items.map(([k,v])=>`<div class="kpi"><span>${k}</span><strong>${v}</strong></div>`).join("");
}
function renderFunnel(f) {
  const stages=[
    ["Trades",f.total,100],["TP1",f.tp1.count,f.tp1.rate],["TP2",f.tp2.count,f.tp2.rate],["TP3",f.tp3.count,f.tp3.rate],
  ];
  document.getElementById("tpFunnel").innerHTML=stages.map(([name,count,rate],i)=>`
    <div class="funnel-stage">
      <span>${name}</span><strong>${count}</strong><small>${ePct(rate)} of all${i>1?` · ${ePct(i===2?f.tp2.from_previous:f.tp3.from_previous)} conversion`:""}</small>
      <i style="width:${Math.max(2,rate)}%"></i>
    </div>`).join("");
}
function renderExitReport(d) {
  renderExitKpis(d); renderFunnel(d.tp_funnel);
  const trades=d.trades||[];
  ePlot("mfeScatter",[{
    type:"scatter",mode:"markers",x:trades.map(t=>t.mfe_r),y:trades.map(t=>t.exit_r),
    text:trades.map(t=>`${t.symbol||"—"} · ${t.exit_family}`),
    marker:{color:trades.map(t=>t.exit_quality_score),colorscale:[[0,EXIT_COLORS.bear],[.5,EXIT_COLORS.accent],[1,EXIT_COLORS.bull]],cmin:0,cmax:100,size:8,showscale:true,colorbar:{title:"Quality"}},
  }],{xaxis:{gridcolor:EXIT_COLORS.grid,title:"MFE (R)"},yaxis:{gridcolor:EXIT_COLORS.grid,title:"Exit (R)"}});

  const reasons=Object.entries(d.by_reason||{});
  ePlot("lostByReason",[{type:"bar",x:reasons.map(x=>x[0]),y:reasons.map(x=>x[1].total_lost_r),marker:{color:EXIT_COLORS.bear}}],
    {yaxis:{gridcolor:EXIT_COLORS.grid,title:"Total Lost R"}});
  ePlot("captureDistribution",[{type:"histogram",x:trades.filter(t=>t.capture_ratio!==null).map(t=>t.capture_ratio*100),marker:{color:EXIT_COLORS.bull},nbinsx:20}],
    {xaxis:{gridcolor:EXIT_COLORS.grid,title:"Capture %"},yaxis:{gridcolor:EXIT_COLORS.grid,title:"Trades"}});

  const dist=d.distribution;
  document.getElementById("excursionDistribution").innerHTML=`
    <div class="distribution-grid">
      ${["mfe_r","mae_r","capture_ratio"].map(k=>`<div class="distribution-card"><span>${k.replace("_"," ").toUpperCase()}</span>
        <strong>${eNum(dist[k].median,k==="capture_ratio"?4:3)}</strong>
        <small>P25 ${eNum(dist[k].p25,k==="capture_ratio"?4:3)} · P75 ${eNum(dist[k].p75,k==="capture_ratio"?4:3)}</small></div>`).join("")}
    </div>`;

  const cols=[
    {label:"Exit",key:"_key"},{label:"N",key:"count"},
    {label:"WR",render:(k,r)=>ePct(r.win_rate)},{label:"Exit R",render:(k,r)=>eNum(r.avg_exit_r,3)},
    {label:"MFE",render:(k,r)=>eNum(r.avg_mfe_r,3)},{label:"MAE",render:(k,r)=>eNum(r.avg_mae_r,3)},
    {label:"Lost R",render:(k,r)=>eNum(r.avg_lost_r,3)},{label:"Capture",render:(k,r)=>r.avg_capture_ratio===null?"N/A":ePct(r.avg_capture_ratio*100)},
    {label:"Quality",render:(k,r)=>`${eNum(r.exit_quality_score,1)}/100`},{label:"TP3",render:(k,r)=>ePct(r.tp3_rate)},
  ];
  document.getElementById("exitReasonTable").innerHTML=eTable(d.by_reason,cols);
  document.getElementById("exitSubreasonTable").innerHTML=eTable(d.by_subreason,cols);

  const shadowCols=[
    {label:"Checkpoint",key:"_key"},{label:"N",key:"count"},
    {label:"Avg Move",render:(k,r)=>eNum(r.avg_move,4)},
    {label:"Continued",render:(k,r)=>ePct(r.continued_pct)},{label:"Reversed",render:(k,r)=>ePct(r.reversed_pct)},
  ];
  document.getElementById("shadowByBars").innerHTML=eTable(d.shadow_exit.by_bars,shadowCols);
  document.getElementById("shadowByReason").innerHTML=eTable(d.shadow_exit.by_reason,shadowCols);

  const rows=trades.slice().reverse();
  document.getElementById("exitTradeExplorer").innerHTML=rows.length?`<div class="table-scroll"><table class="postable"><thead><tr>
    <th>Symbol</th><th>Exit</th><th>Subreason</th><th>Exit R</th><th>MFE</th><th>MAE</th><th>Lost</th><th>Capture</th><th>Quality</th><th>TP</th>
  </tr></thead><tbody>${rows.map(t=>`<tr>
    <td>${eEsc(t.symbol||"—")}</td><td>${eEsc(t.exit_family)}</td><td>${eEsc(t.exit_subreason)}</td>
    <td>${eNum(t.exit_r,3)}</td><td>${eNum(t.mfe_r,3)}</td><td>${eNum(t.mae_r,3)}</td><td>${eNum(t.lost_r,3)}</td>
    <td>${t.capture_ratio===null?"N/A":ePct(t.capture_ratio*100)}</td><td>${eNum(t.exit_quality_score,1)}</td>
    <td>${t.tp3_hit?"TP3":t.tp2_hit?"TP2":t.tp1_hit?"TP1":"—"}</td>
  </tr>`).join("")}</tbody></table></div>`:'<div class="empty-state">No trades yet.</div>';
  document.getElementById("formulaNote").textContent=`Metric formulas · Lost R: ${d.formula.lost_r} · Capture: ${d.formula.capture_ratio} · Quality: ${d.formula.exit_quality_score}`;
}
async function loadExitReport() {
  const bot=document.getElementById("exitBot").value;
  const sample=document.getElementById("exitSample").value;
  const qs=sample?`?last_n=${encodeURIComponent(sample)}`:"";
  try {
    const res=await fetch(`/api/exit-report/${encodeURIComponent(bot)}${qs}`);
    const payload=await res.json();
    if(payload.status!=="ok") throw new Error(payload.message||"Exit report unavailable");
    renderExitReport(payload.data);
    document.getElementById("exitSync").textContent=new Date().toLocaleTimeString([],{hour12:false});
    document.getElementById("exitCsvExport").href=`/api/exit-report/${encodeURIComponent(bot)}/export.csv`;
  } catch(err) {
    document.getElementById("exitKpis").innerHTML=`<div class="empty-state">Exit report error: ${eEsc(err.message)}</div>`;
  }
}
document.addEventListener("DOMContentLoaded",()=>{
  document.getElementById("refreshExitReport").addEventListener("click",loadExitReport);
  document.getElementById("exitBot").addEventListener("change",loadExitReport);
  document.getElementById("exitSample").addEventListener("change",loadExitReport);
  loadExitReport(); setInterval(loadExitReport,EXIT_REFRESH_MS);
});
