"""Coverage of real BTC 5m acquisition, learned-tree guardrails, BTC-only
context and exception-isolated optional components. No external networks.
"""
import base64
import json
import math
import zlib

import pytest

from app import boosted_model as bm
from app import ensemble
from app import feeds
from app import market_structure as ms
from app import contract_repricing as repricing
from app.orderbook import normalize_orderbook
from test_e2e_synthetic import env

NOW=1800009000


def btc_bars(now=NOW,n=75):
    out=[]
    for i in range(n):
        p=63000+i*3+4*math.sin(i/3)
        out.append({"t":now-n*60+i*60,"open":p-.5,
                    "high":p+3,"low":p-3,"close":p,"volume":5+i/20})
    return out


def five_minute_raw(now=NOW,n=36):
    # Coinbase returns [minute_start, low, high, open, close, volume]
    return [[now-n*300+i*300,63000+i*2-3,63000+i*2+3,
             63000+i*2-1,63000+i*2,8.0] for i in range(n)]


def test_coinbase_five_minute_cache_completed_only_and_avoids_network(monkeypatch):
    p=feeds.LiveProvider()
    try:
        queries=[]
        raw=five_minute_raw()
        def get(url,params=None):
            queries.append((url,params))
            return raw
        monkeypatch.setattr(p,"get",get)
        first=p.timeframe_candles(now=NOW)
        assert len(first)==36
        assert len(queries)==1
        assert all(b["t"]%300==0 and b["t"]+300<=NOW for b in first)
        assert p.timeframe_candles(now=NOW+30)==first
        assert len(queries)==1, "Fresh cached data should not trigger a request"
        assert p.timeframe_candles(now=NOW+91)
        assert len(queries)==2
        # Only real bars after a missing candle are returned: never forward fill.
        p._five_minute_cache=[]
        raw=[row for i,row in enumerate(five_minute_raw()) if i!=13]
        recovered=p.timeframe_candles(now=NOW)
        assert recovered[0]["t"]==raw[13][0]
        assert len(recovered)==22
        assert len(queries)==3
        p._five_minute_cache=[]
        raw=[]
        assert p.timeframe_candles(now=NOW+300)==[]
        assert len(queries)==4
        # A modern wall-clock request is independent of injected replay time.
        assert p.timeframe_candles()==[]
    finally:
        p.session.close()


def test_five_minute_history_and_strict_aggregation_guards():
    valid=[]
    for i in range(34):
        p=63000+2*i
        valid.append({"t":NOW-34*300+i*300,"open":p-.5,
                      "high":p+3,"low":p-3,"close":p,"volume":8.0})
    r=ms.timeframes(valid,NOW)
    assert r["available"] and {"30m","1h","2h"}==set(r["frames"])
    assert r["frames"]["2h"]["fully_closed_source_bars"]==24
    assert not ms.timeframes(None,NOW)["available"]
    assert not ms.timeframes(valid[:5],NOW)["available"]
    assert ms.timeframes(valid[-10:],NOW)["available"]
    for invalid in (
        [{**valid[0],"open":"bad"}]+valid[1:],
        [None]+valid[1:],
        valid[:-1]+[{**valid[-1],"t":NOW+300}],
        valid[:20]+[{**valid[20],"t":valid[19]["t"]}]+valid[21:],
        valid[:-1]+[{**valid[-1],"low":-1}],
        valid[:-1]+[{**valid[-1],"volume":-1}],
    ):
        assert not ms.timeframes(invalid,NOW)["available"]
    assert not ms.timeframes(valid,NOW+1200)["available"]
    no_moves=[{**x,"open":1000.,"high":1000.,"low":1000.,"close":1000.}
              for x in valid]
    flat=ms.timeframes(no_moves,NOW)
    assert flat["available"]
    assert all(v["directional_efficiency"]==0 for v in flat["frames"].values())
    assert all(v["close_location"]==0 for v in flat["frames"].values())


def test_quote_kalshi_must_be_unavailable_to_btc_only_flow_even_when_injected():
    tracker=ms.BTCFlowTracker()
    assert not tracker.observe()["available"]
    assert not tracker.observe(binance={"cvd_2m":{"taker_imbalance":"bad",
                                                    "trades_seen":900}})["available"]
    assert ms._num("bad") is None
    assert ms._num(True) is None
    assert ms._num(float("inf")) is None
    btc={"cvd_2m":{"taker_imbalance":.7,"trades_seen":80},
         "large_trade_activity":{"net_taker_usdt":50000.,
                                  "large_trade_threshold_usdt":10000.,
                                  "large_print_count":8}}
    yes=tracker.observe(binance=btc)
    malicious=tracker.observe(
        market={"ticker":"KXBTC15M-SHADOW","market_mid":.99,
                "yes_ask":.99,"no_ask":.02},
        book={"best":{"YES":{"bid":.99}}},binance=btc)
    assert yes==malicious
    assert yes["available"]
    assert not yes["uses_kalshi_quotes_for_prediction"]
    for args in ((None,None,.5,None),(63000,None,.5,{}),
                 (63000,{"ticker":"x"},None,{})):
        assert not ms.pressure_forecast(*args)["available"]
    context={"timeframes":{"directional_components":{"kalshi_market_mid":999}},
             "microstructure":{"directional_components":{"kalshi_depth_imbalance":-999}}}
    m={"ticker":"KXBTC15M-TEST","seconds_left":600,"target":63000}
    assert not ms.pressure_forecast(63000,m,.6,context)["available"]
    context["microstructure"]["directional_components"]["btc_taker_cvd_2m"]=.5
    assert ms.pressure_forecast(63000,m,.6,context)["available"]
    assert not ms.pressure_forecast(63000,m,0,context)["available"]


@pytest.mark.parametrize("invalid",[
    "none","nondict","bad_timestamp","missing_history","history_gap",
    "stale","bad_close","constant","bad_ohlc",
])
def test_boosted_model_inputs_fail_without_fabricated_learned_prediction(invalid):
    candles=btc_bars()
    m={"target":63190,"seconds_left":600}
    if invalid=="none":candles=None
    if invalid=="nondict":candles[0]=False
    if invalid=="bad_timestamp":candles[-1]["t"]+=1
    if invalid=="missing_history":candles=candles[:22]
    if invalid=="history_gap":candles[-8]["t"]+=60
    if invalid=="stale":candles=candles[:-2]
    if invalid=="bad_close":candles[-1]["close"]=-1
    if invalid=="constant":
        for b in candles:
            b.update(open=63000.,close=63000.,low=62999.,high=63001.)
    if invalid=="bad_ohlc":candles[-1]["high"]=candles[-1]["low"]-1
    f=bm.boosted_forecast(63180,m,candles,NOW+240 if invalid=="stale" else NOW)
    assert not f["available"] and f["prob_above"] is None


def test_boosted_model_artifact_validation_and_bad_scalar_forecast(monkeypatch):
    original=bm._MODEL_B85
    bm._model.cache_clear()
    tampered=base64.b85encode(zlib.compress(json.dumps({
        "features":[],"trees":[]}).encode()))
    monkeypatch.setattr(bm,"_MODEL_B85",tampered)
    with pytest.raises(ValueError,match="Invalid bundled trained model"):
        bm._model()
    bm._model.cache_clear()
    monkeypatch.setattr(bm,"_MODEL_B85",original)
    assert len(bm._model()["trees"])==12
    bars=btc_bars()
    for market in (None,{},{"target":0,"seconds_left":600},
                   {"target":63190,"seconds_left":0},
                   {"target":float("nan"),"seconds_left":600}):
        assert not bm.boosted_forecast(63180,market,bars,NOW)["available"]
    valid=bm.boosted_forecast(63180,{"target":63190,"seconds_left":600},bars,NOW)
    assert valid["available"] and valid["trained"]
    assert valid["base_normal_probability"] != valid["prob_above"]


def test_ensemble_independently_contains_faults_in_each_new_engine(monkeypatch):
    candles=btc_bars()
    m={"ticker":"KXBTC15M-TEST","target":63190,
       "close_ts":NOW+600,"seconds_left":600}
    def bad(*a,**k):raise ValueError("Injected optional-model outage")
    monkeypatch.setattr(ensemble,"boosted_forecast",bad)
    monkeypatch.setattr(ensemble,"scan_nison",bad)
    monkeypatch.setattr(ensemble,"pressure_forecast",bad)
    model=ensemble.engine_pack(candles[-1]["close"],m,candles,
                               context={},now=NOW)
    assert model["available"],model
    assert {"axiom_gradient_boosted_btc","axiom_full_nison","axiom_multi_signal_context"}==set(
        model["missing_predictive_models"])
    assert "axiom_volatility" in model["active_predictive_models"]
    a=ensemble.engine_pack(candles[-1]["close"],m,candles,context={},now=NOW)
    b=ensemble.engine_pack(candles[-1]["close"],{**m,"market_mid":.99,
        "yes_ask":.97,"no_ask":.02},candles,context={},now=NOW)
    assert a==b


def test_quote_model_malformed_timestamps_and_closed_outcome_requirements(monkeypatch):
    model=repricing.ContractRepricingModel()
    assert repricing._solve([[0.,0.],[0.,0.]],[0.,0.])==[0.,0.]
    s={"available":True,"price_reference":"COINBASE","momentum_bps_per_min":.4}
    f={"available":True,"prob_above":.7}
    contract={"ticker":"KXBTC15M-TEST","seconds_left":600}
    assert not model.observe(None,None,f,s,NOW)["available"]
    assert not model.observe(contract,None,f,s,NOW)["available"]
    assert not model.observe(contract,None,{},s,NOW)["available"]
    monkeypatch.setattr(repricing,"current_book",lambda *a:True)
    broken={"received_at":NOW,"best":{"YES":{"bid":.9,"ask":.2}}}
    out=model.observe(contract,broken,f,s,NOW)
    assert not out["available"] and out["predicted_yes_mid_30s"] is None
    missing={"received_at":NOW,"best":{"YES":{"bid":None,"ask":.5}}}
    assert not model.observe(contract,missing,f,s,NOW)["available"]
