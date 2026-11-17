"""Read-only execution evidence, deliberately separate from research scoring.

Public book snapshots cannot prove that any order executed, at what price,
how much fee Kalshi charged, whether an exit was possible, or net profitability.
This module reports only contemporaneous hypothetical book-walk friction.
"""
from __future__ import annotations
from .orderbook import current_book, sweep

SIZE = 10.0


def examine_liquidity(book, market, now, size_contracts=SIZE):
    """Conservative indicative crossing-cost check; never labels simulated fills."""
    report = {
        "status": "UNVERIFIED_EXECUTION", "mode": "READ_ONLY_RESEARCH",
        "real_orders_sent": False, "authenticated_fill_records": 0,
        "actual_entry_and_exit_fills_verified": False,
        "official_applied_trade_fees_verified": False,
        "realized_net_profit_usd": None, "verified_win_rate": None,
        "forecast_accuracy_is_execution_profit": False,
        "paper_gross_pnl_is_realized_profit": False,
        "paper_entry_assumption": "TOP_QUOTE_NO_CONFIRMED_FILL",
        "orderbook_estimates_are_executable_fills": False,
        "size_contracts": float(size_contracts),
        "scenarios": {}, "reason": "Authenticated fill and fee ledger not connected",
    }
    if not market or not current_book(book, market.get("ticker"), now):
        report["book_replay_status"] = "UNAVAILABLE"
        return report
    report["book_replay_status"] = "SIMULATED_SAME_SNAPSHOT"
    for side in ("YES", "NO"):
        try:
            buy = sweep(book, side, "BUY", size_contracts)
            sell = sweep(book, side, "SELL", size_contracts)
        except (ValueError, KeyError, TypeError):
            report["book_replay_status"] = "INVALID_BOOK"
            return report
        # A hypothetical instantaneous round-trip compares crossing bids and
        # asks in the SAME book. This is not realized profit or even a guaranteed
        # executable position; price/size can change before the second action.
        both = bool(buy["complete"] and sell["complete"])
        cost = (buy["total_notional"] - sell["total_notional"]) if both else None
        report["scenarios"][side] = {
            "entry": buy, "immediate_exit": sell,
            "full_size_available_on_both_sides": both,
            "same_snapshot_spread_crossing_cost_usd": round(cost, 6) if cost is not None else None,
            "fee_adjusted_net_return_usd": None,
            "actual_fill": False,
            "realized_pnl_usd": None,
        }
    return report
