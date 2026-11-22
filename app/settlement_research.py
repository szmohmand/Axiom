"""Research-only, non-voting BTC15m settlement-probability challenger.

The core signal follows the retrospective official-BRTI studies: normalized
log-distance to strike divided by realized 1m volatility * sqrt(time left).

Live AXIOM supplies CF Benchmarks BRTI candles to this module. Historical
source-event timing is not a guarantee of live receipt at the same time.
It must not modify existing ensemble, opportunity, paper, or settlement logic.
"""
from __future__ import annotations

import math
import statistics
from typing import Any


MIN_COMPLETED_CANDLES = 31  # 30 real one-minute returns
MAX_VOLATILITY_MINUTES = 60
MAX_INPUT_AGE_SECONDS = 120


def unavailable(reason: str) -> dict[str, Any]:
    return {
        'available': False, 'side': 'WAIT', 'prob_above': None,
        'prob_below': None, 'z_score': None, 'vol_minutes': None,
        'status': 'UNAVAILABLE', 'source': 'COINBASE_SPOT_PROXY_NOT_BRTI',
        'research_only': True, 'votes_in_ensemble': False,
        'can_trigger_paper_or_orders': False, 'reason': reason,
    }


def shadow_forecast_from_candles(candles: list[dict], market: dict | None,
                                 now: float) -> dict[str, Any]:
    """Read ONLY completed, consecutive candles; never use future/incomplete bars.

    The BRTI event-time version can be evaluated offline on official BRTI,
    separately from this Coinbase-proxy runtime. That retrospective study
    does NOT establish when every strike and index print first arrived.
    """
    if not market:
        return unavailable('No active BTC15m market')
    try:
        strike = float(market['target'])
        seconds_left = float(market['seconds_left'])
        asof = float(now)
    except (KeyError, TypeError, ValueError):
        return unavailable('Missing strike, time remaining, or observation time')
    if (not all(map(math.isfinite, (strike, seconds_left, asof))) or
            strike <= 0 or seconds_left < 1 or seconds_left > 900):
        # Subsecond expiration could underflow sqrt(T) to zero and divide
        # by zero. An effectively expired contract cannot produce a signal.
        return unavailable('Invalid published target or expiration clock')
    if not isinstance(candles, list):
        return unavailable('No valid minute candles')

    # Bar timestamp is its BEGINNING, not its close/publication time.
    # Only consider closed bars, and never silently hide timestamp anomalies.
    observations = []
    for c in candles:
        if not isinstance(c, dict):
            return unavailable('Invalid candle record')
        try:
            ts = float(c['t'])
            price = float(c['close'])
        except (KeyError, TypeError, ValueError):
            return unavailable('Candle missing timestamp or close')
        if not math.isfinite(ts) or not math.isfinite(price) or price <= 0:
            return unavailable('Nonfinite or nonpositive market data')
        if observations and ts <= observations[-1][0]:
            return unavailable('Duplicate or out-of-order minute candles')
        if ts > asof + 60:
            return unavailable('Future-dated candle')
        if ts + 60 <= asof:
            observations.append((ts, price))
    if len(observations) < MIN_COMPLETED_CANDLES:
        return unavailable('Fewer than 31 completed minute candles')

    # Avoid mixing unrelated periods; no interpolation, dropping gaps or
    # using a partly closed current minute to manufacture a volatility signal.
    window = observations[-(MAX_VOLATILITY_MINUTES+1):]
    if any(b[0] - a[0] != 60 for a, b in zip(window, window[1:])):
        return unavailable('Gap or non-minute cadence in volatility history')
    if asof - (window[-1][0] + 60) > MAX_INPUT_AGE_SECONDS:
        return unavailable('Latest completed candle is stale')
    closes = [p for _, p in window]
    returns = [math.log(b/a) for a, b in zip(closes, closes[1:])]
    if len(returns) < MIN_COMPLETED_CANDLES-1:
        return unavailable('Insufficient real returns')
    sigma = statistics.stdev(returns)
    if not math.isfinite(sigma) or sigma <= 0:
        return unavailable('Volatility unavailable or zero; no invented floor')
    z = math.log(closes[-1] / strike) / (sigma * math.sqrt(seconds_left / 60))
    if not math.isfinite(z):
        return unavailable('Forecast not finite')
    p = min(.995, max(.005, .5 * (1 + math.erf(z / math.sqrt(2)))))
    # Near the target, basis and uncertain terminal averaging can easily flip
    # outcome. Keep the raw experimental probability but explicitly abstain.
    side = 'WAIT' if abs(z) < .5 else 'ABOVE' if z > 0 else 'BELOW'
    return {
        'available': True, 'status': 'PROXY_ONLY_NOT_CALIBRATED',
        'side': side, 'prob_above': round(p, 6),
        'prob_below': round(1-p, 6), 'z_score': round(z, 5),
        'vol_minutes': len(returns), 'completed_bar_end': window[-1][0] + 60,
        'source': ('CF_BENCHMARKS_BRTI_LIVE' if candles and
                   candles[-1].get('source')=='cfbenchmarks_brti_authenticated_live'
                   else 'COINBASE_SPOT_PROXY_NOT_BRTI'),
        'research_only': True, 'votes_in_ensemble': False,
        'can_trigger_paper_or_orders': False,
        'near_target_uncertainty': abs(z) < .5,
        'reason': ('Near target: proxy basis and settlement averaging can reverse the result' if side == 'WAIT'
                   else 'Retrospective distance/volatility/time candidate; not proven to beat Kalshi quotes'),
    }
