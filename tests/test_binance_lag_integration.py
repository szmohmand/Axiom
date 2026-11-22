"""Binance public BTC spot trade stream and Binance-first Kalshi lag.

REST quote timestamps are receipt times, not exchange first-publication
clocks or executable fills. No futures funding data is collected.
"""
import json
import threading

import pytest

from app.binance_telemetry import (BinanceTelemetry, finite, invalid,
                                    spot_worker)
from app.lag_intelligence import BinanceKalshiLagTracker, wait
from app.orderbook import normalize_orderbook
from test_e2e_synthetic import env

T=1800000000.0


def trade(seconds=T,price=60000,tid=1):
    ms=int(seconds*1000)
    return {"e":"aggTrade","s":"BTCUSDT","a":tid,
            "T":ms,"E":ms+5,"p":str(price)}


def bk(seconds=T,ticker="KXBTC15M-TEST",yes=".38",no=".60",
       yes_size="35",no_size="35"):
    return normalize_orderbook({"orderbook_fp":{"yes_dollars":[[yes,yes_size]],
       "no_dollars":[[no,no_size]]}},ticker,seconds)


def market(ticker="KXBTC15M-TEST"):
    return {"ticker":ticker,"seconds_left":600,"close_ts":T+600,
            "target":60010,"market_mid":.39}


def spot(price,seconds,now=None):
    return {"status":"STREAMING","spot_price":price,"spot_trade_at":seconds-.15,
            "spot_received_at":seconds-.05}


def test_binance_spot_has_real_timestamps_and_no_funding_fields():
    b=BinanceTelemetry(enabled=True)
    assert b.snapshot(T)["status"]=="UNAVAILABLE"
    assert b.observe_trade(trade(T-.1),T)
    s=b.snapshot(T+.25)
    assert s["status"]=="STREAMING" and s["spot_price"]==60000
    assert not any("funding" in field or "perpetual" in field for field in s)
    assert s["settlement_reference"] is False and s["orders_placed"] is False
    assert b.snapshot(T+8)["status"]=="STALE"
    b.note_connection(connected=True)
    assert b.snapshot(T+.3)["connected"]


@pytest.mark.parametrize("event,received",[
    (None,T),({"e":"trade"},T),({**trade(),"s":"BTCUSD"},T),
    ({**trade(),"a":True},T),({**trade(),"a":-1},T),
    ({**trade(),"T":None},T),({**trade(),"E":0},T),
    ({**trade(),"p":"inf"},T),({**trade(),"p":"0"},T),
    ({**trade(),"T":1000,"E":1005},T),
    (trade(),T+90),(trade(),T-10),
])
def test_binance_rejects_invalid_trade_and_spoofed_times(event,received):
    b=BinanceTelemetry(enabled=True)
    assert not b.observe_trade(event,received)
    assert b.snapshot(T)["status"]=="UNAVAILABLE"


def test_binance_trade_order_duplicates_and_no_futures_api():
    b=BinanceTelemetry(enabled=True)
    assert b.observe_trade(trade(T,tid=11),T+.1)
    assert not b.observe_trade(trade(T,tid=11),T+.2)
    assert not b.observe_trade(trade(T-1,tid=12),T+.2)
    assert b.observe_trade(trade(T+.1,tid=12),T+.2)
    assert not hasattr(b,"observe_funding")
    assert not hasattr(b,"note_funding_error")
    assert "funding" not in repr(b.snapshot(T+.2)).lower()
    assert not BinanceTelemetry().snapshot(T)["orders_placed"]


def test_helper_invalid_numbers_and_safe_default():
    for x in (None,True,"nan","inf","missing",[],10**1000):
        assert finite(x) is None
    assert finite("7.5")==7.5
    assert invalid("no feed")["status"]=="UNAVAILABLE"


def test_live_spot_worker_reconnects_and_ignores_invalid_frames(monkeypatch):
    from app import binance_telemetry as mod
    done=threading.Event()
    b=BinanceTelemetry(enabled=True)
    frames=iter(["bad json",json.dumps({"garbage":1}),
                 json.dumps(trade(T,tid=1))])
    class Sock:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def recv(self,timeout=None):
            try:return next(frames)
            except StopIteration:
                done.set()
                return None
    monkeypatch.setattr(mod,"connect",lambda *args,**kwargs:Sock())
    monkeypatch.setattr(mod.time,"time",lambda:T+.1)
    spot_worker(b,done)
    assert b.snapshot(T+.1)["spot_price"]==60000
    assert not b.snapshot(T+.1)["connected"]


def test_spot_worker_network_failure_never_creates_fake_trade(monkeypatch):
    from app import binance_telemetry as mod
    stop=threading.Event()
    class Stop:
        def is_set(self):return False
        def wait(self,seconds):return True
    monkeypatch.setattr(mod,"connect",lambda *a,**k: (_ for _ in ()).throw(OSError("blocked")))
    b=BinanceTelemetry(enabled=True)
    spot_worker(b,Stop())
    assert b.last_error=="OSError" and not b.snapshot(T)["orders_placed"]


def test_binance_first_followed_by_small_quote_change_can_be_buy_candidate():
    tracker=BinanceKalshiLagTracker()
    p=market()
    f={"available":True,"side":"ABOVE","prob_above":.85}
    first=tracker.observe(p,bk(T+.25),spot(60000,T),f,T+.25)
    assert first["action"]=="WAIT"
    second=tracker.observe(p,bk(T+5.3),spot(60050,T+5),f,T+5.3)
    assert second["action"]=="BUY_CANDIDATE"
    assert second["side"]=="YES" and second["probable_observed_lag"]
    assert second["actual_quote_delay_verified"] is False
    assert second["measured_binance_move_bps"]>5
    assert second["kalshi_yes_mid_change"]==pytest.approx(0)
    assert second["independent_outcome_edge_after_entry_fee"]>.03
    assert second["entry_ask_size_adjusted"]==pytest.approx(.4)
    assert second["orders_placed"] is False


def test_binance_drop_can_identify_no_candidate_without_yes_bias():
    tracker=BinanceKalshiLagTracker()
    p=market()
    f={"available":True,"side":"BELOW","prob_above":.1}
    tracker.observe(p,bk(T+.25),spot(60000,T),f,T+.25)
    o=tracker.observe(p,bk(T+5.3),spot(59950,T+5),f,T+5.3)
    assert o["action"]=="BUY_CANDIDATE" and o["side"]=="NO"


@pytest.mark.parametrize("scenario",[
    "weak","repriced","bad_fair","absent_forecast","future_event",
    "source_before_previous_book","changed_contract","stale","wide_spread",
    "thin","near_expiry","too_fast","too_slow","no_quotes","bad_timestamp",
    "invalid_type"])
def test_binance_kalshi_delay_fails_closed(scenario):
    tracker=BinanceKalshiLagTracker()
    p=market()
    b=bk(T+.25)
    f={"available":True,"side":"ABOVE","prob_above":.85}
    first=spot(60000,T)
    assert tracker.observe(p,b,first,f,T+.25)["action"]=="WAIT"
    second=spot(60050,T+5)
    book=bk(T+5.3)
    now=T+5.3
    if scenario=="weak":second["spot_price"]=60003
    if scenario=="repriced":book=bk(T+5.3,yes=".40",no=".58")
    if scenario=="bad_fair":f={"available":True,"side":"ABOVE","prob_above":.42}
    if scenario=="absent_forecast":f={"available":False}
    if scenario=="future_event":second["spot_trade_at"]=T+15
    if scenario=="source_before_previous_book":second["spot_trade_at"]=T+.05
    if scenario=="changed_contract":
        p=market("KXBTC15M-OTHER");book=bk(T+5.3,p["ticker"])
    if scenario=="stale":now=T+90
    if scenario=="wide_spread":book=bk(T+5.3,yes=".32",no=".56")
    if scenario=="thin":book=bk(T+5.3,yes_size="2")
    if scenario=="near_expiry":p["seconds_left"]=90
    if scenario=="too_fast":book=bk(T+1);second=spot(60050,T+1)
    if scenario=="too_slow":book=bk(T+40);second=spot(60050,T+40);now=T+40
    if scenario=="no_quotes":book={**book,"best":{"YES":{"bid":None,"ask":None}}}
    if scenario=="bad_timestamp":second["spot_received_at"]=T-20
    if scenario=="invalid_type":second=None
    o=tracker.observe(p,book,second,f,now)
    assert o["action"] in ("WAIT","WATCH")
    assert not o["order_placed"]
    assert o["actual_quote_delay_verified"] is False


def test_lag_no_model_value_is_watch_not_buy():
    tracker=BinanceKalshiLagTracker()
    p=market()
    tracker.observe(p,bk(T+.25),spot(60000,T),{"available":True,"side":"ABOVE","prob_above":.85},T+.25)
    result=tracker.observe(p,bk(T+5.3),spot(60050,T+5),
       {"available":True,"side":"BELOW","prob_above":.2},T+5.3)
    assert result["action"]=="WATCH" and result["probable_observed_lag"]


def test_full_app_snapshot_and_api_use_real_binance_data_but_no_real_order(env):
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    telemetry=BinanceTelemetry(enabled=True)
    main.binance_telemetry=telemetry
    provider.orderbook=lambda m,now=None:bk(clock.now,m["ticker"])
    telemetry.observe_trade(trade(clock.now-.2,90325,1),clock.now-.1)
    baseline=main.update_once()
    assert baseline["binance_kalshi_delay"]["action"]=="WAIT"
    clock.now+=5
    telemetry.observe_trade(trade(clock.now-.2,90380,2),clock.now-.1)
    updated=main.update_once()
    assert updated["binance_kalshi_delay"]["probable_observed_lag"] is True
    assert updated["binance_kalshi_delay"]["action"] in ("BUY_CANDIDATE","WATCH")
    assert updated["binance_kalshi_delay"]["orders_placed"] is False
    api=client.get("/api/state").json()
    assert api["binance_intelligence"]["status"]=="STREAMING"
    assert api["binance_kalshi_delay"]["side"]=="YES"
    assert "binanceLeadSection" in client.get("/").text
    clock.now+=5
    provider.fail_price=True
    degraded=main.update_once()
    assert degraded["binance_kalshi_delay"]["action"]=="WAIT"
    assert not degraded["ok"]
    assert client.get("/api/state").json()["binance_kalshi_delay"]["action"]=="WAIT"



def test_spot_worker_timeout_frame_none_connect_loop_and_stop_paths(monkeypatch):
    from app import binance_telemetry as mod
    monkeypatch.setattr(mod.time,"time",lambda:T)
    b=BinanceTelemetry(enabled=True)
    stopped=threading.Event()
    stopped.set()
    spot_worker(b,stopped)  # no connection if already stopped
    class TimeoutThenNone:
        def __init__(self):self.calls=0
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def recv(self,timeout=None):
            self.calls+=1
            if self.calls==1:raise TimeoutError()
            return None
    sock=TimeoutThenNone()
    class StopOnce:
        def __init__(self):self.waits=0
        def is_set(self):return False
        def wait(self,_delay):
            self.waits+=1
            return self.waits>=2
    stop=StopOnce()
    calls=[]
    def connection(*args,**kwargs):
        calls.append(1)
        return sock
    monkeypatch.setattr(mod,"connect",connection)
    spot_worker(b,stop)
    assert len(calls)==2 and sock.calls>=3 and stop.waits==2
    assert not b.connected
    # Connection may return while worker stop was set; no frames consumed.
    stop_event=threading.Event()
    class EnterSetsStop:
        def __enter__(self):
            stop_event.set()
            return self
        def __exit__(self,*args):return False
        def recv(self,timeout=None):raise AssertionError("Should never read")
    monkeypatch.setattr(mod,"connect",lambda *a,**k:EnterSetsStop())
    spot_worker(b,stop_event)
    assert not b.connected


def test_lag_rejects_binance_trade_observed_before_prior_book():
    tracker=BinanceKalshiLagTracker()
    p=market()
    forecast={"available":True,"side":"ABOVE","prob_above":.8}
    tracker.observe(p,bk(T+.25),spot(60000,T),forecast,T+.25)
    updated=spot(60050,T+5)
    updated["spot_trade_at"]=T+.2
    updated["spot_received_at"]=T+.3
    result=tracker.observe(p,bk(T+5.3),updated,forecast,T+5.3)
    assert result["action"]=="WAIT"
    assert "Binance event" in result["reason"]


def test_lag_rejects_wide_spread_after_valid_big_binance_move():
    tracker=BinanceKalshiLagTracker()
    p=market()
    f={"available":True,"side":"ABOVE","prob_above":.85}
    tracker.observe(p,bk(T+.25),spot(60000,T),f,T+.25)
    updated=bk(T+5.3)
    updated["best"]["YES"]["spread"]=.2
    result=tracker.observe(p,updated,spot(60050,T+5),f,T+5.3)
    assert result["action"]=="WAIT" and "Spread" in result["reason"]


def test_lag_analysis_exception_does_not_interrupt_original_bot(env,monkeypatch):
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    def broken(*args,**kwargs):raise TypeError("injected malformed exchange pair")
    monkeypatch.setattr(main.binance_lag_tracker,"observe",broken)
    state=main.update_once()
    assert state["ok"] and state["model"]["available"]
    assert state["binance_kalshi_delay"]["action"]=="WAIT"
    assert not state["binance_kalshi_delay"]["orders_placed"]
    assert client.get("/health").status_code==200


def test_binance_worker_threads_start_and_stop_with_actual_api_lifespan(env,monkeypatch):
    from fastapi.testclient import TestClient
    main,clock,provider,client,_=env
    monkeypatch.setattr(main,"BINANCE_INTELLIGENCE_ENABLED",True)
    started=set()
    def fake_worker(_tracker,stop_event):
        started.add(threading.current_thread().name)
        stop_event.wait(3)
    monkeypatch.setattr(main,"binance_spot_worker",fake_worker)
    with TestClient(main.app) as live:
        assert live.get("/").status_code==200
        assert "read-only-binance-spot-worker" in (
            {thread.name for thread in threading.enumerate()})
        assert "read-only-binance-funding-worker" not in (
            {thread.name for thread in threading.enumerate()})
    assert "read-only-binance-spot-worker" in started
    assert not any(thread.name.startswith("read-only-binance-") and thread.is_alive()
                   for thread in threading.enumerate())
