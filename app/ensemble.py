"""AXIOM v2: multiple experimental BTC15M forecast engines, one consensus.

Provenance:
 - aaryann_fair: translated/adapted from aaryann123/kalshi-bot bot.py, MIT.
 - kalshibot_headstart: uses the published MIT head-start feature from
   jaldrich2023/KalshiBot Predictor.swift, but NOT its trained predictor.
 - axiom_volatility: original AXIOM v1 GBM-inspired forecast.
 - market_baseline: contemporaneous Kalshi midpoint; not independent alpha.

The ensemble is not calibrated and none of the above is verified profitable.
"""
from __future__ import annotations
import math
import statistics
from .engine import volatility_forecast, numeric


def cdf(z: float) -> float:
    return min(.995, max(.005, .5 * (1 + math.erf(z / math.sqrt(2)))))


def engine_result(name: str, p: float | None, method: str, note: str, **extra) -> dict:
    if p is None or not math.isfinite(p):
        return {'name':name, 'method':method,'available':False,'prob_above':None,
                'prob_below':None,'side':'WAIT','reason':note,**extra}
    p=min(.995,max(.005,p))
    return {'name':name,'method':method,'available':True,
            'prob_above':round(p,5),'prob_below':round(1-p,5),
            'side':'ABOVE' if p>.5 else 'BELOW' if p<.5 else 'WAIT',
            'reason':note,**extra}


def log_returns(closes: list[float]) -> list[float]:
    return [math.log(b/a) for a,b in zip(closes,closes[1:]) if a>0 and b>0]


def engine_pack(spot: float | None, market: dict | None, candles: list[dict]) -> dict:
    """Run available engines on the SAME market/spot snapshot.

    Each engine reports its source and provenance; no fabricated ML outputs or
    unsupported order flow data. Consensus is a median of independent estimates,
    withheld when disagreement is substantial. Market mid stays outside consensus.
    """
    engines=[]
    mid=market.get('market_mid') if market else None
    engines.append(engine_result('kalshi_market',mid,'market-baseline',
                                 'Kalshi quote-derived midpoint; comparator, not independent prediction',
                                 independent=False))
    if not market:
        return {'available':False, 'prob_above':None,'prob_below':None,'side':'WAIT',
                'reason':'No active Kalshi BTC15M market', 'engines':engines,
                'agreement':None,'spread':None,'alpha_vs_market':None,
                'validated':False,'method':'experimental-median-consensus'}
    target=numeric(market.get('target'))
    seconds=market.get('seconds_left') or 0
    closes=[numeric(c.get('close')) for c in candles if isinstance(c,dict)]
    closes=[c for c in closes if c is not None and c>0]
    ready=spot is not None and spot>0 and target is not None and target>0 and seconds>0 and len(closes)>=31
    # Engine #1: preserved AXIOM v1 volatility model
    v1=volatility_forecast(spot,target,seconds,candles)
    engines.append(engine_result('axiom_volatility',v1.get('prob_above') if v1.get('available') else None,
                                 'original-axiom',v1.get('reason','Insufficient data'),independent=True))
    if not ready:
        engines.append(engine_result('aaryann_fair',None,'ported-MIT','Need >=31 candles, spot, target and active market',independent=True))
        engines.append(engine_result('kalshibot_headstart',None,'adapted-MIT-feature','Need >=31 candles, spot, target and active market',independent=True))
    else:
        ret=log_returns(closes[-61:]);sigma=max(statistics.pstdev(ret),1e-6)
        remaining=seconds/60
        # Ported equation: fair_yes from aaryann123/kalshi-bot/bot.py
        # drift = 0.5 * five-minute return * min(remaining,5)/5
        # z = (ln(spot/strike)+drift)/(sigma_per_min*sqrt(remaining))
        ret_5m=math.log(spot/closes[-6])
        drift=.5*ret_5m*min(remaining,5)/5
        z=(math.log(spot/target)+drift)/(sigma*math.sqrt(remaining))
        engines.append(engine_result('aaryann_fair',cdf(z),'ported-MIT',
                                     'aaryann123 fair_yes: five-minute momentum + realized volatility',
                                     independent=True, vol_per_min=round(sigma,9)))
        # Ported headStart feature from KalshiBot Predictor.swift:
        # horizon=max(T-1,0)+1/3; headStart=(spot-strike)/(price_sigma*sqrt(horizon))
        # CDF maps this FEATURE to illustrative probability; it is NOT the
        # original project\'s learned/logistic model and does not claim its accuracy.
        returns=log_returns(closes[-61:])
        sigma_usd=max(statistics.stdev(returns)*spot, spot*.00005)
        horizon=max(remaining-1,0)+1/3
        headstart=(spot-target)/(sigma_usd*math.sqrt(horizon))
        engines.append(engine_result('kalshibot_headstart',cdf(headstart),'adapted-MIT-feature',
                                     'KalshiBot head-start distance feature mapped through normal CDF; NOT trained Predictor',
                                     independent=True, z_score=round(headstart,4)))
    good=[e['prob_above'] for e in engines if e.get('independent') and e['available']]
    if len(good)<2:
        return {'available':False,'prob_above':None,'prob_below':None,'side':'WAIT','reason':'At least 2 independent estimates required',
                'engines':engines,'agreement':None,'spread':None,'alpha_vs_market':None,
                'validated':False,'method':'experimental-median-consensus'}
    p=statistics.median(good)
    spread=max(good)-min(good)
    side='ABOVE' if p>=.60 else 'BELOW' if p<=.40 else 'WAIT'
    if spread>.30: side='WAIT'
    agreement=sum((e['prob_above']>.5)==(p>.5) for e in engines if e.get('independent') and e['available'])
    reason=('Consensus withheld: engines strongly disagree' if spread>.30 else
            'Consensus near 50%: no directional call' if side=='WAIT' else
            'Experimental median of independent models; NOT yet validated vs Kalshi')
    return {'available':True,'prob_above':round(p,5),'prob_below':round(1-p,5),'side':side,
            'reason':reason,'engines':engines,'agreement':agreement,
            'spread':round(spread,5),'alpha_vs_market':round(p-mid,5) if mid is not None else None,
            'validated':False,'method':'experimental-median-consensus'}


def taker_fee(price: float, count: int=1) -> float:
    """Illustrative single-contract taker fee formula ported from MIT
    aaryann123/kalshi-bot/bot.py. Actual venue fees must be series/date verified."""
    return math.ceil(.07*count*price*(1-price)*100-1e-9)/100


def execution_screen(ensemble:dict, market:dict|None, min_edge:float=.08)->dict:
    """Gross and approximate after-fee paper opportunity. No live orders."""
    out={'side':'WAIT','edge':None,'gross_edge':None,'entry_price':None,'fee_estimate':None,
         'reason':'No independent ensemble estimate / valid quotes'}
    if not market or not ensemble.get('available') or ensemble.get('side')=='WAIT': return out
    p=ensemble['prob_above']
    candidates=[]
    for side,prob,key in [('YES',p,'yes_ask'),('NO',1-p,'no_ask')]:
        ask=market.get(key)
        if ask is None or not .01<ask<1:continue
        f=taker_fee(ask)
        candidates.append((side,prob-ask-f,prob-ask,ask,f))
    if not candidates:return out
    side,edge,gross,ask,fee=max(candidates,key=lambda x:x[1])
    out.update(edge=round(edge,5),gross_edge=round(gross,5),entry_price=ask,fee_estimate=fee)
    # Evaluate the executable spread on the SELECTED side, not always YES.
    # A crossed book (negative spread) must never qualify as a tradable quote.
    bid=market.get('yes_bid' if side=='YES' else 'no_bid')
    spread=ask-bid if bid is not None else None
    if (side==('YES' if ensemble['side']=='ABOVE' else 'NO') and edge>=min_edge and
        .05<=ask<=.90 and market['seconds_left']>=120 and
        spread is not None and 0 <= spread <= .04):
        out.update(side=side,reason='Experimental after-fee paper candidate, not verified alpha or guaranteed fill')
    else:
        out['reason']='No qualifying consensus-aligned opportunity after fee, spread, price and time screens'
    return out
