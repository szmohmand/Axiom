"""Build price-only, completed CF Benchmarks BRTI candles from received ticks.

All observations are already received, authenticated Kalshi BRTI stream updates.
No exchange OHLCV, quote data, backfilled seconds, manufactured volume, or
future ticks are used. An incomplete minute is omitted, not interpolated.
Only derived minute bars, never the raw stream, reach the dashboard.
"""
from __future__ import annotations

import math
import statistics

SOURCE = "cfbenchmarks_brti_authenticated_live"
MIN_SECONDS = 50
MAX_GAP_SECONDS = 8


def completed_one_minute(seconds, now_seconds):
    """seconds: {Unix whole second: observed first BRTI price in that second}."""
    groups = {}
    for sec, price in sorted(seconds.items()):
        if not isinstance(sec, int) or isinstance(sec, bool):
            continue
        if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            continue
        start = sec - sec % 60
        if start + 60 <= now_seconds:
            groups.setdefault(start, []).append((sec, float(price)))
    bars = []
    for start, samples in sorted(groups.items()):
        stamps = [s for s, _ in samples]
        if (len(samples) < MIN_SECONDS or stamps[0] - start > 5 or
                start + 59 - stamps[-1] > 5 or
                any(b - a > MAX_GAP_SECONDS for a, b in zip(stamps, stamps[1:]))):
            continue
        values = [p for _, p in samples]
        bars.append({"t": start, "open": values[0], "high": max(values),
                     "low": min(values), "close": values[-1],
                     "volume": None, "observed_seconds": len(values),
                     "source": SOURCE})
    return bars[-155:]


def completed_five_minute(bars):
    """Aggregate five actual contiguous, completed BRTI minutes; no fake volume."""
    if not isinstance(bars, list):
        return []
    by_time = {bar["t"]: bar for bar in bars}
    result = []
    starts = sorted(t for t in by_time if t % 300 == 0)
    for start in starts:
        window = [by_time.get(start + 60 * j) for j in range(5)]
        if any(bar is None for bar in window):
            continue
        result.append({"t": start, "open": window[0]["open"],
                       "high": max(b["high"] for b in window),
                       "low": min(b["low"] for b in window),
                       "close": window[-1]["close"], "volume": None,
                       "source": SOURCE})
    return result[-30:]


def completed_minute_sigma(bars):
    """A one-minute BRTI log-return sigma from 30 to 45 consecutive changes."""
    if not isinstance(bars, list) or len(bars) < 31:
        return None
    recent = bars[-46:]
    if any(b["t"] - a["t"] != 60 for a, b in zip(recent, recent[1:])):
        return None
    closes = [float(b["close"]) for b in recent]
    if min(closes) <= 0:
        return None
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    sigma = statistics.stdev(returns[-45:])
    return sigma if math.isfinite(sigma) and sigma >= 1e-7 else None


def final_minute_prefix(seconds, close_ts, current_source_second):
    """Live contiguous as-received prefix of the final 60 seconds, or unavailable."""
    if (not isinstance(close_ts, (int, float)) or
            not math.isfinite(close_ts) or int(close_ts) % 60):
        return None
    end = int(close_ts)
    start = end - 60
    if not start <= current_source_second < end:
        return None
    count = current_source_second - start + 1
    observed = [seconds.get(t) for t in range(start, start + count)]
    complete = all(x is not None for x in observed)
    return {"window_end_ts": end, "observed_seconds": count if complete else
            sum(x is not None for x in observed), "expected_seconds": count,
            "complete_prefix": complete,
            "observed_mean_usd": sum(observed) / count if complete else None,
            "source": SOURCE}
