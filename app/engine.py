"""Transparent, experimental BTC15m and spot momentum research logic.

This is NOT the original implementation of any researched third-party bot.
No trained model, calibrated probability, fills, or performance are claimed.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import math
import re
import statistics
from typing import Any


def utc_timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def quote(value: Any) -> float | None:
    f = numeric(value)
    return round(f, 5) if f is not None and 0 < f < 1 else None


def market_snapshot(raw: dict, now: float | None = None) -> dict:
    """Extract only known Kalshi fields. Never guess a target from spot."""
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    ticker = str(raw.get('ticker') or '')
    if not ticker.startswith('KXBTC15M-'):
        raise ValueError('Not a KXBTC15M market')
    end = utc_timestamp(raw.get('close_time') or raw.get('expiration_time') or raw.get('expected_expiration_time'))
    if not end:
        raise ValueError('Market missing close_time')
    target = numeric(raw.get('floor_strike'))
    if not target or target < 1000:
        target = None
    # APIs may provide dollars fields, deprecated integer cents, or one side only.
    def price(dollars: str, cents: str):
        p = quote(raw.get(dollars))
        if p is None:
            x = numeric(raw.get(cents))
            if x is not None:
                p = quote(x / 100)
        return p
    yb = price('yes_bid_dollars', 'yes_bid')
    ya = price('yes_ask_dollars', 'yes_ask')
    nb = price('no_bid_dollars', 'no_bid')
    na = price('no_ask_dollars', 'no_ask')
    if ya is None and nb is not None: ya = round(1 - nb, 5)
    if na is None and yb is not None: na = round(1 - yb, 5)
    if yb is None and na is not None: yb = round(1 - na, 5)
    if nb is None and ya is not None: nb = round(1 - ya, 5)
    mids = [(yb + ya) / 2] if yb is not None and ya is not None and yb <= ya else []
    if not mids and ya is not None and na is not None:
        mids = [(ya + (1 - na)) / 2]
    mid = round(mids[0], 5) if mids else None
    return {
        'ticker': ticker, 'title': raw.get('title') or 'BTC up in 15 minutes?',
        'status': raw.get('status'), 'close_ts': end,
        'seconds_left': max(0, round(end - now)),
        'target': target, 'target_source': 'Kalshi floor_strike' if target else 'Not yet published',
        'yes_bid': yb, 'yes_ask': ya, 'no_bid': nb, 'no_ask': na, 'market_mid': mid,
        'result': str(raw.get('result') or '').lower(),
    }


def normalize_candles(raw: list) -> list[dict]:
    """Coinbase candles are [timestamp, low, high, open, close, volume]."""
    result = {}
    for c in raw or []:
        if not isinstance(c, (tuple, list)) or len(c) < 6: continue
        nums = [numeric(z) for z in c[:6]]
        if any(x is None for x in nums): continue
        t, lo, hi, op, cl, vol = nums
        if min(lo, op, cl) <= 0 or hi < lo or not (lo <= op <= hi and lo <= cl <= hi): continue
        result[int(t)] = {'t': int(t), 'low': lo, 'high': hi, 'open': op, 'close': cl, 'volume': vol}
    return sorted(result.values(), key=lambda k: k['t'])[-150:]


def volatility_forecast(spot: float | None, target: float | None,
                        seconds_left: int, candles: list[dict]) -> dict:
    """GBM-inspired descriptive probability; *not* calibrated or validated.

    Volatility is from actual one-minute closes, 15+ observations required.
    Drift deliberately capped. Spot proxy is NOT the official BRTI index.
    """
    empty = {'available': False, 'prob_above': None, 'prob_below': None, 'side': 'WAIT',
             'reason': 'Requires a published Kalshi target, fresh BTC price and at least 16 candles',
             'sigma_1m': None, 'drift_1m': None, 'distance': None, 'method': 'experimental-volatility-model'}
    if spot is None or target is None or spot <= 0 or target <= 0 or seconds_left <= 0: return empty
    closes = [c['close'] for c in candles if c.get('close') and c['close'] > 0]
    if len(closes) < 16: return empty
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    if len(returns) < 15: return empty
    sigma = statistics.stdev(returns[-45:])
    if not math.isfinite(sigma) or sigma < 1e-7: return empty
    # Conservative drift cap: do not extrapolate 1-minute momentum without bound.
    drift = statistics.mean(returns[-5:]) * 0.2
    remaining_min = seconds_left / 60
    std = sigma * math.sqrt(max(remaining_min, 0.01))
    forward_drift = max(-std * .35, min(std * .35, drift * remaining_min))
    z = (math.log(spot / target) + forward_drift) / std
    p = min(.995, max(.005, .5 * (1 + math.erf(z / math.sqrt(2)))))
    return {'available': True, 'prob_above': round(p, 4), 'prob_below': round(1-p, 4),
            'side': 'ABOVE' if p > .5 else 'BELOW', 'reason': 'Coinbase spot proxy + realized 1m volatility; not trained or calibrated',
            'sigma_1m': round(sigma, 8), 'drift_1m': round(drift, 8),
            'distance': round(spot - target, 2), 'method': 'experimental-volatility-model'}


def ema(values: list[float], period: int) -> float:
    if not values: return 0.0
    k = 2/(period + 1)
    e = values[0]
    for v in values[1:]: e = k*v+(1-k)*e
    return e


def scalp_signal(candles: list[dict], spot: float | None) -> dict:
    wait = {'side': 'WAIT', 'entry': None, 'stop': None, 'target': None, 'reason': 'Need at least 24 fresh one-minute BTC candles', 'atr': None}
    if spot is None or len(candles) < 24: return wait
    closes = [x['close'] for x in candles]
    trs = []
    for prev, cur in zip(candles, candles[1:]):
        trs.append(max(cur['high']-cur['low'], abs(cur['high']-prev['close']), abs(cur['low']-prev['close'])))
    atr = statistics.mean(trs[-14:])
    if atr <= 0: return wait
    fast, slow = ema(closes[-40:], 9), ema(closes[-60:], 21)
    gap = (fast-slow)/max(atr, .01)
    side = ('LONG' if gap > .22 and spot > slow else 'SHORT' if gap < -.22 and spot < slow else 'WAIT')
    if side == 'WAIT':
        return {**wait, 'reason': 'EMA trend lacks sufficient separation', 'atr': round(atr,2)}
    direction = 1 if side == 'LONG' else -1
    return {'side': side, 'entry': round(spot,2), 'stop': round(spot - direction*atr*1.25,2),
            'target': round(spot + direction*atr*2.2,2), 'reason': 'EMA(9/21) + ATR(14) research signal; independent of Kalshi contracts',
            'atr': round(atr,2)}


def opportunity(model: dict, market: dict, min_edge: float = .08) -> dict:
    """Before-fee, before-slippage opportunity screen, not an executable quote guarantee."""
    out = {'side': 'WAIT', 'edge': None, 'entry_price': None, 'reason': 'Insufficient independent estimate or executable ask'}
    if not model.get('available'): return out
    yes, no = market.get('yes_ask'), market.get('no_ask')
    p = model['prob_above']
    choices = []
    if yes is not None: choices.append(('YES', p - yes, yes))
    if no is not None: choices.append(('NO', 1-p - no, no))
    if not choices: return out
    side, edge, ask = max(choices, key=lambda z:z[1])
    out.update({'edge': round(edge,4), 'entry_price': ask})
    if edge >= min_edge and .05 <= ask <= .92 and market['seconds_left'] >= 90:
        out.update({'side': side, 'reason': 'Experimental estimate exceeds quoted ask before fees; fill not guaranteed'})
    else:
        out['reason'] = 'Model-market discrepancy below the research gate, time too short, or quote outside range'
    return out


def paper_result(side: str, entry_price: float, official_result: str) -> float:
    if official_result not in ('yes', 'no'): raise ValueError('Unknown official result')
    if side not in ('YES', 'NO'): raise ValueError('Unknown side')
    return round((1-entry_price) if side.lower()==official_result else -entry_price, 5)
