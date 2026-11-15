"""Period-specific CONDITIONAL historical comparison on authentic KalshiEye samples.

Read-only retrospective replay: train Oct 13, test Oct 25. The result is NOT
verified live model performance. The historical contract target comes from a
day-end market catalog without independently verified as-of publication time.
BTC spot features use exchange MID QUOTE bars, NOT historical exchange trades
or CF BRTI ticks. This is not a full original-third-party-bot reproduction.

User periods:
  first 2 minutes: T+15s,T+30s,T+60s,T+90s,T+120s;
  10 minutes left: expiry-600s;
  5 minutes left: expiry-300s;
  last minute: expiry-60s,-45s,-30s,-15s,-5s.

For multi-timepoint periods, score each contract equally by averaging all
eligible checkpoint losses WITHIN that contract, then across contracts. All
independent models use exactly the same held-out contract/timestamp rows.
The separate Kalshi-price benchmark is re-scored on the overlapping subset.
No real orders or live system writes.
"""
from __future__ import annotations

import collections
import json
import math
import random
import statistics

from app.ensemble import engine_pack
from research import kalshieye_replay as R

PERIODS = {
    "first_two_minutes": [
        ("opening_plus_15s", 885),
        ("opening_plus_30s", 870),
        ("opening_plus_60s", 840),
        ("opening_plus_90s", 810),
        ("opening_plus_120s", 780),
    ],
    "ten_minutes_left": [("ten_min", 600)],
    "five_minutes_left": [("five_min", 300)],
    "final_minute": [
        ("last_60s", 60),
        ("last_45s", 45),
        ("last_30s", 30),
        ("last_15s", 15),
        ("last_5s", 5),
    ],
}
CP = {name: seconds for cps in PERIODS.values() for name,seconds in cps}
# The 6 independently generated candidates are compared on common rows.
COMPARE = (
    "axiom_volatility", "aaryann_fair", "kalshibot_headstart",
    "axiom_ensemble", "independent_logit_candle_features",
    "xgb_spot_only_subset",
)
# M0 is added only when its approximate variance equation is well-defined.
# Its final-minute missing partial-index samples prevent evaluation < 60 sec.
M0 = "schen_m0_minute_proxy"
MARKET = "kalshi_yes_mid_benchmark"


def fit_learned_models(train):
    grouped = collections.defaultdict(list)
    for row in train:
        grouped[row["checkpoint"]].append(row)
    logit = {cp: R.fit_logit(rows) for cp,rows in grouped.items()}
    xgb = {}
    try:
        from xgboost import XGBClassifier
    except ImportError:
        return logit, xgb, "XGBoost dependency missing"
    keys = ("headstart","momentum5","rsi","volatility","log_distance",
            "time_sin","time_cos")
    for cp,rows in grouped.items():
        if len(rows)<35 or len({r["y"] for r in rows})<2:
            continue
        model=XGBClassifier(n_estimators=60,max_depth=2,
                            learning_rate=.055,subsample=1,
                            colsample_bytree=1,random_state=19,
                            eval_metric="logloss",n_jobs=1,
                            objective="binary:logistic")
        model.fit([[r["features"][k] for k in keys] for r in rows],
                  [r["y"] for r in rows])
        xgb[cp]=model
    return logit,xgb,None


def predict(row, logit, xgb):
    market = {
        "target":row["target"],
        "seconds_left":row["remaining"],
        "market_mid":row["quote"]["market_mid"] if row["quote"] else None,
    }
    pack = engine_pack(row["spot"],market,row["candles"])
    predictions = {entry["name"]:entry["prob_above"]
                   for entry in pack["engines"]
                   if entry["available"] and entry["name"]!="kalshi_market"}
    if pack["available"]:
        predictions["axiom_ensemble"]=pack["prob_above"]
    if row["remaining"]>=60:
        predictions[M0]=R.zero_drift(row)
    if logit.get(row["checkpoint"]) is not None:
        theta=logit[row["checkpoint"]]
        predictions["independent_logit_candle_features"]=R.sigmoid(
            sum(a*b for a,b in zip(theta,R.vector(row["features"]))))
    if row["checkpoint"] in xgb:
        keys=("headstart","momentum5","rsi","volatility","log_distance",
              "time_sin","time_cos")
        predictions["xgb_spot_only_subset"]=float(
            xgb[row["checkpoint"]].predict_proba(
                [[row["features"][k] for k in keys]])[0][1])
    if row["quote"] is not None:
        predictions[MARKET]=row["quote"]["market_mid"]
    # Reject any non-finite, out-of-bound output rather than fixing predictions.
    for k,p in list(predictions.items()):
        if p is None or not math.isfinite(p) or p<0 or p>1:
            predictions.pop(k)
    return predictions


def score(rows):
    if not rows:
        return {"n_rows":0,"n_contracts":0}
    # Rows with same contract at different timestamps are strongly correlated.
    by_contract=collections.defaultdict(list)
    for r in rows:
        by_contract[r["ticker"]].append(r)
    avg_brier=statistics.mean(statistics.mean(
        (r["p"]-r["y"])**2 for r in items) for items in by_contract.values())
    avg_acc=statistics.mean(statistics.mean(
        int((r["p"]>=.5)==bool(r["y"])) for r in items)
        for items in by_contract.values())
    avg_log=statistics.mean(statistics.mean(
        -r["y"]*math.log(max(1e-6,r["p"]))
        -(1-r["y"])*math.log(max(1e-6,1-r["p"]))
        for r in items) for items in by_contract.values())
    # Five-bin calibration with equal contract influence. Ordinary
    # observation-weighted ECE would overrepresent contracts with more
    # timestamp snapshots or uninterrupted recorder coverage.
    bin_weight=[0.]*5
    bin_pred=[0.]*5
    bin_truth=[0.]*5
    for items in by_contract.values():
        weight=1/(len(by_contract)*len(items))
        for r in items:
            k=min(4,max(0,int(r["p"]*5)))
            bin_weight[k]+=weight
            bin_pred[k]+=r["p"]*weight
            bin_truth[k]+=r["y"]*weight
    ece=sum(abs(p-y) for p,y in zip(bin_pred,bin_truth))
    calibration=[{"range":[round(k*.2,1),round((k+1)*.2,1)],
                  "mass":round(mass,6),
                  "predicted":round(bin_pred[k]/mass,6),
                  "observed_yes":round(bin_truth[k]/mass,6)}
                 for k,mass in enumerate(bin_weight) if mass>0]
    result={
        "n_rows":len(rows),"n_contracts":len(by_contract),
        "brier":round(avg_brier,6),
        "directional_accuracy":round(avg_acc,6),
        "logloss":round(avg_log,6),
        "ece_5bin_contract_weighted":round(ece,6),
        "calibration_bins":calibration,
        "mean_obs_per_contract":round(len(rows)/len(by_contract),3),
    }
    # Confidence labels are a separate metric, not substitutes for proper scores.
    conf_by=collections.defaultdict(list)
    for r in rows:
        if r["p"] >= .60 or r["p"] <= .40:
            conf_by[r["ticker"]].append(r)
    result["confident_contract_fraction"]=round(len(conf_by)/len(by_contract),5)
    return result


def make_common_predictions(test, logit, xgb):
    obs=[]
    by_cp=collections.Counter()
    for row in test:
        p=predict(row,logit,xgb)
        if not set(COMPARE).issubset(p):
            by_cp[row["checkpoint"]]+=1
            continue
        obs.append({
            "ticker":row["ticker"],
            "checkpoint":row["checkpoint"],
            "remaining":row["remaining"],
            "y":row["y"],
            "predictions":p,
        })
    return obs,dict(by_cp)


def period_rows(observations, period, name):
    period_cps={cp for cp,_ in PERIODS[period]}
    return [
        {"ticker":r["ticker"],"checkpoint":r["checkpoint"],
         "remaining":r["remaining"],"y":r["y"],
         "p":r["predictions"][name]}
        for r in observations
        if r["checkpoint"] in period_cps and name in r["predictions"]
    ]


def paired_brier_by_contract(observations, period, winner, challenger,
                             draws=2000, seed=20261115):
    w=period_rows(observations, period, winner)
    c=period_rows(observations, period, challenger)
    k=lambda x:(x["ticker"],x["checkpoint"])
    w_by={k(x):x for x in w}
    c_by={k(x):x for x in c}
    common=w_by.keys()&c_by.keys()
    groups=collections.defaultdict(list)
    for key in common:
        a,b=w_by[key],c_by[key]
        if a["y"]!=b["y"]:raise AssertionError("Ground-truth mismatch")
        # positive = first model's Brier smaller than second's.
        groups[key[0]].append(
            (b["p"]-b["y"])**2-(a["p"]-a["y"])**2)
    if not groups:
        return {"n_contracts":0,"n_rows":0}
    means=[statistics.mean(vals) for _,vals in sorted(groups.items())]
    n=len(means)
    rng=random.Random(seed)
    trials=sorted(
        sum(means[rng.randrange(n)] for _ in range(n))/n
        for _ in range(draws)
    )
    return {
        "first_model":winner,"second_model":challenger,
        "n_contracts":n,"n_rows":len(common),
        "delta_brier_second_minus_first":round(statistics.mean(means),6),
        "approx_95pct_contract_bootstrap_ci":[round(trials[int(draws*.025)],6),
                                               round(trials[int(draws*.975)],6)],
        "bootstrap_draws":draws,
        "one_holdout_day_only":True,
        "post_selection_not_multiplicity_adjusted":True,
    }


def summarize_windows(observations):
    report={}
    for period,cps in PERIODS.items():
        available=[r for r in observations if r["checkpoint"] in {c for c,_ in cps}]
        # Schen M0 is an eligible independent challenger when its entire
        # evaluation period contains only >=60-second checkpoints. It must
        # NOT be ranked across the last-minute interval: its approximate
        # formula is unavailable at -45,-30,-15 and -5 seconds.
        candidate_models=(COMPARE+(M0,) if period!="final_minute" else COMPARE)
        rows={}
        for name in candidate_models:
            s=period_rows(available,period,name)
            rows[name]=score(s)
        first_name=min(rows,key=lambda x:rows[x]["brier"] if rows[x]["n_rows"] else float("inf"))
        rank=sorted(rows,key=lambda x:rows[x]["brier"] if rows[x]["n_rows"] else float("inf"))
        names_at_each_time={
            cp:{name:score(period_rows(
                [r for r in available if r["checkpoint"]==cp],period,name))
                for name in (COMPARE+(M0,) if CP[cp]>=60 else COMPARE)}
            for cp,_ in cps
        }
        by_market=[r for r in available if MARKET in r["predictions"]]
        market_rows=period_rows(by_market,period,MARKET)
        market_score=score(market_rows)
        market_paired={}
        if market_rows:
            for name in candidate_models:
                market_paired[name]=paired_brier_by_contract(
                    by_market,period,name,MARKET)
        m0_rows=period_rows(available,period,M0)
        comparisons=[
            paired_brier_by_contract(available,period,first_name,runner)
            for runner in rank[1:]
        ]
        report[period]={
            "time_offsets":{name:sec for name,sec in cps},
            "main_comparison_common_rows":len(available),
            "main_comparison_distinct_contracts":len({r["ticker"] for r in available}),
            "ranking_basis":"equal-weight-per-contract Brier on common observations; Schen eligible in first2, 10m and 5m but not all of final 60s",
            "independent_rankings":rank,
            "best_independent_model_by_brier":first_name,
            "model_scores":rows,
            "per_exact_checkpoint":names_at_each_time,
            "winner_vs_each_competitor_paired_bootstrap":comparisons,
            "schen_m0_formula_only_when_remaining_ge_60s":{
                "score":score(m0_rows),
                "eligible_in_final_last_second":False,
                "note":"In final minute Schen is valid only at exactly 60sec, not 45/30/15/5 because recorded accumulated BRTI ticks are missing",
            },
            "market_price_benchmark":{
                "score_on_available_book_quotes":market_score,
                "paired_independent_vs_market_same_contracts":market_paired,
                "not_in_independent_ranking":True,
            },
        }
    return report


def main():
    # Child research only: don't mutate R.py, AXIOM workers, database, or services.
    R.CHECKPOINTS=dict(CP)
    observations,quality,_ = R.make_dataset()
    train=observations[R.DAYS[0]]
    test=observations[R.DAYS[1]]
    logit,xgb,xgb_error=fit_learned_models(train)
    eligible,excluded=make_common_predictions(test,logit,xgb)
    report={
        "evaluation_status":"CONDITIONAL_RETROSPECTIVE_RESEARCH_NOT_VALIDATED_LIVE",
        "question":"best model: first two min / ten min left / five min left / last min",
        "dataset":"KalshiEye/kalshi-order-book-sample",
        "license":"CC BY-NC 4.0 noncommercial research",
        "train_date":R.DAYS[0],"heldout_date":R.DAYS[1],
        "training_contracts":len({r["ticker"] for r in train}),
        "holdout_contracts_with_any_point":len({r["ticker"] for r in test}),
        "training_observations":len(train),
        "holdout_observations":len(test),
        "common_independent_observations":len(eligible),
        "excluded_missing_any_challenger":excluded,
        "trained_logit_at":[cp for cp in CP if logit.get(cp) is not None],
        "trained_spot_only_xgb_at":[cp for cp in CP if cp in xgb],
        "xgb_error":xgb_error,
        "quality_by_day":quality,
        "timing_periods":summarize_windows(eligible),
        "critical_limits":[
            "Historical Kalshi floor_strike from day-end market catalog lacks proof it was published at the model timestamp. This can invalidate claims of strict as-of replay.",
            "Historical spot is recorder Coinbase MID QUOTE, not actual Coinbase trade OHLCV, and not CF BRTI settlement index.",
            "Model source-level parity is incomplete: reduced logistic and XGB are reimplementations, not complete original systems.",
            "Training only 1 day, holdout only 1 day; post-selection winner may reflect chance or regime shift.",
            "First 2 minutes means after opening, not early detection of a move before it starts.",
            "Last-minute near-100pct directional correctness from already-known price proximity would not establish early-warning capability or tradable alpha.",
            "Model winner is selected by Brier; directional accuracy may select a different model. Kalshi benchmark is intentionally excluded from independent ranking.",
            "Bootstrap intervals use whole contracts as clusters, but neighboring contracts are correlated; intervals are descriptive and unadjusted for model selection.",
            "Real data recorder outage hours and incomplete BTC minute data are excluded. Market price benchmark covers a smaller, timestamp-matched eligible set.",
            "No actual orders, guaranteed fills or live profitability validation; changing live AXIOM model remains forbidden.",
        ]
    }
    print("BEGIN_PERIOD_SPECIFIC_EVIDENCE")
    print(json.dumps(report,indent=2,sort_keys=True))
    print("END_PERIOD_SPECIFIC_EVIDENCE")


if __name__=="__main__":
    main()
