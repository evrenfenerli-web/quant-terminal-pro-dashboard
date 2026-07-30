const WS_REFRESH_MS = Math.max(5, parseInt(document.body.dataset.refresh || "15", 10)) * 1000;
const MARKETS = window.QUANT_MARKETS || [];
let marketItems = [];
let activeWorkspaceId = null;
let workspaceState = null;
let plotInitialized = new Set();
let syncedCharts = true;

const defaultSymbols = MARKETS.flatMap(m => m.symbols.map(s => ({market:m.key, symbol:s.symbol, slug:s.slug}))).slice(0, 8);

function workspaceDefaults() {
  return {
    version: 1,
    active: "default",
    workspaces: {
      default: {
        name: "Default",
        layout: parseInt(document.body.dataset.defaultLayout || "4", 10),
        timeframe: "15m",
        charts: defaultSymbols.slice(0, 4),
      }
    }
  };
}

function loadWorkspaceState() {
  try { return JSON.parse(localStorage.getItem("quantWorkspaces")) || workspaceDefaults(); }
  catch { return workspaceDefaults(); }
}
function saveWorkspaceState() {
  localStorage.setItem("quantWorkspaces", JSON.stringify(workspaceState));
}
function currentWorkspace() { return workspaceState.workspaces[activeWorkspaceId]; }
function esc(v) { return String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function fmtPrice(v) {
  const n = Number(v); if (!Number.isFinite(n)) return "—";
  return Math.abs(n)<1?n.toFixed(6):Math.abs(n)<100?n.toFixed(4):n.toLocaleString("en-US",{maximumFractionDigits:2});
}
function fmtPct(v) { const n=Number(v); return Number.isFinite(n)?`${n>=0?"+":""}${n.toFixed(2)}%`:"—"; }

function renderWorkspaceTabs() {
  const wrap = document.getElementById("workspaceTabs");
  wrap.innerHTML = Object.entries(workspaceState.workspaces).map(([id,w]) =>
    `<button class="workspace-tab ${id===activeWorkspaceId?"active":""}" data-id="${id}">${esc(w.name)}</button>`
  ).join("");
  wrap.querySelectorAll(".workspace-tab").forEach(btn => btn.addEventListener("click", () => {
    activeWorkspaceId = btn.dataset.id;
    workspaceState.active = activeWorkspaceId;
    saveWorkspaceState();
    applyWorkspace();
  }));
}

function normalizeCharts(ws) {
  const layout = Math.max(1, Math.min(8, Number(ws.layout)||4));
  while (ws.charts.length < layout) {
    ws.charts.push(defaultSymbols[ws.charts.length % Math.max(1, defaultSymbols.length)] || {market:"okx",symbol:"BTC/USDT:USDT",slug:"BTC-USDT-USDT"});
  }
  ws.charts = ws.charts.slice(0, layout);
}

function applyWorkspace() {
  const ws = currentWorkspace();
  normalizeCharts(ws);
  document.getElementById("layoutSelect").value = String(ws.layout);
  document.getElementById("workspaceTimeframe").value = ws.timeframe;
  renderWorkspaceTabs();
  renderMultiChartGrid();
  saveWorkspaceState();
  refreshAll();
}

function chartCard(i, cfg) {
  return `<article class="workspace-chart-card" data-index="${i}">
    <div class="workspace-chart-head">
      <select class="chart-symbol-select" data-index="${i}">
        ${MARKETS.flatMap(m=>m.symbols.map(s=>`<option value="${m.key}|${esc(s.symbol)}|${s.slug}" ${m.key===cfg.market&&s.symbol===cfg.symbol?"selected":""}>${esc(s.symbol)} · ${esc(m.label)}</option>`)).join("")}
      </select>
      <div class="chart-mini-stats" id="chartStats${i}">—</div>
    </div>
    <div class="workspace-plot" id="workspacePlot${i}"></div>
  </article>`;
}

function renderMultiChartGrid() {
  const ws = currentWorkspace();
  const grid = document.getElementById("multiChartGrid");
  grid.className = `multi-chart-grid layout-${ws.layout}`;
  grid.innerHTML = ws.charts.map((c,i)=>chartCard(i,c)).join("");
  plotInitialized = new Set();
  grid.querySelectorAll(".chart-symbol-select").forEach(sel => sel.addEventListener("change", () => {
    const [market,symbol,slug] = sel.value.split("|");
    const idx = Number(sel.dataset.index);
    ws.charts[idx] = {market,symbol,slug};
    if (syncedCharts && idx===0) {
      ws.charts = ws.charts.map((c,j)=>j===0?ws.charts[0]:c);
    }
    saveWorkspaceState();
    refreshCharts();
  }));
}

async function fetchChart(cfg, timeframe) {
  const res = await fetch(`/api/chart/${encodeURIComponent(cfg.market)}/${encodeURIComponent(cfg.slug)}?timeframe=${encodeURIComponent(timeframe)}`);
  return await res.json();
}

function chartLayout(title) {
  return {
    paper_bgcolor:"transparent", plot_bgcolor:"transparent",
    font:{family:"IBM Plex Mono",color:"#8B8F98",size:9},
    margin:{l:40,r:42,t:8,b:26},
    xaxis:{gridcolor:"#23272F",rangeslider:{visible:false}},
    yaxis:{gridcolor:"#23272F",side:"right"},
    showlegend:false, hovermode:"x unified", dragmode:"pan",
    uirevision:`ws-${activeWorkspaceId}-${title}`,
  };
}

async function refreshCharts() {
  const ws = currentWorkspace();
  await Promise.all(ws.charts.map(async (cfg,i) => {
    try {
      const d = await fetchChart(cfg, ws.timeframe);
      if (d.status !== "ok") return;
      const c = d.candles;
      const traces = [
        {type:"candlestick",x:c.t,open:c.o,high:c.h,low:c.l,close:c.c,
         increasing:{line:{color:"#4FAE7A"}},decreasing:{line:{color:"#D5654F"}},name:"Price"},
        {type:"scatter",mode:"lines",x:c.t,y:c.ema9,line:{color:"#E8A33D",width:1},name:"EMA9"},
        {type:"scatter",mode:"lines",x:c.t,y:c.ema21,line:{color:"#5B8FBF",width:1},name:"EMA21"},
      ];
      const id = `workspacePlot${i}`;
      Plotly.react(id,traces,chartLayout(cfg.symbol),{displaylogo:false,responsive:true,modeBarButtonsToRemove:["lasso2d","select2d"]});
      document.getElementById(`chartStats${i}`).innerHTML =
        `<span>${fmtPrice(d.last_price)}</span><span class="${d.last_change_pct>=0?"up":"down"}">${fmtPct(d.last_change_pct)}</span><b style="color:${d.regime_color}">${esc(d.regime_label)}</b>`;
    } catch(e) { console.error(e); }
  }));
}

function renderWatchlist(items) {
  const q = (document.getElementById("watchlistSearch").value||"").toLowerCase();
  const activeFilter = document.querySelector(".watchlist-tabs button.active")?.dataset.filter || "all";
  const filtered = items.filter(x => {
    if (x.status !== "ok") return false;
    if (q && !x.symbol.toLowerCase().includes(q)) return false;
    if (activeFilter==="position" && !x.has_position) return false;
    if (activeFilter==="trend" && !["TREND_UP","TREND_DOWN"].includes(x.regime)) return false;
    if (activeFilter==="strong" && !["STRONG_BULL","STRONG_BEAR","STRONG"].includes(x.regime)) return false;
    return true;
  });
  document.getElementById("watchlistRows").innerHTML = filtered.map(x=>`
    <button class="watchlist-row" data-market="${x.market}" data-symbol="${esc(x.symbol)}" data-slug="${x.slug}">
      <span class="watch-symbol">${esc(x.symbol)}${x.has_position?" ●":""}</span>
      <span class="mono">${fmtPrice(x.price)}</span>
      <span class="${x.change_pct>=0?"up":"down"}">${fmtPct(x.change_pct)}</span>
      <span class="regime-dot" style="background:${x.regime_color}" title="${esc(x.regime_label)}"></span>
      <small>ADX ${x.adx} · Vol ${x.volume_ratio}x</small>
    </button>`).join("") || `<div class="empty-state">No symbols match.</div>`;
  document.querySelectorAll(".watchlist-row").forEach(btn=>btn.addEventListener("click",()=>{
    const ws=currentWorkspace();
    ws.charts[0]={market:btn.dataset.market,symbol:btn.dataset.symbol,slug:btn.dataset.slug};
    saveWorkspaceState(); renderMultiChartGrid(); refreshCharts();
  }));
}

function renderRegimeMap(items) {
  document.getElementById("regimeMap").innerHTML = items.filter(x=>x.status==="ok").map(x=>`
    <div class="regime-map-row"><span>${esc(x.symbol)}</span><strong style="color:${x.regime_color}">${esc(x.regime_label)}</strong><small>ADX ${x.adx} · RSI ${x.rsi}</small></div>`).join("");
}

function heatColor(score) {
  const n=Math.max(-100,Math.min(100,Number(score)||0));
  if(n>0) return `rgba(79,174,122,${0.18+Math.abs(n)/140})`;
  if(n<0) return `rgba(213,101,79,${0.18+Math.abs(n)/140})`;
  return "rgba(139,143,152,.18)";
}
function renderHeatmap(items) {
  document.getElementById("marketHeatmap").innerHTML = items.filter(x=>x.status==="ok").map(x=>`
    <div class="heat-tile" style="background:${heatColor(x.heat_score)}">
      <strong>${esc(x.symbol)}</strong><span>${x.heat_score}</span><small>${esc(x.regime_label)}</small>
    </div>`).join("");
}

async function refreshMarketMap() {
  const tf=currentWorkspace().timeframe;
  const res=await fetch(`/api/market-map?timeframe=${encodeURIComponent(tf)}`);
  const p=await res.json();
  marketItems=p.items||[];
  renderWatchlist(marketItems); renderRegimeMap(marketItems); renderHeatmap(marketItems);
}

async function refreshCorrelation() {
  const market=document.getElementById("correlationMarket").value;
  const tf=currentWorkspace().timeframe;
  const res=await fetch(`/api/correlation/${encodeURIComponent(market)}?timeframe=${encodeURIComponent(tf)}`);
  const p=await res.json();
  const symbols=p.symbols||[], matrix=p.matrix||[];
  const root=document.getElementById("correlationMatrix");
  if(!symbols.length){root.innerHTML='<div class="empty-state">Not enough data.</div>';return;}
  root.style.setProperty("--matrix-cols", symbols.length+1);
  root.innerHTML=`<div class="matrix-cell matrix-head"></div>${symbols.map(s=>`<div class="matrix-cell matrix-head">${esc(s)}</div>`).join("")}`+
    symbols.map((s,i)=>`<div class="matrix-cell matrix-head">${esc(s)}</div>${symbols.map((_,j)=>{
      const v=matrix[i][j]; const alpha=.12+Math.abs(v)*.68; const bg=v>=0?`rgba(79,174,122,${alpha})`:`rgba(213,101,79,${alpha})`;
      return `<div class="matrix-cell" style="background:${bg}">${Number(v).toFixed(2)}</div>`;
    }).join("")}`).join("");
}

async function refreshAll() {
  await Promise.all([refreshCharts(),refreshMarketMap(),refreshCorrelation()]);
  document.getElementById("workspaceSync").textContent=new Date().toLocaleTimeString([],{hour12:false});
}

document.addEventListener("DOMContentLoaded",()=>{
  workspaceState=loadWorkspaceState();
  activeWorkspaceId=workspaceState.active&&workspaceState.workspaces[workspaceState.active]?workspaceState.active:Object.keys(workspaceState.workspaces)[0];
  applyWorkspace();

  document.getElementById("layoutSelect").addEventListener("change",e=>{
    currentWorkspace().layout=Number(e.target.value); normalizeCharts(currentWorkspace()); applyWorkspace();
  });
  document.getElementById("workspaceTimeframe").addEventListener("change",e=>{
    currentWorkspace().timeframe=e.target.value; saveWorkspaceState(); refreshAll();
  });
  document.getElementById("syncChartsBtn").addEventListener("click",e=>{
    syncedCharts=!syncedCharts; e.target.textContent=`Sync symbols: ${syncedCharts?"ON":"OFF"}`; e.target.classList.toggle("active",syncedCharts);
  });
  document.getElementById("newWorkspaceBtn").addEventListener("click",()=>{
    const name=prompt("Workspace name","Workspace");
    if(!name)return;
    const id=`ws-${Date.now()}`;
    workspaceState.workspaces[id]={name,layout:4,timeframe:"15m",charts:defaultSymbols.slice(0,4)};
    activeWorkspaceId=id; workspaceState.active=id; applyWorkspace();
  });
  document.getElementById("saveWorkspaceBtn").addEventListener("click",saveWorkspaceState);
  document.getElementById("resetWorkspaceBtn").addEventListener("click",()=>{
    if(!confirm("Reset current workspace?"))return;
    workspaceState.workspaces[activeWorkspaceId]=workspaceDefaults().workspaces.default;
    applyWorkspace();
  });
  document.getElementById("watchlistSearch").addEventListener("input",()=>renderWatchlist(marketItems));
  document.querySelectorAll(".watchlist-tabs button").forEach(b=>b.addEventListener("click",()=>{
    document.querySelectorAll(".watchlist-tabs button").forEach(x=>x.classList.remove("active")); b.classList.add("active"); renderWatchlist(marketItems);
  }));
  document.getElementById("correlationMarket").addEventListener("change",refreshCorrelation);
  setInterval(refreshAll,WS_REFRESH_MS);
});