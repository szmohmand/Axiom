"""Real-time BTC15M target, movement and execution signals.

Deterministic, point-in-time calculations from fresh candles, Kalshi target
and optionally authenticated live BRTI. NOT a pre-trained 0.700-AUC model;
no assertion of calibrated probabilities, future fills or net profitability.
"""
from __future__ import annotations
import math
import statistics

from .engine import numeric
from .orderbook import current_book

MOVE_LOG_THRESHOLD = math.log(1.0005)  # 5 bp
MAX_CANDLE_AGE_SECONDS = 200
MAX_SPOT_AGE_SECONDS = 90


def _normal(z):
    return 0.5 * math.erfc(-z / math.sqrt(2))


def unavailable(reason):
    return {"available": False, "reason": reason, "side": "WAIT",
            "prob_above": None, "prob_below": None,
            "target_touch_probability": None,
            "movement_2m_probability_5bp": None,
            "price_reference": "UNAVAILABLE", "calibrated": False,
            "immediate_direction_from_move_probability": False}


def derive_signals(market, spot, candles, now, brti=None, spot_received_at=None,
                   spot_source_at=None):
    """Calculate six price signals; never infer a missing target or bar.

    A signed current BRTI reference is preferred for distance-to-target.
    Coinbase candles remain explicitly the proxy for momentum and volatility.
    All values are point-in-time from already-observed data.
    """
    if not isinstance(market, dict):
        return unavailable("No active target contract")
    target = numeric(market.get("target"))
    spot = numeric(spot)
    now = numeric(now)
    close_ts = numeric(market.get("close_ts"))
    if target is None or target <= 0 or spot is None or spot <= 0 or now is None or close_ts is None:
        return unavailable("Missing positive target, BTC price or reliable time")
    remaining = close_ts-now
    if not 0 < remaining <= 900:
        return unavailable("Contract closed or expiry outside active BTC15M horizon")
    if not isinstance(candles, list) or len(candles) < 31:
        return unavailable("At least 31 genuine one-minute candles required")
    try:
        times = [numeric(c["t"]) for c in candles[-61:]]
        closes = [numeric(c["close"]) for c in candles[-61:]]
    except (TypeError, KeyError):
        return unavailable("Invalid Coinbase candle")
    if (any(x is None for x in times+closes) or any(x <= 0 for x in closes)
            or any(b-a != 60 for a,b in zip(times, times[1:]))
            or times[-1] > now+60 or now-times[-1] > MAX_CANDLE_AGE_SECONDS):
        return unavailable("Missing, stale, out-of-order or invalid one-minute data")
    if spot_received_at is not None:
        receipt=numeric(spot_received_at)
        if receipt is None or receipt>now+2 or now-receipt>MAX_SPOT_AGE_SECONDS:
            return unavailable("BTC ticker receipt is stale or invalid")
    if spot_source_at is not None:
        source=numeric(spot_source_at)
        if source is None or source>now+2 or now-source>MAX_SPOT_AGE_SECONDS:
            return unavailable("BTC trade event timestamp is stale or invalid")

    ret=[math.log(b/a) for a,b in zip(closes,closes[1:])]
    if len(ret)<30:
        return unavailable("Insufficient valid price history")
    sigma_long=statistics.pstdev(ret[-min(45,len(ret)):])
    sigma_short=statistics.pstdev(ret[-10:])
    sigma=math.sqrt(.75*sigma_long*sigma_long+.25*sigma_short*sigma_short)
    if not math.isfinite(sigma) or sigma<1e-7:
        return unavailable("Flat or invalid BTC volatility; abstaining")
    duration=remaining/60
    reference=spot
    ref_name="COINBASE_PROXY_NOT_SETTLEMENT"
    if isinstance(brti,dict) and brti.get("status")=="STREAMING" and brti.get("authenticated_stream_verified"):
        value=numeric(brti.get("latest_value_usd"))
        source_ms=numeric(brti.get("source_ts_ms"))
        receipt_ms=numeric(brti.get("axiom_received_at_ms"))
        if (value and value>0 and source_ms is not None and receipt_ms is not None
                and -2 <= now-source_ms/1000 <= 5 and -2 <= now-receipt_ms/1000 <= 5):
            reference=value
            ref_name="AUTHENTICATED_LIVE_BRTI"
    distance=reference-target
    distance_bps=10000*math.log(reference/target)
    normalized=math.log(reference/target)/(sigma*math.sqrt(duration))
    # Acceleration uses 3-minute mean return delta, not just trend sign.
    first=statistics.mean(ret[-6:-3])
    second=statistics.mean(ret[-3:])
    acceleration=second-first
    # Small, bounded acceleration term; no claim of fitted historic weights.
    acceleration_z=max(-.12,min(.12,acceleration/max(sigma,1e-7)*.08))
    early_displacement_bps=None
    early_flag="NOT_OBSERVED"
    reversal="NO"
    start=close_ts-900
    by_time={int(t): c for t,c in zip(times,candles[-61:])}
    initial=by_time.get(int(start))
    if initial:
        start_open=numeric(initial.get("open"))
        if start_open and start_open>0:
            early_displacement_bps=round(10000*math.log(spot/start_open),3)
            elapsed=now-start
            if 0<=elapsed<=300:
                early_flag=("UP" if early_displacement_bps>=5 else
                            "DOWN" if early_displacement_bps<=-5 else "NEUTRAL")
            second_bar=by_time.get(int(start)+60)
            early_close=numeric(second_bar.get("close")) if second_bar else None
            if early_close and early_close>0 and elapsed>=120:
                initial_two_bps=10000*math.log(early_close/start_open)
                if initial_two_bps<=-5:
                    reversal="EARLY_DOWN_REBOUND_TENDENCY"
                elif initial_two_bps>=5:
                    reversal="EARLY_UP_NO_RELIABLE_REVERSAL"
    # Head-start affects settlement forecast only in the first 5 minutes.
    # It NEVER asserts immediate continuation or a guaranteed cheaper exit.
    early_z=0.
    if early_flag in ("UP","DOWN") and ref_name=="COINBASE_PROXY_NOT_SETTLEMENT":
        early_z=max(-.07,min(.07,(early_displacement_bps or 0)*.002))
    p=max(.005,min(.995,_normal(normalized+acceleration_z+early_z)))
    # Reflection principle: driftless Brownian approximation, not observed
    # trained/validated Kalshi touch rates or actual settlement probability.
    touch=max(0.,min(1.,math.erfc(abs(math.log(reference/target))/
                                (sigma*math.sqrt(2*duration)))))
    # Magnitude-only risk. Approximately 5bp or more in either direction in
    # two minutes; explicitly NOT directional confidence.
    move=max(0.,min(1.,math.erfc(MOVE_LOG_THRESHOLD/
                               (sigma*math.sqrt(2*2)))))
    momentum_bps=10000*second
    return {
        "available": True, "reason":"Fresh observed BTC distance, volatility, time, acceleration and early displacement",
        "side":"ABOVE" if p>=.60 else "BELOW" if p<=.40 else "WAIT",
        "prob_above":round(p,5), "prob_below":round(1-p,5),
        "price_reference":ref_name, "reference_value":round(reference,2),
        "settlement_proxy_warning":ref_name!="AUTHENTICATED_LIVE_BRTI",
        "target":target, "seconds_left":round(remaining),
        "distance_usd":round(distance,2), "distance_bps":round(distance_bps,3),
        "distance_volatility_z":round(normalized,4),
        "volatility_1m_long":round(sigma_long,9),
        "volatility_1m_short":round(sigma_short,9),
        "volatility_1m_blended":round(sigma,9),
        "acceleration_bps_per_min":round(acceleration*10000,4),
        "momentum_bps_per_min":round(momentum_bps,4),
        "target_touch_probability":round(touch,5),
        "movement_2m_probability_5bp":round(move,5),
        "immediate_direction_from_move_probability":False,
        "early_displacement_bps":early_displacement_bps,
        "early_displacement_signal":early_flag,
        "first_two_minute_reversal_flag":reversal,
        "calibrated":False,
        "forecast_type":"end_of_contract",
        "touch_type":"touch_at_any_time_before_close_not_settlement",
        "model_type":"analytic_bounded_acceleration_not_historical_fitted_model",
    }


def execution_decision(signals, forecast, market, book, opportunity, now):
    """Unified *read-only* entry timing filter, not an actual order router."""
    wait={"action":"WAIT", "side":None, "reason":"No qualified live entry",
          "read_only":True,"order_placed":False,"verified_net_returns":False,
          "outcome_not_equal_resale":True,"signal_source":"btc_distance_acceleration_touch_move_depth"}
    if not signals or not signals.get("available"):
        return {**wait,"reason":"BTC signals unavailable or stale"}
    if not forecast or not forecast.get("available") or not market:
        return {**wait,"reason":"Independent forecast unavailable"}
    if not current_book(book, market["ticker"],now):
        return {**wait,"reason":"Full-depth Kalshi liquidity unavailable or stale"}
    if not opportunity or opportunity.get("status")!="CANDIDATE":
        return {**wait,"reason":"Wait for an independently favorable after-fee, size-adjusted ask"}
    pick=opportunity.get("selected") or {}
    p=numeric(forecast.get("prob_above"))
    mid=numeric(market.get("market_mid"))
    side=pick.get("side")
    if p is None or side not in ("YES","NO"):
        return {**wait,"reason":"Missing direction or independent probability"}
    # Small-sample 50/50 observation is treated as uncertainty *with*
    # weak model conviction, not as a universal ban on 50-cent contracts.
    if mid is not None and .47<=mid<=.53 and .35<=p<=.65:
        return {**wait,"reason":"Market near 50/50 and independent evidence weak"}
    if signals.get("first_two_minute_reversal_flag")=="EARLY_DOWN_REBOUND_TENDENCY" and side=="NO" and p>.20:
        return {**wait,"reason":"Sharp early drop has a reversal-risk flag; wait for stronger downside evidence"}
    # BRTI and Coinbase can diverge; only the current authenticated BRTI
    # earns the official-reference label, but proxies remain transparently
    # flagged for forecast-only interpretation.
    buy=pick.get("ask_sweep") or {}
    sell=pick.get("bid_sweep") or {}
    entry=buy.get("average_price")
    displayed_bid=sell.get("average_price")
    value=pick.get("net_estimated_model_minus_cost")
    return {**wait, "action":"BUY_CANDIDATE","side":side,
            "reason":"Independent outcome estimate + depth-adjusted price and fee gate; not a promised resale",
            "entry_price":entry,"current_exit_bid":displayed_bid,
            "spread":pick.get("spread"),"size_contracts":pick.get("size_contracts"),
            "estimated_value_per_contract":value,
            "movement_risk_2m":signals.get("movement_2m_probability_5bp"),
            "touch_probability":signals.get("target_touch_probability"),
            "reference":signals.get("price_reference"),
            "current_resale_profit_verified":False,
            "quote_fill_guaranteed":False}
