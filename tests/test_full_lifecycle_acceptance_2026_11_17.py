"""Independent AXIOM three-lane full-cycle acceptance tests.

Research-only validation. Never uses real accounts, credentials, orders, or
deployment; applies existing synthetic clock and isolated temporary SQLite.
Preserves ALL original regression tests without replacement or weakening.
"""
import csv
import io

import pytest

from test_e2e_synthetic import env  # Existing isolated clock/provider/SQLite fixture
from app.orderbook import normalize_orderbook, unavailable


def depth_for(market, now, *, yes=None, no=None):
    if yes is None:
        yes = [["0.46", "25"], ["0.45", "40"]]
    if no is None:
        no = [["0.42", "25"], ["0.41", "40"]]
    return normalize_orderbook(
        {"orderbook_fp": {"yes_dollars": yes, "no_dollars": no}},
        market["ticker"], now
    )


def test_full_depth_joins_real_engine_paper_http_settlement_export_restart(env):
    """Do not just call functions: exercise entire running app's state and storage."""
    main, clock, provider, client, tmp = env
    clock.now = provider.close - 840
    provider.orderbook = lambda market, now=None: depth_for(market, clock.now)
    assert client.get("/health").status_code == 503  # Before any market poll

    first = main.update_once()
    assert first["ok"] and first["status"] == "DEMO"
    assert first["model"]["available"] and len(first["engines"]) == 4
    assert first["scalp"]["side"] in ("LONG", "SHORT", "WAIT")
    assert first["orderbook"]["available"]
    assert first["orderbook"]["ticker"] == provider.ticker
    assert first["orderbook"]["levels"] == {"YES": 2, "NO": 2}
    assert first["orderbook"]["is_full_aggregated_depth"] is True
    assert first["depth_opportunity"]["read_only"] is True
    assert first["depth_opportunity"]["uses_orderbook_quotes_as_forecast"] is False
    assert first["execution_intelligence"]["read_only"] is True
    assert first["execution_intelligence"]["order_placed"] is False
    assert first["execution_intelligence"]["action"] in ("ENTER", "WAIT")
    assert client.get("/health").status_code == 200
    state = client.get("/api/state")
    assert state.status_code == 200
    payload = state.json()
    assert payload["orderbook"]["ticker"] == provider.ticker
    assert payload["execution_intelligence"]["order_placed"] is False
    assert payload["ledger_available"]
    assert "bookStatus" in client.get("/").text

    # Actual paper endpoint is authenticated; no live-order endpoint exists.
    auth = {"Authorization": "Bearer synthetic-local-testing-token"}
    assert client.post("/api/paper", json={"side": "YES"}).status_code == 401
    manual = client.post("/api/paper", json={"side": "YES"}, headers=auth)
    assert manual.status_code == 200, manual.text
    assert client.post("/api/paper", json={"side": "NO"}, headers=auth).status_code == 409
    exposed = client.get("/api/state").json()
    assert exposed["count"]["paper"] == 1
    simulated_position = exposed["paper_position_execution"]
    assert simulated_position["action"] in ("HOLD", "EXIT", "WAIT")
    assert simulated_position["order_placed"] is False

    # Entire 15-minute clock and scoring path using actual engine, no shortcuts.
    for remaining in (600, 300, 60):
        clock.now = provider.close - remaining
        polled = main.update_once()
        assert polled["ok"] and polled["model"]["available"]
        assert polled["orderbook"]["ticker"] == provider.ticker
        assert polled["execution_intelligence"]["order_placed"] is False
    before = client.get("/api/state").json()
    assert before["engine_scores"]["samples"] == 20
    assert before["stats"]["settled_paper_trades"] == 0
    assert before["count"]["paper"] == 1

    clock.now = provider.close + 6
    provider.result = "yes"
    main.grade_once()
    graded = client.get("/api/state").json()
    assert graded["stats"]["settled_paper_trades"] == 1
    assert graded["trades"][0]["result"] == "yes"
    assert graded["engine_scores"]["samples"] == 20
    assert len(graded["engine_scores"]["scores"]) == 20
    assert main.ledger.unresolved() == []
    main.grade_once()
    assert client.get("/api/state").json()["stats"] == graded["stats"]
    assert client.get("/api/export/paper_trades").status_code == 401
    exported = client.get("/api/export/paper_trades", headers=auth)
    assert exported.status_code == 200
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(rows) == 1 and rows[0]["result"] == "yes"

    from app.storage import Ledger
    reopened = Ledger(str(tmp / "runtime.sqlite3"))
    assert reopened.data()["count"]["paper"] == 1
    assert reopened.data()["stats"]["settled_paper_trades"] == 1
    assert reopened.engine_scores()["samples"] == 20
    reopened.conn.close()


@pytest.mark.parametrize("fault", ["missing", "wrong_ticker", "stale", "invalid", "timeout"])
def test_depth_fail_closed_forecast_scoring_and_ledger_continue(env, fault):
    main, clock, provider, client, _ = env
    clock.now = provider.close - 600
    provider.orderbook = lambda market, now=None: depth_for(market, clock.now)
    baseline = main.update_once()
    assert baseline["ok"] and baseline["orderbook"]["available"]
    p = baseline["model"]["prob_above"]
    initial_scores = baseline["model"].copy()
    before = main.ledger.data()["count"]
    clock.now += 10

    def troubled(market, now=None):
        if fault == "missing":
            return unavailable(market["ticker"], "No bids")
        if fault == "wrong_ticker":
            return depth_for({**market, "ticker": "KXBTC15M-OTHER-MARKET"}, clock.now)
        if fault == "stale":
            return depth_for(market, clock.now - 100)
        if fault == "invalid":
            return normalize_orderbook(
                {"orderbook_fp": {"yes_dollars": [["0.62", "5"]],
                                  "no_dollars": [["0.45", "10"]]}},
                market["ticker"], clock.now
            )
        raise TimeoutError("injected orderbook timeout")
    provider.orderbook = troubled
    degraded_depth = main.update_once()
    assert degraded_depth["model"]["available"]
    assert degraded_depth["model"]["prob_above"] == pytest.approx(p)
    assert degraded_depth["model"]["side"] == initial_scores["side"]
    assert degraded_depth["depth_opportunity"]["status"] == "WAIT"
    assert degraded_depth["execution_intelligence"]["action"] == "WAIT"
    assert degraded_depth["execution_intelligence"]["order_placed"] is False
    # Optional book outage must not take down the independent forecast/ledger.
    assert degraded_depth["ok"] is True
    assert main.ledger.data()["count"] == before
    assert client.get("/health").status_code == 200

    provider.orderbook = lambda market, now=None: depth_for(market, clock.now)
    clock.now += 10
    recovered = main.update_once()
    assert recovered["orderbook"]["available"]
    assert recovered["model"]["prob_above"] == pytest.approx(p)
    assert recovered["execution_intelligence"]["action"] in ("ENTER", "WAIT")


def test_contract_rollover_cannot_reuse_old_depth_and_official_grade_persists(env):
    main, clock, provider, client, tmp = env
    first_ticker = provider.ticker
    clock.now = provider.close - 600
    provider.orderbook = lambda market, now=None: depth_for(market, clock.now)
    first = main.update_once()
    assert first["model"]["available"] and first["orderbook"]["ticker"] == first_ticker

    auth = {"Authorization": "Bearer synthetic-local-testing-token"}
    assert client.post("/api/paper", json={"side": "NO"}, headers=auth).status_code == 200
    clock.now = provider.close + 10
    provider.result = "no"
    main.grade_once()
    assert client.get("/api/state").json()["stats"]["settled_paper_trades"] == 1

    provider.ticker = "KXBTC15M-E2E-SYNTH-ROLLOVER"
    provider.close += 900
    clock.now = provider.close - 840
    provider.orderbook = lambda market, now=None: depth_for(
        {**market, "ticker": first_ticker}, clock.now
    )
    new = main.update_once()
    assert new["market"]["ticker"] == provider.ticker
    assert new["orderbook"]["ticker"] == first_ticker
    assert new["depth_opportunity"]["status"] == "WAIT"
    assert new["execution_intelligence"]["action"] == "WAIT"
    assert new["model"]["available"]
    assert client.get("/api/state").json()["stats"]["settled_paper_trades"] == 1

    provider.orderbook = lambda market, now=None: depth_for(market, clock.now)
    clock.now += 10
    good = main.update_once()
    assert good["orderbook"]["ticker"] == provider.ticker
    assert good["orderbook"]["available"]
    assert good["depth_opportunity"]["uses_orderbook_quotes_as_forecast"] is False
    assert client.get("/health").status_code == 200


def test_market_feed_failure_suppresses_all_entry_lanes_and_recovers(env):
    main, clock, provider, client, _ = env
    clock.now = provider.close - 600
    provider.orderbook = lambda market, now=None: depth_for(market, clock.now)
    ok = main.update_once()
    assert ok["ok"]
    provider.fail_price = True
    clock.now += 10
    failed = main.update_once()
    assert not failed["ok"] and failed["status"] == "DEGRADED"
    assert failed["opportunity"]["side"] == "WAIT"
    assert failed["depth_opportunity"]["status"] == "WAIT"
    assert failed["execution_intelligence"]["action"] == "WAIT"
    state = client.get("/api/state").json()
    assert state["manual_paper_available"] is False
    assert client.get("/health").status_code == 503
    auth = {"Authorization": "Bearer synthetic-local-testing-token"}
    assert client.post("/api/paper", json={"side": "YES"}, headers=auth).status_code == 409
    provider.fail_price = False
    clock.now += 10
    recovered = main.update_once()
    assert recovered["ok"]
    assert recovered["orderbook"]["available"]
    assert client.get("/health").status_code == 200
    assert client.get("/api/state").json()["manual_paper_available"] is True
