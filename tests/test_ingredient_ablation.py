"""Permanent-methodology research tests. No app runtime or live data modifications."""
import copy
import math

import pytest

from research import ingredient_ablation as A
from research import kalshieye_replay as R
from research import window_specific_rerun as W


def row(i=0,seconds=840):
    closes=[90000+2*j+18*math.sin((i+j)/3) for j in range(61)]
    candles=[{"close":price,"high":price+3,"low":price-3,
              "t":1_800_000_000+60*j} for j,price in enumerate(closes)]
    result={"ticker":f"KXBTC15M-INGREDIENT-{i}",
            "checkpoint":"opening_plus_60s",
            "remaining":seconds,"spot":closes[-1]+3,"target":90000+10*i,
            "candles":candles,"quote":None,"ts":1_800_003_610+i*900,
            "y":i%2}
    result["features"]=R.math_features(result)
    return result


@pytest.mark.parametrize("remain",[885,840,600,300,60])
def test_exact_source_equations_parity_for_each_forecast_horizon(remain):
    source=row(1,remain)
    z,mirror,errs=A.original_formula_audit(source)
    assert max(errs.values())<=2e-5
    assert mirror["schen_m0_minute_proxy"]==pytest.approx(R.zero_drift(source))


def test_headstart_and_schen_share_same_settlement_averaging_variance_horizon():
    x=A.extract_components(row(1,600))
    # HeadStart horizon in minutes is exactly (T - 40s) / 60s
    assert x["horizon_head"]==pytest.approx((x["seconds"]-40)/60)
    assert x["sigma_head"]==max(x["stdev"],.00005)
    assert x["linear_distance"]==pytest.approx(
        (x["spot"]-x["target"])/x["spot"])


def test_headstart_and_schen_at_zero_distance_differ_only_by_small_ito_effect():
    raw=row(1,600)
    raw["target"]=raw["spot"]
    z=A.extract_components(raw)
    assert z["z_head"]==0
    assert z["z_schen"]<0
    assert abs(A.cdf(z["z_schen"])-.5)<.005


def test_momentum_ablations_preserve_distance_volatility_and_remaining_time():
    x=row(4,300)
    z=A.extract_components(x)
    p=A.counterfactuals(x,z,.0009)
    assert p["axiom_v1_no_momentum"]==round(
        A.cdf(z["logdistance"]/z["std_axiom"]),4)
    assert p["aaryann_no_momentum"]==round(
        A.cdf(z["logdistance"]/(z["sigma_aaryann"]*math.sqrt(z["remaining"]))),5)
    assert p["headstart_no_target_distance"]==.5
    assert 0<p["headstart_fixed_train_volatility"]<1
    assert 0<p["headstart_no_60s_averaging"]<1


def test_logit_original_full_weights_exactly_refit_in_research_module():
    records=[row(i,300) for i in range(32)]
    custom=A.fit_logit_group(records,"logit_full")
    original=R.fit_logit(records)
    assert custom["theta"]==pytest.approx(original,abs=1e-10)


@pytest.mark.parametrize("excluded",[("headstart","logit_without_headstart"),
                                     ("momentum5","logit_without_momentum"),
                                     ("rsi","logit_without_rsi")])
def test_removed_feature_cannot_alter_refit_predictions(excluded):
    name,group=excluded
    records=[row(i,600) for i in range(36)]
    fit=A.fit_logit_group(records,group)
    assert name not in fit["features"]
    a=row(150,600)
    b=copy.deepcopy(a)
    b["features"][name]+=100000
    assert A.glm_predict(a,fit)==A.glm_predict(b,fit)


def test_heldout_outcome_not_input_to_independent_probability():
    records=[row(i,600) for i in range(34)]
    fit=A.fit_logit_group(records,"logit_full")
    a=row(160,600)
    b=copy.deepcopy(a)
    b["y"]=1-a["y"]
    assert A.glm_predict(a,fit)==A.glm_predict(b,fit)
    z,_,_=A.original_formula_audit(a)
    assert A.counterfactuals(a,z,.001)==A.counterfactuals(b,z,.001)


def test_independent_ablations_not_using_kalshi_market_probability():
    records=[row(i,600) for i in range(32)]
    fit=A.fit_logit_group(records,"logit_full")
    a=row(160,600)
    b=copy.deepcopy(a)
    b["quote"]={"market_mid":.95}
    assert A.glm_predict(a,fit)==A.glm_predict(b,fit)
    assert A.counterfactuals(a,A.extract_components(a),.001)==A.counterfactuals(
        b,A.extract_components(b),.001)


def test_equal_contract_weights_prevent_multiple_snapshots_dominating():
    records=[
        {"ticker":"A","checkpoint":"ten_min","remaining":600,
         "y":1,"predictions":{"candidate":.9,"parent":.6}},
        {"ticker":"B","checkpoint":"ten_min","remaining":600,
         "y":0,"predictions":{"candidate":.7,"parent":.2}},
    ]
    expected=(((.6-1)**2-(.9-1)**2)+(.2**2-.7**2))/2
    got=A.paired_comparison(records,"ten_minutes_left","candidate","parent",
                            draws=100)
    assert got["delta_brier_second_minus_first"]==pytest.approx(expected)


def test_zero_future_samples_not_used_inside_forecast_features():
    a=row(42,300)
    b=copy.deepcopy(a)
    # The result label can change without changing any feature z-score.
    b["y"]^=1
    assert A.extract_components(a)==A.extract_components(b)


def test_glm_group_has_clear_interpretable_feature_identity_and_prior():
    assert A.GLM_GROUPS["logit_full"]==("headstart","momentum5","rsi")
    assert A.GLM_GROUPS["logit_without_headstart"]==("momentum5","rsi")
    assert A.GLM_GROUPS["logit_intercept_only"]==()
    assert "kalshi_yes_mid_benchmark" not in A.MODELS_BASE
    assert "kalshi_market_mid" not in A.FEATURES


def test_schen_counterfactual_only_eligible_before_partial_index_time():
    x=row(42,45)
    z=A.extract_components(x)
    p=A.counterfactuals(x,z,.001)
    assert "schen_no_ito_correction" not in p
    assert "schen_linear_distance" not in p


def test_all_model_ingredients_are_original_or_explicitly_ablated():
    source=row(100,840)
    z,mirror,errs=A.original_formula_audit(source)
    altered=A.counterfactuals(source,z,.001)
    assert set(A.SCORED_ABLATIONS).issubset(altered)
    assert all(0<=p<=1 for p in altered.values())
    assert max(errs.values())<.00003
