"""Read-only Binance BTCUSDT spot trade stream and perpetual funding rate.

Binance spot USDT price is NOT CF Benchmarks BRTI (Kalshi settlement).
Spot trade event time, local receipt time, and Kalshi REST receipt time are
distinct. No inferred fills, latency arbitrage, real orders or account access.
Unreachable/geo-blocked Binance source is explicitly UNAVAILABLE.
"""
from __future__ import annotations

from collections import deque
import statistics
import json
import math
import os
import threading
import time

import requests
from websockets.sync.client import connect

SPOT_WS = "wss://data-stream.binance.vision/ws/btcusdt@aggTrade"
FUNDING_API = "https://fapi.binance.com/fapi/v1/premiumIndex"
MAX_EVENT_AGE_SECONDS = 4.0
MAX_FUNDING_AGE_SECONDS = 180.0


def finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def invalid(reason, status="UNAVAILABLE"):
    return {"status":status,"reason":reason,"spot_price":None,
            "spot_trade_at":None,"spot_received_at":None,
            "funding_status":"UNAVAILABLE","funding_rate":None,
            "funding_percent":None,"funding_bias":"UNKNOWN",
            "funding_next_at":None,"funding_source_at":None,
            "funding_mark_index_basis_bps":None,
            "settlement_reference":False,"orders_placed":False}


class BinanceTelemetry:
    def __init__(self,enabled=False):
        self.enabled=bool(enabled)
        self.lock=threading.RLock()
        self.trades=deque(maxlen=16000)
        self.funding=None
        self.connected=False
        self.last_error=None
        self.last_funding_error=None

    def note_connection(self,connected=False,error=None):
        with self.lock:
            self.connected=bool(connected)
            self.last_error=error

    def observe_trade(self,event,received_at):
        """Validate one real aggregate-trade frame with exchange timestamp."""
        ts=finite(event.get("T")) if isinstance(event,dict) else None
        price=finite(event.get("p")) if isinstance(event,dict) else None
        event_ms=finite(event.get("E")) if isinstance(event,dict) else None
        received=finite(received_at)
        trade_id=event.get("a") if isinstance(event,dict) else None
        if (not isinstance(event,dict) or event.get("e")!="aggTrade" or
                event.get("s")!="BTCUSDT" or isinstance(trade_id,bool) or
                not isinstance(trade_id,int) or trade_id<0 or
                ts is None or event_ms is None or received is None or
                price is None or not 100<price<10_000_000 or
                not 1_500_000_000_000<ts<4_000_000_000_000 or
                abs(event_ms-ts)>20_000 or
                not -2 <= received-ts/1000 <= MAX_EVENT_AGE_SECONDS):
            return False
        # Binance aggTrade 'm' identifies whether buyer was maker; this
        # distinguishes actual taker-signed volume from candle shape guesses.
        qty=finite(event.get("q"))
        maker=event.get("m")
        signed=(-qty if maker else qty) if qty is not None and qty>0 and isinstance(maker,bool) else None
        with self.lock:
            if self.trades and (ts < self.trades[-1]["timestamp_ms"] or
                                trade_id<=self.trades[-1]["id"]):
                return False
            self.trades.append({"id":trade_id,"timestamp_ms":int(ts),
                                "received_at":received,"price":price,
                                "quantity":qty if qty is not None and qty>0 else None,
                                "signed_quantity":signed})
        return True

    def observe_funding(self,payload,received_at):
        """Read published perpetual funding; no inference from funding sign."""
        if not isinstance(payload,dict) or payload.get("symbol")!="BTCUSDT":
            return False
        rate=finite(payload.get("lastFundingRate"))
        source=finite(payload.get("time"))
        next_ms=finite(payload.get("nextFundingTime"))
        mark=finite(payload.get("markPrice"))
        index=finite(payload.get("indexPrice"))
        received=finite(received_at)
        if (None in (rate,source,next_ms,received,mark,index)
                or abs(rate)>0.05 or not 100<mark<10_000_000
                or not 100<index<10_000_000
                or not 1_500_000_000_000<source<4_000_000_000_000
                or not -2 <= received-source/1000 <= 30
                or not source-86400000 <= next_ms <= source+86400000):
            return False
        with self.lock:
            self.funding={"rate":rate,"source_at":source/1000,
                          "received_at":received,"next_at":next_ms/1000,
                          "basis_bps":10_000*(mark/index-1)}
            self.last_funding_error=None
        return True

    def note_funding_error(self,error_kind):
        with self.lock:
            self.last_funding_error=error_kind

    def snapshot(self,now=None):
        now=time.time() if now is None else now
        if not self.enabled:
            return invalid("Binance telemetry disabled","DISABLED")
        with self.lock:
            latest=self.trades[-1].copy() if self.trades else None
            recent=[p.copy() for p in self.trades]
            funding=self.funding.copy() if self.funding else None
            err=self.last_error
            f_err=self.last_funding_error
            connected=self.connected
        fresh=(latest is not None and -2<=now-latest["timestamp_ms"]/1000<=MAX_EVENT_AGE_SECONDS
               and -2<=now-latest["received_at"]<=MAX_EVENT_AGE_SECONDS)
        f_fresh=(funding is not None and -2<=now-funding["source_at"]<=MAX_FUNDING_AGE_SECONDS
                 and -2<=now-funding["received_at"]<=MAX_FUNDING_AGE_SECONDS)
        status="STREAMING" if fresh else "STALE" if latest else "UNAVAILABLE"
        direction=("LONGS_PAY_SHORTS" if funding["rate"]>0 else
                   "SHORTS_PAY_LONGS" if funding["rate"]<0 else "NEUTRAL") if f_fresh else "UNKNOWN"
        recent_2m=[p for p in recent if 0<=now-p["timestamp_ms"]/1000<=120 and
                   p.get("signed_quantity") is not None]
        recent_5m=[p for p in recent if 0<=now-p["timestamp_ms"]/1000<=300 and
                   p.get("signed_quantity") is not None]
        def signed_flow(rows):
            total=sum(p["quantity"] for p in rows)
            value=sum(p["signed_quantity"] for p in rows)
            return {"volume_btc":round(total,7),
                    "cvd_btc":round(value,7),
                    "taker_imbalance":round(value/total,6) if total>0 else None,
                    "trades_seen":len(rows),
                    "window_observed_seconds":round(
                        (rows[-1]["timestamp_ms"]-rows[0]["timestamp_ms"])/1000,3
                    ) if len(rows)>1 else 0}
        two=signed_flow(recent_2m)
        five=signed_flow(recent_5m)
        notionals=sorted(p["quantity"]*p["price"] for p in recent_5m)
        high_threshold=notionals[int(.99*(len(notionals)-1))] if len(notionals)>=50 else None
        large=[p for p in recent_5m if high_threshold is not None and
               p["quantity"]*p["price"]>=high_threshold]
        large_net=sum(p["signed_quantity"]*p["price"] for p in large)
        return {
            "cvd_status":"OBSERVED_SIGNED_AGGTRADES" if recent_2m else "UNAVAILABLE",
            "cvd_2m":two,"cvd_5m":five,
            "large_trade_activity":{"status":"OBSERVED_PERCENTILE_PROXY" if high_threshold else "UNAVAILABLE",
                "large_print_count":len(large),
                "net_taker_usdt":round(large_net,3) if high_threshold else None,
                "large_trade_threshold_usdt":round(high_threshold,3) if high_threshold else None,
                "identity_known":False,"is_verified_whale_wallet":False},
            "status":status,
            "reason":("Fresh Binance BTCUSDT public spot trade" if fresh else
                       err or "No fresh Binance BTCUSDT trade"),
            "connected":connected,
            "spot_price":latest["price"] if fresh else None,
            "spot_trade_at":latest["timestamp_ms"]/1000 if fresh else None,
            "spot_received_at":latest["received_at"] if fresh else None,
            "spot_trade_id":latest["id"] if fresh else None,
            "spot_source_age_seconds":round(now-latest["timestamp_ms"]/1000,3) if fresh else None,
            "spot_source_receipt_ms":round((latest["received_at"]-
                                     latest["timestamp_ms"]/1000)*1000,1) if fresh else None,
            "funding_status":"LIVE" if f_fresh else "STALE" if funding else "UNAVAILABLE",
            "funding_rate":funding["rate"] if f_fresh else None,
            "funding_percent":round(funding["rate"]*100,6) if f_fresh else None,
            "funding_bias":direction,
            "funding_next_at":funding["next_at"] if f_fresh else None,
            "funding_source_at":funding["source_at"] if f_fresh else None,
            "funding_mark_index_basis_bps":round(funding["basis_bps"],3) if f_fresh else None,
            "funding_reason":f_err if not f_fresh else "Binance BTCUSDT USD-M perpetual published funding",
            "funding_direction_is_prediction":False,
            "settlement_reference":False,"orders_placed":False,
        }


def spot_worker(telemetry, stop_event):
    """Reconnect a public Binance spot WS; never block the AXIOM market poll."""
    delay=1.
    while not stop_event.is_set():
        try:
            with connect(SPOT_WS,open_timeout=8,close_timeout=2,max_size=262144) as ws:
                telemetry.note_connection(connected=True)
                delay=1.
                while not stop_event.is_set():
                    try:
                        frame=ws.recv(timeout=2)
                    except TimeoutError:
                        continue
                    if frame is None:
                        break
                    try:
                        packet=json.loads(frame)
                    except (ValueError,TypeError):
                        continue
                    telemetry.observe_trade(packet,time.time())
        except Exception as exc:
            telemetry.note_connection(error=type(exc).__name__)
        finally:
            telemetry.note_connection(connected=False,error=telemetry.last_error)
        if stop_event.wait(delay):
            break
        delay=min(delay*2,60.)


def funding_worker(telemetry,stop_event,interval=60):
    """Separate funding sampler so futures rate-limit/geofence cannot stall WS."""
    session=requests.Session()
    try:
        while not stop_event.is_set():
            try:
                response=session.get(FUNDING_API,params={"symbol":"BTCUSDT"},timeout=6)
                response.raise_for_status()
                if not telemetry.observe_funding(response.json(),time.time()):
                    telemetry.note_funding_error("InvalidOrStaleFundingPayload")
            except (requests.RequestException,ValueError,TypeError) as exc:
                telemetry.note_funding_error(type(exc).__name__)
            if stop_event.wait(interval):
                break
    finally:
        session.close()
