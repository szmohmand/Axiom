"""A BRTI-settlement-aligned BTC15M probability, independent of Kalshi prices.

The official outcome uses a *60-second average* of the CF Bitcoin Real-Time
Index, not an end-point spot tick. In the Brownian log-price approximation,
before the last minute, the future average has variance
    sigma_1m**2 * (seconds_to_close - 40) / 60
rather than sigma_1m**2 * seconds_to_close / 60.
Within the last minute, only authenticated, received, contiguous first
observations per second can contribute to the already-known portion of the
average; the conditional future-average variance shrinks with sum(k**2).
Neither historical index revisions nor unobserved seconds are invented.

Source conventions: Kalshi crypto market rules and CF Benchmarks BRTI.
This model does not ingest Kalshi YES/NO quotes, and creates no orders.
"""
from __future__ import annotations

import math
import statistics

from .engine import numeric


def unavailable(reason):
    return {"available": False, "prob_above": None, "reason": reason,
            "method": "brti-60s-average-conditional-normal",
            "forecast_type": "official_benchmark_settlement_average",
            "calibrated": False, "trading_actions_enabled": False}


def _sigma_coinbase_proxy(candles):
    """Fallback variance only: NEVER treat Coinbase price as BRTI price."""
    if not isinstance(candles, list):
        return None
    closes = [numeric(c.get("close")) for c in candles[-46:]
              if isinstance(c, dict)]
    if len(closes) < 31 or any(p is None or p <= 0 for p in closes):
        return None
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    result = statistics.stdev(returns[-45:])
    return result if math.isfinite(result) and result >= 1e-7 else None


def forecast(market, brti, candles, now):
    if not isinstance(market, dict) or not isinstance(brti, dict):
        return unavailable("Missing official contract or authenticated BRTI")
    target = numeric(market.get("target"))
    close = numeric(market.get("close_ts"))
    when = numeric(now)
    if target is None or target <= 0 or close is None or when is None:
        return unavailable("Missing official strike or close time")
    remaining = close - when
    if not 0 < remaining <= 900:
        return unavailable("Not a currently open 15-minute contract")
    if (brti.get("status") != "STREAMING" or
            brti.get("authenticated_stream_verified") is not True):
        return unavailable("Authenticated live BRTI stream not available")
    reference = numeric(brti.get("latest_value_usd"))
    event_ms = numeric(brti.get("source_ts_ms"))
    receipt_ms = numeric(brti.get("axiom_received_at_ms"))
    if (reference is None or reference <= 0 or event_ms is None or
            receipt_ms is None or not
            (-2 <= when - event_ms / 1000 <= 5 and
             -2 <= when - receipt_ms / 1000 <= 5)):
        return unavailable("BRTI benchmark stale, invalid or future-dated")

    measured_sigma = numeric(brti.get("completed_minute_sigma_45"))
    if measured_sigma is not None and 1e-7 <= measured_sigma <= .10:
        sigma, sigma_source = measured_sigma, "authenticated_BRTI_completed_minutes"
    else:
        sigma = _sigma_coinbase_proxy(candles)
        sigma_source = "Coinbase_completed_1m_volatility_proxy"
    if sigma is None:
        return unavailable("No valid recent volatility; cannot price settlement uncertainty")

    partial_count = 0
    estimated_average = reference
    if remaining >= 60:
        # E[future 60s mean] equals today's benchmark under zero drift.
        # Integrated Brownian variance of the final-minute average adds
        # 1/3 minute, rather than an instantaneous endpoint's full minute.
        effective_variance_minutes = (remaining - 40) / 60
        method = "unrealized_final_minute_integrated_brownian_variance"
    else:
        # The final interval has already begun. Past observed seconds are
        # locked into the average, so today's spot alone is insufficient.
        window = brti.get("settlement_window_stats")
        if (not isinstance(window, dict) or
                numeric(window.get("window_end_ts")) != close or
                window.get("complete_prefix") is not True):
            return unavailable("Incomplete authenticated BRTI seconds in current closing minute")
        partial_count = window.get("observed_seconds")
        prefix_mean = numeric(window.get("observed_mean_usd"))
        expected_count = window.get("expected_seconds")
        if (isinstance(partial_count, bool) or not isinstance(partial_count, int) or
                partial_count < 0 or partial_count >= 60 or
                expected_count != partial_count or
                (partial_count > 0 and (prefix_mean is None or prefix_mean <= 0))):
            return unavailable("Final-minute BRTI sample coverage invalid")
        unknown = 60 - partial_count
        estimated_average = (
            (partial_count * (prefix_mean if partial_count else 0) +
             unknown * reference) / 60
        )
        # Discrete first-tick-per-second approximation; each future second's
        # Brownian shock influences a decreasing number of remaining readings.
        sum_squares = unknown * (unknown + 1) * (2 * unknown + 1) / 6
        effective_variance_minutes = sum_squares / (60 ** 3)
        method = "observed_final_minute_prefix_conditional_brownian_variance"

    if not (effective_variance_minutes > 0 and math.isfinite(estimated_average)
            and estimated_average > 0):
        return unavailable("Invalid conditional variance or benchmark average")
    z = math.log(estimated_average / target) / (
        sigma * math.sqrt(effective_variance_minutes))
    p = max(.0005, min(.9995, .5 * math.erfc(-z / math.sqrt(2))))
    return {
        "available": True, "prob_above": round(p, 5),
        "prob_below": round(1 - p, 5),
        "method": "brti-60s-average-conditional-normal",
        "conditional_method": method, "calibrated": False,
        "forecast_type": "official_benchmark_settlement_average",
        "source": "authenticated_live_CF_BRTI_only",
        "volatility_source": sigma_source,
        "volatility_1m": round(sigma, 9),
        "effective_variance_minutes": round(effective_variance_minutes, 7),
        "estimated_final_mean_usd": round(estimated_average, 3),
        "observed_final_minute_seconds": partial_count,
        "benchmark_asof_timestamp_ms": int(event_ms),
        "trading_actions_enabled": False,
        "reason": "Actual BRTI benchmark with modeled final 60-second averaging uncertainty",
    }
