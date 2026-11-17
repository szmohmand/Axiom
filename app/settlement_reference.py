"""Read-only, retrospective reconciliation of official KXBTC15M contract terms.

This module does not fetch, infer, or sign index data. Callers must supply
original CF Benchmarks BRTI history from an authenticated source and official
Kalshi contract terms. A first-tick-per-second average is a documented research
reconstruction, not an assertion about every exchange sampling convention.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

HALF_CENT = Decimal("0.005")


def _time(value):
    if isinstance(value, bool) or not isinstance(value, str):
        raise ValueError("A timestamp with UTC offset is required")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("A timezone-aware contract timestamp is required")
    if dt.microsecond:
        raise ValueError("Contract boundary must be an exact second")
    return int(dt.timestamp())


def _money(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("Missing source reference price")
    try:
        v = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError("Invalid reference price") from None
    if not v.is_finite() or not (Decimal("100") < v < Decimal("1000000")):
        raise ValueError("Nonfinite/out-of-bounds official index price")
    return v


def reconcile_contract(market, ticks):
    """Compare genuine BRTI candidate 60-second averages to official outcomes.

    Returns RECONCILED, PENDING, INCOMPLETE, or CONFLICT; never a trading
    signal. An event timestamp is NOT proof of publication/receipt as-of time.
    """
    outcome = {
        "status": "INCOMPLETE", "research_only": True, "authoritative_source_required": True,
        "source": "CF_BENCHMARKS_BRTI_HISTORY_VIA_KALSHI_AUTHENTICATED_GET",
        "reconstruction": "first recorded BRTI tick in each of 60 whole seconds preceding boundary",
        "event_time_not_asof_delivery": True, "trade_fills_verified": False,
        "winner_verified": False, "ticker": None, "reason": None, "windows": {},
    }
    if not isinstance(market, dict):
        return {**outcome, "reason": "Official contract terms missing"}
    ticker = market.get("ticker")
    outcome["ticker"] = ticker if isinstance(ticker, str) else None
    if not isinstance(ticker, str) or not ticker.startswith("KXBTC15M-"):
        return {**outcome, "reason": "Not an official BTC15M contract"}
    if str(market.get("status") or "").lower() not in ("settled", "finalized"):
        return {**outcome, "status": "PENDING", "reason": "Contract not officially finalized"}
    reported = str(market.get("result") or "").lower()
    if reported not in ("yes", "no"):
        return {**outcome, "status": "PENDING", "reason": "Official winner not published"}
    if not isinstance(ticks, (list, tuple)):
        return {**outcome, "reason": "Official index tick array missing"}
    try:
        opening = _time(market.get("open_time"))
        closing = _time(market.get("close_time"))
        if closing - opening != 900:
            return {**outcome, "reason": "Not an exact 900-second contract window"}
        published = {"opening": _money(market.get("floor_strike")),
                     "closing": _money(market.get("expiration_value"))}
    except (ValueError, TypeError, OverflowError) as exc:
        return {**outcome, "reason": str(exc)[:110]}
    first = {}
    seen = set()
    for row in ticks:
        if not isinstance(row, dict):
            return {**outcome, "reason": "Malformed BRTI observation"}
        try:
            raw_ms = row["time"]
            if isinstance(raw_ms, bool) or not str(raw_ms).isdigit():
                raise ValueError("Invalid millisecond event time")
            ms = int(raw_ms)
            val = _money(row["value"])
        except (KeyError, ValueError, TypeError) as exc:
            return {**outcome, "reason": "Malformed BRTI observation: " + str(exc)[:80]}
        if ms in seen:
            return {**outcome, "reason": "Duplicate BRTI event timestamp"}
        seen.add(ms)
        sec = ms // 1000
        if sec not in first or ms < first[sec][0]:
            first[sec] = (ms, val)
    averages = {}
    for tag, boundary in (("opening", opening), ("closing", closing)):
        seconds = [first[s][1] for s in range(boundary - 60, boundary) if s in first]
        info = {"sampled_seconds": len(seconds), "expected_seconds": 60,
                "official_reference": str(published[tag]), "complete": len(seconds) == 60}
        if len(seconds) == 60:
            avg = sum(seconds, Decimal(0)) / Decimal(60)
            diff = abs(avg - published[tag])
            averages[tag] = avg
            info.update(reconstructed_reference=str(avg),
                        absolute_difference_usd=str(diff),
                        matches_to_half_cent=diff <= HALF_CENT)
        outcome["windows"][tag] = info
    if len(averages) < 2:
        return {**outcome, "reason": "Missing true BRTI seconds in a reference window"}
    if not all(outcome["windows"][tag]["matches_to_half_cent"] for tag in ("opening", "closing")):
        return {**outcome, "status": "CONFLICT", "reason": "Reconstructed BRTI differs from official contract reference"}
    # Compare independent reconstructed winner and authoritative published
    # reference winner, both against official Kalshi contract result.
    candidate = "yes" if averages["closing"] >= averages["opening"] else "no"
    official_values_winner = "yes" if published["closing"] >= published["opening"] else "no"
    outcome.update(candidate_reconstructed_winner=candidate,
                   published_reference_winner=official_values_winner,
                   official_result=reported)
    if candidate != reported or official_values_winner != reported:
        return {**outcome, "status": "CONFLICT", "reason": "Official result and reference winner disagree"}
    return {**outcome, "status": "RECONCILED", "winner_verified": True,
            "reason": "Official result agrees with reconstructed and published references; historical only"}
