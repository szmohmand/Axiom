"""Candlestick-context research features for AXIOM; NOT a trading signal.

Rule families are inspired by concepts discussed in Steve Nison,
Japanese Candlestick Charting Techniques (2nd ed.), particularly chapters
3-8, 11, 13, 15 and 17.  This is original implementation, not book text.

Candle formations are CONDITIONED ON PRECEDING TREND and read as information
about possible changes in market pressure, not evidence of imminent direction.
All thresholds are research hypotheses that require out-of-sample testing.
"""
from __future__ import annotations
import math
import statistics
from typing import Any

MIN_CANDLES = 26
MAX_CLOSED_BAR_AGE_SECONDS = 125


def unavailable(reason: str) -> dict[str, Any]:
    return {
        "available": False, "status": "UNAVAILABLE",
        "source": "COINBASE_EXCHANGE_1M_CANDLES", "timeframe": "1m",
        "research_only": True, "votes_in_ensemble": False,
        "can_trigger_paper_or_orders": False, "changes_forecast_probability": False,
        "market_read": "UNKNOWN", "prior_trend": "UNKNOWN",
        "formations": [], "confluence": [], "measurements": None,
        "reason": reason,
    }


def _numeric(x: Any) -> float:
    if isinstance(x, bool):
        raise ValueError("Boolean is not a market price")
    y = float(x)
    if not math.isfinite(y):
        raise ValueError("Nonfinite market data")
    return y


def _bar_shape(bar: dict) -> dict:
    op, cl, hi, lo = (bar[k] for k in ("open", "close", "high", "low"))
    span = hi - lo
    body = abs(cl-op)
    return {
        "bullish": cl>op, "bearish": cl<op,
        "body": body, "span": span, "upper": hi-max(op, cl),
        "lower": min(op, cl)-lo,
        "body_fraction": body/span if span>0 else 0,
        "upper_fraction": (hi-max(op,cl))/span if span>0 else 0,
        "lower_fraction": (min(op,cl)-lo)/span if span>0 else 0,
        "close_location": (cl-lo)/span if span>0 else 0.5,
    }


def _trend_before(bars: list[dict], pattern_bars: int, atr: float) -> str:
    # The formation itself must NOT determine its preceding trend.
    prior = bars[:-pattern_bars]
    if len(prior) < 8:
        return "UNKNOWN"
    move = prior[-1]["close"]-prior[-8]["close"]
    if move > 0.8*atr:
        return "UP"
    if move < -0.8*atr:
        return "DOWN"
    return "RANGE"


def _feature(name: str, interpretation: str, direction: str,
             confirmation: str, context: list[str]) -> dict:
    return {
        "name": name, "interpretation": interpretation,
        "conditional_bias": direction, "confirmation": confirmation,
        "confluence": context,
        "actionable": False, "validated_win_rate": None,
    }


def read_candlestick_context(candles: list[dict], now: float) -> dict[str, Any]:
    """Analyze *only fully closed*, verified 1-minute BTC OHLCV bars.

    Does not use the Kalshi target, contract price, BRTI, labels, or future bars.
    Never computes the final contract winner, learned probability or a trade.
    """
    try:
        asof = _numeric(now)
    except (TypeError, ValueError):
        return unavailable("Invalid observation time")
    if not isinstance(candles, list):
        return unavailable("Missing OHLCV candles")
    parsed: list[dict] = []
    previous_timestamp = None
    for row in candles:
        if not isinstance(row, dict):
            return unavailable("Malformed candle")
        try:
            ts = _numeric(row["t"])
            op, hi, lo, cl = (_numeric(row[k]) for k in ("open","high","low","close"))
            raw_volume = row.get("volume")
            volume = None if raw_volume is None else _numeric(raw_volume)
        except (KeyError, TypeError, ValueError, OverflowError):
            return unavailable("Invalid OHLCV record")
        if (previous_timestamp is not None and ts-previous_timestamp != 60) or ts % 60 != 0:
            return unavailable("Duplicate, non-monotonic, or missing 1-minute candle")
        previous_timestamp = ts
        if ts > asof + 60:
            return unavailable("Future-dated market candle")
        if (lo<=0 or lo>min(op,cl) or hi<max(op,cl) or
                (volume is not None and volume<0)):
            return unavailable("Impossible OHLCV values")
        # Coinbase candle timestamp denotes bar START; a bar closes at t+60.
        if ts+60 <= asof:
            parsed.append({"t":ts,"open":op,"high":hi,"low":lo,
                           "close":cl,"volume":volume})
    if len(parsed) < MIN_CANDLES:
        return unavailable("Insufficient fully closed 1-minute bars")
    if asof-(parsed[-1]["t"]+60)>MAX_CLOSED_BAR_AGE_SECONDS:
        return unavailable("Last fully closed bar is stale")
    bars=parsed[-61:]
    current, prev=bars[-1],bars[-2]
    tr=[max(b["high"]-b["low"],
            abs(b["high"]-a["close"]),abs(b["low"]-a["close"]))
        for a,b in zip(bars[:-1],bars[1:])]
    atr=statistics.mean(tr[-14:])
    if atr<=0:
        return unavailable("No measurable price range for context")
    sh=_bar_shape(current)
    prior_shape=_bar_shape(prev)
    before_last=_trend_before(bars,1,atr)
    before_pair=_trend_before(bars,2,atr)

    volume_history=[b["volume"] for b in bars[-21:-1] if b["volume"] is not None]
    relative_volume=None
    if (len(volume_history)==20 and current["volume"] is not None):
        typical=statistics.median(volume_history)
        if typical>0:
            relative_volume=current["volume"]/typical
    high_volume=relative_volume is not None and relative_volume>=1.5

    # Levels are formed *before* the possible signal. Never use signal highs or
    # lows to manufacture its own apparent support/resistance confirmation.
    prev_twenty=bars[-21:-1]
    support=min(b["low"] for b in prev_twenty)
    resistance=max(b["high"] for b in prev_twenty)
    near_support=abs(current["low"]-support)<=0.5*atr
    near_resistance=abs(current["high"]-resistance)<=0.5*atr
    common=[]
    if high_volume:
        common.append("RELATIVE_VOLUME_SPIKE")

    events=[]
    lower_umbrella=(sh["lower"]>=2*max(sh["body"],.02*sh["span"])
                    and sh["lower_fraction"]>=.55
                    and sh["upper_fraction"]<=.15)
    upper_rejection=(sh["upper"]>=2*max(sh["body"],.02*sh["span"])
                     and sh["upper_fraction"]>=.55
                     and sh["lower_fraction"]<=.15)
    if lower_umbrella and before_last=="DOWN":
        ctx=common+(["PRIOR_SUPPORT"] if near_support else [])
        events.append(_feature("HAMMER","Decline may be losing selling pressure",
                               "BULLISH_CAUTION","CLOSED_CANDLE; FOLLOW_THROUGH_NOT_ESTABLISHED",ctx))
    if lower_umbrella and before_last=="UP":
        events.append(_feature("HANGING_MAN","Rally may be vulnerable; bearish confirmation required",
                               "BEARISH_CAUTION","NEXT_CANDLE_REQUIRED",common))
    if upper_rejection and before_last=="UP":
        ctx=common+(["PRIOR_RESISTANCE"] if near_resistance else [])
        events.append(_feature("SHOOTING_STAR","Higher prices were rejected during a rally",
                               "BEARISH_CAUTION","FOLLOW_THROUGH_NOT_ESTABLISHED",ctx))
    if upper_rejection and before_last=="DOWN":
        events.append(_feature("INVERTED_HAMMER","Downtrend may be stalling; upward confirmation required",
                               "BULLISH_CAUTION","NEXT_CANDLE_REQUIRED",common))

    # Engulfing evaluates REAL BODIES, not total high-low ranges, and uses the
    # trend BEFORE BOTH pattern candles.  No gap is required on continuous BTC.
    bull_engulf=(prior_shape["bearish"] and sh["bullish"] and
                 current["open"]<=prev["close"] and current["close"]>=prev["open"]
                 and sh["body"]>prior_shape["body"])
    bear_engulf=(prior_shape["bullish"] and sh["bearish"] and
                 current["open"]>=prev["close"] and current["close"]<=prev["open"]
                 and sh["body"]>prior_shape["body"])
    if bull_engulf and before_pair=="DOWN":
        events.append(_feature("BULLISH_ENGULFING","Buying overcame the previous real-body decline",
                               "BULLISH_CAUTION","TWO_COMPLETED_CANDLES; NO_FOLLOW_THROUGH_YET",
                               common+(["PRIOR_SUPPORT"] if near_support else [])))
    if bear_engulf and before_pair=="UP":
        events.append(_feature("BEARISH_ENGULFING","Selling overcame the previous real-body advance",
                               "BEARISH_CAUTION","TWO_COMPLETED_CANDLES; NO_FOLLOW_THROUGH_YET",
                               common+(["PRIOR_RESISTANCE"] if near_resistance else [])))

    if sh["span"]>0 and sh["body_fraction"]<=.10:
        if before_last in ("UP","DOWN"):
            events.append(_feature("DOJI","Previous trend may be pausing; direction is not established",
                                   "TREND_STALL","FOLLOW_THROUGH_REQUIRED",common))
        else:
            events.append(_feature("DOJI","Buyer/seller balance in an already sideways market",
                                   "NEUTRAL","NO_DIRECTIONAL_CONFIRMATION",common))

    if sh["body_fraction"]>=.70 and sh["span"]>=0.8*atr:
        same_dir=("UP" if sh["bullish"] else "DOWN" if sh["bearish"] else "RANGE")
        if same_dir==before_last:
            events.append(_feature("LONG_BODY_WITH_TREND","Directional close supports the prior trend",
                                   "CONTINUATION_OBSERVATION","NOT_A_PRICE_TARGET",common))
    if sh["lower_fraction"]>=.50 and sh["close_location"]>=.70 and not lower_umbrella:
        events.append(_feature("LOWER_WICK_REJECTION","Lower prices rejected within one completed minute",
                               "BUYER_RESPONSE_OBSERVED","NOT_ORDER_BOOK_ABSORPTION",common))
    if sh["upper_fraction"]>=.50 and sh["close_location"]<=.30 and not upper_rejection:
        events.append(_feature("UPPER_WICK_REJECTION","Higher prices rejected within one completed minute",
                               "SELLER_RESPONSE_OBSERVED","NOT_ORDER_BOOK_ABSORPTION",common))
    if any(e["conditional_bias"]=="TREND_STALL" for e in events):
        market_read="TREND_STALL_WARNING"
    elif any(e["conditional_bias"].endswith("_CAUTION") for e in events):
        market_read="POSSIBLE_TREND_CHANGE_NOT_CONFIRMED"
    elif any(e["conditional_bias"]=="CONTINUATION_OBSERVATION" for e in events):
        market_read="TREND_CONTINUATION_OBSERVED"
    elif any(e["conditional_bias"].endswith("_OBSERVED") for e in events):
        market_read="LOCAL_REJECTION_OBSERVED"
    else:
        market_read="NO_DISTINCTIVE_FORMATION"

    return {
        "available": True, "status": "DESCRIPTIVE_UNCALIBRATED",
        "source": "COINBASE_EXCHANGE_1M_CANDLES", "timeframe": "1m",
        "research_only": True, "votes_in_ensemble": False,
        "can_trigger_paper_or_orders": False, "changes_forecast_probability": False,
        "market_read": market_read, "prior_trend": before_last,
        "formations": events,
        "confluence": common+([ "PRIOR_SUPPORT" ] if near_support else [])+
                      (["PRIOR_RESISTANCE"] if near_resistance else []),
        "measurements": {
            "body_fraction": round(sh["body_fraction"],4),
            "upper_wick_fraction": round(sh["upper_fraction"],4),
            "lower_wick_fraction": round(sh["lower_fraction"],4),
            "close_location": round(sh["close_location"],4),
            "atr_14_usd": round(atr,4),
            "relative_volume_to_previous_20_median":
                None if relative_volume is None else round(relative_volume,4),
            "local_support_usd": round(support,2),
            "local_resistance_usd": round(resistance,2),
            "completed_candles": len(bars),
            "last_completed_bar_end": int(current["t"]+60),
        },
        "reason": "Descriptive candle and context observations; no independently verified Kalshi prediction edge",
    }
