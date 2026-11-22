"""Verify that the explicitly requested novel features really influence predictions.

These are acceptance checks for the new integration, not inherited tests that
assumed every research signal must be prevented from changing AXIOM output.
"""
import math

from app.boosted_model import boosted_forecast, _model
from app.market_structure import timeframes, DepthFlowTracker, pressure_forecast
from app.ensemble import engine_pack
from app.orderbook import normalize_orderbook


def btc_candles(now,n=75):
    t=int(now//60)*60-n*60
    out=[]
    for i in range(n):
        p=64000+2*i+.8*math.sin(i*.9)
        out.append({"t":t+i*60,"open":p-1,"close":p,
                    "high":p+2,"low":p-2,"volume":12+i*.01})
    return out


def five_minute(now,n=40):
    t=int(now//300)*300-n*300
    out=[]
    for i in range(n):
        p=64000+7*i
        out.append({"t":t+i*300,"open":p-2,"close":p,
                    "high":p+3,"low":p-3,"volume":45})
    return out


def test_fitted_gradient_boosted_artifact_loads_and_forecasts_on_completed_real_format():
    assert len(_model()["trees"])==12
    now=1800007200
    candles=btc_candles(now)
    m={"ticker":"KXBTC15M-EXPERIMENT","target":64120,
       "seconds_left":600,"market_mid":.5}
    f=boosted_forecast(64148,m,candles,now)
    assert f["available"],f
    assert f["trained"] is True
    assert 0<f["prob_above"]<1
    assert f["base_normal_probability"]!=f["prob_above"]


def test_genuine_two_hour_completed_5m_context():
    now=1800007200
    f=timeframes(five_minute(now),now)
    assert f["available"]
    assert {"30m","1h","2h"}==set(f["frames"])
    assert f["frames"]["2h"]["fully_closed_source_bars"]==24
    assert f["directional_components"]["2h_efficiency"]>0


def test_binance_cvd_large_print_without_kalshi_depth_still_influences():
    now=1800007200
    binance={"status":"STREAMING",
             "cvd_2m":{"taker_imbalance":.7,"trades_seen":100},
             "cvd_5m":{"taker_imbalance":.4,"trades_seen":200},
             "large_trade_activity":{"net_taker_usdt":120000.,
                 "large_trade_threshold_usdt":150000.,"large_print_count":4}}
    tracker=DepthFlowTracker()
    result=tracker.observe(None,{"ticker":"KXBTC15M-TEST"},binance,64000,now)
    signals=result["directional_components"]
    assert result["available"],result
    assert "btc_taker_cvd_2m" in signals
    assert "btc_large_aggressive_prints" in signals
    assert "btc_perpetual_funding_pressure" not in signals
    assert "btc_perpetual_basis_pressure" not in signals


def test_funding_cannot_change_market_structure_features_or_forecast():
    now=1800007200
    tracker=DepthFlowTracker()
    ticker={"ticker":"KXBTC15M-TEST"}
    base={"status":"STREAMING","cvd_2m":{"taker_imbalance":.60,"trades_seen":100},
          "large_trade_activity":{"net_taker_usdt":3000.,
              "large_trade_threshold_usdt":1000.,"large_print_count":3}}
    original=tracker.observe(None,ticker,base,64000,now)
    fake={**base,"funding_rate":.05,"funding_status":"LIVE",
          "funding_percent":5.0,"funding_mark_index_basis_bps":99999}
    injected=tracker.observe(None,ticker,fake,64000,now)
    assert original==injected
    forecast={"timeframes":{"directional_components":{"30m_efficiency":.5}},
              "microstructure":original}
    other={"timeframes":{"directional_components":{"30m_efficiency":.5}},
           "microstructure":injected}
    m={"ticker":ticker["ticker"],"target":64000,"seconds_left":600}
    assert pressure_forecast(64000,m,.52,forecast)==pressure_forecast(64000,m,.52,other)


def test_kalshi_book_imbalance_and_replenishment_never_enter_btc_prediction():
    now=1800007200
    market={"ticker":"KXBTC15M-TEST"}
    tracker=DepthFlowTracker()
    a=normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[["0.40","50"],["0.39","40"]],
        "no_dollars":[["0.50","10"],["0.49","12"]]}},market["ticker"],now)
    b=normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[["0.90","2000"],["0.89","400"]],
        "no_dollars":[["0.09","1"],["0.08","2"]]}},market["ticker"],now+15)
    btc={"status":"STREAMING","cvd_2m":{"taker_imbalance":.55,"trades_seen":100}}
    first=tracker.observe(a,market,btc,64000,now)
    second=tracker.observe(b,market,btc,64003,now+15)
    assert first==second
    assert "btc_taker_cvd_2m" in first["directional_components"]
    assert not any("kalshi" in key or "quote" in key or "book" in key
                   for key in first["directional_components"])


def test_multi_signal_pressure_directly_changes_probability():
    now=1800007200
    market={"ticker":"KXBTC15M-TEST","seconds_left":600,"target":64000}
    bullish={"timeframes":{"directional_components":{"30m_efficiency":.9}},
             "microstructure":{"directional_components":{"btc_taker_cvd_2m":.8,
                                              "btc_taker_cvd_5m":.7}}}
    bearish={"timeframes":{"directional_components":{"30m_efficiency":-.9}},
             "microstructure":{"directional_components":{"btc_taker_cvd_2m":-.8,
                                              "btc_taker_cvd_5m":-.7}}}
    up=pressure_forecast(64000,market,.50,bullish)
    down=pressure_forecast(64000,market,.50,bearish)
    assert up["prob_above"]>.5>down["prob_above"]
    assert up["combined_z_shift"]>0>down["combined_z_shift"]


def test_every_new_model_voting_and_microstructure_changes_ensemble_probability():
    now=1800007200
    candles=btc_candles(now)
    spot=candles[-1]["close"]
    market={"ticker":"KXBTC15M-TEST","seconds_left":600,"close_ts":now+600,
            "target":spot+9,"market_mid":.50}
    bull={"timeframes":{"available":True,
           "directional_components":{"30m_efficiency":.95,
                                      "1h_efficiency":.80,
                                      "2h_efficiency":.75}},
          "microstructure":{"available":True,
            "directional_components":{"btc_taker_cvd_2m":.80,
                                     "btc_large_aggressive_prints":.8}}}
    bear={"timeframes":{"available":True,
           "directional_components":{"30m_efficiency":-.95,
                                      "1h_efficiency":-.80,
                                      "2h_efficiency":-.75}},
          "microstructure":{"available":True,
            "directional_components":{"btc_taker_cvd_2m":-.80,
                                     "btc_large_aggressive_prints":-.8}}}
    a=engine_pack(spot,market,candles,context=bull,now=now)
    b=engine_pack(spot,market,candles,context=bear,now=now)
    assert a["all_signal_integration_active"]
    names=set(a["active_predictive_models"])
    assert {"axiom_gradient_boosted_btc","axiom_full_nison",
            "axiom_multi_signal_context"}<=names
    assert a["prob_above"]>b["prob_above"],(a["prob_above"],b["prob_above"])
    assert "kalshi_market" not in a["active_predictive_models"]
