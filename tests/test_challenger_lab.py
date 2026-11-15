"""Permanent regression gates for isolated challenger research.

Synthetic fixtures verify methodology only; they provide NO market accuracy evidence.
"""
import math
import sys
import subprocess
from copy import deepcopy

import pytest

from research import challenger_lab as lab


def one(ticker_id=0, remaining=840, market_mid=.52):
    opening=1_800_000_000 + 900*ticker_id
    expiry=opening+900
    ts=expiry-remaining
    base=90000 + 5*ticker_id
    candles=[]
    for i in range(61):
        stamp=(int(ts)//60)*60-(61-i)*60
        close=base + 100*math.sin((i+ticker_id)/8) + i*.75
        candles.append({"t":stamp,"close":close,"high":close+10,
                        "low":close-10,"volume":5+i*.01})
    return {"ticker":f"KXBTC15M-SYNTH-{ticker_id:04d}", "ts":ts,
            "spot_ts":ts, "open_ts":opening,"expires_ts":expiry,
            "target_ts":opening,"spot":candles[-1]["close"]+3,
            "target":base,"candles":candles,
            "market_mid":market_mid,"market_mid_ts":ts}


def outcome(raw, yes=None):
    return {"ticker":raw["ticker"],"result":"yes" if yes is None or yes else "no",
            "source":"synthetic_fixture","expires_ts":raw["expires_ts"],
            "settled_at":raw["expires_ts"]+10}


def test_no_model_imports_runtime_or_auth_side_effects():
    # Other independent tests may have already imported app.main in this pytest
    # process. The isolation guarantee must be tested in a clean interpreter.
    child=subprocess.run([sys.executable,"-c",
                          "import sys; from research import challenger_lab; assert 'app.main' not in sys.modules"],
                         capture_output=True,text=True,check=False)
    assert child.returncode==0, child.stderr
    assert "market_mid" not in lab.FEATURES
    assert all("kalshi" not in name for name in lab.FEATURES)
    assert all(name in lab.FEATURES for name in ("headstart","momentum5","rsi"))


def test_causal_input_guards_reject_future_missing_and_stale_evidence():
    good=one()
    assert lab.normalize_observation(good)["checkpoint"]=="14m"
    mutations=[]
    a=deepcopy(good);a["spot_ts"]=a["ts"]+1;mutations.append(a)
    a=deepcopy(good);a["spot_ts"]=a["ts"]-31;mutations.append(a)
    a=deepcopy(good);a["target_ts"]=a["ts"]+1;mutations.append(a)
    a=deepcopy(good);a["market_mid_ts"]=a["ts"]+1;mutations.append(a)
    a=deepcopy(good);a["market_mid_ts"]=a["ts"]-31;mutations.append(a)
    a=deepcopy(good);a["candles"][-1]["t"]+=60;mutations.append(a)
    a=deepcopy(good);a["candles"][-1]["t"]-=60;mutations.append(a)
    a=deepcopy(good);a["candles"][-1]["t"]-=120;mutations.append(a)
    a=deepcopy(good);a["result"]="yes";mutations.append(a)
    for bad in mutations:
        with pytest.raises(lab.ReplayError):
            lab.normalize_observation(bad)


def test_independent_inputs_and_models_ignore_kalshi_market_price():
    a=lab.normalize_observation(one(market_mid=.05))
    b=lab.normalize_observation(one(market_mid=.95))
    assert lab.inputs(a)==lab.inputs(b)
    assert lab.zero_drift(a)==lab.zero_drift(b)
    assert lab.logistic_predict([0.,1.7,.1,.2],a)==lab.logistic_predict([0.,1.7,.1,.2],b)
    m_a={"target":a["target"],"seconds_left":a["seconds_left"],"market_mid":a["market_mid"]}
    m_b={"target":b["target"],"seconds_left":b["seconds_left"],"market_mid":b["market_mid"]}
    from app.ensemble import engine_pack
    packs=[engine_pack(r["spot"],m,r["candles"]) for r,m in ((a,m_a),(b,m_b))]
    assert packs[0]["prob_above"]==packs[1]["prob_above"]
    assert packs[0]["engines"][0]["prob_above"]!=packs[1]["engines"][0]["prob_above"]


def test_settlement_averaging_matches_schen_m0_equation_with_explicit_minute_proxy():
    for remain in (900,840,300,60):
        row=lab.normalize_observation(one(remaining=remain))
        sigma=lab.inputs(row)["volatility"]/math.sqrt(60)
        z=(math.log(row["spot"]/row["target"])-.5*sigma*sigma*(remain-30))/(sigma*math.sqrt(remain-40))
        expected=min(1-lab.EPS,max(lab.EPS,lab.normal_cdf(z)))
        assert lab.zero_drift(row)==pytest.approx(expected,abs=1e-12)
    row=lab.normalize_observation(one(remaining=45))
    assert lab.zero_drift(row) is None  # no future-average samples fabricated


def test_future_settlements_never_train_or_grade():
    row=lab.normalize_observation(one())
    label=lab.normalize_settlement(outcome(one()),allow_synthetic=True)
    assert lab.fit_independent_logistic([row]*30,{row["ticker"]:label},row["ts"]) is None
    with pytest.raises(lab.ReplayError):
        lab.normalize_settlement(outcome(one()),allow_synthetic=False)
    early=outcome(one());early["settled_at"]=early["expires_ts"]-1
    with pytest.raises(lab.ReplayError):
        lab.normalize_settlement(early,allow_synthetic=True)


def test_synthetic_full_holdout_folds_paired_scoring_and_report_disclaimer():
    raw=[one(i,remaining=840,market_mid=.51) for i in range(80)]
    raw+=[one(i,remaining=300,market_mid=.45) for i in range(80)]
    rows=[lab.normalize_observation(r) for r in raw]
    labels={r["ticker"]:lab.normalize_settlement(outcome(r,yes=int(r["ticker"][-4:])%2==0),
                                              allow_synthetic=True)
            for r in raw}
    report=lab.evaluate(rows,labels,min_train_contracts=40,folds=4,use_xgboost=False)
    assert report["out_of_sample_contracts"]==40
    assert report["folds"]==4
    assert report["status"]=="RESEARCH_ONLY_UNVALIDATED"
    assert all(x["validated_alpha"] is False for x in report["paired_brier"])
    assert any(x["model"]=="kalshi_market_mid" and x["category"]=="market_price_benchmark"
               for x in report["scores"])
    assert any(x["model"]=="kalshibot_independent_logistic" for x in report["scores"])
    assert any(x["model"]=="settlement_zero_drift" for x in report["scores"])
    assert all(x["matched_contracts"] <= 40 for x in report["paired_brier"])
    assert all(0 <= x["brier"] <= 1 for x in report["scores"])
    assert report["unavailable_models"]["siddha_spot_xgboost"].startswith("Optional")


def test_insufficient_contracts_never_pretend_to_report_skill():
    row=lab.normalize_observation(one())
    label=lab.normalize_settlement(outcome(one()),allow_synthetic=True)
    r=lab.evaluate([row],{row["ticker"]:label},min_train_contracts=30)
    assert r["status"]=="INSUFFICIENT_REAL_HISTORY"
    assert r["scores"]==[]


def test_duplicate_contract_checkpoint_and_mismatched_expiration_fail(tmp_path):
    one_row=one()
    obs=tmp_path/"observations.jsonl"
    lab_path=tmp_path/"settlements.jsonl"
    import json
    obs.write_text(json.dumps(one_row)+"\n"+json.dumps(one_row)+"\n")
    lab_path.write_text(json.dumps(outcome(one_row))+"\n")
    with pytest.raises(lab.ReplayError,match="Duplicate"):
        lab.load_data(obs,lab_path,allow_synthetic=True)
    obs.write_text(json.dumps(one_row)+"\n")
    x=outcome(one_row);x["expires_ts"]+=900
    lab_path.write_text(json.dumps(x)+"\n")
    with pytest.raises(lab.ReplayError,match="expiration"):
        lab.load_data(obs,lab_path,allow_synthetic=True)
