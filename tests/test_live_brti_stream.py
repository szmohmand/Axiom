"""BRTI point-in-time, WebSocket, publication provenance and fail-closed tests."""
import asyncio
from datetime import datetime, timezone
import json
import sys
import threading
import time
import types
from unittest.mock import patch

import pytest
import requests

from app.brti_live import (BRTITracker, CHANNELS, WS_PATH, parse_update,
                           observe_connection, _price, _timestamp)


BASE=1795046700000

def tick_5hz(ts=BASE,val="62430.001"):
    return {"type":"cfbenchmarks_value_5hz","seq":12,"msg":{
        "index_id":"BRTI","value_usd":val,"source_ts_ms":ts,
        "received_at":ts+30,"data":"{}"}}

def tick_1hz(ts=BASE,val="62430.001",size=10):
    return {"type":"cfbenchmarks_value","seq":7,"msg":{
        "index_id":"BRTI","received_at":ts+40,
        "data":json.dumps({"type":"value","id":"BRTI","time":ts,"value":val}),
        "avg_60s_data":{"value":val,"window_size":size,
                        "window_start_ts_ms":ts-60000,
                        "window_end_ts_exclusive":ts},
        "last_60s_windowed_average_15min":{
            "value":val,"window_size":size,"window_start_ts_ms":ts-60000,
            "window_end_ts_exclusive":ts}}}


def test_exact_source_kalshi_local_clocks_and_nonvoting_record():
    row=parse_update(tick_5hz(),BASE+90)
    assert row["source_to_kalshi_ms"]==30
    assert row["kalshi_to_axiom_ms"]==60
    assert row["source_to_axiom_ms"]==90
    assert row["value_usd"]=="62430.001"
    assert row["trading_actions_enabled"] is False
    assert row["votes_in_forecast"] is False
    row=parse_update(tick_1hz(size=60),BASE+70)
    assert row["quarter_hour_final_minute_provider"]["is_full_60"] is True
    assert row["trailing_60s_provider"]["window_size"]==60
    assert row["source_to_axiom_ms"]==70


def test_wrong_index_malformed_and_nonfinite_values_are_never_accepted():
    tracker=BRTITracker(enabled=True)
    wrong=tick_5hz();wrong["msg"]["index_id"]="ETHUSD_RTI"
    assert tracker.accept(wrong,BASE+90) is False
    assert parse_update({"type":"other","msg":{}},BASE+90) is None
    for raw in [None,False,"not-a-number","NaN","Infinity",0,-7,"1e100"]:
        with pytest.raises(ValueError):
            _price(raw)
    for raw in [None,False,3.3,"bad",float("nan"),float("inf")]:
        with pytest.raises(ValueError):
            _timestamp(raw)
    for bad in [tick_5hz(val="nan"),tick_5hz(val="-1"),
                tick_5hz(ts=BASE+1000000)]:
        assert tracker.accept(bad,BASE+100) is False
    broken=tick_1hz();broken["msg"]["data"]="not-json"
    assert tracker.accept(broken,BASE+70) is False
    assert tracker.snapshot(BASE+100)["status"]=="UNAVAILABLE"
    assert tracker.rejected>=4


def test_out_of_order_duplicate_and_stale_frames_never_become_current_reference():
    t=BRTITracker(enabled=True)
    t.mark(connected=True,subscribed="cfbenchmarks_value_5hz")
    assert t.accept(tick_5hz(),BASE+85)
    assert not t.accept(tick_5hz(),BASE+100)
    assert not t.accept(tick_5hz(BASE-100),BASE+120)
    s=t.snapshot(BASE+1000)
    assert s["status"]=="STREAMING"
    assert s["out_of_order"]==2
    assert s["received_counts"]["cfbenchmarks_value_5hz"]==1
    assert s["live_prediction_accuracy_proven"] is False
    assert s["orders_placed"] is False
    assert t.snapshot(BASE+20000)["status"]=="STALE"
    t.mark(connected=False,error_kind="ConnectionClosed")
    assert t.snapshot(BASE+1000)["status"]=="STALE"
    assert t.snapshot(BASE+1000)["last_error_type"]=="ConnectionClosed"


def test_missing_credentials_do_not_fake_live_stream_or_publication():
    t=BRTITracker()
    assert t.snapshot(BASE)["status"]=="DISABLED"
    t.observe_market({"ticker":"KXBTC15M-DEMO","target":90000},BASE)
    m=t.snapshot(BASE)["first_observed_market"]
    assert m["target_usd"]=="90000"
    assert m["first_publication_time_verified"] is False
    t.observe_market({"ticker":"KXBTC15M-DEMO","target":90002},BASE+1000)
    m=t.snapshot(BASE)["first_observed_market"]
    assert m["target_changed_after_first_observation"] is True
    t.observe_market({"ticker":"KXBTC15M-NEW","target":90100},BASE+1100)
    assert t.snapshot(BASE)["first_observed_market"]["ticker"]=="KXBTC15M-NEW"


def test_bad_average_is_absent_and_partial_minute_never_called_final():
    t=BRTITracker(True);t.mark(connected=True)
    p=tick_1hz(size=14)
    p["msg"]["avg_60s_data"]["window_size"]=400
    assert t.accept(p,BASE+90)
    state=t.snapshot(BASE+1000)
    assert state["trailing_60s_provider"] is None
    assert state["quarter_hour_final_minute_provider"]["is_full_60"] is False
    assert state["quarter_hour_final_minute_provider"]["window_size"]==14


def test_source_kalshi_clock_cannot_be_future_or_inverted():
    p=tick_5hz()
    p["msg"]["received_at"]=BASE-30000
    with pytest.raises(ValueError):
        parse_update(p,BASE+100)
    p=tick_5hz(ts=BASE+20000)
    with pytest.raises(ValueError):
        parse_update(p,BASE+100)


def test_signed_subscribe_uses_only_benchmark_channels_and_sanitized_state(monkeypatch):
    from research import verify_official_brti_live as verifier
    monkeypatch.setenv("KALSHI_API_KEY_ID","synthetic-test-key-id")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM","synthetic-test-PEM")
    seen=[]
    done=threading.Event()
    class FakeWS:
        async def send(self,packet):seen.append(json.loads(packet))
        async def recv(self):
            done.set()
            return json.dumps(tick_5hz(BASE))
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
    def connect(url,**kwargs):
        assert url.startswith("wss://external-api-ws.kalshi.com/")
        assert kwargs["additional_headers"]=={"SYNTHETIC":"test"}
        return FakeWS()
    with patch.object(verifier,"_signed_headers",return_value={"SYNTHETIC":"test"}) as signer:
        with patch.dict(sys.modules,{"websockets":types.SimpleNamespace(connect=connect)}):
            tracker=BRTITracker(True)
            count=asyncio.run(observe_connection(tracker,stop_event=done))
    assert signer.call_args.args == ("synthetic-test-key-id","synthetic-test-PEM",WS_PATH)
    assert count==1
    assert len(seen)==2
    assert [s["params"]["channels"][0] for s in seen]==list(CHANNELS)
    assert all(s["cmd"]=="subscribe" and s["params"]["index_ids"]==["BRTI"] for s in seen)
    state=json.dumps(tracker.snapshot(BASE+100))
    assert "synthetic-test-PEM" not in state
    assert "synthetic-test-key-id" not in state


def test_live_stream_missing_credentials_exits_cleanly(monkeypatch):
    monkeypatch.delenv("KALSHI_API_KEY_ID",raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM",raising=False)
    tracker=BRTITracker(True)
    assert asyncio.run(observe_connection(tracker,duration_seconds=.1))==0
    assert tracker.snapshot(BASE)["last_error_type"]=="MissingCredentials"


def test_live_reference_has_no_execution_or_probability_code_path():
    import inspect
    from app import brti_live
    body=inspect.getsource(brti_live)
    assert "/portfolio" not in body
    assert "/orders" not in body
    assert "prob_above" not in body
    assert "read-only" in observe_connection.__doc__.lower()


def test_transient_kalshi_rollover_503_retries_once_and_fail_closes(monkeypatch):
    """A30: public 503 at real boundary retries once, no fabricated contract."""
    from app.feeds import LiveProvider
    from app import feeds
    import time
    now=float(int(time.time()//900)*900+10)
    resp=requests.Response(); resp.status_code=503
    error=requests.HTTPError("temporary 503",response=resp)
    market={
        "ticker":"KXBTC15M-26NOV181700-00","status":"open",
        "close_time":datetime.fromtimestamp(now+800,timezone.utc).isoformat(),
        "floor_strike":90000,
    }
    p=LiveProvider()
    try:
        with patch.object(feeds.time,"time",return_value=now),patch.object(
               feeds.time,"sleep",return_value=None) as sleep:
            with patch.object(p,"get",side_effect=[error,{"markets":[market]}]) as get:
                result=p.market(now)
                assert result is not None
                assert result["ticker"]==market["ticker"]
                assert get.call_count==2
                sleep.assert_called_once_with(.4)
            with patch.object(p,"get",side_effect=[error,error]) as get:
                assert p.market(now) is None
                assert get.call_count==2
        with patch.object(feeds.time,"time",return_value=now+350):
            with patch.object(p,"get",side_effect=error) as get:
                with pytest.raises(requests.HTTPError):
                    p.market(now+350)
                assert get.call_count==1
    finally:
        p.session.close()
