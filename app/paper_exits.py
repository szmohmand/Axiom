"""Phase 3: depth-backed, one-contract paper exits; never sends real orders."""
from __future__ import annotations

import math

from .orderbook import current_book, sweep

BRTI_SOURCE = "cfbenchmarks_brti_authenticated_live"


def _number(value):
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if math.isfinite(v) else None


def _invalidated(position, brti, candles, now):
    rule = position.get("invalidation_rule")
    if not isinstance(rule, dict):
        return False
    if not isinstance(brti, dict) or brti.get("status") != "STREAMING" or (
            brti.get("authenticated_stream_verified") is not True):
        return False
    price = _number(brti.get("latest_value_usd"))
    event = _number(brti.get("source_ts_ms"))
    receipt = _number(brti.get("axiom_received_at_ms"))
    if (price is None or price <= 0 or event is None or receipt is None
            or not -2 <= now-event/1000 <= 5
            or not -2 <= now-receipt/1000 <= 5):
        return False
    kind = rule.get("type")
    if kind == "BRTI_CLOSE_BACK_INSIDE_RANGE":
        level = _number(rule.get("level_usd"))
        direction = rule.get("direction")
        if (level is None or level <= 0 or not candles or
                direction not in ("UP","DOWN")):
            return False
        bar = candles[-1]
        if (bar.get("source") != BRTI_SOURCE or bar.get("volume") is not None
                or not bar.get("t") or
                bar["t"]+60 < position["created"] or
                not 0 <= now-(bar["t"]+60) < 90):
            return False
        close = _number(bar.get("close"))
        return close is not None and (
            (direction == "UP" and close < level) or
            (direction == "DOWN" and close > level))
    if kind == "BRTI_STRIKE_BAND_OR_CVD_FLIP":
        strike = _number(rule.get("strike"))
        bps = _number(rule.get("max_deviation_bps"))
        return (strike is not None and strike > 0 and bps is not None and
                bps > 0 and abs(price/strike-1)*10000 > bps)
    if kind == "BRTI_CONFIRMED_VENUE_EXTENSION":
        level = _number(rule.get("beyond_outlier_usd"))
        return (level is not None and level > 0 and
                ((position["side"] == "NO" and price >= level) or
                 (position["side"] == "YES" and price <= level)))
    return False


def evaluate_exit(position, market, brti, candles, book, flow, now):
    """Return a quote-backed sell instruction or None. No state mutations."""
    if (not position or not market or
            position.get("ticker") != market.get("ticker")):
        return None
    if position.get("side") not in ("YES", "NO"):
        return None
    remaining = _number(market.get("close_ts"))
    if remaining is None or remaining <= now:
        # No made-up $0/$1 expiry exit; official settlement worker grades it.
        return None
    if not current_book(book, market["ticker"], now, 15):
        return None
    side = position["side"]
    sell = sweep(book, side, "SELL", 1.)
    bid = sell.get("average_price")
    if not sell.get("complete") or bid is None or not 0 < bid < 1:
        return None
    seconds_left = remaining-now
    target = _number(position.get("take_profit"))
    if target is not None and 0 < target <= 1 and bid >= target:
        reason = "TAKE_PROFIT"
    elif _invalidated(position, brti, candles, now):
        reason = "BRTI_INVALIDATION"
    elif seconds_left <= 150 and bid < .50:
        reason = "TIME_STOP"
    else:
        cvd = _number((flow or {}).get("CVD_norm_60s"))
        ready = ((flow or {}).get("available") is True and
                 _number((flow or {}).get("cvd_60_span")) is not None and
                 (flow or {})["cvd_60_span"] >= 45)
        opposed = cvd is not None and (
            (side == "YES" and cvd < -.05) or
            (side == "NO" and cvd > .05))
        reason = "CVD_SIGN_FLIP" if seconds_left > 180 and ready and opposed else None
    return ({"exit_price": bid, "exit_reason": reason,
             "quote_received_at": book.get("received_at")}
            if reason else None)
