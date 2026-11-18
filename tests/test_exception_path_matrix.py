"""Failure-injection and boundary matrix for AXIOM's independent research lanes.

No network, trading credentials, real orders, or external writes.
Existing historical tests remain unchanged.
"""
from __future__ import annotations
import math
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
import requests
from unittest.mock import patch

from app import engine
from app import orderbook as ob
from app import feeds
from app import depth_intelligence as di
from app import settlement_reference as sr
from app import settlement_research as shadow
from app.execution_evidence import examine_liquidity
from app.storage import Ledger
from test_feed_contracts_audit import FakeResponse, provider, market
from test_e2e_synthetic import env


TICK="KXBTC15M-26NOV171800-00"
OPEN="2026-11-17T17:45:00Z"
CLOSE="2026-11-17T18:00:00Z"
TERMS={"ticker":TICK,"status":"settled","result":"yes","open_time":OPEN,
       "close_time":CLOSE,"floor_strike":"90000","expiration_value":"90100"}


def valid_book(t=1000):
    return ob.normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[["0.40","20"],["0.39","10"]],
        "no_dollars":[["0.55","20"],["0.54","10"]]}},TICK,t)


@pytest.mark.parametrize("raw",[
    None,[],{},{"orderbook":{}},{"orderbook_fp":None},
    {"orderbook_fp":{"yes_dollars":None,"no_dollars":[]}},
    {"orderbook_fp":{"yes_dollars":[[.3,1]],"no_dollars":"invalid"}},
    {"orderbook_fp":{"yes_dollars":[[.3,1],[.3,2]],"no_dollars":[]}},
    {"orderbook_fp":{"yes_dollars":[[1.0,2]],"no_dollars":[]}},
    {"orderbook_fp":{"yes_dollars":[["NaN",2]],"no_dollars":[]}},
    {"orderbook_fp":{"yes_dollars":[[.2,-1]],"no_dollars":[]}},
    {"orderbook_fp":{"yes_dollars":[[.2,1,2]],"no_dollars":[]}},
    {"orderbook_fp":{"yes_dollars":[[.8,1]],"no_dollars":[[.7,1]]}},
])
def test_orderbook_malformed_never_looks_available(raw):
    with pytest.raises(ValueError):
        ob.normalize_orderbook(raw,TICK,1000)


@pytest.mark.parametrize("time",["bad",None,float("inf"),float("nan")])
def test_orderbook_bad_receipt_time_rejected(time):
    with pytest.raises(ValueError):
        ob.normalize_orderbook({"orderbook_fp":{"yes_dollars":[],"no_dollars":[]}},TICK,time)


def test_orderbook_empty_unavailable_and_one_sided_is_explicit():
    empty=ob.normalize_orderbook({"orderbook_fp":{"yes_dollars":[],"no_dollars":[]}},TICK,1000)
    assert not empty["available"] and empty["status"]=="UNAVAILABLE"
    single=ob.normalize_orderbook({"orderbook_fp":{"yes_dollars":[["0.50","10"]],"no_dollars":[]}},TICK,1000)
    assert single["available"] and single["best"]["YES"]["ask"] is None
    assert single["best"]["NO"]["ask"]==.5
    assert single["book_imbalance_5c"]==1
    assert ob.current_book(single,TICK,1001)
    for t in (950,1047,997):
        assert not ob.current_book(single,TICK,t)
    assert not ob.current_book(single,"WRONG",1001)


def test_sweep_partial_empty_multilevel_and_sell_spread():
    book=valid_book()
    assert ob.sweep(book,"YES","BUY",5)["complete"]
    partial=ob.sweep(book,"YES","BUY",100)
    assert not partial["complete"] and partial["available_contracts"]==30
    assert partial["levels_consumed"]==2
    assert partial["slippage_from_best"]>0
    sell=ob.sweep(book,"YES","SELL",25)
    assert sell["complete"] and sell["slippage_from_best"]>0
    assert not ob.sweep(book,"NO","SELL",100)["complete"]
    for side,action in (("OTHER","BUY"),("YES","CANCEL")):
        with pytest.raises(ValueError):ob.sweep(book,side,action)
    for size in (0,-1,100001,float("nan"),"invalid",True):
        with pytest.raises(ValueError):ob.sweep(book,"YES","BUY",size)


def test_sweep_bad_normalized_levels_fail_closed():
    book=valid_book()
    for level in ({"price":0,"size":10},{"price":.2,"size":-1},{"price":"inf","size":10}):
        bad={**book,"asks":{**book["asks"],"YES":[level]}}
        with pytest.raises(ValueError):ob.sweep(bad,"YES","BUY")


def test_depth_lanes_reject_missing_invalid_stale_and_illiquid_cases():
    book=valid_book()
    market={"ticker":TICK,"seconds_left":600}
    forecast={"available":True,"side":"ABOVE","prob_above":.9}
    assert di.analyze_opportunities(None,market,book,1002)["status"]=="WAIT"
    assert di.analyze_opportunities(forecast,None,book,1002)["status"]=="WAIT"
    assert di.analyze_opportunities({**forecast,"side":"WAIT"},market,book,1002)["status"]=="WAIT"
    assert di.analyze_opportunities(forecast,market,book,1100)["status"]=="WAIT"
    assert di.analyze_opportunities(forecast,{**market,"seconds_left":50},book,1002)["status"]=="WAIT"
    for p in ("invalid",float("nan"),0,1,None):
        assert di.analyze_opportunities({**forecast,"prob_above":p},market,book,1002)["status"]=="WAIT"
    for size in (0,-1,float("nan"),100001,"invalid"):
        assert di.analyze_opportunities(forecast,market,book,1002,size)["status"]=="WAIT"
    too_big=di.analyze_opportunities(forecast,market,book,1002,100)
    assert too_big["status"]=="WAIT"
    assert all(not c["complete_buy_depth"] for c in too_big["candidates"])
    assert di.execution_guidance(None,forecast,market,book,1100)["action"]=="WAIT"
    assert di.execution_guidance(None,None,market,book,1002)["action"]=="WAIT"
    assert di.execution_guidance(None,{**forecast,"side":"WAIT"},market,book,1002,
                                 position={"side":"YES","contracts":1})["action"]=="WAIT"
    for pos in ({"side":"NO","contracts":-1},{"side":"YES","contracts":"bad"},
                {"side":"OTHER","contracts":1},{"side":"YES","contracts":100}):
        assert di.execution_guidance(None,forecast,market,book,1002,position=pos)["action"]=="WAIT"
    assert di.execution_guidance(None,forecast,market,book,1002)["action"]=="WAIT"


@pytest.mark.parametrize("value",["bad",None,True,float("nan"),"2026-11-17T18:00:00"])
def test_reference_timestamp_rejects_malformed(value):
    with pytest.raises((ValueError,TypeError)):
        sr._time(value)


@pytest.mark.parametrize("value",[None,True,"abc","NaN",float("inf"),0,99,1000000])
def test_reference_money_rejects_nonfinite_and_out_of_range(value):
    with pytest.raises((ValueError,TypeError)):
        sr._money(value)


def test_reference_contract_rejects_inconsistent_clocks_and_tick_types():
    assert sr.reconcile_contract({**TERMS,"ticker":"OTHER"},[])["status"]=="INCOMPLETE"
    assert sr.reconcile_contract({**TERMS,"status":"open"},[])["status"]=="PENDING"
    assert sr.reconcile_contract({**TERMS,"result":""},[])["status"]=="PENDING"
    assert sr.reconcile_contract({**TERMS,"close_time":OPEN},[])["status"]=="INCOMPLETE"
    for ticks in (None,{},[None],[{}],[{"time":True,"value":"90000"}],
                  [{"time":"abc","value":"90000"}],[{"time":1000,"value":"NaN"}]):
        result=sr.reconcile_contract(TERMS,ticks)
        assert result["status"]=="INCOMPLETE" and not result["winner_verified"]


def test_source_candle_recovery_explicitly_rejects_cadence_and_recent_gaps():
    rows=[{"t":i*60} for i in range(65)]
    usable,quality=feeds.contiguous_real_candle_suffix(rows)
    assert quality["status"]=="FULL"
    assert usable==rows
    for size in (0,1,30):
        _,q=feeds.contiguous_real_candle_suffix(rows[:size])
        assert q["status"]=="INSUFFICIENT"
    _,q=feeds.contiguous_real_candle_suffix(rows[:40])
    assert q["status"]=="SHORT_BUT_CONTIGUOUS"
    for delta in (1,59,61,119,121,-60):
        damaged=[dict(x) for x in rows]
        damaged[-1]["t"]=damaged[-2]["t"]+delta
        _,q=feeds.contiguous_real_candle_suffix(damaged)
        assert q["status"]=="INVALID_CADENCE"
    damaged=[dict(x) for x in rows]
    for i in range(50,65):
        damaged[i]["t"]+=60
    _,q=feeds.contiguous_real_candle_suffix(damaged)
    assert q["status"]=="GAP_TOO_RECENT"


def test_live_market_transient_http_503_near_rollover_recovers(monkeypatch):
    now=int(datetime.fromisoformat(CLOSE.replace("Z","+00:00")).timestamp())+8
    monkeypatch.setattr(feeds,"time",SimpleNamespace(time=lambda:now,sleep=lambda _:None))
    p=provider({feeds.KALSHI+"/markets":[FakeResponse(status=503),
              FakeResponse({"markets":[market("KXBTC15M-NEW",now+870)]})]})
    result=p.market(now)
    assert result is not None and result["ticker"]=="KXBTC15M-NEW"
    assert len(p.session.calls)==2


def test_live_market_http_503_outside_boundary_does_not_hide_error(monkeypatch):
    now=int(datetime.fromisoformat(CLOSE.replace("Z","+00:00")).timestamp())+140
    monkeypatch.setattr(feeds,"time",SimpleNamespace(time=lambda:now,sleep=lambda _:None))
    p=provider({feeds.KALSHI+"/markets":FakeResponse(status=503)})
    with pytest.raises(requests.HTTPError):
        p.market(now)
    assert len(p.session.calls)==1


def test_live_provider_malformed_market_rows_do_not_invent_strikes():
    now=1800000000
    p=provider({feeds.KALSHI+"/markets":FakeResponse({"markets":[
        {"ticker":"WRONG"},{"ticker":"KXBTC15M-BAD","close_time":"broken"},
        market("KXBTC15M-GOOD",now+600)]})})
    assert p.market(now)["ticker"]=="KXBTC15M-GOOD"


def test_live_orderbook_bad_market_and_spot_are_explicit():
    p=provider({feeds.COINBASE+"/products/BTC-USD/ticker":FakeResponse({"price":"NaN"})})
    for m in (None,{},{"ticker":"OTHER"},{"ticker":"KXBTC15M-BAD/../"}):
        with pytest.raises(ValueError):p.orderbook(m)
    with pytest.raises(ValueError):p.price()


def test_demo_source_never_confused_with_live_depth(monkeypatch):
    p=feeds.DemoProvider()
    now=1800000000
    m=p.market(now)
    book=p.orderbook(m,now)
    assert book["source"]=="synthetic_demo_orderbook"
    assert "SYNTHETIC" in book["reason"]
    assert len(p.candles())>=31
    assert p.price()>0
    assert p.settlement("OTHER") is None


@pytest.mark.parametrize("raw",["no",None,"NaN",float("inf"),True,{},[]])
def test_engine_numeric_rejects_bad_input(raw):
    assert engine.numeric(raw) is None


def test_engine_dates_and_market_quote_edge_cases():
    assert engine.utc_timestamp(None) is None
    assert engine.utc_timestamp("bad") is None
    assert engine.utc_timestamp(100)==100
    assert engine.quote(1) is None
    assert engine.quote(0) is None
    assert engine.ema([],10)==0
    with pytest.raises(ValueError):engine.market_snapshot({"ticker":"OTHER","close_time":CLOSE})
    with pytest.raises(ValueError):engine.market_snapshot({"ticker":TICK})
    m=engine.market_snapshot({"ticker":TICK,"close_time":CLOSE,
        "yes_bid":45,"no_bid":55,"floor_strike":"invalid"},1794938000)
    assert m["target"] is None and m["yes_bid"]==.45
    assert m["yes_ask"]==.45
    assert m["market_price_is_forecast"] is False


def test_engine_bad_candles_not_synthesized_and_models_abstain():
    raw=[[0,1,2,1.5,1.6,10],["bad",1,2,1.5,1.6,10],
         [60,2,1,1.5,1.6,10],[120,1,2,3,3,10],["bad"],None]
    normalized=engine.normalize_candles(raw)
    assert len(normalized)==1
    assert engine.volatility_forecast(None,90000,600,[])["side"]=="WAIT"
    assert engine.volatility_forecast(90000,None,600,[])["side"]=="WAIT"
    flat=[{"close":90000} for _ in range(35)]
    assert engine.volatility_forecast(90000,90000,600,flat)["side"]=="WAIT"
    assert engine.scalp_signal([],90000)["side"]=="WAIT"
    assert engine.scalp_signal([{"close":90000,"high":90000,"low":90000}]*25,90000)["side"]=="WAIT"
    assert engine.opportunity({"available":False},{})["side"]=="WAIT"
    assert engine.opportunity({"available":True,"prob_above":.5,"side":"ABOVE"},
                              {"yes_ask":None,"no_ask":None})["side"]=="WAIT"
    for bad in (("MAYBE",.5,"yes"),("YES",.5,"pending")):
        with pytest.raises(ValueError):engine.paper_result(*bad)


def test_shadow_research_abstains_on_invalid_target_and_clock():
    for m in (None,{},{"target":float("nan"),"seconds_left":400},
              {"target":90000,"seconds_left":1000},
              {"target":-1,"seconds_left":400}):
        assert shadow.shadow_forecast_from_candles([],m,1000)["side"]=="WAIT"
    assert shadow.shadow_forecast_from_candles(None,
        {"target":90000,"seconds_left":500},1000)["side"]=="WAIT"


def test_ledger_empty_guards_and_unresolved_queue(tmp_path):
    db=Ledger(str(tmp_path/"test.sqlite3"))
    try:
        assert db.unresolved(0)==[]
        assert db.watch_info("NOT-THERE") is None
        assert db.engine_snapshots({"ticker":TICK,"seconds_left":450},
                                  {"engines":[],"available":False},1000)==0
        assert db.engine_scores()["scores"]==[]
        assert db.data()["stats"]["first_call_accuracy"] is None
        with pytest.raises(ValueError):db.export("invalid")
        with pytest.raises(ValueError):db.grade(TICK,"pending",1000)
        with db.atomic_cycle():
            with pytest.raises(RuntimeError):
                with db.atomic_cycle():pass
        assert db._atomic_poll is False
    finally:db.conn.close()


def test_main_http_ledger_failure_and_recovery_preserves_health(env,monkeypatch):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.update_once()
    old=main.ledger.data
    monkeypatch.setattr(main.ledger,"data",lambda:(_ for _ in ()).throw(sqlite3.OperationalError("offline")))
    r=client.get("/api/state")
    assert r.status_code==503 and r.json()["ledger_available"] is False
    assert r.json()["execution_evidence"]["realized_net_profit_usd"] is None
    monkeypatch.setattr(main.ledger,"data",old)
    r=client.get("/api/state")
    assert r.status_code==200 and r.json()["ledger_available"] is True


def test_main_http_healthcheck_failure_is_reported_and_recovers(env,monkeypatch):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.update_once()
    original=main.ledger.healthcheck
    monkeypatch.setattr(main.ledger,"healthcheck",lambda:(_ for _ in ()).throw(sqlite3.OperationalError("offline")))
    assert client.get("/health").status_code==503
    assert "ledger_connection" in client.get("/health").json()["errors"]
    monkeypatch.setattr(main.ledger,"healthcheck",original)
    assert client.get("/health").status_code==200


def test_main_health_stale_and_paper_auth_are_fail_closed(env):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.update_once()
    clock.now+=200
    s=client.get("/api/state").json()
    assert s["status"]=="DEGRADED" and s["model"]["side"]=="WAIT"
    assert s["depth_opportunity"]["status"]=="WAIT"
    assert s["manual_paper_available"] is False
    assert client.post("/api/paper",json={"side":"YES"},
                       headers={"Authorization":"Bearer synthetic-local-testing-token"}).status_code==409


def test_main_grade_invalid_result_retained_as_error(env):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.update_once()
    p.result="invalid"
    main.grade_once()
    assert main.state["settlement"]["status"]=="ERROR"
    assert "settlement" in main.state["errors"]
    assert main.ledger.unresolved()


def test_execution_evidence_incomplete_depth_never_claims_real_fills():
    book=valid_book()
    report=examine_liquidity(book,{"ticker":TICK},1002,size_contracts=1000)
    assert report["book_replay_status"]=="SIMULATED_SAME_SNAPSHOT"
    assert all(v["same_snapshot_spread_crossing_cost_usd"] is None for v in report["scenarios"].values())
    assert report["realized_net_profit_usd"] is None
