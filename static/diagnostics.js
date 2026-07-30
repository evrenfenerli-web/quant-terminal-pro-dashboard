const DIAG_REFRESH_MS=Math.max(15,parseInt(document.body.dataset.refresh||"60",10))*1000;
const DC={bull:"#4FAE7A",bear:"#D5654F",accent:"#E8A33D",blue:"#5B8DB8",dim:"#8B8F98",grid:"#23272F"};
function dNum(v,n=2){return v===null||v===undefined?"N/A":Number(v).toFixed(n);}
function dPct(v){return v===null||v===undefined?"N/A":`${Number(v).toFixed(1)}%`;}
function dEsc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function dPlot(id,traces,layout={}){
  const base={paper_bgcolor:"transparent",plot_bgcolor:"transparent",font:{color:DC.dim,family:"IBM Plex Mono",size:10},margin:{l:48,r:18,t:12,b:42},
    xaxis:{gridcolor:DC.grid},yaxis:{gridcolor:DC.grid},showlegend:false};
  Plotly.react(id,traces,{...base,...layout},{displaylogo:false,responsive:true,modeBarButtonsToRemove:["lasso2d","select2d"]});
}
const perfColumns=["count","win_rate","profit_factor","avg_r","avg_mfe_r","avg_mae_r","avg_capture_ratio","avg_bars_held","tp3_rate"];
function perfTable(obj,keyLabel="Name"){
  const rows=Object.entries(obj||{});if(!rows.length)return'<div class="empty-state">No data.</div>';
  return `<div class="table-scroll"><table class="postable"><thead><tr><th>${keyLabel}</th>${perfColumns.map(k=>`<th>${k.replaceAll("_"," ")}</th>`).join("")}</tr></thead>
  <tbody>${rows.map(([key,v])=>`<tr><td>${dEsc(key)}</td>${perfColumns.map(k=>`<td>${k.includes("rate")||k==="win_rate"?dPct(v[k]):dNum(v[k],k==="count"?0:k==="profit_factor"?2:3)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function simpleList(rows,empty="None detected."){
  return rows&&rows.length?`<div class="diag-list">${rows.map(r=>`<div>${Object.entries(r).map(([k,v])=>`<span><small>${dEsc(k)}</small>${dEsc(Array.isArray(v)?v.join(", "):v)}</span>`).join("")}</div>`).join("")}</div>`:`<div class="ok-state">${empty}</div>`;
}
function renderDiagnostics(d){
  const s=d.summary;
  document.getElementById("diagKpis").innerHTML=[
    ["Trades",s.trades],["Coins",s.coins],["Regime Violations",s.regime_violations],["Counter Trend",s.counter_trend_violations],
    ["Hedge Conflicts",s.position_side_conflicts],["BTC Rejects",s.btc_rejections],["Missing Fields",s.missing_fields],["Config",s.config_status],
  ].map(([k,v])=>`<div class="kpi ${v==="FAIL"||Number(v)>0&&["Regime Violations","Counter Trend","Missing Fields"].includes(k)?"kpi-alert":""}"><span>${k}</span><strong>${v}</strong></div>`).join("");
  document.getElementById("coinDiagnostics").innerHTML=perfTable(d.coin_analytics,"Symbol");
  const bars=Object.entries(d.time_analytics.bars_held||{});
  dPlot("barsHeldChart",[{type:"bar",x:bars.map(x=>x[0]),y:bars.map(x=>x[1].avg_r),marker:{color:bars.map(x=>x[1].avg_r>=0?DC.bull:DC.bear)},text:bars.map(x=>`N=${x[1].count}`)}],
    {yaxis:{gridcolor:DC.grid,title:"Avg R"}});
  const hours=Object.entries(d.time_analytics.hour_utc||{});
  dPlot("hourChart",[{type:"bar",x:hours.map(x=>x[0]),y:hours.map(x=>x[1].avg_r),marker:{color:DC.blue},text:hours.map(x=>`N=${x[1].count}`)}],
    {yaxis:{gridcolor:DC.grid,title:"Avg R"}});
  document.getElementById("regimeDiagnostics").innerHTML=`${perfTable(d.regime_debug.stats,"Regime")}
    <div class="diag-split"><div><h3>Forbidden regime entries</h3>${simpleList(d.regime_debug.forbidden_entries)}</div>
    <div><h3>Counter-trend entries</h3>${simpleList(d.regime_debug.counter_trend_entries)}</div></div>`;
  const btc=d.btc_filter_debug;
  document.getElementById("btcDiagnostics").innerHTML=`<div class="diag-metric"><span>Field coverage</span><strong>${dPct(btc.trade_field_coverage_pct)}</strong></div>
    <div class="diag-metric"><span>Rejected</span><strong>${btc.rejected}</strong></div>
    ${simpleList(Object.entries(btc.by_reason||{}).map(([reason,count])=>({reason,count})),"No BTC filter rejections.")}`;
  const p=d.exit_trigger_priority;
  document.getElementById("priorityDiagnostics").innerHTML=`<div class="diag-metric"><span>Candidate coverage</span><strong>${dPct(p.coverage_pct)}</strong></div>
    <div class="diag-metric"><span>Multiple triggers</span><strong>${p.multiple_trigger_trades}</strong></div>${simpleList(p.recent_multiple,"No multi-trigger records.")}`;
  const quality=Object.entries(d.data_quality||{});
  document.getElementById("dataQuality").innerHTML=`<div class="quality-grid">${quality.map(([field,v])=>`<div class="${v.coverage_pct<100?"quality-missing":""}">
    <span>${dEsc(field)}</span><strong>${dPct(v.coverage_pct)}</strong><i><b style="width:${v.coverage_pct}%"></b></i><small>${v.missing} missing</small></div>`).join("")}</div>`;
  const sc=d.symbol_config;
  document.getElementById("symbolConfig").innerHTML=`<div class="diag-metric"><span>Configured</span><strong>${sc.configured.length}</strong></div>
    <div class="diag-metric"><span>Observed</span><strong>${sc.observed.length}</strong></div>
    ${simpleList([
      ...(sc.configured_not_observed.length?[{type:"Configured not observed",symbols:sc.configured_not_observed}]:[]),
      ...(sc.observed_not_configured.length?[{type:"Observed not configured",symbols:sc.observed_not_configured}]:[]),
      ...(sc.duplicates.length?[{type:"Duplicates",symbols:sc.duplicates}]:[]),
      ...(sc.simultaneous_long_short.length?[{type:"Simultaneous LONG + SHORT",symbols:sc.simultaneous_long_short}]:[]),
    ],"Symbol config is aligned.")}`;
  const ca=d.config_audit;
  document.getElementById("configAudit").innerHTML=`<div class="config-status ${ca.status}">${ca.status}</div>
    <p class="diag-caption">Allowed: ${ca.allowed_entry_regimes.join(", ")}</p>${simpleList(ca.issues,"Config audit passed.")}`;
  document.getElementById("sourceHealth").innerHTML=`<div class="source-health">${d.source_health.map(x=>`<div><span>${dEsc(x.name)}</span>
    <strong class="${x.status}">${x.status}</strong><small>${x.connected?`${x.size_bytes} bytes · age ${x.age_seconds}s`:"not connected"}</small></div>`).join("")}</div>`;
}
async function loadDiagnostics(){
  const bot=document.getElementById("diagBot").value,sample=document.getElementById("diagSample").value;
  try{const r=await fetch(`/api/diagnostics/${encodeURIComponent(bot)}${sample?`?last_n=${encodeURIComponent(sample)}`:""}`),p=await r.json();
    if(p.status!=="ok")throw new Error(p.message||"Diagnostics unavailable");renderDiagnostics(p.data);
    document.getElementById("diagSync").textContent=new Date().toLocaleTimeString([],{hour12:false});
  }catch(e){document.getElementById("diagKpis").innerHTML=`<div class="empty-state">Diagnostics error: ${dEsc(e.message)}</div>`;}
}
document.addEventListener("DOMContentLoaded",()=>{document.getElementById("refreshDiagnostics").addEventListener("click",loadDiagnostics);
  document.getElementById("diagBot").addEventListener("change",loadDiagnostics);document.getElementById("diagSample").addEventListener("change",loadDiagnostics);
  loadDiagnostics();setInterval(loadDiagnostics,DIAG_REFRESH_MS);});
