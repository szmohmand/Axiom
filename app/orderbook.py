"""Kalshi full-available-depth aggregated order-book snapshots (read-only).

Official Kalshi REST /markets/{ticker}/orderbook?depth=0 returns every
available *price level*, not individual orders or order-owner identities.
Only YES/NO bids exist in the payload; asks are their $1 complements.
Snapshot does not prove event-by-event changes between polls or fills.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
from typing import Any


ONE = Decimal("1")


def _number(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError("Invalid price/quantity type")
    try:
        x = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid order-book numeric value") from None
    if not x.is_finite():
        raise ValueError("Nonfinite order-book numeric value")
    return x


def unavailable(ticker: str | None, reason: str) -> dict:
    return {
        "available": False, "ticker": ticker, "status": "UNAVAILABLE",
        "reason": reason, "received_at": None, "source": "kalshi_orderbook_fp",
        "depth_request": 0, "is_full_aggregated_depth": False,
        "individual_orders_visible": False,
        "bids": {"YES": [], "NO": []}, "asks": {"YES": [], "NO": []},
        "best": {"YES": {"bid": None, "ask": None, "spread": None},
                 "NO": {"bid": None, "ask": None, "spread": None}},
        "near_best_bid_size_5c": {"YES": 0., "NO": 0.},
    }


def _levels(items: Any, name: str) -> list[tuple[Decimal, Decimal]]:
    if not isinstance(items, list):
        raise ValueError(f"{name} must be an array")
    if len(items) > 10000:
        raise ValueError(f"{name} exceeds price-level safety bound")
    seen = set()
    out = []
    for entry in items:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError(f"Malformed {name} price level")
        p, size = map(_number, entry)
        if not (0 < p < 1) or size <= 0:
            raise ValueError(f"Invalid {name} price or quantity")
        if p in seen:
            raise ValueError(f"Duplicate {name} price level")
        seen.add(p)
        out.append((p, size))
    # Kalshi documents ascending order. Sort as a defensive normalization
    # without dropping / inventing any level.
    return sorted(out, key=lambda x: x[0], reverse=True)


def _json_levels(items: list[tuple[Decimal, Decimal]]) -> list[dict]:
    return [{"price": float(p), "size": float(size)} for p, size in items]


def normalize_orderbook(payload: dict, ticker: str, received_at: float) -> dict:
    """Validate and normalize every price level from Kalshi's bid-only book.

    Failure is explicit, never replaced with summary quote sizes or
    fabricated order-book volume.
    """
    if not ticker or not ticker.startswith("KXBTC15M-"):
        raise ValueError("Orderbook must be tied to an active BTC15m ticker")
    if not isinstance(received_at, (int, float)) or not math.isfinite(received_at):
        raise ValueError("Invalid order-book receipt time")
    if not isinstance(payload, dict) or not isinstance(payload.get("orderbook_fp"), dict):
        raise ValueError("Kalshi orderbook_fp missing")
    fp = payload["orderbook_fp"]
    yes = _levels(fp.get("yes_dollars"), "YES bids")
    no = _levels(fp.get("no_dollars"), "NO bids")
    if not yes and not no:
        return unavailable(ticker, "Empty order book: no resting price levels")
    if yes and no and yes[0][0] + no[0][0] > ONE:
        raise ValueError("Crossed/inconsistent YES and NO bids")
    # A NO bid at p implies a YES ask at 1-p, and vice versa.
    yes_ask = [(ONE-p, size) for p, size in no]
    no_ask = [(ONE-p, size) for p, size in yes]
    bids = {"YES": _json_levels(yes), "NO": _json_levels(no)}
    asks = {"YES": _json_levels(yes_ask), "NO": _json_levels(no_ask)}
    best = {}
    for side, b, a in (("YES", yes, yes_ask), ("NO", no, no_ask)):
        bid = b[0][0] if b else None
        ask = a[0][0] if a else None
        spread = ask-bid if bid is not None and ask is not None else None
        if spread is not None and spread < 0:
            raise ValueError("Crossed order-book side")
        best[side] = {
            "bid": float(bid) if bid is not None else None,
            "bid_size": float(b[0][1]) if b else 0.,
            "ask": float(ask) if ask is not None else None,
            "ask_size": float(a[0][1]) if a else 0.,
            "spread": float(spread) if spread is not None else None,
        }
    near = {}
    for side, rows in (("YES", yes), ("NO", no)):
        near[side] = float(sum((sz for p, sz in rows if rows[0][0]-p <= Decimal("0.05")), Decimal(0))) if rows else 0.
    return {
        "available": True, "ticker": ticker, "status": "OK",
        "reason": "Full available aggregated Kalshi REST depth; no individual order IDs",
        "received_at": float(received_at),
        "source": "kalshi_orderbook_fp",
        "depth_request": 0, "is_full_aggregated_depth": True,
        "individual_orders_visible": False,
        "bids": bids, "asks": asks, "best": best,
        "near_best_bid_size_5c": near,
        "levels": {"YES": len(yes), "NO": len(no)},
        "resting_bid_contracts": {
            "YES": float(sum((sz for _, sz in yes), Decimal(0))),
            "NO": float(sum((sz for _, sz in no), Decimal(0))),
        },
        "book_imbalance_5c": (
            (near["YES"]-near["NO"])/(near["YES"]+near["NO"])
            if near["YES"]+near["NO"] else None),
    }


def current_book(book: dict | None, ticker: str, now: float, max_age: float = 45) -> bool:
    if not isinstance(book, dict) or not book.get("available") or book.get("ticker") != ticker:
        return False
    ts = book.get("received_at")
    return isinstance(ts, (int, float)) and math.isfinite(ts) and -2 <= now-ts <= max_age


def sweep(book: dict, side: str, action: str, contracts: float = 1.) -> dict:
    """Hypothetical book walk; never assumes top quote fills unlimited size."""
    if side not in ("YES", "NO") or action not in ("BUY", "SELL"):
        raise ValueError("Invalid side or book action")
    requested = _number(contracts)
    if not 0 < requested <= 100000:
        raise ValueError("Invalid requested contract size")
    levels = book.get("asks" if action == "BUY" else "bids", {}).get(side, [])
    filled = Decimal(0)
    notional = Decimal(0)
    used = 0
    worst = None
    for level in levels:
        price = _number(level["price"])
        size = _number(level["size"])
        if not (0 < price < 1) or size <= 0:
            raise ValueError("Invalid normalized order-book level")
        take = min(size, requested-filled)
        if take <= 0:
            break
        filled += take
        notional += take*price
        worst = price
        used += 1
        if filled == requested:
            break
    complete = filled == requested
    avg = notional/filled if filled > 0 else None
    top = _number(levels[0]["price"]) if levels else None
    slip = (avg-top if action == "BUY" else top-avg) if avg is not None and top is not None else None
    return {
        "complete": complete, "requested_contracts": float(requested),
        "available_contracts": float(filled), "levels_consumed": used,
        "best_price": float(top) if top is not None else None,
        "worst_price": float(worst) if worst is not None else None,
        "average_price": float(avg) if avg is not None else None,
        "total_notional": float(notional), "slippage_from_best": float(slip) if slip is not None else None,
        "action": action, "side": side, "simulated": True,
    }
