"""Every reachable new signal guard gets an explicit deterministic test.

No fake observed fills, no real orders, no overwritten regression fixtures.
"""
from math import sin
import pytest

from app.decision_signals import derive_signals, execution_decision
from app.depth_intelligence import analyze_opportunities
from app.orderbook import normalize_orderbook
from app.feeds import LiveProvider
from test_e2e_synthetic import env  # existing isolated live app + SQLite harness

T=1800000000


def fixture(now=T, close=None):
    if close is None:
        close=now+300
    rows=[]
    for i in range(61):
        t=now-3600+i*60
        p=60000+2*i+6*sin(i*.7)
        rows.append({"t":t,"close":p,"open":p-1,"high":p+3,
                     "low":p-3,"volume":5})
    m={"ticker":"KXBTC15M-COVERAGE", "close_ts":close,
       "seconds_left":close-now, "target":60116, "market_mid":.35}
    return m,rows[-1]["close"],rows


def test_missing_market_bad_candle_stale_ticker_source_and_flat_volatility():
    m,p,c=fixture()
    assert not derive_signals(None,p,c,T)["available"]
    missing=[dict(x) for x in c]
    del missing[7]["t"]
    assert "Invalid Coinbase candle" in derive_signals(m,p,missing,T)["reason"]
    assert "trade event timestamp" in derive_signals(m,p,c,T,spot_source_at=T-120)["reason"]
    flat=[{**row,"close":60000.} for row in c]
    assert "Flat" in derive_signals(m,60000,flat,T)["reason"]


def test_real_first_five_minute_signals_and_both_reversal_branches():
    now=T+180
    m,p,c=fixture(now,close=T+900)
    start=T
    first=next(x for x in c if x["t"]==start)
    second=next(x for x in c if x["t"]==start+60)
    first["open"]=60000
    second["close"]=60100
    up=derive_signals(m,p,c,now)
    assert up["available"]
    assert up["first_two_minute_reversal_flag"]=="EARLY_UP_NO_RELIABLE_REVERSAL"
    assert up["early_displacement_signal"] in ("UP","NEUTRAL")
    first["open"]=60100
    second["close"]=60000
    down=derive_signals(m,p,c,now)
    assert down["first_two_minute_reversal_flag"]=="EARLY_DOWN_REBOUND_TENDENCY"
    assert down["early_displacement_signal"] in ("DOWN","NEUTRAL")
    first["open"]=0
    invalid_open=derive_signals(m,p,c,now)
    assert invalid_open["available"]
    assert invalid_open["early_displacement_bps"] is None


def test_missing_forecast_invalid_candidate_and_reversal_wait():
    m,p,c=fixture()
    sig=derive_signals(m,p,c,T)
    assert sig["available"]
    book={"available":True,"ticker":m["ticker"],"received_at":T}
    selected={"side":"NO","ask_sweep":{"average_price":.41},"bid_sweep":{"average_price":.39},
              "spread":.02,"size_contracts":10,"net_estimated_model_minus_cost":.1}
    op={"status":"CANDIDATE","selected":selected}
    a=execution_decision(sig,None,m,book,op,T)
    assert "forecast" in a["reason"]
    b=execution_decision(sig,{"available":True,"prob_above":None},m,book,op,T)
    assert "Missing direction" in b["reason"]
    c=execution_decision({**sig,"first_two_minute_reversal_flag":
        "EARLY_DOWN_REBOUND_TENDENCY"},{"available":True,"prob_above":.3},m,book,op,T)
    assert "reversal-risk" in c["reason"]
    assert not c["order_placed"]


def test_full_depth_uncertainty_stale_and_reversal_filters_are_real():
    m,p,c=fixture()
    book=normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[["0.38","35"]],"no_dollars":[["0.60","35"]]}},m["ticker"],T)
    fresh=derive_signals(m,p,c,T)
    assert fresh["available"]
    forecast={"available":True,"side":"ABOVE","prob_above":.62}
    baseline=analyze_opportunities(forecast,m,book,T,signals=fresh)
    assert any(x["signal_gate"]=="OK" for x in baseline["candidates"])
    stale=analyze_opportunities(forecast,m,book,T,signals={"available":False})
    assert all(x["signal_gate"]=="Stale or missing BTC dynamics" for x in stale["candidates"])
    near=analyze_opportunities(forecast,{**m,"market_mid":.50},book,T,signals=fresh)
    assert all(x["signal_gate"]=="Near-even quote with weak independent direction"
               for x in near["candidates"])
    rebound=analyze_opportunities({"available":True,"side":"BELOW","prob_above":.3},
        m,book,T,signals={**fresh,"first_two_minute_reversal_flag":
                          "EARLY_DOWN_REBOUND_TENDENCY"})
    assert next(x for x in rebound["candidates"] if x["side"]=="NO")["signal_gate"]=="Early-down rebound risk"


def test_live_ticker_is_rejected_when_exchange_trade_event_stale(monkeypatch):
    p=LiveProvider()
    monkeypatch.setattr(p,"get",lambda *a,**kw:{"price":"60000","time":"2020-01-01T00:00:00Z"})
    with pytest.raises(ValueError,match="stale"):
        p.price()
    p.session.close()


def test_signal_math_error_degrades_real_application_without_entries(env,monkeypatch):
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    def broken(*args,**kwargs):
        raise ArithmeticError("synthetic numeric fault")
    monkeypatch.setattr(main,"derive_signals",broken)
    updated=main.update_once()
    assert updated["btc_signals"]["available"] is False
    assert updated["trade_decision"]["action"]=="WAIT"
    assert updated["execution_intelligence"]["order_placed"] is False
    assert updated["status"]=="DEGRADED"
    assert "btc_signals" in updated["errors"]
