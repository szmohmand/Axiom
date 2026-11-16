"""AXIOM large-cohort source-bounded independent forecast ingredient replication.

25,370 Kalshi official outcome windows (Jan 10-Oct 4, 2026; DegenHedge),
Binance official BTCUSDT 1m exchange TRADE klines (Jan-Oct 2026).
Critically a USDT spot proxy with a contract-strike-offset approximation;
NOT the CF BRTI index, not spot USD, and Kalshi strike publication timestamps
are unavailable. THIS IS CONDITIONAL RETROSPECTIVE RESEARCH, NOT LIVE ALPHA.

Fixed chronological training: Jan-Jun. Analysis validation: Jul-Aug.
Previously-inspected but out-of-train research check: Sep-Oct 4. Previous
Oct25 model discoveries influenced test specification and are newer than
Sep-Oct, so this is NOT a pristine historical prospective holdout.

Only completed one-minute bars: opening +60 and +120s, expiry -600,
-300, and -60s. Intraminute (+15s, last-15s) scores unavailable. Missing
or gapped bars are NEVER interpolated. Kalshi market quote is NOT an input.
All 1m candles and window official labels are fetched from PUBLIC sources,
with source checksums validated where published. Nothing is committed
from downloaded market data or written to production. Read-only.
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import hashlib
import io
import json
import math
import random
import statistics
import time
import urllib.request
import zipfile

import numpy as np

from app.ensemble import engine_pack
from research import ingredient_ablation as A
from research import kalshieye_replay as R

WINDOW_URL = "https://huggingface.co/datasets/DegenHedge/kalshi-btc-15m/resolve/main/windows.csv"
CHECKSUM_URL = "https://huggingface.co/datasets/DegenHedge/kalshi-btc-15m/resolve/main/CHECKSUMS.sha256"
BINANCE = "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/"
MONTHS=tuple(f"2026-{m:02}" for m in range(1,11))
POINTS = {
    "opening_plus_60s":60,
    "opening_plus_120s":120,
    "ten_minutes_left":300,
    "five_minutes_left":600,
    "last_60s":840,
}
PERIODS={
    "first_2min":("opening_plus_60s","opening_plus_120s"),
    "10min_left":("ten_minutes_left",),
    "5min_left":("five_minutes_left",),
    "last_60s_only":("last_60s",),
}
# Two independent 1m OHLCV-based opening strike proxy anchors:
# Exchange 1m TWAP estimator from OHLC4, and the pre-open last trade close.
ANCHORS=("ohlc4","preopen_close")
GLMS={
    "logit_full":("headstart","momentum5","rsi"),
    "logit_headstart_only":("headstart",),
    "logit_without_headstart":("momentum5","rsi"),
    "logit_without_momentum":("headstart","rsi"),
    "logit_without_rsi":("headstart","momentum5"),
    "logit_intercept_only":(),
}
COMPARATORS=("kalshibot_headstart","schen_m0_minute_proxy",
             "axiom_volatility","aaryann_fair","axiom_ensemble",
             "logit_full","logit_headstart_only",
             "logit_without_headstart","logit_without_momentum",
             "logit_without_rsi","logit_intercept_only","headstart_prior_only")
FIXED_HYPOTHESIS_MODEL={
    "first_2min":"kalshibot_headstart",
    "10min_left":"kalshibot_headstart",
    "5min_left":"logit_headstart_only",
    "last_60s_only":"logit_headstart_only",
}
REQ={"User-Agent":"AXIOM-offline-research/1.0"}

def download(url, maxbytes):
    last=None
    for i in range(3):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=REQ),timeout=100) as stream:
                b=stream.read(maxbytes+1)
            if len(b)>maxbytes:
                raise ValueError(f"source larger than research limit: {url}")
            return b
        except Exception as exc:
            last=exc
            if i<2: time.sleep(1+i)
    raise RuntimeError(f"unable to fetch required genuine data: {url}: {last}")


def source_windows():
    raw=download(WINDOW_URL,20_000_000)
    digest=hashlib.sha256(raw).hexdigest()
    check=download(CHECKSUM_URL,150_000).decode("utf-8")
    expected=None
    for line in check.splitlines():
        if "windows.csv" in line:
            expected=line.split()[0].lower()
            break
    if not expected or len(expected)!=64 or expected!=digest:
        raise ValueError(f"OFFICIAL public data checksum mismatch ({digest} vs {expected})")
    kept=[];exc=collections.Counter(); seen=set()
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
        tick=row.get("window_ticker") or ""
        if tick in seen:
            raise ValueError("duplicate Kalshi contract in source")
        seen.add(tick)
        if not tick.startswith("KXBTC15M-"):
            exc["not_btc_15m"]+=1;continue
        if row.get("strike_flag")!="ok":
            exc["invalid_strike_flag"]+=1;continue
        if row.get("result") not in ("yes","no"):
            exc["no_official_yes_no_result"]+=1;continue
        try:
            strike=float(row.get("official_strike") or "")
            opened=dt.datetime.fromisoformat(row["open_utc"].replace("Z","+00:00"))
            closed=dt.datetime.fromisoformat(row["close_utc"].replace("Z","+00:00"))
            a=int(opened.timestamp());b=int(closed.timestamp())
        except (ValueError,TypeError,OverflowError):
            exc["unparseable_record"]+=1;continue
        if (strike<1000 or not math.isfinite(strike) or
            b-a!=900 or a%60 or b%60):
            exc["invalid_strike_clock_duration"]+=1;continue
        settlement=row.get("official_settlement_value")
        if settlement:
            value=float(settlement)
            if not math.isfinite(value) or
                (("yes" if round(value,2)>=round(strike,2) else "no")!=row["result"]):
                # This is an INTEGRITY discrepancy, not a reason to silently
                # replace the official outcome using spot.
                exc["settlement_value_vs_result_conflict"]+=1;continue
        kept.append({"ticker":tick,"open":a,"close":b,
                     "strike":strike,"y":int(row["result"]=="yes"),
                     "date":opened.date().isoformat()})
    return kept,{"csv_sha256":digest,"raw_rows":len(seen),
                 "eligible_window_rows":len(kept),"excluded":dict(exc)}


def load_klines():
    bars={};manifest={}
    allproblems=collections.Counter()
    for month in MONTHS:
        name=f"BTCUSDT-1m-{month}.zip"
        u=BINANCE+name
        blob=download(u,35_000_000)
        ch=download(u+".CHECKSUM",5000).decode().split()[0].lower()
        digest=hashlib.sha256(blob).hexdigest()
        if ch!=digest:raise ValueError(f"checksum mismatch for {month}: {digest}!={ch}")
        z=zipfile.ZipFile(io.BytesIO(blob))
        if len(z.namelist())!=1 or not z.namelist()[0].endswith(".csv"):
            raise ValueError(f"invalid source archive members for {month}")
        count=0
        lines=0
        with z.open(z.namelist()[0],"r") as f:
            stream=io.TextIOWrapper(f,encoding="utf-8")
            for row in csv.reader(stream):
                lines+=1
                if len(row)<7:
                    raise ValueError(f"missing 1m OHLCV columns: {month}")
                try:
                    rawts=int(row[0])
                    if rawts > 10**14: epoch=rawts//1_000_000
                    elif rawts > 10**12: epoch=rawts//1000
                    else:raise ValueError("unexpected timestamp unit")
                    op,hi,lo,cl,volume=[float(row[i]) for i in range(1,6)]
                except (ValueError,IndexError) as e:
                    raise ValueError(f"invalid primary candle in {month} row {lines}: {e}")
                if (epoch%60!=0 or op<=0 or lo<=0 or
                    lo>min(op,cl) or hi<max(op,cl) or
                    not all(math.isfinite(x) for x in (op,hi,lo,cl,volume)) or
                    volume<0):
                    raise ValueError(f"out-of-spec original 1m candle {month} row {lines}")
                if epoch in bars:raise ValueError(f"source duplicate minute {epoch}")
                bars[epoch]=(op,hi,lo,cl)
                count+=1
        manifest[month]={"sha256_zip":digest,"rows":count,
                         "byte_length":len(blob)}
        print("VALIDATED_EXCHANGE_MONTH",json.dumps(
            {"month":month,"rows":count,"sha256":digest}),flush=True)
    return bars,manifest


def qualified_candles(bars,w,checkpoint,anchor):
    """All times are EPOCH seconds. Only [t-61m,t) completed bars."""
    opening=w["open"];decision=opening+POINTS[checkpoint]
    pre=bars.get(opening-60)
    if pre is None:return None,"missing_opening_reference"
    first=opening+POINTS[checkpoint]-61*60
    raw=[]
    for n in range(61):
        t=first+60*n
        b=bars.get(t)
        if b is None:return None,"gapped_or_missing_completed_minute"
        if t>=decision:return None,"future_bar"
        raw.append((t,b))
    # Calibration anchor is an ESTIMATE of Binance's 60s pre-open average,
    # NOT a historical BRTI opening average. The genuine Kalshi strike
    # is an explicit event input, originally fetched after settlement.
    base=(sum(pre)/4 if anchor=="ohlc4" else pre[3])
    offset=w["strike"]-base
    adjusted=[{"t":t,"open":x[0]+offset,"high":x[1]+offset,
               "low":x[2]+offset,"close":x[3]+offset,
               "source":"BINANCE_SPOT_BTCUSDT_OFFSET_PROXY"}
              for t,x in raw]
    if any(row["low"]<=0 for row in adjusted):
        return None,"invalid_shifted_price"
    row={
        "ticker":w["ticker"],"date":w["date"],"ts":decision,
        "checkpoint":checkpoint,"remaining":w["close"]-decision,
        "spot":adjusted[-1]["close"],"candles":adjusted,
        "target":w["strike"],"y":w["y"],"quote":None
    }
    row["features"]=R.math_features(row)
    return row,None


def build_dataset(windows,bars,anchor):
    subset=collections.defaultdict(list);excluded=collections.Counter()
    for w in windows:
        source_rows=[]
        for cp in POINTS:
            row,err=qualified_candles(bars,w,cp,anchor)
            if err:
                excluded[err]+=1;continue
            source_rows.append(row)
        # Require complete same-contract checkpoint set. Do not compare
        # a subset with a different source coverage and claim matched rank.
        if len(source_rows)==len(POINTS):
            year_month=w["date"][:7]
            if year_month<="2026-06":
                subset["train"].extend(source_rows)
            elif year_month<="2026-08":
                subset["validation"].extend(source_rows)
            else:
                subset["test"].extend(source_rows)
        else:
            excluded["contract_missing_one_or_more_checkpoints"]+=1
    return subset,dict(excluded)


def fit_glm(rows,group):
    """Exact normalized prior-gradient specification; numpy speeds batch fit."""
    cols=GLMS[group]
    X=np.ones((len(rows),len(cols)+1),dtype=np.float64)
    for i,name in enumerate(cols,1):
        X[:,i]=[r["features"][name] for r in rows]
    y=np.asarray([r["y"] for r in rows],dtype=np.float64)
    if len(y)<100 or len(set(y))<2:raise ValueError("not enough labeled training contracts")
    prior=np.asarray([0.]+[1.7 if x=="headstart" else 0 for x in cols])
    w=prior.copy()
    # The existing research code's deterministic L2-to-prior 400-step solver.
    for _ in range(400):
        z=np.clip(X@w,-40,40)
        p=1/(1+np.exp(-z))
        grad=X.T@(p-y)/len(y)+.08*(w-prior)
        w-=.12*grad
    return { "features":list(cols),"coefs":w.tolist(),
             "train_windows":len(y)}


def fit_all(train):
    grouped=collections.defaultdict(list)
    for r in train:grouped[r["checkpoint"]].append(r)
    models={}
    for cp,rows in grouped.items():
        for group in GLMS:
            models[(cp,group)]=fit_glm(rows,group)
    return models


def predict_glm(rows,fitted):
    features=fitted["features"]
    X=np.ones((len(rows),len(features)+1),dtype=np.float64)
    for i,name in enumerate(features,1):
        X[:,i]=[r["features"][name] for r in rows]
    w=np.asarray(fitted["coefs"])
    return (1/(1+np.exp(-np.clip(X@w,-40,40)))).tolist()


def infer(split,trained):
    bycp=collections.defaultdict(list)
    for row in split: bycp[row["checkpoint"]].append(row)
    result=[]
    for cp,rows in bycp.items():
        fits={g:predict_glm(rows,trained[(cp,g)]) for g in GLMS}
        for i,row in enumerate(rows):
            market={"target":row["target"],"seconds_left":row["remaining"],
                    "market_mid":None}
            pack=engine_pack(row["spot"],market,row["candles"])
            pred={v["name"]:v["prob_above"] for v in pack["engines"]
                  if v.get("independent") and v["available"]}
            if pack["available"]:pred["axiom_ensemble"]=pack["prob_above"]
            pred["schen_m0_minute_proxy"]=R.zero_drift(row)
            pred["headstart_prior_only"]=R.sigmoid(
                1.7*row["features"]["headstart"])
            pred.update({g:fits[g][i] for g in GLMS})
            if not set(COMPARATORS).issubset(pred):
                raise AssertionError(f"all models must share same records: {cp}")
            if any(not math.isfinite(p) or p<0 or p>1 for p in pred.values()):
                raise ValueError("Invalid forecast; do not silently impute")
            result.append({"ticker":row["ticker"],"date":row["date"],
                           "cp":cp,"y":row["y"],"p":pred,
                           "close":row["ts"]+row["remaining"]})
    return result


def get_samples(rows,period,model):
    cps=set(PERIODS[period])
    by_contract=collections.defaultdict(list)
    for r in rows:
        if r["cp"] in cps:
            by_contract[r["ticker"]].append(
                (r["p"][model],r["y"],r["date"]))
    return by_contract


def score(rows,period,model):
    data=get_samples(rows,period,model)
    if not data:return None
    errors=[];directions=[];date_scores=collections.defaultdict(list)
    for ticker,items in data.items():
        if len(items)!=len(PERIODS[period]):
            raise AssertionError("partial contract period")
        mse=statistics.mean((p-y)**2 for p,y,day in items)
        acc=statistics.mean(int((p>=.5)==bool(y)) for p,y,day in items)
        errors.append(mse);directions.append(acc)
        date_scores[items[0][2]].append(mse)
    return {"contracts":len(errors),"days":len(date_scores),
            "brier":round(statistics.mean(errors),7),
            "accuracy":round(statistics.mean(directions),6)}


def paired_day_uncertainty(rows,period,first,second,seed=20261115,draws=2000):
    a=get_samples(rows,period,first)
    b=get_samples(rows,period,second)
    if a.keys()!=b.keys():raise AssertionError("different contract populations")
    days=collections.defaultdict(list)
    for ticker in a:
        xa,xb=a[ticker],b[ticker]
        if len(xa)!=len(xb):raise AssertionError("unequal window observations")
        d=statistics.mean((y-p2)**2-(y-p1)**2 for
                          (p1,y,day),(p2,y2,day2) in zip(xa,xb)
                          if y==y2 and day==day2)
        days[xa[0][2]].append(d)
    if len(days)<2:return {"days":len(days),"status":"INSUFFICIENT_DAYS"}
    dayitems=sorted(days.items())
    daily_means=[statistics.mean(v) for _,v in dayitems]
    # Date block bootstrap: resample whole UTC days weighted by number of
    # held-out contracts in each day, not a false IID 1m snapshot sample.
    rng=random.Random(seed)
    boot=[]
    for _ in range(draws):
        chosen=[dayitems[rng.randrange(len(dayitems))][1]
                for _ in range(len(dayitems))]
        boot.append(sum(sum(x) for x in chosen)/sum(len(x) for x in chosen))
    boot.sort()
    exact=sum(sum(x) for _,xs in dayitems for x in xs)/sum(len(xs) for _,xs in dayitems)
    return {"days":len(days),"contracts":sum(len(v) for _,v in dayitems),
            "delta_brier_second_minus_first":round(exact,7),
            "approx_day_cluster_bootstrap95":[round(boot[49],7),
                                               round(boot[1950],7)],
            "descriptive_one_proxy_only":True}


def grade(result):
    summary={}
    for split,records in result.items():
        section={}
        for p in PERIODS:
            section[p]={
                "models":{model:score(records,p,model) for model in COMPARATORS},
                "pairs":{
                    "headstart_versus_existing_ensemble":
                        paired_day_uncertainty(records,p,"kalshibot_headstart","axiom_ensemble"),
                    "learned_headstart_vs_direct":
                        paired_day_uncertainty(records,p,"logit_headstart_only","kalshibot_headstart"),
                    "headstart_removed_from_full_logit":
                        paired_day_uncertainty(records,p,"logit_full","logit_without_headstart"),
                    "remove_momentum_from_full_logit":
                        paired_day_uncertainty(records,p,"logit_without_momentum","logit_full"),
                    "remove_rsi_from_full_logit":
                        paired_day_uncertainty(records,p,"logit_without_rsi","logit_full"),
                },
            }
        # Prechosen adaptation from PRIOR Oct25 exploration; never pretend
        # this was learned/picked from the present held-out months.
        numerator=0;den=0
        per_period={}
        for period in PERIODS:
            chosen=FIXED_HYPOTHESIS_MODEL[period]
            per_period[period]={"fixed_preexisting_challenger":chosen,
                    "score":score(records,period,chosen)}
        section["fixed_time_switch_from_previously_seen_results"]=per_period
        summary[split]=section
    return summary


def main():
    windows,wm=source_windows()
    bars,ex_manifest=load_klines()
    out={};anchor_summary={}
    for anchor in ANCHORS:
        splits,excluded=build_dataset(windows,bars,anchor)
        if not splits["train"] or not splits["validation"] or not splits["test"]:
            raise AssertionError(f"missing source months in {anchor}: {dict((k,len(v)) for k,v in splits.items())}")
        trains=fit_all(splits["train"])
        # Exact dense solver parity to research small reference case:
        sample=splits["train"][:40]
        reference=R.fit_logit(sample)
        testfit=fit_glm(sample,"logit_full")
        if max(abs(a-b) for a,b in zip(reference,testfit["coefs"]))>1e-7:
            raise AssertionError("numpy logistic optimizer does not reproduce prior reference")
        evaluated={name:infer(rows,trains) for name,rows in splits.items()}
        out[anchor]=grade(evaluated)
        anchor_summary[anchor]={
            "excluded_checkpoint_events":excluded,
            "contract_counts":{name:len(rows)//len(POINTS) for name,rows in splits.items()},
            "checkpoint_rows":{name:len(rows) for name,rows in splits.items()},
            "trained_coefficients":{
                cp:{g:{"features":trains[(cp,g)]["features"],
                       "values":[round(z,5) for z in trains[(cp,g)]["coefs"]]}
                    for g in ("logit_full","logit_headstart_only")}
                for cp in POINTS},
        }
        print("ANCHOR_COMPLETED",anchor,json.dumps(anchor_summary[anchor]["contract_counts"]),flush=True)
    output={
        "status":"RETROSPECTIVE_PROXY_STRESS_TEST_NOT_STRICT_ASOF_BRTI",
        "data_source_official_outcomes":"DegenHedge/kalshi-btc-15m v2026.10.1, Kalshi historical market facts",
        "data_source_spot":"Binance exchange published BTCUSDT spot TRADE 1m monthly zip archives",
        "original_record_checksums":{"kalshi":wm,"binance":ex_manifest},
        "source_total_eligible_official_windows":len(windows),
        "windows_and_model_periods":{
            "training":"Jan-Jun 2026",
            "validation":"Jul-Aug 2026",
            "research_test":"Sep-Oct 4 2026 (outcome history already exposed)"
        },
        "minimum_source_anchors":ANCHORS,
        "source_quality_and_training":anchor_summary,
        "model_period_scores_and_paired_day_uncertainty":out,
        "honest_limits":[
            "Binance USDT trade price is not Kalshi CF Benchmarks BRTI and opening 60-second BRTI strike is not reconstructable from 1-minute OHLCV. OHLC4 vs last close are explicit different PROXY assumptions.",
            "Day-end official strike publication timestamp is not separately proven. This is retrospective conditional input and CANNOT certify real point-in-time forecasts.",
            "The hypothesis/model family was chosen after inspecting October 25; Sept-Oct 4 is a pre-existing earlier-date corroboration, not untouched prospective confirmation.",
            "No intraminute observations: first 2min means +60/+120 sec; final minute is ONLY -60 sec, never last 15, 5 or 1 seconds.",
            "Binance 1m candle close for minute [t-60,t) used at t, not BTC price exactly at t; possible exchange data publication latency unmeasured.",
            "Data official YES/NO outcome is used only as training label in Jan-Jun and scoring later; no third-party alert self-selection.",
            "No direct Kalshi YES market price quote source. Cannot calculate contemporaneous fee-aware executable edge or profit.",
            "Source metadata/CSV may be backfilled or corrected. Checksum integrity proves file identity not contemporaneous existence.",
            "Exchange anchor shift equal to official strike conditions Binance-relative movement on known strike; not proof of real BRTI proxy validity. Near-target sensitivity may dominate.",
            "No production model changes, scheduling, trades, deployment or merges.",
        ]
    }
    print("BEGIN_LARGE_COHORT_RESEARCH_JSON")
    print(json.dumps(output,sort_keys=True,indent=2))
    print("END_LARGE_COHORT_RESEARCH_JSON")
if __name__=="__main__":
    main()
