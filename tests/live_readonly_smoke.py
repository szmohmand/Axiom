"""Read-only production-provider smoke for BRTI-first AXIOM.

Public Kalshi REST supplies contract terms, depth and settlement.
It does NOT supply the authenticated BRTI reference stream. Coinbase price
is intentionally never queried or used as a substitute live prediction input.
No portfolio, orders, funding, money, or trading actions.
"""
import json
import time

from app.feeds import LiveProvider, KALSHI


def probe():
    provider = LiveProvider()
    result = {
        "source": "real public Kalshi markets, depth, official outcomes (GET only)",
        "read_only": True,
        "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": {}, "warnings": [],
    }
    failed = []
    market = None
    try:
        market = provider.market()
        result["checks"]["kalshi_open_market"] = {
            "ok": bool(market), "ticker": market["ticker"] if market else None,
            "has_published_target": bool(market and market.get("target")),
            "seconds_left": market["seconds_left"] if market else None}
        if not market:
            result["warnings"].append("No active contract during poll; fail-closed market WAIT")
    except Exception as exc:
        result["checks"]["kalshi_open_market"] = {"ok": False, "error": type(exc).__name__}
        failed.append("Cannot read Kalshi open-market metadata")
    if market is not None:
        try:
            book = provider.orderbook(market)
            result["checks"]["kalshi_full_depth"] = {
                "ok": bool(book.get("available")), "ticker": book.get("ticker"),
                "read_only": True, "source": book.get("source"),
                "individual_trader_ids_visible": False}
            if not book.get("available"):
                result["warnings"].append("Unavailable Kalshi depth: execution must WAIT")
        except Exception as exc:
            result["checks"]["kalshi_full_depth"] = {
                "ok": False, "error": type(exc).__name__}
            failed.append("Cannot query Kalshi full-depth order book")
    try:
        payload = provider.get(KALSHI + "/markets",
            {"series_ticker": "KXBTC15M", "status": "settled",
             "mve_filter": "exclude", "limit": 10})
        resolved = [m for m in payload.get("markets", [])
                    if m.get("result") in ("yes", "no")]
        if resolved:
            item = resolved[0]
            outcome = provider.settlement(item["ticker"])
            good = outcome == item["result"]
            result["checks"]["kalshi_official_settlement"] = {
                "ok": good, "official_result_present": True}
            if not good:
                failed.append("Official settlement lookup disagrees with market outcome")
        else:
            result["checks"]["kalshi_official_settlement"] = {"ok": None}
            result["warnings"].append("No recently settled contract returned")
    except Exception as exc:
        result["checks"]["kalshi_official_settlement"] = {
            "ok": False, "error": type(exc).__name__}
        failed.append("Kalshi settlement readback unavailable")
    result["checks"]["btc_reference"] = {
        "provider": "AUTHENTICATED_CF_BENCHMARKS_BRTI",
        "no_coinbase_fallback": True,
        "authentication_in_this_public_probe": False,
        "forecasts_when_not_streaming": "WAIT"}
    result["failed_checks"] = failed
    print(json.dumps(result, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    probe()
