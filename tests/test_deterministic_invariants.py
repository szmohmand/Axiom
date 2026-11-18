"""Deterministic high-volume invariant checks and operational integrity contracts.

A green test here does not imply mathematically proven future correctness.
"""
import json
import random
from pathlib import Path
from app.orderbook import normalize_orderbook,sweep
from app.execution_evidence import examine_liquidity

ROOT=Path(__file__).resolve().parents[1]
TICK="KXBTC15M-INVARIANT-TEST"


def test_thousands_of_randomized_books_obey_conservation_and_no_false_fills():
    rng=random.Random(20261117)
    for case in range(2500):
        yprices=sorted(rng.sample(range(2,47),rng.randint(1,12)),reverse=True)
        nprices=sorted(rng.sample(range(2,47),rng.randint(1,12)),reverse=True)
        yes=[[str(p/100),str(rng.randint(1,150))] for p in yprices]
        no=[[str(p/100),str(rng.randint(1,150))] for p in nprices]
        book=normalize_orderbook({"orderbook_fp":{"yes_dollars":yes,"no_dollars":no}},TICK,1000)
        assert book["available"] and not book["individual_orders_visible"]
        assert book["is_full_aggregated_depth"]
        assert book["levels"]["YES"]==len(yes) and book["levels"]["NO"]==len(no)
        for side in ("YES","NO"):
            for action in ("BUY","SELL"):
                quantity=rng.randint(1,400)
                walk=sweep(book,side,action,quantity)
                assert walk["simulated"] is True
                assert 0<=walk["available_contracts"]<=quantity
                assert walk["complete"]==(walk["available_contracts"]==quantity)
                if walk["available_contracts"]>0:
                    assert walk["best_price"] is not None
                    assert walk["worst_price"] is not None
                    assert 0<walk["average_price"]<1
                    assert abs(walk["total_notional"]-walk["average_price"]*walk["available_contracts"])<1e-6
                    assert walk["slippage_from_best"]>=-1e-10
                else:
                    assert walk["average_price"] is None
        report=examine_liquidity(book,{"ticker":TICK},1001,size_contracts=20)
        assert report["realized_net_profit_usd"] is None
        assert report["authenticated_fill_records"]==0
        assert not report["actual_entry_and_exit_fills_verified"]


def test_brtI_recheck_is_bounded_readonly_and_no_auto_orders():
    source=(ROOT/".github/workflows/axiom-official-brti-settlement-readonly.yml").read_text()
    assert "cron: '17 */2 * * *'" in source
    assert "python -m research.verify_official_brti_live" in source
    assert "AUTO_PAPER: '0'" in source
    assert "workflow_dispatch:" in source
    assert "actions/upload-artifact@v6" in source
    assert "secrets.KALSHI_PRIVATE_KEY_PEM" in source
    assert "portfolio/orders" not in source
    assert "POST " not in source


def test_historical_transfer_source_identity_not_falsified_by_signoff_notes():
    m=json.loads((ROOT/"phase0/transfer_manifest.json").read_text())
    assert m["legacy_zip_commit_sha"] is None
    assert len([x for x in m["source_artifacts"] if x["type"]=="legacy_zip"])==2
    assert all(len(x["sha256"])==64 for x in m["source_artifacts"])
    acceptance=(ROOT/"phase0/ACCEPTANCE.md").read_text()
    assert "PENDING HISTORICAL DISPOSITION + OWNER SIGN-OFF" in acceptance
    assert "UNRESOLVED" in acceptance
    assert "PENDING" in (ROOT/"phase0/SIGNOFF_TEMPLATE.md").read_text()


def test_unverified_economics_never_promoted_to_authentic_fills():
    from app.execution_evidence import examine_liquidity
    report=examine_liquidity(None,None,1000)
    assert report["real_orders_sent"] is False
    assert report["actual_entry_and_exit_fills_verified"] is False
    assert report["official_applied_trade_fees_verified"] is False
    assert report["realized_net_profit_usd"] is None
    assert report["verified_win_rate"] is None
