"""One-shot BRTI entitlement/access probe using repository Actions secrets.

Security and scope:
- Strictly read-only GET requests for CF Benchmarks BRTI and one bounded
  WebSocket subscription to cfbenchmarks_value. No orders, portfolios,
  account reads, databases, app imports, deployments or persistence.
- No private keys, API key IDs, signed headers or raw error responses printed.
- Does not save exchange feed contents or any credentials to files/artifacts.
- Only reports sanitized status, schema keys, and a couple of BRTI values.
- Never schedule, retry indefinitely, or log the full HTTP response.
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa, padding

BASE = "https://external-api.kalshi.com"
REST_PATH = "/trade-api/v2/cfbenchmarks/values"
HISTORY_PATH = "/trade-api/v2/cfbenchmarks/history/values"
WS_URL = "wss://external-feeds.kalshi.com/trade-api/v2/external-feeds"
WS_PATH = "/trade-api/v2/external-feeds"
INDEX = "BRTI"
MAX_RESPONSE_BYTES = 10_000_000
WHITELISTED_PRICE_FIELDS = (
    "value", "price", "indexValue", "index_value",
    "last_60s_windowed_average_15min", "last_60s_windowed_average",
)
WHITELISTED_TIME_FIELDS = ("timestamp", "ts", "time", "serverTime", "asOf")


def load_key(text: str):
    """Parse only in-process; never log the key text or parsed key object."""
    pem = text.strip()
    if "\\n" in pem and "\n" not in pem:
        pem = pem.replace("\\n", "\n")
    key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    if isinstance(key, ed25519.Ed25519PrivateKey):
        return key, "Ed25519"
    if isinstance(key, rsa.RSAPrivateKey):
        return key, "RSA-PSS"
    raise ValueError("unsupported_asymmetric_key")


def sign_headers(key_id, key, method: str, path: str, timestamp_ms: str | None = None):
    """Kalshi signs timestamp + uppercase HTTP method + path WITHOUT query."""
    if method != "GET":
        raise ValueError("read_only_get_required")
    if not path.startswith("/trade-api/"):
        raise ValueError("only_kalshi_trade_api_paths_allowed")
    t = timestamp_ms if timestamp_ms is not None else str(int(time.time() * 1000))
    data = (t + "GET" + path.split("?", 1)[0]).encode()
    if isinstance(key, ed25519.Ed25519PrivateKey):
        sig = key.sign(data)
    elif isinstance(key, rsa.RSAPrivateKey):
        sig = key.sign(data, padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=hashes.SHA256().digest_size), hashes.SHA256())
    else:
        raise ValueError("unsupported_asymmetric_key")
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": t,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
    }


def safe_error_code(body):
    """Error code only, never a raw body or account-specific details."""
    if not isinstance(body, dict):
        return None
    item = body.get("error")
    if isinstance(item, dict):
        code = item.get("code")
    else:
        code = body.get("code")
    if isinstance(code, (int, str)) and len(str(code)) <= 70:
        return str(code)
    return None


def safe_values(node, limit=2):
    """Traverse only recognized market data keys, NEVER arbitrary payload text."""
    found = []
    seen_keys = set()
    def visit(value, depth=0):
        if depth > 7 or len(found) >= limit:
            return
        if isinstance(value, list):
            for child in value[:8]:
                visit(child, depth+1)
                if len(found) >= limit:
                    break
        elif isinstance(value, dict):
            seen_keys.update(k for k in value if isinstance(k, str) and len(k) < 60)
            prices = {}
            for k in WHITELISTED_PRICE_FIELDS:
                v = value.get(k)
                if isinstance(v, (float, int)) and not isinstance(v, bool):
                    prices[k] = v
                elif isinstance(v, str):
                    try:
                        num = float(v)
                        if abs(num) < 1e9:
                            prices[k] = round(num, 8)
                    except ValueError:
                        pass
            if prices:
                point = dict(prices)
                for k in WHITELISTED_TIME_FIELDS:
                    ts = value.get(k)
                    if isinstance(ts, (int, float)) or (
                        isinstance(ts, str) and len(ts) <= 45
                    ):
                        point[k] = ts
                        break
                found.append(point)
            if len(found) < limit:
                for k in ("data", "payload", "values", "history", "items", "results", "points"):
                    if k in value:
                        visit(value[k], depth+1)
    visit(node)
    return found, sorted(seen_keys)[:35]


def rest_probe(key_id, key, path, params):
    """Exactly one GET; fail closed. No printed auth headers or HTTP body."""
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        BASE + path + "?" + qs,
        headers=sign_headers(key_id, key, "GET", path),
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=24) as res:
            raw = res.read(MAX_RESPONSE_BYTES + 1)
            status = res.status
        if len(raw) > MAX_RESPONSE_BYTES:
            return {"status":"response_too_large","http_status":status}
        data = json.loads(raw)
        samples, fields = safe_values(data)
        has_envelope = isinstance(data, dict) and "data" in data
        return {
            "status": "http_ok" if status == 200 else "http_non_200",
            "http_status": status,
            "kalshi_data_envelope": has_envelope,
            "source_schema_fields": fields,
            "official_index_id_requested": INDEX,
            "numeric_price_samples": samples,
            "has_verified_numeric_value": bool(samples),
            "reported_point_count": count_points(data),
        }
    except urllib.error.HTTPError as exc:
        response = None
        try:
            raw = exc.read(32768)
            response = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            pass
        return {"status": "http_error",
                "http_status": int(exc.code),
                "error_code": safe_error_code(response)}
    except (TimeoutError, urllib.error.URLError):
        return {"status": "network_or_timeout"}
    except (ValueError, json.JSONDecodeError):
        return {"status": "invalid_json_or_response_format"}


def count_points(data):
    """Only count records in obvious source arrays, not inferred data points."""
    if isinstance(data, dict):
        for key in ("values", "history", "points", "items", "results"):
            arr = data.get(key)
            if isinstance(arr, list):
                return len(arr)
        for key in ("data","payload"):
            val = data.get(key)
            if val is not None:
                c = count_points(val)
                if c is not None:
                    return c
    if isinstance(data, list):
        return len(data)
    return None


async def ws_probe(key_id, key):
    """One bounded external-feeds WS subscription; never open any trade channel."""
    try:
        import websockets
        from websockets.exceptions import InvalidStatus
    except ImportError:
        return {"status": "optional_websockets_package_unavailable"}
    sub = {
        "id": 1, "cmd": "subscribe",
        "params": {"channels": ["cfbenchmarks_value"], "index_ids": [INDEX]},
    }
    results = {
        "status": "no_data_received",
        "index": INDEX,
        "subscription_accepted": False,
        "price_messages": 0,
        "samples": [],
        "last_60s_average_field_seen": False,
    }
    try:
        async with websockets.connect(
            WS_URL,
            additional_headers=sign_headers(key_id, key, "GET", WS_PATH),
            open_timeout=12,
            close_timeout=3,
            max_size=2_000_000,
        ) as socket:
            await socket.send(json.dumps(sub))
            deadline = time.monotonic() + 16
            while time.monotonic() < deadline and results["price_messages"] < 3:
                try:
                    raw = await asyncio.wait_for(
                        socket.recv(), timeout=max(.25, deadline-time.monotonic()))
                except asyncio.TimeoutError:
                    break
                obj = json.loads(raw)
                typ = obj.get("type") if isinstance(obj, dict) else None
                if typ in ("subscribed", "ok"):
                    results["subscription_accepted"] = True
                elif typ == "error":
                    msg = obj.get("msg", {}) if isinstance(obj, dict) else {}
                    code = msg.get("code") if isinstance(msg, dict) else None
                    return {
                        "status": "subscription_error",
                        "subscription_error_code": code if isinstance(code,(int,str)) else None,
                        "index": INDEX,
                    }
                elif typ and "cfbenchmarks" in typ:
                    samples, fields = safe_values(obj.get("msg", obj), limit=1)
                    results["price_messages"] += 1
                    results["samples"].extend(samples[:1])
                    results["last_60s_average_field_seen"] |= (
                        "last_60s_windowed_average_15min" in fields
                    )
                    results["status"] = "index_messages_received"
        return results
    except InvalidStatus as exc:
        return {
            "status": "websocket_http_rejected",
            "http_status": exc.response.status_code,
        }
    except (OSError, TimeoutError, asyncio.TimeoutError):
        return {"status": "websocket_network_or_timeout"}
    except Exception:
        # Avoid leaking response bytes, credential-bearing headers or URLs.
        return {"status": "websocket_unexpected_error"}


def run():
    key_id = os.environ.get("KALSHI_API_KEY_ID", "").strip()
    private_text = os.environ.get("KALSHI_PRIVATE_KEY_PEM", "")
    print("BRTI_PROBE_SCOPE read_only_index_only_no_orders_no_persistence")
    if not key_id or not private_text:
        print("BRTI_PROBE_JSON " + json.dumps({
            "status": "missing_required_github_secrets",
            "key_id_secret_present": bool(key_id),
            "private_key_secret_present": bool(private_text)
        }))
        return 2
    try:
        key, kind = load_key(private_text)
    except (ValueError, TypeError):
        print("BRTI_PROBE_JSON " + json.dumps({
            "status":"invalid_private_key_pem_or_secret_format",
            "key_id_secret_present": True,
            "private_key_secret_present": True,
        }))
        return 3

    # Query a complete historical hour beginning two hours before now.
    now = dt.datetime.now(dt.timezone.utc)
    hr = (now - dt.timedelta(hours=2)).replace(minute=0,second=0,microsecond=0)
    timestamp = hr.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    latest = rest_probe(key_id, key, REST_PATH, {"id": INDEX})
    history = rest_probe(key_id, key, HISTORY_PATH, {
        "id": INDEX, "timespan":"HOUR", "timestamp": timestamp})
    live = asyncio.run(ws_probe(key_id,key))
    results = {
        "kind": kind, "key_id_secret_present":True,
        "private_key_secret_present": True,
        "rest_latest": latest, "history_hour_start_utc": timestamp,
        "rest_historical": history, "websocket": live,
        "security": "only signed GET and BRTI subscription; no trading endpoints",
    }
    print("BRTI_PROBE_JSON " + json.dumps(results, sort_keys=True))
    # This is a diagnostic, not a CI error when entitlement is denied.
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
