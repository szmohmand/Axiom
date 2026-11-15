"""Synthetic regression checks for the real-source conditional research replay.

The tests do not use actual outcomes to build a signal and make no claims
about production model accuracy or trading profits.
"""
import math
from copy import deepcopy

import pytest

from research import kalshieye_replay as R


def fake_spot():
    source={}
    for venue in R.SOURCES:
        times=list(range(100,110))
        p=[80000.0+i for i in range(len(times))]
        source[venue]={t:(t*R.NSEC+500,p[i]) for i,t in enumerate(times)}
    return {"times":{s:sorted(d) for s,d in source.items()},"seconds":source,
            "bars":{s:{} for s in R.SOURCES}}


def test_asof_received_sec_is_earlier_than_prediction_boundary():
    spot=fake_spot()
    p=R.point(spot,"coinbase",108,max_age_s=2)
    assert p is not None and p["asof_sec"]==107 and p["price"]==80007
    # The quote in the boundary's second is deliberately NOT visible.
    spot["seconds"]["coinbase"][108]=(108*R.NSEC+950_000_000,10**9)
    assert R.point(spot,"coinbase",108,max_age_s=2)["price"]==80007


def test_stale_future_and_missing_source_quotes_fail_closed():
    spot=fake_spot()
    assert R.point(spot,"coinbase",112,max_age_s=1) is None
    assert R.point(spot,"coinbase",100,max_age_s=2) is None
    assert R.point(spot,"unknown",110,max_age_s=2) is None if "unknown" in spot["times"] else True


def test_quote_bars_only_completed_and_contiguous():
    spot=fake_spot()
    end=1_800_000_000
    for i in range(61):
        stamp=end-(61-i)*60
        spot["bars"]["coinbase"][stamp]={
            "t":stamp,"close":90000+i,"last_ts_ns":(stamp+29)*R.NSEC
        }
    got=R.candles_at(spot,"coinbase",end,61)
    assert len(got)==61
    assert got[-1]["t"]==end-60
    del spot["bars"]["coinbase"][end-660]
    assert R.candles_at(spot,"coinbase",end,61) is None


def test_no_second_level_kalshi_book_forward_leakage():
    q=lambda t,bid,ask:{"ts":t*R.NSEC,
                        "bid_px_0":bid,"ask_px_0":ask,
                        "bid_sz_0":12,"ask_sz_0":14}
    history=[q(100,.40,.44),q(101,.60,.64)]
    assert R.asof_book(history,101,5)["market_mid"]==pytest.approx(.42)
    assert R.asof_book(history,102,5)["market_mid"]==pytest.approx(.62)
    assert R.asof_book(history,107,5) is None


def test_zero_drift_probability_between_zero_and_one():
    bars=[{"t":i*60,"close":80000+math.sin(i/3)*30+i*.5} for i in range(61)]
    row={"candles":bars,"spot":80037.3,"target":80000.0,
         "remaining":840,"ts":900.}
    p=R.zero_drift(row)
    assert 0<p<1
    assert p==R.zero_drift(deepcopy(row))


def test_logistic_prior_no_market_price_feature_and_training_count_minimum():
    bars=[{"t":i*60,"close":80000+math.sin(i/3)*30+i*.5} for i in range(61)]
    template={"candles":bars,"spot":80037.3,"target":80000.0,
              "remaining":840,"ts":900.}
    x=R.math_features(template)
    assert "market_mid" not in x
    assert R.fit_logit([{"features":x,"y":i%2} for i in range(24)]) is None
    theta=R.fit_logit([{"features":x,"y":i%2} for i in range(26)])
    assert theta is not None
    p=R.sigmoid(sum(a*b for a,b in zip(theta,R.vector(x))))
    assert 0<p<1


def test_brier_on_point_in_time_paired_probabilities():
    assert R.score_predictions([(.2,0),(.8,1)])["brier"]==pytest.approx(.04)
    assert R.score_predictions([(.2,0),(.8,1)])["directional_accuracy"]==1.
    assert R.score_predictions([])=={"n":0}


def test_future_price_movement_not_used_to_calculate_early_signal():
    observations={
        "2026-10-13":{"early_move_inputs":[
            {"trend":1,"dislocation":1,"future_move":-2}]},
        "2026-10-25":{"early_move_inputs":[
            {"trend":1,"dislocation":-3,"future_move":20},
            {"trend":-1,"dislocation":-2,"future_move":-20}]},
    }
    result=R.early_test(observations)
    assert result["train_minute_samples"]==1
    assert result["test_minute_samples"]==2
    assert result["tests"]["spot_trend_prev_60s"]["holdout_oct25_all"]["directional_accuracy"]==1
    assert result["tests"]["coinbase_minus_other_venues"]["holdout_oct25_all"]["directional_accuracy"]==.5


def test_official_expiration_value_is_ground_truth_not_recorded_coin_end():
    # Two independent fields may disagree. The official Kalshi expiration
    # string MUST win over the recorder's approximate coin_price_end.
    close=1800
    secmap={venue:{sec:(sec*R.NSEC+100,80001.0)
                   for sec in range(close-60,close)}
            for venue in R.SOURCES}
    spot={"times":{venue:sorted(events) for venue,events in secmap.items()},
          "seconds":secmap,"bars":{venue:{} for venue in R.SOURCES}}
    markets={"KXBTC15M-SYNTH-1":{"open":900,"close":close,"floor_strike":80000.0}}
    labels={"KXBTC15M-SYNTH-1":{
        "result":"yes","expiration_value":"80001.0",
        "coin_price_end":90000.0,"coin_price_start":79999.0}}
    result=R.audit_benchmark_proxy_basis(spot,markets,labels,[])
    assert result["official_end_index_markets_after_excluding_incidents"]==1
    assert result["by_exchange"]["coinbase"]["markets_with_60_complete_spot_seconds"]==1
    assert result["by_exchange"]["coinbase"]["mean_absolute_usd"]==pytest.approx(0)
    assert result["by_exchange"]["coinbase"]["wrong_contract_winner_if_replaced_with_spot_average"]==0


def test_unavailable_official_expiration_value_never_substitutes_coin_price_end():
    close=1800
    secmap={venue:{sec:(sec*R.NSEC+100,80001.0)
                   for sec in range(close-60,close)}
            for venue in R.SOURCES}
    spot={"times":{venue:sorted(events) for venue,events in secmap.items()},
          "seconds":secmap,"bars":{venue:{} for venue in R.SOURCES}}
    markets={"KXBTC15M-SYNTH-2":{"open":900,"close":close,"floor_strike":80000.0}}
    labels={"KXBTC15M-SYNTH-2":{
        "result":"yes","expiration_value":None,
        "coin_price_end":80001.0,"coin_price_start":79999.0}}
    report=R.audit_benchmark_proxy_basis(spot,markets,labels,[])
    assert report["official_end_index_markets_after_excluding_incidents"]==0
    assert report["unusable"]["no_numerical_official_end_index"]==1
