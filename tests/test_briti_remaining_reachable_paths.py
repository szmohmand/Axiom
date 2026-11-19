"""Execute newly reachable BRTI/WebSocket failure branches without credentials or orders.

The original 99.5893% measured baseline is preserved; no source exclusions or
coverage gate weakening. Fake sessions test every status transition explicitly.
"""
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import threading
import types
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from app import brti_live, main
from research import live_brti_probe, verify_official_brti_live


TS=1795046700000


async def fake_session(monkeypatch, frames=None, *, deadline=None, timeout_mode=False):
    """Connect with only fake keys; inject ack, malformed frames or timeout."""
    monkeypatch.setenv("KALSHI_API_KEY_ID","fake-id")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM","fake-pem")
    frames=list(frames or [])
    class Socket:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
        async def send(self,packet):
            msg=json.loads(packet)
            assert msg["cmd"]=="subscribe" and msg["params"]["index_ids"]==["BRTI"]
        async def recv(self):
            return frames.pop(0) if frames else json.dumps({"type":"error","msg":{"code":12}})
    tracker=brti_live.BRTITracker(True)
    fake=types.SimpleNamespace(connect=lambda *a,**kw:Socket())
    with patch.object(verify_official_brti_live,"_signed_headers",return_value={}):
        with patch.dict(sys.modules,{"websockets":fake}):
            if timeout_mode:
                async def timeout(*args,**kwargs):
                    # Prevent un-awaited coroutine from leaking a runtime warning.
                    coro=args[0];coro.close()
                    raise asyncio.TimeoutError()
                with patch.object(brti_live.asyncio,"wait_for",side_effect=timeout):
                    return await brti_live.observe_connection(tracker,
                        duration_seconds=deadline),tracker
            return await brti_live.observe_connection(tracker,
                duration_seconds=deadline),tracker


def test_malformed_upstream_and_nonmarket_first_observation_are_ignored():
    bad={"type":"cfbenchmarks_value","msg":{"index_id":"BRTI",
         "received_at":TS+50,"data":[]} }
    with pytest.raises(ValueError,match="Malformed upstream"):
        brti_live.parse_update(bad,TS+100)
    obj=brti_live.BRTITracker(True)
    obj.observe_market(None,TS)
    obj.observe_market("bad-market",TS)
    assert obj.snapshot(TS)["first_observed_market"] is None


def test_briti_websocket_duration_zero_exits_before_receiving(monkeypatch):
    n,obj=asyncio.run(fake_session(monkeypatch,deadline=0))
    assert n==0
    assert obj.snapshot(TS)["received_counts"]["cfbenchmarks_value_5hz"]==0


def test_briti_timeout_with_and_without_capture_deadline(monkeypatch):
    # For a bounded probe, a timeout causes the client to continue until
    # the capture deadline; for a persistent worker it closes to reconnect.
    n,_=asyncio.run(fake_session(monkeypatch,deadline=.001,timeout_mode=True))
    assert n==0
    n,_=asyncio.run(fake_session(monkeypatch,deadline=None,timeout_mode=True))
    assert n==0


def test_briti_nonobject_frames_and_subscribed_ack_are_not_counted(monkeypatch):
    frames=[json.dumps(None),json.dumps({"type":"subscribed",
        "msg":{"channel":"cfbenchmarks_value_5hz"}}),
        json.dumps({"type":"error","msg":{"code":24}})]
    n,obj=asyncio.run(fake_session(monkeypatch,frames=frames))
    assert n==0
    assert obj.snapshot(TS)["subscribed_channels"]==["cfbenchmarks_value_5hz"]
    assert obj.snapshot(TS)["last_error_type"]=="SubscriptionErrorCode_24"


def test_briti_worker_success_case_backoff_resets(monkeypatch):
    tracker=brti_live.BRTITracker(True)
    class Stop:
        def __init__(self):self.count=0;self.slept=[]
        def is_set(self):self.count+=1;return self.count>1
        def wait(self,seconds):self.slept.append(seconds)
    stop=Stop()
    def close_and_return(coro):
        coro.close()
        return 4
    with patch.object(brti_live.asyncio,"run",side_effect=close_and_return):
        brti_live.run_worker(tracker,stop)
    assert stop.slept==[2]
    assert stop.count==2


def test_fastapi_real_briti_worker_thread_start_stop_in_full_lifespan(monkeypatch):
    called=threading.Event()
    def fake_worker(tracker,shutdown):
        assert tracker is main.brti_tracker
        called.set()
    monkeypatch.setattr(main,"BRTI_LIVE_ENABLED",True)
    monkeypatch.setattr(main,"worker",lambda:None)
    monkeypatch.setattr(main,"grading_worker",lambda:None)
    monkeypatch.setattr(main,"brti_reference_worker",fake_worker)
    with TestClient(main.app) as client:
        assert client.get("/").status_code==200
        assert called.wait(2)
    assert main.shutdown.is_set()


def test_briti_probe_error_reason_cannot_contain_original_network_message(monkeypatch,tmp_path,capsys):
    monkeypatch.setenv("BRTI_PROBE_SECONDS","10")
    monkeypatch.setenv("AXIOM_LIVE_BRTI_SUMMARY",str(tmp_path/"status.json"))
    def close_and_fail(coro):
        coro.close()
        raise OSError("private-key-must-not-leak")
    with patch.object(live_brti_probe.asyncio,"run",side_effect=close_and_fail):
        assert live_brti_probe.run()==2
    row=json.loads((tmp_path/"status.json").read_text())
    assert row["transport_failure_type"]=="OSError"
    assert "private-key-must-not-leak" not in json.dumps(row)


def test_standalone_probe_main_without_keys_exits_two_with_no_raw_feed(monkeypatch):
    monkeypatch.delenv("KALSHI_API_KEY_ID",raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM",raising=False)
    monkeypatch.delenv("AXIOM_LIVE_BRTI_SUMMARY",raising=False)
    monkeypatch.setenv("BRTI_PROBE_SECONDS","10")
    with contextlib.redirect_stdout(io.StringIO()) as capture:
        with pytest.raises(SystemExit) as ex:
            runpy.run_path(str(Path(live_brti_probe.__file__)),run_name="__main__")
    assert ex.value.code==2
    assert '"status": "NOT_VERIFIED"' in capture.getvalue()
    assert "fake-pem" not in capture.getvalue()
