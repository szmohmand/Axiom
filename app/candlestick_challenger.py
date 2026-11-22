"""Read-only, falsifiable candlestick forecast challenger for AXIOM.

Candlestick concepts are inspired by Steve Nison's Japanese Candlestick
Charting Techniques (2nd ed.). This is original heuristic code, NOT a
trained model or a demonstrated trading edge.

The candidate uses the EXISTING independent BTC ensemble forecast as its
baseline and makes a small, bounded change only when a completed-candle
pattern has corroboration from prior support/resistance or real volume.
It never votes in the active ensemble or places paper/real trades.
"""
from __future__ import annotations

import math
from typing import Any


def unavailable(reason: str) -> dict[str, Any]:
    return {
        "available": False, "status": "SHADOW_UNAVAILABLE",
        "name": "nison_candlestick_challenger",
        "prob_above": None, "side": "WAIT", "delta": None,
        "reference_ensemble_prob": None,
        "trigger": None, "reason": reason,
        "research_only": True, "validated": False,
        "independent": False, "votes_in_ensemble": False,
        "can_trigger_paper_or_orders": False,
    }


# Predeclared hypotheses, not book-derived measured win rates. A capped
# 1.5-3.5 percentage-point tilt makes an honest candidate for paired scoring.
# Candles without contextual corroboration are observations, not forecasts.
_PATTERNS = {
    "HAMMER": (1, 0.025, "PRIOR_SUPPORT"),
    "BULLISH_ENGULFING": (1, 0.035, "PRIOR_SUPPORT"),
    "SHOOTING_STAR": (-1, 0.025, "PRIOR_RESISTANCE"),
    "BEARISH_ENGULFING": (-1, 0.035, "PRIOR_RESISTANCE"),
}


def derive_candlestick_challenger(context: dict | None,
                                  ensemble: dict | None) -> dict[str, Any]:
    """Return a shadow probability only on corroborated completed-bar signals.

    The underlying consensus, Kalshi prices, real trades and policy gates are
    never edited. No target, future candle or result is read by this function.
    Doji alone and unconfirmed hanging-man/inverted-hammer formations never
    imply an up/down prediction.
    """
    if not isinstance(context, dict) or not context.get("available"):
        return unavailable("No fresh, validated, fully closed candle context")
    if not isinstance(ensemble, dict) or not ensemble.get("available"):
        return unavailable("Independent AXIOM ensemble unavailable")
    raw = ensemble.get("prob_above")
    if isinstance(raw, bool):
        return unavailable("Invalid ensemble probability")
    try:
        baseline = float(raw)
    except (TypeError, ValueError, OverflowError):
        return unavailable("Invalid ensemble probability")
    if not math.isfinite(baseline) or not 0 < baseline < 1:
        return unavailable("Invalid ensemble probability")
    events = context.get("formations")
    if not isinstance(events, list):
        return unavailable("Malformed candle patterns")

    candidates = []
    for event in events:
        if not isinstance(event, dict):
            continue
        name = event.get("name")
        tags = event.get("confluence", [])
        if not isinstance(tags, list):
            continue
        corroboration = set(t for t in tags if isinstance(t, str))
        if name in _PATTERNS:
            direction, magnitude, level = _PATTERNS[name]
            if level in corroboration or "RELATIVE_VOLUME_SPIKE" in corroboration:
                candidates.append((direction, magnitude, name))
        elif name == "LONG_BODY_WITH_TREND" and "RELATIVE_VOLUME_SPIKE" in corroboration:
            trend = context.get("prior_trend")
            if trend in ("UP", "DOWN"):
                candidates.append((1 if trend == "UP" else -1, 0.015, name))

    if not candidates:
        return unavailable("No corroborated candlestick forecast hypothesis")
    if len({direction for direction, _, _ in candidates}) != 1:
        return unavailable("Conflicting bullish and bearish candle warnings")
    direction, magnitude, trigger = max(candidates, key=lambda x: x[1])
    shift = direction * min(0.035, magnitude)
    p = min(0.995, max(0.005, baseline + shift))
    if abs(p - baseline) < 1e-9:
        return unavailable("Forecast already at probability cap")

    return {
        "available": True, "status": "SHADOW_UNVALIDATED",
        "name": "nison_candlestick_challenger",
        "prob_above": round(p, 5),
        "side": "ABOVE" if p > 0.5 else "BELOW" if p < 0.5 else "WAIT",
        "delta": round(p - baseline, 5),
        "reference_ensemble_prob": round(baseline, 5),
        "trigger": trigger,
        "reason": "Corroborated completed-candle heuristic, not verified alpha",
        "research_only": True, "validated": False,
        "independent": False, "votes_in_ensemble": False,
        "can_trigger_paper_or_orders": False,
    }
