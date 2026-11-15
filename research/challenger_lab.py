"""Isolated, read-only BTC15m challenger research. NOT loaded by AXIOM runtime.

All independent models see the same *causal* BTC candles, spot, Kalshi
published target and expiry. Kalshi quotes are benchmark-only. Outcomes
are supplied separately after official settlement. No orders or credentials.

Third-party-inspired reimplementations, NOT the original trained model weights
or a claim of source-level parity. No predictive advantage is presumed.
"""
from __future__ import annotations
import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from app.ensemble import engine_pack

CHECKPOINTS = {"14m": 840, "12m": 720, "10m": 600, "5m": 300, "1m": 60}
INDEPENDENT = ("axiom_volatility", "aaryann_fair", "kalshibot_headstart",
               "ensemble", "settlement_zero_drift", "kalshibot_independent_logistic",
               "siddha_spot_xgboost")
BENCHMARK = "kalshi_market_mid"
FEATURES = ("headstart", "momentum5", "rsi", "volatility", "log_distance",
            "minutes_left", "vol_5m", "time_sin", "time_cos")
EPS = 1e-6


class ReplayError(ValueError):
    pass


def _num(x, name):
    if isinstance(x, bool):
        raise ReplayError(f"Invalid {name}: bool")
    try:
        y = float(x)
    except (ValueError, TypeError):
        raise ReplayError(f"Invalid {name}") from None
    if not math.isfinite(y):
        raise ReplayError(f"Non-finite {name}")
    return y


def checkpoint(seconds_left):
    fits = [(abs(seconds_left - sec), label) for label, sec in CHECKPOINTS.items()
            if abs(seconds_left - sec) <= 30]
    return min(fits)[1] if fits else None


def normalize_observation(raw):
    """Reject future candles, forming candles, stale spot and embedded outcomes."""
    if any(key in raw for key in ("label", "result", "official_result", "went_up")):
        raise ReplayError("Outcomes must be stored in a separate settlement dataset")
    ticker = raw.get("ticker")
    if not isinstance(ticker, str) or not ticker.startswith("KXBTC15M-"):
        raise ReplayError("Only KXBTC15M contracts")
    ts, spot_ts = _num(raw.get("ts"), "ts"), _num(raw.get("spot_ts"), "spot_ts")
    opened = _num(raw.get("open_ts"), "open_ts")
    expires = _num(raw.get("expires_ts"), "expires_ts")
    spot, target = _num(raw.get("spot"), "spot"), _num(raw.get("target"), "target")
    if not (opened <= ts < expires and expires > opened and spot > 0 and target > 0):
        raise ReplayError("Invalid contract times or price")
    if not (0 <= ts - spot_ts <= 30):
        raise ReplayError("Spot quote is future-dated or older than 30 seconds")
    candles = raw.get("candles")
    if not isinstance(candles, list) or len(candles) < 31:
        raise ReplayError("At least 31 authentic completed minute candles needed")
    cleaned = []
    for candle in candles:
        if not isinstance(candle, dict):
            raise ReplayError("Malformed candle")
        t = _num(candle.get("t"), "candle.t")
        close = _num(candle.get("close"), "candle.close")
        high = _num(candle.get("high", close), "candle.high")
        low = _num(candle.get("low", close), "candle.low")
        volume = _num(candle.get("volume", 0), "candle.volume")
        if t != int(t) or int(t) % 60 or close <= 0 or low <= 0 or high < max(low, close) or close < low or volume < 0:
            raise ReplayError("Invalid candle values or nonminute timestamp")
        cleaned.append({"t": int(t), "close": close, "high": high, "low": low, "volume": volume})
    if any(b["t"] - a["t"] != 60 for a, b in zip(cleaned, cleaned[1:])):
        raise ReplayError("No interpolated, reordered, duplicate or missing minute bars")
    if cleaned[-1]["t"] + 60 > ts:
        raise ReplayError("In-progress or future candle is not a causal input")
    if ts - (cleaned[-1]["t"] + 60) > 180:
        raise ReplayError("Candle input stale")
    mid = raw.get("market_mid")
    if mid is not None:
        mid = _num(mid, "market_mid")
        if not 0 < mid < 1:
            raise ReplayError("Invalid market benchmark quote")
    proxy_error = raw.get("proxy_error_usd")
    if proxy_error is not None:
        proxy_error = _num(proxy_error, "proxy_error_usd")
        if proxy_error < 0:
            raise ReplayError("Negative proxy error")
    return {"ticker": ticker, "ts": ts, "spot_ts": spot_ts, "open_ts": opened,
            "expires_ts": expires, "spot": spot, "target": target,
            "seconds_left": expires-ts, "candles": cleaned, "market_mid": mid,
            "proxy_error_usd": proxy_error, "checkpoint": checkpoint(expires-ts)}


def normalize_settlement(raw, allow_synthetic=False):
    ticker = raw.get("ticker")
    result = raw.get("result")
    source = raw.get("source")
    if not isinstance(ticker, str) or not ticker.startswith("KXBTC15M-"):
        raise ReplayError("Bad settlement ticker")
    if result not in ("yes", "no"):
        raise ReplayError("Only official yes/no outcomes can be scored")
    if source != "kalshi_official" and not (allow_synthetic and source == "synthetic_fixture"):
        raise ReplayError("Requires verified Kalshi official result source")
    close_ts = _num(raw.get("expires_ts"), "settlement expires_ts")
    settled_at = _num(raw.get("settled_at"), "settled_at")
    if settled_at < close_ts:
        raise ReplayError("Label cannot be known before contract expiration")
    return {"ticker": ticker, "result": result, "source": source,
            "expires_ts": close_ts, "settled_at": settled_at}


def inputs(row):
    """Explicit allowlist prevents Kalshi quotes or official labels entering challengers."""
    vals = [c["close"] for c in row["candles"][-61:]]
    returns = [math.log(b/a) for a, b in zip(vals, vals[1:])]
    vol = max(statistics.stdev(returns), EPS)
    sigma_usd = row["spot"] * vol
    minutes = row["seconds_left"] / 60
    # Approximate 60-second settlement averaging; not a true BRTI input.
    effective = max(minutes - 2 / 3, 1 / 3)
    headstart = (row["spot"]-row["target"]) / (sigma_usd*math.sqrt(effective))
    diffs = [b-a for a,b in zip(vals[-15:], vals[-14:])]
    gains = sum(max(d,0) for d in diffs)
    losses = sum(max(-d,0) for d in diffs)
    rsi = (gains / (gains+losses) - .5)*4 if gains+losses > 0 else 0.0
    last_5 = returns[-5:]
    # Every input is market-independent. Do not add market_mid to this list.
    x = {"headstart": max(-10, min(10, headstart)),
         "momentum5": max(-10, min(10, sum(last_5)/(vol*math.sqrt(5)))),
         "rsi": rsi, "volatility": vol,
         "log_distance": math.log(row["spot"]/row["target"]),
         "minutes_left": minutes,
         "vol_5m": sum(c["volume"] for c in row["candles"][-5:]),
         "time_sin": math.sin(2*math.pi*(row["ts"]%86400)/86400),
         "time_cos": math.cos(2*math.pi*(row["ts"]%86400)/86400)}
    return x


def sigmoid(z):
    z = max(-40, min(40, z))
    return 1 / (1 + math.exp(-z))


def normal_cdf(z):
    return .5*(1 + math.erf(z/math.sqrt(2)))


def zero_drift(row):
    """Spot/strike zero-drift estimate with approximate BRTI-average variance."""
    x = inputs(row)
    vol_usd = max(row["spot"]*x["volatility"], EPS)
    effective = max(row["seconds_left"]/60 - 2/3, 1/3)
    err = row["proxy_error_usd"] or 0.0
    sigma = math.sqrt(vol_usd**2 * effective + err**2)
    return min(.999, max(.001, normal_cdf((row["spot"]-row["target"])/sigma)))


def _glm_vector(x):
    # Independent mode: no Kalshi implied odds/price term.
    return (1.0, x["headstart"], x["momentum5"], x["rsi"])


def fit_independent_logistic(train, labels, cutoff):
    """Regularized KalshiBot-inspired logistic challenger, trained only on prior settlements."""
    points = []
    seen = set()
    for row in sorted(train, key=lambda r: (r["ts"], r["ticker"])):
        label = labels.get(row["ticker"])
        if not label or label["settled_at"] >= cutoff:
            continue
        # One representative early view per contract for equal contract weighting.
        if row["ticker"] in seen:
            continue
        seen.add(row["ticker"])
        points.append((_glm_vector(inputs(row)), int(label["result"] == "yes")))
    if len(points) < 10 or len({y for _,y in points}) < 2:
        return None
    prior = [0., 1.7, 0., 0.]
    theta = prior[:]
    for _ in range(400):
        grad = [0.,0.,0.,0.]
        for x,y in points:
            delta = sigmoid(sum(a*b for a,b in zip(theta,x))) - y
            for j in range(4):
                grad[j] += delta*x[j]
        for j in range(4):
            theta[j] -= .12*(grad[j]/len(points) + .08*(theta[j]-prior[j]))
    return theta


def logistic_predict(theta, row):
    x = _glm_vector(inputs(row))
    return sigmoid(sum(a*b for a,b in zip(theta,x)))


def fit_spot_xgboost(train, labels, cutoff):
    """Optional actual XGBoost estimator; a new spot-only challenger, not original weights."""
    try:
        from xgboost import XGBClassifier
    except ImportError:
        return None, "xgboost is not installed in the optional research environment"
    by_contract = {}
    for row in sorted(train, key=lambda r:(r["ts"],r["ticker"])):
        label = labels.get(row["ticker"])
        if label and label["settled_at"] < cutoff:
            by_contract.setdefault(row["ticker"], row)
    items = list(by_contract.values())
    if len(items) < 20 or len({labels[x["ticker"]]["result"] for x in items}) < 2:
        return None, "At least 20 earlier independently settled contracts of both outcomes required"
    X = [[inputs(x)[k] for k in FEATURES] for x in items]
    y = [int(labels[x["ticker"]]["result"]=="yes") for x in items]
    model = XGBClassifier(n_estimators=75, max_depth=2, learning_rate=.05,
                          subsample=.9, colsample_bytree=1., objective="binary:logistic",
                          eval_metric="logloss", n_jobs=1, random_state=19)
    model.fit(X,y)
    return model, None


def _read_jsonl(path):
    result=[]
    with Path(path).open(encoding="utf-8") as fh:
        for line_number, line in enumerate(fh,1):
            if not line.strip():
                continue
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ReplayError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return result


def load_data(observations_path, settlements_path, allow_synthetic=False):
    obs=[normalize_observation(row) for row in _read_jsonl(observations_path)]
    labels={}
    for raw in _read_jsonl(settlements_path):
        s=normalize_settlement(raw,allow_synthetic)
        if s["ticker"] in labels:
            raise ReplayError(f"Duplicate official result for {s['ticker']}")
        labels[s["ticker"]]=s
    by_key=set()
    for row in obs:
        key=(row["ticker"], row["checkpoint"])
        if row["checkpoint"] is None:
            raise ReplayError("Observation must be at an early or fixed checkpoint (+/-30s)")
        if key in by_key:
            raise ReplayError("Duplicate contract/checkpoint; choose it before evaluation")
        by_key.add(key)
        if row["ticker"] in labels and row["expires_ts"] != labels[row["ticker"]]["expires_ts"]:
            raise ReplayError("Settlement expiration does not match observed contract")
    return sorted(obs,key=lambda r:(r["expires_ts"],r["ts"],r["ticker"])),labels


def _score(points):
    if not points:
        return None
    n=len(points)
    brier=sum((p-y)**2 for p,y,_,_ in points)/n
    loss=-sum(y*math.log(max(EPS,p))+(1-y)*math.log(max(EPS,1-p)) for p,y,_,_ in points)/n
    correct=sum((p >= .5)==bool(y) for p,y,_,_ in points)
    bins=[]
    ece=0.0
    for lower in (0,.2,.4,.6,.8):
        subset=[(p,y) for p,y,_,_ in points if lower<=p < lower+.2 or lower==.8 and p==1]
        if subset:
            confidence=sum(p for p,_ in subset)/len(subset)
            observed=sum(y for _,y in subset)/len(subset)
            ece+=abs(confidence-observed)*len(subset)/n
            bins.append({"from":lower,"to":round(lower+.2,1),"n":len(subset),
                         "mean_predicted":round(confidence,5),"observed":round(observed,5)})
    return {"n":n, "brier":round(brier,6), "logloss":round(loss,6),
            "directional_accuracy":round(correct/n,6), "ece_5_bin":round(ece,6),
            "calibration":bins}


def evaluate(observations, labels, min_train_contracts=30, folds=4,
             use_xgboost=True):
    """Expanding chronological contract-level holdouts, strict settlement-time cutoff.

    All checkpoint rows from a contract stay inside one fold. Training only uses
    labels actually known before the earliest test observation of that fold.
    """
    if min_train_contracts < 10:
        raise ReplayError("Minimum train size is 10 contracts")
    settled={r["ticker"] for r in observations if r["ticker"] in labels}
    order=sorted(settled,key=lambda t:(labels[t]["expires_ts"],t))
    if len(order) <= min_train_contracts:
        return {"status":"INSUFFICIENT_REAL_HISTORY","contracts":len(order),
                "min_train_contracts":min_train_contracts,"scores":[],
                "note":"No out-of-sample accuracy may be claimed."}
    remaining=order[min_train_contracts:]
    chunk=max(1, math.ceil(len(remaining)/max(1,folds)))
    observations_by_ticker=defaultdict(list)
    for row in observations:
        observations_by_ticker[row["ticker"]].append(row)
    scored=defaultdict(list)
    statuses={}
    for start in range(0,len(remaining),chunk):
        batch=remaining[start:start+chunk]
        testing=[r for t in batch for r in observations_by_ticker[t]]
        cutoff=min(r["ts"] for r in testing)
        before=[r for t in order[:min_train_contracts+start]
                for r in observations_by_ticker[t] if r["ts"] < cutoff]
        # The cutoff uses actual label availability, NOT just the earlier contract's close.
        logistic=fit_independent_logistic(before,labels,cutoff)
        xgb, reason=(fit_spot_xgboost(before,labels,cutoff) if use_xgboost
                     else (None,"Optional XGBoost explicitly disabled"))
        if xgb is None:
            statuses["siddha_spot_xgboost"]=reason
        if logistic is None:
            statuses["kalshibot_independent_logistic"]="Insufficient prior official labels"
        for row in testing:
            y=int(labels[row["ticker"]]["result"]=="yes")
            cp=row["checkpoint"]
            market={"target":row["target"],"seconds_left":row["seconds_left"],
                    "market_mid":row["market_mid"]}
            axiom=engine_pack(row["spot"],market,row["candles"])
            for engine in axiom["engines"] + [axiom]:
                name=engine.get("name","ensemble")
                p=engine.get("prob_above") if engine.get("available") else None
                if name not in INDEPENDENT or p is None:
                    continue
                scored[(name,cp)].append((p,y,row["ticker"],row["seconds_left"]))
            scored[("settlement_zero_drift",cp)].append(
                (zero_drift(row),y,row["ticker"],row["seconds_left"]))
            if logistic is not None:
                scored[("kalshibot_independent_logistic",cp)].append(
                    (logistic_predict(logistic,row),y,row["ticker"],row["seconds_left"]))
            if xgb is not None:
                score=float(xgb.predict_proba([[inputs(row)[k] for k in FEATURES]])[0][1])
                scored[("siddha_spot_xgboost",cp)].append(
                    (score,y,row["ticker"],row["seconds_left"]))
            if row["market_mid"] is not None:
                scored[(BENCHMARK,cp)].append(
                    (row["market_mid"],y,row["ticker"],row["seconds_left"]))
    result=[]
    for (name,cp),pts in sorted(scored.items()):
        result.append({"model":name,"checkpoint":cp,"category":
                      "market_price_benchmark" if name==BENCHMARK else "independent_btc",
                       **_score(pts)})
    leads=[]
    for name in INDEPENDENT:
        by=defaultdict(list)
        for (model,cp),pts in scored.items():
            if model==name:
                for p,y,t,remain in pts:
                    by[t].append((remain,p,y))
        calls=[]
        for ticker,ps in by.items():
            early=sorted(ps,reverse=True)  # earliest checkpoint / most remaining first
            selected=next(((remain,p,y) for remain,p,y in early if p>=.60 or p<=.40),None)
            if selected:
                remain,p,y=selected
                calls.append((remain,int((p>=.5)==bool(y))))
        if by:
            leads.append({"model":name,"contracts_evaluated":len(by),
                          "first_confident_calls":len(calls),
                          "call_coverage":round(len(calls)/len(by),5),
                          "first_call_accuracy":round(sum(c for _,c in calls)/len(calls),5) if calls else None,
                          "mean_seconds_before_expiry":round(statistics.mean(s for s,_ in calls),1) if calls else None})
    return {"status":"RESEARCH_ONLY_UNVALIDATED", "train_contract_floor":min_train_contracts,
            "out_of_sample_contracts":len(remaining),"folds":math.ceil(len(remaining)/chunk),
            "official_contracts_total":len(order),"scores":result,"lead_time":leads,
            "unavailable_models":statuses,
            "note":"Descriptive out-of-sample scoring only. No significance, economic edge, or early-move foresight established. Coinbase is a BRTI proxy, not its settlement index."}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations",required=True,help="Point-in-time BTC checkpoint JSONL")
    parser.add_argument("--settlements",required=True,help="Separate official Kalshi result JSONL")
    parser.add_argument("--output",required=True,help="Local JSON report path (not trading ledger)")
    parser.add_argument("--allow-synthetic",action="store_true",help="Explicitly permit synthetic test labels")
    parser.add_argument("--min-train-contracts",type=int,default=30)
    parser.add_argument("--skip-xgboost",action="store_true")
    args=parser.parse_args()
    obs,labels=load_data(args.observations,args.settlements,args.allow_synthetic)
    results=evaluate(obs,labels,args.min_train_contracts,use_xgboost=not args.skip_xgboost)
    results["data_mode"]="SYNTHETIC_ALLOWED_NOT_REAL_PERFORMANCE" if args.allow_synthetic else "OFFICIAL_LABEL_REQUIRED"
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(results,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"status":results["status"],"output":str(path),
                      "out_of_sample_contracts":results.get("out_of_sample_contracts",0)}))


if __name__ == "__main__":
    main()
