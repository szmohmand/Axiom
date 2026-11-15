"""Validation of exact requested AXIOM time-window evaluation semantics."""
import math

import pytest

from research import window_specific_rerun as W


def test_exact_user_requested_windows():
    assert W.PERIODS["first_two_minutes"]==[
        ("opening_plus_15s",885),("opening_plus_30s",870),
        ("opening_plus_60s",840),("opening_plus_90s",810),
        ("opening_plus_120s",780)]
    assert W.PERIODS["ten_minutes_left"]==[("ten_min",600)]
    assert W.PERIODS["five_minutes_left"]==[("five_min",300)]
    assert W.PERIODS["final_minute"]==[
        ("last_60s",60),("last_45s",45),("last_30s",30),
        ("last_15s",15),("last_5s",5)]
    assert len(W.CP)==12


def test_model_score_equal_weights_per_contract_not_timestamp():
    rows=[dict(ticker="a",p=.0,y=1),
          dict(ticker="a",p=.0,y=1),
          dict(ticker="a",p=.0,y=1),
          dict(ticker="b",p=1.0,y=1)]
    result=W.score(rows)
    # A's three identical observations count as one contract, not three.
    assert result["brier"]==.5
    assert result["directional_accuracy"]==.5
    assert result["n_rows"]==4
    assert result["n_contracts"]==2


def test_window_filter_scores_only_requested_period_and_known_outputs():
    observations=[
        {"ticker":"a","checkpoint":"opening_plus_15s","remaining":885,"y":1,
         "predictions":{"axiom_volatility":.8,"kalshi_yes_mid_benchmark":.7}},
        {"ticker":"a","checkpoint":"ten_min","remaining":600,"y":1,
         "predictions":{"axiom_volatility":.2}},
        {"ticker":"b","checkpoint":"last_5s","remaining":5,"y":0,
         "predictions":{"axiom_volatility":.1}}
    ]
    first=W.period_rows(observations,"first_two_minutes","axiom_volatility")
    assert len(first)==1
    assert first[0]["p"]==.8
    assert len(W.period_rows(observations,"final_minute","axiom_volatility"))==1
    assert not W.period_rows(observations,"five_minutes_left","axiom_volatility")
    assert W.period_rows(observations,"first_two_minutes","kalshi_yes_mid_benchmark")[0]["p"]==.7


def test_same_ticker_timestamp_paired_brier_direction_and_sign():
    rows=[
        {"ticker":"a","checkpoint":"ten_min","remaining":600,"y":1,
         "predictions":{"axiom_ensemble":.9,
                        "independent_logit_candle_features":.4}},
        {"ticker":"b","checkpoint":"ten_min","remaining":600,"y":0,
         "predictions":{"axiom_ensemble":.1,
                        "independent_logit_candle_features":.6}}
    ]
    res=W.paired_brier_by_contract(rows,"ten_minutes_left",
                                   "axiom_ensemble",
                                   "independent_logit_candle_features",draws=100)
    assert res["n_contracts"]==2
    assert res["n_rows"]==2
    assert res["delta_brier_second_minus_first"]==.35
    assert res["approx_95pct_contract_bootstrap_ci"]==[.35,.35]


def test_missing_market_mid_never_silently_enters_independent_comparison():
    assert "kalshi_yes_mid_benchmark" not in W.COMPARE


def test_near_expiration_zero_drift_must_be_excluded():
    # R.zero_drift uses a sqrt(remaining-40) equation and is not valid
    # for remainder below 60 with no actual partial BRTI settlement samples.
    assert W.CP["last_45s"]<60
    assert W.CP["last_30s"]<60
    assert W.CP["last_15s"]<60
    assert W.CP["last_5s"]<60
    assert W.M0 not in W.COMPARE


def test_no_lookahead_ground_truth_disagreement_allowed():
    rows=[
        {"ticker":"a","checkpoint":"ten_min","remaining":600,"y":1,
         "predictions":{"axiom_ensemble":.8}},
        {"ticker":"a","checkpoint":"ten_min","remaining":600,"y":0,
         "predictions":{"independent_logit_candle_features":.3}},
    ]
    with pytest.raises(AssertionError,match="Ground-truth mismatch"):
        W.paired_brier_by_contract(rows,"ten_minutes_left",
                                   "axiom_ensemble",
                                   "independent_logit_candle_features")


def test_confident_call_fraction_is_contract_weighted():
    rows=[
        {"ticker":"a","p":.8,"y":1},
        {"ticker":"a","p":.8,"y":1},
        {"ticker":"b","p":.55,"y":1},
    ]
    assert W.score(rows)["confident_contract_fraction"]==.5
