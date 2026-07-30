#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_providers.py
──────────────────────────────────────────────────────────────────────────
Read-only data layer for the Quantum SMC Engine / Alpaca SMC bots' live
dashboard.

This file is fully independent from the bots' core codebase — it does not
import quant.py, does not open an exchange session, and never places or
closes a trade. It only:
  1) fetches OHLCV candles from the exchange (public endpoints),
  2) computes indicators (EMA/RSI/ATR/ADX/BB) and the market regime,
  3) reads the positions_state.json file that the bots already write.

This separation is deliberate: the bots' internal logic (confluence
scoring, sweep/OB/FVG filters, risk management) changes quickly, and
keeping the dashboard in lockstep with it would be fragile. The dashboard
only shows "price + structure + regime + the bot's recorded open
position" — it never makes an entry decision.
"""

import os
import json
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("dashboard")

# =============================================================================
# CONFIG
# =============================================================================
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_config.json")


def load_config() -> Dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# INDICATORS (same formulas as the bots — EMA/RSI/ATR/ADX/BB)
# =============================================================================
EMA_PERIODS = [9, 21, 50, 200]
RSI_PERIOD = 14
ATR_PERIOD = 14


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Same formulas as calculate_indicators_vectorized in the bots."""
    if df is None or len(df) < 5:
        return df
    df = df.copy()

    for p in EMA_PERIODS:
        df[f"ema_{p}"] = df["close"].ewm(span=p, adjust=False).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
    df["rsi"] = 100 - 100 / (1 + gain / (loss + 1e-10))

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    hl = df["high"] - df["low"]
    hpc = (df["high"] - df["close"].shift()).abs()
    lpc = (df["low"] - df["close"].shift()).abs()
    df["tr"] = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(ATR_PERIOD).mean()

    hdiff = df["high"].diff()
    ldiff = df["low"].diff()
    df["plus_dm"] = np.where((hdiff > 0) & (hdiff > -ldiff), hdiff, 0.0)
    df["minus_dm"] = np.where((ldiff < 0) & (-ldiff > hdiff), -ldiff, 0.0)
    atr14 = df["atr"] + 1e-10
    df["plus_di"] = 100 * df["plus_dm"].rolling(14).mean() / atr14
    df["minus_di"] = 100 * df["minus_dm"].rolling(14).mean() / atr14
    di_sum = df["plus_di"] + df["minus_di"] + 1e-10
    df["dx"] = 100 * (df["plus_di"] - df["minus_di"]).abs() / di_sum
    df["adx"] = df["dx"].rolling(14).mean()

    df["bb_mid"] = df["close"].rolling(20).mean()
    bb_std = df["close"].rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2 * bb_std
    df["bb_lower"] = df["bb_mid"] - 2 * bb_std
    df["vol_sma"] = df["volume"].rolling(20).mean()

    return df


# =============================================================================
# REGIME DETECTION (same thresholds as the bots' detect_market_regime: 12/18/25/35)
# =============================================================================
REGIME_COLORS = {
    "STRONG_BULL": "#4FAE7A",
    "TREND_UP": "#7BC79E",
    "NEUTRAL": "#8B8F98",
    "RANGE": "#5B8FBF",
    "TREND_DOWN": "#E08A78",
    "STRONG_BEAR": "#D5654F",
    "STRONG": "#E8A33D",
    "CHOP": "#5A5F6A",
    "SHOCK": "#C43D3D",
}

REGIME_LABELS = {
    "STRONG_BULL": "STRONG BULL",
    "TREND_UP": "TREND UP",
    "NEUTRAL": "NEUTRAL",
    "RANGE": "RANGE",
    "TREND_DOWN": "TREND DOWN",
    "STRONG_BEAR": "STRONG BEAR",
    "STRONG": "STRONG (DIRECTIONLESS)",
    "CHOP": "CHOP",
    "SHOCK": "SHOCK",
}


def detect_regime(df: pd.DataFrame, thresholds: Dict[str, float]) -> str:
    """Same ADX/EMA logic as detect_market_regime in the bots (SHOCK is
    excluded — this is visualization only, no hysteresis is applied)."""
    if df is None or len(df) < 50:
        return "NEUTRAL"
    last = df.iloc[-1]
    adx = float(last.get("adx", 0) or 0)
    e9 = float(last.get("ema_9", 0) or 0)
    e21 = float(last.get("ema_21", 0) or 0)
    e50 = float(last.get("ema_50", 0) or 0)
    e200 = float(last.get("ema_200", 0) or 0)
    bb_upper = float(last.get("bb_upper", 0) or 0)
    bb_lower = float(last.get("bb_lower", 0) or 0)
    bb_mid = float(last.get("bb_mid", 1) or 1)
    bb_width = (bb_upper - bb_lower) / (bb_mid + 1e-10)

    adx_chop = thresholds.get("adx_chop", 12)
    adx_range = thresholds.get("adx_range", 18)
    adx_neutral = thresholds.get("adx_neutral", 25)
    adx_strong = thresholds.get("adx_strong", 35)

    if adx < adx_chop:
        return "CHOP"
    if adx < adx_range:
        return "RANGE" if bb_width < 0.035 else "NEUTRAL"
    if adx < adx_neutral:
        return "NEUTRAL"
    if adx < adx_strong:
        if e9 > e21 > e50:
            return "TREND_UP"
        if e9 < e21 < e50:
            return "TREND_DOWN"
        return "NEUTRAL"
    # adx >= adx_strong
    if e9 > e21 > e50 > e200:
        return "STRONG_BULL"
    if e9 < e21 < e50 < e200:
        return "STRONG_BEAR"
    return "STRONG"


# =============================================================================
# SIMPLE STRUCTURE (BOS/CHOCH) MARKERS — visualization only
# =============================================================================
def detect_structure_markers(df: pd.DataFrame, lookback: int = 30, min_dist: int = 2) -> List[Dict]:
    """Simplified swing-break detection used to draw small BOS/CHOCH
    triangles on the chart. The displacement/volume filters from the bots'
    entry engine are NOT applied here — this is a readability aid for
    market structure, not a trading signal."""
    markers: List[Dict] = []
    if df is None or len(df) < lookback + 5:
        return markers

    n = len(df)
    swing_highs, swing_lows = [], []
    for i in range(min_dist, n - min_dist):
        window_h = df["high"].iloc[i - min_dist:i + min_dist + 1]
        window_l = df["low"].iloc[i - min_dist:i + min_dist + 1]
        if df["high"].iloc[i] == window_h.max():
            swing_highs.append((i, df["high"].iloc[i]))
        if df["low"].iloc[i] == window_l.min():
            swing_lows.append((i, df["low"].iloc[i]))

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return markers

    for idx in range(max(2, n - lookback), n):
        close = df["close"].iloc[idx]
        prior_highs = [h for i, h in swing_highs if i < idx]
        prior_lows = [l for i, l in swing_lows if i < idx]
        if not prior_highs or not prior_lows:
            continue
        last_sh = prior_highs[-1]
        last_sl = prior_lows[-1]
        if close > last_sh:
            markers.append({"idx": idx, "type": "BOS", "side": "LONG", "level": float(last_sh)})
        elif close < last_sl:
            markers.append({"idx": idx, "type": "BOS", "side": "SHORT", "level": float(last_sl)})

    # collapse consecutive markers in the same direction (keep only the first)
    deduped: List[Dict] = []
    last_side = None
    for m in markers:
        if m["side"] != last_side:
            deduped.append(m)
            last_side = m["side"]
    return deduped[-6:]


# =============================================================================
# POSITION STATE READER (positions_state.json)
# =============================================================================
def load_positions(path: str) -> Dict[str, Dict]:
    """Reads the file written by the bot's save_positions_state(). Tolerant
    of a momentarily malformed JSON, since the bot may be writing to this
    file at the exact same instant."""
    try:
        if not path or not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    except Exception as e:
        logger.warning(f"load_positions {path}: {e}")
        return {}


# =============================================================================
# TIMEFRAME HELPER
# =============================================================================
def timeframe_to_minutes(tf: str) -> int:
    unit = tf[-1]
    n = int(tf[:-1])
    return {"m": n, "h": n * 60, "d": n * 1440}.get(unit, 15)


# =============================================================================
# CRYPTO PROVIDER (ccxt, public OHLCV, no credentials required)
# =============================================================================
class CryptoProvider:
    def __init__(self, exchange_id: str = "okx", sandbox_mode: bool = False, default_type: str = "swap"):
        import ccxt
        self._ccxt = ccxt
        exchange_cls = getattr(ccxt, exchange_id, None)
        if exchange_cls is None:
            raise ValueError(f"Unsupported ccxt exchange: {exchange_id}")
        options = {"defaultType": default_type} if default_type else {}
        self.exchange = exchange_cls({
            "enableRateLimit": True,
            "rateLimit": 150,
            "options": options,
        })
        if sandbox_mode:
            self.exchange.set_sandbox_mode(True)
        self._lock = threading.Lock()
        self._markets_loaded = False

    def _ensure_markets(self):
        if not self._markets_loaded:
            with self._lock:
                if not self._markets_loaded:
                    self.exchange.load_markets()
                    self._markets_loaded = True

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> Optional[pd.DataFrame]:
        try:
            self._ensure_markets()
            with self._lock:
                raw = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not raw or len(raw) < 5:
                return None
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            return df
        except Exception as e:
            logger.warning(f"CryptoProvider.get_ohlcv {symbol} {timeframe}: {e}")
            return None

    def get_last_price(self, symbol: str) -> Optional[float]:
        try:
            with self._lock:
                ticker = self.exchange.fetch_ticker(symbol)
            return float(ticker.get("last") or ticker.get("close") or 0) or None
        except Exception as e:
            logger.warning(f"CryptoProvider.get_last_price {symbol}: {e}")
            return None


# =============================================================================
# STOCK PROVIDER (Alpaca — requires a market-data API key/secret)
# =============================================================================
class StockProvider:
    _TF_MAP = {
        "1m": (1, "Minute"), "3m": (3, "Minute"), "5m": (5, "Minute"),
        "15m": (15, "Minute"), "30m": (30, "Minute"),
        "1h": (1, "Hour"), "4h": (4, "Hour"), "1d": (1, "Day"),
    }

    def __init__(self, api_key: str, api_secret: str):
        from alpaca.data.historical import StockHistoricalDataClient
        self._client = StockHistoricalDataClient(api_key=api_key, secret_key=api_secret)

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> Optional[pd.DataFrame]:
        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
            from datetime import timedelta

            amount, unit_name = self._TF_MAP.get(timeframe, (15, "Minute"))
            unit = getattr(TimeFrameUnit, unit_name)

            mins = timeframe_to_minutes(timeframe)
            lookback_days = max(int(limit * mins / 390) + 6, 10)  # ~390 min/day for a regular session
            start_dt = datetime.now(timezone.utc) - timedelta(days=lookback_days)

            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame(amount=amount, unit=unit),
                start=start_dt,
                limit=10000,
            )
            bars = self._client.get_stock_bars(req)
            df = bars.df
            if df is None or df.empty:
                return None
            if isinstance(df.index, pd.MultiIndex):
                df = df.droplevel(0)
            df = df.reset_index()
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            if len(df) > limit:
                df = df.iloc[-limit:]
            return df[["timestamp", "open", "high", "low", "close", "volume"]]
        except Exception as e:
            logger.warning(f"StockProvider.get_ohlcv {symbol} {timeframe}: {e}")
            return None

    def get_last_price(self, symbol: str) -> Optional[float]:
        try:
            from alpaca.data.requests import StockLatestTradeRequest
            req = StockLatestTradeRequest(symbol_or_symbols=symbol)
            trades = self._client.get_stock_latest_trade(req)
            trade = trades.get(symbol)
            return float(trade.price) if trade is not None else None
        except Exception as e:
            logger.warning(f"StockProvider.get_last_price {symbol}: {e}")
            return None


# =============================================================================
# LIGHTWEIGHT TTL CACHE (so every open tab doesn't hammer the exchange)
# =============================================================================
class TTLCache:
    def __init__(self, ttl_seconds: float = 10.0):
        self._ttl = ttl_seconds
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: str, factory):
        with self._lock:
            hit = self._store.get(key)
            if hit and (time.time() - hit[0]) < self._ttl:
                return hit[1]
        value = factory()
        with self._lock:
            self._store[key] = (time.time(), value)
        return value
