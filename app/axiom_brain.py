"""Single live AXIOM decision brain: authenticated BRTI price + USD constituent flow."""
from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import logging
import math
import statistics
import threading
import time

from .orderbook import current_book, sweep
from .settlement_probability import forecast as brti_settlement_forecast, _student_t_cdf, NU

VENUES = ("coinbase", "kraken", "bitstamp")
URLS = {
    "coinbase": "wss://ws-feed.exchange.coinbase.com",
    "kraken": "wss://ws.kraken.com/v2",
    "bitstamp": "wss://ws.bitstamp.net",
}
BRTI_SOURCE = "cfbenchmarks_brti_authenticated_live"
# 1m log-return sigma; conservative temporary ceiling until 24h IV history.
COLD_START_IV_MAX_1M = 0.0012
LOG = logging.getLogger(__name__)
CONSTITUENT_MAX_FRAME_BYTES = 16 * 1024 * 1024


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




def _near_depth(book):
    """USD venue midpoint is used ONLY for dispersion/depth calculations."""
    bids, asks = book["bids"], book["asks"]
    if not bids or not asks:
        return None, None, None
    bid, ask = max(bids), min(asks)
    if bid <= 0 or bid >= ask:
        return None, None, None
    mid = (bid + ask)/2
    return (mid,
            sum(q for p, q in bids.items() if p >= mid*(1-.001)),
            sum(q for p, q in asks.items() if p <= mid*(1+.001)))


def _trade_autocorr(rows):
    """Lag-one Pearson sign autocorrelation of at most the last 200 trades."""
    signs = [1 if size > 0 else -1 for _, size, _ in
             sorted(rows, key=lambda r:(r[0],r[2]))[-200:]]
    if len(signs) < 30:
        return None
    x, y = signs[:-1], signs[1:]
    ax, ay = statistics.mean(x), statistics.mean(y)
    cov = sum((a-ax)*(b-ay) for a,b in zip(x,y))
    vx = sum((a-ax)**2 for a in x)
    vy = sum((b-ay)**2 for b in y)
    return cov/math.sqrt(vx*vy) if vx > 0 and vy > 0 else None


def _depth_thinning(samples, now, side):
    """Reference is the preceding 30-300s; no fabricated baseline."""
    column = 0 if side == "bid" else 1
    older = [(t,r[column]) for t,*r in samples if 30 <= now-t <= 300]
    # The tuple above expands samples as (t, [bid_depth,ask_depth]).
    if len(older) < 20 or older[-1][0]-older[0][0] < 60:
        return None, False
    normal = statistics.median(val for _,val in older)
    recent = [(t, row[column]) for t,*row in samples if 0 <= now-t <= 15]
    if normal <= 0 or len(recent) < 8 or recent[-1][0] < now-2 or (
            recent[-1][0] - recent[0][0] < 14):
        return None, False
    current = recent[-1][1]
    thin = current < .5*normal and max(v for _,v in recent) < .5*normal
    # Remaining under 0.5x continuously also guarantees no >1.5x refill.
    return current/normal, thin


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
        self.depth_samples = {v: deque(maxlen=1200) for v in VENUES}
        self.trade_sequence = 0
        # Transport diagnostics never feed prices, votes, or paper decisions.
        self.worker_status = {v: "STARTING" for v in VENUES}
        self.connected_at = {v: None for v in VENUES}
        self.last_error = {v: None for v in VENUES}
        self.last_error_at = {v: None for v in VENUES}
        self.last_valid_book_at = {v: None for v in VENUES}
        self.last_valid_trade_at = {v: None for v in VENUES}

    def connection_event(self, venue, status, *, error=None, now=None):
        at = time.time() if now is None else float(now)
        with self.lock:
            self.worker_status[venue] = status
            if status == "SUBSCRIPTION_SENT":
                self.connected_at[venue] = at
            if error is not None:
                self.last_error[venue] = f"{type(error).__name__}: {str(error)[:220]}"
                self.last_error_at[venue] = at

    def diagnostics(self, now=None):
        now = time.time() if now is None else float(now)
        with self.lock:
            result = {}
            for venue in VENUES:
                status = self.worker_status[venue]
                book_at, trade_at = self.book_at[venue], self.trade_at[venue]
                book_ready = book_at is not None and 0 <= now-book_at <= 12
                trade_ready = trade_at is not None and 0 <= now-trade_at <= 20
                connected_at = self.connected_at[venue]
                def age(at):
                    return None if at is None else round(max(0., now-at), 2)
                if status == "BACKOFF":
                    problem = self.last_error[venue] or "WebSocket reconnecting"
                elif (status == "SUBSCRIPTION_SENT" and connected_at is not None
                      and now-connected_at > 30):
                    problem = ("No recent valid order book" if not book_ready else
                               "No recent accepted trades" if not trade_ready else None)
                else:
                    problem = None
                result[venue] = {
                    "connection_status": status, "connection_at": connected_at,
                    "last_error": self.last_error[venue],
                    "last_error_at": self.last_error_at[venue],
                    "last_valid_book_at": self.last_valid_book_at[venue],
                    "last_valid_book_age_seconds": age(self.last_valid_book_at[venue]),
                    "last_trade_at": self.last_valid_trade_at[venue],
                    "last_trade_age_seconds": age(self.last_valid_trade_at[venue]),
                    "book_ready": book_ready, "trade_ready": trade_ready,
                    "ready": book_ready and trade_ready,
                    "health_error": problem,
                }
            return result

    def reset(self, venue):
        with self.lock:
            self.books[venue] = None
            self.book_at[venue] = None
            self.trade_at[venue] = None
            self.ofi[venue].clear()
            self.trades[venue].clear()
            self.trade_ids[venue].clear()
            self.depth_samples[venue].clear()

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
                                    reverse=(side == "bids"))[:200])
        if max(new["bids"]) >= min(new["asks"]):
            self.reset(venue)
            return
        if old is not None:
            pressure, gross = _pressure(old, new)
            if gross:
                self.ofi[venue].append((now, pressure, gross))
        self.books[venue] = new
        self.book_at[venue] = now
        self.last_valid_book_at[venue] = now
        mid, bid_depth, ask_depth = _near_depth(new)
        if mid is not None:
            samples = self.depth_samples[venue]
            tick = int(now)
            if samples and samples[-1][0] == tick:
                samples[-1] = (tick, bid_depth, ask_depth)
            else:
                samples.append((tick, bid_depth, ask_depth))

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
        self.trade_sequence += 1
        self.trades[venue].append((now, size if side == "buy" else -size,
                                   self.trade_sequence))
        self.trade_at[venue] = now
        self.last_valid_trade_at[venue] = now

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

            # Current USD venue mids never enter BRTI price/settlement.
            book_ready = [v for v in VENUES if self.books[v] is not None
                          and self.book_at[v] is not None
                          and 0 <= now-self.book_at[v] <= 12]
            venue_mids, depth, depletion, top_obi = {}, {}, {}, {}
            for v in book_ready:
                mid, bid_sz, ask_sz = _near_depth(self.books[v])
                if mid is None:
                    continue
                venue_mids[v] = mid
                depth[v] = {"bid_10bps_btc": bid_sz, "ask_10bps_btc": ask_sz,
                            "total_10bps_btc": bid_sz + ask_sz}
                top_obi[v] = ((bid_sz-ask_sz)/(bid_sz+ask_sz)
                              if bid_sz+ask_sz else None)
                depletion[v] = {}
                for name in ("bid", "ask"):
                    ratio_, persistent = _depth_thinning(self.depth_samples[v], now, name)
                    depletion[v][name] = {"ratio_to_normal": ratio_,
                                           "below_half_for_15s": persistent}
            median_mid, delta_venue, outlier = None, None, None
            if len(venue_mids) == 3:
                median_mid = statistics.median(venue_mids.values())
                outlier = max(venue_mids, key=lambda v: abs(venue_mids[v]-median_mid))
                delta_venue = abs(venue_mids[outlier]-median_mid)
            cvd90 = [totals(v, 90, False) for v in ready]
            cvd300 = [totals(v, 300, False) for v in ready]
            c90, c300 = ratio(cvd90), ratio(cvd300)
            trades200 = [e for v in ready for e in self.trades[v]
                         if 0 <= now-e[0] <= 300]
            rho = _trade_autocorr(trades200)
            bid_total = sum(d["bid_10bps_btc"] for d in depth.values())
            ask_total = sum(d["ask_10bps_btc"] for d in depth.values())
            advanced = {
                "OBI_spot": round((bid_total-ask_total)/(bid_total+ask_total), 6)
                            if bid_total+ask_total else None,
                "D_spot": round(bid_total+ask_total, 6) if depth else None,
                "D_spot_by_venue": depth,
                "depth_depletion": depletion,
                "CVD_norm_60s": round(c60, 6),
                "CVD_norm_90s": round(c90, 6),
                "CVD_norm_5m": round(c300, 6),
                "taker_buy_share_90s": round((1+c90)/2, 6)
                                        if sum(p[1] for p in cvd90)>0 else None,
                "taker_sell_share_90s": round((1-c90)/2, 6)
                                        if sum(p[1] for p in cvd90)>0 else None,
                "rho_trade": round(rho, 6) if rho is not None else None,
                "trade_count_90s": sum(p[2] for p in cvd90),
                "trade_count_5m": sum(p[2] for p in cvd300),
                "cvd_90s_span": (now-min((p[3] for p in cvd90 if p[3] is not None),
                                       default=now)),
                "cvd_5m_span": (now-min((p[3] for p in cvd300 if p[3] is not None),
                                     default=now)),
                "median_venue_spot": median_mid,
                "venue_midpoints": venue_mids,
                "outlier_venue": outlier,
                "delta_venue": delta_venue,
                "delta_venue_pct": (delta_venue/median_mid if median_mid else None),
                "synthetic_price": median_mid,
                "source_price_role": "dispersion_diagnostic_only",
            }
            return {
                "available": supported, "venues": ready,
                "ofi_30": round(o30, 5), "ofi_60": round(o60, 5),
                "cvd_30": round(sum(p[0] for p in cvd30), 8),
                "cvd_60": round(sum(p[0] for p in cvd60), 8),
                "cvd_60_span": (now-min((p[3] for p in cvd60 if p[3] is not None), default=now)),
                "cvd_180": round(sum(p[0] for p in cvd180), 8),
                "cvd_ratio_30": round(c30, 5), "cvd_ratio_60": round(c60, 5),
                "confirmed_direction": direction,
                "price_source": None, "source": "USD_constituent_trade_size_and_book_only",
                **advanced,
            }


async def _session(flow, venue, stop):
    import websockets
    async with websockets.connect(URLS[venue], open_timeout=10, close_timeout=3,
                                  ping_interval=20, ping_timeout=15,
                                  max_size=CONSTITUENT_MAX_FRAME_BYTES) as ws:
        if venue == "coinbase":
            await ws.send(json.dumps({"type": "subscribe", "product_ids": ["BTC-USD"],
                                      "channels": ["level2", "matches"]}))
        elif venue == "kraken":
            await ws.send(json.dumps({"method": "subscribe",
                                      "params": {"channel": "book", "symbol": ["BTC/USD"],
                                                 "depth": 100, "snapshot": True}}))
            await ws.send(json.dumps({"method": "subscribe",
                                      "params": {"channel": "trade", "symbol": ["BTC/USD"],
                                                 "snapshot": False}}))
        else:
            for channel in ("order_book_btcusd", "live_trades_btcusd"):
                await ws.send(json.dumps({"event": "bts:subscribe",
                                          "data": {"channel": channel}}))
        flow.connection_event(venue, "SUBSCRIPTION_SENT")
        while not stop.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
            except asyncio.TimeoutError as exc:
                raise TimeoutError(f"{venue} WebSocket received no data for 30s") from exc
            packet = json.loads(raw)
            flow.ingest(venue, packet)


def _venue_worker(flow, venue, stop):
    backoff = 2
    while not stop.is_set():
        flow.reset(venue)
        flow.connection_event(venue, "CONNECTING")
        try:
            asyncio.run(_session(flow, venue, stop))
            backoff = 2
        except Exception as exc:
            LOG.exception("Constituent WebSocket worker failed: venue=%s", venue)
            flow.connection_event(venue, "BACKOFF", error=exc)
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


def _et_windows(now):
    local = datetime.fromtimestamp(now, ZoneInfo("America/New_York"))
    if local.weekday() >= 5:
        return False, False
    minute = local.hour*60 + local.minute + local.second/60
    return (abs(minute-510) <= 5 or abs(minute-600) <= 5,
            570 <= minute < 690)


def _implied_minute_sigma(market, book, spot, now):
    """Invert model t-CDF on Kalshi YES midpoint; never use it as BTC price."""
    best = book.get("best", {}).get("YES", {})
    bid, ask = best.get("bid"), best.get("ask")
    if bid is None or ask is None or not 0 < bid <= ask < 1:
        return None
    prob = (bid+ask)/2
    strike = _positive(market.get("target"))
    remaining = _positive(market.get("close_ts")-now)
    if strike is None or spot <= 0 or remaining is None or remaining <= 60:
        return None
    distance = math.log(spot/strike)
    if abs(distance) < 1e-5 or abs(prob-.5) < .02 or distance*(prob-.5) <= 0:
        return None
    # Solve |t_score| by bisection; no new paid library/dependency.
    goal = max(.5000001, prob if prob > .5 else 1-prob)
    low, high = 0., 100.
    for _ in range(62):
        mid = (low+high)/2
        if _student_t_cdf(mid, NU) < goal:
            low = mid
        else:
            high = mid
    t_quantile = (low+high)/2
    effective_minutes = (remaining-40)/60
    sigma = abs(distance)*math.sqrt(NU/(NU-2))/(
        t_quantile*math.sqrt(effective_minutes))
    return sigma if 1e-7 <= sigma <= .05 and math.isfinite(sigma) else None


class MarketTape:
    """In-memory live Kalshi quote history, no extra study/service or database."""
    def __init__(self):
        self.lock = threading.RLock()
        self.mid_history = deque(maxlen=30)
        self.implied_24h = deque(maxlen=1600)
        self.last_vol_sample = None

    def observe(self, market, book, brti_spot, now):
        if not market or not current_book(book, market["ticker"], now, 15):
            return
        best = book.get("best", {}).get("YES", {})
        bid, ask = best.get("bid"), best.get("ask")
        if bid is None or ask is None or not 0 < bid <= ask < 1:
            return
        mid = (bid+ask)/2
        with self.lock:
            self.mid_history.append((now, market["ticker"], mid))
            while self.mid_history and self.mid_history[0][0] < now-30:
                self.mid_history.popleft()
            while self.implied_24h and self.implied_24h[0][0] < now-86400:
                self.implied_24h.popleft()
            if self.last_vol_sample is not None and now-self.last_vol_sample < 60:
                return
            sigma = _implied_minute_sigma(market, book, brti_spot, now)
            if sigma is not None:
                self.implied_24h.append((now, sigma))
                self.last_vol_sample = now

    def snapshot(self, market, now):
        with self.lock:
            mids = [(t,p) for t,ticker,p in self.mid_history
                    if ticker == market["ticker"] and 0 <= now-t <= 20]
            jump = None
            if len(mids) >= 2:
                new = mids[-1][1]
                candidates = [(new-old,t) for t,old in mids[:-1]
                              if 1 <= now-t <= 20]
                if candidates:
                    jump = max(candidates,key=lambda v:abs(v[0]))[0]
            samples = [(t,v) for t,v in self.implied_24h if 0 <= now-t <= 86400]
            enough = (len(samples) >= 100 and samples[-1][0]-samples[0][0] >= 23*3600)
            quartile = None
            if enough:
                ordered = sorted(v for _,v in samples)
                quartile = ordered[int((len(ordered)-1)*.25)]
            return {"mid_jump_20s": jump,
                    "implied_sigma_quartile_24h": quartile,
                    "implied_samples_24h": len(samples),
                    "implied_history_ready": enough}


def _brti_breakout(bars, direction):
    """Completed BRTI candle must actually break its prior 10m range."""
    last = bars[-1]
    prior = bars[-11:-1]
    high = max(b["high"] for b in prior)
    low = min(b["low"] for b in prior)
    cushion = .000015*last["close"]
    if direction == "UP" and last["open"] <= high and last["close"] > high+cushion:
        return high
    if direction == "DOWN" and last["open"] >= low and last["close"] < low-cushion:
        return low
    return None


def _exit_signal(open_side, book, flow, remaining):
    if open_side not in ("YES", "NO") or remaining > 150:
        return None
    bid = book.get("best",{}).get(open_side,{}).get("bid")
    if bid is None or bid >= .50:
        return None
    cvd = flow.get("CVD_norm_60s") if isinstance(flow,dict) else None
    reversed_flow = (cvd is not None and
                     ((open_side == "YES" and cvd < -.05) or
                      (open_side == "NO" and cvd > .05)))
    return {"action": "SELL_CANDIDATE", "side": open_side,
            "reason": "CVD_SIGN_FLIP" if reversed_flow else "TIME_STOP",
            "live_bid": bid, "paper_execution_performed": False}


def decide(market, brti, candles, five, book, flow, now, *,
           tape=None, open_side=None):
    """One read-only direction; exchange prices only measure dispersion."""
    out = {"action": "WAIT", "setup_type": "NONE", "fair_prob": None,
           "fair_prob_side": "YES", "entry_price": None, "take_profit": None,
           "invalidation_rule": None, "invalidation_price": None,
           "kill_switch_triggered": False, "exit_signal": None,
           "side": None, "reason": "Awaiting authenticated BRTI",
           "regime": "CHOP", "price_source": "CF_BENCHMARKS_BRTI",
           "order_placed": False, "read_only": True,
           "prob_above": None, "prob_below": None,
           "forecast_available": False, "model_method": None}
    if not isinstance(market, dict):
        return out
    # Existing paper positions still receive a read-only time-stop signal
    # even if settlement probability is temporarily unavailable.
    remaining = market["close_ts"]-now
    if current_book(book,market["ticker"],now,15):
        out["exit_signal"] = _exit_signal(open_side,book,flow,remaining)
        if out["exit_signal"]:
            out["kill_switch_triggered"] = True
            out["reason"] = out["exit_signal"]["reason"]
            return out
    fair = brti_settlement_forecast(market, brti, candles, now)
    if not fair.get("available"):
        out["reason"] = fair.get("reason", "Authenticated BRTI unavailable")
        return out
    out.update(prob_above=fair["prob_above"], prob_below=fair["prob_below"],
               fair_prob=fair["prob_above"], forecast_available=True,
               model_method=fair["method"], reason="No qualifying Phase 2 setup")
    macro, twap = _et_windows(now)
    if macro:
        out.update(kill_switch_triggered=True,
                   reason="08:30/10:00 ET macro blackout (+/-5 minutes)")
        return out
    if not 180 <= remaining <= 720:
        out["reason"] = "Outside 3-12 minute entry window"
        return out
    # Short-history setups still require fresh, contiguous authentic BRTI
    # candles; they do not require the 60-minute compression/regime window.
    if not _bars_usable(candles,now,31,60):
        out["reason"] = "Awaiting fresh contiguous BRTI minute history"
        return out
    structure_ready = (_bars_usable(candles,now,61,60) and
                       _bars_usable(five,now,12,300))
    out["regime"] = _regime(candles,five) if structure_ready else "WARMING"
    if not current_book(book,market["ticker"],now,15):
        out["reason"] = "Stale or incomplete Kalshi book"
        return out
    if not isinstance(flow,dict) or not flow.get("available"):
        out["reason"] = "USD constituent order flow not healthy"
        return out
    spot = _positive(brti.get("latest_value_usd"))
    if spot is None:
        return out
    history = tape.snapshot(market,now) if tape else {}
    delta_venue = flow.get("delta_venue")
    venue_pct = flow.get("delta_venue_pct")
    outlier = flow.get("outlier_venue")
    if flow.get("synthetic_price") is not None:
        out["delta_BRTI"] = spot - flow["synthetic_price"]
    out["delta_venue"] = delta_venue
    out["OBI_spot"] = flow.get("OBI_spot")
    out["D_spot"] = flow.get("D_spot")
    out["CVD_norm_90s"] = flow.get("CVD_norm_90s")
    out["rho_trade"] = flow.get("rho_trade")
    # Candidate selection is deterministic and mutually exclusive.
    setup = None
    direction = None
    invalidation = None
    details = {}
    if twap:
        # Institutional TWAP window: no contrarian sweep fades.
        cvd5 = flow.get("CVD_norm_5m")
        rho = flow.get("rho_trade")
        if (abs(spot/market["target"]-1) <= .0012 and
            flow.get("cvd_5m_span",0) >= 240 and
            cvd5 is not None and abs(cvd5) > .28 and
            rho is not None and rho > .22):
            setup = "US_SESSION_TWAP_DRIFT"
            direction = "UP" if cvd5 > 0 else "DOWN"
            invalidation = {"type": "BRTI_STRIKE_BAND_OR_CVD_FLIP",
                            "strike": market["target"], "max_deviation_bps":12,
                            "cvd_window_seconds":300}
            details = {"cvd_norm_5m": cvd5, "rho_trade":rho}
    else:
        # Sweep fade is explicitly contrarian to a Kalshi quote jump,
        # not contrarian to a fabricated exchange-based BTC price.
        jump = history.get("mid_jump_20s")
        if (jump is not None and abs(jump) >= .14 and
            venue_pct is not None and venue_pct > .0008 and
            delta_venue is not None and
            abs(out["delta_BRTI"]) < .35*delta_venue and
            outlier in (flow.get("depth_depletion") or {})):
            venue_mid = flow["venue_midpoints"][outlier]
            median = flow["synthetic_price"]
            outlier_up = venue_mid > median
            # Kalshi YES quote movement must match the swept spot venue.
            if ((jump > 0 and outlier_up) or (jump < 0 and not outlier_up)):
                depleted = ("ask" if outlier_up else "bid")
                depletion = flow["depth_depletion"][outlier][depleted]
                if depletion["below_half_for_15s"]:
                    setup = "SINGLE_VENUE_SWEEP_FADE"
                    direction = "DOWN" if jump > 0 else "UP"
                    invalidation = {"type":"BRTI_CONFIRMED_VENUE_EXTENSION",
                                    "venue":outlier,
                                    "brti_reference_usd":spot,
                                    "beyond_outlier_usd":venue_mid}
                    details = {"kalshi_mid_jump_20s":round(jump,4),
                               "depth_ratio":depletion["ratio_to_normal"]}
        if setup is None and structure_ready and out["regime"] == "SQUEEZE":
            sigma_5s = _positive(brti.get("brti_sigma_5s_3m"))
            sigma_1m = _implied_minute_sigma(market, book, spot, now)
            quartile = _positive(history.get("implied_sigma_quartile_24h"))
            iv_ready = history.get("implied_history_ready") is True
            # No 24h samples yet: remain filtered, not permanently blocked or
            # allowed through unchecked. Use only measured BRTI volatility.
            brti_sigma = _positive(fair.get("volatility_1m"))
            iv_ceiling = (quartile if iv_ready else
                          min(COLD_START_IV_MAX_1M, .85*brti_sigma)
                          if brti_sigma is not None else None)
            out["iv_guard"] = "24h_bottom_quartile" if iv_ready else "cold_start_ceiling"
            out["iv_ceiling_1m"] = iv_ceiling
            out["implied_sigma_1m"] = sigma_1m
            ratio_depth = [
                x["ratio_to_normal"]
                for side in (flow.get("depth_depletion") or {}).values()
                for x in side.values()
                if x["ratio_to_normal"] is not None and x["ratio_to_normal"]>0]
            if (sigma_5s is not None and sigma_1m is not None and
                iv_ceiling is not None and sigma_1m <= iv_ceiling and
                ratio_depth and flow.get("cvd_90s_span",0) >= 75 and
                flow.get("trade_count_90s",0) >= 30):
                thinning = min(2.,max(1.,1./statistics.median(ratio_depth)))
                r_sigma = sigma_5s*math.sqrt(12)/sigma_1m*thinning
                out["R_sigma"] = round(r_sigma,6)
                if r_sigma > 1.65:
                    share_up = flow.get("taker_buy_share_90s") or 0
                    share_dn = flow.get("taker_sell_share_90s") or 0
                    direction = ("UP" if share_up >= .65 else
                                 "DOWN" if share_dn >= .65 else None)
                    boundary = _brti_breakout(candles,direction)
                    if boundary is not None:
                        setup = "COMPRESSION_BREAKOUT"
                        invalidation = {"type":"BRTI_CLOSE_BACK_INSIDE_RANGE",
                                        "level_usd":boundary,
                                        "direction":direction}
                        details = {"R_sigma":round(r_sigma,6),
                                   "implied_sigma_1m":sigma_1m,
                                   "implied_sigma_q25_24h":quartile if iv_ready else None,
                                   "implied_sigma_ceiling_1m":iv_ceiling,
                                   "iv_guard":out["iv_guard"],
                                   "taker_share_90s":max(share_up,share_dn)}
    if setup is None or direction is None:
        out["reason"] = ("No qualified TWAP drift" if twap else
                         "No qualified compression breakout or one-venue sweep fade")
        return out
    side = "YES" if direction == "UP" else "NO"
    ask_fill = sweep(book,side,"BUY",1.)
    ask = ask_fill.get("average_price")
    lo,hi = ((.18,.35) if setup == "SINGLE_VENUE_SWEEP_FADE" else
             (.28,.44) if setup == "US_SESSION_TWAP_DRIFT" else (.18,.45))
    if not ask_fill["complete"] or ask is None or not lo <= ask <= hi:
        out["reason"] = "Target-side Kalshi ask outside setup-specific entry range"
        return out
    probability = fair["prob_above"] if side == "YES" else fair["prob_below"]
    # Preserve Phase 1's positive after-fee entry rule, without a flat edge wall.
    import decimal
    dprice = decimal.Decimal(str(ask))
    fee = float((decimal.Decimal(".07")*dprice*(1-dprice)*100).to_integral_value(
        rounding=decimal.ROUND_CEILING)/100)
    if probability <= ask+fee:
        out["reason"] = "BRTI fair probability does not cover ask and entry fee"
        return out
    out.update(action="BUY_"+side, setup_type=setup,
               fair_prob=probability, fair_prob_side=side,
               entry_price=round(ask,4),
               take_profit=round(max(.60,min(.85,probability)),4),
               invalidation_rule=invalidation, side=side,
               details=details,
               reason="Phase 2 setup and BRTI fair value aligned")
    return out
