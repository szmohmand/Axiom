"""Adversarial FastAPI + background-worker lifecycle tests, no network or orders."""
from __future__ import annotations
import math
import sqlite3
from types import SimpleNamespace
import pytest

from test_e2e_synthetic import env
from app import feeds
from app import orderbook as ob
from app import settlement_research as shadow


def test_feed_bad_price_and_stale_candles_degrade_without_paper(env,monkeypatch):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.DEMO=False
    original_price=p.price
    monkeypatch.setattr(p,"price",lambda:float("nan"))
    bad=main.update_once()
    assert bad["status"]=="DEGRADED" and "coinbase_ticker" in bad["errors"]
    assert main.ledger.data()["count"]["paper"]==0
    monkeypatch.setattr(p,"price",original_price)
    original_candles=p.candles
    monkeypatch.setattr(p,"candles",lambda:[
        {**c,"t":c["t"]-600} for c in original_candles()])
    stale=main.update_once()
    assert "coinbase_candles" in stale["errors"]
    assert "stale" in stale["errors"]["coinbase_candles"].lower()
    assert not stale["model"]["available"]


def test_optional_research_failure_does_not_break_independent_model(env,monkeypatch):
    main,clock,p,client,_=env
    clock.now=p.close-600
    monkeypatch.setattr(main,"shadow_forecast_from_candles",lambda *a:(_ for _ in ()).throw(ValueError("injected")))
    s=main.update_once()
    assert s["model"]["available"] and s["research_shadow"]["status"]=="UNAVAILABLE"
    assert s["status"]=="DEMO"


def test_depth_failure_is_isolated_and_forecast_still_valid(env,monkeypatch):
    main,clock,p,client,_=env
    clock.now=p.close-600
    from app.orderbook import normalize_orderbook
    book=normalize_orderbook({"orderbook_fp":{"yes_dollars":[["0.40","20"]],
                                               "no_dollars":[["0.55","20"]]}},p.ticker,clock.now)
    monkeypatch.setattr(p,"orderbook",lambda market,now=None:book,raising=False)
    monkeypatch.setattr(main,"analyze_opportunities",
                        lambda *a:(_ for _ in ()).throw(RuntimeError("depth analyzer fault")))
    s=main.update_once()
    assert s["model"]["available"] and s["status"]=="DEMO"
    assert s["depth_opportunity"]["status"]=="WAIT"
    assert "Depth analysis failed" in s["depth_opportunity"]["reason"]
    assert s["execution_intelligence"]["action"]=="WAIT"


def test_model_unavailable_without_feed_error_is_degraded(env,monkeypatch):
    main,clock,p,client,_=env
    clock.now=p.close-600
    monkeypatch.setattr(main,"engine_pack",lambda *a:{
        "available":False,"reason":"synthetic model unavailable","engines":[],"side":"WAIT"})
    s=main.update_once()
    assert s["status"]=="DEGRADED" and "forecast" in s["errors"]
    assert s["opportunity"]["side"]=="WAIT"


def test_unresolved_queue_confirmation_failure_never_marked_healthy(env,monkeypatch):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.update_once()
    original=main.ledger.unresolved
    calls=[0]
    def injected(*args,**kwargs):
        calls[0]+=1
        if calls[0]==2:raise sqlite3.OperationalError("injected queue check outage")
        return original(*args,**kwargs)
    monkeypatch.setattr(main.ledger,"unresolved",injected)
    main.grade_once()
    assert main.state["settlement"]["status"]=="ERROR"
    assert "__ledger__" in main.settlement_failures
    assert "settlement" in main.state["errors"]
    assert client.get("/health").status_code==503


def test_market_worker_exception_marks_error_not_silent_live(env,monkeypatch):
    main,clock,p,client,_=env
    counter=[0]
    class Shutdown:
        def is_set(self):
            counter[0]+=1
            return counter[0]>1
        def wait(self,secs):return True
    monkeypatch.setattr(main,"shutdown",Shutdown())
    monkeypatch.setattr(main,"update_once",lambda:(_ for _ in ()).throw(RuntimeError("synthetic worker fault")))
    main.worker()
    assert main.state["status"]=="ERROR"
    assert "worker" in main.state["errors"]


def test_settlement_worker_exception_and_independent_session_cleanup(env,monkeypatch):
    main,clock,p,client,_=env
    from app.feeds import LiveProvider
    live=LiveProvider()
    monkeypatch.setattr(main,"provider",live)
    attempts=[0]
    class Shutdown:
        def wait(self,secs):
            attempts[0]+=1
            return attempts[0]>1
    monkeypatch.setattr(main,"shutdown",Shutdown())
    monkeypatch.setattr(main,"grade_once",lambda *a:(_ for _ in ()).throw(RuntimeError("synthetic settlement fault")))
    main.grading_worker()
    assert attempts[0]==2
    assert "settlement_worker" in main.state["errors"]
    assert main.state["status"]=="DEGRADED"


def test_paper_position_depth_failure_returns_wait_not_http_500(env,monkeypatch):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.update_once()
    auth={"Authorization":"Bearer synthetic-local-testing-token"}
    assert client.post("/api/paper",json={"side":"YES"},headers=auth).status_code==200
    monkeypatch.setattr(main,"execution_guidance",lambda *a,**kw:(_ for _ in ()).throw(ValueError("synthetic")))
    d=client.get("/api/state").json()
    assert d["paper_position_execution"]["action"]=="WAIT"
    assert "unavailable" in d["paper_position_execution"]["reason"].lower()


def test_manual_paper_disabled_and_crossed_quotes_rejected(env):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.update_once()
    main.ADMIN_TOKEN=""
    assert client.post("/api/paper",json={"side":"YES"}).status_code==403
    main.ADMIN_TOKEN="synthetic-local-testing-token"
    main.state["market"]["yes_ask"]=.30
    main.state["market"]["yes_bid"]=.40
    assert client.post("/api/paper",json={"side":"YES"},headers={
        "Authorization":"Bearer synthetic-local-testing-token"}).status_code==409


def test_demo_provider_result_waits_until_expiration_and_does_not_use_live(env,monkeypatch):
    p=feeds.DemoProvider()
    now=1800000000
    m=p.market(now)
    block=int(m["ticker"].rsplit("-",1)[-1])
    close=(block+1)*900
    monkeypatch.setattr(feeds,"time",SimpleNamespace(time=lambda:close))
    assert p.settlement(m["ticker"]) is None
    monkeypatch.setattr(feeds,"time",SimpleNamespace(time=lambda:close+6))
    assert p.settlement(m["ticker"]) in ("yes","no")


def test_rollover_retry_second_http_failure_stays_unavailable(monkeypatch):
    from datetime import datetime
    from test_feed_contracts_audit import provider,FakeResponse
    now=int(datetime.fromisoformat("2026-11-17T18:00:00+00:00").timestamp())+5
    monkeypatch.setattr(feeds,"time",SimpleNamespace(time=lambda:now,sleep=lambda _:None))
    p=provider({feeds.KALSHI+"/markets":[FakeResponse({"markets":[]}),FakeResponse(status=503)]})
    assert p.market(now) is None
    assert len(p.session.calls)==2


def test_broken_depth_orderbook_never_converts_to_real_fills():
    from app.execution_evidence import examine_liquidity
    book={"available":True,"ticker":"KXBTC15M-TEST","received_at":1000,
          "asks":{"YES":[{"price":0,"size":10}],"NO":[]},
          "bids":{"YES":[],"NO":[]}}
    r=examine_liquidity(book,{"ticker":"KXBTC15M-TEST"},1001)
    assert r["book_replay_status"]=="INVALID_BOOK"
    assert r["realized_net_profit_usd"] is None


def test_shadow_research_malformed_completed_candles_rejected():
    market={"target":90000,"seconds_left":600}
    now=1800000000
    good=[{"t":now-(50-i)*60,"close":90000+i*2} for i in range(50)]
    for replacement in (None,{},{"t":"invalid","close":90000},
                        {"t":now-60,"close":float("nan")}):
        rows=list(good)
        rows[20]=replacement
        r=shadow.shadow_forecast_from_candles(rows,market,now)
        assert r["status"]=="UNAVAILABLE"
