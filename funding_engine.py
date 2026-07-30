#!/usr/bin/env python3
"""Funding Engine v2 — symbol-normalized, execution-independent analytics.

This module does not fetch funding, place orders, calculate charged funding,
or alter K7. Feed it the rates already produced by the bot.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Dict, Iterable, List, Optional


class FundingEngineV2:
    def __init__(
        self,
        windows: Iterable[int] = (90, 30, 8),
        elevated_z: float = 1.5,
        extreme_z: float = 2.5,
        min_std: float = 1e-8,
    ):
        self.windows = tuple(sorted({max(2, int(w)) for w in windows}, reverse=True))
        self.elevated_z = float(elevated_z)
        self.extreme_z = float(extreme_z)
        self.min_std = max(float(min_std), 1e-12)

    def _select_baseline(self, history: List[float]) -> tuple[List[float], int]:
        for window in self.windows:
            if len(history) >= window:
                return history[-window:], window
        if len(history) >= 2:
            return history, len(history)
        return history, len(history)

    def analyze(
        self,
        symbol: str,
        current_rate: float,
        historical_rates: Iterable[float],
        side: Optional[str] = None,
    ) -> Dict[str, Any]:
        clean = []
        for value in historical_rates:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                clean.append(number)
        baseline, window = self._select_baseline(clean)
        mean = statistics.fmean(baseline) if baseline else 0.0
        std = statistics.pstdev(baseline) if len(baseline) >= 2 else 0.0
        rate = float(current_rate)
        z_score = (rate - mean) / max(std, self.min_std) if baseline else 0.0
        abs_z = abs(z_score)
        if abs_z >= self.extreme_z:
            funding_class = "EXTREME"
        elif abs_z >= self.elevated_z:
            funding_class = "ELEVATED"
        else:
            funding_class = "NORMAL"

        crowding = "LONGS_PAY" if rate > 0 else "SHORTS_PAY" if rate < 0 else "BALANCED"
        side_upper = str(side or "").upper()
        adverse = (
            (side_upper == "LONG" and rate > 0)
            or (side_upper == "SHORT" and rate < 0)
        )
        favorable = (
            (side_upper == "LONG" and rate < 0)
            or (side_upper == "SHORT" and rate > 0)
        )
        if not side_upper:
            side_effect = "UNSPECIFIED"
        elif adverse:
            side_effect = "ADVERSE"
        elif favorable:
            side_effect = "FAVORABLE"
        else:
            side_effect = "NEUTRAL"

        return {
            "symbol": symbol,
            "current_funding": rate,
            "baseline_mean": mean,
            "baseline_std": std,
            "z_score": z_score,
            "normalized": z_score,
            "funding_class": funding_class,
            "baseline_window": window,
            "sample_count": len(clean),
            "crowding": crowding,
            "side": side_upper or None,
            "side_effect": side_effect,
        }

    def analyze_series(self, symbol: str, rates: Iterable[float]) -> List[Dict[str, Any]]:
        clean = []
        for value in rates:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                clean.append(number)
        output: List[Dict[str, Any]] = []
        for index, rate in enumerate(clean):
            # Current observation is excluded from its own baseline.
            output.append(self.analyze(symbol, rate, clean[:index]))
        return output


def get_funding_analytics(
    symbol: str,
    current_funding: float,
    funding_history: Iterable[float],
    side: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Small integration wrapper for the existing bot.

    Keep get_cached_funding_rate(), calculate_funding_cost(), and K7 unchanged;
    call this only after the current rate and history are already available.
    """
    cfg = config or {}
    engine = FundingEngineV2(
        windows=cfg.get("windows", (90, 30, 8)),
        elevated_z=cfg.get("elevated_z", 1.5),
        extreme_z=cfg.get("extreme_z", 2.5),
        min_std=cfg.get("min_std", 1e-8),
    )
    return engine.analyze(symbol, current_funding, funding_history, side=side)
