"""Fitted residual gradient-boosted model for BTC settlement-price direction.

Model artifact was fitted on 180 days of genuine CF Benchmarks BRTI
first-tick-per-second 1m price bars. Synthetic volatility-scaled strikes avoid
retrospectively assuming Kalshi floors were published as of prediction time.
Training labels use the final minute's BRTI first-second-tick average. The model
learns residuals from a normal-volatility reference with gradient-boosted
regression trees. It is experimental; no claim of money-making alpha.

Inference uses only Python standard-library modules on Oracle.
"""
from __future__ import annotations
import base64
import functools
import json
import math
import statistics
import zlib

from .brti_boosted_artifact import MODEL_B85 as _MODEL_B85

@functools.lru_cache(maxsize=1)
def _model():
    data=json.loads(zlib.decompress(base64.b85decode(_MODEL_B85)))
    if len(data["trees"])!=12 or len(data["features"])!=14:
        raise ValueError("Invalid bundled trained model")
    return data

def _ema(vals,span):
    a=2/(span+1)
    current=vals[0]
    for x in vals[1:]:
        current=current+a*(x-current)
    return current

def _vector(spot,target,hminutes,candles,now):
    if not isinstance(candles,list):return None
    closed=[]
    for bar in candles:
        if not isinstance(bar,dict):return None
        t=bar.get("t")
        if not isinstance(t,(int,float)) or not math.isfinite(t) or t%60:
            return None
        if t+60<=now: closed.append(bar)
    closed=closed[-62:]
    if len(closed)<62 or any(b["t"]-a["t"]!=60 for a,b in zip(closed,closed[1:])):
        return None
    if now-closed[-1]["t"]-60>150:return None
    closes=[float(v["close"]) for v in closed]
    if min(closes)<=0:return None
    returns=[math.log(b/a) for a,b in zip(closes,closes[1:])]
    s15=statistics.stdev(returns[-15:])
    s45=statistics.stdev(returns[-45:])
    if s45<1e-10:return None
    candle=closed[-1]
    c,o,h,l=[float(candle[k]) for k in ("close","open","high","low")]
    if not 0<l<=min(c,o)<=max(c,o)<=h:return None
    # BRTI is a price index, not a trade tape: no volume feature is invented.
    vratio=0.
    # An average over the closing 60s is less uncertain than an endpoint.
    effective_minutes=max(hminutes-2/3,.05)
    z=math.log(spot/target)/(s45*math.sqrt(effective_minutes))
    features=[z,hminutes,
              10000*returns[-1],
              10000*math.log(c/closes[-6]),
              10000*math.log(c/closes[-16]),
              10000*math.log(c/closes[-31]),
              10000*math.log(c/closes[-61]),
              10000*s15,10000*s45,vratio,
              10000*(c-o)/c,
              10000*(h-max(c,o))/c,
              10000*(min(c,o)-l)/c,
              10000*(_ema(closes,9)-_ema(closes,21))/c]
    return features if all(map(math.isfinite,features)) else None

def boosted_forecast(spot,market,candles,now):
    wait={"name":"axiom_gradient_boosted_btc",
          "method":"learned_brti_residual_gradient_boosting_12_tree",
          "available":False,"prob_above":None,"prob_below":None,"side":"WAIT",
          "reason":"Need published strike and 62 completed genuine 1m bars",
          "independent":True,"trained":True,"calibrated":False,
          "training_strikes_are_synthetic":True}
    if not isinstance(market,dict):return wait
    try:
        spot=float(spot);target=float(market["target"])
        minutes=float(market["seconds_left"])/60
        if not all(math.isfinite(x) and x>0 for x in (spot,target,minutes)):
            return wait
        xs=_vector(spot,target,minutes,candles,now)
        if xs is None:return wait
        data=_model()
        baseline=.5*math.erfc(-xs[0]/math.sqrt(2))
        clipped=min(.985,max(.015,baseline))
        score=math.log(clipped/(1-clipped))
        for tree in data["trees"]:
            node=0
            while tree[node][0]!=-2:
                feat,threshold,left,right,_=tree[node]
                node=left if xs[feat]<=threshold else right
            score=max(-8.,min(8.,score+data["learning_rate"]*
                      max(-5.,min(5.,tree[node][4]))))
        p=1/(1+math.exp(-score))
        return {**wait,"available":True,"prob_above":round(p,6),
                "prob_below":round(1-p,6),
                "side":"ABOVE" if p>.5 else "BELOW",
                "reason":"Historically fitted BRTI 60-second-average residual gradient boosting",
                "base_normal_probability":round(baseline,6),
                "trees":len(data["trees"]),
                "out_of_training_strike_range":abs(xs[0])>1.5,
                "labels_are_real_future_brti_60s_means":True,
                "source":"historical_cf_benchmarks_brti_price_only",
                "historical_contract_strikes_synthetic":True}
    except (TypeError,ValueError,OverflowError,ZeroDivisionError,KeyError,IndexError):
        return wait
