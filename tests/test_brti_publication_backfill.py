"""Deterministic BRTI retrospective publication/backfill acceptance; no network."""
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import pytest
import requests

from research import verify_brti_backlog as backfill


CLOCK=1794957700


def iso(t):
    return datetime.fromtimestamp(t,timezone.utc).isoformat()


def official(ticker,age):
    end=CLOCK-age
    return {"ticker":ticker,"status":"settled","result":"yes","open_time":iso(end-900),
            "close_time":iso(end),"floor_strike":"90000","expiration_value":"90100"}


def official_ticks(m,drop_closing=False):
    start=int(datetime.fromisoformat(m["open_time"]).timestamp())
    end=int(datetime.fromisoformat(m["close_time"]).timestamp())
    rows=[]
    for boundary,price in ((start,"90000"),(end,"90100")):
        for s in range(boundary-60,boundary):
            if drop_closing and boundary==end and s>=end-59:
                continue
            rows.append({"time":s*1000,"value":price})
    return rows


def source(records,terms=None,drop=None,fail=None):
    def listing(*args,**kwargs):
        return {"markets":records}
    def detail(session,ticker):
        if fail=="detail":
            raise requests.Timeout("synthetic source timeout")
        return (terms or {m["ticker"]:m for m in records}).get(ticker)
    def history(session,kid,key,contract):
        if fail=="history":
            raise requests.Timeout("synthetic index timeout")
        return official_ticks(contract,drop_closing=contract["ticker"]==drop),[
            "2026-11-17T16:00:00Z","2026-11-17T17:00:00Z"]
    return listing,detail,history


def check(monkeypatch,records,terms=None,drop=None,fail=None):
    listing,detail,history=source(records,terms,drop,fail)
    monkeypatch.setattr(backfill.src,"_get",listing)
    monkeypatch.setattr(backfill.src,"_public_market",detail)
    monkeypatch.setattr(backfill.src,"_load_hours",history)
    return backfill.inspect(object(),"synthetic-key-id","synthetic-key",now=CLOCK)


def test_missing_auth_and_invalid_bounds_do_not_suggest_verified():
    assert backfill.inspect(object(),"","secret")["status"]=="NOT_VERIFIED"
    assert backfill.inspect(object(),"id","")["all_checked_contracts_verified"] is False
    for limit in (0,-1,51):
        with pytest.raises(ValueError):
            backfill.inspect(object(),"id","secret",now=CLOCK,limit=limit)


def test_no_eligible_markets_and_invalid_public_listing_fail_closed(monkeypatch):
    m=official("KXBTC15M-OLD",9*3600)
    assert check(monkeypatch,[m])["status"]=="NOT_VERIFIED"
    newer=official("KXBTC15M-TOO_NEW",30)
    assert check(monkeypatch,[newer])["status"]=="NOT_VERIFIED"
    monkeypatch.setattr(backfill.src,"_get",lambda *a,**kw:{"markets":"not-an-array"})
    r=backfill.inspect(object(),"id","secret",now=CLOCK)
    assert r["status"]=="SOURCE_ERROR" and r["source_errors"]==1


def test_all_eligible_authentic_60_second_cohorts_reconcile(monkeypatch):
    records=[official(f"KXBTC15M-COHORT-{i}",300+900*i) for i in range(8)]
    r=check(monkeypatch,records)
    assert r["status"]=="RECONCILED_ALL"
    assert r["checked"]==r["verified"]==8
    assert r["all_checked_contracts_verified"] is True
    assert all(x["opening_seconds"]==60 and x["closing_seconds"]==60 for x in r["records"])
    assert all(x["reconstructed_winner_matches"] for x in r["records"])


def test_missing_latest_historical_hour_is_retained_until_backfilled(monkeypatch):
    a=official("KXBTC15M-NEW",300)
    b=official("KXBTC15M-OLDER",1200)
    r=check(monkeypatch,[b,a],drop=a["ticker"])
    assert r["status"]=="RECONCILED_WITH_PENDING"
    assert r["all_checked_contracts_verified"] is False
    assert r["verified"]==1 and r["publication_pending"]==1
    missing=[x for x in r["records"] if x["status"]=="PENDING_INDEX_PUBLICATION"]
    assert len(missing)==1 and missing[0]["closing_seconds"]==1
    # Later the exact missing index seconds become available; the original
    # contract must transition to genuinely reconciled, not be substituted.
    r=check(monkeypatch,[b,a])
    assert r["status"]=="RECONCILED_ALL" and r["verified"]==2


def test_no_matching_index_data_never_launders_a_success(monkeypatch):
    m=official("KXBTC15M-NEW",300)
    r=check(monkeypatch,[m],drop=m["ticker"])
    assert r["status"]=="PENDING" and r["verified"]==0
    assert r["publication_pending"]==1


def test_mismatched_reported_winner_blocks_not_cherry_picks_older(monkeypatch):
    newer=official("KXBTC15M-NEW",300)
    older=official("KXBTC15M-OLD",1200)
    bad={**newer,"result":"no"}
    r=check(monkeypatch,[newer,older],terms={newer["ticker"]:bad,older["ticker"]:older})
    assert r["status"]=="CONFLICT"
    assert r["verified"]==0 and r["conflicts"]==1
    assert r["checked"]==1
    assert r["records"][0]["ticker"]==newer["ticker"]


def test_incomplete_official_details_are_distinct_from_missing_index(monkeypatch):
    a=official("KXBTC15M-A",300)
    b=official("KXBTC15M-B",1200)
    for term in (None,{**a,"status":"closed","result":"yes"},
                 {**a,"floor_strike":None}):
        r=check(monkeypatch,[a,b],terms={a["ticker"]:term,b["ticker"]:b})
        assert r["status"]=="RECONCILED_WITH_PENDING"
        assert r["detail_pending"]==1
        assert r["verified"]==1
        assert r["publication_pending"]==0


def test_source_exceptions_are_visible_without_fabricated_reconciliation(monkeypatch):
    a=official("KXBTC15M-A",300)
    for fault in ("detail","history"):
        r=check(monkeypatch,[a],fail=fault)
        assert r["status"]=="SOURCE_ERROR"
        assert r["source_errors"]==1
        assert r["all_checked_contracts_verified"] is False
        assert r["records"][0]["status"]=="SOURCE_ERROR"


def test_invalid_index_rows_are_conflict_not_ignored(monkeypatch):
    a=official("KXBTC15M-A",300)
    listing,detail,history=source([a])
    monkeypatch.setattr(backfill.src,"_get",listing)
    monkeypatch.setattr(backfill.src,"_public_market",detail)
    monkeypatch.setattr(backfill.src,"_load_hours",lambda *args: ([None],["2026-11-17T17:00:00Z"]))
    r=backfill.inspect(object(),"id","key",now=CLOCK)
    assert r["status"]=="CONFLICT" and r["conflicts"]==1


def test_backlog_output_hides_auth_and_does_not_claim_trade_profits(monkeypatch):
    records=[official("KXBTC15M-A",300)]
    listing,detail,history=source(records)
    monkeypatch.setattr(backfill.src,"_get",listing)
    monkeypatch.setattr(backfill.src,"_public_market",detail)
    monkeypatch.setattr(backfill.src,"_load_hours",history)
    class Session:
        def __init__(self):self.headers={}
        def __enter__(self):return self
        def __exit__(self,*args):return False
    monkeypatch.setattr(backfill.requests,"Session",Session)
    with tempfile.TemporaryDirectory() as tmp:
        path=str(Path(tmp)/"backfill-status.json")
        monkeypatch.setenv("KALSHI_API_KEY_ID","synthetic-id-not-a-secret")
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM","synthetic-PEM-not-a-secret")
        monkeypatch.setenv("AXIOM_BRTI_BACKFILL_EVIDENCE_PATH",path)
        with patch("time.time",return_value=CLOCK),patch("sys.stdout",new=io.StringIO()):
            assert backfill.main()==0
        data=Path(path).read_text()
        assert "synthetic-PEM-not-a-secret" not in data
        assert '"status": "RECONCILED_ALL"' in data
        assert json.loads(data)["orders_placed"] is False
        with patch.object(backfill,"inspect",side_effect=RuntimeError("synthetic exception")):
            with patch("sys.stdout",new=io.StringIO()):
                assert backfill.main()==1
        assert json.loads(Path(path).read_text())["status"]=="SOURCE_ERROR"


def test_invalid_or_naive_clock_and_malformed_listing_records_cannot_qualify(monkeypatch):
    for raw in (None,3,"invalid","2026-11-17T18:00:00"):
        with pytest.raises((ValueError,TypeError)):
            backfill._utc_sec(raw)
    recent=official("KXBTC15M-OK",300)
    malformed=[None,{},{"ticker":"OTHER","result":"yes","close_time":iso(CLOCK-900)},
               {"ticker":None,"result":"yes","close_time":iso(CLOCK-900)},
               {"ticker":"KXBTC15M-WRONGRESULT","result":"void","close_time":iso(CLOCK-900)},
               {"ticker":"KXBTC15M-BADTIME","result":"yes","close_time":"bad"},
               recent,recent]
    result=check(monkeypatch,malformed,terms={recent["ticker"]:recent})
    assert result["status"]=="RECONCILED_ALL"
    assert result["checked"]==result["verified"]==1


def test_verifier_incomplete_official_outcome_never_certifies_correctness(monkeypatch):
    m=official("KXBTC15M-INVALID",300)
    listing,detail,_=source([m])
    monkeypatch.setattr(backfill.src,"_get",listing)
    monkeypatch.setattr(backfill.src,"_public_market",detail)
    monkeypatch.setattr(backfill.src,"_load_hours",lambda *_: ([None],[]))
    report=backfill.inspect(object(),"id","key",now=CLOCK)
    assert report["status"]=="CONFLICT"
    assert not report["all_checked_contracts_verified"]


def test_manual_backfill_cli_without_entitlement_reports_not_verified(monkeypatch):
    import runpy, contextlib, sys
    monkeypatch.delenv("KALSHI_API_KEY_ID",raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM",raising=False)
    monkeypatch.delenv("AXIOM_BRTI_BACKFILL_EVIDENCE_PATH",raising=False)
    with patch.object(sys,"argv",["verify_brti_backlog.py"]):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with pytest.raises(SystemExit) as ex:
                runpy.run_path(str(Path(backfill.__file__)),run_name="__main__")
    assert ex.value.code==1
    assert "NOT_VERIFIED" in out.getvalue()
