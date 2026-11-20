"""Binance public stream, published funding and Binance-first Kalshi lag.

Futures funding is SECONDARY nonvoting context. REST quote timestamps are
receipt times, not exchange first-publication clocks or executable fills.
"""
import json
import threading

import pytest
import requests

from app.binance_telemetry import (BinanceTelemetry, finite, invalid,
                                    spot_worker, funding_worker)
from app.lag_intelligence import BinanceKalshiLagTracker, wait
from app.orderbook import normalize_orderbook
from test_e2e_synthetic import env

T=1800000000.0


def trade(seconds=T,price=60000,tid=1):
    ms=int(seconds*1000)
    return {"e":"aggTrade","s":"BTCUSDT","a":tid,
            "T":ms,"E":ms+5,"p":str(price)}


def funding(seconds=T,rate=".00015"):
    return {"symbol":"BTCUSDT","lastFundingRate":rate,
            "time":int(seconds*1000),
            "nextFundingTime":int((seconds+1200)*1000),
            "markPrice":"60020","indexPrice":"60000"}


def bk(seconds=T,ticker="KXBTC15M-TEST",yes=".38",no=".60",
       yes_size="35",no_size="35"):
    return normalize_orderbook({"orderbook_fp":{"yes_dollars":[[yes,yes_size]],
       "no_dollars":[[no,no_size]]}},ticker,seconds)


def market(ticker="KXBTC15M-TEST"):
    return {"ticker":ticker,"seconds_left":600,"close_ts":T+600,
            "target":60010,"market_mid":.39}


def spot(price,seconds,now=None,funding_rate=None):
    return {"status":"STREAMING","spot_price":price,"spot_trade_at":seconds-.15,
            "spot_received_at":seconds-.05,
            "funding_bias":"LONGS_PAY_SHORTS" if funding_rate else "UNKNOWN",
            "funding_percent":funding_rate,
            "funding_status":"LIVE" if funding_rate else "UNAVAILABLE"}


def test_binance_spot_and_funding_are_real_distinct_timestamped_sources():
    b=BinanceTelemetry(enabled=True)
    assert b.snapshot(T)["status"]=="UNAVAILABLE"
    assert b.observe_trade(trade(T-.1),T)
    assert b.observe_funding(funding(T-1),T)
    s=b.snapshot(T+.25)
    assert s["status"]=="STREAMING"
    assert s["spot_price"]==60000
    assert s["funding_status"]=="LIVE"
    assert s["funding_percent"]==pytest.approx(.015)
    assert s["funding_bias"]=="LONGS_PAY_SHORTS"
    assert s["funding_mark_index_basis_bps"]>0
    assert s["settlement_reference"] is False
    assert s["funding_direction_is_prediction"] is False
    assert s["orders_placed"] is False
    assert b.snapshot(T+8)["status"]=="STALE"
    assert b.snapshot(T+190)["funding_status"]=="STALE"
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


def test_binance_trade_order_duplicate_and_funding_sign_and_errors():
    b=BinanceTelemetry(enabled=True)
    assert b.observe_trade(trade(T,tid=11),T+.1)
    assert not b.observe_trade(trade(T,tid=11),T+.2)
    assert not b.observe_trade(trade(T-1,tid=12),T+.2)
    assert b.observe_trade(trade(T+.1,tid=12),T+.2)
    assert b.observe_funding(funding(T-1,rate="-.0003"),T)
    assert b.snapshot(T+.2)["funding_bias"]=="SHORTS_PAY_LONGS"
    assert b.observe_funding(funding(T-1,rate="0"),T)
    assert b.snapshot(T+.2)["funding_bias"]=="NEUTRAL"
    b.note_funding_error("HTTPError")
    assert b.snapshot(T+200)["funding_reason"]=="HTTPError"
    assert not BinanceTelemetry().snapshot(T)["orders_placed"]


@pytest.mark.parametrize("field,value",[
    ("symbol","WRONG"),("lastFundingRate","nan"),
    ("lastFundingRate",".7"),("time",1000),
    ("time",int((T-90)*1000)),("nextFundingTime",0),
    ("markPrice","0"),("indexPrice","nan")])
def test_binance_funding_validation_rejects_unavailable_or_stale(field,value):
    b=BinanceTelemetry(enabled=True)
    d=funding(T)
    d[field]=value
    assert not b.observe_funding(d,T)
    assert b.snapshot(T)["funding_status"]=="UNAVAILABLE"


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


def test_funding_worker_success_and_bad_http_are_bounded(monkeypatch):
    from app import binance_telemetry as mod
    class Stop:
        def is_set(self):return False
        def wait(self,s):return True
    class Response:
        def raise_for_status(self):return None
        def json(self):return funding(T-1)
    class Session:
        def __init__(self):self.closed=False
        def get(self,*a,**k):return Response()
        def close(self):self.closed=True
    instance=Session()
    monkeypatch.setattr(mod.requests,"Session",lambda:instance)
    monkeypatch.setattr(mod.time,"time",lambda:T)
    b=BinanceTelemetry(enabled=True)
    funding_worker(b,Stop())
    assert instance.closed and b.snapshot(T)["funding_status"]=="LIVE"
    class BrokenSession(Session):
        def get(self,*args,**kwargs):
            raise requests.RequestException("geoblocked")
    monkeypatch.setattr(mod.requests,"Session",BrokenSession)
    funding_worker(b,Stop())
    assert b.last_funding_error=="RequestException"
    class Invalid(Response):
        def json(self):return {"symbol":"BTCUSDT"}
    class InvalidSession(Session):
        def get(self,*a,**k):return Invalid()
    monkeypatch.setattr(mod.requests,"Session",InvalidSession)
    funding_worker(b,Stop())
    assert b.last_funding_error=="InvalidOrStaleFundingPayload"


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
    assert not second["funding_used_for_direction"]
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
