"""Experimental Kalshi contract quote repricing model, AFTER BTC prediction.

Forecasts a future *Kalshi YES quote change*, never BTC price or settlement.
Inputs: independently finished BTC probability, observed Kalshi YES bid/ask,
BTC momentum, spread, resting depth, time-to-expiration and signed BTC trades.
Learns on REAL consecutive point-in-time quote observations with online ridge
regression; no future quotes are available at prediction time. No order API.

This is explicitly *not* a calibrated settlement predictor, verified edge,
or a forecast of executable future bids. Intracontract prices may diverge
from BTC outcome probabilities for liquidity and risk reasons.
"""
from __future__ import annotations

import math
from collections import deque

from .engine import numeric
from .orderbook import current_book, sweep

HORIZON_SECONDS = 30
FEATURES = ("bias","btc_vs_quote_gap","btc_momentum","quote_momentum",
            "kalshi_depth_imbalance","spread","time_to_close","quote_level",
            "btc_taker_cvd")


def unavailable(reason: str) -> dict:
    return {"available":False,"name":"axiom_contract_repricing",
            "target":"next_30s_yes_quote_midpoint_change_not_btc_outcome",
            "predicted_yes_mid_change_30s":None,
            "predicted_yes_mid_30s":None,
            "direction":"WAIT","training_transitions":0,
            "trained_on_future_observed_quotes_only":True,
            "read_only":True,"order_placed":False,
            "independent_btc_forecast_changed":False,
            "future_exit_bid_verified":False,
            "reason":reason}


def _bounded(x, scale=1.):
    v=numeric(x)
    return math.tanh(v/scale) if v is not None else 0.0


def _solve(matrix, rhs):
    """Deterministic small regularized normal-equation solver, stdlib only."""
    n=len(rhs)
    a=[row[:]+[b] for row,b in zip(matrix,rhs)]
    for i in range(n):
        pivot=max(range(i,n),key=lambda r:abs(a[r][i]))
        a[i],a[pivot]=a[pivot],a[i]
        if abs(a[i][i])<1e-12:
            return [0.0]*n
        div=a[i][i]
        for j in range(i,n+1):
            a[i][j]/=div
        for k in range(n):
            if k==i:continue
            factor=a[k][i]
            for j in range(i,n+1):
                a[k][j]-=factor*a[i][j]
    return [row[-1] for row in a]


class ContractRepricingModel:
    """Online quote-change learner. Samples include only *past* quote changes.

    The stored feature row is t0; label is the quote observed at t1.
    Only then can that t0->t1 pair update the coefficients.
    Learning persists across contracts while this worker remains alive.
    It resets pending ticks when market/ticker/data provenance changes.
    """
    def __init__(self):
        self.samples=deque(maxlen=500)
        self.pending=None
        self.previous_quote_delta=0.0
        self.last_result=unavailable("Waiting for first observed Kalshi quote")

    def _features(self,market,book,independent_forecast,signals,flow,mid,spread):
        p=numeric(independent_forecast.get("prob_above"))
        momentum=numeric((signals or {}).get("momentum_bps_per_min"))
        imbalance=numeric(book.get("book_imbalance_5c"))
        remaining=numeric(market.get("seconds_left"))
        cvd=numeric(((flow or {}).get("directional_components") or {}).get("btc_taker_cvd_2m"))
        return [
            1.0,
            _bounded((p-mid)*2),
            _bounded(momentum,10),
            _bounded(self.previous_quote_delta*100,3),
            _bounded(imbalance),
            _bounded(spread,.04),
            _bounded((remaining or 0)/900),
            _bounded((mid-.5)*2),
            _bounded(cvd),
        ]

    def _coefficients(self):
        n=len(FEATURES)
        # Every feature is eligible to be learned; ridge only regularizes
        # small samples and prevents singular inversion.
        alpha=2.0
        gram=[[alpha if j==i else 0. for j in range(n)]
              for i in range(n)]
        response=[0.]*n
        for x,y in self.samples:
            for i in range(n):
                response[i]+=x[i]*y
                for j in range(n):
                    gram[i][j]+=x[i]*x[j]
        return _solve(gram,response)

    def observe(self,market,book,independent_forecast,signals,now,btc_flow=None):
        ticker=(market or {}).get("ticker")
        if (not isinstance(market,dict) or not ticker or
            not current_book(book,ticker,now) or
            not isinstance(independent_forecast,dict) or
            not independent_forecast.get("available")):
            self.pending=None
            self.previous_quote_delta=0.
            self.last_result=unavailable("Need independent BTC forecast and fresh Kalshi quote")
            self.last_result["training_transitions"]=len(self.samples)
            return dict(self.last_result)
        best=(book.get("best") or {}).get("YES") or {}
        bid=numeric(best.get("bid"));ask=numeric(best.get("ask"))
        ts=numeric(book.get("received_at"))
        p=numeric(independent_forecast.get("prob_above"))
        if (ts is None or bid is None or ask is None or p is None
            or not 0<bid<=ask<1 or not 0<p<1):
            self.pending=None
            self.last_result=unavailable("Need coherent same-contract YES bid/ask")
            self.last_result["training_transitions"]=len(self.samples)
            return dict(self.last_result)
        mid=(bid+ask)/2
        spread=ask-bid
        old=self.pending
        if old and old["ticker"]!=ticker:
            old=None
            self.previous_quote_delta=0.
        if old:
            dt=ts-old["ts"]
            if dt<=0:
                # Never learn from duplicate/out-of-order timestamps.
                return dict(self.last_result)
            if dt<=120 and old["reference"]==(signals or {}).get("price_reference"):
                change=mid-old["mid"]
                # Next-observation labels are available only NOW, never at t0.
                normalized_change=max(-1.,min(1.,change*HORIZON_SECONDS/dt))
                self.samples.append((old["features"],normalized_change))
                self.previous_quote_delta=change*HORIZON_SECONDS/dt
            else:
                self.previous_quote_delta=0.
        features=self._features(market,book,independent_forecast,signals,
                                btc_flow,mid,spread)
        self.pending={"ticker":ticker,"ts":ts,"mid":mid,
                      "reference":(signals or {}).get("price_reference"),
                      "features":features}
        result=unavailable("No observed future quote transitions yet")
        result["training_transitions"]=len(self.samples)
        result["source"]="kalshi_aggregate_depth_plus_independent_btc_data"
        result["observed_yes_bid"]=bid
        result["observed_yes_ask"]=ask
        result["observed_yes_mid"]=round(mid,6)
        result["independent_btc_probability_above"]=round(p,6)
        result["btc_vs_quote_gap"]=round(p-mid,6)
        result["feature_names"]=list(FEATURES)
        result["training_persists_across_contracts_in_process"]=True
        result["training_persists_across_process_restart"]=False
        if not self.samples:
            self.last_result=result
            return dict(result)
        coefficients=self._coefficients()
        change=sum(x*y for x,y in zip(coefficients,features))
        # Price bounds are contract arithmetic, not confidence vetoes.
        predicted_mid=max(.001,min(.999,mid+change))
        change=predicted_mid-mid
        out={**result,"available":True,
             "reason":"Online learner fitted only on prior observed future quote changes",
             "predicted_yes_mid_change_30s":round(change,6),
             "predicted_yes_mid_30s":round(predicted_mid,6),
             "direction":"UP" if change>0 else "DOWN" if change<0 else "FLAT",
             "trained":True,
             "experimental_uncalibrated_quote_prediction":True,
             "forecast_horizon_seconds":HORIZON_SECONDS,
             "bid_ask_spread_now":round(spread,6),
             # An updated midpoint is NOT an executable future exit bid.
             "predicted_future_executable_bid":None,
             "future_exit_bid_verified":False}
        self.last_result=out
        return dict(out)
