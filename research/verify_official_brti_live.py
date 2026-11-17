"""Bounded independent official BRTI-vs-Kalshi result audit.

Only public Kalshi contract GETs and authenticated CF Benchmarks BRTI
historical GETs. NO order, portfolio, withdrawal, credential storage,
raw index export, or deployment. No raw HTTP body or secrets are logged.
A reconstruction mismatch or missing entitlement is NOT treated as a pass.
"""
from __future__ import annotations
import base64
import datetime as dt
import json
import os
import sys
from urllib.parse import quote
import requests

from app.settlement_reference import reconcile_contract

API = "https://external-api.kalshi.com/trade-api/v2"
HISTORY_PATH = "/trade-api/v2/cfbenchmarks/history/values"
HISTORY = API + "/cfbenchmarks/history/values"
MAX_BYTES = 8_000_000


def _signed_headers(key_id, private_key, path):
    # Deferred import: signing packages are NOT runtime dependencies.
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519, rsa, padding
    import time
    text = private_key.replace("\\n", "\n").strip()
    key = serialization.load_pem_private_key(text.encode(), password=None)
    timestamp = str(int(time.time() * 1000))
    payload = (timestamp + "GET" + path).encode()
    if isinstance(key, ed25519.Ed25519PrivateKey):
        signature = key.sign(payload)
    elif isinstance(key, rsa.RSAPrivateKey):
        signature = key.sign(payload, padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=hashes.SHA256().digest_size), hashes.SHA256())
    else:
        raise ValueError("Only Kalshi RSA/Ed25519 signing keys are supported")
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
    }


def _get(session, url, params=None, headers=None):
    if not url.startswith(API + "/") or "?" in url:
        raise ValueError("Unexpected source URL")
    r = session.get(url, params=params, headers=headers, timeout=(8, 25))
    r.raise_for_status()
    if len(r.content) > MAX_BYTES:
        raise ValueError("Official response exceeded safety size")
    obj = r.json()
    if not isinstance(obj, dict):
        raise ValueError("Official response is not a JSON object")
    return obj


def _walk_values(node):
    if isinstance(node, list):
        for row in node:
            yield from _walk_values(row)
    elif isinstance(node, dict):
        if "time" in node and "value" in node:
            yield {"time": node["time"], "value": node["value"]}
        else:
            for name in ("data", "payload", "values", "history", "items", "results"):
                if name in node:
                    yield from _walk_values(node[name])


def _seconds(value):
    date = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not date.tzinfo:
        raise ValueError("Missing UTC offset in contract clock")
    return int(date.timestamp())


def _public_market(session, ticker):
    encoded = quote(ticker, safe="")
    pending = None
    for endpoint in (f"/markets/{encoded}", f"/historical/markets/{encoded}"):
        try:
            item = _get(session, API + endpoint).get("market")
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                continue
            raise
        if isinstance(item, dict):
            if (str(item.get("status") or "").lower() in ("settled", "finalized")
                    and str(item.get("result") or "").lower() in ("yes", "no")):
                return item
            pending = item
    return pending


def _load_hours(session, key_id, private_key, contract):
    start, end = _seconds(contract["open_time"]), _seconds(contract["close_time"])
    bounds = [(start-60, start-1), (end-60, end-1)]
    hours = set()
    for a,b in bounds:
        for t in (a,b):
            hour = dt.datetime.fromtimestamp(t, dt.timezone.utc).replace(
                minute=0, second=0, microsecond=0)
            hours.add(hour)
    if len(hours) > 4:
        raise ValueError("Unexpected BRTI reference interval count")
    data = []
    for hour in sorted(hours):
        date = hour.strftime("%Y-%m-%dT%H:00:00.000Z")
        obj = _get(session, HISTORY,
                   {"id": "BRTI", "timespan": "HOUR", "timestamp": date},
                   _signed_headers(key_id, private_key, HISTORY_PATH))
        data.extend(_walk_values(obj))
    return data, [x.isoformat().replace("+00:00", "Z") for x in sorted(hours)]


def audit():
    key_id = os.environ.get("KALSHI_API_KEY_ID", "").strip()
    secret = os.environ.get("KALSHI_PRIVATE_KEY_PEM", "").strip()
    summary = {
        "kind": "OFFICIAL_BRTI_REFERENCE_READ_ONLY",
        "research_only": True,
        "authentication_method": "signed_Kalshi_GET_without_credentials_in_artifact",
        "source": "Kalshi CF Benchmarks BRTI historical 5Hz API",
        "status": "NOT_VERIFIED",
        "real_orders": False,
        "actual_fills": False,
        "original_index_precision_exported": False,
        "verified_live_asof_delivery": False,
        "verified_trade_profit": False,
        "tried_contracts": 0,
    }
    if not key_id or not secret:
        summary["reason"] = "Required read-only BRTI GitHub Secrets not configured"
        return summary
    with requests.Session() as session:
        session.headers.update({"User-Agent": "AXIOM-readonly-BRTI-reconciliation/1.0",
                                "Accept": "application/json"})
        listing = _get(session, API+"/markets",
                       {"series_ticker": "KXBTC15M", "status": "settled", "limit": 30})
        markets = listing.get("markets", [])
        if not isinstance(markets, list):
            summary["reason"] = "Official settled-market listing missing"
            return summary
        candidates = sorted(
            (m for m in markets if isinstance(m, dict) and
             str(m.get("ticker", "")).startswith("KXBTC15M-") and
             str(m.get("result") or "").lower() in ("yes", "no")),
            key=lambda m: str(m.get("close_time") or ""), reverse=True)
        import time
        now = time.time()
        for market in candidates[:8]:
            ticker = market["ticker"]
            try:
                if not (120 <= now - _seconds(market["close_time"]) <= 3 * 86400):
                    continue
                summary["tried_contracts"] += 1
                detail = _public_market(session, ticker)
                if not detail:
                    continue
                if (str(detail.get("result") or "").lower() !=
                        str(market.get("result") or "").lower()):
                    summary.update(status="CONFLICT",
                                   reason="Official settled listing/detail outcomes disagree",
                                   ticker=ticker)
                    return summary
                if (not detail.get("open_time") or not detail.get("close_time") or
                        detail.get("floor_strike") is None or
                        detail.get("expiration_value") is None):
                    continue
                ticks, hours = _load_hours(session, key_id, secret, detail)
                result = reconcile_contract(detail, ticks)
                summary.update(status=result["status"], ticker=ticker,
                               requested_utc_hours=hours,
                               opening_seconds=result["windows"].get("opening", {}).get("sampled_seconds"),
                               closing_seconds=result["windows"].get("closing", {}).get("sampled_seconds"),
                               reference_differences_usd={
                                   tag: result["windows"].get(tag, {}).get("absolute_difference_usd")
                                   for tag in ("opening", "closing")},
                               result_consistent=result["winner_verified"],
                               reason=result["reason"])
                # A mismatch is consequential, not a reason to choose a
                # different contract and silently claim a later success.
                return summary
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                summary.update(status="SOURCE_ERROR", ticker=ticker,
                               reason=type(exc).__name__ + " during official read-only audit")
                return summary
    summary["reason"] = "No recent finalized contract with complete official reference fields"
    return summary


def main():
    try:
        result = audit()
    except Exception as exc:
        result = {"status": "SOURCE_ERROR",
                  "reason": type(exc).__name__ + " during bounded official read-only audit",
                  "real_orders": False, "verified_trade_profit": False}
    print("OFFICIAL_BRTI_RECONCILIATION " + json.dumps(result, sort_keys=True))
    path = os.environ.get("AXIOM_BRTI_EVIDENCE_PATH")
    if path:
        with open(path, "w", encoding="utf-8") as out:
            json.dump(result, out, indent=2)
    return 0 if result["status"] == "RECONCILED" else 2


if __name__ == "__main__":
    sys.exit(main())
