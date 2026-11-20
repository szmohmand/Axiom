"""Intra-contract Kalshi quote/price-movement intelligence, separate from settlement.

Read-only, bounded per-ticker full-depth REST snapshots. Changes are net
price-level changes BETWEEN observations, not actual add/cancel/fill events.
Midpoint changes are not executable profits. No learned price-impact model.
"""
from __future__ import annotations
from collections import deque
import math

from .engine import numeric
from .ensemble import taker_fee
from .orderbook import current_book, sweep

SIZE = 10.0
MAX_GAP = 60.0


def unavailable(reason):
    return {"available": False, "reason": reason, "observations": 0,
            "last_move": None, "max_observed_yes_mid_move": None,
            "rejection_proxy": "NONE", "funding": "NOT_CONNECTED",
            "net_book_change_is_order_events": False,
            "unverified_resale_profit": True}


def wait(reason):
    return {"action": "WAIT", "side": "WAIT", "reason": reason,
            "read_only": True, "order_placed": False,
            "entry_ask": None, "break_even_exit_bid": None,
            "net_profit_verified": False, "outcome_not_equal_resale": True}


def _levels(book, side):
    return {float(row["price"]):float(row["size"]) for row in book["bids"][side]}


def _changes(before, after):
    prices=before.keys() | after.keys()
    added=sum(max(0.0,after.get(p,0)-before.get(p,0)) for p in prices)
    removed=sum(max(0.0,before.get(p,0)-after.get(p,0)) for p in prices)
    return {"net_addition_contracts":round(added,3),
            "net_removal_contracts":round(removed,3),
            "net_change_contracts":round(added-removed,3)}


class IntracontractTracker:
    def __init__(self):
        self.ticker=None
        self.rows=deque(maxlen=40)

    def reset(self):
        self.ticker=None
        self.rows.clear()

    def observe(self, market, book, signals, now):
        if not market or not signals or not signals.get("available") or not current_book(
                book,market["ticker"],now):
            self.reset()
            return unavailable("Market, BTC reference or fresh full depth missing")
        best=book.get("best",{}).get("YES",{})
        bid=numeric(best.get("bid"))
        ask=numeric(best.get("ask"))
        btc=numeric(signals.get("reference_value"))
        stamp=numeric(book.get("received_at"))
        if (bid is None or ask is None or not 0<bid<=ask<1
                or btc is None or btc<=0 or stamp is None):
            self.reset()
            return unavailable("No coherent two-sided price or BTC reference")
        ticker=market["ticker"]
        if self.ticker!=ticker:
            self.reset()
            self.ticker=ticker
        elif self.rows and (stamp<=self.rows[-1]["ts"] or stamp-self.rows[-1]["ts"]>MAX_GAP):
            self.reset()
            self.ticker=ticker
        row={"ts":stamp,"mid":(bid+ask)/2,"btc":btc,
             "reference":signals.get("price_reference"),"yes":_levels(book,"YES"),
             "no":_levels(book,"NO"),"imbalance":numeric(book.get("book_imbalance_5c"))}
        prev=self.rows[-1] if self.rows else None
        older=self.rows[-2] if len(self.rows)>=2 else None
        self.rows.append(row)
        move=None
        reject="NONE"
        if prev:
            interval=stamp-prev["ts"]
            same_ref=row["reference"]==prev["reference"]
            delta_btc=(10000*math.log(btc/prev["btc"])) if same_ref else None
            change=row["mid"]-prev["mid"]
            if older and prev["mid"]>older["mid"] and row["mid"]<older["mid"]:
                reject="YES_UP_SWING_REJECTION_PROXY"
            elif older and prev["mid"]<older["mid"] and row["mid"]>older["mid"]:
                reject="YES_DOWN_SWING_REJECTION_PROXY"
            move={"observed_seconds":round(interval,2),
                  "yes_midpoint_change":round(change,5),
                  "btc_reference_change_bps":round(delta_btc,4) if delta_btc is not None else None,
                  "yes_bid_level_change":_changes(prev["yes"],row["yes"]),
                  "no_bid_level_change":_changes(prev["no"],row["no"]),
                  "imbalance_change":round(row["imbalance"]-prev["imbalance"],5)
                     if row["imbalance"] is not None and prev["imbalance"] is not None else None,
                  "source_same":same_ref}
        changes=[abs(b["mid"]-a["mid"]) for a,b in zip(self.rows,list(self.rows)[1:])]
        return {"available":True,"reason":"Observed Kalshi full-depth snapshots; no unseen events assumed",
                "ticker":ticker,"observations":len(self.rows),
                "current_yes_midpoint":round(row["mid"],5),
                "last_move":move,"max_observed_yes_mid_move":round(max(changes),5) if changes else None,
                "rejection_proxy":reject, "funding":"NOT_CONNECTED",
                "net_book_change_is_order_events":False,
                "unverified_resale_profit":True}


def resale_screen(market, book, signals, timeline, now):
    """An independent movement-based entry lane; never requires YES/NO to win.

    The gate requires *observed* matching BTC and Kalshi price changes and
    actual spread/depth. It does not project a future exit or promise resale.
    """
    result=wait("Await two fresh same-contract Kalshi snapshots")
    if not timeline or not timeline.get("available") or not signals or not signals.get("available"):
        return result
    if not current_book(book,market["ticker"],now):
        return wait("Stale or mismatched execution book")
    if timeline.get("ticker")!=market["ticker"]:
        return wait("Snapshot history belongs to a different contract")
    last=timeline.get("last_move")
    if not last or last["btc_reference_change_bps"] is None:
        return result
    if market.get("seconds_left",0)<120:
        return wait("Too close to expiration for a new speculative resale entry")
    btc=last["btc_reference_change_bps"]
    yes=last["yes_midpoint_change"]
    if abs(btc)<0.5 or abs(yes)<.005 or btc*yes<=0:
        return wait("No corroborating BTC/contract midpoint movement")
    side="YES" if btc>0 else "NO"
    best=book["best"][side]
    spread=numeric(best.get("spread"))
    buy=sweep(book,side,"BUY",SIZE)
    sell=sweep(book,side,"SELL",SIZE)
    ask=buy["average_price"]
    if (not buy["complete"] or not sell["complete"] or ask is None or
            spread is None or spread>.04 or not .05<=ask<=.90):
        return wait("Insufficient size-adjusted buy/sell depth, price or spread")
    # The maximum per-contract illustrative 7% quadratic taker fee is 2c.
    # The bid below is ONLY the minimum observed future price that would
    # overcome current asking cost, two approximate fees and 1c slippage.
    entry_fee=taker_fee(ask)
    break_even=round(ask+entry_fee+.02+.01,4)
    return {**result,"action":"BUY_CANDIDATE","side":side,
            "reason":"Observed BTC/contract co-movement and executable-looking depth; resale not forecast",
            "entry_ask":round(ask,5),
            "current_sell_bid":sell["average_price"],
            "break_even_exit_bid":break_even,
            "illustrative_fee_entry":entry_fee,
            "assumed_exit_fee_upper_bound":.02,
            "adverse_exit_slippage_buffer":.01,
            "observed_move_seconds":last["observed_seconds"],
            "observed_yes_midpoint_move":yes,
            "momentum_acceleration_bps_per_min":signals.get("acceleration_bps_per_min"),
            "btc_target_touch_probability":signals.get("target_touch_probability"),
            "btc_movement_risk_2m":signals.get("movement_2m_probability_5bp"),
            "reversal_risk_observed":signals.get("first_two_minute_reversal_flag"),
            "quote_rejection_proxy":timeline.get("rejection_proxy"),
            "settlement_winner_not_required":True,
            "net_profit_verified":False}


def resale_position_review(position, market, book, signals, timeline, now):
    """Current depth-aware, after-illustrative-fee P/L for ONE paper position."""
    base=wait("No matching open simulated position")
    if not position:
        return base
    if not market or not current_book(book,market["ticker"],now):
        return wait("Cannot evaluate exit without current same-contract bids")
    if position.get("ticker") not in (None,market["ticker"]):
        return wait("Paper position belongs to a different contract")
    if not signals or not signals.get("available"):
        return wait("Fresh BTC evidence is required for a hold/sell review")
    side=position.get("side")
    cost=numeric(position.get("entry"))
    if side not in ("YES","NO") or cost is None or not 0<cost<1:
        return wait("Invalid paper entry")
    exit_book=sweep(book,side,"SELL",1)
    bid=exit_book["average_price"]
    if not exit_book["complete"] or bid is None:
        return wait("Cannot sell a full paper contract at displayed depth")
    net=round(bid-cost-taker_fee(cost)-taker_fee(bid),4)
    last=(timeline or {}).get("last_move") or {}
    change=last.get("yes_midpoint_change")
    weakening=(change is not None and (change<0 if side=="YES" else change>0))
    opposing=(signals or {}).get("side") == ("BELOW" if side=="YES" else "ABOVE")
    action=("SELL_CANDIDATE" if net>=.02 and weakening else
            "EXIT_REVIEW" if opposing and net<0 else "HOLD")
    return {**base, "action":action,"side":side,
            "reason":("Positive displayed after-fee resale with weakening quote" if action=="SELL_CANDIDATE"
                      else "BTC outcome evidence opposes paper position" if action=="EXIT_REVIEW"
                      else "No fresh evidence-based early sale signal"),
            "entry_ask":cost,"current_sell_bid":bid,
            "estimated_net_per_paper_contract":net,
            "displayed_exit_depth_complete":True,
            "realized_profit":False,
            "entry_was_hypothetical_quoted_fill":True}
