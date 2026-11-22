"""Single live AXIOM decision brain: authenticated BRTI price + USD constituent flow."""
from __future__ import annotations

import asyncio
from collections import deque
import json
import math
import statistics
import threading
import time

from .orderbook import current_book, sweep
from .settlement_probability import forecast as brti_settlement_forecast

VENUES = ("coinbase", "kraken", "bitstamp")
URLS = {
    "coinbase": "wss://ws-feed.exchange.coinbase.com",
    "kraken": "wss://ws.kraken.com/v2",
    "bitstamp": "wss://ws.bitstamp.net",
}
BRTI_SOURCE = "cfbenchmarks_brti_authenticated_live"


def _positive(value):
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if math.isfinite(n) and n > 0 else None


def _levels(rows, *, kraken=False):
    result = {}
    if not isinstance(rows, list):
        return result
    for row in rows:
        if kraken and isinstance(row, dict):
            price, qty = row.get("price"), row.get("qty")
        elif isinstance(row, (tuple, list)) and len(row) >= 2:
            price, qty = row[0], row[1]
        else:
            continue
        p = _positive(price)
        q = _positive(qty)
        if p is not None and q is not None:
            result[p] = q
    return result


def _pressure(old, new):
    """Signed, weighted change in the five best levels; no price reference."""
    def top(book, side):
        rev = side == "bids"
        return dict(sorted(book[side].items(), reverse=rev)[:5])
    total = 0.
    gross = 0.
    for side, sign in (("bids", 1), ("asks", -1)):
        before, after = top(old, side), top(new, side)
        prices = sorted(set(before) | set(after), reverse=(side == "bids"))
        for rank, price in enumerate(prices[:7]):
            change = after.get(price, 0.) - before.get(price, 0.)
            weighted = sign * change / (rank + 1)
            total += weighted
            gross += abs(weighted)
    return total, gross


class ConstituentFlow:
    """Independent read-only exchange books/trades. Never supplies BTC price."""
    def __init__(self):
        self.lock = threading.RLock()
        self.books = {v: None for v in VENUES}
        self.book_at = {v: None for v in VENUES}
        self.trade_at = {v: None for v in VENUES}
        self.ofi = {v: deque(maxlen=12000) for v in VENUES}
        self.trades = {v: deque(maxlen=30000) for v in VENUES}
        self.trade_ids = {v: {} for v in VENUES}

    def reset(self, venue):
        with self.lock:
            self.books[venue] = None
            self.book_at[venue] = None
            self.trade_at[venue] = None
            self.ofi[venue].clear()
            self.trades[venue].clear()
            self.trade_ids[venue].clear()

    def _book(self, venue, bids, asks, now, *, snapshot):
        old = self.books[venue]
        if snapshot:
            new = {"bids": bids, "asks": asks}
        elif old is not None:
            new = {side: dict(old[side]) for side in ("bids", "asks")}
            for side, updates in (("bids", bids), ("asks", asks)):
                for price, qty in updates.items():
                    if qty > 0:
                        new[side][price] = qty
                    else:
                        new[side].pop(price, None)
        else:
            return
        if not new["bids"] or not new["asks"]:
            return
        # Retain enough levels for delta continuity without unbounded memory.
        for side in ("bids", "asks"):
            new[side] = dict(sorted(new[side].items(),
                                    reverse=(side == "bids"))[:200 if venue == "coinbase" else 10])
        if max(new["bids"]) >= min(new["asks"]):
            self.reset(venue)
            return
        if old is not None:
            pressure, gross = _pressure(old, new)
            if gross:
                self.ofi[venue].append((now, pressure, gross))
        self.books[venue] = new
        self.book_at[venue] = now

    def _trade(self, venue, trade_id, side, size, now):
        size = _positive(size)
        if size is None or side not in ("buy", "sell"):
            return
        if trade_id is not None:
            seen = self.trade_ids[venue]
            if trade_id in seen:
                return
            seen[trade_id] = now
            if len(seen) > 4000:
                for key in list(seen)[:2000]:
                    del seen[key]
        self.trades[venue].append((now, size if side == "buy" else -size))
        self.trade_at[venue] = now

    def ingest(self, venue, packet, now=None):
        if venue not in VENUES or not isinstance(packet, dict):
            return
        now = time.time() if now is None else float(now)
        with self.lock:
            if venue == "coinbase":
                kind = packet.get("type")
                if packet.get("product_id") != "BTC-USD":
                    return
                if kind == "snapshot":
                    self._book(venue, _levels(packet.get("bids")),
                               _levels(packet.get("asks")), now, snapshot=True)
                elif kind == "l2update":
                    bids, asks = {}, {}
                    for change in packet.get("changes", []):
                        if not isinstance(change, list) or len(change) != 3:
                            continue
                        side, price, qty = change
                        try:
                            p, q = float(price), float(qty)
                        except (TypeError, ValueError, OverflowError):
                            continue
                        if math.isfinite(p) and p > 0 and math.isfinite(q) and q >= 0:
                            (bids if side == "buy" else asks if side == "sell" else {})[p] = q
                    self._book(venue, bids, asks, now, snapshot=False)
                elif kind in ("match", "last_match"):
                    # Coinbase match.side describes the resting MAKER order.
                    maker = packet.get("side")
                    taker = "buy" if maker == "sell" else "sell" if maker == "buy" else None
                    self._trade(venue, packet.get("trade_id"), taker, packet.get("size"), now)
            elif venue == "kraken":
                channel = packet.get("channel")
                for item in packet.get("data", []) if isinstance(packet.get("data"), list) else []:
                    if not isinstance(item, dict) or item.get("symbol") != "BTC/USD":
                        continue
                    if channel == "book":
                        is_snapshot = packet.get("type") == "snapshot"
                        # Kraken qty=0 removes the level.
                        def updates(key):
                            entries = {}
                            for row in item.get(key, []):
                                if not isinstance(row, dict):
                                    continue
                                p = _positive(row.get("price"))
                                try:
                                    qty = float(row.get("qty"))
                                except (ValueError, TypeError, OverflowError):
                                    continue
                                if p is not None and math.isfinite(qty) and qty >= 0:
                                    entries[p] = qty
                            return entries
                        self._book(venue, updates("bids"), updates("asks"), now,
                                   snapshot=is_snapshot)
                    elif channel == "trade":
                        key = item.get("trade_id")
                        if key is None:
                            key = (item.get("timestamp"), item.get("price"),
                                   item.get("qty"), item.get("side"))
                        self._trade(venue, key, item.get("side"), item.get("qty"), now)
            elif venue == "bitstamp":
                channel, data = packet.get("channel"), packet.get("data")
                if not isinstance(data, dict):
                    return
                if channel == "order_book_btcusd" and packet.get("event") == "data":
                    self._book(venue, _levels(data.get("bids")),
                               _levels(data.get("asks")), now, snapshot=True)
                elif channel == "live_trades_btcusd" and packet.get("event") == "trade":
                    kind = data.get("type")
                    side = "buy" if kind in (0, "0") else "sell" if kind in (1, "1") else None
                    self._trade(venue, data.get("id"), side,
                                data.get("amount", data.get("amount_str")), now)

    def snapshot(self, now=None):
        now = time.time() if now is None else float(now)
        with self.lock:
            ready = [v for v in VENUES
                     if self.books[v] is not None
                     and self.book_at[v] is not None and 0 <= now-self.book_at[v] <= 12
                     and self.trade_at[v] is not None and 0 <= now-self.trade_at[v] <= 20]
            def totals(venue, window, flow):
                entries = self.ofi[venue] if flow else self.trades[venue]
                recent = [e for e in entries if 0 <= now-e[0] <= window]
                signed = sum(e[1] for e in recent)
                gross = sum(e[2] if flow else abs(e[1]) for e in recent)
                return signed, gross, len(recent), (min(e[0] for e in recent) if recent else None)
            ofi30 = [totals(v, 30, True) for v in ready]
            ofi60 = [totals(v, 60, True) for v in ready]
            cvd30 = [totals(v, 30, False) for v in ready]
            cvd60 = [totals(v, 60, False) for v in ready]
            cvd180 = [totals(v, 180, False) for v in ready]
            def ratio(parts):
                signed = sum(p[0] for p in parts)
                gross = sum(p[1] for p in parts)
                return signed/gross if gross else 0.
            by_venue = {}
            for i, v in enumerate(ready):
                a, b = (ofi30[i][0]/ofi30[i][1] if ofi30[i][1] else 0,
                        cvd60[i][0])
                by_venue[v] = {"ofi_30": a, "cvd_60": b}
            o30, o60 = ratio(ofi30), ratio(ofi60)
            c30, c60 = ratio(cvd30), ratio(cvd60)
            supported = (len(ready) >= 2 and
                         sum(p[2] for p in ofi60) >= 12 and
                         sum(p[2] for p in cvd60) >= 12 and
                         any(p[3] is not None and p[3] <= now-30 for p in ofi60) and
                         any(p[3] is not None and p[3] <= now-30 for p in cvd60))
            up_venues = sum(d["ofi_30"] > 0 and d["cvd_60"] > 0 for d in by_venue.values())
            down_venues = sum(d["ofi_30"] < 0 and d["cvd_60"] < 0 for d in by_venue.values())
            direction = None
            if supported and o30 > .08 and o60 > .04 and c30 > .08 and c60 > .04 and up_venues >= 2:
                direction = "UP"
            elif supported and o30 < -.08 and o60 < -.04 and c30 < -.08 and c60 < -.04 and down_venues >= 2:
                direction = "DOWN"
            return {
                "available": supported, "venues": ready,
                "ofi_30": round(o30, 5), "ofi_60": round(o60, 5),
                "cvd_30": round(sum(p[0] for p in cvd30), 8),
                "cvd_60": round(sum(p[0] for p in cvd60), 8),
                "cvd_180": round(sum(p[0] for p in cvd180), 8),
                "cvd_ratio_30": round(c30, 5), "cvd_ratio_60": round(c60, 5),
                "confirmed_direction": direction,
                "price_source": None, "source": "USD_constituent_trade_size_and_book_only",
            }


async def _session(flow, venue, stop):
    import websockets
    async with websockets.connect(URLS[venue], open_timeout=10, close_timeout=3,
                                  ping_interval=20, ping_timeout=15, max_size=4_000_000) as ws:
        if venue == "coinbase":
            await ws.send(json.dumps({"type": "subscribe", "product_ids": ["BTC-USD"],
                                      "channels": ["level2", "matches"]}))
        elif venue == "kraken":
            await ws.send(json.dumps({"method": "subscribe",
                                      "params": {"channel": "book", "symbol": ["BTC/USD"],
                                                 "depth": 10, "snapshot": True}}))
            await ws.send(json.dumps({"method": "subscribe",
                                      "params": {"channel": "trade", "symbol": ["BTC/USD"],
                                                 "snapshot": False}}))
        else:
            for channel in ("order_book_btcusd", "live_trades_btcusd"):
                await ws.send(json.dumps({"event": "bts:subscribe",
                                          "data": {"channel": channel}}))
        while not stop.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
            except asyncio.TimeoutError:
                break
            packet = json.loads(raw)
            flow.ingest(venue, packet)


def _venue_worker(flow, venue, stop):
    backoff = 2
    while not stop.is_set():
        flow.reset(venue)
        try:
            asyncio.run(_session(flow, venue, stop))
            backoff = 2
        except Exception:
            backoff = min(60, backoff * 2)
        finally:
            flow.reset(venue)
        stop.wait(backoff)


def start_flow_workers(flow, stop):
    threads = []
    for venue in VENUES:
        thread = threading.Thread(target=_venue_worker, args=(flow, venue, stop),
                                  name="usd-constituent-" + venue, daemon=True)
        thread.start()
        threads.append(thread)
    return threads


def _bars_usable(bars, now, minimum, seconds):
    if not isinstance(bars, list) or len(bars) < minimum:
        return False
    tail = bars[-minimum:]
    try:
        return all(b["source"] == BRTI_SOURCE and b.get("volume") is None
                   and all(math.isfinite(float(b[k])) and float(b[k]) > 0
                           for k in ("open", "high", "low", "close"))
                   for b in tail) and all(b["t"]-a["t"] == seconds
                                          for a, b in zip(tail, tail[1:])) and (
                   0 <= now-(tail[-1]["t"]+seconds) < seconds+30)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _regime(bars, five):
    closes = [b["close"] for b in bars[-46:]]
    returns = [math.log(b/a) for a, b in zip(closes, closes[1:])]
    # Classify compression BEFORE the breakout candle, not using its impulse.
    short = statistics.pstdev(returns[-9:-1])
    long = statistics.pstdev(returns[:-1])
    prior = bars[-11:-1]
    previous = bars[-46:-11]
    tight_range = max(b["high"] for b in prior)-min(b["low"] for b in prior)
    older_ranges = [
        max(b["high"] for b in previous[i:i+10]) -
        min(b["low"] for b in previous[i:i+10])
        for i in range(0, len(previous)-9, 5)
    ]
    five_close = [b["close"] for b in five[-6:]]
    five_trend = five_close[-1]-five_close[0]
    efficiency = abs(closes[-1]-closes[-9]) / max(
        sum(abs(b-a) for a, b in zip(closes[-9:-1],closes[-8:])), 1e-9)
    compressed = bool(older_ranges and
                      tight_range <= statistics.median(older_ranges)*.75 and
                      short <= max(long*.85, 1e-9))
    if compressed:
        return "SQUEEZE"
    if efficiency >= .48 and abs(five_trend) > 0 and (
            (closes[-1]-closes[-9]) * five_trend > 0):
        return "TRENDING"
    return "CHOP"


def _setup(bars, strike, regime):
    last = bars[-1]
    pivot15 = bars[-16:-1]
    pivot60 = bars[-61:-1]
    levels = {
        "15m_high": max(b["high"] for b in pivot15),
        "15m_low": min(b["low"] for b in pivot15),
        "1h_high": max(b["high"] for b in pivot60),
        "1h_low": min(b["low"] for b in pivot60),
        "strike": float(strike),
    }
    if regime == "CHOP":
        return None, None, None
    cushion = last["close"] * .000015
    # Sweep/reclaim must occur within the same completed BRTI candle.
    for label in ("strike", "15m_low", "1h_low"):
        level = levels[label]
        if last["low"] < level-cushion and last["close"] > level+cushion:
            return "LIQUIDITY_SWEEP", "UP", level
    for label in ("strike", "15m_high", "1h_high"):
        level = levels[label]
        if last["high"] > level+cushion and last["close"] < level-cushion:
            return "LIQUIDITY_SWEEP", "DOWN", level
    if regime == "SQUEEZE":
        prior = bars[-11:-1]
        high, low = max(b["high"] for b in prior), min(b["low"] for b in prior)
        if last["close"] > high+cushion and last["open"] <= high:
            return "SQUEEZE_BREAKOUT", "UP", high
        if last["close"] < low-cushion and last["open"] >= low:
            return "SQUEEZE_BREAKOUT", "DOWN", low
    return None, None, None


def decide(market, brti, candles, five, book, flow, now):
    """One decision per active Kalshi contract. Quotes only constrain execution."""
    out = {"action": "WAIT", "setup_type": "NONE", "fair_prob": None,
           "entry_price": None, "take_profit": None, "invalidation_price": None,
           "side": None, "reason": "Awaiting authenticated BRTI", "regime": "CHOP",
           "price_source": "CF_BENCHMARKS_BRTI", "order_placed": False,
           "read_only": True, "prob_above": None, "prob_below": None,
           "forecast_available": False, "model_method": None}
    if not isinstance(market, dict):
        return out
    fair = brti_settlement_forecast(market, brti, candles, now)
    if not fair.get("available"):
        out["reason"] = fair.get("reason", "Unavailable BRTI settlement estimate")
        return out
    out.update(prob_above=fair["prob_above"], prob_below=fair["prob_below"],
               forecast_available=True, model_method=fair["method"],
               reason="Waiting for aligned 3-12 minute setup")
    remaining = market.get("close_ts", 0)-now
    if not 180 <= remaining <= 720:
        out["reason"] = "Outside 3-12 minute directional entry window"
        return out
    if not (_bars_usable(candles, now, 61, 60) and
            _bars_usable(five, now, 12, 300)):
        out["reason"] = "Need fresh continuous authenticated 1m and 5m BRTI structure"
        return out
    regime = _regime(candles, five)
    out["regime"] = regime
    setup, direction, invalidation = _setup(candles, market["target"], regime)
    if setup is None:
        out["reason"] = "No confirmed BRTI squeeze breakout or sweep/reclaim"
        return out
    if not isinstance(flow, dict) or not flow.get("available") or (
            flow.get("confirmed_direction") != direction):
        out["reason"] = "Sustained USD constituent OFI and 30s/60s taker CVD not aligned"
        return out
    if not current_book(book, market["ticker"], now, 15):
        out["reason"] = "Kalshi depth unavailable or stale"
        return out
    side = "YES" if direction == "UP" else "NO"
    buy = sweep(book, side, "BUY", 1.)
    if not buy["complete"]:
        out["reason"] = "No executable target-side ask depth"
        return out
    ask = buy["average_price"]
    if ask is None or not .18 <= ask <= .45:
        out["reason"] = "Target-side ask outside 18c-45c"
        return out
    probability = fair["prob_above"] if side == "YES" else fair["prob_below"]
    if probability <= ask + .01:
        out["reason"] = "BRTI fair value does not exceed target-side ask"
        return out
    out.update(action="BUY_" + side, setup_type=setup, fair_prob=probability,
               entry_price=round(ask, 4),
               take_profit=min(.99, round(max(.62, probability), 2)),
               invalidation_price=float(invalidation), side=side,
               reason="BRTI structure, 3-12m window, 18c-45c ask and sustained USD flow aligned")
    return out
