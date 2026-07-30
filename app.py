#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Live dashboard for the Quantum SMC / Alpaca SMC bots.

This service runs independently from the bots: it is its own Flask
process and never touches the bots' running process. It only fetches
candle data from the exchanges and reads the bots' positions_state.json
file.

Run:
    python3 app.py
    # or
    gunicorn -w 1 -b 0.0.0.0:8050 app:app
"""

import re
import time
import logging
import threading
import csv
import io
import os
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

import pandas as pd
from flask import Flask, render_template, jsonify, abort, request, Response

from data_providers import (
    load_config, calculate_indicators, detect_regime, detect_structure_markers,
    load_positions, CryptoProvider, StockProvider, TTLCache,
    REGIME_COLORS, REGIME_LABELS,
)
from funding_engine import FundingEngineV2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dashboard")

app = Flask(__name__)

CONFIG = load_config()
CACHE_TTL = max(5, CONFIG.get("refresh_seconds", 15) - 2)
cache = TTLCache(ttl_seconds=CACHE_TTL)
CRYPTO_MARKET_KEYS = ("okx", "binance", "bybit")
DEFAULT_ACTION_CAPABILITIES = [
    "close_100", "close_25", "close_50", "close_75",
    "move_sl", "move_tp", "break_even", "emergency_close",
]

# =============================================================================
# MARKET REGISTRY (builds providers and symbol/slug maps from config)
# =============================================================================
_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


def _slugify(symbol: str) -> str:
    return _SLUG_RE.sub("-", symbol).strip("-").upper()


class MarketRegistry:
    def __init__(self, cfg: Dict[str, Any]):
        self.markets: Dict[str, Dict[str, Any]] = {}

        for market_key in CRYPTO_MARKET_KEYS:
            crypto_cfg = cfg.get(market_key, {})
            if crypto_cfg.get("enabled") and crypto_cfg.get("symbols"):
                try:
                    provider = CryptoProvider(
                        exchange_id=crypto_cfg.get("exchange_id", market_key),
                        sandbox_mode=crypto_cfg.get("sandbox_mode", False),
                        default_type=crypto_cfg.get("default_type", "swap"),
                    )
                    self._register(market_key, crypto_cfg, provider)
                except Exception as e:
                    logger.error(f"Could not set up the {market_key.upper()} provider, this market is disabled: {e}")

        alpaca_cfg = cfg.get("alpaca", {})
        if alpaca_cfg.get("enabled") and alpaca_cfg.get("symbols"):
            if not alpaca_cfg.get("api_key") or not alpaca_cfg.get("api_secret"):
                logger.error("Alpaca api_key/api_secret is empty in dashboard_config.json, this market is disabled")
            else:
                try:
                    provider = StockProvider(alpaca_cfg["api_key"], alpaca_cfg["api_secret"])
                    self._register("alpaca", alpaca_cfg, provider)
                except Exception as e:
                    logger.error(f"Could not set up the Alpaca provider, this market is disabled: {e}")

        if not self.markets:
            logger.warning(
                "No market is enabled — dashboard_config.json must have "
                "'enabled': true and at least one symbol under a market adapter."
            )

    def _register(self, key: str, mcfg: Dict[str, Any], provider):
        symbol_map, slug_map = {}, {}
        for sym in mcfg["symbols"]:
            slug = _slugify(sym)
            symbol_map[slug] = sym
            slug_map[sym] = slug
        self.markets[key] = {
            "label": mcfg.get("label", key.upper()),
            "provider": provider,
            "symbols": mcfg["symbols"],
            "symbol_map": symbol_map,     # slug -> real symbol
            "slug_map": slug_map,         # real symbol -> slug
            "positions_file": mcfg.get("positions_state_file", ""),
            "orders_file": mcfg.get("orders_state_file", ""),
            "decision_file": mcfg.get("decision_state_file", ""),
            "trade_events_file": mcfg.get("trade_events_file", ""),
            "manual_actions_file": mcfg.get("manual_actions_file", ""),
            "action_capabilities": mcfg.get("action_capabilities", DEFAULT_ACTION_CAPABILITIES),
        }

    def resolve(self, market_key: str, slug: str):
        m = self.markets.get(market_key)
        if not m:
            return None, None
        symbol = m["symbol_map"].get(slug)
        if not symbol:
            return m, None
        return m, symbol


registry = MarketRegistry(CONFIG)

PRIMARY_TF = CONFIG.get("primary_timeframe", "15m")
CANDLES = CONFIG.get("candles_shown", 180)
REGIME_THRESHOLDS = CONFIG.get("regime_thresholds", {})


# =============================================================================
# HELPERS
# =============================================================================
def _age_str(open_time_iso: str) -> str:
    try:
        opened = datetime.fromisoformat(open_time_iso)
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - opened
        mins = int(delta.total_seconds() // 60)
        if mins < 60:
            return f"{mins}m"
        hrs, rem = divmod(mins, 60)
        if hrs < 24:
            return f"{hrs}h {rem}m"
        days, rem_h = divmod(hrs, 24)
        return f"{days}d {rem_h}h"
    except Exception:
        return "-"


def _position_payload(pos: Dict[str, Any], live_price: Optional[float]) -> Dict[str, Any]:
    entry = float(pos.get("entry", 0) or 0)
    size = float(pos.get("size", 0) or 0)
    side = pos.get("signal", "LONG")
    direction = 1 if side == "LONG" else -1

    pnl_pct = None
    pnl_usd = None
    if live_price and entry:
        pnl_pct = ((live_price - entry) / entry) * direction * 100
        pnl_usd = (live_price - entry) * size * direction

    return {
        "side": side,
        "entry": entry,
        "sl": pos.get("sl"),
        "tp1": pos.get("tp1"),
        "tp2": pos.get("tp2"),
        "tp3": pos.get("tp3"),
        "tp1_hit": bool(pos.get("tp1_hit")),
        "tp2_hit": bool(pos.get("tp2_hit")),
        "tp3_hit": bool(pos.get("tp3_hit")),
        "regime_at_entry": pos.get("regime"),
        "conf_score_at_entry": pos.get("conf_score"),
        "bos_type_at_entry": pos.get("bos_type"),
        "leverage": pos.get("leverage"),
        "opened_ago": _age_str(pos.get("open_time", "")),
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "pnl_usd": round(pnl_usd, 2) if pnl_usd is not None else None,
        "size": size,
        "original_size": float(pos.get("original_size", size) or size),
        "atr": pos.get("atr"),
        "trade_id": pos.get("trade_id"),
        "has_sweep": bool(pos.get("has_sweep")),
        "open_time": pos.get("open_time"),
        "open_ts": pos.get("open_ts"),
        "original_sl": pos.get("original_sl"),
        "peak_pnl": pos.get("peak_pnl"),
        "highest_price": pos.get("highest_price"),
        "lowest_price": pos.get("lowest_price"),
        "funding_at_entry": pos.get("funding_at_entry"),
        "entry_imbalance": pos.get("entry_imbalance"),
        "mtf_score": pos.get("mtf_score"),
        "quality_score": pos.get("quality_score"),
        "risk_usd": abs(entry - float(pos.get("sl", entry) or entry)) * size if entry and size else None,
    }


def _build_chart_payload(market_key: str, symbol: str, timeframe: Optional[str] = None) -> Dict[str, Any]:
    m = registry.markets[market_key]
    provider = m["provider"]
    timeframe = timeframe or PRIMARY_TF
    allowed = CONFIG.get("timeframes", [PRIMARY_TF])
    if timeframe not in allowed:
        timeframe = PRIMARY_TF

    def _fetch():
        df = provider.get_ohlcv(symbol, timeframe, limit=CANDLES)
        if df is None or len(df) < 50:
            return None
        df = calculate_indicators(df)
        regime = detect_regime(df, REGIME_THRESHOLDS)
        markers = detect_structure_markers(df)
        return {"df": df, "regime": regime, "markers": markers}

    cache_key = f"chart:{market_key}:{symbol}:{timeframe}"
    bundle = cache.get_or_set(cache_key, _fetch)

    if bundle is None:
        return {"status": "error", "message": "Could not fetch data (the exchange may be unreachable)"}

    df = bundle["df"]
    last_close = float(df["close"].iloc[-1])

    positions = load_positions(m["positions_file"])
    pos = positions.get(symbol)
    position_payload = _position_payload(pos, last_close) if pos else None

    candles = {
        "t": [ts.isoformat() for ts in df["timestamp"]],
        "o": df["open"].round(6).tolist(),
        "h": df["high"].round(6).tolist(),
        "l": df["low"].round(6).tolist(),
        "c": df["close"].round(6).tolist(),
        "v": df["volume"].round(2).tolist(),
        "ema9": df["ema_9"].round(6).tolist(),
        "ema21": df["ema_21"].round(6).tolist(),
        "ema50": df["ema_50"].round(6).tolist(),
        "ema200": df["ema_200"].round(6).tolist(),
    }

    last_row = df.iloc[-1]
    prev_row = df.iloc[-2] if len(df) > 1 else last_row

    return {
        "status": "ok",
        "symbol": symbol,
        "market": market_key,
        "timeframe": timeframe,
        "last_price": round(last_close, 6),
        "last_change_pct": round(((last_close - float(prev_row["close"])) / float(prev_row["close"])) * 100, 3)
            if float(prev_row["close"]) else 0.0,
        "regime": bundle["regime"],
        "regime_label": REGIME_LABELS.get(bundle["regime"], bundle["regime"]),
        "regime_color": REGIME_COLORS.get(bundle["regime"], "#8B8F98"),
        "adx": round(float(last_row.get("adx", 0) or 0), 1),
        "rsi": round(float(last_row.get("rsi", 0) or 0), 1),
        "structure_markers": bundle["markers"],
        "position": position_payload,
        "candles": candles,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }





# =============================================================================
# PHASE 3 — WORKSPACE / MULTI-CHART / MARKET MAP
# =============================================================================
def _market_snapshot(market_key: str, symbol: str, timeframe: str = None) -> Dict[str, Any]:
    market = registry.markets[market_key]
    provider = market["provider"]
    timeframe = timeframe or PRIMARY_TF
    df = provider.get_ohlcv(symbol, timeframe, limit=max(80, min(CANDLES, 220)))
    if df is None or len(df) < 50:
        return {"status": "error", "symbol": symbol, "market": market_key}
    df = calculate_indicators(df)
    regime = detect_regime(df, REGIME_THRESHOLDS)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    vol_sma = float(last.get("vol_sma", 0) or 0)
    volume = float(last.get("volume", 0) or 0)
    volume_ratio = volume / vol_sma if vol_sma > 0 else 0.0
    close = float(last.get("close", 0) or 0)
    change = ((close - float(prev.get("close", close))) / float(prev.get("close", close)) * 100) if float(prev.get("close", 0) or 0) else 0.0
    ema9 = float(last.get("ema_9", close) or close)
    ema21 = float(last.get("ema_21", close) or close)
    momentum = ((ema9 - ema21) / close * 100) if close else 0.0
    adx = float(last.get("adx", 0) or 0)
    rsi = float(last.get("rsi", 0) or 0)

    # Visualization score only, not bot entry confidence.
    regime_weight = {
        "STRONG_BULL": 2.0, "TREND_UP": 1.4, "NEUTRAL": 0.2, "RANGE": 0.0,
        "TREND_DOWN": -1.4, "STRONG_BEAR": -2.0, "STRONG": 0.0, "CHOP": 0.0, "SHOCK": 0.0,
    }.get(regime, 0.0)
    heat_score = max(-100.0, min(100.0, regime_weight * 25 + momentum * 12 + (rsi - 50) * 0.7))

    positions = load_positions(market["positions_file"])
    pos = positions.get(symbol)
    pos_payload = _position_payload(pos, close) if pos else None
    return {
        "status": "ok",
        "market": market_key,
        "market_label": market["label"],
        "symbol": symbol,
        "slug": market["slug_map"].get(symbol, _slugify(symbol)),
        "timeframe": timeframe,
        "price": round(close, 8),
        "change_pct": round(change, 3),
        "regime": regime,
        "regime_label": REGIME_LABELS.get(regime, regime),
        "regime_color": REGIME_COLORS.get(regime, "#8B8F98"),
        "adx": round(adx, 1),
        "rsi": round(rsi, 1),
        "volume_ratio": round(volume_ratio, 2),
        "momentum": round(momentum, 3),
        "heat_score": round(heat_score, 1),
        "has_position": bool(pos),
        "position": pos_payload,
    }


@app.route("/workspace")
def workspace_page():
    return render_template(
        "workspace.html",
        markets=[
            {
                "key": key,
                "label": m["label"],
                "symbols": [{"symbol": s, "slug": m["slug_map"].get(s, _slugify(s))} for s in m["symbols"]],
            }
            for key, m in registry.markets.items()
        ],
        timeframes=CONFIG.get("timeframes", [PRIMARY_TF]),
        refresh_seconds=CONFIG.get("refresh_seconds", 15),
        default_layout=CONFIG.get("phase3", {}).get("multi_chart_default_layout", 4),
        sidebar_default_pinned=CONFIG.get("phase3", {}).get("sidebar_default_pinned", True),
    )


@app.route("/api/market-map")
def api_market_map():
    timeframe = request.args.get("timeframe", PRIMARY_TF)
    items = []
    for market_key, market in registry.markets.items():
        for symbol in market["symbols"]:
            try:
                items.append(_market_snapshot(market_key, symbol, timeframe))
            except Exception as exc:
                logger.debug("market map %s %s: %s", market_key, symbol, exc)
                items.append({"status": "error", "market": market_key, "symbol": symbol})
    return jsonify({"status": "ok", "items": items, "generated_at": datetime.now(timezone.utc).isoformat()})


@app.route("/api/correlation/<market_key>")
def api_correlation(market_key: str):
    market = registry.markets.get(market_key)
    if not market:
        abort(404)
    timeframe = request.args.get("timeframe", PRIMARY_TF)
    lookback = int(CONFIG.get("phase3", {}).get("correlation_lookback", 120))
    series = {}
    for symbol in market["symbols"]:
        try:
            df = market["provider"].get_ohlcv(symbol, timeframe, limit=lookback + 20)
            if df is not None and len(df) >= 30:
                series[symbol] = df.set_index("timestamp")["close"].astype(float).pct_change()
        except Exception as exc:
            logger.debug("correlation fetch %s: %s", symbol, exc)
    if len(series) < 2:
        return jsonify({"status": "ok", "symbols": list(series.keys()), "matrix": []})
    frame = pd.concat(series, axis=1).dropna(how="all")
    corr = frame.corr().fillna(0.0)
    symbols = list(corr.columns)
    return jsonify({
        "status": "ok",
        "symbols": symbols,
        "matrix": [[round(float(corr.loc[a, b]), 3) for b in symbols] for a in symbols],
        "timeframe": timeframe,
    })


# =============================================================================
# PHASE 2 — READ-ONLY TRADE MANAGER
# =============================================================================
def _read_json_file(path: str, default: Any) -> Any:
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read state file %s: %s", path, exc)
        return default


def _normalize_orders(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        if isinstance(raw.get("orders"), list):
            return [x for x in raw["orders"] if isinstance(x, dict)]
        rows = []
        for key, value in raw.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("id", key)
                rows.append(row)
        return rows
    return []


def _decision_for_symbol(decisions: Any, symbol: str) -> Dict[str, Any]:
    if not isinstance(decisions, dict):
        return {}
    if isinstance(decisions.get(symbol), dict):
        return decisions[symbol]
    symbols = decisions.get("symbols")
    if isinstance(symbols, dict) and isinstance(symbols.get(symbol), dict):
        return symbols[symbol]
    return {}


def _score_items(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    rows = []
    for key, value in raw.items():
        if isinstance(value, dict):
            score = value.get("score", value.get("value", 0))
            maximum = value.get("max", value.get("maximum", 10))
            active = value.get("active", value.get("triggered", False))
            detail = value.get("detail", value.get("reason", ""))
        else:
            score, maximum, active, detail = value, 10, False, ""
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.0
        try:
            maximum = max(float(maximum), 1e-9)
        except (TypeError, ValueError):
            maximum = 10.0
        rows.append({
            "key": str(key),
            "score": round(score, 4),
            "max": round(maximum, 4),
            "pct": round(max(0.0, min(100.0, score / maximum * 100)), 1),
            "active": bool(active),
            "detail": str(detail or ""),
        })
    return rows


def _build_explanation(position: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
    entry_factors = decision.get("entry_factors") or decision.get("entry_scores") or {}
    exit_layers = decision.get("exit_layers") or decision.get("smart_exit") or {}
    risk = decision.get("risk") if isinstance(decision.get("risk"), dict) else {}

    fallback_entry = {
        "BOS/CHOCH": {"score": 10 if position.get("bos_type") else 0, "max": 10, "detail": position.get("bos_type") or "not recorded"},
        "Liquidity sweep": {"score": 10 if position.get("has_sweep") else 0, "max": 10, "detail": "confirmed" if position.get("has_sweep") else "not recorded"},
        "Confidence": {"score": position.get("conf_score_at_entry") or 0, "max": 10, "detail": "entry confidence"},
        "MTF": {"score": position.get("mtf_score") or 0, "max": 10, "detail": "MTF score"},
        "Quality": {"score": position.get("quality_score") or 0, "max": 10, "detail": "quality score"},
    }
    if not entry_factors:
        entry_factors = fallback_entry

    return {
        "summary": decision.get("summary") or (
            f"{position.get('side', 'UNKNOWN')} position opened in "
            f"{position.get('regime_at_entry') or 'UNKNOWN'} regime."
        ),
        "risk_level": decision.get("risk_level") or risk.get("level") or "UNAVAILABLE",
        "risk_notes": decision.get("risk_notes") or risk.get("notes") or [],
        "entry_factors": _score_items(entry_factors),
        "exit_layers": _score_items(exit_layers),
        "current_thesis": decision.get("current_thesis") or "Live decision snapshot is not connected.",
        "why_exit": decision.get("why_exit") or "",
        "updated_at": decision.get("updated_at") or decision.get("ts"),
    }


def _load_trade_events(market: Dict[str, Any], symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    limit = int(CONFIG.get("phase2", {}).get("max_timeline_events", 1000))
    rows = _read_jsonl(market.get("trade_events_file", ""), limit)
    if symbol:
        rows = [r for r in rows if r.get("symbol") == symbol]
    return sorted(rows, key=lambda r: _safe_float(r.get("ts", r.get("timestamp", 0))))


def _manager_bundle(market_key: str) -> Dict[str, Any]:
    market = registry.markets[market_key]
    positions_raw = load_positions(market["positions_file"])
    orders = _normalize_orders(_read_json_file(market.get("orders_file", ""), []))
    decisions = _read_json_file(market.get("decision_file", ""), {})
    events = _load_trade_events(market)

    positions = []
    provider = market.get("provider")
    for symbol, raw in positions_raw.items():
        live_price = None
        try:
            live_price = provider.get_last_price(symbol) if provider else None
        except Exception:
            pass
        payload = _position_payload(raw, live_price)
        payload.update({
            "symbol": symbol,
            "slug": market["slug_map"].get(symbol, _slugify(symbol)),
            "market": market_key,
            "market_label": market["label"],
            "last_price": live_price,
            "explanation": _build_explanation(payload, _decision_for_symbol(decisions, symbol)),
            "timeline": [e for e in events if e.get("symbol") == symbol][-100:],
        })
        positions.append(payload)

    return {
        "market": market_key,
        "market_label": market["label"],
        "positions": positions,
        "orders": orders,
        "events": events[-250:],
        "manual_actions_enabled": bool(CONFIG.get("phase2", {}).get("manual_actions_enabled", False)),
        "action_capabilities": market.get("action_capabilities", DEFAULT_ACTION_CAPABILITIES),
        "state_sources": {
            "positions": market.get("positions_file", ""),
            "orders": market.get("orders_file", ""),
            "decisions": market.get("decision_file", ""),
            "events": market.get("trade_events_file", ""),
            "manual_actions": (
                market.get("manual_actions_file")
                or CONFIG.get("phase2", {}).get("manual_actions_file", "")
            ),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.route("/manager")
def manager_page():
    return render_template(
        "manager.html",
        bots=[{"key": key, "label": m["label"]} for key, m in registry.markets.items()],
        refresh_seconds=CONFIG.get("refresh_seconds", 15),
    )


@app.route("/api/manager/<market_key>")
def api_manager(market_key: str):
    if market_key not in registry.markets:
        return jsonify({"status": "error", "message": "Market not found"}), 404
    return jsonify({"status": "ok", "data": _manager_bundle(market_key)})


@app.route("/api/manager/<market_key>/position/<slug>")
def api_manager_position(market_key: str, slug: str):
    market, symbol = registry.resolve(market_key, slug)
    if not market or not symbol:
        abort(404)
    bundle = _manager_bundle(market_key)
    position = next((p for p in bundle["positions"] if p["symbol"] == symbol), None)
    if position is None:
        return jsonify({"status": "error", "message": "Position not found"}), 404
    return jsonify({"status": "ok", "data": position})


@app.route("/api/manager/<market_key>/action", methods=["POST"])
def api_manager_action(market_key: str):
    """Queue a manual trading action for an external bot adapter to execute."""
    market = registry.markets.get(market_key)
    if not market:
        abort(404)
    if not CONFIG.get("phase2", {}).get("manual_actions_enabled", False):
        return jsonify({
            "status": "blocked",
            "message": "Manual trading actions are disabled in dashboard_config.json.",
        }), 403

    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "").strip().lower()
    symbol = str(payload.get("symbol") or "").strip()
    action_aliases = {"close": "close_100", "partial_close": "close_50"}
    action = action_aliases.get(action, action)
    allowed_actions = set(market.get("action_capabilities", DEFAULT_ACTION_CAPABILITIES))
    if action not in allowed_actions:
        return jsonify({"status": "error", "message": f"Unsupported action: {action}"}), 400
    if action != "emergency_close" and not symbol:
        return jsonify({"status": "error", "message": "symbol is required"}), 400

    action_file = (
        market.get("manual_actions_file")
        or CONFIG.get("phase2", {}).get("manual_actions_file")
        or "./manual_actions.jsonl"
    )
    action_file = os.path.abspath(os.path.expanduser(action_file))
    os.makedirs(os.path.dirname(action_file), exist_ok=True)

    record = {
        "id": uuid.uuid4().hex,
        "ts": time.time(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "market": market_key,
        "action": action,
        "symbol": symbol,
        "payload": payload,
    }
    close_pct_map = {"close_25": 0.25, "close_50": 0.50, "close_75": 0.75, "close_100": 1.0}
    if action in close_pct_map:
        record["close_pct"] = close_pct_map[action]
    for key in ("pct", "percent", "close_pct", "price", "sl", "tp", "new_sl", "new_tp", "level", "tp_level"):
        if key in payload:
            record[key] = payload[key]
    with open(action_file, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")

    logger.warning("Queued manual action: %s %s on %s -> %s", action, symbol, market_key, action_file)
    return jsonify({
        "status": "queued",
        "message": "Manual action queued for the bot adapter.",
        "action": action,
        "symbol": symbol,
        "action_file": action_file,
    })


# =============================================================================
# ANALYTICS ENGINE (read-only)
# =============================================================================
def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_jsonl(path: str, last_n: Optional[int] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path or not os.path.exists(path):
        return rows
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        logger.warning("Could not read analytics file %s: %s", path, exc)
        return []
    return rows[-last_n:] if last_n else rows


def _analytics_paths(bot_key: str) -> Dict[str, str]:
    return CONFIG.get("analytics", {}).get(bot_key, {})


def _phase6_group_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "count": 0, "win_rate": 0.0, "avg_r": 0.0, "profit_factor": None,
            "avg_mfe_r": None, "avg_mae_r": None, "avg_capture_ratio": None,
            "avg_bars_held": None, "tp1_rate": 0.0, "tp2_rate": 0.0, "tp3_rate": 0.0,
        }
    enriched = [_phase4_enrich_trade(row) for row in rows]
    exits = [_safe_float(row.get("exit_r")) for row in enriched]
    positive = sum(value for value in exits if value > 0)
    negative = abs(sum(value for value in exits if value < 0))
    captures = [
        _safe_float(row.get("capture_ratio"))
        for row in enriched if row.get("capture_ratio") is not None
    ]
    bars = [
        _safe_float(row.get("bars_held"))
        for row in enriched if row.get("bars_held") is not None
    ]
    return {
        "count": len(enriched),
        "win_rate": round(sum(value > 0 for value in exits) / len(enriched) * 100, 1),
        "avg_r": round(sum(exits) / len(enriched), 3),
        "profit_factor": round(positive / negative, 2) if negative > 1e-9 else None,
        "avg_mfe_r": round(sum(_safe_float(row.get("mfe_r")) for row in enriched) / len(enriched), 3),
        "avg_mae_r": round(sum(_safe_float(row.get("mae_r")) for row in enriched) / len(enriched), 3),
        "avg_capture_ratio": round(sum(captures) / len(captures), 4) if captures else None,
        "avg_bars_held": round(sum(bars) / len(bars), 1) if bars else None,
        "tp1_rate": round(sum(row["tp1_hit"] for row in enriched) / len(enriched) * 100, 1),
        "tp2_rate": round(sum(row["tp2_hit"] for row in enriched) / len(enriched) * 100, 1),
        "tp3_rate": round(sum(row["tp3_hit"] for row in enriched) / len(enriched) * 100, 1),
    }


def _file_health(name: str, path: str, stale_seconds: int) -> Dict[str, Any]:
    if not path:
        return {"name": name, "connected": False, "status": "NOT_CONFIGURED", "age_seconds": None, "size_bytes": 0}
    try:
        stat = os.stat(path)
    except OSError:
        return {"name": name, "connected": False, "status": "MISSING", "age_seconds": None, "size_bytes": 0}
    age = max(0, int(time.time() - stat.st_mtime))
    return {
        "name": name,
        "connected": True,
        "status": "STALE" if age > stale_seconds else "OK",
        "age_seconds": age,
        "size_bytes": stat.st_size,
    }


def _phase6_config_audit(bot_key: str) -> Dict[str, Any]:
    issues: List[Dict[str, str]] = []
    phase6 = CONFIG.get("phase6", {})
    allowed = set(phase6.get(
        "allowed_entry_regimes",
        ["TREND_UP", "STRONG_BULL", "TREND_DOWN", "STRONG_BEAR"],
    ))
    forbidden = {"RANGE", "NEUTRAL", "CHOP", "SHOCK"}
    overlap = sorted(allowed & forbidden)
    if overlap:
        issues.append({"severity": "ERROR", "code": "REGIME_OVERLAP", "detail": ", ".join(overlap)})
    if CONFIG.get("phase2", {}).get("manual_actions_enabled", False):
        issues.append({"severity": "INFO", "code": "MANUAL_ACTIONS_ENABLED", "detail": "Manual action queue is enabled"})
    symbols = CONFIG.get(bot_key, {}).get("symbols", [])
    duplicates = sorted({symbol for symbol in symbols if symbols.count(symbol) > 1})
    if duplicates:
        issues.append({"severity": "ERROR", "code": "DUPLICATE_SYMBOLS", "detail": ", ".join(duplicates)})
    if not symbols:
        issues.append({"severity": "WARN", "code": "NO_SYMBOLS", "detail": f"No symbols configured for {bot_key}"})
    weights = CONFIG.get("phase4", {})
    weight_sum = _safe_float(weights.get("exit_quality_capture_weight"), .75) + _safe_float(
        weights.get("exit_quality_mae_weight"), .25
    )
    if abs(weight_sum - 1.0) > 1e-6:
        issues.append({"severity": "WARN", "code": "EXIT_WEIGHT_NORMALIZED", "detail": f"Configured sum is {weight_sum:.4f}"})
    if not CONFIG.get("analytics", {}).get(bot_key):
        issues.append({"severity": "ERROR", "code": "ANALYTICS_MISSING", "detail": f"No analytics block for {bot_key}"})
    return {
        "status": (
            "FAIL" if any(item["severity"] == "ERROR" for item in issues)
            else "WARN" if any(item["severity"] == "WARN" for item in issues)
            else "PASS"
        ),
        "issues": issues,
        "allowed_entry_regimes": sorted(allowed),
        "forbidden_entry_regimes": sorted(forbidden),
        "symbol_config_source": "market_registry",
    }


def _diagnostics_bundle(bot_key: str, last_n: Optional[int] = None) -> Dict[str, Any]:
    paths = _analytics_paths(bot_key)
    trades = _read_jsonl(paths.get("trade_analytics_file", ""), last_n)
    rejected = _read_jsonl(paths.get("rejected_analytics_file", ""), last_n)
    phase6 = CONFIG.get("phase6", {})

    by_coin: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_regime: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_hour: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_weekday: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    bars_buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    bucket_defs = phase6.get("bars_held_buckets", [5, 10, 20, 50])
    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    forbidden_regimes = set(phase6.get("forbidden_entry_regimes", ["RANGE", "NEUTRAL", "CHOP", "SHOCK"]))
    regime_violations = []
    counter_trend_violations = []
    for row in trades:
        symbol = str(row.get("symbol") or "UNKNOWN")
        regime = str(row.get("regime") or row.get("regime_at_entry") or "UNKNOWN").upper()
        side = str(row.get("signal") or row.get("side") or "UNKNOWN").upper()
        by_coin[symbol].append(row)
        by_regime[regime].append(row)
        bars = row.get("bars_held")
        if bars is not None:
            value = _safe_float(bars)
            lower = 0
            label = f">{bucket_defs[-1]}"
            for upper in bucket_defs:
                if value <= upper:
                    label = f"{lower}-{upper}"
                    break
                lower = upper + 1
            bars_buckets[label].append(row)
        ts = row.get("opened_at", row.get("open_ts", row.get("closed_at")))
        try:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            by_hour[f"{dt.hour:02d}:00"].append(row)
            by_weekday[weekday_names[dt.weekday()]].append(row)
        except (TypeError, ValueError, OSError):
            pass
        if regime in forbidden_regimes:
            regime_violations.append({
                "trade_id": row.get("trade_id"), "symbol": symbol, "side": side, "regime": regime,
            })
        counter = (
            (regime in {"TREND_UP", "STRONG_BULL"} and side == "SHORT")
            or (regime in {"TREND_DOWN", "STRONG_BEAR"} and side == "LONG")
        )
        if counter:
            counter_trend_violations.append({
                "trade_id": row.get("trade_id"), "symbol": symbol, "side": side, "regime": regime,
            })

    btc_rejections = []
    btc_reason_counts = defaultdict(int)
    for row in rejected:
        reason = str(row.get("reason") or row.get("reject_reason") or "UNKNOWN")
        if "BTC" in reason.upper() or row.get("btc_filter_passed") is False:
            btc_rejections.append(row)
            btc_reason_counts[reason.split(":", 1)[0]] += 1
    btc_fields = sum(
        int(any(key in row for key in ("btc_filter_passed", "btc_regime", "btc_filter_reason")))
        for row in trades
    )

    priority_rows = []
    multiple_trigger_count = 0
    priority_coverage = 0
    for row in trades:
        candidates = row.get("exit_trigger_candidates", row.get("exit_candidates", row.get("triggered_exits", [])))
        if isinstance(candidates, str):
            candidates = [part.strip() for part in candidates.split(",") if part.strip()]
        if not isinstance(candidates, list):
            candidates = []
        if candidates:
            priority_coverage += 1
        if len(candidates) > 1:
            multiple_trigger_count += 1
            priority_rows.append({
                "trade_id": row.get("trade_id"),
                "symbol": row.get("symbol"),
                "selected": row.get("exit_reason"),
                "candidates": candidates,
            })

    required_fields = phase6.get("required_trade_fields", [
        "trade_id", "symbol", "signal", "regime", "exit_reason", "exit_r",
        "mfe_r", "mae_r", "bars_held", "tp1_hit", "tp2_hit", "tp3_hit",
    ])
    coverage = {}
    for field in required_fields:
        present = sum(row.get(field) is not None for row in trades)
        coverage[field] = {
            "present": present,
            "missing": len(trades) - present,
            "coverage_pct": round(present / len(trades) * 100, 1) if trades else 0.0,
        }

    market = registry.markets[bot_key]
    raw_positions = _read_json_file(market.get("positions_file", ""), {})
    position_sides: Dict[str, set] = defaultdict(set)
    direct_conflicts = set()
    if isinstance(raw_positions, dict):
        position_items = list(raw_positions.items())
    elif isinstance(raw_positions, list):
        position_items = [(str(index), row) for index, row in enumerate(raw_positions)]
    else:
        position_items = []
    for key, row in position_items:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or key)
        side = str(row.get("signal") or row.get("side") or "").upper()
        if side in {"LONG", "SHORT"}:
            position_sides[symbol].add(side)
        if _safe_float(row.get("long_size")) > 0 and _safe_float(row.get("short_size")) > 0:
            direct_conflicts.add(symbol)
    position_conflicts = sorted(
        direct_conflicts | {symbol for symbol, sides in position_sides.items() if {"LONG", "SHORT"} <= sides}
    )
    configured_symbols = list(market.get("symbols", []))
    observed_symbols = sorted(by_coin)
    stale_seconds = int(phase6.get("stale_after_seconds", 300))
    source_health = [
        _file_health("positions_state", market.get("positions_file", ""), stale_seconds),
        _file_health("orders_state", market.get("orders_file", ""), stale_seconds),
        _file_health("decision_state", market.get("decision_file", ""), stale_seconds),
        _file_health("trade_events", market.get("trade_events_file", ""), stale_seconds),
    ]
    source_health.extend(
        _file_health(name.replace("_file", ""), path, stale_seconds)
        for name, path in paths.items()
    )
    config_audit = _phase6_config_audit(bot_key)
    return {
        "bot": bot_key,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "trades": len(trades),
            "coins": len(by_coin),
            "regime_violations": len(regime_violations),
            "counter_trend_violations": len(counter_trend_violations),
            "position_side_conflicts": len(position_conflicts),
            "btc_rejections": len(btc_rejections),
            "missing_fields": sum(item["missing"] for item in coverage.values()),
            "config_status": config_audit["status"],
        },
        "coin_analytics": {
            symbol: _phase6_group_stats(rows)
            for symbol, rows in sorted(by_coin.items())
        },
        "time_analytics": {
            "bars_held": {key: _phase6_group_stats(rows) for key, rows in bars_buckets.items()},
            "hour_utc": {key: _phase6_group_stats(rows) for key, rows in sorted(by_hour.items())},
            "weekday": {key: _phase6_group_stats(by_weekday[key]) for key in weekday_names if key in by_weekday},
        },
        "regime_debug": {
            "stats": {key: _phase6_group_stats(rows) for key, rows in sorted(by_regime.items())},
            "forbidden_entries": regime_violations[-200:],
            "counter_trend_entries": counter_trend_violations[-200:],
        },
        "btc_filter_debug": {
            "rejected": len(btc_rejections),
            "by_reason": dict(sorted(btc_reason_counts.items(), key=lambda item: -item[1])),
            "trade_field_coverage_pct": round(btc_fields / len(trades) * 100, 1) if trades else 0.0,
            "recent": btc_rejections[-100:],
        },
        "exit_trigger_priority": {
            "coverage_pct": round(priority_coverage / len(trades) * 100, 1) if trades else 0.0,
            "multiple_trigger_trades": multiple_trigger_count,
            "recent_multiple": priority_rows[-100:],
        },
        "symbol_config": {
            "configured": configured_symbols,
            "observed": observed_symbols,
            "configured_not_observed": sorted(set(configured_symbols) - set(observed_symbols)),
            "observed_not_configured": sorted(set(observed_symbols) - set(configured_symbols)),
            "duplicates": sorted({symbol for symbol in configured_symbols if configured_symbols.count(symbol) > 1}),
            "simultaneous_long_short": position_conflicts,
        },
        "data_quality": coverage,
        "source_health": source_health,
        "config_audit": config_audit,
    }


def _funding_bundle(bot_key: str, last_n: Optional[int] = None) -> Dict[str, Any]:
    paths = _analytics_paths(bot_key)
    history_rows = _read_jsonl(paths.get("funding_analytics_file", ""), last_n)
    trade_rows = _read_jsonl(paths.get("trade_analytics_file", ""), last_n)
    cfg = CONFIG.get("phase5", {})
    engine = FundingEngineV2(
        windows=cfg.get("baseline_windows", [90, 30, 8]),
        elevated_z=cfg.get("elevated_z", 1.5),
        extreme_z=cfg.get("extreme_z", 2.5),
        min_std=cfg.get("min_std", 1e-8),
    )

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in history_rows:
        symbol = str(row.get("symbol") or "UNKNOWN")
        rate = row.get("funding_rate", row.get("current_funding"))
        if rate is None:
            continue
        enriched = dict(row)
        enriched["funding_rate"] = _safe_float(rate)
        grouped[symbol].append(enriched)

    current: Dict[str, Dict[str, Any]] = {}
    timeline: List[Dict[str, Any]] = []
    class_counts = defaultdict(int)
    for symbol, rows in grouped.items():
        rows.sort(key=lambda row: _safe_float(row.get("ts", row.get("timestamp"))))
        rates = [row["funding_rate"] for row in rows]
        analyses = engine.analyze_series(symbol, rates)
        for row, analysis in zip(rows, analyses):
            point = dict(analysis)
            point.update({
                "ts": row.get("ts", row.get("timestamp")),
                "next_funding_ts": row.get("next_funding_ts"),
                "mark_price": row.get("mark_price"),
            })
            timeline.append(point)
        if analyses:
            latest = dict(analyses[-1])
            latest.update({
                "ts": rows[-1].get("ts", rows[-1].get("timestamp")),
                "next_funding_ts": rows[-1].get("next_funding_ts"),
                "mark_price": rows[-1].get("mark_price"),
            })
            current[symbol] = latest
            class_counts[latest["funding_class"]] += 1

    costs = []
    cost_by_symbol: Dict[str, Dict[str, float]] = {}
    for trade in trade_rows:
        raw_cost = trade.get("funding_cost_usd", trade.get("funding_cost"))
        if raw_cost is None:
            continue
        cost = _safe_float(raw_cost)
        symbol = str(trade.get("symbol") or "UNKNOWN")
        costs.append(cost)
        item = cost_by_symbol.setdefault(symbol, {"trades": 0, "total_cost_usd": 0.0, "avg_cost_usd": 0.0})
        item["trades"] += 1
        item["total_cost_usd"] += cost
    for item in cost_by_symbol.values():
        item["total_cost_usd"] = round(item["total_cost_usd"], 4)
        item["avg_cost_usd"] = round(item["total_cost_usd"] / item["trades"], 4)

    baseline_symbols = cfg.get(
        "baseline_symbols",
        ["BTC/USDT:USDT", "ETH/USDT:USDT", "LINK/USDT:USDT", "XRP/USDT:USDT",
         "SOL/USDT:USDT", "SUI/USDT:USDT", "ADA/USDT:USDT"],
    )
    missing_symbols = [symbol for symbol in baseline_symbols if symbol not in current]
    return {
        "bot": bot_key,
        "enabled": bool(cfg.get("enabled", True)) and bot_key != "alpaca",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "baseline_windows": list(engine.windows),
            "elevated_z": engine.elevated_z,
            "extreme_z": engine.extreme_z,
            "current_observation_excluded": True,
            "execution_independent": True,
        },
        "summary": {
            "symbols": len(current),
            "normal": class_counts["NORMAL"],
            "elevated": class_counts["ELEVATED"],
            "extreme": class_counts["EXTREME"],
            "history_samples": len(timeline),
            "funding_cost_samples": len(costs),
            "total_funding_cost_usd": round(sum(costs), 4),
            "avg_funding_cost_usd": round(sum(costs) / len(costs), 4) if costs else None,
        },
        "current": current,
        "timeline": sorted(timeline, key=lambda row: _safe_float(row.get("ts")))[-1000:],
        "cost_by_symbol": dict(sorted(cost_by_symbol.items())),
        "missing_baseline_symbols": missing_symbols,
    }


def _reason_family(reason: str) -> str:
    r = (reason or "UNKNOWN").upper()
    for k in [f"K{i}" for i in range(1, 10)]:
        if r.startswith(k) or f"_{k}_" in f"_{r}_":
            return k
    if "NEAR" in r or "TP1_REVERSAL" in r:
        return "NEAR_EXIT"
    if "TRAIL" in r:
        return "TRAILING"
    if "BREAKEVEN" in r or r.startswith("BE_"):
        return "BREAKEVEN"
    if "TIMEOUT" in r:
        return "TIMEOUT"
    if "SL_" in r or r == "SL_HIT":
        return "STOP_LOSS"
    if "TP1" in r:
        return "TP1"
    if "TP2" in r:
        return "TP2"
    if "TP3" in r:
        return "TP3"
    return r.split(":", 1)[0][:48]


def _group_trade_stats(rows: List[Dict[str, Any]], field: str) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, Dict[str, float]] = {}
    for row in rows:
        key = str(row.get(field) or "UNKNOWN")
        r = _safe_float(row.get("exit_r"))
        d = grouped.setdefault(key, {"count": 0, "wins": 0, "r_sum": 0.0, "positive": 0.0, "negative": 0.0})
        d["count"] += 1
        d["r_sum"] += r
        if r > 0:
            d["wins"] += 1
            d["positive"] += r
        elif r < 0:
            d["negative"] += abs(r)
    out = {}
    for key, d in grouped.items():
        n = int(d["count"])
        out[key] = {
            "count": n,
            "win_rate": round(d["wins"] / n * 100, 1) if n else 0.0,
            "avg_r": round(d["r_sum"] / n, 3) if n else 0.0,
            "profit_factor": round(d["positive"] / d["negative"], 2) if d["negative"] > 1e-9 else None,
        }
    return out


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "hit", "y"}
    return bool(value)


def _percentile(values: List[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _phase4_enrich_trade(row: Dict[str, Any]) -> Dict[str, Any]:
    """Add backward-compatible exit metrics without changing analytics files."""
    enriched = dict(row)
    exit_r = _safe_float(row.get("exit_r"))
    mfe_r = max(0.0, _safe_float(row.get("mfe_r")))
    mae_r = abs(_safe_float(row.get("mae_r")))

    phase4_cfg = CONFIG.get("phase4", {})
    derive_missing = bool(phase4_cfg.get("derive_missing_exit_metrics", True))

    if row.get("lost_r") is None and derive_missing:
        lost_r = max(0.0, mfe_r - exit_r)
    else:
        lost_r = max(0.0, _safe_float(row.get("lost_r")))

    if row.get("capture_ratio") is None and derive_missing:
        capture_ratio = exit_r / mfe_r if mfe_r > 1e-9 else None
    elif row.get("capture_ratio") is None:
        capture_ratio = None
    else:
        capture_ratio = _safe_float(row.get("capture_ratio"))

    capture_weight = max(0.0, _safe_float(phase4_cfg.get("exit_quality_capture_weight"), .75))
    mae_weight = max(0.0, _safe_float(phase4_cfg.get("exit_quality_mae_weight"), .25))
    weight_total = capture_weight + mae_weight
    if weight_total <= 1e-9:
        capture_weight, mae_weight, weight_total = .75, .25, 1.0
    capture_weight /= weight_total
    mae_weight /= weight_total
    capture_component = max(0.0, min(1.0, capture_ratio or 0.0))
    adverse_component = max(0.0, 1.0 - min(mae_r, 1.0))
    quality_score = 100.0 * (
        capture_weight * capture_component + mae_weight * adverse_component
    )

    enriched.update({
        "lost_r": round(lost_r, 6),
        "capture_ratio": round(capture_ratio, 6) if capture_ratio is not None else None,
        "exit_quality_score": round(quality_score, 2),
        "exit_family": _reason_family(str(row.get("exit_reason") or "UNKNOWN")),
        "exit_subreason": (
            row.get("exit_subreason")
            or row.get("subreason")
            or row.get("reason_detail")
            or "UNSPECIFIED"
        ),
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "exit_r": exit_r,
        "tp1_hit": _truthy(row.get("tp1_hit")),
        "tp2_hit": _truthy(row.get("tp2_hit")),
        "tp3_hit": _truthy(row.get("tp3_hit")),
    })
    return enriched


def _exit_report_bundle(bot_key: str, last_n: Optional[int] = None) -> Dict[str, Any]:
    paths = _analytics_paths(bot_key)
    raw_trades = _read_jsonl(paths.get("trade_analytics_file", ""), last_n)
    trades = [_phase4_enrich_trade(row) for row in raw_trades]
    post_exit = _read_jsonl(paths.get("exit_analytics_file", ""), None)

    reason_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    subreason_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        reason_groups[trade["exit_family"]].append(trade)
        subreason_groups[str(trade["exit_subreason"])].append(trade)

    def exit_group_stats(groups: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
        output: Dict[str, Dict[str, Any]] = {}
        for name, rows in groups.items():
            exits = [_safe_float(x.get("exit_r")) for x in rows]
            mfes = [_safe_float(x.get("mfe_r")) for x in rows]
            maes = [_safe_float(x.get("mae_r")) for x in rows]
            lost = [_safe_float(x.get("lost_r")) for x in rows]
            captures = [
                _safe_float(x.get("capture_ratio"))
                for x in rows if x.get("capture_ratio") is not None
            ]
            qualities = [_safe_float(x.get("exit_quality_score")) for x in rows]
            output[name] = {
                "count": len(rows),
                "win_rate": round(sum(v > 0 for v in exits) / len(rows) * 100, 1),
                "avg_exit_r": round(sum(exits) / len(rows), 3),
                "avg_mfe_r": round(sum(mfes) / len(rows), 3),
                "avg_mae_r": round(sum(maes) / len(rows), 3),
                "avg_lost_r": round(sum(lost) / len(rows), 3),
                "total_lost_r": round(sum(lost), 3),
                "avg_capture_ratio": round(sum(captures) / len(captures), 4) if captures else None,
                "exit_quality_score": round(sum(qualities) / len(rows), 1),
                "tp3_rate": round(sum(x["tp3_hit"] for x in rows) / len(rows) * 100, 1),
            }
        return dict(sorted(output.items(), key=lambda item: (-item[1]["total_lost_r"], item[0])))

    count = len(trades)
    tp1_count = sum(x["tp1_hit"] for x in trades)
    tp2_count = sum(x["tp2_hit"] for x in trades)
    tp3_count = sum(x["tp3_hit"] for x in trades)
    captures = [
        _safe_float(x.get("capture_ratio"))
        for x in trades if x.get("capture_ratio") is not None
    ]
    qualities = [_safe_float(x.get("exit_quality_score")) for x in trades]
    mfe_values = [_safe_float(x.get("mfe_r")) for x in trades]
    mae_values = [_safe_float(x.get("mae_r")) for x in trades]
    lost_values = [_safe_float(x.get("lost_r")) for x in trades]

    shadow_by_bars: Dict[str, List[float]] = defaultdict(list)
    shadow_by_reason: Dict[str, List[float]] = defaultdict(list)
    for row in post_exit:
        if row.get("move_r") is not None:
            move = _safe_float(row.get("move_r"))
        elif row.get("move_pct") is not None:
            move = _safe_float(row.get("move_pct"))
        else:
            continue
        shadow_by_bars[str(int(_safe_float(row.get("bars"), 0)))].append(move)
        shadow_by_reason[_reason_family(str(row.get("reason") or row.get("exit_reason") or "UNKNOWN"))].append(move)

    def shadow_stats(groups: Dict[str, List[float]], numeric_sort: bool = False) -> Dict[str, Dict[str, Any]]:
        items = groups.items()
        if numeric_sort:
            items = sorted(items, key=lambda item: int(item[0]))
        return {
            key: {
                "count": len(vals),
                "avg_move": round(sum(vals) / len(vals), 4),
                "continued_pct": round(sum(v > 0 for v in vals) / len(vals) * 100, 1),
                "reversed_pct": round(sum(v < 0 for v in vals) / len(vals) * 100, 1),
            }
            for key, vals in items
        }

    return {
        "bot": bot_key,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "formula": {
            "lost_r": "max(0, MFE_R - Exit_R) when lost_r is missing",
            "capture_ratio": "Exit_R / MFE_R when capture_ratio is missing and MFE_R > 0",
            "exit_quality_score": (
                f"{round(CONFIG.get('phase4', {}).get('exit_quality_capture_weight', .75) * 100)}% "
                "capture efficiency + "
                f"{round(CONFIG.get('phase4', {}).get('exit_quality_mae_weight', .25) * 100)}% "
                "MAE control, normalized and bounded to 0-100"
            ),
        },
        "summary": {
            "trades": count,
            "avg_exit_r": round(sum(_safe_float(x.get("exit_r")) for x in trades) / count, 3) if count else None,
            "avg_mfe_r": round(sum(mfe_values) / count, 3) if count else None,
            "avg_mae_r": round(sum(mae_values) / count, 3) if count else None,
            "total_lost_r": round(sum(lost_values), 3),
            "avg_lost_r": round(sum(lost_values) / count, 3) if count else None,
            "avg_capture_ratio": round(sum(captures) / len(captures), 4) if captures else None,
            "exit_quality_score": round(sum(qualities) / count, 1) if count else None,
        },
        "tp_funnel": {
            "total": count,
            "tp1": {"count": tp1_count, "rate": round(tp1_count / count * 100, 1) if count else 0.0},
            "tp2": {
                "count": tp2_count,
                "rate": round(tp2_count / count * 100, 1) if count else 0.0,
                "from_previous": round(tp2_count / tp1_count * 100, 1) if tp1_count else 0.0,
            },
            "tp3": {
                "count": tp3_count,
                "rate": round(tp3_count / count * 100, 1) if count else 0.0,
                "from_previous": round(tp3_count / tp2_count * 100, 1) if tp2_count else 0.0,
            },
        },
        "distribution": {
            "mfe_r": {
                "p25": round(_percentile(mfe_values, .25), 3) if mfe_values else None,
                "median": round(_percentile(mfe_values, .50), 3) if mfe_values else None,
                "p75": round(_percentile(mfe_values, .75), 3) if mfe_values else None,
            },
            "mae_r": {
                "p25": round(_percentile(mae_values, .25), 3) if mae_values else None,
                "median": round(_percentile(mae_values, .50), 3) if mae_values else None,
                "p75": round(_percentile(mae_values, .75), 3) if mae_values else None,
            },
            "capture_ratio": {
                "p25": round(_percentile(captures, .25), 4) if captures else None,
                "median": round(_percentile(captures, .50), 4) if captures else None,
                "p75": round(_percentile(captures, .75), 4) if captures else None,
            },
        },
        "by_reason": exit_group_stats(reason_groups),
        "by_subreason": exit_group_stats(subreason_groups),
        "shadow_exit": {
            "sample_count": len(post_exit),
            "by_bars": shadow_stats(shadow_by_bars, numeric_sort=True),
            "by_reason": shadow_stats(shadow_by_reason),
        },
        "trades": trades[-500:],
    }


def _analytics_bundle(bot_key: str, last_n: Optional[int] = None) -> Dict[str, Any]:
    paths = _analytics_paths(bot_key)
    trades = [_phase4_enrich_trade(row) for row in _read_jsonl(paths.get("trade_analytics_file", ""), last_n)]
    rejected = _read_jsonl(paths.get("rejected_analytics_file", ""), last_n)
    post_exit = _read_jsonl(paths.get("exit_analytics_file", ""), None)

    # Exit / opportunity / capture
    by_reason: Dict[str, Dict[str, float]] = {}
    captures = []
    lost_values = []
    for row in trades:
        family = _reason_family(row.get("exit_reason", "UNKNOWN"))
        d = by_reason.setdefault(family, {"count": 0, "exit_r": 0.0, "lost_r": 0.0, "wins": 0, "capture_sum": 0.0, "capture_n": 0})
        exit_r = _safe_float(row.get("exit_r"))
        lost_r = _safe_float(row.get("lost_r"))
        d["count"] += 1
        d["exit_r"] += exit_r
        d["lost_r"] += lost_r
        d["wins"] += int(exit_r > 0)
        lost_values.append(lost_r)
        if row.get("capture_ratio") is not None:
            cap = _safe_float(row.get("capture_ratio"))
            captures.append(cap)
            d["capture_sum"] += cap
            d["capture_n"] += 1

    exit_stats = {}
    for reason, d in by_reason.items():
        n = max(1, int(d["count"]))
        exit_stats[reason] = {
            "count": int(d["count"]),
            "win_rate": round(d["wins"] / n * 100, 1),
            "avg_exit_r": round(d["exit_r"] / n, 3),
            "avg_lost_r": round(d["lost_r"] / n, 3),
            "avg_capture_ratio": round(d["capture_sum"] / d["capture_n"], 4) if d["capture_n"] else None,
        }

    # Counter trend
    counter, aligned = [], []
    for row in trades:
        regime = str(row.get("regime") or "").upper()
        side = str(row.get("signal") or "").upper()
        is_counter = (
            (regime in ("TREND_UP", "STRONG_BULL", "EXTREME_BULL") and side == "SHORT")
            or (regime in ("TREND_DOWN", "STRONG_BEAR", "EXTREME_BEAR") and side == "LONG")
        )
        (counter if is_counter else aligned).append(row)

    def row_stats(group):
        if not group:
            return {"count": 0, "win_rate": 0.0, "avg_r": 0.0, "profit_factor": None}
        vals = [_safe_float(x.get("exit_r")) for x in group]
        pos = sum(x for x in vals if x > 0)
        neg = abs(sum(x for x in vals if x < 0))
        return {
            "count": len(vals),
            "win_rate": round(sum(x > 0 for x in vals) / len(vals) * 100, 1),
            "avg_r": round(sum(vals) / len(vals), 3),
            "profit_factor": round(pos / neg, 2) if neg > 1e-9 else None,
        }

    # Rejected
    rejected_reason, rejected_symbol, rejected_regime = defaultdict(int), defaultdict(int), defaultdict(int)
    for row in rejected:
        rejected_reason[str(row.get("reason") or "UNKNOWN").split(":", 1)[0]] += 1
        rejected_symbol[str(row.get("symbol") or "UNKNOWN")] += 1
        rejected_regime[str(row.get("regime") or "UNKNOWN")] += 1

    # Near exit checkpoints
    near_checkpoint = defaultdict(list)
    for row in post_exit:
        reason = str(row.get("reason") or "").upper()
        if "NEAR" in reason or "TP1_REVERSAL" in reason:
            if row.get("move_pct") is not None:
                near_checkpoint[str(int(row.get("bars", 0)))].append(_safe_float(row.get("move_pct")))

    # Equity and drawdown in R units
    equity_curve = []
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for idx, row in enumerate(sorted(trades, key=lambda r: _safe_float(r.get("closed_at")))):
        equity += _safe_float(row.get("exit_r"))
        peak = max(peak, equity)
        dd = equity - peak
        max_dd = min(max_dd, dd)
        ts = row.get("closed_at")
        try:
            label = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except Exception:
            label = str(idx + 1)
        equity_curve.append({"x": label, "equity_r": round(equity, 3), "drawdown_r": round(dd, 3)})

    return {
        "bot": bot_key,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_trades": len(trades),
        "regime": _group_trade_stats(trades, "regime"),
        "coin": _group_trade_stats(trades, "symbol"),
        "exit": exit_stats,
        "opportunity_lost": {
            "count": len(lost_values),
            "avg_lost_r": round(sum(lost_values) / len(lost_values), 3) if lost_values else None,
            "total_lost_r": round(sum(lost_values), 3),
        },
        "capture_ratio": {
            "count": len(captures),
            "avg": round(sum(captures) / len(captures), 4) if captures else None,
            "above_70pct": sum(x >= 0.70 for x in captures),
            "negative": sum(x < 0 for x in captures),
        },
        "counter_trend": {
            "share_pct": round(len(counter) / len(trades) * 100, 1) if trades else 0.0,
            "counter": row_stats(counter),
            "aligned": row_stats(aligned),
        },
        "rejected": {
            "total": len(rejected),
            "by_reason": dict(sorted(rejected_reason.items(), key=lambda kv: -kv[1])),
            "by_symbol": dict(sorted(rejected_symbol.items(), key=lambda kv: -kv[1])),
            "by_regime": dict(sorted(rejected_regime.items(), key=lambda kv: -kv[1])),
        },
        "smart_exit": {k: v for k, v in exit_stats.items() if re.fullmatch(r"K[1-9]", k)},
        "near_exit": {
            "stats": exit_stats.get("NEAR_EXIT", {}),
            "checkpoints": {
                bars: {
                    "count": len(vals),
                    "avg_move_pct": round(sum(vals) / len(vals), 4),
                    "continued_pct": round(sum(v > 0 for v in vals) / len(vals) * 100, 1),
                }
                for bars, vals in sorted(near_checkpoint.items(), key=lambda kv: int(kv[0]))
            },
        },
        "equity": {
            "curve": equity_curve,
            "net_r": round(equity, 3),
            "max_drawdown_r": round(max_dd, 3),
        },
        "trades": trades[-500:],
    }


@app.route("/analytics")
def analytics_page():
    return render_template(
        "analytics.html",
        bots=[{"key": key, "label": m["label"]} for key, m in registry.markets.items()],
        refresh_seconds=CONFIG.get("analytics_refresh_seconds", 30),
    )


@app.route("/exit_report")
def exit_report_page():
    return render_template(
        "exit_report.html",
        bots=[{"key": key, "label": m["label"]} for key, m in registry.markets.items()],
        refresh_seconds=CONFIG.get("phase4", {}).get(
            "exit_report_refresh_seconds",
            CONFIG.get("analytics_refresh_seconds", 30),
        ),
    )


@app.route("/funding")
def funding_page():
    return render_template(
        "funding.html",
        bots=[{"key": key, "label": m["label"]} for key, m in registry.markets.items()],
        refresh_seconds=CONFIG.get("phase5", {}).get(
            "funding_report_refresh_seconds",
            CONFIG.get("analytics_refresh_seconds", 30),
        ),
    )


@app.route("/diagnostics")
def diagnostics_page():
    return render_template(
        "diagnostics.html",
        bots=[{"key": key, "label": m["label"]} for key, m in registry.markets.items()],
        refresh_seconds=CONFIG.get("phase6", {}).get(
            "diagnostics_refresh_seconds",
            CONFIG.get("analytics_refresh_seconds", 30),
        ),
    )


@app.route("/api/diagnostics/<bot_key>")
def api_diagnostics(bot_key: str):
    if bot_key not in registry.markets:
        return jsonify({"status": "error", "message": "Bot not found"}), 404
    raw = request.args.get("last_n", "")
    try:
        last_n = int(raw) if raw else None
    except ValueError:
        last_n = None
    return jsonify({"status": "ok", "data": _diagnostics_bundle(bot_key, last_n)})


@app.route("/api/health")
def api_health():
    markets = {}
    for key in registry.markets:
        diagnostics = _diagnostics_bundle(key, 100)
        markets[key] = {
            "config_status": diagnostics["config_audit"]["status"],
            "sources_ok": sum(item["status"] == "OK" for item in diagnostics["source_health"]),
            "sources_total": len(diagnostics["source_health"]),
            "regime_violations": diagnostics["summary"]["regime_violations"],
            "counter_trend_violations": diagnostics["summary"]["counter_trend_violations"],
            "position_side_conflicts": diagnostics["summary"]["position_side_conflicts"],
        }
    overall = "OK" if markets and all(item["config_status"] == "PASS" for item in markets.values()) else "DEGRADED"
    return jsonify({
        "status": overall,
        "service": "quantum-terminal-pro",
        "phase": 6,
        "read_only": not bool(CONFIG.get("phase2", {}).get("manual_actions_enabled", False)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "markets": markets,
    })


@app.route("/api/funding/<bot_key>")
def api_funding(bot_key: str):
    if bot_key not in registry.markets:
        return jsonify({"status": "error", "message": "Bot not found"}), 404
    raw = request.args.get("last_n", "")
    try:
        last_n = int(raw) if raw else None
    except ValueError:
        last_n = None
    return jsonify({"status": "ok", "data": _funding_bundle(bot_key, last_n)})


@app.route("/api/funding/<bot_key>/export.csv")
def api_funding_export(bot_key: str):
    if bot_key not in registry.markets:
        abort(404)
    rows = _funding_bundle(bot_key).get("timeline", [])
    output = io.StringIO()
    fields = [
        "ts", "symbol", "current_funding", "baseline_mean", "baseline_std",
        "z_score", "normalized", "funding_class", "baseline_window",
        "sample_count", "crowding", "next_funding_ts", "mark_price",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={bot_key}_funding_analytics.csv"},
    )


@app.route("/api/exit-report/<bot_key>")
def api_exit_report(bot_key: str):
    if bot_key not in registry.markets:
        return jsonify({"status": "error", "message": "Bot not found"}), 404
    raw = request.args.get("last_n", "")
    try:
        last_n = int(raw) if raw else None
    except ValueError:
        last_n = None
    return jsonify({"status": "ok", "data": _exit_report_bundle(bot_key, last_n)})


@app.route("/api/exit-report/<bot_key>/export.csv")
def api_exit_report_export(bot_key: str):
    if bot_key not in registry.markets:
        abort(404)
    rows = _exit_report_bundle(bot_key).get("trades", [])
    output = io.StringIO()
    fields = [
        "trade_id", "symbol", "signal", "regime", "exit_reason", "exit_family",
        "exit_subreason", "mfe_r", "mae_r", "exit_r", "lost_r", "capture_ratio",
        "exit_quality_score", "tp1_hit", "tp2_hit", "tp3_hit", "bars_held",
        "opened_at", "closed_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={bot_key}_exit_report.csv"},
    )


@app.route("/api/analytics/<bot_key>")
def api_analytics(bot_key: str):
    if bot_key not in registry.markets:
        return jsonify({"status": "error", "message": "Bot not found"}), 404
    raw = request.args.get("last_n", "")
    try:
        last_n = int(raw) if raw else None
    except ValueError:
        last_n = None
    return jsonify({"status": "ok", "data": _analytics_bundle(bot_key, last_n)})


@app.route("/api/analytics/<bot_key>/export.csv")
def api_analytics_export(bot_key: str):
    if bot_key not in registry.markets:
        abort(404)
    rows = _analytics_bundle(bot_key).get("trades", [])
    output = io.StringIO()
    fields = [
        "trade_id", "symbol", "signal", "regime", "confluence", "entry",
        "exit_price", "exit_reason", "mfe_r", "mae_r", "exit_r", "lost_r",
        "capture_ratio", "tp1_hit", "tp2_hit", "tp3_hit", "trade_duration_sec",
        "bars_held", "opened_at", "closed_at"
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={bot_key}_trade_analytics.csv"},
    )


@app.route("/api/analytics/<bot_key>/export.json")
def api_analytics_export_json(bot_key: str):
    if bot_key not in registry.markets:
        abort(404)
    payload = _analytics_bundle(bot_key)
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={bot_key}_analytics.json"},
    )



# =============================================================================
# PAGE ROUTES
# =============================================================================
@app.route("/")
def index():
    markets_ctx = []
    for key, m in registry.markets.items():
        markets_ctx.append({
            "key": key,
            "label": m["label"],
            "symbols": [{"symbol": s, "slug": m["slug_map"][s]} for s in m["symbols"]],
        })
    return render_template(
        "index.html",
        markets=markets_ctx,
        refresh_seconds=CONFIG.get("refresh_seconds", 15),
    )


@app.route("/chart/<market_key>/<slug>")
def chart_page(market_key: str, slug: str):
    m, symbol = registry.resolve(market_key, slug)
    if not m or not symbol:
        abort(404)
    return render_template(
        "chart.html",
        market_key=market_key,
        market_label=m["label"],
        symbol=symbol,
        slug=slug,
        timeframe=PRIMARY_TF,
        timeframes=CONFIG.get("timeframes", [PRIMARY_TF]),
        refresh_seconds=CONFIG.get("refresh_seconds", 15),
    )


# =============================================================================
# API ROUTES
# =============================================================================
@app.route("/api/ticker")
def api_ticker():
    """Lightweight summary data for the homepage ticker tape + symbol cards."""
    out: List[Dict[str, Any]] = []
    for market_key, m in registry.markets.items():
        for symbol in m["symbols"]:
            slug = m["slug_map"][symbol]

            def _fetch(mk=market_key, sym=symbol):
                df = m["provider"].get_ohlcv(sym, PRIMARY_TF, limit=60)
                if df is None or len(df) < 50:
                    return None
                df = calculate_indicators(df)
                regime = detect_regime(df, REGIME_THRESHOLDS)
                last_c = float(df["close"].iloc[-1])
                prev_c = float(df["close"].iloc[-2])
                return {"price": last_c, "chg": ((last_c - prev_c) / prev_c) * 100 if prev_c else 0.0, "regime": regime}

            bundle = cache.get_or_set(f"ticker:{market_key}:{symbol}", _fetch)
            if bundle is None:
                out.append({
                    "market": market_key, "symbol": symbol, "slug": slug,
                    "status": "error",
                })
                continue

            positions = load_positions(m["positions_file"])
            has_position = symbol in positions

            out.append({
                "market": market_key,
                "symbol": symbol,
                "slug": slug,
                "status": "ok",
                "price": round(bundle["price"], 6),
                "change_pct": round(bundle["chg"], 2),
                "regime": bundle["regime"],
                "regime_label": REGIME_LABELS.get(bundle["regime"], bundle["regime"]),
                "regime_color": REGIME_COLORS.get(bundle["regime"], "#8B8F98"),
                "has_position": has_position,
            })
    return jsonify({"items": out, "server_time": datetime.now(timezone.utc).isoformat()})


@app.route("/api/positions_summary")
def api_positions_summary():
    """Returns every open position across both bots in a single list."""
    out: List[Dict[str, Any]] = []
    for market_key, m in registry.markets.items():
        positions = load_positions(m["positions_file"])
        for symbol, pos in positions.items():

            def _price(mk=market_key, sym=symbol):
                return m["provider"].get_last_price(sym)

            live_price = cache.get_or_set(f"price:{market_key}:{symbol}", _price)
            payload = _position_payload(pos, live_price)
            payload.update({
                "market": market_key,
                "market_label": m["label"],
                "symbol": symbol,
                "slug": m["slug_map"].get(symbol, _slugify(symbol)),
            })
            out.append(payload)
    return jsonify({"items": out, "server_time": datetime.now(timezone.utc).isoformat()})


@app.route("/api/chart/<market_key>/<slug>")
def api_chart(market_key: str, slug: str):
    m, symbol = registry.resolve(market_key, slug)
    if not m or not symbol:
        return jsonify({"status": "error", "message": "Symbol not found"}), 404
    timeframe = request.args.get("timeframe", PRIMARY_TF)
    return jsonify(_build_chart_payload(market_key, symbol, timeframe=timeframe))


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "markets": list(registry.markets.keys())})


if __name__ == "__main__":
    port = CONFIG.get("port", 8050)
    logger.info(f"Starting dashboard → http://0.0.0.0:{port}  (markets: {list(registry.markets.keys())})")
    app.run(host="0.0.0.0", port=port, threaded=True)
