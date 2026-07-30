const FUNDING_REFRESH_MS=Math.max(10,parseInt(document.body.dataset.refresh||"30",10))*1000;
const FC={bull:"#4FAE7A",bear:"#D5654F",accent:"#E8A33D",blue:"#5B8DB8",dim:"#8B8F98",grid:"#23272F"};
function fNum(v,d=4){return v===null||v===undefined?"N/A":Number(v).toFixed(d);}
function fPct(v){return v===null||v===undefined?"N/A":`${(Number(v)*100).toFixed(4)}%`;}
function fEsc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function fPlot(id,traces,layout={}){
  const base={paper_bgcolor:"transparent",plot_bgcolor:"transparent",font:{color:FC.dim,family:"IBM Plex Mono",size:10},
    margin:{l:55,r:18,t:12,b:42},xaxis:{gridcolor:FC.grid},yaxis:{gridcolor:FC.grid},showlegend:true,legend:{orientation:"h"}};
  Plotly.react(id,traces,{...base,...layout},{displaylogo:false,responsive:true,modeBarButtonsToRemove:["lasso2d","select2d"]});
}
function renderFunding(d){
  const s=d.summary;
  const items=[["Symbols",s.symbols],["Normal",s.normal],["Elevated",s.elevated],["Extreme",s.extreme],
    ["Samples",s.history_samples],["Funding Cost",`$${fNum(s.total_funding_cost_usd,2)}`],
    ["Avg Cost",s.avg_funding_cost_usd===null?"N/A":`$${fNum(s.avg_funding_cost_usd,4)}`],["Mode",d.enabled?"CRYPTO":"DISABLED"]];
  document.getElementById("fundingKpis").innerHTML=items.map(([k,v])=>`<div class="kpi"><span>${k}</span><strong>${v}</strong></div>`).join("");
  document.getElementById("fundingMethod").innerHTML=`Baselines <strong>${d.method.baseline_windows.join(" → ")}</strong> · Elevated <strong>|Z| ≥ ${d.method.elevated_z}</strong> · Extreme <strong>|Z| ≥ ${d.method.extreme_z}</strong> · Current sample excluded from baseline`;

  const current=Object.values(d.current||{});
  document.getElementById("fundingMap").innerHTML=current.length?current.map(x=>`
    <div class="funding-tile ${x.funding_class}">
      <div><strong>${fEsc(x.symbol)}</strong><span>${fEsc(x.funding_class)}</span></div>
      <b>${fPct(x.current_funding)}</b><small>Z ${fNum(x.z_score,2)} · ${fEsc(x.crowding)} · N=${x.baseline_window}</small>
    </div>`).join(""):'<div class="empty-state">Connect funding_analytics_file to display funding data.</div>';

  const grouped={};
  (d.timeline||[]).forEach(p=>(grouped[p.symbol]??=[]).push(p));
  fPlot("fundingTimeline",Object.entries(grouped).map(([symbol,rows],i)=>({
    type:"scatter",mode:"lines",name:symbol,x:rows.map(r=>r.ts?new Date(Number(r.ts)*1000):null),y:rows.map(r=>r.z_score),
    line:{width:1.6,color:[FC.accent,FC.blue,FC.bull,FC.bear,"#A078C2","#C8B94B","#6BB7B2"][i%7]},
  })),{yaxis:{gridcolor:FC.grid,title:"Z-score",range:[-4,4]},hovermode:"x unified"});
  fPlot("fundingClasses",[{type:"bar",x:["NORMAL","ELEVATED","EXTREME"],y:[s.normal,s.elevated,s.extreme],marker:{color:[FC.bull,FC.accent,FC.bear]}}],
    {showlegend:false,yaxis:{gridcolor:FC.grid,title:"Symbols"}});

  const costs=Object.entries(d.cost_by_symbol||{});
  document.getElementById("fundingCosts").innerHTML=costs.length?`<div class="table-scroll"><table class="postable"><thead><tr><th>Symbol</th><th>Trades</th><th>Total USD</th><th>Avg USD</th></tr></thead>
    <tbody>${costs.map(([k,v])=>`<tr><td>${fEsc(k)}</td><td>${v.trades}</td><td>${fNum(v.total_cost_usd,4)}</td><td>${fNum(v.avg_cost_usd,4)}</td></tr>`).join("")}</tbody></table></div>`:'<div class="empty-state">No funding cost fields in trade analytics yet.</div>';

  document.getElementById("fundingTable").innerHTML=current.length?`<div class="table-scroll"><table class="postable"><thead><tr>
    <th>Symbol</th><th>Rate</th><th>Mean</th><th>Std</th><th>Z</th><th>Class</th><th>Crowding</th><th>Window</th><th>Samples</th>
    </tr></thead><tbody>${current.sort((a,b)=>Math.abs(b.z_score)-Math.abs(a.z_score)).map(x=>`<tr>
    <td>${fEsc(x.symbol)}</td><td>${fPct(x.current_funding)}</td><td>${fPct(x.baseline_mean)}</td><td>${fPct(x.baseline_std)}</td>
    <td>${fNum(x.z_score,2)}</td><td><span class="funding-badge ${x.funding_class}">${fEsc(x.funding_class)}</span></td>
    <td>${fEsc(x.crowding)}</td><td>${x.baseline_window}</td><td>${x.sample_count}</td></tr>`).join("")}</tbody></table></div>`:'<div class="empty-state">No current funding snapshot.</div>';
  const missing=d.missing_baseline_symbols||[];
  document.getElementById("missingBaselines").innerHTML=missing.length?`<div class="missing-symbols">${missing.map(x=>`<span>${fEsc(x)}</span>`).join("")}</div>`:'<div class="ok-state">All configured funding baselines are connected.</div>';
}
async function loadFunding(){
  const bot=document.getElementById("fundingBot").value,sample=document.getElementById("fundingSample").value;
  try{
    const res=await fetch(`/api/funding/${encodeURIComponent(bot)}${sample?`?last_n=${encodeURIComponent(sample)}`:""}`);
    const payload=await res.json();if(payload.status!=="ok")throw new Error(payload.message||"Funding unavailable");
    renderFunding(payload.data);document.getElementById("fundingSync").textContent=new Date().toLocaleTimeString([],{hour12:false});
    document.getElementById("fundingCsvExport").href=`/api/funding/${encodeURIComponent(bot)}/export.csv`;
  }catch(err){document.getElementById("fundingKpis").innerHTML=`<div class="empty-state">Funding error: ${fEsc(err.message)}</div>`;}
}
document.addEventListener("DOMContentLoaded",()=>{
  document.getElementById("refreshFunding").addEventListener("click",loadFunding);
  document.getElementById("fundingBot").addEventListener("change",loadFunding);
  document.getElementById("fundingSample").addEventListener("change",loadFunding);
  loadFunding();setInterval(loadFunding,FUNDING_REFRESH_MS);
});
