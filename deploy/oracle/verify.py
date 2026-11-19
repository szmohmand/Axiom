"""Localhost-only read-only AXIOM health check; no order endpoints."""
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

def request(path):
    try:
        with urlopen("http://127.0.0.1:8000" + path, timeout=12) as resp:
            return resp.status, json.loads(resp.read())
    except HTTPError as err:
        return err.code, json.loads(err.read())

def main():
    try:
        hcode, health = request("/health")
        scode, state = request("/api/state")
    except (URLError, OSError, ValueError) as exc:
        print("UNREACHABLE:", type(exc).__name__)
        return 1
    brti = state.get("live_briti") or {}
    report = dict(health_http=hcode, state_http=scode, healthy=health.get("ok"),
                  state_status=state.get("status"), auto_paper=state.get("paper_auto_enabled"),
                  brti_status=brti.get("status"), brti_channels=brti.get("received_counts"),
                  orders_placed=(state.get("execution_intelligence") or {}).get("order_placed"))
    print(json.dumps(report, indent=2, sort_keys=True))
    if (report["auto_paper"] is not False or report["orders_placed"] is not False
            or brti.get("votes_in_ensemble") is not False):
        print("FAIL: read-only constraints not verified")
        return 2
    if hcode != 200 or scode != 200 or not health.get("ok"):
        print("DEGRADED: service responds but live evidence is not healthy")
        return 3
    print("PASS: local live HTTP and read-only constraints")
    return 0

if __name__ == "__main__":
    sys.exit(main())
