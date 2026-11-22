"""AXIOM v2: multiple experimental BTC15M forecast engines, one consensus.

Provenance:
 - aaryann_fair: translated/adapted from aaryann123/kalshi-bot bot.py, MIT.
 - kalshibot_headstart: uses the published MIT head-start feature from
   jaldrich2023/KalshiBot Predictor.swift, but NOT its trained predictor.
 - axiom_volatility: original AXIOM v1 GBM-inspired forecast.
 - market_baseline: participant order-book YES midpoint; NOT a Kalshi prediction.

The ensemble is not calibrated and none of the above is verified profitable.
"""
from __future__ import annotations
import math
import statistics
from .engine import volatility_forecast, numeric
from .boosted_model import boosted_forecast
from .nison_methodology import scan_nison, forecast_nison_independent
from .market_structure import pressure_forecast


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


def engine_pack(spot: float | None, market: dict | None, candles: list[dict], signals: dict | None = None, *, context: dict | None = None, now: float | None = None) -> dict:
    """Run available engines on the SAME market/spot snapshot.

    Each engine reports its source and provenance; no fabricated ML outputs or
    unsupported order flow data. Consensus is a median of independent estimates,
    withheld when disagreement is substantial. Market mid stays outside consensus.
    """
    engines=[]
    mid=market.get('market_mid') if market else None
    # Retain the historical 'kalshi_market' name for scorecard and export
    # compatibility, but do NOT treat participant order-book quotes as a model.
    # A 70-cent price is a price, not Kalshi's 70% winning prediction.
    quote_benchmark=engine_result('kalshi_market',mid,'orderbook-quote-benchmark',
                                  'YES bid/ask midpoint set by participant orders; NOT Kalshi\'s prediction',
                                  independent=False,is_model_prediction=False,
                                  role='participant_order_book_price_benchmark')
    quote_benchmark['side']='N/A'  # A quote cannot issue a direction signal.
    engines.append(quote_benchmark)
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
    # When called by the live application, include the point-in-time analytic
    # target model in the existing integrated ensemble. Standalone legacy
    # engine_pack calls without a signals snapshot retain their original
    # three-engine semantics and archived regression scorecards.
    if isinstance(signals,dict) and signals.get('available'):
        d=signals
        engines.append(engine_result('axiom_target_dynamics',
            d.get('prob_above') if d.get('available') else None,
            'analytic-distance-volatility-acceleration',
            d.get('reason','Fresh target dynamics unavailable'),independent=True,
            reference=d.get('price_reference'),
            target_touch_probability=d.get('target_touch_probability'),
            movement_2m_probability_5bp=d.get('movement_2m_probability_5bp'),
            calibrated=False))
    # The integrated candidate gives the learned model, complete Nison
    # methodology and all observed market-context features actual ensemble
    # votes. Nothing is relegated to "background" merely for being new.
    # Baseline calls without context preserve historical regression behavior.
    enhanced=isinstance(context,dict) and now is not None
    if enhanced:
        try:
            learned=boosted_forecast(spot,market,candles,now)
        except (KeyError,TypeError,ValueError,ArithmeticError):
            learned={'name':'axiom_gradient_boosted_btc','available':False,
                     'prob_above':None,'reason':'Fitted model input unavailable'}
        engines.append(engine_result('axiom_gradient_boosted_btc',
            learned.get('prob_above') if learned.get('available') else None,
            'trained-gradient-boosting','Historical BTC 90-day model with actual future BTC outcomes',
            independent=True,calibrated=False,training='binance_spot_90day',
            learning_status=learned.get('reason')))
        try:
            report=scan_nison(candles,now)
            japanese=forecast_nison_independent(report,market,spot,now)
        except (KeyError,TypeError,ValueError,ArithmeticError,IndexError):
            japanese={'available':False,'prob_above':None,'reason':'Japanese pattern inputs unavailable'}
            report={'pattern_evidence':[]}
        engines.append(engine_result('axiom_full_nison',
            japanese.get('prob_above') if japanese.get('available') else None,
            'nison-full-book-independent',
            'Nison candlestick, continuation, structures and convergence; original numeric mapping',
            independent=True,calibrated=False,
            detected_patterns=[x.get('name') for x in report.get('pattern_evidence',[])],
            interpretation=japanese.get('reason')))
        source_base=next((e['prob_above'] for e in engines if
                          e['name']=='axiom_volatility' and e.get('available')),None)
        try:
            pressure=pressure_forecast(spot,market,source_base,context)
        except (KeyError,TypeError,ValueError,ArithmeticError,IndexError):
            pressure={'available':False,'prob_above':None,'reason':'Market feature inputs unavailable'}
        engines.append(engine_result('axiom_multi_signal_context',
            pressure.get('prob_above') if pressure.get('available') else None,
            'multiscale-orderflow-funding-cvd-walls',
            '30m/60m/120m + book imbalance, liquidity walls, absorption, CVD, funding and large-trade flow',
            independent=False,calibrated=False,
            active_factors=pressure.get('components',{}),
            experimental_z_shift=pressure.get('combined_z_shift')))
    # Kalshi midpoint quote stays a comparator, not a probability forecast.
    voting_models=frozenset((
        'axiom_volatility','aaryann_fair','kalshibot_headstart',
        'axiom_target_dynamics','axiom_gradient_boosted_btc',
        'axiom_full_nison','axiom_multi_signal_context'))
    good=[e['prob_above'] for e in engines
          if e['name'] in voting_models and e['available']]
    if len(good)<2:
        return {'available':False,'prob_above':None,'prob_below':None,'side':'WAIT','reason':'At least 2 independent estimates required',
                'engines':engines,'agreement':None,'spread':None,'alpha_vs_market':None,
                'validated':False,'method':'experimental-median-consensus'}
    p=statistics.median(good)
    spread=max(good)-min(good)
    # Predictive outputs are not silenced just because competing hypotheses
    # disagree. Expose disagreement numerically for the execution layer.
    side=('ABOVE' if p>.5 else 'BELOW' if p<.5 else 'WAIT') if enhanced else (
          'ABOVE' if p>=.60 else 'BELOW' if p<=.40 else 'WAIT')
    if not enhanced and spread>.30: side='WAIT'
    agreement=sum((e['prob_above']>.5)==(p>.5) for e in engines
                  if e['name'] in voting_models and e['available'])
    reason=('Experimental all-signal consensus; disagreement preserved, not vetoed' if enhanced else
            'Consensus withheld: engines strongly disagree' if spread>.30 else
            'Consensus near 50%: no directional call' if side=='WAIT' else
            'Experimental median of independent models; NOT yet validated vs Kalshi')
    return {'available':True,'prob_above':round(p,5),'prob_below':round(1-p,5),'side':side,
            'reason':reason,'engines':engines,'agreement':agreement,
            'spread':round(spread,5),
            # Preserve legacy alpha_vs_market for existing API consumers;
            # this is only a model-minus-order-book-mid quote discrepancy.
            'alpha_vs_market':round(p-mid,5) if mid is not None else None,
            'forecast_minus_quote_mid':round(p-mid,5) if mid is not None else None,
            'quote_discrepancy_is_validated_alpha':False,
            'validated':False,'method':'experimental-median-consensus',
            'all_signal_integration_active':enhanced,
            'active_predictive_models':[e['name'] for e in engines
                 if e['name'] in voting_models and e.get('available')],
            'missing_predictive_models':[e['name'] for e in engines
                 if e['name'] in voting_models and not e.get('available')]}


def taker_fee(price: float, count: int=1) -> float:
    """Illustrative single-contract taker fee formula ported from MIT
    aaryann123/kalshi-bot/bot.py. Actual venue fees must be series/date verified."""
    return math.ceil(.07*count*price*(1-price)*100-1e-9)/100


def execution_screen(ensemble:dict, market:dict|None, min_edge:float=.08)->dict:
    """Compare independent model estimate to participant offers, not Kalshi forecasts.

    Gross/approximate after-fee paper opportunity only; no guaranteed fills.
    """
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
        out.update(side=side,reason='Independent model minus participant ask (estimated fee); unverified value, not a guaranteed fill')
    else:
        out['reason']='No qualifying consensus-aligned opportunity after fee, spread, price and time screens'
    return out
