"""Pure failure and lifecycle cases for the authenticated reference worker.

All fake frames and credentials are synthetic. Never accesses Kalshi networks.
"""
import asyncio
import io
import json
from pathlib import Path
import threading
import time
import types
from unittest.mock import patch

import pytest
from app import brti_live
from research import live_brti_probe


TS=1795046700000


def sample(channel="cfbenchmarks_value_5hz"):
    raw={"index_id":"BRTI","source_ts_ms":TS,
         "value_usd":"63000.1000","received_at":TS+40}
    if channel=="cfbenchmarks_value":
        raw={"index_id":"BRTI","received_at":TS+40,
             "data":{"id":"BRTI","time":TS,"value":"63000.1000"}}
    return {"type":channel,"msg":raw}


def test_bounded_average_structural_rejections_and_valid_zero_prior_window():
    valid={"value":"63000.1000","window_size":0,
           "window_start_ts_ms":TS-60000,
           "window_end_ts_exclusive":TS}
    assert brti_live._average(valid)["is_full_60"] is False
    for bad in (None,[],{},{"value":"NaN","window_size":60},
                {**valid,"window_size":True},{**valid,"window_size":-1},
                {**valid,"window_end_ts_exclusive":TS-61000},
                {**valid,"window_start_ts_ms":TS}):
        assert brti_live._average(bad) is None
    assert brti_live.parse_update({"type":"not-brti","msg":{}},TS+100) is None
    for bad in (None,[],"bad",{"type":"cfbenchmarks_value_5hz","msg":None}):
        assert brti_live.parse_update(bad,TS+100) is None
    with pytest.raises(ValueError):
        brti_live.parse_update(sample("cfbenchmarks_value"),TS-5000)


def test_market_strike_fails_closed_on_missing_target_bad_ticker_and_bad_timestamp():
    obj=brti_live.BRTITracker(enabled=True)
    for ticker,target,instant in (
        ("ETH15M-XYZ",90000,TS),(None,90000,TS),
        ("KXBTC15M-XYZ","NaN",TS),
        ("KXBTC15M-XYZ",None,TS),
        ("KXBTC15M-XYZ",90000,False),
    ):
        obj.observe_market({"ticker":ticker,"target":target},instant)
    assert obj.snapshot(TS)["first_observed_market"] is None
    obj.observe_market({"ticker":"KXBTC15M-VALID","target":90000},TS)
    obj.observe_market({"ticker":"KXBTC15M-VALID","target":90000},TS+500)
    assert obj.snapshot(TS)["first_observed_market"]["axiom_first_observed_at_ms"]==TS


def test_rejected_and_out_of_order_frames_cannot_change_last_live_value():
    tracker=brti_live.BRTITracker(True)
    tracker.mark(connected=True)
    assert tracker.accept(sample(),TS+100)
    old=tracker.snapshot(TS+200)
    malformed=sample()
    malformed["msg"]["value_usd"]="bad"
    assert not tracker.accept(malformed,TS+200)
    assert not tracker.accept(sample(),TS+210)
    new=tracker.snapshot(TS+300)
    assert old["latest_value_usd"]==new["latest_value_usd"]
    assert new["out_of_order"]==1
    assert new["rejected"]==1
    assert new["authenticated_stream_verified"] is True


def test_subscription_error_fails_closed_without_leaking_exchange_message(monkeypatch):
    monkeypatch.setenv("KALSHI_API_KEY_ID","fake-id")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM","fake-pem")
    class Socket:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
        async def send(self, data):pass
        async def recv(self):
            return json.dumps({"type":"error","msg":{
                "code":9,"msg":"fake-pem should never be published"}})
    from research import verify_official_brti_live
    with patch.object(verify_official_brti_live,"_signed_headers",return_value={}):
        with patch.dict(__import__("sys").modules,
                        {"websockets":types.SimpleNamespace(connect=lambda *a,**kw:Socket())}):
            obj=brti_live.BRTITracker(True)
            assert asyncio.run(brti_live.observe_connection(obj,duration_seconds=1))==0
    state=json.dumps(obj.snapshot(TS))
    assert "fake-pem" not in state
    assert "SubscriptionErrorCode_9" in state


def test_stop_event_prevents_any_work_and_reconnect_error_is_sanitized():
    obj=brti_live.BRTITracker(True)
    stopped=threading.Event();stopped.set()
    with patch.object(brti_live.asyncio,"run",side_effect=AssertionError("should not run")):
        brti_live.run_worker(obj,stopped)
    class One:
        def __init__(self):self.calls=0;self.sleep=None
        def is_set(self):
            self.calls+=1
            return self.calls>1
        def wait(self,delay):self.sleep=delay
    event=One()
    with patch.object(brti_live.asyncio,"run",side_effect=RuntimeError("fake private secret")):
        brti_live.run_worker(obj,event)
    assert event.sleep==4
    state=json.dumps(obj.snapshot(TS))
    assert "RuntimeError" in state
    assert "fake private secret" not in state


def test_probe_is_explicit_about_missing_data_and_outputs_no_values(tmp_path,monkeypatch,capsys):
    monkeypatch.setenv("BRTI_PROBE_SECONDS","10")
    monkeypatch.setenv("AXIOM_LIVE_BRTI_SUMMARY",str(tmp_path/"summary.json"))
    monkeypatch.delenv("KALSHI_API_KEY_ID",raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM",raising=False)
    with patch.object(live_brti_probe.asyncio,"run",return_value=0):
        assert live_brti_probe.run()==2
    report=json.loads((tmp_path/"summary.json").read_text())
    assert report["status"]=="NOT_VERIFIED"
    assert report["raw_index_data_exported"] is False
    assert report["predictive_alpha_or_real_profit_verified"] is False
