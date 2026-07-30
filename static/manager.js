const MANAGER_REFRESH_MS = Math.max(5, parseInt(document.body.dataset.refresh || "15", 10)) * 1000;
let _managerData = null;

function mPrice(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  return Math.abs(n) < 1 ? n.toFixed(6) : Math.abs(n) < 100 ? n.toFixed(4) : n.toLocaleString("en-US", {maximumFractionDigits:2});
}
function mMoney(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : ""}$${n.toFixed(2)}`;
}
function mPct(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function fmtTs(raw) {
  if (!raw) return "—";
  const numeric = Number(raw);
  const d = Number.isFinite(numeric) ? new Date(numeric * (numeric < 1e12 ? 1000 : 1)) : new Date(raw);
  return Number.isNaN(d.getTime()) ? String(raw) : d.toLocaleString();
}

function progressRows(items, kind) {
  if (!items || !items.length) return `<div class="empty-state">Live ${kind} snapshot is not connected.</div>`;
  return `<div class="score-list">${items.map(x => `
    <div class="score-row ${x.active ? "score-row--active" : ""}">
      <div class="score-row__head"><span>${esc(x.key)}</span><span>${Number(x.score).toFixed(2)} / ${Number(x.max).toFixed(2)}</span></div>
      <div class="score-track"><span style="width:${Math.max(0, Math.min(100, x.pct))}%"></span></div>
      ${x.detail ? `<small>${esc(x.detail)}</small>` : ""}
    </div>`).join("")}</div>`;
}

function renderSummary(data) {
  const positions = data.positions || [];
  const totalPnl = positions.reduce((a,p)=>a+(Number(p.pnl_usd)||0),0);
  const totalRisk = positions.reduce((a,p)=>a+(Number(p.risk_usd)||0),0);
  const longCount = positions.filter(p=>p.side==="LONG").length;
  const shortCount = positions.filter(p=>p.side==="SHORT").length;
  document.getElementById("managerSummary").innerHTML = [
    ["Positions", positions.length],
    ["Open PnL", mMoney(totalPnl)],
    ["Open Risk", `$${totalRisk.toFixed(2)}`],
    ["Long / Short", `${longCount} / ${shortCount}`],
    ["Orders", (data.orders||[]).length],
    ["Mode", data.manual_actions_enabled ? "LIVE ACTIONS" : "READ-ONLY"],
  ].map(([k,v])=>`<div class="kpi"><span>${k}</span><strong>${v}</strong></div>`).join("");
  const badge = document.getElementById("managerSafetyBadge");
  if (badge) {
    badge.textContent = data.manual_actions_enabled ? "LIVE ACTIONS · QUEUE ENABLED" : "READ-ONLY · ACTIONS DISABLED";
    badge.classList.toggle("safety-badge--live", Boolean(data.manual_actions_enabled));
  }
}

function actionButtons(p) {
  const enabled = Boolean(_managerData?.manual_actions_enabled);
  const caps = new Set(_managerData?.action_capabilities || []);
  const disabled = action => enabled && caps.has(action) ? "" : "disabled";
  const title = action => enabled && caps.has(action) ? "" : "title=\"This adapter does not allow this action\"";
  return `<div class="position-actions">
    <button class="terminal-btn danger action-btn" data-symbol="${esc(p.symbol)}" data-action="close_100" ${disabled("close_100")} ${title("close_100")}>Close 100%</button>
    <button class="terminal-btn action-btn" data-symbol="${esc(p.symbol)}" data-action="close_25" ${disabled("close_25")} ${title("close_25")}>Close 25%</button>
    <button class="terminal-btn action-btn" data-symbol="${esc(p.symbol)}" data-action="close_50" ${disabled("close_50")} ${title("close_50")}>Close 50%</button>
    <button class="terminal-btn action-btn" data-symbol="${esc(p.symbol)}" data-action="close_75" ${disabled("close_75")} ${title("close_75")}>Close 75%</button>
    <button class="terminal-btn action-btn" data-symbol="${esc(p.symbol)}" data-action="move_sl" ${disabled("move_sl")} ${title("move_sl")}>Move SL</button>
    <button class="terminal-btn action-btn" data-symbol="${esc(p.symbol)}" data-action="move_tp" ${disabled("move_tp")} ${title("move_tp")}>Move TP</button>
    <button class="terminal-btn action-btn" data-symbol="${esc(p.symbol)}" data-action="break_even" ${disabled("break_even")} ${title("break_even")}>Break Even</button>
    <button class="terminal-btn danger action-btn" data-symbol="${esc(p.symbol)}" data-action="emergency_close" ${disabled("emergency_close")} ${title("emergency_close")}>Emergency Close</button>
  </div>`;
}

function positionCard(p) {
  const pnlClass = (Number(p.pnl_usd)||0) >= 0 ? "up" : "down";
  const sideClass = p.side === "LONG" ? "up" : "down";
  const ex = p.explanation || {};
  return `<article class="manager-position-card">
    <div class="manager-position-head">
      <div><a href="/chart/${esc(p.market)}/${esc(p.slug)}" class="manager-symbol">${esc(p.symbol)}</a>
      <span class="${sideClass} mono">${esc(p.side)}</span></div>
      <div class="${pnlClass} manager-pnl">${mMoney(p.pnl_usd)} <small>${mPct(p.pnl_pct)}</small></div>
    </div>

    <div class="position-meter-grid">
      <div><span>Entry</span><strong>${mPrice(p.entry)}</strong></div>
      <div><span>Last</span><strong>${mPrice(p.last_price)}</strong></div>
      <div><span>SL</span><strong class="down">${mPrice(p.sl)}</strong></div>
      <div><span>TP1</span><strong class="up">${mPrice(p.tp1)}</strong></div>
      <div><span>TP2</span><strong class="up">${mPrice(p.tp2)}</strong></div>
      <div><span>TP3</span><strong class="up">${mPrice(p.tp3)}</strong></div>
      <div><span>Size</span><strong>${p.size ?? "—"}</strong></div>
      <div><span>Leverage</span><strong>${p.leverage ?? "—"}x</strong></div>
      <div><span>Regime</span><strong>${esc(p.regime_at_entry || "—")}</strong></div>
      <div><span>Confidence</span><strong>${p.conf_score_at_entry ?? "—"}</strong></div>
      <div><span>Structure</span><strong>${esc(p.bos_type_at_entry || "—")}</strong></div>
      <div><span>Duration</span><strong>${esc(p.opened_ago || "—")}</strong></div>
    </div>

    <div class="manager-insight ${String(ex.risk_level).toUpperCase()}">
      <span>Current risk</span><strong>${esc(ex.risk_level || "UNAVAILABLE")}</strong>
      <small>${esc(ex.current_thesis || "")}</small>
    </div>

    <div class="position-card-footer">
      <button class="terminal-btn explain-btn" data-symbol="${esc(p.symbol)}">Explain Trade</button>
      <button class="terminal-btn timeline-btn" data-symbol="${esc(p.symbol)}">Timeline (${(p.timeline||[]).length})</button>
      <span class="faint mono">ID ${esc(p.trade_id || "—")}</span>
    </div>
    ${actionButtons(p)}
  </article>`;
}

function renderPositions(data) {
  const positions = data.positions || [];
  document.getElementById("managerPositionCount").textContent = positions.length ? `(${positions.length})` : "";
  document.getElementById("managerPositions").innerHTML = positions.length
    ? positions.map(positionCard).join("")
    : `<div class="empty-state">No open positions.</div>`;
  document.querySelectorAll(".explain-btn").forEach(btn => btn.addEventListener("click", () => openExplain(btn.dataset.symbol, false)));
  document.querySelectorAll(".timeline-btn").forEach(btn => btn.addEventListener("click", () => openExplain(btn.dataset.symbol, true)));
  document.querySelectorAll(".action-btn").forEach(btn => btn.addEventListener("click", () => handleActionClick(btn)));
}

function renderOrders(data) {
  const rows = data.orders || [];
  document.getElementById("managerOrderCount").textContent = rows.length ? `(${rows.length})` : "";
  if (!rows.length) {
    document.getElementById("managerOrders").innerHTML = `<div class="empty-state">No order snapshot found. Connect orders_state_file to display orders.</div>`;
    return;
  }
  const keys = ["symbol","side","type","price","amount","status","id"];
  document.getElementById("managerOrders").innerHTML = `<div class="table-scroll"><table class="postable"><thead><tr>${keys.map(k=>`<th>${k}</th>`).join("")}<th>Action</th></tr></thead>
    <tbody>${rows.map(o=>`<tr>${keys.map(k=>`<td>${esc(o[k] ?? "—")}</td>`).join("")}<td><button class="terminal-btn" disabled>Cancel</button></td></tr>`).join("")}</tbody></table></div>`;
}

function renderEvents(data) {
  const rows = (data.events || []).slice().reverse();
  document.getElementById("managerEvents").innerHTML = rows.length ? `<div class="timeline-list">${rows.map(e=>`
    <div class="timeline-event"><time>${fmtTs(e.ts || e.timestamp)}</time><strong>${esc(e.symbol || "SYSTEM")}</strong>
    <span>${esc(e.event || e.type || e.reason || "EVENT")}</span><small>${esc(e.detail || e.message || "")}</small></div>`).join("")}</div>`
    : `<div class="empty-state">No trade_events.jsonl data yet.</div>`;
}

function openExplain(symbol, timelineOnly) {
  const p = (_managerData?.positions || []).find(x=>x.symbol===symbol);
  if (!p) return;
  const ex = p.explanation || {};
  const content = document.getElementById("explainDialogContent");
  if (timelineOnly) {
    content.innerHTML = `<h2>${esc(symbol)} · Position Timeline</h2>${(p.timeline||[]).length ? `<div class="timeline-list">${p.timeline.map(e=>`
      <div class="timeline-event"><time>${fmtTs(e.ts || e.timestamp)}</time><strong>${esc(e.event || e.type || "EVENT")}</strong><small>${esc(e.detail || e.message || e.reason || "")}</small></div>`).join("")}</div>` : `<div class="empty-state">No timeline events recorded.</div>`}`;
  } else {
    content.innerHTML = `<h2>${esc(symbol)} · Explain Trade</h2>
      <div class="explain-summary"><strong>${esc(ex.summary || "")}</strong><p>${esc(ex.current_thesis || "")}</p></div>
      <h3>Why Entry?</h3>${progressRows(ex.entry_factors, "entry")}
      <h3>Exit Engine Live</h3>${progressRows(ex.exit_layers, "exit-engine")}
      <h3>Risk</h3><div class="compare-card"><span>Level</span><strong>${esc(ex.risk_level || "UNAVAILABLE")}</strong>
      ${(ex.risk_notes||[]).map(x=>`<small>${esc(x)}</small>`).join("")}</div>
      ${ex.why_exit ? `<h3>Why Exit?</h3><p>${esc(ex.why_exit)}</p>` : ""}`;
  }
  document.getElementById("explainDialog").showModal();
}

async function handleActionClick(btn) {
  const symbol = btn.dataset.symbol;
  const action = btn.dataset.action;
  const extra = {};
  if (action === "move_sl") {
    const value = prompt(`New stop loss price for ${symbol}:`);
    if (!value) return;
    extra.new_sl = Number(value);
  }
  if (action === "move_tp") {
    const value = prompt(`New take profit price for ${symbol}:`);
    if (!value) return;
    extra.new_tp = Number(value);
  }
  const danger = action === "emergency_close" || action === "close_100";
  const ok = confirm(`${action.replaceAll("_", " ").toUpperCase()} will be queued for ${symbol}. Continue?`);
  if (!ok) return;
  btn.disabled = true;
  try {
    await sendManagerAction(symbol, action, extra);
    btn.textContent = danger ? "Queued" : "Queued OK";
    setTimeout(loadManager, 900);
  } catch (err) {
    alert(`Action failed: ${err.message}`);
    btn.disabled = false;
  }
}

async function sendManagerAction(symbol, action, extra = {}) {
  const bot = document.getElementById("managerBot").value;
  const res = await fetch(`/api/manager/${encodeURIComponent(bot)}/action`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({symbol, action, ...extra}),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok || payload.status === "error" || payload.status === "blocked") {
    throw new Error(payload.message || `HTTP ${res.status}`);
  }
  return payload;
}

async function loadManager() {
  const bot = document.getElementById("managerBot").value;
  try {
    const res = await fetch(`/api/manager/${encodeURIComponent(bot)}`);
    const payload = await res.json();
    if (payload.status !== "ok") throw new Error(payload.message || "Manager unavailable");
    _managerData = payload.data;
    renderSummary(_managerData);
    renderPositions(_managerData);
    renderOrders(_managerData);
    renderEvents(_managerData);
    document.getElementById("managerSync").textContent = new Date().toLocaleTimeString([], {hour12:false});
  } catch (err) {
    console.error(err);
    document.getElementById("managerPositions").innerHTML = `<div class="empty-state">Manager error: ${esc(err.message)}</div>`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("managerRefresh").addEventListener("click", loadManager);
  document.getElementById("managerBot").addEventListener("change", loadManager);
  document.getElementById("closeExplainDialog").addEventListener("click", ()=>document.getElementById("explainDialog").close());
  loadManager();
  setInterval(loadManager, MANAGER_REFRESH_MS);
});
