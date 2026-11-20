"""Binance-first / Kalshi-repricing observer integrated into AXIOM's live poll.

Tracks observed, event-time-ordered Binance BTCUSDT spot changes versus
separately received Kalshi BTC15m aggregate book prices. This is a *possible*
stale-quote monitor, not an exchange-proven lag measurement or trade fill.
Funding is a nonvoting context input, never a YES/NO predictor.
"""
from __future__ import annotations
import math

from .binance_telemetry import finite
from .depth_intelligence import _fee_estimate
from .orderbook import current_book, sweep

MIN_BINANCE_MOVE_BPS = 5.0
MAX_OBSERVATION_GAP = 25.0
MIN_BOOKS_SECONDS = 2.0
MAX_UNCHANGED_MID = 0.01
SIZE = 10.0


def wait(reason, funding=None):
    return {"status":"WAIT","action":"WAIT","side":None,"reason":reason,
            "probable_observed_lag":False,"actual_quote_delay_verified":False,
            "measured_binance_move_bps":None,"kalshi_yes_mid_change":None,
            "book_observation_gap_seconds":None,
            "funding_bias":(funding or {}).get("funding_bias","UNKNOWN"),
            "funding_percent":(funding or {}).get("funding_percent"),
            "funding_used_for_direction":False,
            "read_only":True,"order_placed":False,"verified_profit":False}


class BinanceKalshiLagTracker:
    def __init__(self):
        self.previous=None

    def reset(self):
        self.previous=None

    def observe(self, market, book, binance, forecast, now):
        result=wait("Need two source-ordered Binance/Kalshi snapshots",binance)
        if not isinstance(market,dict) or not isinstance(binance,dict) or not isinstance(book,dict):
            self.reset()
            return result
        ticker=market.get("ticker")
        if (binance.get("status")!="STREAMING" or
                not current_book(book,ticker,now) or
                market.get("seconds_left",0)<120):
            self.reset()
            return wait("Fresh Binance/Kalshi feed and >2m before close required",binance)
        price=finite(binance.get("spot_price"))
        trade_at=finite(binance.get("spot_trade_at"))
        receive_at=finite(binance.get("spot_received_at"))
        book_at=finite(book.get("received_at"))
        best=book.get("best",{}).get("YES",{})
        bid=finite(best.get("bid"))
        ask=finite(best.get("ask"))
        if (None in (price,trade_at,receive_at,book_at,bid,ask)
                or price<=0 or not 0<bid<=ask<1
                or not -2<=book_at-receive_at<=8
                or not -2<=receive_at-trade_at<=4
                or not -2<=book_at-trade_at<=12):
            self.reset()
            return wait("Source timestamps, book time or two-sided quotes invalid",binance)
        row={"ticker":ticker,"book_at":book_at,"binance_event_at":trade_at,
             "binance_received_at":receive_at,"price":price,"yes_mid":(bid+ask)/2}
        previous=self.previous
        self.previous=row
        if not previous or previous["ticker"]!=ticker:
            return result
        interval=book_at-previous["book_at"]
        if not MIN_BOOKS_SECONDS<=interval<=MAX_OBSERVATION_GAP:
            return wait("Out-of-order or discontinuous Kalshi snapshot intervals",binance)
        if not (previous["binance_event_at"] < trade_at <= book_at
                and trade_at > previous["book_at"] and
                receive_at<=book_at+2):
            return wait("Binance event was not observed after previous Kalshi quote and before current quote",binance)
        move=10000*math.log(price/previous["price"])
        quote_change=row["yes_mid"]-previous["yes_mid"]
        base={**result,
              "measured_binance_move_bps":round(move,3),
              "kalshi_yes_mid_change":round(quote_change,5),
              "book_observation_gap_seconds":round(interval,2),
              "binance_event_at":trade_at,
              "kalshi_book_received_at":book_at,
              "binance_source_to_receipt_ms":round(1000*(receive_at-trade_at),1),
              "venue_currency_warning":"Binance BTCUSDT vs Kalshi BRTI BTCUSD: percent changes only",
              "actual_quote_delay_verified":False}
        if abs(move)<MIN_BINANCE_MOVE_BPS or abs(quote_change)>MAX_UNCHANGED_MID:
            return {**base,"reason":"Binance move below threshold or Kalshi quote already changed"}
        side="YES" if move>0 else "NO"
        best_side=book["best"][side]
        spread=finite(best_side.get("spread"))
        if spread is None or not 0<=spread<=.04:
            return {**base,"reason":"Spread too wide or unknown","side":side}
        buy=sweep(book,side,"BUY",SIZE)
        sell=sweep(book,side,"SELL",SIZE)
        if (not buy["complete"] or not sell["complete"] or
                buy["average_price"] is None or
                not .05<=buy["average_price"]<=.90):
            return {**base,"reason":"No full size-adjusted entry/exit depth","side":side}
        ask_price=buy["average_price"]
        fees=_fee_estimate(buy,side)/SIZE
        fair=finite((forecast or {}).get("prob_above"))
        direction_estimate=(fair if side=="YES" else 1-fair) if fair is not None else None
        # Only independent outcome estimate supports a model-vs-ask gap;
        # this alone does NOT price a resale or guarantee a lagged repricing.
        edge=(direction_estimate-ask_price-fees) if direction_estimate is not None else None
        feasible=(edge is not None and edge>=.03 and
                  forecast.get("available") is True and
                  (forecast.get("side")=="ABOVE" if side=="YES" else forecast.get("side")=="BELOW"))
        return {**base,
                "status":"CANDIDATE" if feasible else "WATCH",
                "action":"BUY_CANDIDATE" if feasible else "WATCH",
                "side":side,"reason":("Binance moved before current observed quote adjustment; independent after-fee price filter passes"
                                if feasible else "Possible delayed Kalshi quote, but no independently priced after-fee candidate"),
                "probable_observed_lag":True,
                "entry_ask_size_adjusted":round(ask_price,5),
                "current_exit_bid_size_adjusted":sell["average_price"],
                "estimated_entry_fee_per_contract":round(fees,4),
                "independent_outcome_edge_after_entry_fee":round(edge,5) if edge is not None else None,
                "contract_size":SIZE,
                "funding_warning":(binance.get("funding_bias") if binance.get("funding_status")=="LIVE" else "NO_FUNDING_REFERENCE"),
                "reference_price_is_not_brti":True,
                "fee_and_slippage_do_not_prove_resale_profit":True}
