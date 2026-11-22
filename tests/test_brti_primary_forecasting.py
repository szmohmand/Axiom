"""BRTI-first forecasting end-to-end purity and missing-data tests."""
import math
from app.brti_candles import (completed_one_minute, completed_five_minute,
                              final_minute_prefix, completed_minute_sigma)
from app.brti_live import BRTITracker
from app.ensemble import engine_pack
from app.settlement_probability import forecast as settlement_forecast
from app.market_structure import timeframes


BASE = 1795046400000  # exact UTC minute


def tick(ts_ms, value):
    return {"type": "cfbenchmarks_value_5hz",
            "msg": {"index_id": "BRTI", "value_usd": str(value),
                    "source_ts_ms": ts_ms, "received_at": ts_ms + 20,
                    "data": "{}"}}


def sample_tracker(minutes=65):
    tracker = BRTITracker(enabled=True)
    tracker.mark(connected=True, subscribed="cfbenchmarks_value_5hz")
    for i in range(minutes * 60 + 10):
        stamp = BASE + i * 1000
        price = 64000 + i * .003 + math.sin(i / 100) * 1.5
        assert tracker.accept(tick(stamp, price), stamp + 40)
    return tracker


def test_real_received_index_samples_build_price_only_candles_and_live_frames():
    t = sample_tracker(130)
    end = BASE + (130 * 60 + 9) * 1000 + 40
    snap = t.snapshot(end)
    assert snap["status"] == "STREAMING"
    assert snap["price_candle_source"] == "cfbenchmarks_brti_authenticated_live"
    assert snap["candle_quality"]["missing_seconds_filled"] == 0
    bars = snap["btc_1m_candles"]
    assert len(bars) >= 62
    assert all(b["source"] == "cfbenchmarks_brti_authenticated_live" for b in bars)
    assert all(b["volume"] is None and b["observed_seconds"] == 60 for b in bars)
    assert bars[-1]["t"] + 60 <= end / 1000
    assert snap["completed_minute_sigma_45"] is not None
    five = snap["btc_5m_candles"]
    assert len(five)>=25, (len(bars),len(five),bars[0]['t'],bars[-1]['t'])
    assert all(bar["volume"] is None for bar in five)
    higher = timeframes(five, end / 1000)
    assert higher["available"] and higher["source"] == "cfbenchmarks_brti_authenticated_live"
    assert {"30m","1h","2h"} <= set(higher["frames"])


def test_missing_index_seconds_are_never_interpolated_or_counted_as_complete():
    samples = {BASE // 1000 + sec: 64000 + .1 * sec for sec in range(180)}
    first = completed_one_minute(samples, BASE / 1000 + 180)
    assert len(first) == 3
    for sec in range(60, 83):
        samples.pop(BASE // 1000 + sec)
    recovered = completed_one_minute(samples, BASE / 1000 + 180)
    assert len(recovered) == 1  # genuine contiguous suffix after a missing minute
    assert completed_five_minute(recovered) == []
    prefix = final_minute_prefix(samples, BASE / 1000 + 120, BASE // 1000 + 100)
    assert prefix["complete_prefix"] is False
    assert prefix["observed_mean_usd"] is None
    assert completed_minute_sigma(recovered) is None


def test_model_uses_authentic_index_and_reports_eighth_vote_separate_from_quotes():
    t=sample_tracker(65)
    now=(BASE + (65 * 60 + 9) * 1000 + 40) / 1000
    snapshot=t.snapshot(round(now * 1000))
    spot=float(snapshot["latest_value_usd"])
    candles=snapshot["btc_1m_candles"]
    market={"ticker":"KXBTC15M-BRTI", "target":spot+1,
            "seconds_left":480, "close_ts":now+480}
    context={"brti":snapshot,
             "timeframes":timeframes(snapshot["btc_5m_candles"], now),
             "microstructure":{}}
    result=engine_pack(spot,market,candles,context=context,now=now)
    assert result["available"]
    assert "axiom_brti_settlement" in result["active_predictive_models"]
    assert all(name not in result["active_predictive_models"]
               for name in ("kalshi_market", "coinbase_market", "binance_market"))
    assert result["method"]=="experimental-equal-weight-mean-consensus"
    changed=engine_pack(spot,{**market,"yes_ask":.99,"no_bid":.01,
                              "market_mid":.99,"volume":1e9},
                        candles,context=context,now=now)
    assert changed["prob_above"] == result["prob_above"]
    boosted=next(x for x in result["engines"] if x["name"]=="axiom_gradient_boosted_btc")
    assert boosted["available"]


def test_settlement_model_final_minute_uses_actual_received_prefix_not_only_last_price():
    close=BASE/1000+900
    market={"ticker":"KXBTC15M-BRTI", "target":64050, "close_ts":close}
    now=close-30
    brti={"status":"STREAMING", "authenticated_stream_verified":True,
          "latest_value_usd":"64010", "source_ts_ms":int(now*1000),
          "axiom_received_at_ms":int(now*1000)+25,
          "completed_minute_sigma_45":.001,
          "settlement_window_stats":{"window_end_ts":close,
              "complete_prefix":True,"observed_seconds":30,
              "expected_seconds":30,"observed_mean_usd":64090}}
    prob=settlement_forecast(market,brti,[],now)
    assert prob["available"] and prob["observed_final_minute_seconds"]==30
    assert abs(prob["estimated_final_mean_usd"]-64050)<.01
    assert abs(prob["prob_above"]-.5)<.01
    brti["settlement_window_stats"]["complete_prefix"]=False
    assert not settlement_forecast(market,brti,[],now)["available"]
    brti["status"]="STALE"
    assert not settlement_forecast(market,brti,[],now)["available"]


def test_live_brti_warmup_keeps_server_operational_but_blocks_predictions_and_paper(env, monkeypatch):
    # Real authenticated reference, but <31 completed BRTI candles since start.
    main,clock,provider,client,_=env
    main.DEMO=False
    clock.now=provider.close-600
    candles=provider.candles()[-12:]
    for b in candles:
        b["source"]="cfbenchmarks_brti_authenticated_live"
        b["volume"]=None
    sample={
        "status":"STREAMING", "authenticated_stream_verified":True,
        "latest_value_usd":"90325.0",
        "source_ts_ms":int(clock.now*1000),
        "axiom_received_at_ms":int(clock.now*1000)+10,
        "btc_1m_candles":candles,"btc_5m_candles":[],
        "candle_quality":{"status":"WARMING_BRTI_LIVE","bars_used":12,
                          "missing_seconds_filled":0},
    }
    monkeypatch.setattr(main.brti_tracker,"snapshot",lambda now_ms=None:sample)
    def forbidden(*args,**kwargs):
        raise AssertionError("Forbidden Coinbase access during live BRTI warmup")
    provider.price=forbidden
    provider.candles=forbidden
    provider.timeframe_candles=forbidden
    out=main.update_once()
    assert out["status"]=="LIVE" and out["ok"] is True
    assert out["price_source"]=="CF_BENCHMARKS_BRTI"
    assert out["forecast_warming"] is True
    assert out["model"]["available"] is False
    assert out["opportunity"]["side"]=="WAIT"
    assert out["execution_intelligence"]["order_placed"] is False
    assert client.get('/health').status_code==200
    state=client.get('/api/state')
    assert state.status_code==200
    assert state.json()["manual_paper_available"] is False
    auth={"Authorization":"Bearer synthetic-local-testing-token"}
    assert client.post('/api/paper',json={"side":"YES"},headers=auth).status_code==409
    assert main.ledger.data()['count']=={'calls':0,'paper':0}
