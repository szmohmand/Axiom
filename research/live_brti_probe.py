"""Bounded authenticated LIVE BRTI visibility probe; no market trading.

Retains only aggregated source/receipt age, subscription evidence and counts.
Never writes API credentials, raw CF index values or raw market-data frames.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import time
from app.brti_live import BRTITracker, observe_connection, CHANNELS


def run():
    seconds = max(10, min(90, int(os.environ.get("BRTI_PROBE_SECONDS", "25"))))
    tracker = BRTITracker(True)
    started = time.monotonic()
    failure = None
    try:
        accepted = asyncio.run(observe_connection(tracker, duration_seconds=seconds))
    except Exception as exc:
        accepted = 0
        failure = type(exc).__name__
    state = tracker.snapshot()
    counts = state["received_counts"]
    now_ms = int(time.time()*1000)
    sample_age = now_ms - state["source_ts_ms"] if state["source_ts_ms"] else None
    found = all(counts.get(channel,0)>0 for channel in CHANNELS)
    recent = sample_age is not None and -2000 <= sample_age <= 15000
    result = {
        "kind":"AXIOM_LIVE_BRTI_1HZ_AND_5HZ_AUTHENTICATED_CAPTURE",
        "status":"PASS" if found and recent and not failure else "NOT_VERIFIED",
        "channels_received":{c:counts[c] for c in CHANNELS},
        "last_source_age_ms":sample_age,
        "last_source_to_axiom_ms":state["source_to_axiom_ms"],
        "subscribed_channels":state["subscribed_channels"],
        "invalid_packets":state["rejected"],
        "out_of_order_packets":state["out_of_order"],
        "transport_failure_type":failure or state["last_error_type"],
        "elapsed_seconds":round(time.monotonic()-started,2),
        "real_orders":False,
        "actual_fills":False,
        "official_strike_first_publication_verified":False,
        "predictive_alpha_or_real_profit_verified":False,
        "full_reference_60_second_settlement_validated":False,
        "received_actual_index_frames":bool(accepted),
        "raw_index_data_exported":False
    }
    payload = json.dumps(result,sort_keys=True)
    print("AXIOM_LIVE_BRTI "+payload,flush=True)
    artifact = os.environ.get("AXIOM_LIVE_BRTI_SUMMARY","")
    if artifact:
        Path(artifact).write_text(json.dumps(result,indent=2,sort_keys=True))
    return 0 if result["status"]=="PASS" else 2


if __name__=="__main__":
    raise SystemExit(run())
