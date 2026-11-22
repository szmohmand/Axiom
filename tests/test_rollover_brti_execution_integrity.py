"""Permanent regressions: real-source rollover, official BRTI and fill provenance."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import pytest

from app.settlement_reference import reconcile_contract
from app.execution_evidence import examine_liquidity
from app.orderbook import normalize_orderbook
from app.feeds import LiveProvider, KALSHI
from test_feed_contracts_audit import FakeResponse, provider, market
from test_e2e_synthetic import env


OPEN = "2026-11-17T17:45:00Z"
CLOSE = "2026-11-17T18:00:00Z"
TICKER = "KXBTC15M-26NOV171800-00"


def _sec(s):
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def _ticks(open_price="90000", close_price="90100"):
    rows = []
    for boundary, value in ((_sec(OPEN), open_price), (_sec(CLOSE), close_price)):
        for sec in range(boundary - 60, boundary):
            for i in range(5):
                rows.append({"time": sec * 1000 + 200 * i, "value": value})
    return rows


def _terms(**changes):
    m = {"ticker": TICKER, "open_time": OPEN, "close_time": CLOSE,
         "floor_strike": "90000", "expiration_value": "90100",
         "result": "yes", "status": "settled"}
    m.update(changes)
    return m


def test_official_5hz_brti_reconstructs_both_sixty_second_windows_without_proxy():
    report = reconcile_contract(_terms(), _ticks())
    assert report["status"] == "RECONCILED"
    assert report["winner_verified"]
    assert report["candidate_reconstructed_winner"] == "yes"
    assert report["published_reference_winner"] == "yes"
    assert report["windows"]["opening"]["sampled_seconds"] == 60
    assert report["windows"]["closing"]["sampled_seconds"] == 60
    assert report["source"].startswith("CF_BENCHMARKS_BRTI")
    assert report["event_time_not_asof_delivery"] is True
    assert report["trade_fills_verified"] is False


def test_official_result_conflict_never_becomes_a_verified_winner():
    r = reconcile_contract(_terms(result="no"), _ticks())
    assert r["status"] == "CONFLICT"
    assert r["winner_verified"] is False


def test_official_reference_discrepancy_is_not_silently_rebased():
    r = reconcile_contract(_terms(floor_strike="90005"), _ticks())
    assert r["status"] == "CONFLICT"
    assert r["windows"]["opening"]["matches_to_half_cent"] is False


def test_no_invented_index_values_if_one_real_second_is_missing():
    t = [x for x in _ticks() if x["time"] // 1000 != _sec(CLOSE)-1]
    r = reconcile_contract(_terms(), t)
    assert r["status"] == "INCOMPLETE" and not r["winner_verified"]
    assert r["windows"]["closing"]["sampled_seconds"] == 59


@pytest.mark.parametrize("change", [
    {"status": "open"}, {"result": ""},
    {"expiration_value": None}, {"close_time": "2026-11-17T17:59:59Z"},
    {"open_time": "not a date"}, {"ticker": "KXBTC-OTHER"},
])
def test_pending_or_invalid_official_market_cannot_verify(change):
    r = reconcile_contract(_terms(**change), _ticks())
    assert r["status"] in ("PENDING", "INCOMPLETE") and not r["winner_verified"]


def test_duplicate_or_malformed_index_ticks_are_rejected():
    t = _ticks()
    for values in (t + [dict(t[0])], t[:-1] + [{"time": "bad", "value": "90000"}]):
        r = reconcile_contract(_terms(), values)
        assert r["status"] == "INCOMPLETE" and not r["winner_verified"]


def test_live_provider_bounded_rollover_retry_finds_actual_new_published_market(monkeypatch):
    import app.feeds as feeds
    now = _sec(CLOSE) + 8
    monkeypatch.setattr(feeds, "time", SimpleNamespace(time=lambda: now, sleep=lambda x: None))
    new = market("KXBTC15M-REAL-AFTER", now + 870)
    p = provider({KALSHI+"/markets": [FakeResponse({"markets": []}),
                                      FakeResponse({"markets": [new]})]})
    found = p.market(now)
    assert found and found["ticker"] == "KXBTC15M-REAL-AFTER"
    assert len(p.session.calls) == 2
    assert all(call[1]["status"] == "open" for call in p.session.calls)


def test_rollover_retry_stays_fail_closed_when_market_still_not_published(monkeypatch):
    import app.feeds as feeds
    now = _sec(CLOSE) + 8
    monkeypatch.setattr(feeds, "time", SimpleNamespace(time=lambda: now, sleep=lambda x: None))
    p = provider({KALSHI+"/markets": [FakeResponse({"markets": []}),
                                      FakeResponse({"markets": []})],
                  KALSHI+"/events": FakeResponse({"events": []})})
    assert p.market(now) is None
    assert len(p.session.calls) == 3


def test_no_duplicate_market_retry_outside_boundary_and_empty_event_fallback(monkeypatch):
    import app.feeds as feeds
    now = _sec(CLOSE) + 140
    monkeypatch.setattr(feeds, "time", SimpleNamespace(time=lambda: now, sleep=lambda x: None))
    p = provider({KALSHI+"/markets": FakeResponse({"markets": []}),
                  KALSHI+"/events": FakeResponse({"events": []})})
    assert p.market(now) is None
    assert [c[0] for c in p.session.calls] == [KALSHI+"/markets", KALSHI+"/events"]


def test_closed_but_not_finalized_primary_uses_historical_finalized_source():
    tick = "KXBTC15M-26NOV171800-00"
    primary = f"{KALSHI}/markets/{tick}"
    history = f"{KALSHI}/historical/markets/{tick}"
    p = provider({primary: FakeResponse({"market": {"status": "closed", "result": "yes"}}),
                  history: FakeResponse({"market": {"status": "settled", "result": "yes"}})})
    assert p.settlement(tick) == "yes"
    assert [x[0] for x in p.session.calls] == [primary, history]


def test_settlement_stays_pending_if_primary_and_historical_are_not_finalized():
    tick = "KXBTC15M-26NOV171800-00"
    primary = f"{KALSHI}/markets/{tick}"
    history = f"{KALSHI}/historical/markets/{tick}"
    p = provider({primary: FakeResponse({"market": {"status": "closed", "result": "yes"}}),
                  history: FakeResponse({"market": {"status": "closed", "result": "no"}})})
    assert p.settlement(tick) is None


def test_same_snapshot_walk_never_claims_genuine_trade_profit_or_fee_knowledge():
    book = normalize_orderbook({"orderbook_fp": {
        "yes_dollars": [["0.42", "50"], ["0.41", "50"]],
        "no_dollars": [["0.49", "50"], ["0.48", "50"]]}}, TICKER, 1000)
    report = examine_liquidity(book, {"ticker": TICKER}, now=1002)
    assert report["book_replay_status"] == "SIMULATED_SAME_SNAPSHOT"
    assert report["authenticated_fill_records"] == 0
    assert report["realized_net_profit_usd"] is None
    assert not report["actual_entry_and_exit_fills_verified"]
    assert not report["official_applied_trade_fees_verified"]
    assert report["scenarios"]["YES"]["same_snapshot_spread_crossing_cost_usd"] > 0
    assert report["scenarios"]["YES"]["realized_pnl_usd"] is None


def test_missing_or_wrong_contract_book_cannot_yield_executable_return():
    for book in (None, {"available": True, "ticker": "OTHER", "received_at": 999}):
        report = examine_liquidity(book, {"ticker": TICKER}, now=1001)
        assert report["book_replay_status"] == "UNAVAILABLE"
        assert report["realized_net_profit_usd"] is None


def test_paper_profit_cannot_be_mistaken_for_exchange_fill_performance(env):
    main, clock, p, client, _ = env
    clock.now = p.close-600
    main.update_once()
    auth = {"Authorization": "Bearer synthetic-local-testing-token"}
    entry = client.post("/api/paper", json={"side": "YES"}, headers=auth)
    assert entry.status_code == 200
    clock.now = p.close+6
    p.result = "yes"
    main.grade_once()
    result = client.get("/api/state").json()
    assert result["stats"]["settled_paper_trades"] == 1
    assert result["execution_evidence"]["realized_net_profit_usd"] is None
    assert result["execution_evidence"]["authenticated_fill_records"] == 0
    assert result["execution_evidence"]["paper_gross_pnl_is_realized_profit"] is False


def test_dashboard_labels_real_net_as_unmeasured_and_paper_as_assumed():
    from pathlib import Path
    s = (Path(__file__).resolve().parents[1]/"app/static/index.html").read_text()
    assert 'id="executionEvidence"' in s
    assert "Real net P&L: NOT MEASURED" in s
    assert "Before fees" in s
    assert "Assumed quoted-ask fill" in s


def test_authenticated_index_check_does_not_claim_success_without_credentials(monkeypatch):
    from research.verify_official_brti_live import audit
    monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM", raising=False)
    r = audit()
    assert r["status"] == "NOT_VERIFIED"
    assert r["real_orders"] is False
    assert r["verified_trade_profit"] is False


def test_official_market_detail_prefers_finalized_historical_over_lagging_live_detail():
    from research.verify_official_brti_live import _public_market, API

    class Response:
        status_code = 200
        content = b"{}"
        def __init__(self, status, result):
            self.payload = {"market": {**_terms(), "status": status, "result": result}}
        def raise_for_status(self):
            return None
        def json(self):
            return self.payload

    class Session:
        def __init__(self):
            self.urls = []
        def get(self, url, params=None, headers=None, timeout=None):
            self.urls.append(url)
            if "/historical/" in url:
                return Response("settled", "yes")
            return Response("closed", "yes")

    s = Session()
    m = _public_market(s, TICKER)
    assert m["status"] == "settled" and m["result"] == "yes"
    assert len(s.urls) == 2
    assert all(url.startswith(API + "/") for url in s.urls)


def test_newest_unpublished_brti_hour_is_recorded_while_older_complete_contract_is_reconciled(monkeypatch):
    from research import verify_official_brti_live as verifier

    latest = _terms(ticker="KXBTC15M-26NOV171815-15",
                    open_time="2026-11-17T18:00:00Z",
                    close_time="2026-11-17T18:15:00Z")
    older = _terms()
    monkeypatch.setattr("time.time", lambda: _sec(latest["close_time"]) + 3600)
    monkeypatch.setenv("KALSHI_API_KEY_ID", "synthetic-id-not-used")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", "synthetic-secret-not-used")

    class Session:
        def __init__(self):
            self.headers = {}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    monkeypatch.setattr(verifier.requests, "Session", Session)
    monkeypatch.setattr(verifier, "_get", lambda *a, **kw: {"markets": [older, latest]})
    monkeypatch.setattr(verifier, "_public_market",
                        lambda session, ticker: latest if ticker == latest["ticker"] else older)
    def hours(session, keyid, key, market):
        if market["ticker"] == latest["ticker"]:
            # Latest contract is finalized but current-hour index publication
            # has no closing seconds yet. This is not a fake settlement match.
            return [x for x in _ticks() if x["time"] // 1000 < _sec(CLOSE)], ["2026-11-17T18:00:00Z"]
        return _ticks(), ["2026-11-17T17:00:00Z"]
    monkeypatch.setattr(verifier, "_load_hours", hours)
    report = verifier.audit()
    assert report["status"] == "RECONCILED"
    assert report["ticker"] == older["ticker"]
    assert report["tried_contracts"] == 2
    assert report["pending_index_publication"][0]["ticker"] == latest["ticker"]
    assert report["pending_index_publication"][0]["closing_seconds"] < 60
    assert report["result_consistent"] is True


def test_actual_index_conflict_is_not_skipped_to_later_passing_contract(monkeypatch):
    from research import verify_official_brti_live as verifier
    latest = _terms(ticker="KXBTC15M-26NOV171815-15",
                    open_time="2026-11-17T18:00:00Z",
                    close_time="2026-11-17T18:15:00Z")
    older = _terms()
    monkeypatch.setattr("time.time", lambda: _sec(latest["close_time"]) + 3600)
    monkeypatch.setenv("KALSHI_API_KEY_ID", "synthetic-id")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", "synthetic-secret")
    class Session:
        def __init__(self):
            self.headers={}
        def __enter__(self):
            return self
        def __exit__(self,*a):
            return False
    monkeypatch.setattr(verifier.requests,"Session",Session)
    monkeypatch.setattr(verifier,"_get",lambda *a,**k:{"markets":[older,latest]})
    monkeypatch.setattr(verifier,"_public_market",
                        lambda s,t:latest if t==latest["ticker"] else older)
    # Complete data for the newer contract's own time windows but
    # an official outcome that conflicts with the BRTI reconstruction.
    later_ticks=[]
    start=_sec(latest["open_time"])
    stop=_sec(latest["close_time"])
    for boundary,value in ((start,"90000"),(stop,"90100")):
        for second in range(boundary-60,boundary):
            later_ticks.extend({"time":second*1000+i*200,"value":value} for i in range(5))
    called=[]
    def hours(s,k,p,m):
        called.append(m["ticker"])
        return later_ticks,["2026-11-17T18:00:00Z"]
    monkeypatch.setattr(verifier,"_load_hours",hours)
    monkeypatch.setattr(verifier,"reconcile_contract",
                        lambda m,t:{**reconcile_contract(m,t),"status":"CONFLICT",
                                    "winner_verified":False,"reason":"Deliberate official conflict"})
    result=verifier.audit()
    assert result["status"]=="CONFLICT"
    assert called==[latest["ticker"]]


def test_live_kalshi_nested_event_recovers_real_contract_missed_by_market_index(monkeypatch):
    import app.feeds as feeds
    now = _sec(CLOSE) + 140
    monkeypatch.setattr(feeds, "time", SimpleNamespace(time=lambda: now, sleep=lambda _: None))
    valid = market("KXBTC15M-PUBLISHED-CURRENT", now+760)
    valid["open_time"] = datetime.fromtimestamp(now-120, timezone.utc).isoformat()
    future = market("KXBTC15M-FUTURE", now+300)
    future["open_time"] = datetime.fromtimestamp(now+100, timezone.utc).isoformat()
    closed = market("KXBTC15M-CLOSED", now+300)
    closed["status"] = "closed"
    expired = market("KXBTC15M-EXPIRED", now-5)
    too_far = market("KXBTC15M-TOO-FAR", now+1600)
    p = provider({KALSHI+"/markets": FakeResponse({"markets": []}),
                  KALSHI+"/events": FakeResponse({"events": [
                      {"series_ticker": "OTHER", "markets": [market("KXBTC15M-OTHER", now+90)]},
                      {"series_ticker": "KXBTC15M", "markets": [
                          None, future, expired, closed, too_far, valid]}]})})
    found = p.market(now)
    assert found and found["ticker"] == valid["ticker"]
    assert found["seconds_left"] == 760
    assert len(p.session.calls) == 2
    assert p.session.calls[0][1]["limit"] == 200
    assert p.session.calls[0][1]["min_close_ts"] == int(now)
    assert p.session.calls[0][1]["mve_filter"] == "exclude"
    assert p.session.calls[1][1]["with_nested_markets"] == "true"


def test_current_market_listing_skips_future_open_time_and_selects_active(monkeypatch):
    import app.feeds as feeds
    now = _sec(CLOSE) + 140
    monkeypatch.setattr(feeds, "time", SimpleNamespace(time=lambda: now, sleep=lambda _: None))
    future = market("KXBTC15M-FUTURE", now+200)
    future["open_time"] = datetime.fromtimestamp(now+10,timezone.utc).isoformat()
    active = market("KXBTC15M-ACTIVE", now+400)
    active["open_time"] = datetime.fromtimestamp(now-200,timezone.utc).isoformat()
    p = provider({KALSHI+"/markets": FakeResponse({"markets": [future, active]})})
    assert p.market(now)["ticker"] == active["ticker"]
    assert len(p.session.calls) == 1


def test_live_event_fallback_http_error_and_historical_poll_fail_closed(monkeypatch):
    import app.feeds as feeds
    now = _sec(CLOSE) + 140
    monkeypatch.setattr(feeds, "time", SimpleNamespace(time=lambda: now, sleep=lambda _: None))
    p = provider({KALSHI+"/markets": FakeResponse({"markets": []}),
                  KALSHI+"/events": FakeResponse(status=503)})
    assert p.market(now) is None
    assert len(p.session.calls) == 2
    # A replayed timestamp must not read today's event listing.
    historical = now-1000
    p = provider({KALSHI+"/markets": FakeResponse({"markets": []})})
    assert p.market(historical) is None
    assert len(p.session.calls) == 1
