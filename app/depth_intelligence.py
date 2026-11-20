"""Distinct, read-only order-book opportunity and execution-intelligence lanes.

1. Forecasting is performed elsewhere using independent BTC information.
2. Opportunity compares that estimate to participant ask prices with depth.
3. Execution describes ENTER/WAIT/HOLD/EXIT, never places orders.

The Kalshi REST book is a *single aggregated snapshot*, not a streaming
sequence of individual orders. No liquidity guarantee or validated edge.
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_CEILING
from typing import Any

from .orderbook import current_book, sweep

DEFAULT_SIZE = 10.
MAX_BOOK_AGE_SECONDS = 45
MAX_SPREAD = .04
MIN_AFTER_FEE_EDGE = .08


def unavailable_opportunity(reason: str) -> dict[str, Any]:
    return {
        "status": "WAIT", "side": "WAIT", "reason": reason, "candidates": [],
        "selected": None, "size_contracts": DEFAULT_SIZE, "source": "full_depth_order_book",
        "uses_orderbook_quotes_as_forecast": False, "verified_profit": False,
        "read_only": True,
    }


def unavailable_execution(reason: str) -> dict[str, Any]:
    return {
        "action": "WAIT", "side": None, "reason": reason,
        "entry_price": None, "estimated_exit_price": None,
        "size_contracts": None, "sweep": None, "read_only": True,
        "order_placed": False, "verified_profit": False,
    }


def _fee_estimate(sweep_result: dict, side: str) -> float:
    """Conservative illustrative per-level fee; NOT an official fee quote."""
    filled = sweep_result["available_contracts"]
    if not filled:
        return 0.
    # Use a per-contract upper rounding on aggregated average price, not an
    # invented official series-specific fee schedule.
    p = Decimal(str(sweep_result["average_price"]))
    raw = Decimal("0.07") * p * (Decimal(1)-p)
    fee_per_contract = (raw*100).to_integral_value(rounding=ROUND_CEILING)/100
    return float(fee_per_contract * Decimal(str(filled)))


def analyze_opportunities(forecast: dict | None, market: dict | None,
                          book: dict | None, now: float,
                          size_contracts: float = DEFAULT_SIZE,
                          signals: dict | None = None) -> dict:
    """Compare model probabilities with *size-adjusted* book ask, never mid.

    No forecast is created from order book. If no independent forecast, no
    estimate of value or claim of cheapness can be made.
    """
    if not market or not forecast or not forecast.get("available"):
        return unavailable_opportunity("Independent forecast or contract unavailable")
    if forecast.get("side") not in ("ABOVE", "BELOW"):
        return unavailable_opportunity("Independent forecast has no directional decision")
    if not current_book(book, market["ticker"], now, MAX_BOOK_AGE_SECONDS):
        return unavailable_opportunity("Full aggregated order-book data unavailable, wrong market or stale")
    if (market.get("seconds_left") or 0) < 120:
        return unavailable_opportunity("Less than 2 minutes remain; no new entry recommended")
    try:
        p = float(forecast["prob_above"])
        requested = float(size_contracts)
    except (ValueError, TypeError, KeyError):
        return unavailable_opportunity("Invalid forecast probability or order size")
    if not (math.isfinite(p) and 0 < p < 1 and math.isfinite(requested) and 0 < requested <= 100000):
        return unavailable_opportunity("Invalid forecast probability or order size")

    candidates = []
    for side, probability in (("YES", p), ("NO", 1-p)):
        buys = sweep(book, side, "BUY", requested)
        sells = sweep(book, side, "SELL", requested)
        best = book.get("best", {}).get(side, {})
        spread = best.get("spread")
        complete = buys["complete"]
        fee = _fee_estimate(buys, side)
        # All values in dollars per contract; ask is size-weighted, never
        # assumed unlimited at top price.
        avg_ask = buys["average_price"]
        gross = probability-avg_ask if complete and avg_ask is not None else None
        net = gross-fee/requested if gross is not None else None
        valid_spread = spread is not None and 0 <= spread <= MAX_SPREAD
        can_enter = (complete and valid_spread and .05 <= avg_ask <= .90
                     and net is not None and net >= MIN_AFTER_FEE_EDGE
                     and side == ("YES" if forecast["side"]=="ABOVE" else "NO"))
        signal_gate = 'OK'
        if signals is not None:
            if not signals.get('available'):
                signal_gate = 'Stale or missing BTC dynamics'
            elif (market.get('market_mid') is not None and
                  .47 <= market['market_mid'] <= .53 and .35 <= p <= .65):
                signal_gate = 'Near-even quote with weak independent direction'
            elif (signals.get('first_two_minute_reversal_flag') ==
                  'EARLY_DOWN_REBOUND_TENDENCY' and side == 'NO' and p > .20):
                signal_gate = 'Early-down rebound risk'
        can_enter = can_enter and signal_gate == 'OK'
        candidates.append({
            "side": side, "signal_gate":signal_gate, "model_probability": round(probability, 6),
            "size_contracts": requested, "ask_sweep": buys,
            "bid_sweep": sells, "complete_buy_depth": complete,
            "gross_model_minus_avg_ask": round(gross, 6) if gross is not None else None,
            "net_estimated_model_minus_cost": round(net, 6) if net is not None else None,
            "total_illustrative_entry_fee": round(fee, 4),
            "spread": spread, "eligible": bool(can_enter),
            "reason": ("Potential entry candidate (not verified alpha or fill)" if can_enter else
                       "No qualified size-adjusted, forecast-aligned after-fee entry"),
        })
    eligible=[x for x in candidates if x["eligible"]]
    winner=max(eligible,key=lambda c:c["net_estimated_model_minus_cost"]) if eligible else None
    return {
        "status": "CANDIDATE" if winner else "WAIT",
        "side": winner["side"] if winner else "WAIT",
        "reason": ("Model versus participant orders, with full-depth hypothetical sweep" if winner else
                   "No size-adjusted entry meets the experimental edge, spread, time and liquidity gates"),
        "selected": winner, "candidates": candidates,
        "size_contracts": requested, "source": "full_depth_order_book",
        "uses_orderbook_quotes_as_forecast": False,
        "verified_profit": False, "read_only": True,
    }


def execution_guidance(opportunity: dict | None, forecast: dict | None,
                       market: dict | None, book: dict | None,
                       now: float, position: dict | None = None) -> dict:
    """Manual execution research recommendation; no account access or orders.

    position is optional and purely explicit input (side and contracts);
    no assumption of actual user ownership or portfolio access.
    """
    if not market or not current_book(book, market["ticker"], now, MAX_BOOK_AGE_SECONDS):
        return unavailable_execution("Book unavailable, stale, or for another contract")
    if not forecast or not forecast.get("available"):
        return unavailable_execution("Independent forecast unavailable")
    if position is not None:
        if forecast.get('side') not in ('ABOVE','BELOW'):
            return unavailable_execution('Independent forecast abstained; no basis for HOLD or EXIT')
        side=position.get("side")
        try: size=float(position.get("contracts"))
        except (TypeError, ValueError): return unavailable_execution("Invalid hypothetical position size")
        if side not in ("YES","NO") or not math.isfinite(size) or size <= 0:
            return unavailable_execution("Invalid hypothetical position")
        sell = sweep(book, side, "SELL", size)
        if not sell["complete"]:
            return unavailable_execution("Insufficient displayed bid depth to exit hypothetical position")
        aligned = (side=="YES" and forecast.get("side")=="ABOVE") or (
            side=="NO" and forecast.get("side")=="BELOW")
        # A bare expiry timer is NOT evidence that selling beats settlement;
        # only an explicit opposing forecast produces experimental EXIT advice.
        should_exit = not aligned
        return {
            "action": "EXIT" if should_exit else "HOLD", "side": side,
            "reason": ("Experimental forecast opposes the position; review hypothetical bid-depth exit, not guaranteed advice" if should_exit else
                       "Current model remains aligned; hypothetical hold, not a guaranteed winning position"),
            "entry_price": None, "estimated_exit_price":sell["average_price"],
            "size_contracts": size, "sweep": sell, "read_only": True,
            "order_placed": False, "verified_profit": False,
        }
    chosen = (opportunity or {}).get("selected")
    if chosen and chosen.get("eligible"):
        return {
            "action": "ENTER", "side": chosen["side"],
            "reason": "Experimental size-adjusted opportunity; verify live depth and fee schedule before any manual action",
            "entry_price": chosen["ask_sweep"]["average_price"],
            "estimated_exit_price": None,
            "size_contracts": chosen["size_contracts"],
            "sweep": chosen["ask_sweep"], "read_only": True,
            "order_placed": False, "verified_profit": False,
        }
    return unavailable_execution("WAIT for better participant pricing or deeper available liquidity")
