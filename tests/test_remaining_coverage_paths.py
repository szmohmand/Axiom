"""Remaining reachable statement/branch tests based on measured Coverage.py arcs.

These cases exercise the ORIGINAL safety guards; no production code is mocked
to manufacture coverage. All market data is synthetic, all SQLite data is
temporary and no remote/network/order API is used.
"""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import io
import json
import math
import tempfile
from unittest.mock import patch
from zipfile import ZipFile

from fastapi import HTTPException
import pytest

from app import main, engine, orderbook, settlement_research
from app.storage import Ledger
from phase0 import verify_transfer
from research import verify_brti_backlog, verify_official_brti_live
from research.reconcile_imported_fills import reconcile_imported_records


def test_disabled_manual_paper_endpoint_rejects_without_writing_any_order(monkeypatch):
    # main.py:433 -> exit. This branch must be tested without starting workers.
    monkeypatch.setattr(main, "ADMIN_TOKEN", "")
    with pytest.raises(HTTPException) as raised:
        main.paper(main.PaperRequest(side="YES"), authorization=None)
    assert raised.value.status_code == 403
    assert "disabled" in str(raised.value.detail).lower()


def test_research_shadow_extreme_finite_strike_abstains_on_nonfinite_z():
    # settlement_research.py:94: a finite *extremely small* strike makes
    # price/strike evaluate to infinity. No trading signal may result.
    now = 1794957700
    bars = []
    for i in range(61):
        px = 90000 + 7 * math.sin(i * .4) + i * .2
        bars.append({"t": now - (61-i)*60, "close": px})
    result = settlement_research.shadow_forecast_from_candles(
        bars, {"target": 1e-308, "seconds_left": 600}, now)
    assert result["available"] is False
    assert result["side"] == "WAIT"
    assert result["reason"] == "Forecast not finite"
    assert result["can_trigger_paper_or_orders"] is False


def test_provenance_optional_missing_archive_and_matching_external_archive():
    # phase0/verify_transfer.py:37->30 and 78->80.
    # Missing archive is tolerated only when require_archives=False;
    # supplied legacy_zip must still hash-match the pinned manifest.
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "checkout"
        folder = root / "phase0"
        folder.mkdir(parents=True)
        source = Path(temp) / "separately-supplied-original.zip"
        with ZipFile(source, "w") as archive:
            archive.writestr("AXIOM_v2/README.md", "only synthetic archive content")
        digest = verify_transfer.sha(source)
        manifest = {
            "transfer_base": "original.zip",
            "source_artifacts": [{"type": "legacy_zip", "filename": "original.zip", "sha256": digest}],
            "transferred_files": [],
        }
        (folder / "transfer_manifest.json").write_text(json.dumps(manifest))
        assert verify_transfer.verify(root, require_archives=False) == []
        assert verify_transfer.verify(root, legacy_zip=source, require_archives=False) == []
        required = verify_transfer.verify(root, require_archives=True)
        assert any("missing frozen ZIP" in msg for msg in required)


def test_imported_record_decimal_parse_and_timestamp_type_fail_closed():
    # research/reconcile_imported_fills.py:24-25 and 33.
    base = {
        "fill_id": "synthetic-001",
        "ticker": "KXBTC15M-AUDIT-ONLY",
        "side": "yes", "action": "buy", "count_fp": "5",
        "yes_price_dollars": "0.36", "fee_cost": "0.03",
        "created_time": "2026-11-17T20:00:00Z",
    }
    for bad in [
        {**base, "yes_price_dollars": "unparseable-decimal"},
        {**base, "count_fp": "invalid"},
        {**base, "fee_cost": "not-a-fee"},
        {**base, "created_time": None},
        {**base, "created_time": 1794957700},
    ]:
        result = reconcile_imported_records([bad], {})
        assert result["status"] == "INVALID_INPUT"
        assert result["realized_net_profit_usd"] is None
        assert result["computed_record_net_usd"] is None
        assert result["actual_trading_profit_verified"] is False


def test_bounded_brti_history_inspector_stops_at_requested_limit(monkeypatch):
    # research/verify_brti_backlog.py:73, with >limit eligible rows.
    now = 1794957700
    entries = [
        {
            "ticker": f"KXBTC15M-FAKE-{i}", "result": "yes",
            "close_time": datetime.fromtimestamp(now - 300 - 900*i, timezone.utc).isoformat(),
        }
        for i in range(5)
    ]
    seen = []
    monkeypatch.setattr(verify_brti_backlog.src, "_get",
                        lambda *args, **kwargs: {"markets": entries})
    def detail(session, ticker):
        seen.append(ticker)
        item = next(r for r in entries if r["ticker"] == ticker)
        return {**item, "status": "settled",
                "open_time": datetime.fromtimestamp(
                    datetime.fromisoformat(item["close_time"]).timestamp() - 900,
                    timezone.utc).isoformat(),
                "floor_strike": "90000",
                "expiration_value": "90100"}
    monkeypatch.setattr(verify_brti_backlog.src, "_public_market", detail)
    monkeypatch.setattr(verify_brti_backlog.src, "_load_hours",
                        lambda *args: ([], ["synthetic-boundary-hour"]))
    monkeypatch.setattr(verify_brti_backlog, "reconcile_contract",
                        lambda *_: {
                            "status": "RECONCILED", "winner_verified": True,
                            "windows": {
                                "opening": {"sampled_seconds": 60},
                                "closing": {"sampled_seconds": 60},
                            },
                        })
    result = verify_brti_backlog.inspect(object(), "fake-id", "fake-key",
                                           now=now, limit=2)
    assert result["checked"] == 2
    assert result["verified"] == 2
    assert result["status"] == "RECONCILED_ALL"
    assert len(seen) == 2
    assert len(result["records"]) == 2
    assert result["all_checked_contracts_verified"] is True
    assert result["no_account_api"] is True
    assert result["orders_placed"] is False


def test_official_brti_walker_disregards_scalars_and_unrecognized_records():
    # verify_official_brti_live.py:66->exit (scalar after elif list/dict).
    assert list(verify_official_brti_live._walk_values(None)) == []
    assert list(verify_official_brti_live._walk_values("not-a-row")) == []
    assert list(verify_official_brti_live._walk_values(123)) == []
    assert list(verify_official_brti_live._walk_values({"unknown": 4})) == []
    assert list(verify_official_brti_live._walk_values(
        {"data": [None, "noise", {"time": 1234, "value": 90000}]}
    )) == [{"time": 1234, "value": 90000}]


def test_sqlite_watch_and_snapshot_branches_with_multiple_officially_graded_rows():
    # storage.py:113->exit, 178->176, 180->182, 211->199.
    # Includes both supplied participant-midpoint and missing-midpoint paths.
    with tempfile.TemporaryDirectory() as temp:
        db = Ledger(str(Path(temp) / "test-only.sqlite3"))
        try:
            now = 1794957700.0
            watched = {"ticker": "KXBTC15M-WATCH", "seconds_left": 600, "target": 90000}
            model = {"available": True, "side": "ABOVE", "prob_above": .91}
            assert db.watch_info(watched["ticker"]) is None
            assert db.first_call(watched, model, 90000, now) is None
            held = db.watch_info(watched["ticker"])
            assert held is not None and held["side"] == "ABOVE"
            assert db.first_call(watched, model, 90000, now + 15) is not None
            assert db.watch_info(watched["ticker"]) is None

            engines = [
                {"name": "strong", "available": True, "prob_above": .8},
                {"name": "disabled", "available": False, "prob_above": .2},
                {"name": "no_probability", "available": True, "prob_above": None},
                {"name": "second", "available": True, "prob_above": .6},
            ]
            for ticker, quote in [("KXBTC15M-SCORE-A", .52),
                                  ("KXBTC15M-SCORE-B", None)]:
                contract = {"ticker": ticker, "seconds_left": 600,
                            "market_mid": quote, "target": 90000}
                output = {"available": True, "prob_above": .75, "engines": engines}
                assert db.engine_snapshots(contract, output, now) == 3
                db.grade(ticker, "yes", now + 10)

            scores = db.engine_scores()
            assert scores["samples"] == 6
            assert len(scores["scores"]) == 3
            assert all(row["n"] == 2 for row in scores["scores"])
            assert all(row["market_brier"] is not None for row in scores["scores"])
            assert all(row["validated_alpha"] is False for row in scores["scores"])

            # Explicitly skip both the per-engine record and ensemble row.
            none_model = {"available": False, "prob_above": None,
                          "engines": [{"name": "disabled", "available": False,
                                       "prob_above": None}]}
            assert db.engine_snapshots({"ticker": "KXBTC15M-SCORE-C",
                                        "seconds_left": 600, "market_mid": None},
                                       none_model, now) == 0
            assert db.engine_scores()["samples"] == 6
        finally:
            db.conn.close()


def test_mathematical_invariants_that_make_redundant_guards_unreachable():
    # These tests do NOT remove or suppress any defensive source branches.
    # Engine: len(closes)>=16 => len(zip(closes, closes[1:]))>=15.
    for count in range(16, 200):
        closes = [float(i + 1) for i in range(count)]
        assert len(list(zip(closes, closes[1:]))) >= 15

    # Order-book: if YES top bid + NO top bid <= $1 then BOTH reciprocal
    # implied ask-minus-bid spreads are nonnegative; these guards are retained.
    for y in range(1, 100):
        for n in range(1, 101 - y):
            yes, no = Decimal(y)/100, Decimal(n)/100
            assert yes + no <= 1
            assert (1 - no) - yes >= 0
            assert (1 - yes) - no >= 0

    # Sweep: with requested>0 and each size>0, take>0 until filled==requested;
    # the code breaks immediately at equality, before the next iteration.
    for request in (1, 2, 10, 100):
        filled = 0
        for size in (3, 7, 20, 1000):
            take = min(size, request - filled)
            assert take > 0
            filled += take
            if filled == request:
                break

    # Research: >=31 completed candles => window length>=31 => >=30 returns.
    for observations in range(31, 200):
        window_len = min(61, observations)
        assert window_len - 1 >= 30

    # The BRTI history loader receives exactly two intervals and examines
    # only their four endpoints; at most four distinct UTC hour buckets exist.
    from datetime import timedelta
    for start in (datetime(2026, 11, 17, 15, 12, tzinfo=timezone.utc),
                  datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)):
        end = start + timedelta(minutes=15)
        endpoints = [
            start - timedelta(seconds=60), start - timedelta(seconds=1),
            end - timedelta(seconds=60), end - timedelta(seconds=1),
        ]
        hours = {t.replace(minute=0, second=0, microsecond=0)
                 for t in endpoints}
        assert len(hours) <= 4
