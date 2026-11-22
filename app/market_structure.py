"""Multi-timeframe and market-microstructure features that genuinely vote.

Coinbase 5-minute OHLCV supplies actual completed 30m/60m/120m candles.
Kalshi orderbook identifies participant quote positioning (NOT authenticated
BTC order flow); Binance signed aggressive trades identify BTC taker flow.
All contributions are exposed to the ensemble, not background-only.
"""
from __future__ import annotations

import math
import statistics
from .orderbook import current_book


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
        l=_num(row.get("low"));c=_num(row.get("close"));v=_num(row.get("volume"))
        if (None in (ts,o,h,l,c,v) or ts%300!=0 or ts+300>now or
            (last is not None and ts-last!=300) or not 0<l<=min(o,c)<=max(o,c)<=h or v<0):
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
    return {"available":bool(output),
            "reason":"Actual closed 5m OHLCV aggregated into multi-hour structure",
            "source":"coinbase_5m_completed",
            "frames":output,"directional_components":signals,
            "last_completed_bar_end":clean[-1]["t"]+300}


class DepthFlowTracker:
    def __init__(self):
        self.last=None

    @staticmethod
    def _top(levels):
        if not levels:return None
        return _num(levels[0].get("price"))

    @staticmethod
    def _levels_value(levels):
        return sum(float(x.get("size") or 0) for x in levels if
                   _num(x.get("price")) is not None and _num(x.get("size")) is not None)

    def observe(self,book,market,binance,spot,now):
        result={"available":False,"reason":"No current Kalshi depth",
                "source":"kalshi_rest_depth_and_binance_trades",
                "directional_components":{},"observations":{},
                "absorption_is_verified":False,"whale_wallet_identified":False}
        if not isinstance(market,dict) or not current_book(book,market.get("ticker"),now):
            self.last=None
            return result
        best=book.get("best") or {};bids=book.get("bids") or {};asks=book.get("asks") or {}
        yi=_num((book.get("book_imbalance_5c")))
        if yi is not None:
            result["directional_components"]["kalshi_near_book_imbalance"]=_sig(2*yi)
        # Kalshi resting order walls on a given outcome, NOT identified BTC market makers.
        yes_wall=max([_num(x.get("size")) or 0 for x in bids.get("YES",[])],default=0)
        no_wall=max([_num(x.get("size")) or 0 for x in bids.get("NO",[])],default=0)
        if yes_wall+no_wall>0:
            result["directional_components"]["kalshi_liquidity_wall_bias"]=_sig(
                math.log((1+yes_wall)/(1+no_wall)))
        ybest=best.get("YES") or {}
        midpoint=None
        if _num(ybest.get("bid")) is not None and _num(ybest.get("ask")) is not None:
            midpoint=(float(ybest["bid"])+float(ybest["ask"]))/2
        snapshot={"ticker":market["ticker"],"ts":float(book["received_at"]),
                  "mid":midpoint,"yes":self._levels_value(bids.get("YES",[])),
                  "no":self._levels_value(bids.get("NO",[])),
                  "spot":_num(spot)}
        prev=self.last
        self.last=snapshot
        if (prev and prev["ticker"]==snapshot["ticker"] and
            0<snapshot["ts"]-prev["ts"]<=120):
            # Positive imbalance in replenishment is a separate feature from
            # static walls, and can reveal shifts within the contract.
            delta_yes=snapshot["yes"]-prev["yes"]
            delta_no=snapshot["no"]-prev["no"]
            norm=(abs(delta_yes)+abs(delta_no))
            if norm>0:
                result["directional_components"]["kalshi_depth_replenishment"]=_sig(
                    (delta_yes-delta_no)/norm*2)
            result["observations"]["kalshi_depth_change"]={
                "yes_contracts":round(delta_yes,3),"no_contracts":round(delta_no,3),
                "seconds_between":round(snapshot["ts"]-prev["ts"],3),
            }
            if (prev["spot"] is not None and snapshot["spot"] is not None and
                prev["spot"]>0):
                result["observations"]["spot_change_bps"]=round(
                    math.log(snapshot["spot"]/prev["spot"])*10000,4)
        if isinstance(binance,dict):
            # Binance @aggTrade includes buyer-is-maker, allowing genuine
            # signed taker volume; no invented Bitcoin CVD from Kalshi quotes.
            for label,key in (("cvd_2m","btc_taker_cvd_2m"),("cvd_5m","btc_taker_cvd_5m")):
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
                    net/max(threshold,1.))
                result["observations"]["large_trades"]={
                    "count":large.get("large_print_count"),
                    "proxy_not_wallet_identity":True,
                    "net_taker_usdt":net}
            funding=_num(binance.get("funding_rate"))
            basis=_num(binance.get("funding_mark_index_basis_bps"))
            if binance.get("funding_status")=="LIVE" and funding is not None:
                # Directional hypothesis (long pressure), NOT a proven
                # economic law. Negative funding can mean squeeze risk.
                result["directional_components"]["btc_perpetual_funding_pressure"]=_sig(
                    math.copysign(math.log1p(abs(funding)*1e4),funding))
                result["observations"]["funding_hypothesis"]="same-direction positioning; contrarian possibility still open"
            if binance.get("funding_status")=="LIVE" and basis is not None:
                result["directional_components"]["btc_perpetual_basis_pressure"]=_sig(basis/10)
        if (prev and snapshot["mid"] is not None and prev["mid"] is not None and
            prev["ticker"]==snapshot["ticker"] and
            abs(snapshot["mid"]-prev["mid"])<.005):
            cvd=_num((binance or {}).get("cvd_2m",{}).get("taker_imbalance"))
            if cvd is not None and abs(cvd)>.25:
                result["observations"]["absorption_proxy"]={
                    "status":"POSSIBLE_KALSHI_QUOTE_STICKINESS_WITH_BTC_TAKER_FLOW",
                    "not_verified_btc_l2_absorption":True,
                    "direction":"BUY" if cvd>0 else "SELL",
                    "quote_change":round(snapshot["mid"]-prev["mid"],5)}
                # Detecting lack of Kalshi quote adjustment after signed BTC
                # flow is useful as a repricing signal, not proof of a wall fill.
                result["directional_components"]["btc_vs_kalshi_quote_absorption_proxy"]=_sig(cvd*2)
        result.update(available=bool(result["directional_components"]),
                      reason="Observed Coinbase/Binance/Kalshi context with explicit provenance",
                      observations={**result["observations"],
                        "kalshi_best_yes_bid":_num(ybest.get("bid")),
                        "kalshi_best_yes_ask":_num(ybest.get("ask")),
                        "kalshi_resting_wall_yes":yes_wall,
                        "kalshi_resting_wall_no":no_wall})
        return result


def pressure_forecast(spot,market,base_probability,context):
    """Independent market-pressure forecast. Every observed family can vote.

    Equal-family evidence scales as signed sum/sqrt(n): agreeing modalities
    can meaningfully affect predictions; there is NO 1.5%-3.5% rule.
    Underlying strengths are hypotheses, not a fitted ML classifier.
    """
    unavailable={"name":"axiom_multi_signal_context",
       "method":"multi-timeframe-orderflow-cvd-funding-walls-largeprints",
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
            if x is not None:
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
            "reason":"Experimental independent BTC market features add measurable forecast influence",
            "components":families,"combined_z_shift":round(combined,6),
            "source_status":{k:(context.get(k) or {}).get("available") for k in ("timeframes","microstructure")},
            "hypotheses_not_validated_alpha":True}
