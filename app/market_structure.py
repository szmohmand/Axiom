"""Multi-timeframe BTC price and exchange trade-flow forecasting features.

Only real BTC exchange OHLCV and Binance aggressor-signed trades enter model
features. Kalshi quote, depth, bid, ask, midpoint, volume and wall values
must never enter a BTC outcome predictor. Kalshi liquidity belongs exclusively
to separate execution / value / spread / contract-repricing analysis.
"""
from __future__ import annotations

import math


def _num(v):
    if isinstance(v,bool) or v is None:return None
    try:
        n=float(v)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError,OverflowError):return None


def _sig(value):
    """Scale-invariant normalization to +/-1 without a hard confidence cap."""
    return math.tanh(value)


def timeframes(five_minute,now):
    unavailable={"available":False,"reason":"No 30m/1h/2h fully closed Coinbase data",
                 "source":"coinbase_5m_completed","frames":{},"directional_components":{}}
    if not isinstance(five_minute,list) or len(five_minute)<7:return unavailable
    clean=[];last=None
    for row in five_minute:
        if not isinstance(row,dict):return unavailable
        ts=_num(row.get("t"));o=_num(row.get("open"));h=_num(row.get("high"))
        l=_num(row.get("low"));c=_num(row.get("close"))
        raw_volume=row.get("volume");v=_num(raw_volume) if raw_volume is not None else None
        if (None in (ts,o,h,l,c) or ts%300!=0 or ts+300>now or
            (last is not None and ts-last!=300) or not 0<l<=min(o,c)<=max(o,c)<=h or (raw_volume is not None and (v is None or v<0))):
            return unavailable
        clean.append({"t":int(ts),"open":o,"high":h,"low":l,"close":c,"volume":v})
        last=ts
    if now-clean[-1]["t"]-300>600:return unavailable
    output={};signals={}
    for n,label in ((6,"30m"),(12,"1h"),(24,"2h")):
        if len(clean)<n+1:continue
        prior=clean[-n-1];window=clean[-n:]
        close=window[-1]["close"];open_price=window[0]["open"]
        high=max(c["high"] for c in window);low=min(c["low"] for c in window)
        start_close=prior["close"]
        logmove=math.log(close/start_close)
        paths=[math.log(b["close"]/a["close"]) for a,b in zip(clean[-n-1:-1],window)]
        realized=max(math.sqrt(sum(r*r for r in paths)),1e-9)
        # Normalized efficiency: trend strength across its own observed path.
        effort=sum(abs(r) for r in paths)
        efficiency=logmove/effort if effort>0 else 0.
        # End-candle position distinguishes rejection from continuation.
        close_location=2*(close-low)/(high-low)-1 if high>low else 0
        # Two independent features per timeframe: efficiency + close location.
        signals[label+"_efficiency"]=_sig(efficiency*2)
        signals[label+"_close_location"]=_sig(close_location)
        output[label]={
            "open":round(open_price,2),"high":round(high,2),
            "low":round(low,2),"close":round(close,2),
            "return_bps":round(logmove*1e4,4),
            "realized_log_range":round(realized,8),
            "directional_efficiency":round(efficiency,6),
            "close_location":round(close_location,6),
            "fully_closed_source_bars":n,
            "period_start":window[0]["t"],"period_end":window[-1]["t"]+300,
        }
    from_brti=bool(clean) and all(x.get("source")=="cfbenchmarks_brti_authenticated_live"
                                 for x in five_minute)
    return {"available":bool(output),
            "reason":"Completed BRTI 5m price-only bars aggregated into multi-hour structure" if from_brti else "Actual closed 5m OHLCV aggregated into multi-hour structure",
            "source":"cfbenchmarks_brti_authenticated_live" if from_brti else "coinbase_5m_completed",
            "frames":output,"directional_components":signals,
            "last_completed_bar_end":clean[-1]["t"]+300}


class BTCFlowTracker:
    """Forecast adapter is BTC-only.

    The arguments 'book'/'market' are deliberately ignored, even if callers
    supply Kalshi bid/ask/mid/orderbook data. No historical quote state is kept
    or inspected here. This enforces Kalshi's role as an execution venue rather
    than a forecasting oracle.
    """
    def observe(self,book=None,market=None,binance=None,spot=None,now=None):
        result={"available":False,"reason":"No observed Bitcoin trade-flow features",
                "source":"binance_btc_spot_aggtrades_only",
                "directional_components":{},"observations":{},
                "uses_kalshi_quotes_for_prediction":False,
                "uses_kalshi_orderbook_for_prediction":False,
                "whale_wallet_identified":False}
        if isinstance(binance,dict):
            for label,key in (("cvd_2m","btc_taker_cvd_2m"),
                              ("cvd_5m","btc_taker_cvd_5m")):
                row=binance.get(label) or {}
                imbalance=_num(row.get("taker_imbalance"))
                if imbalance is not None and row.get("trades_seen",0)>0:
                    result["directional_components"][key]=_sig(2*imbalance)
                    result["observations"][label]=row
            large=binance.get("large_trade_activity") or {}
            net=_num(large.get("net_taker_usdt"))
            threshold=_num(large.get("large_trade_threshold_usdt"))
            if net is not None and threshold is not None and threshold>0:
                result["directional_components"]["btc_large_aggressive_prints"]=_sig(
                    net/threshold)
                result["observations"]["large_trades"]={
                    "count":large.get("large_print_count"),
                    "proxy_not_wallet_identity":True,
                    "net_taker_usdt":net}
        result.update(available=bool(result["directional_components"]),
                      reason="Real Binance BTC trade-flow signals, never Kalshi contract prices")
        return result

# Compatibility for archived readers; both names refer to BTC-only flow.
DepthFlowTracker=BTCFlowTracker

_BTC_PREDICTIVE_FEATURES=frozenset((
    "30m_efficiency","30m_close_location",
    "1h_efficiency","1h_close_location",
    "2h_efficiency","2h_close_location",
    "btc_taker_cvd_2m","btc_taker_cvd_5m",
    "btc_large_aggressive_prints",
))

def pressure_forecast(spot,market,base_probability,context):
    """Independent market-pressure forecast. Every observed family can vote.

    Equal-family evidence scales as signed sum/sqrt(n): agreeing modalities
    can meaningfully affect predictions; there is NO 1.5%-3.5% rule.
    Underlying strengths are hypotheses, not a fitted ML classifier.
    """
    unavailable={"name":"axiom_multi_signal_context",
       "method":"btc-only-multitimeframe-cvd-aggressive-prints",
       "available":False,"prob_above":None,"prob_below":None,
       "side":"WAIT","reason":"No observed features",
       "independent":False,"trained":False,"calibrated":False}
    if not isinstance(context,dict) or not isinstance(market,dict):
        return unavailable
    if not isinstance(base_probability,(int,float)) or not 0<base_probability<1:
        return unavailable
    families={}
    for name in ("timeframes","microstructure"):
        obj=context.get(name) or {}
        signals=obj.get("directional_components") or {}
        for key,val in signals.items():
            x=_num(val)
            # Harden the boundary against old/stale injected Kalshi features.
            if key in _BTC_PREDICTIVE_FEATURES and x is not None:
                families[key]=x
    if not families:return unavailable
    combined=sum(families.values())/math.sqrt(len(families))
    # Predictive shift is z-score space, preserving original BTC/target
    # distance instead of treating Kalshi YES price as true probability.
    from statistics import NormalDist
    normal=NormalDist()
    z=normal.inv_cdf(min(.999999,max(.000001,base_probability)))
    probability=normal.cdf(z+combined)
    return {**unavailable,"available":True,
            "prob_above":round(max(.000001,min(.999999,probability)),6),
            "prob_below":round(max(.000001,min(.999999,1-probability)),6),
            "side":"ABOVE" if probability>.5 else "BELOW",
            "reason":"Experimental BTC-only OHLCV and actual exchange trade-flow features",
            "components":families,"combined_z_shift":round(combined,6),
            "source_status":{k:(context.get(k) or {}).get("available") for k in ("timeframes","microstructure")},
            "hypotheses_not_validated_alpha":True}
