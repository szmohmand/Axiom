"""Failure isolation in AXIOM integrated pipeline: optional advanced feeds
and contract-price learner must never break accounting or BTC forecast.
All providers are synthetic, supplied by the established end-to-end fixture.
"""
import math
import pytest
from test_e2e_synthetic import env


def fail(*args,**kwargs):
    raise ValueError("Injected malformed optional component")


@pytest.mark.parametrize("component",[
    "timeframe_feed","btc_trade_flow","candle_context","candle_challenger",
    "quote_repricing",
])
def test_independent_live_pipeline_survives_each_optional_feature_error(
    env,monkeypatch,component):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.AUTO_PAPER=False
    if component=="timeframe_feed":
        p.timeframe_candles=fail
    elif component=="btc_trade_flow":
        monkeypatch.setattr(main.market_flow_tracker,"observe",fail)
    elif component=="candle_context":
        monkeypatch.setattr(main,"read_candlestick_context",fail)
    elif component=="candle_challenger":
        monkeypatch.setattr(main,"derive_candlestick_challenger",fail)
    elif component=="quote_repricing":
        monkeypatch.setattr(main.contract_repricing_tracker,"observe",fail)
    previous=main.ledger.data()["count"]
    status=main.update_once()
    assert status["model"]["available"] and status["ok"]
    assert status["trade_decision"]["order_placed"] is False
    assert main.ledger.data()["count"]["paper"]==previous["paper"]
    assert main.ledger.data()["count"]["calls"]>=previous["calls"]
    if component=="timeframe_feed":
        assert not status["higher_timeframes"]["available"]
    if component=="btc_trade_flow":
        assert not status["market_microstructure"]["available"]
    if component=="candle_context":
        assert not status["candlestick_context"]["available"]
    if component=="candle_challenger":
        assert not status["candlestick_challenger"]["available"]
    if component=="quote_repricing":
        assert not status["contract_repricing"]["available"]
        assert not status["contract_repricing"]["order_placed"]
    assert client.get("/health").status_code==200


def test_completed_real_five_minute_context_is_available_when_provided(env):
    main,clock,p,client,_=env
    clock.now=p.close-600
    def five():
        t=(int(clock.now)//300)*300
        out=[]
        for i in range(40):
            price=90000+i*2
            out.append({"t":t-(40-i)*300,"open":price-1,
                        "high":price+3,"low":price-3,
                        "close":price,"volume":10})
        return out
    p.timeframe_candles=five
    first=main.update_once()
    assert first["ok"] and first["model"]["available"]
    assert set(first["higher_timeframes"]["frames"])=={"30m","1h","2h"}
    assert first["contract_repricing"]["independent_btc_forecast_changed"] is False
    assert not first["contract_repricing"]["order_placed"]


def test_bad_manual_auto_paper_entry_is_isolated_but_observation_commits(env,monkeypatch):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.AUTO_PAPER=True
    monkeypatch.setattr(main,"execution_screen",
                        lambda *a,**k:{"side":"YES","entry_price":.45,
                                      "edge":.5,"reason":"synthetic-only"})
    monkeypatch.setattr(main.ledger,"trade",
                        lambda *a,**k:(_ for _ in ()).throw(
                            ValueError("No valid hypothetical entry")))
    state=main.update_once()
    assert state["ok"]
    assert state["model"]["available"]
    assert main.ledger.conn.execute("SELECT count(*) FROM observations").fetchone()[0]==1
    assert main.ledger.conn.execute("SELECT count(*) FROM paper_trades").fetchone()[0]==0


def test_explicit_opt_in_shadow_grading_keeps_btc_vote_unchanged(env,monkeypatch):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.AUTO_PAPER=False
    monkeypatch.setattr(main,"CANDLESTICK_SHADOW_GRADING_ENABLED",True)
    result=main.update_once()
    assert result["ok"] and result["model"]["available"]
    assert not result["candlestick_challenger"]["votes_in_ensemble"]
    assert not result["candlestick_challenger"]["can_trigger_paper_or_orders"]
    graded={r[0] for r in main.ledger.conn.execute(
        "SELECT DISTINCT engine FROM engine_snapshots WHERE ticker=?",
        (p.ticker,)).fetchall()}
    assert "ensemble" in graded
    assert graded.issuperset({e["name"] for e in result["engines"] if e["available"]})
    # Opt-in adds rows to prospective scoring; never adds a voting BTC engine.
    assert "nison_candlestick_challenger" not in {
        e["name"] for e in result["engines"]}
