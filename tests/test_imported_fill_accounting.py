"""Prove imported fill math without pretending unauthenticated imports are real profit."""
from decimal import Decimal
from datetime import datetime,timezone
import random
from research.reconcile_imported_fills import reconcile_imported_records as audit


def row(ident,*,ticker="KXBTC15M-TEST-A",side="yes",action="buy",
        count="10",price="0.30",fee="0.10",when=100):
    data={"fill_id":ident,"ticker":ticker,"side":side,"action":action,
          "count_fp":count,"fee_cost":fee,
          "created_time":datetime.fromtimestamp(1794957700+when,timezone.utc).isoformat()}
    data[side+"_price_dollars"]=price
    return data


def test_empty_or_missing_auth_evidence_never_claims_zero_net_or_real_trades():
    for fills in ([],None):
        r=audit(fills,{})
        assert r["status"]=="NO_EVIDENCE"
        assert r["realized_net_profit_usd"] is None
        assert r["computed_record_net_usd"] is None
        assert not r["source_authenticated"]


def test_both_sides_actual_price_fields_and_supplied_fees_are_used_not_estimated():
    fills=[row("buy"),row("sell",action="sell",price="0.50",fee="0.05",when=110)]
    r=audit(fills,{})
    assert r["status"]=="RECORD_ARITHMETIC_COMPLETE"
    assert Decimal(r["computed_record_net_usd"])==Decimal("1.85")
    assert Decimal(r["fees_from_supplied_rows_usd"])==Decimal(".15")
    assert r["realized_net_profit_usd"] is None
    assert not r["actual_trading_profit_verified"]
    no=[row("nob",side="no",count="4",price="0.60",fee="0.03"),
        row("nos",side="no",action="sell",count="4",price="0.70",fee="0.02",when=111)]
    r=audit(no,{})
    assert Decimal(r["computed_record_net_usd"])==Decimal("0.35")


def test_finalized_official_winner_turns_remaining_exposure_into_record_only_cash():
    filled=[row("entry")]
    r=audit(filled,{"KXBTC15M-TEST-A":{"status":"settled","result":"yes"}})
    assert r["status"]=="RECORD_ARITHMETIC_COMPLETE"
    assert Decimal(r["computed_record_net_usd"])==Decimal("6.90")
    assert r["settled_contracts"]==1
    lost=audit(filled,{"KXBTC15M-TEST-A":{"status":"settled","result":"no"}})
    assert Decimal(lost["computed_record_net_usd"])==Decimal("-3.10")
    assert lost["realized_net_profit_usd"] is None


def test_partial_open_or_pending_settlement_never_creates_fake_net_returns():
    fills=[row("open",count="5"),row("flat-b",ticker="KXBTC15M-TEST-B"),
           row("flat-s",ticker="KXBTC15M-TEST-B",action="sell",price=".7",fee=".05",when=120)]
    for results in ({}, {"KXBTC15M-TEST-A":{"status":"closed","result":"yes"}}):
        r=audit(fills,results)
        assert r["status"]=="PARTIAL_OPEN_POSITIONS"
        assert r["pending_contracts"]==["KXBTC15M-TEST-A"]
        assert r["computed_record_net_usd"] is None


def test_duplicate_partial_omitted_fee_or_invalid_source_fields_fail_closed():
    invalids=[
      "not-a-list", [{"fill_id":"empty"}], [row("same"),row("same",when=110)],
      [row("sell-first",action="sell")],
      [row("bad-count",count="-1")], [row("bad-count",count="NaN")],
      [row("bool-count",count=True)], [row("too-many",count="1000001")],
      [row("bad-price",price="1")], [row("bad-price",price="NaN")],
      [row("bad-fee",fee=None)], [row("bad-fee",fee="-1")],
      [row("wrong-ticker",ticker="KXETH15M-OTHER")],
      [row("bad-side",side="maybe")],
      [row("bad-action",action="remove")],
      [row("bad-time",when=5e20)],
      [row("bad-row")] + ["not-a-record"],
    ]
    for entries in invalids:
        try:
            r=audit(entries,{})
        except (OverflowError,ValueError):
            # Fault injection itself may be unable to construct an impossible
            # datetime (e.g. a Python year outside platform range).
            continue
        assert r["status"]=="INVALID_INPUT",entries
        assert r["realized_net_profit_usd"] is None
        assert r["computed_record_net_usd"] is None


def test_invalid_timestamp_missing_id_or_backdated_fills_never_certify_performance():
    m=row("x");m["created_time"]="2026-11-17T20:00:00"
    n=row("y");n["fill_id"]=""
    k=row("z");k["created_time"]="not-a-date"
    for f in (m,n,k,None):
        r=audit([f],{})
        assert r["status"]=="INVALID_INPUT"
    assert audit([row("x")],[])["status"]=="INVALID_INPUT"


def test_thousand_seeded_round_trips_prove_fee_exact_cashflow_and_no_false_verification():
    rng=random.Random(20261117)
    for i in range(1000):
        buy=Decimal(rng.randrange(10,80))/100
        sell=Decimal(rng.randrange(10,90))/100
        qty=Decimal(rng.randrange(1,50))
        fee1=Decimal(rng.randrange(0,60))/100
        fee2=Decimal(rng.randrange(0,60))/100
        first=row("buy",count=str(qty),price=str(buy),fee=str(fee1))
        second=row("sell",action="sell",count=str(qty),price=str(sell),
                   fee=str(fee2),when=110)
        r=audit([first,second],{})
        assert r["status"]=="RECORD_ARITHMETIC_COMPLETE"
        expected=qty*(sell-buy)-fee1-fee2
        assert Decimal(r["computed_record_net_usd"])==expected,(i,r)
        assert r["actual_trading_profit_verified"] is False


def test_nonempty_input_without_official_fee_does_not_estimate_from_public_quote():
    m=row("no-fee")
    m.pop("fee_cost")
    r=audit([m],{})
    assert r["status"]=="INVALID_INPUT"
    assert r["actual_trading_profit_verified"] is False
