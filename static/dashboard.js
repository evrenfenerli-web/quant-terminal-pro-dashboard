/* dashboard.js — ticker tape + symbol grid + positions summary (shared) */

const REFRESH_MS = Math.max(5, parseInt(document.body.dataset.refresh || "15", 10)) * 1000;
const _tickerNodes = new Map(); // "market:symbol" -> {price, change, dot}

function fmtPrice(v) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  if (Math.abs(v) < 1) return v.toFixed(6);
  if (Math.abs(v) < 100) return v.toFixed(4);
  return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(v) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function pctClass(v) {
  if (v === null || v === undefined || isNaN(v)) return "";
  return v > 0 ? "up" : v < 0 ? "down" : "";
}

function flash(el, up) {
  if (!el) return;
  el.classList.remove("flash-up", "flash-down");
  // reflow — forces the animation to restart if it's already running
  void el.offsetWidth;
  el.classList.add(up ? "flash-up" : "flash-down");
}

function setSyncTime() {
  const el = document.getElementById("syncTime");
  if (!el) return;
  const now = new Date();
  el.textContent = now.toLocaleTimeString("en-US", { hour12: false });
}

/* ── TICKER TAPE ─────────────────────────────────────────────────────── */
function tickerItemHTML(item) {
  const dotColor = item.status === "ok" ? item.regime_color : "#565B66";
  const priceTxt = item.status === "ok" ? fmtPrice(item.price) : "n/a";
  const chgTxt = item.status === "ok" ? fmtPct(item.change_pct) : "";
  const posFlag = item.has_position ? " ●" : "";
  return `<span class="ticker__item">
      <span class="dot" style="background:${dotColor}"></span>
      <span class="sym">${item.symbol}${posFlag}</span>
      <span class="mono">${priceTxt}</span>
      <span class="mono ${pctClass(item.change_pct)}">${chgTxt}</span>
    </span>`;
}

function renderTicker(items) {
  const track = document.getElementById("tickerTrack");
  if (!track) return;
  if (!items.length) {
    track.innerHTML = `<span class="ticker__item faint">no symbols configured — check dashboard_config.json</span>`;
    return;
  }
  // Content is printed twice back-to-back for a seamless loop (once the
  // track scrolls 50%, the second copy exactly takes the first one's place).
  const html = items.map(tickerItemHTML).join("");
  track.innerHTML = html + html;
}

/* ── SYMBOL CARDS (homepage only) ────────────────────────────────────── */
function updateCard(item) {
  const card = document.getElementById(`card-${item.market}-${item.slug}`);
  if (!card) return;
  const priceEl = card.querySelector(".card__price");
  const chgEl = card.querySelector(".card__change");
  const badgeEl = card.querySelector(".badge");
  const flagEl = card.querySelector(".card__position-flag");

  if (item.status !== "ok") {
    priceEl.textContent = "n/a";
    chgEl.textContent = "";
    badgeEl.textContent = "NO DATA";
    badgeEl.style.color = "#565B66";
    return;
  }

  const prevPrice = parseFloat(priceEl.dataset.raw || "0");
  const newPrice = item.price;
  if (prevPrice && newPrice !== prevPrice) {
    flash(card, newPrice > prevPrice);
  }
  priceEl.dataset.raw = newPrice;
  priceEl.textContent = fmtPrice(newPrice);
  chgEl.textContent = fmtPct(item.change_pct);
  chgEl.className = `card__change mono ${pctClass(item.change_pct)}`;
  badgeEl.textContent = item.regime_label;
  badgeEl.style.color = item.regime_color;
  flagEl.style.display = item.has_position ? "block" : "none";
}

/* ── OPEN POSITIONS SUMMARY (homepage only) ──────────────────────────── */
function renderPositionsSummary(items) {
  const wrap = document.getElementById("positionsWrap");
  const countEl = document.getElementById("posCount");
  if (!wrap) return;

  if (countEl) countEl.textContent = items.length ? ` (${items.length})` : "";

  if (!items.length) {
    wrap.innerHTML = `<div class="empty-state">No open positions on any symbol right now.</div>`;
    return;
  }

  const rows = items.map(p => {
    const pnlClass = (p.pnl_usd ?? 0) >= 0 ? "up" : "down";
    const sideClass = p.side === "LONG" ? "up" : "down";
    return `<tr>
      <td><a href="/chart/${p.market}/${p.slug}">${p.symbol}</a></td>
      <td class="dim">${p.market_label}</td>
      <td class="${sideClass}">${p.side}</td>
      <td>${fmtPrice(p.entry)}</td>
      <td class="${pnlClass}">${p.pnl_usd !== null ? (p.pnl_usd >= 0 ? "+" : "") + p.pnl_usd.toFixed(2) + "$" : "—"}</td>
      <td class="${pnlClass}">${p.pnl_pct !== null ? fmtPct(p.pnl_pct) : "—"}</td>
      <td class="dim">${p.regime_at_entry || "—"}</td>
      <td class="dim">${p.opened_ago}</td>
    </tr>`;
  }).join("");

  wrap.innerHTML = `<table class="postable">
    <thead><tr>
      <th>Symbol</th><th>Bot</th><th>Side</th><th>Entry</th>
      <th>PnL ($)</th><th>PnL (%)</th><th>Regime at Entry</th><th>Open For</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

/* ── POLLING ─────────────────────────────────────────────────────────── */
async function pollTicker() {
  try {
    const res = await fetch("/api/ticker");
    const data = await res.json();
    renderTicker(data.items);
    data.items.forEach(updateCard);
    setSyncTime();
  } catch (e) {
    console.error("ticker poll failed", e);
  }
}

async function pollPositionsSummary() {
  const wrap = document.getElementById("positionsWrap");
  if (!wrap) return; // no positions summary on this page (chart page)
  try {
    const res = await fetch("/api/positions_summary");
    const data = await res.json();
    renderPositionsSummary(data.items);
  } catch (e) {
    console.error("positions summary poll failed", e);
  }
}

function startCommonPolling() {
  pollTicker();
  pollPositionsSummary();
  setInterval(pollTicker, REFRESH_MS);
  setInterval(pollPositionsSummary, REFRESH_MS);
}

document.addEventListener("DOMContentLoaded", startCommonPolling);
