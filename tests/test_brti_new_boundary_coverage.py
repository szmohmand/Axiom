"""Exhaustively exercise BRTI-only boundary conditions reported by full-source coverage.

Every malformed timestamp, missing second, invalid benchmark/volatility and
impossible final-window estimate must fail closed; never backfill Coinbase.
"""
import math

from app.brti_candles import (
    SOURCE, completed_one_minute, completed_five_minute,
    completed_minute_sigma, final_minute_prefix)
from app.brti_live import BRTITracker
from app.settlement_probability import (
    _sigma_benchmark_only, forecast as settlement_forecast)
from test_e2e_synthetic import env


BASE = 1795046400000
SEC = BASE // 1000


def reference(now, **overrides):
    row = {
        "status": "STREAMING", "authenticated_stream_verified": True,
        "latest_value_usd": "64010.0",
        "source_ts_ms": int(now * 1000),
        "axiom_received_at_ms": int(now * 1000),
        "completed_minute_sigma_45": .001,
    }
    row.update(overrides)
    return row


def contract(now, **overrides):
    item = {"ticker": "KXBTC15M-TEST", "target": 64000.,
            "close_ts": now + 300}
    item.update(overrides)
    return item


def test_candle_reader_rejects_bad_second_types_and_nonphysical_prices():
    assert completed_one_minute({"bad-seconds": 64000.}, SEC + 300) == []
    assert completed_one_minute({SEC: float("nan")}, SEC + 300) == []
    assert completed_one_minute({SEC: -1.0}, SEC + 300) == []
    assert completed_one_minute({SEC: 0.}, SEC + 300) == []
    assert completed_one_minute({SEC: "64000"}, SEC + 300) == []
    assert completed_one_minute({True: 64000.}, SEC + 300) == []


def test_five_minute_rejects_invalid_type_and_missing_component_minute():
    assert completed_five_minute(None) == []
    assert completed_five_minute("not an actual candle list") == []
    # One observed 1m BRTI bar does not imply all five exist.
    bar = {"t": SEC, "open": 64000.0, "high": 64000.,
           "low": 64000., "close": 64000., "volume": None,
           "source": SOURCE}
    assert completed_five_minute([bar]) == []


def test_sigma_rejects_discontinuity_and_nonpositive_reference_price():
    bars=[{"t":SEC + i * 60,"close":64000.+i} for i in range(35)]
    gap=[dict(x) for x in bars]
    gap[10]["t"] += 60
    assert completed_minute_sigma(gap) is None
    negative=[dict(x) for x in bars]
    negative[-1]["close"]=0.
    assert completed_minute_sigma(negative) is None


def test_settlement_prefix_rejects_bad_or_outside_window_coordinates():
    assert final_minute_prefix({}, "bad", SEC) is None
    assert final_minute_prefix({}, float("inf"), SEC) is None
    assert final_minute_prefix({}, SEC+61, SEC+5) is None
    assert final_minute_prefix({}, SEC+60, SEC-10) is None
    assert final_minute_prefix({}, SEC+60, SEC+60) is None


def test_benchmark_tracker_keeps_first_second_tick_and_evicts_stale_ram():
    t=BRTITracker(enabled=True)
    t.mark(connected=True)
    def packet(ts):
        return {"type":"cfbenchmarks_value_5hz","msg":{
            "index_id":"BRTI","value_usd":"64010",
            "source_ts_ms":ts,"received_at":ts+20,"data":"{}"}}
    assert t.accept(packet(BASE),BASE+40)
    assert t.accept(packet(BASE+200),BASE+240)
    assert len(t.seconds)==1
    assert t.seconds[SEC]==64010.
    # Memory cannot grow forever while the feed streams several hours.
    t.seconds={SEC-j:64010. for j in range(1,11002)}
    assert t.accept(packet(BASE+1000),BASE+1040)
    assert len(t.seconds)<=10801
    assert min(t.seconds)>=SEC-3*3600+1


def test_settlement_reference_type_strike_horizon_authentication_and_freshness():
    now=SEC+100
    r=reference(now)
    m=contract(now)
    assert not settlement_forecast(None,r,[],now)["available"]
    assert not settlement_forecast(m,None,[],now)["available"]
    assert not settlement_forecast({**m,"target":None},r,[],now)["available"]
    assert not settlement_forecast({**m,"target":-1},r,[],now)["available"]
    assert not settlement_forecast({**m,"close_ts":now-1},r,[],now)["available"]
    assert not settlement_forecast({**m,"close_ts":now+901},r,[],now)["available"]
    assert not settlement_forecast(m,{**r,"status":"STALE"},[],now)["available"]
    assert not settlement_forecast(m,{**r,"source_ts_ms":int((now-60)*1000)},[],now)["available"]
    assert not settlement_forecast(m,{**r,"latest_value_usd":None},[],now)["available"]


def test_final_minute_prefix_cannot_be_malformed_or_arbitrarily_huge():
    now=SEC+100
    m=contract(now,close_ts=now+30)
    r=reference(now)
    r["settlement_window_stats"]={"window_end_ts":m["close_ts"],
        "complete_prefix":True,"observed_seconds":61,
        "expected_seconds":61,"observed_mean_usd":64000.}
    bad=settlement_forecast(m,r,[],now)
    assert bad["available"] is False
    assert "coverage invalid" in bad["reason"]
    r["settlement_window_stats"]["observed_seconds"]=30
    r["settlement_window_stats"]["expected_seconds"]=30
    r["settlement_window_stats"]["observed_mean_usd"]=1e308
    huge=settlement_forecast(m,r,[],now)
    assert huge["available"] is False
    assert "conditional variance or benchmark average" in huge["reason"]


def test_benchmark_only_fallback_volatility_does_not_accept_exchange_prices():
    assert _sigma_benchmark_only("not candles") is None
    assert _sigma_benchmark_only([{"close":64000,"source":"COINBASE"}]*31) is None
    assert _sigma_benchmark_only([{"close":0.,"source":SOURCE}]*31) is None
    now=SEC+100
    bars=[{"close":64000 + i*0.04 + 3*math.sin(i/3),
           "source":SOURCE} for i in range(46)]
    valid=settlement_forecast(contract(now),reference(
        now,completed_minute_sigma_45=None),bars,now)
    assert valid["available"] is True
    assert valid["volatility_source"]=="authenticated_BRTI_completed_minutes"


def test_live_streaming_reference_rejects_nan_without_coinbase_retry(env,monkeypatch):
    main,clock,provider,client,_=env
    main.DEMO=False
    clock.now=provider.close-600
    snapshot=reference(clock.now,latest_value_usd="nan",
                       btc_1m_candles=[],btc_5m_candles=[])
    monkeypatch.setattr(main.brti_tracker,"snapshot",lambda now_ms=None:snapshot)
    provider.price=lambda:(_ for _ in ()).throw(AssertionError("Forbidden live Coinbase"))
    provider.candles=lambda:(_ for _ in ()).throw(AssertionError("Forbidden live Coinbase"))
    out=main.update_once()
    assert out["spot"] is None
    assert out["errors"]["brti_stream"]=="Invalid authenticated CF Benchmarks BRTI index value"
    assert not out["model"]["available"]
    assert not out["ok"]
    assert main.ledger.data()['count']=={"calls":0,"paper":0}


def test_demo_candle_exception_preserves_error_and_wait(env):
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    provider.candles=lambda:(_ for _ in ()).throw(RuntimeError("invalid demo candle network"))
    out=main.update_once()
    assert out["status"]=="DEGRADED"
    assert "coinbase_candles" in out["errors"]
    assert "RuntimeError" in out["errors"]["coinbase_candles"]
    assert out["model"]["available"] is False
    assert out["opportunity"]["side"]=="WAIT"
