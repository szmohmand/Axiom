"""Whole-book Nison candlestick methodology: independent, read-only shadow.

Original rule implementation informed by Steve Nison, Japanese Candlestick
Charting Techniques (2nd ed., 2001), Chapters 3-17. Not a reproduction of the
book, certified implementation of Nison's proprietary judgment, trained model,
or proof of predictive edge.

The scanner reports literal candle formations, Western convergence, and
non-automatable/absent information. The separate Kalshi-direction mapping is
an explicitly AXIOM-designed experiment, NOT a rule from the book.
"""
from __future__ import annotations

import math
import statistics
from typing import Any
from .nison_structures import scan_structural_formations

_MIN = 31
_MAX_AGE = 125

# These are AXIOM experimental weights, NOT numbers or measured win rates
# attributed to Nison. Competing same-direction patterns are capped.
_WEIGHTS = {
    "HAMMER": 0.8, "HANGING_MAN": -0.5,
    "BULLISH_ENGULFING": 1.0, "BEARISH_ENGULFING": -1.0,
    "DARK_CLOUD_COVER": -0.9, "PIERCING_PATTERN": 0.9,
    "MORNING_STAR": 1.1, "EVENING_STAR": -1.1,
    "MORNING_DOJI_STAR": 1.2, "EVENING_DOJI_STAR": -1.2,
    "SHOOTING_STAR": -0.8, "INVERTED_HAMMER": 0.5,
    "BULLISH_HARAMI": 0.5, "BEARISH_HARAMI": -0.5,
    "BULLISH_HARAMI_CROSS": 0.6, "BEARISH_HARAMI_CROSS": -0.6,
    "TWEEZERS_BOTTOM": 0.35, "TWEEZERS_TOP": -0.35,
    "BULLISH_BELT_HOLD": 0.35, "BEARISH_BELT_HOLD": -0.35,
    "THREE_BLACK_CROWS": -0.95, "THREE_WHITE_SOLDIERS": 0.95,
    "BULLISH_COUNTERATTACK": 0.35, "BEARISH_COUNTERATTACK": -0.35,
    "RISING_THREE_METHODS": 0.9, "FALLING_THREE_METHODS": -0.9,
    "BULLISH_SEPARATING_LINES": 0.35, "BEARISH_SEPARATING_LINES": -0.35,
    "RISING_WINDOW": 0.5, "FALLING_WINDOW": -0.5,
    "UPSIDE_TASUKI_GAP": 0.6, "DOWNSIDE_TASUKI_GAP": -0.6,
    "HIGH_PRICE_GAPPING_PLAY": 0.65, "LOW_PRICE_GAPPING_PLAY": -0.65,
    "UPSIDE_GAP_TWO_CROWS": -0.7,
    "BULLISH_GAPPING_SIDE_BY_SIDE": 0.4,
    "BEARISH_GAPPING_SIDE_BY_SIDE": -0.4,
    "DRAGONFLY_DOJI": 0.2, "GRAVESTONE_DOJI": -0.2,
    "TRISTAR_BOTTOM": 0.6, "TRISTAR_TOP": -0.6,
    "SPRING": 0.8, "UPTHRUST": -0.8,
    "BOX_BREAKOUT_UP": 0.6, "BOX_BREAKOUT_DOWN": -0.6,
    "BULL_FLAG_BREAKOUT": 0.5, "BEAR_FLAG_BREAKOUT": -0.5,
    "BULL_PENNANT_BREAKOUT": 0.5, "BEAR_PENNANT_BREAKOUT": -0.5,
    "POLARITY_SUPPORT_RETEST": 0.5, "POLARITY_RESISTANCE_RETEST": -0.5,
    "BULLISH_CONFIRMATION": 0.35, "BEARISH_CONFIRMATION": -0.35,
}

_COVERAGE = {
    "3": "Implemented OHLC construction, bodies, shadows, doji and spinning tops",
    "4": "Implemented umbrellas, engulfing, dark-cloud cover, piercing",
    "5": "Implemented morning/evening (doji) stars and star-related candles; abandoned baby needs true price gaps",
    "6": "Implemented harami/cross, tweezers, belt-hold, counterattack, crows, soldiers, gap crows; conservative three-mountain/river/Buddha/dumpling/frypan/tower geometric proxies disclosed as judgmental",
    "7": "Implemented real windows, tasuki gap, side-by-side gap, three methods, separating lines, high/low-price gapping plays",
    "8": "Implemented doji, long-legged/rickshaw, dragonfly, gravestone and tri-star",
    "9": "Implemented preexisting trend, market context and conflicting-warning classification",
    "10": "Implemented repeated-high/low support/resistance cluster evidence",
    "11": "Implemented least-squares trend-line context, springs/upthrusts, polarity retests",
    "12": "Implemented 38.2%, 50%, 61.8% retracement context, not trade commands",
    "13": "Implemented SMA, WMA and EMA alignment",
    "14": "Implemented RSI, stochastic, MACD histogram and divergence checks",
    "15": "Implemented volume spike and prior-volume context; no invented order flow",
    "16": "Implemented box breakouts and bounded geometric flag/pennant screens; measured target is descriptive only",
    "17": "Implemented convergence with support/resistance, trend, volume, retracements and oscillators; experimental scoring separate from Nison's text",
}

def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean is not numeric")
    n=float(value)
    if not math.isfinite(n):
        raise ValueError("Nonfinite numeric")
    return n

def _avg(vals):
    return sum(vals)/len(vals) if vals else 0.0

def _ema(vals, n):
    if not vals: return None
    k=2/(n+1)
    result=vals[0]
    for x in vals[1:]:
        result+=k*(x-result)
    return result

def _rsi(closes, period=14):
    if len(closes)<period+1: return None
    changes=[b-a for a,b in zip(closes[-period-1:-1],closes[-period:])]
    gain=sum(max(d,0) for d in changes)/period
    loss=sum(max(-d,0) for d in changes)/period
    return 100 if loss==0 else 100-100/(1+gain/loss)

def _stochastic(bars, period=14):
    if len(bars)<period: return None
    b=bars[-period:]
    high=max(c["high"] for c in b); low=min(c["low"] for c in b)
    return 50 if high==low else 100*(bars[-1]["close"]-low)/(high-low)

def _linreg(vals):
    n=len(vals)
    if n<3:return None
    xbar=(n-1)/2; ybar=_avg(vals)
    den=sum((i-xbar)**2 for i in range(n))
    return sum((i-xbar)*(v-ybar) for i,v in enumerate(vals))/den

def _shape(bar):
    body=abs(bar["close"]-bar["open"])
    span=bar["high"]-bar["low"]
    upper=bar["high"]-max(bar["open"],bar["close"])
    lower=min(bar["open"],bar["close"])-bar["low"]
    return {"body":body,"span":span,
            "fraction":body/span if span else 0,
            "upper":upper,"lower":lower,
            "up_frac":upper/span if span else 0,
            "low_frac":lower/span if span else 0,
            "close_pos":(bar["close"]-bar["low"])/span if span else .5,
            "up":bar["close"]>bar["open"],
            "down":bar["close"]<bar["open"],
            "doji":body<=max(0.1*span,0.0),
            "small":body<=0.3*span,
            "long":body>=0.60*span}

def _trend(bars, lookback=9):
    if len(bars)<lookback+1:return "UNKNOWN"
    a=bars[-lookback]["close"]
    b=bars[-1]["close"]
    ranges=[x["high"]-x["low"] for x in bars[-lookback:]]
    atr=max(_avg(ranges),1e-9)
    change=b-a
    if change>1.0*atr:return "UP"
    if change< -1.0*atr:return "DOWN"
    return "RANGE"

def _validated(candles,now):
    now=_number(now)
    if not isinstance(candles,list):
        raise ValueError("Missing list of one-minute candles")
    bars=[]
    last=None
    for row in candles:
        if not isinstance(row,dict):
            raise ValueError("Invalid candle")
        t=_number(row["t"])
        o=_number(row["open"]);h=_number(row["high"])
        l=_number(row["low"]);c=_number(row["close"])
        v=None if row.get("volume") is None else _number(row["volume"])
        if t%60 or (last is not None and t-last!=60):
            raise ValueError("Candles must be consecutive UTC minutes")
        last=t
        if t>now+60:
            raise ValueError("Future candle timestamp")
        if l<=0 or not l<=min(o,c)<=max(o,c)<=h or (v is not None and v<0):
            raise ValueError("Invalid OHLCV range")
        if t+60<=now:
            bars.append({"t":int(t),"open":o,"high":h,"low":l,"close":c,"volume":v})
    if len(bars)<_MIN:
        raise ValueError("Need 31 fully completed one-minute bars")
    if now-bars[-1]["t"]-60>_MAX_AGE:
        raise ValueError("Stale candle data")
    return bars[-240:]

def _bar_gap(a,b):
    return "UP" if b["low"]>a["high"] else "DOWN" if b["high"]<a["low"] else None

def _append(evidence,name,chapter,**details):
    evidence.append({"name":name,"chapter":chapter,"bias":("UP" if _WEIGHTS.get(name,0)>0
                    else "DOWN" if _WEIGHTS.get(name,0)<0 else "NEUTRAL"),
                    "experimental_weight":_WEIGHTS.get(name,0.0),
                    "details":details})

def scan_nison(candles:list[dict],now:float)->dict:
    """Non-voting candle-methodology report using only completed market data."""
    result={"available":False,"status":"UNAVAILABLE","independent":True,
            "research_only":True,"votes_in_ensemble":False,
            "can_trigger_paper_or_orders":False,
            "book_chapters":_COVERAGE,"pattern_evidence":[],
            "western_context":{},"convergence":{},"reason":None}
    try:
        b=_validated(candles,now)
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        result["reason"]=str(exc);return result
    a=[_shape(x) for x in b]
    current,prev=b[-1],b[-2]
    cur,pr=a[-1],a[-2]
    closes=[z["close"] for z in b]
    atr=_avg([max(x["high"]-x["low"],abs(x["high"]-p["close"]),
                  abs(x["low"]-p["close"]))
              for p,x in zip(b[-15:-1],b[-14:])])
    atr=max(atr,1e-9)
    trend1=_trend(b[:-1]);trend2=_trend(b[:-2])
    tol=max(atr*.12, current["close"]*.000001)
    prior20=b[-21:-1]
    support=min(x["low"] for x in prior20)
    resistance=max(x["high"] for x in prior20)
    volumes=[x["volume"] for x in b[-21:-1]]
    if all(x is not None for x in volumes) and current["volume"] is not None:
        median_vol=statistics.median(volumes)
        relative_volume=current["volume"]/median_vol if median_vol>0 else None
    else:relative_volume=None
    high_volume=relative_volume is not None and relative_volume>=1.5
    patterns=[]
    # Ch 4: the trend BEFORE a pattern must be in place, not created by it.
    umbrella=cur["low_frac"]>=.55 and cur["lower"]>=2*max(cur["body"],1e-8) and cur["up_frac"]<=.15
    upper=cur["up_frac"]>=.55 and cur["upper"]>=2*max(cur["body"],1e-8) and cur["low_frac"]<=.15
    if umbrella and trend1=="DOWN":_append(patterns,"HAMMER",4,requires_follow_through=True)
    if umbrella and trend1=="UP":_append(patterns,"HANGING_MAN",4,requires_bearish_confirmation=True)
    if upper and trend1=="UP":_append(patterns,"SHOOTING_STAR",5,requires_follow_through=True)
    if upper and trend1=="DOWN":_append(patterns,"INVERTED_HAMMER",5,requires_bullish_confirmation=True)
    bull_engulf=(pr["down"] and cur["up"] and current["open"]<=prev["close"]
                 and current["close"]>=prev["open"] and cur["body"]>pr["body"])
    bear_engulf=(pr["up"] and cur["down"] and current["open"]>=prev["close"]
                 and current["close"]<=prev["open"] and cur["body"]>pr["body"])
    if bull_engulf and trend2=="DOWN":_append(patterns,"BULLISH_ENGULFING",4)
    if bear_engulf and trend2=="UP":_append(patterns,"BEARISH_ENGULFING",4)
    # Strict opening gap vs previous extremum: no fake gaps on continuous BTC.
    if (trend2=="UP" and pr["up"] and cur["down"] and
        current["open"]>prev["high"] and current["close"]<
        (prev["open"]+prev["close"])/2 and current["close"]>prev["open"]):
        _append(patterns,"DARK_CLOUD_COVER",4,strict_opening_gap=True)
    if (trend2=="DOWN" and pr["down"] and cur["up"] and
        current["open"]<prev["low"] and current["close"]>
        (prev["open"]+prev["close"])/2 and current["close"]<prev["open"]):
        _append(patterns,"PIERCING_PATTERN",4,strict_opening_gap=True)
    # Ch 5: Nison discusses flexible middle/last-body gaps on intraday stars,
    # but NOT rewriting strict abandoned-baby shadow gaps as arbitrary overlap.
    if len(b)>=3:
        x,y,z=b[-3:];ax,ay,az=a[-3:]
        earlier=_trend(b[:-3])
        if (earlier=="DOWN" and ax["down"] and ax["long"] and ay["small"]
            and az["up"] and az["long"]
            and z["close"]>(x["open"]+x["close"])/2):
            nm="MORNING_DOJI_STAR" if ay["doji"] else "MORNING_STAR"
            _append(patterns,nm,5,intraday_body_gap_optional=True,
                    ideal_middle_body_gap=max(y["open"],y["close"])<min(x["open"],x["close"]))
        if (earlier=="UP" and ax["up"] and ax["long"] and ay["small"]
            and az["down"] and az["long"]
            and z["close"]<(x["open"]+x["close"])/2):
            nm="EVENING_DOJI_STAR" if ay["doji"] else "EVENING_STAR"
            _append(patterns,nm,5,intraday_body_gap_optional=True,
                    ideal_middle_body_gap=min(y["open"],y["close"])>max(x["open"],x["close"]))
        if ax["doji"] and ay["doji"] and az["doji"]:
            if earlier=="DOWN" and y["low"]<min(x["low"],z["low"]):
                _append(patterns,"TRISTAR_BOTTOM",8,confirmed_gaps=False)
            if earlier=="UP" and y["high"]>max(x["high"],z["high"]):
                _append(patterns,"TRISTAR_TOP",8,confirmed_gaps=False)
        if earlier=="UP" and all(v["down"] and v["close_pos"]<=.25
                 for v in a[-3:]) and x["close"]>y["close"]>z["close"]:
            _append(patterns,"THREE_BLACK_CROWS",6)
        if earlier=="DOWN" and all(v["up"] and v["close_pos"]>=.75
                 for v in a[-3:]) and x["close"]<y["close"]<z["close"]:
            _append(patterns,"THREE_WHITE_SOLDIERS",6)
        # Upside gap two crows: two falling-colored bodies in a genuine
        # gap above prior white body, second crow engulfs first body.
        if (earlier=="UP" and ax["up"] and ay["down"] and az["down"] and
            y["low"]>x["high"] and z["open"]>y["open"] and
            z["close"]<y["close"] and z["close"]>x["high"]):
            _append(patterns,"UPSIDE_GAP_TWO_CROWS",6,strict_gaps=True)
    # Ch 6: "contained real body", not shadow-only harami.
    if pr["long"] and cur["small"] and min(current["open"],current["close"])>=min(prev["open"],prev["close"]) and max(current["open"],current["close"])<=max(prev["open"],prev["close"]):
        if trend2=="DOWN" and pr["down"]:
            _append(patterns,"BULLISH_HARAMI_CROSS" if cur["doji"] else "BULLISH_HARAMI",6)
        if trend2=="UP" and pr["up"]:
            _append(patterns,"BEARISH_HARAMI_CROSS" if cur["doji"] else "BEARISH_HARAMI",6)
    if abs(current["low"]-prev["low"])<=tol and trend2=="DOWN":
        _append(patterns,"TWEEZERS_BOTTOM",6,tolerance_usd=round(tol,4))
    if abs(current["high"]-prev["high"])<=tol and trend2=="UP":
        _append(patterns,"TWEEZERS_TOP",6,tolerance_usd=round(tol,4))
    if trend1=="DOWN" and cur["up"] and cur["long"] and cur["low_frac"]<=.06:
        _append(patterns,"BULLISH_BELT_HOLD",6)
    if trend1=="UP" and cur["down"] and cur["long"] and cur["up_frac"]<=.06:
        _append(patterns,"BEARISH_BELT_HOLD",6)
    if trend2=="DOWN" and pr["down"] and cur["up"] and current["open"]<prev["low"] and abs(current["close"]-prev["close"])<=tol:
        _append(patterns,"BULLISH_COUNTERATTACK",6,strict_opening_gap=True)
    if trend2=="UP" and pr["up"] and cur["down"] and current["open"]>prev["high"] and abs(current["close"]-prev["close"])<=tol:
        _append(patterns,"BEARISH_COUNTERATTACK",6,strict_opening_gap=True)
    # Ch 7 strict windows (nonoverlapping complete shadows).
    gap=_bar_gap(prev,current)
    if gap=="UP":_append(patterns,"RISING_WINDOW",7,window_floor=prev["high"])
    if gap=="DOWN":_append(patterns,"FALLING_WINDOW",7,window_ceiling=prev["low"])
    if trend2=="UP" and pr["down"] and cur["up"] and abs(current["open"]-prev["open"])<=tol:
        _append(patterns,"BULLISH_SEPARATING_LINES",7)
    if trend2=="DOWN" and pr["up"] and cur["down"] and abs(current["open"]-prev["open"])<=tol:
        _append(patterns,"BEARISH_SEPARATING_LINES",7)
    if len(b)>=3:
        x,y,z=b[-3:]
        if (_bar_gap(x,y)=="UP" and z["close"]<z["open"] and
            z["close"]<y["low"] and z["close"]>x["high"]):
            _append(patterns,"UPSIDE_TASUKI_GAP",7,strict_gap=True)
        if (_bar_gap(x,y)=="DOWN" and z["close"]>z["open"] and
            z["close"]>y["high"] and z["close"]<x["low"]):
            _append(patterns,"DOWNSIDE_TASUKI_GAP",7,strict_gap=True)
        if (_bar_gap(x,y)=="UP" and _bar_gap(x,z)=="UP" and
            a[-2]["up"] and cur["up"] and abs(y["open"]-z["open"])<=tol):
            _append(patterns,"BULLISH_GAPPING_SIDE_BY_SIDE",7)
        if (_bar_gap(x,y)=="DOWN" and _bar_gap(x,z)=="DOWN" and
            a[-2]["up"] and cur["up"] and abs(y["open"]-z["open"])<=tol):
            _append(patterns,"BEARISH_GAPPING_SIDE_BY_SIDE",7)
    if len(b)>=5:
        for inner in (2,3,4):
            if len(b)<inner+2:continue
            first=b[-(inner+2)];middle=b[-(inner+1):-1]
            fshape=_shape(first)
            if (fshape["up"] and fshape["long"] and cur["up"] and cur["long"]
                and current["close"]>first["close"] and
                all(first["low"]<=p["low"] and p["high"]<=first["high"] and
                    _shape(p)["small"] for p in middle)):
                _append(patterns,"RISING_THREE_METHODS",7,inner_candles=inner);break
            if (fshape["down"] and fshape["long"] and cur["down"] and cur["long"]
                and current["close"]<first["close"] and
                all(first["low"]<=p["low"] and p["high"]<=first["high"] and
                    _shape(p)["small"] for p in middle)):
                _append(patterns,"FALLING_THREE_METHODS",7,inner_candles=inner);break
    if len(b)>=6:
        start=b[-6]
        mid=b[-5:-1]
        if (_shape(start)["long"] and _shape(start)["up"] and
            all(_shape(x)["small"] for x in mid) and
            max(x["high"] for x in mid)<=start["high"]+atr*.4 and
            gap=="UP"):
            _append(patterns,"HIGH_PRICE_GAPPING_PLAY",7)
        if (_shape(start)["long"] and _shape(start)["down"] and
            all(_shape(x)["small"] for x in mid) and
            min(x["low"] for x in mid)>=start["low"]-atr*.4 and
            gap=="DOWN"):
            _append(patterns,"LOW_PRICE_GAPPING_PLAY",7)
    # Ch 8: doji types: neutral until evidence of directional confirmation.
    if cur["doji"]:
        _append(patterns,"DOJI_IN_TREND" if trend1!="RANGE" else "DOJI_IN_RANGE",8)
        if cur["low_frac"]>=.6 and cur["up_frac"]<=.1:
            _append(patterns,"DRAGONFLY_DOJI",8)
        if cur["up_frac"]>=.6 and cur["low_frac"]<=.1:
            _append(patterns,"GRAVESTONE_DOJI",8)
        if cur["up_frac"]>=.25 and cur["low_frac"]>=.25:
            _append(patterns,"LONG_LEGGED_DOJI",8)
    elif cur["small"]:
        _append(patterns,"SPINNING_TOP",3)
    # Completed next-candle confirmation of the preceding completed candle.
    if len(b)>=3:
        prior_trend=_trend(b[:-2])
        if (prior_trend=="DOWN" and _shape(prev)["low_frac"]>=.55 and
            current["close"]>prev["high"] and cur["up"]):
            _append(patterns,"BULLISH_CONFIRMATION",9,after="previous_rejection")
        if (prior_trend=="UP" and _shape(prev)["up_frac"]>=.55 and
            current["close"]<prev["low"] and cur["down"]):
            _append(patterns,"BEARISH_CONFIRMATION",9,after="previous_rejection")
    # Ch 6 longer geometric structures, after confirmed pivots and strict windows.
    patterns.extend(scan_structural_formations(b,atr))
    # Ch 10 repeated rejection levels, based on strictly PRIOR candles only.
    history=b[-51:-1]
    bottom_touches=sum(abs(x["low"]-support)<=tol for x in prior20)
    top_touches=sum(abs(x["high"]-resistance)<=tol for x in prior20)
    near_sup=abs(current["low"]-support)<=max(atr*.5,tol)
    near_res=abs(current["high"]-resistance)<=max(atr*.5,tol)
    # Ch 11 Wyckoff-derived spring and upthrust with genuine past level.
    if (current["low"]<support-.15*atr and current["close"]>support+.10*atr and
        trend1 in ("DOWN","RANGE")):
        _append(patterns,"SPRING",11,reclaimed_prior_support=True)
    if (current["high"]>resistance+.15*atr and current["close"]<resistance-.10*atr and
        trend1 in ("UP","RANGE")):
        _append(patterns,"UPTHRUST",11,rejected_prior_resistance=True)
    # Polarity: an earlier range high is broken before this candle; retest now.
    if len(b)>=42:
        old=b[-42:-21]
        old_hi=max(x["high"] for x in old)
        old_lo=min(x["low"] for x in old)
        if (max(x["close"] for x in b[-20:-1])>old_hi+tol and
            abs(current["low"]-old_hi)<=atr*.4 and current["close"]>old_hi):
            _append(patterns,"POLARITY_SUPPORT_RETEST",11)
        if (min(x["close"] for x in b[-20:-1])<old_lo-tol and
            abs(current["high"]-old_lo)<=atr*.4 and current["close"]<old_lo):
            _append(patterns,"POLARITY_RESISTANCE_RETEST",11)
    # Ch 16 box breakout with close, not just a wick.
    if (trend1=="RANGE" and high_volume and cur["fraction"]>=.55
        and current["close"]>resistance+.15*atr and cur["close_pos"]>=.75):
        _append(patterns,"BOX_BREAKOUT_UP",16,box_height_usd=round(resistance-support,3),
                measured_target_usd=round(current["close"]+(resistance-support),2))
    if (trend1=="RANGE" and high_volume and cur["fraction"]>=.55
        and current["close"]<support-.15*atr and cur["close_pos"]<=.25):
        _append(patterns,"BOX_BREAKOUT_DOWN",16,box_height_usd=round(resistance-support,3),
                measured_target_usd=round(current["close"]-(resistance-support),2))
    if len(b)>=15:
        impulse=b[-15:-8]
        pause=b[-8:-1]
        initial=impulse[-1]["close"]-impulse[0]["open"]
        pause_span=max(x["high"] for x in pause)-min(x["low"] for x in pause)
        if abs(initial)>=3*atr and pause_span<=.75*abs(initial):
            slope_high=_linreg([x["high"] for x in pause])
            slope_low=_linreg([x["low"] for x in pause])
            if initial>0 and current["close"]>max(x["high"] for x in pause)+tol:
                nm="BULL_PENNANT_BREAKOUT" if (slope_high is not None and
                    slope_low is not None and slope_high<0<slope_low) else "BULL_FLAG_BREAKOUT"
                _append(patterns,nm,16,measured_move_projection_usd=round(current["close"]+abs(initial),2))
            elif initial<0 and current["close"]<min(x["low"] for x in pause)-tol:
                nm="BEAR_PENNANT_BREAKOUT" if (slope_high is not None and
                    slope_low is not None and slope_high<0<slope_low) else "BEAR_FLAG_BREAKOUT"
                _append(patterns,nm,16,measured_move_projection_usd=round(current["close"]-abs(initial),2))
    # Ch 12 retracements: window of historical price extents; reference only.
    high30=max(x["high"] for x in b[-31:-1])
    low30=min(x["low"] for x in b[-31:-1])
    height=high30-low30
    retracements={"38.2pct":low30+.382*height,
                  "50pct":low30+.5*height,
                  "61.8pct":low30+.618*height}
    nearest_retrace=min(retracements,key=lambda k:abs(current["close"]-retracements[k]))
    retrace_near=abs(current["close"]-retracements[nearest_retrace])<=atr*.5
    # Ch 13: distinct SMA, WMA, EMA; don't invent nonexistent 200-bar MA.
    sma9=_avg(closes[-9:])
    sma21=_avg(closes[-21:])
    wma21=sum(i*c for i,c in enumerate(closes[-21:],1))/sum(range(1,22))
    ema9=_ema(closes[-50:],9)
    ema21=_ema(closes[-50:],21)
    ema50=_ema(closes[-50:],50) if len(closes)>=50 else None
    # Ch 14 oscillators: explicitly defined periods.
    rsi=_rsi(closes)
    stochastic=_stochastic(b)
    fast=_ema(closes,12);slow=_ema(closes,26)
    macd=(fast-slow) if fast is not None and slow is not None else None
    macd_line=[_ema(closes[:j],12)-_ema(closes[:j],26)
               for j in range(max(1,len(closes)-30),len(closes)+1)]
    macd_signal=_ema(macd_line,9)
    macd_hist=macd-macd_signal if macd is not None else None
    # A small fixed-span divergence diagnostic; not claimed to be pivot-confirmed.
    rsi_prev=_rsi(closes[:-5])
    price_delta=closes[-1]-closes[-6]
    oscillator_divergence=("BULLISH_WARNING" if price_delta<0 and
        rsi is not None and rsi_prev is not None and rsi>rsi_prev+3 else
        "BEARISH_WARNING" if price_delta>0 and rsi is not None and
        rsi_prev is not None and rsi<rsi_prev-3 else "NONE")
    slope=_linreg(closes[-20:-1])
    trendline_projection=(closes[-2]+slope) if slope is not None else None
    technical={
        "prior_trend":trend1,"trendline_slope_usd_per_min":slope,
        "trendline_projection_usd":trendline_projection,
        "prior_support_usd":support,"prior_resistance_usd":resistance,
        "support_cluster_touches":bottom_touches,
        "resistance_cluster_touches":top_touches,
        "near_prior_support":near_sup,"near_prior_resistance":near_res,
        "atr_14_usd":atr,"relative_volume":relative_volume,
        "high_relative_volume":high_volume,
        "retracement_levels":retracements,
        "near_retracement":retrace_near,
        "nearest_retracement":nearest_retrace,
        "sma_9":sma9,"sma_21":sma21,"wma_21":wma21,
        "ema_9":ema9,"ema_21":ema21,"ema_50":ema50,
        "rsi_14":rsi,"stoch_14":stochastic,
        "macd_12_26":macd,"macd_signal_9":macd_signal,
        "macd_histogram":macd_hist,
        "rsi_divergence_warning":oscillator_divergence,
        "completed_candles":len(b),
        "last_completed_bar_end":b[-1]["t"]+60,
        "missing_context":["intrabar_bid_ask_orderflow","order_book_absorption",
            "independent_higher_timeframe" if len(b)<155 else "none",
            "human_discretion_for_mountains_rivers_towers_dumpling_frypan",
            "unverified_price_gap_equivalence"],
    }
    # Ch 17 convergence; only contemporaneous evidence. Pattern contribution
    # is bounded per sign to prevent multiple aliases of one candle from
    # spuriously multiplying forecast strength.
    bullish=[e for e in patterns if e["experimental_weight"]>0]
    bearish=[e for e in patterns if e["experimental_weight"]<0]
    bull=max((e["experimental_weight"] for e in bullish),default=0)
    bear=min((e["experimental_weight"] for e in bearish),default=0)
    positives=[];negatives=[]
    if high_volume:positives.append("VOLUME_CONFIRMS_ACTIVITY")
    if near_sup and bottom_touches>=2:positives.append("REPEATED_SUPPORT")
    if near_res and top_touches>=2:negatives.append("REPEATED_RESISTANCE")
    if ema9 is not None and ema21 is not None:
        if ema9>ema21 and current["close"]>ema9: positives.append("EMA_BULLISH_ALIGNMENT")
        if ema9<ema21 and current["close"]<ema9: negatives.append("EMA_BEARISH_ALIGNMENT")
    if rsi is not None:
        if rsi<30:positives.append("RSI_OVERSOLD_WARNING")
        if rsi>70:negatives.append("RSI_OVERBOUGHT_WARNING")
    if oscillator_divergence=="BULLISH_WARNING":positives.append("RSI_BULLISH_DIVERGENCE")
    if oscillator_divergence=="BEARISH_WARNING":negatives.append("RSI_BEARISH_DIVERGENCE")
    if retrace_near: positives.append("RETRACEMENT_CONFLUENCE_NON_DIRECTIONAL")
    technical_adjust=(.12 if "REPEATED_SUPPORT" in positives else 0)
    technical_adjust-=(.12 if "REPEATED_RESISTANCE" in negatives else 0)
    technical_adjust+=(.1 if "EMA_BULLISH_ALIGNMENT" in positives else 0)
    technical_adjust-=(.1 if "EMA_BEARISH_ALIGNMENT" in negatives else 0)
    technical_adjust+=(.08 if "RSI_BULLISH_DIVERGENCE" in positives else 0)
    technical_adjust-=(.08 if "RSI_BEARISH_DIVERGENCE" in negatives else 0)
    # Overbought/oversold alone need not imply immediate reversal.
    score=max(-1.5,min(1.5,bull+bear+technical_adjust))
    if bullish and bearish:disagreement="CONFLICTING_CANDLE_SIGNALS"
    else:disagreement="NONE"
    result.update(available=True,status="READ_ONLY_UNCALIBRATED",
                  reason="Whole-book candle and convergence mapping; no validated directional edge",
                  last_closed_bar_ts=b[-1]["t"],pattern_evidence=patterns,
                  western_context=technical,
                  convergence={"bullish_count":len(bullish),
                       "bearish_count":len(bearish),"bullish_support":positives,
                       "bearish_support":negatives,"conflict":disagreement,
                       "raw_experimental_direction_score":round(score,5),
                       "directional_bias":("UP" if score>.15 else
                                           "DOWN" if score<-.15 else "INDETERMINATE"),
                       "weight_provenance":"AXIOM_HEURISTICS_NOT_NISON_STATISTICS"},
                  methodology_status={"implemented_chapters":list(_COVERAGE),
                   "not_machine_equivalent":["large-scale subjective chart tops/bottoms",
                    "protective stop selection and capital allocation",
                    "higher timeframe unless enough historical bars supplied",
                    "licensed proprietary judgment/training"]})
    return result


def forecast_nison_independent(report:dict|None,market:dict|None,
                               spot:float|None,now:float)->dict:
    """A separate uncalibrated Kalshi expiry hypothesis: no AXIOM ensemble.

    BTC spot and strike/timing are required; cannot infer an ABOVE outcome
    from a visually bullish candle alone. Formula/weights are newly proposed
    experiment, not a probability endorsed by Nison.
    """
    wait={"available":False,"status":"SHADOW_UNAVAILABLE","prob_above":None,
          "side":"WAIT","independent_from_axiom_ensemble":True,
          "votes_in_ensemble":False,"can_trigger_paper_or_orders":False,
          "research_only":True,"calibrated":False,"validated_alpha":False,
          "method":"unfitted_nison_context_plus_target_distance",
          "reason":"Insufficient independent candle/market context"}
    if not isinstance(report,dict) or report.get("available") is not True:
        return wait
    if not isinstance(market,dict):
        return wait
    try:
        now=_number(now);spot=_number(spot)
        target=_number(market.get("target"))
        seconds=_number(market.get("close_ts"))-now
        atr=_number(report["western_context"]["atr_14_usd"])
        score=_number(report["convergence"]["raw_experimental_direction_score"])
    except (TypeError,KeyError,ValueError,OverflowError):
        return wait
    if not (spot>0 and target>0 and atr>0 and 0<seconds<=900):
        return wait
    # ATR is a one-minute USD range proxy, not trained forecast variance.
    vol=max(atr*.65,spot*.000025)
    z=(spot-target)/(vol*math.sqrt(seconds/60))
    # Nison explicitly says candles do not supply targets; the target term is
    # an AXIOM experiment and is kept separate from book-driven evidence.
    z_bounded=max(-4,min(4,z+.25*score))
    probability=max(.005,min(.995,.5*math.erfc(-z_bounded/math.sqrt(2))))
    return {**wait,"available":True,"status":"SHADOW_UNVALIDATED",
            "prob_above":round(probability,5),
            "side":"ABOVE" if probability>.5 else "BELOW" if probability<.5 else "WAIT",
            "price_reference":"BTC_SPOT_PROXY_NOT_OFFICIAL_BRTI",
            "model_component_score":round(score,5),
            "target_distance_z":round(z,5),
            "reason":"Independent experimental estimate. Nison supplies analysis, not calibrated expiry probabilities"}
