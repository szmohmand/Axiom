"""AXIOM ingredient-level research: isolated ablation, formula parity & mechanism audit.

Strict limitations: source is two noncontiguous dates, historic Kalshi
strike as-of publication NOT proved, exchange MID-QUOTE bars are NOT BRTI,
the models are reduced versions. All scores descriptive and exploratory.
Nothing from this module is imported by the live AXIOM runtime.
"""
from __future__ import annotations

import collections
import json
import math
import random
import statistics

from app.ensemble import engine_pack
from research import kalshieye_replay as R
from research import window_specific_rerun as W

FEATURES=("headstart","momentum5","rsi")
GLM_GROUPS={
    "logit_full": FEATURES,
    "logit_without_headstart":("momentum5","rsi"),
    "logit_without_momentum":("headstart","rsi"),
    "logit_without_rsi":("headstart","momentum5"),
    "logit_headstart_only":("headstart",),
    "logit_momentum_only":("momentum5",),
    "logit_rsi_only":("rsi",),
    "logit_intercept_only":(),
}
PERIODS=W.PERIODS
CP=W.CP
OUTCOME_TIME_HOLDS=R.DAYS
MODELS_BASE=("axiom_ensemble","axiom_volatility","aaryann_fair",
             "kalshibot_headstart","schen_m0_minute_proxy")
SCORED_ABLATIONS=(
    "axiom_v1_no_momentum", "aaryann_no_momentum",
    "aaryann_no_target_distance", "headstart_no_60s_averaging",
    "headstart_fixed_train_volatility","headstart_no_target_distance",
    "schen_no_ito_correction", "schen_linear_distance",
    "schen_clamped_like_headstart","headstart_unclamped_like_schen",
)
HYBRIDS=("half_headstart_half_logit","half_ensemble_half_logit",
         "half_headstart_half_ensemble","half_schen_half_logit")
RANDOM_SEED=20261115


def clamp(p):
    return min(.995,max(.005,p))


def cdf(z):
    return clamp(.5*(1+math.erf(z/math.sqrt(2))))


def schen_cdf(z):
    # Existing Schen research formula clamps at 1e-6, not .005.
    # Never silently equate different clipping policies in parity checks.
    raw=.5*(1+math.erf(z/math.sqrt(2)))
    return min(1-1e-6,max(1e-6,raw))


def extract_components(row):
    """Reconstruct original source equations from the SAME candle/spot snapshot."""
    closes=[float(c["close"]) for c in row["candles"][-61:]]
    spot,target=float(row["spot"]),float(row["target"])
    seconds=float(row["remaining"])
    remaining=seconds/60
    returns=[math.log(b/a) for a,b in zip(closes,closes[1:])]
    stdev=statistics.stdev(returns)
    sigma_axiom=statistics.stdev(returns[-45:])
    sigma_aaryann=max(statistics.pstdev(returns),1e-6)
    sigma_head=max(stdev,.00005)
    logdistance=math.log(spot/target)
    linear_distance=(spot-target)/spot
    momentum_5=math.log(spot/closes[-6])
    drift_aaryann=.5*momentum_5*min(remaining,5)/5
    drift_axiom=statistics.mean(returns[-5:])*.2
    std_axiom=sigma_axiom*math.sqrt(max(remaining,.01))
    projected_drift=max(-std_axiom*.35,
                        min(std_axiom*.35,drift_axiom*remaining))
    horizon_head=max(remaining-1,0)+1/3
    z_head=linear_distance/(sigma_head*math.sqrt(horizon_head))
    z_schen=(logdistance-.5*(max(stdev,1e-6)**2/60)*(seconds-30))/(
        max(stdev,1e-6)*math.sqrt((seconds-40)/60)) if seconds>=60 else None
    return {
        "closes":closes,"returns":returns,"spot":spot,"target":target,
        "seconds":seconds,"remaining":remaining,"logdistance":logdistance,
        "linear_distance":linear_distance,"stdev":stdev,
        "sigma_axiom":sigma_axiom,"sigma_aaryann":sigma_aaryann,
        "sigma_head":sigma_head,"momentum_5":momentum_5,
        "drift_aaryann":drift_aaryann,"drift_axiom":drift_axiom,
        "projected_drift":projected_drift,"std_axiom":std_axiom,
        "horizon_head":horizon_head,"z_head":z_head,"z_schen":z_schen,
        "z_aaryann":(logdistance+drift_aaryann)/
                    (sigma_aaryann*math.sqrt(remaining)),
        "z_axiom":(logdistance+projected_drift)/std_axiom,
    }


def original_formula_audit(row):
    z=extract_components(row)
    market={"target":row["target"],"seconds_left":row["remaining"],
            "market_mid":row["quote"]["market_mid"] if row["quote"] else None}
    pack=engine_pack(row["spot"],market,row["candles"])
    source={v["name"]:v.get("prob_above") for v in pack["engines"]}
    mirror={
        "axiom_volatility":round(cdf(z["z_axiom"]),4),
        "aaryann_fair":round(cdf(z["z_aaryann"]),5),
        "kalshibot_headstart":round(cdf(z["z_head"]),5),
    }
    if row["remaining"]>=60:
        mirror["schen_m0_minute_proxy"]=R.zero_drift(row)
    if pack["available"]:
        mirror["axiom_ensemble"]=pack["prob_above"]
    errors={k:abs(source.get(k,mirror[k])-mirror[k]) for k in
            ("axiom_volatility","aaryann_fair","kalshibot_headstart")}
    if max(errors.values())>2e-5:
        raise AssertionError(f"Formula parity mismatch: {errors}")
    if "schen_m0_minute_proxy" in mirror:
        if abs(schen_cdf(z["z_schen"])-mirror["schen_m0_minute_proxy"])>5e-8:
            raise AssertionError("Schen formula not reproduced")
    return z,mirror,errors


def counterfactuals(row,z,train_sigma):
    """No outcome, future return or Kalshi-price input is accessed here."""
    t=z["remaining"]
    out={}
    # Removal of original capped 5min drift: isolates momentum contribution
    out["axiom_v1_no_momentum"]=round(
        cdf(z["logdistance"]/z["std_axiom"]),4)
    out["aaryann_no_momentum"]=round(
        cdf(z["logdistance"]/(z["sigma_aaryann"]*math.sqrt(t))),5)
    # Null controls test the dependence on the contract target/distance
    out["aaryann_no_target_distance"]=round(
        cdf(z["drift_aaryann"]/(z["sigma_aaryann"]*math.sqrt(t))),5)
    out["headstart_no_target_distance"]=.5
    # Counterfactual remove the 60-second settlement-average time correction
    out["headstart_no_60s_averaging"]=round(
        cdf(z["linear_distance"]/(z["sigma_head"]*math.sqrt(t))),5)
    # Counterfactual replace live estimated volatility with train-day median
    out["headstart_fixed_train_volatility"]=round(
        cdf(z["linear_distance"]/(max(train_sigma,.00005)*math.sqrt(
            z["horizon_head"]))),5)
    if z["seconds"]>=60:
        sig=max(z["stdev"],1e-6)
        se=sig*math.sqrt((z["seconds"]-40)/60)
        out["schen_no_ito_correction"]=schen_cdf(z["logdistance"]/se)
        out["schen_linear_distance"]=schen_cdf(z["linear_distance"]/se)
        out["schen_clamped_like_headstart"]=cdf(z["z_schen"])
        out["headstart_unclamped_like_schen"]=schen_cdf(z["z_head"])
    return out


def fit_logit_group(rows,group,min_train=25):
    if len(rows)<min_train or len({r["y"] for r in rows})<2:
        return None
    feat=GLM_GROUPS[group]
    prior=[0.]+[1.7 if k=="headstart" else 0. for k in feat]
    w=prior[:]
    d=len(w)
    x=[[1.]+[r["features"][key] for key in feat] for r in rows]
    y=[r["y"] for r in rows]
    for _ in range(400):
        grad=[0.]*d
        for values,label in zip(x,y):
            residual=R.sigmoid(sum(a*b for a,b in zip(w,values)))-label
            for j in range(d):
                grad[j]+=residual*values[j]
        for j in range(d):
            w[j]-=.12*(grad[j]/len(x)+.08*(w[j]-prior[j]))
    return {"features":list(feat),"theta":w,
            "train_contracts":len({r["ticker"] for r in rows})}


def glm_predict(row,fit):
    if fit is None:return None
    x=[1.]+[row["features"][key] for key in fit["features"]]
    return R.sigmoid(sum(a*b for a,b in zip(fit["theta"],x)))


def prepare_train(train):
    bycp=collections.defaultdict(list)
    for row in train:bycp[row["checkpoint"]].append(row)
    fitted={}
    source_full={}
    for cp, rows in bycp.items():
        for group in GLM_GROUPS:
            fitted[(cp,group)]=fit_logit_group(rows,group)
        source_full[cp]=R.fit_logit(rows)
        custom=fitted[(cp,"logit_full")]
        if custom is not None and source_full[cp] is not None:
            if any(abs(a-b)>1e-8 for a,b in zip(custom["theta"],source_full[cp])):
                raise AssertionError(f"Original logistic refit failed parity at {cp}")
    # Training-only vol constant; final holdout never enters the estimated sigma.
    sigma_by_cp={}
    for cp,rows in bycp.items():
        sigma_by_cp[cp]=statistics.median(
            extract_components(r)["stdev"] for r in rows)
    return fitted,sigma_by_cp


def evaluate_rows(rows,fits,sigmas):
    result=[]
    parity=collections.defaultdict(list)
    mechanics=collections.defaultdict(list)
    for row in rows:
        cp=row["checkpoint"]
        z,mirror,errs=original_formula_audit(row)
        predictions=dict(mirror)
        variants=counterfactuals(row,z,sigmas[cp])
        predictions.update(variants)
        predictions.update({
            key:glm_predict(row,fits[(cp,key)])
            for key in GLM_GROUPS if fits.get((cp,key)) is not None
        })
        # Fixed full-model prior, no observed labels are used.
        predictions["headstart_prior_only"]=R.sigmoid(1.7*row["features"]["headstart"])
        if "logit_full" in predictions:
            p=predictions["logit_full"]
            predictions["half_headstart_half_logit"]=(
                predictions["kalshibot_headstart"]+p)/2
            predictions["half_ensemble_half_logit"]=(
                predictions["axiom_ensemble"]+p)/2
            if "schen_m0_minute_proxy" in predictions:
                predictions["half_schen_half_logit"]=(
                    predictions["schen_m0_minute_proxy"]+p)/2
        predictions["half_headstart_half_ensemble"]=(
            predictions["kalshibot_headstart"]+
            predictions["axiom_ensemble"])/2
        if not all(math.isfinite(p) and 0<=p<=1 for p in predictions.values()):
            raise AssertionError("Nonfinite candidate, no clipping permitted")
        parity[cp].append(max(errs.values()))
        if row["remaining"]>=60:
            mechanics[cp].append({
                "schen_minus_headstart_prob":predictions[
                    "schen_m0_minute_proxy"]-predictions["kalshibot_headstart"],
                "headstart_sigma_floor_active":z["stdev"]<.00005,
                "relative_momentum":abs(z["drift_aaryann"])/
                       max(1e-9,abs(z["logdistance"])),
                "trend_aligned":z["logdistance"]*z["momentum_5"]>0,
            })
        result.append({
            "ticker":row["ticker"],"checkpoint":cp,
            "remaining":row["remaining"],"y":row["y"],
            "predictions":predictions,
            "regime":{
                "abs_headstart_z":abs(row["features"]["headstart"]),
                "volatility":z["stdev"],
                "momentum_aligns_target_distance":z["logdistance"]*z["momentum_5"]>0,
            }
        })
    return result,parity,mechanics


def prepare_holdout_rows(train,test):
    # Full set of reduced candidate models must be fit on Oct13 only.
    fits,sigmas=prepare_train(train)
    data,parity,mechanics=evaluate_rows(test,fits,sigmas)
    return data,fits,sigmas,parity,mechanics


def periods(data):
    summary={}
    for period,cps in PERIODS.items():
        wanted={c for c,_ in cps}
        samples=[r for r in data if r["checkpoint"] in wanted]
        models=sorted(set.intersection(*(
            set(r["predictions"]) for r in samples
        ))) if samples else []
        # Schen and derivatives exist at >=60s but not entire last minute.
        model_scores={}
        for model in models:
            exact=[{"ticker":r["ticker"],"checkpoint":r["checkpoint"],
                    "p":r["predictions"][model],"y":r["y"]}
                   for r in samples]
            model_scores[model]=W.score(exact)
        # Explicitly label ineligible and avoid their partial-period score.
        available_only=sorted(set().union(*(set(r["predictions"]) for r in samples))-set(models))
        summary[period]={
            "eligible_contracts":len({r["ticker"] for r in samples}),
            "eligible_observations":len(samples),
            "scores":model_scores,
            "models_with_incomplete_period_coverage":available_only,
        }
    return summary


def paired_comparison(data,period,first,second,draws=1000,seed=RANDOM_SEED):
    # Precomputed labels remain separate from all prediction functions.
    cps={c for c,_ in PERIODS[period]}
    vals=collections.defaultdict(list)
    for row in data:
        p=row["predictions"]
        if row["checkpoint"] not in cps or first not in p or second not in p:
            continue
        y=row["y"]
        vals[row["ticker"]].append((p[second]-y)**2-(p[first]-y)**2)
    if not vals:return {"n_contracts":0}
    per_contract=[statistics.mean(v) for _,v in sorted(vals.items())]
    n=len(per_contract)
    mean=statistics.mean(per_contract)
    rng=random.Random(seed)
    boot=sorted(sum(per_contract[rng.randrange(n)] for _ in range(n))/n
                for _ in range(draws))
    # Approximate two-sided sign-flip null, then family-wise Holm correction
    # across ALL reported ablation comparisons. Assumes exchangeable
    # contract-level paired errors; neighboring contracts violate perfect
    # independence, so this is a conservative research diagnostic, not
    # confirmatory market evidence.
    threshold=abs(mean)
    exceed=0
    for _ in range(draws):
        null_mean=sum(value*(1 if rng.randrange(2) else -1)
                      for value in per_contract)/n
        exceed+=abs(null_mean)>=threshold-1e-14
    pvalue=(1+exceed)/(draws+1)
    return {"n_contracts":n,"delta_brier_second_minus_first":round(mean,8),
            "approx_two_sided_signflip_p":round(pvalue,6),
            "approx_95pct_contract_bootstrap_ci":[
                round(boot[int(draws*.025)],8),
                round(boot[int(draws*.975)],8)],
            "draws":draws,"descriptive_only":True}


def ablation_matrix(data):
    # Compare each removed/swapped factor only to ITS original parent on
    # identical selected rows. No artificial change of another input.
    parent={
        "axiom_v1_no_momentum":"axiom_volatility",
        "aaryann_no_momentum":"aaryann_fair",
        "aaryann_no_target_distance":"aaryann_fair",
        "headstart_no_target_distance":"kalshibot_headstart",
        "headstart_no_60s_averaging":"kalshibot_headstart",
        "headstart_fixed_train_volatility":"kalshibot_headstart",
        "schen_no_ito_correction":"schen_m0_minute_proxy",
        "schen_linear_distance":"schen_m0_minute_proxy",
        "schen_clamped_like_headstart":"schen_m0_minute_proxy",
        "headstart_unclamped_like_schen":"kalshibot_headstart",
        "logit_without_headstart":"logit_full",
        "logit_without_momentum":"logit_full",
        "logit_without_rsi":"logit_full",
        "logit_headstart_only":"logit_full",
        "logit_momentum_only":"logit_full",
        "logit_rsi_only":"logit_full",
        "logit_intercept_only":"logit_full",
        "headstart_prior_only":"logit_full",
        "half_headstart_half_logit":"logit_full",
        "half_ensemble_half_logit":"axiom_ensemble",
        "half_headstart_half_ensemble":"axiom_ensemble",
        "half_schen_half_logit":"schen_m0_minute_proxy",
    }
    # For interpretability, positive deltas mean the variant IMPROVES parent.
    report={}
    for period in PERIODS:
        entries=[]
        expected_cps={cp for cp,_ in PERIODS[period]}
        for ablated,origin in parent.items():
            # A 'last minute' result must cover all five requested instants,
            # never covertly represent only the 60-seconds-left snapshot.
            present_cps={r["checkpoint"] for r in data
                         if r["checkpoint"] in expected_cps
                         and ablated in r["predictions"] and
                         origin in r["predictions"]}
            if present_cps!=expected_cps:
                continue
            pair=paired_comparison(data,period,ablated,origin)
            if not pair.get("n_contracts"):continue
            entries.append({"parent":origin,"variant":ablated,
                            "improvement_over_parent":pair})
        report[period]=entries
    # Family-wise Holm-Bonferroni over every ablation and time window,
    # rather than treating nominal unadjusted intervals as discoveries.
    flat=[e["improvement_over_parent"] for entries in report.values()
          for e in entries]
    ranked=sorted(enumerate(flat),key=lambda x:x[1]["approx_two_sided_signflip_p"])
    highwater=0.
    for rank,(idx,item) in enumerate(ranked):
        adjusted=min(1.,item["approx_two_sided_signflip_p"]*(len(flat)-rank))
        highwater=max(highwater,adjusted)
        item["holm_familywise_adjusted_p"]=round(highwater,6)
        item["holm_familywise_5pct_pass"]=bool(highwater<.05)
        item["multiple_comparisons_count"]=len(flat)
    return report


def direction_vs_probability_diagnostics(data):
    """Separate changes in WHICH SIDE wins from confidence calibration shifts.

    Per-contract weighting avoids inflating precision from five same-label
    checkpoints. Zero reflects no evidence of extra directional information.
    """
    comparisons=(
        ("logit_full","kalshibot_headstart"),
        ("logit_full","axiom_ensemble"),
        ("logit_without_headstart","logit_full"),
        ("logit_without_momentum","logit_full"),
        ("logit_without_rsi","logit_full"),
        ("headstart_fixed_train_volatility","kalshibot_headstart"),
        ("schen_m0_minute_proxy","kalshibot_headstart"),
    )
    out={}
    for period,cps in PERIODS.items():
        cp_names={c for c,_ in cps}
        subset=[r for r in data if r["checkpoint"] in cp_names]
        for first,second in comparisons:
            contract=collections.defaultdict(list)
            for row in subset:
                p=row["predictions"]
                if first not in p or second not in p:
                    continue
                a,b=p[first],p[second]
                correct_a=int((a>=.5)==bool(row["y"]))
                correct_b=int((b>=.5)==bool(row["y"]))
                contract[row["ticker"]].append({
                    "different_direction":int((a>=.5)!=(b>=.5)),
                    "first_helped":int(correct_a>correct_b),
                    "first_hurt":int(correct_a<correct_b),
                    "mean_abs_probability_change":abs(a-b),
                })
            if not contract:continue
            per_contract={key:statistics.mean(
                statistics.mean(item[name] for item in record)
                for record in contract.values())
                for key in ("different_direction","first_helped","first_hurt",
                            "mean_abs_probability_change")}
            out[f"{period}::{first}_vs_{second}"]={
                "matched_contracts":len(contract),
                "matched_snapshots":sum(len(x) for x in contract.values()),
                **{key:round(value,6) for key,value in per_contract.items()},
                "interpretation":"Different-direction fraction distinguishes directional change from probability recalibration; these exploratory results cannot establish market causality.",
            }
    return out


def model_coefficients(fits):
    result={}
    for cp in CP:
        keys={}
        for group in GLM_GROUPS:
            fit=fits.get((cp,group))
            if fit is not None:
                keys[group]={
                    "intercept":round(fit["theta"][0],6),
                    "weights":{feature:round(value,6)
                               for feature,value in zip(
                                   fit["features"],fit["theta"][1:])},
                    "train_contracts":fit["train_contracts"],
                }
        result[cp]=keys
    return result


def source_mechanism_summary(parity,mechanics):
    result={}
    for cp in CP:
        m=mechanics.get(cp,[])
        diff=[x["schen_minus_headstart_prob"] for x in m]
        result[cp]={
            "actual_source_formula_mirror_max_abs_diff":round(
                max(parity.get(cp, [0.])),8),
            "paired_schen_headstart_count":len(diff),
            "schen_headstart_mean_abs_probability_delta":round(
                statistics.mean(abs(v) for v in diff),9) if diff else None,
            "schen_headstart_max_abs_probability_delta":round(
                max(abs(v) for v in diff),9) if diff else None,
            "headstart_sigma_floor_engaged_n":sum(x["headstart_sigma_floor_active"]
                                                 for x in m),
            "momentum_aligned_with_distance_fraction":round(
                statistics.mean(x["trend_aligned"] for x in m),4) if m else None,
        }
    return result


def regime_scores(data,train):
    # Thresholds chosen using TRAINING source volatility only.
    train_vols=sorted(extract_components(r)["stdev"] for r in train)
    median_vol=statistics.median(train_vols)
    regimes={}
    for period,cps in PERIODS.items():
        wanted={c for c,_ in cps}
        pool=[r for r in data if r["checkpoint"] in wanted]
        modes={
            "near_strike_z_below_0_5":lambda r:r["regime"]["abs_headstart_z"]<.5,
            "far_from_strike_z_at_least_1_5":lambda r:r["regime"]["abs_headstart_z"]>=1.5,
            "higher_than_training_median_vol":lambda r:r["regime"]["volatility"]>median_vol,
            "lower_than_training_median_vol":lambda r:r["regime"]["volatility"]<=median_vol,
            "momentum_aligned":lambda r:r["regime"]["momentum_aligns_target_distance"],
            "momentum_opposed":lambda r:not r["regime"]["momentum_aligns_target_distance"],
        }
        for condition,fn in modes.items():
            subset=[r for r in pool if fn(r)]
            selected=("axiom_ensemble","kalshibot_headstart","schen_m0_minute_proxy",
                      "logit_full","logit_without_headstart",
                      "logit_without_momentum","aaryann_no_momentum")
            groups={}
            for candidate in selected:
                present=[{"ticker":r["ticker"],"p":r["predictions"][candidate],
                          "y":r["y"]}
                         for r in subset if candidate in r["predictions"]]
                if present:groups[candidate]=W.score(present)
            regimes[f"{period}::{condition}"]={
                "n_contracts":len({r["ticker"] for r in subset}),
                "n_observations":len(subset),
                "scores":groups,
                "small_sample_posthoc_exploratory_only":True,
            }
    return {"train_vol_median":median_vol,"details":regimes}


def early_day_rolling_validation(train):
    """Two expanding chronological folds INSIDE Oct 13. No Oct 25 in fitting."""
    contract_start={}
    for row in train:
        contract_start[row["ticker"]]=min(row["ts"],
              contract_start.get(row["ticker"],row["ts"]))
    order=sorted(contract_start,key=lambda t:(contract_start[t],t))
    # Treat BOTH settlement timestamp and dataset's actual received timestamp
    # as hard as-of constraints. A day-end grade may be unavailable at the
    # earlier training moment; never train from retrospectively known labels.
    grades=R.outcomes(R.DAYS[0])
    chunks=[(0,28,28,36),(0,36,36,len(order))]
    fold_counts=[]
    all_predictions=[]
    for fold,(first,before,start,end) in enumerate(chunks,1):
        prior=set(order[first:before])
        future=set(order[start:end])
        test_rows=[r for r in train if r["ticker"] in future]
        cutoff=min((r["ts"] for r in test_rows),default=None)
        known=set()
        if cutoff is not None:
            for ticker in prior:
                g=grades.get(ticker)
                if not g or g.get("ts_recv") is None or g.get("settlement_ts") is None:
                    continue
                if (g["ts_recv"]/R.NSEC<cutoff and
                    g["settlement_ts"]/R.NSEC<cutoff):
                    known.add(ticker)
        train_rows=[r for r in train if r["ticker"] in known]
        fold_record={"fold":fold,"train_contracts_in_time_order":len(prior),
                     "labels_evidenced_received_by_validation":len(known),
                     "validation_contracts":len(future),
                     "first_validation_ts":cutoff}
        if len(known)<25:
            fold_record["status"]="INSUFFICIENT_ASOF_OFFICIAL_TRAINING_LABELS"
            fold_counts.append(fold_record)
            continue
        fits,sigmas=prepare_train(train_rows)
        test_eligible=[r for r in test_rows if r["checkpoint"] in sigmas]
        outcome,_,_=evaluate_rows(test_eligible,fits,sigmas)
        fold_record["status"]="REPLAYED_WITH_ASOF_RECEIVED_LABEL_GUARD"
        fold_record["validation_observations"]=len(outcome)
        fold_counts.append(fold_record)
        for r in outcome:r["fold"]=fold
        all_predictions.extend(outcome)
    # Zero internal scored rows is a meaningful label-provenance result, not a
    # license to use retrospectively known settlements.
    return {
        "fold_contract_counts":fold_counts,
        "validation_contracts":len({r["ticker"] for r in all_predictions}),
        "period_scores":periods(all_predictions) if all_predictions else {},
        "note":"Strict as-of settlement-receipt guard; absence of in-day evidence is reported as UNAVAILABLE. External Oct25 data was previously examined, so remains exploratory.",
    }


def main():
    R.CHECKPOINTS=dict(CP)
    observations,quality,_=R.make_dataset()
    train=observations[R.DAYS[0]]
    test=observations[R.DAYS[1]]
    data,fits,sigmas,parity,mechanics=prepare_holdout_rows(train,test)
    internal=early_day_rolling_validation(train)
    output={
        "status":"EXPLORATORY_CAUSAL_FORMULA_ABLATION_NOT_VALIDATED_ECONOMIC_ALPHA",
        "source":"KalshiEye/kalshi-order-book-sample (CC BY-NC 4.0)",
        "train_day":R.DAYS[0],"holdout_day_already_previously_explored":R.DAYS[1],
        "training_contracts":len({r["ticker"] for r in train}),
        "holdout_contracts":len({r["ticker"] for r in data}),
        "holdout_rows":len(data),
        "source_quality":{d:{
            "clean_distinct_contracts":q["clean_distinct_contracts"],
            "clean_checkpoints":q["clean_checkpoints"],
            "rejections":q["rejections"]}
            for d,q in quality.items()},
        "frozen_source_equation_parity_and_similarity":source_mechanism_summary(
            parity,mechanics),
        "train_day_model_coefficients":model_coefficients(fits),
        "direction_vs_probability_diagnostics":direction_vs_probability_diagnostics(data),
        "all_ablations_compared_to_their_frozen_parent":ablation_matrix(data),
        "all_period_model_scores_contract_weighted":periods(data),
        "regime_stratification_posthoc":regime_scores(data,train),
        "prior_date_rolling_validation":internal,
        "limits":[
            "Historical market strikes originate in a day-end market catalog. Publication time is unknown; cannot certify point-in-time contract target.",
            "This uses received exchange MID QUOTE bars, not actual Coinbase traded OHLCV or CF Benchmarks BRTI index.",
            "Schen M0 is a one-minute volatility proxy, not the exact per-second original; the final-second partial BRTI averaging history is missing.",
            "The existing HeadStart is a CDF on a feature, not the complete trained Swift KalshiBot.",
            "GLM ablations are refit solely on the Oct13 training data. Causal ablation here means a controlled code/model intervention; it does NOT prove market causal mechanisms.",
            "Oct25 was already inspected in earlier rounds, so this is exploratory model diagnosis not untouched confirmatory holdout despite chronological training.",
            "Two noncontiguous days, tiny GLM training sets, correlated consecutive contracts, broad model search; bootstrap intervals unadjusted for multiple testing.",
            "Time-window model switching/combinations are candidate counterfactuals, not production strategies.",
            "No live trading, orders, deployment, database update or production model changes.",
        ],
    }
    print("BEGIN_ABLATION_AUDIT_JSON")
    print(json.dumps(output,sort_keys=True,indent=2))
    print("END_ABLATION_AUDIT_JSON")


if __name__=="__main__":
    main()
