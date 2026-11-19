"""Read-only BRTI WebSocket reference, receipt provenance and freshness.

No real orders, portfolio access, or historical backfill. The BTC spot based
forecast intentionally remains unchanged: live BRTI is a separate nonvoting
reference lane until forward accuracy is verified. No raw index feed is
published to disk or to the browser.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import math
import os
import threading
import time

WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
WS_PATH = "/trade-api/ws/v2"
CHANNELS = ("cfbenchmarks_value", "cfbenchmarks_value_5hz")
MAX_LAG_MS = 15000
MAX_RECEIPT_AGE_MS = 15000


def _timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid index timestamp type")
    if not math.isfinite(value) or not 1_000_000_000_000 <= value <= 9_999_999_999_999:
        raise ValueError("Invalid Unix millisecond index timestamp")
    return int(value)


def _price(value):
    if value is None or isinstance(value, bool):
        raise ValueError("Missing reference price")
    try:
        amount = Decimal(str(value))
    except (ValueError, InvalidOperation, TypeError):
        raise ValueError("Malformed index value") from None
    if not amount.is_finite() or not Decimal("100") < amount < Decimal("10000000"):
        raise ValueError("Invalid reference index value")
    return str(amount)


def _average(item):
    if not isinstance(item, dict):
        return None
    try:
        value = _price(item.get("value"))
        size = item.get("window_size")
        start = _timestamp(item.get("window_start_ts_ms"))
        end = _timestamp(item.get("window_end_ts_exclusive"))
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= 60:
            return None
        if end <= start or end - start > 61000:
            return None
    except ValueError:
        return None
    return {"value_usd": value, "window_size": size,
            "window_start_ts_ms": start, "window_end_ts_exclusive": end,
            "is_full_60": size == 60}


def parse_update(packet, local_ms):
    """Only accept documented BRTI frames; source/transport clocks distinct."""
    if not isinstance(packet, dict) or packet.get("type") not in CHANNELS:
        return None
    msg = packet.get("msg")
    if not isinstance(msg, dict) or msg.get("index_id") != "BRTI":
        return None
    local_ms = _timestamp(local_ms)
    channel = packet["type"]
    if channel == "cfbenchmarks_value_5hz":
        source = _timestamp(msg.get("source_ts_ms"))
        value = _price(msg.get("value_usd"))
    else:
        raw = msg.get("data")
        try:
            raw = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            raise ValueError("Invalid CF Benchmarks upstream JSON") from None
        if not isinstance(raw, dict) or raw.get("id") != "BRTI":
            raise ValueError("Malformed upstream BRTI frame")
        source = _timestamp(raw.get("time"))
        value = _price(raw.get("value"))
    kalshi_received = _timestamp(msg.get("received_at"))
    # A malformed or future-dated source must never be treated as a live signal.
    if source > local_ms + 2000 or kalshi_received > local_ms + 2000:
        raise ValueError("Index source or exchange timestamp in the future")
    if kalshi_received < source - 2000:
        raise ValueError("Exchange receipt precedes source timestamp")
    row = {"channel": channel, "index_id": "BRTI", "value_usd": value,
           "source_ts_ms": source, "kalshi_received_at_ms": kalshi_received,
           "axiom_received_at_ms": local_ms,
           "source_to_kalshi_ms": kalshi_received - source,
           "kalshi_to_axiom_ms": local_ms - kalshi_received,
           "source_to_axiom_ms": local_ms - source,
           "reference_only": True, "votes_in_forecast": False,
           "trading_actions_enabled": False}
    if channel == "cfbenchmarks_value":
        row["trailing_60s_provider"] = _average(msg.get("avg_60s_data"))
        row["quarter_hour_final_minute_provider"] = _average(
            msg.get("last_60s_windowed_average_15min"))
    return row


class BRTITracker:
    def __init__(self, enabled=False):
        self.lock = threading.RLock()
        self.enabled = bool(enabled)
        self.connected = False
        self.error_kind = None
        self.latest = {}
        self.received_counts = {name: 0 for name in CHANNELS}
        self.rejected = 0
        self.out_of_order = 0
        self.first_observed_market = None
        self.subscribed_channels = set()

    def observe_market(self, market, at_ms=None):
        if not isinstance(market, dict):
            return
        ticker = market.get("ticker")
        target = market.get("target")
        if not isinstance(ticker, str) or not ticker.startswith("KXBTC15M-"):
            return
        try:
            target = _price(target)
            instant = _timestamp(int(time.time()*1000) if at_ms is None else at_ms)
        except ValueError:
            return
        with self.lock:
            old = self.first_observed_market
            if old is None or old["ticker"] != ticker:
                self.first_observed_market = {
                    "ticker": ticker, "target_usd": target,
                    "axiom_first_observed_at_ms": instant,
                    "first_publication_time_verified": False,
                    "source": "first_Kalshi_public_REST_observation"}
            elif old["target_usd"] != target:
                self.first_observed_market = {**old,
                    "target_changed_after_first_observation": True,
                    "last_observed_target_usd": target}

    def accept(self, packet, received_at_ms=None):
        if received_at_ms is None:
            received_at_ms = int(time.time()*1000)
        try:
            row = parse_update(packet, received_at_ms)
        except (ValueError, TypeError, OverflowError):
            with self.lock:
                self.rejected += 1
            return False
        if row is None:
            return False
        channel = row["channel"]
        with self.lock:
            old = self.latest.get(channel)
            if old and row["source_ts_ms"] <= old["source_ts_ms"]:
                self.out_of_order += 1
                return False
            self.latest[channel] = row
            self.received_counts[channel] += 1
            self.error_kind = None
        return True

    def mark(self, connected=None, error_kind=None, subscribed=None):
        with self.lock:
            if connected is not None:
                self.connected = bool(connected)
            if error_kind:
                # Do NOT write raw network exception strings or credentials.
                self.error_kind = str(error_kind)[:60]
            if subscribed in CHANNELS:
                self.subscribed_channels.add(subscribed)

    def snapshot(self, now_ms=None):
        now_ms = int(time.time()*1000) if now_ms is None else _timestamp(now_ms)
        with self.lock:
            latest = {k: dict(v) for k, v in self.latest.items()}
            current = max(latest.values(), key=lambda v:v["source_ts_ms"]) if latest else None
            delay = now_ms-current["axiom_received_at_ms"] if current else None
            age = now_ms-current["source_ts_ms"] if current else None
            status = "DISABLED" if not self.enabled else (
                "UNAVAILABLE" if not current else
                "STALE" if not self.connected or delay > MAX_RECEIPT_AGE_MS or age > MAX_LAG_MS else
                "STREAMING")
            return {"status": status,
                    "reason": ("Live WebSocket not configured" if status == "DISABLED" else
                               "Awaiting genuine BRTI messages" if status == "UNAVAILABLE" else
                               "BRTI event/receipt data too old" if status == "STALE" else
                               "Current authentic BRTI stream, NONVOTING only"),
                    "authenticated_stream_verified": bool(status=="STREAMING"),
                    "latest_value_usd": current["value_usd"] if current else None,
                    "latest_channel": current["channel"] if current else None,
                    "source_ts_ms": current["source_ts_ms"] if current else None,
                    "kalshi_received_at_ms": current["kalshi_received_at_ms"] if current else None,
                    "axiom_received_at_ms": current["axiom_received_at_ms"] if current else None,
                    "source_to_axiom_ms": current["source_to_axiom_ms"] if current else None,
                    "received_counts": dict(self.received_counts),
                    "rejected": self.rejected, "out_of_order": self.out_of_order,
                    "subscribed_channels": sorted(self.subscribed_channels),
                    "trailing_60s_provider": latest.get("cfbenchmarks_value",{}).get("trailing_60s_provider"),
                    "quarter_hour_final_minute_provider": latest.get("cfbenchmarks_value",{}).get("quarter_hour_final_minute_provider"),
                    "first_observed_market": dict(self.first_observed_market) if self.first_observed_market else None,
                    "last_error_type": self.error_kind,
                    "live_strike_first_publication_proven": False,
                    "live_prediction_accuracy_proven": False,
                    "votes_in_ensemble": False,
                    "orders_placed": False}


async def observe_connection(tracker, *, duration_seconds=None, stop_event=None):
    """One authenticated, read-only WebSocket session. No private channels."""
    import websockets
    from research.verify_official_brti_live import _signed_headers
    kid = os.environ.get("KALSHI_API_KEY_ID","").strip()
    private = os.environ.get("KALSHI_PRIVATE_KEY_PEM","").strip()
    if not kid or not private:
        tracker.mark(connected=False,error_kind="MissingCredentials")
        return 0
    headers = _signed_headers(kid, private, WS_PATH)
    count = 0
    started = time.monotonic()
    async with websockets.connect(WS_URL, additional_headers=headers,
                                  open_timeout=12, close_timeout=3,
                                  ping_interval=20, ping_timeout=20, max_size=1048576) as ws:
        tracker.mark(connected=True)
        for n, channel in enumerate(CHANNELS, 1):
            await ws.send(json.dumps({"id": n, "cmd": "subscribe",
                                      "params": {"channels": [channel],
                                                 "index_ids": ["BRTI"]}}))
        while not (stop_event and stop_event.is_set()):
            remaining = None if duration_seconds is None else duration_seconds-(time.monotonic()-started)
            if remaining is not None and remaining <= 0:
                break
            try:
                frame = await asyncio.wait_for(ws.recv(), timeout=min(8.,remaining) if remaining is not None else 8.)
            except asyncio.TimeoutError:
                if duration_seconds is not None:
                    continue
                # Idle websocket is not live evidence; reconnect boundedly.
                break
            packet = json.loads(frame)
            if not isinstance(packet, dict):
                continue
            if packet.get("type") == "error":
                code = (packet.get("msg") or {}).get("code")
                tracker.mark(error_kind="SubscriptionErrorCode_"+str(code)[:12])
                break
            if packet.get("type") == "subscribed":
                channel=(packet.get("msg") or {}).get("channel")
                tracker.mark(subscribed=channel)
            if tracker.accept(packet):
                count += 1
    tracker.mark(connected=False)
    return count


def run_worker(tracker, stop_event):
    """Reconnect with bounded backoff; never convert outage into fake ticks."""
    backoff = 2
    while not stop_event.is_set():
        try:
            count = asyncio.run(observe_connection(tracker, stop_event=stop_event))
            backoff = 2 if count else min(backoff*2, 60)
        except Exception as exc:
            tracker.mark(connected=False,error_kind=type(exc).__name__)
            backoff = min(backoff*2, 60)
        stop_event.wait(backoff)
