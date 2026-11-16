"""Research-only test boundaries for large 2026 multi-month BTC cohort.

These validate access/timing rules and mathematical parity. They do not make
claims of actual out-of-sample market skill.
"""
import math
from copy import deepcopy
import pytest
from research import monthly_cohort_replay as M
from research import kalshieye_replay as R

def fake_candles(t, count=100):
    return {
      t+(i-count)*60:(85000+i*3,85005+i*3,84995+i*3,85001+i*3)
      for i in range(count)
    }

def contract(t):
    return {"ticker":"KXBTC15M-TEST","open":t,"close":t+900,
            "strike":85260.0,"y":1,"date":"2026-06-15"}

def test_checkpoint_boundaries_and_data_minute_granularity():
    assert M.POINTS=={
        "opening_plus_60s":60,"opening_plus_120s":120,
        "ten_minutes_left":300,"five_minutes_left":600,
        "last_60s":840}
    assert len(M.PERIODS["first_2min"])==2
    assert M.PERIODS["last_60s_only"]==("last_60s",)

def test_pinned_source_sha_prevents_drifting_public_labels():
    assert M.EXPECTED_WINDOW_SHA256=="9fd4f92f7b85038c825c7468e4e982ca17f7f4c4bb4cba75f1760f51262078d7"

def test_only_completed_genuine_61_minute_trade_candles_are_accepted():
    t=1800000000-(1800000000%60)
    w=contract(t)
    bars=fake_candles(t+60,120)
    row,err=M.qualified_candles(bars,w,"opening_plus_60s","ohlc4")
    assert err is None
    assert len(row["candles"])==61
    assert all(c["t"]<t+60 for c in row["candles"])
    assert row["remaining"]==840
    assert row["target"]==w["strike"]
    assert row["candles"][-1]["t"]==t
    assert row["spot"]>0
    assert not any("kalshi" in k for k in row["features"])
    del bars[t-60]
    r,e=M.qualified_candles(bars,w,"opening_plus_60s","ohlc4")
    assert r is None and e=="missing_opening_reference"

def test_no_gap_imputation_and_no_future_bar():
    t=1800000000-(1800000000%60)
    w=contract(t)
    bars=fake_candles(t+60,120)
    del bars[t-120]
    r,e=M.qualified_candles(bars,w,"opening_plus_60s","preopen_close")
    assert r is None and e=="gapped_or_missing_completed_minute"

def test_anchor_ohcl_vs_last_close_means_spot_proxy_assumptions_are_visible():
    t=1800000000-(1800000000%60)
    w=contract(t)
    bars=fake_candles(t+60,120)
    a,err=M.qualified_candles(bars,w,"opening_plus_60s","ohlc4")
    b,err2=M.qualified_candles(bars,w,"opening_plus_60s","preopen_close")
    assert err==err2==None
    assert a["spot"]!=b["spot"]
    assert a["y"]==b["y"]
    assert a["target"]==b["target"]

def test_btc_settlement_is_label_only_and_never_model_feature():
    t=1800000000-(1800000000%60)
    w=contract(t);bars=fake_candles(t+60,120)
    x,_=M.qualified_candles(bars,w,"opening_plus_60s","ohlc4")
    v=deepcopy(w);v["y"]=0
    z,_=M.qualified_candles(bars,v,"opening_plus_60s","ohlc4")
    assert x["features"]==z["features"]
    assert x["candles"]==z["candles"]

def test_mini_batch_logistic_fit_matches_frozen_source_optimizer():
    records=[]
    for i in range(160):
        f={"headstart":(i-80)/20,
           "momentum5":math.sin(i/7),
           "rsi":math.cos(i/11)}
        records.append({"ticker":str(i),"features":f,"y":i%3==0})
    reference=R.fit_logit(records)
    modeled=M.fit_glm(records,"logit_full")["coefs"]
    assert len(reference)==len(modeled) and max(abs(a-b) for a,b in zip(reference,modeled))<1e-8

def test_ablated_logistic_does_not_use_removed_headstart_term():
    records=[]
    for i in range(120):
        records.append({"ticker":str(i),"features":{
            "headstart":(i-50)/20,"momentum5":math.sin(i),
            "rsi":math.cos(i)},"y":i%3==0})
    fit=M.fit_glm(records,"logit_without_headstart")
    x=[{"features":{"headstart":1e8,"momentum5":0.4,"rsi":0.1}}]
    z=[{"features":{"headstart":-1e8,"momentum5":0.4,"rsi":0.1}}]
    assert M.predict_glm(x,fit)==M.predict_glm(z,fit)

def test_day_bootstrap_same_contract_population_and_direction_of_delta():
    records=[]
    for i in range(15):
        for cp in M.PERIODS["first_2min"]:
            records.append({"ticker":f"contract{i}",
                "date":f"2026-08-{1+i:02}","cp":cp,
                "y":i%2,"p":{"first":.9 if i%2 else .1,
                             "second":.5}})
    r=M.paired_day_uncertainty(records,"first_2min","first","second",draws=100)
    assert r["days"]==15
    assert r["delta_brier_second_minus_first"]==pytest.approx(.24)
    assert r["approx_day_cluster_bootstrap95"]==[.24,.24]

def test_no_fake_calendar_extrapolation_into_unavailable_months():
    assert M.MONTHS[0]=="2026-01"
    assert M.MONTHS[-1]=="2026-10"
    assert len(M.MONTHS)==10

def test_no_market_quote_ever_enters_candidate_feature_vector():
    assert "kalshi_market" not in M.COMPARATORS
    assert "kalshi_yes_mid_benchmark" not in M.COMPARATORS
    for names in M.GLMS.values():
        assert all(x in ("headstart","momentum5","rsi") for x in names)


def test_actual_official_winner_never_replaced_by_proxy_classification():
    t=1800000000-(1800000000%60)
    w=contract(t)
    w["official_expiration_value"]=85265.2
    bars={t-60:(85000,85005,84995,85001),
          t+840:(84920,84923,84915,84918)}
    audit=M.settlement_basis_audit([w],bars,"ohlc4")
    assert audit["official_labeled_windows_compared"]==1
    assert audit["proxy_disagreed_with_official_winner"]==1
    assert audit["official_numeric_expiration_index_available"]==1
    assert audit["official_end_index_vs_proxy_mean_abs_usd"]>0
    # Official result is immutable even when a proxy would declare NO.
    assert w["y"]==1


def test_validation_only_model_selection_cannot_look_at_later_labels():
    # Four prechosen model names, test labels deliberately favor a DIFFERENT
    # option. The chosen model must remain the validation winner.
    def make(split_y,day,idx):
        out=[]
        for cp in M.POINTS:
            if cp=="opening_plus_60s" or cp=="opening_plus_120s":
                a=.9 if split_y else .1
            else:a=.9 if split_y else .1
            # Val picks direct HeadStart; test retrospectively prefers
            # logistic. The selector must not use the latter.
            ps={
               "kalshibot_headstart":a if day.startswith("2026-08") else 1-a,
               "logit_headstart_only":.6 if split_y else .4,
               "logit_full":.5,
               "logit_without_headstart":.55 if split_y else .45,
               "axiom_ensemble":.5,
            }
            out.append({"ticker":f"x{idx}","date":day,"cp":cp,
                        "y":split_y,"abs_headstart_z":0.2,
                        "p":ps})
        return out
    v=make(1,"2026-08-01",1)+make(0,"2026-08-02",2)
    t=make(1,"2026-09-01",3)+make(0,"2026-09-02",4)
    got=M.validation_selection_and_regimes({"validation":v,"test":t})
    for period,selection in got["frozen_four_candidate_validation_choice"].items():
        assert selection["selected_from_validation"]=="kalshibot_headstart"
        assert selection["September_October_score"]["brier"]==pytest.approx(.81)
        assert selection["test_vs_constant_HeadStart"]["delta_brier_second_minus_first"]==0
