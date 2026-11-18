"""Read-only authoritative BRTI settlement publication/backfill monitor.

Rechecks multiple settled BTC15M contracts instead of treating one older
matching contract as proof the newer delayed contracts are complete.

All index data is signed-GET only and processed in memory. Artifacts contain
only sanitized status, per-contract second coverage and rounded differences.
No fills, trading accounts, credential output or order endpoints.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
import time
import requests

from app.settlement_reference import reconcile_contract
from research import verify_official_brti_live as src

DEFAULT_LIMIT = 12
MAX_LOOKBACK_SECONDS = 8 * 3600


def _utc_sec(ts):
    if not isinstance(ts, str):
        raise ValueError("Missing UTC contract time")
    parsed=datetime.fromisoformat(ts.replace("Z","+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Missing contract UTC offset")
    return parsed.timestamp()


def inspect(session, key_id, private_key, *, now=None, limit=DEFAULT_LIMIT):
    """Return honest complete/pending/conflict statuses for a bounded cohort."""
    now=time.time() if now is None else float(now)
    if not key_id or not private_key:
        return {"status":"NOT_VERIFIED", "verified":0,
                "reason":"Read-only CF Benchmarks API entitlement unavailable",
                "all_checked_contracts_verified":False, "records":[]}
    if not 1 <= limit <= 50:
        raise ValueError("Invalid bounded history inspection limit")
    summary={"kind":"BRTI_PUBLICATION_BACKFILL","status":"NOT_VERIFIED",
             "research_only":True, "no_account_api":True,"orders_placed":False,
             "official_ref":"CF_BENCHMARKS_BRTI","checked":0,"verified":0,
             "publication_pending":0,"detail_pending":0,
             "conflicts":0,"source_errors":0, "records":[],
             "all_checked_contracts_verified":False,
             "historical_event_time_not_live_delivery_proof":True,
             "authenticated_fills_verified":False}
    listing=src._get(session,src.API+"/markets",
                     {"series_ticker":"KXBTC15M","status":"settled","limit":50})
    rows=listing.get("markets",[])
    if not isinstance(rows,list):
        return {**summary,"status":"SOURCE_ERROR","source_errors":1,
                "reason":"Settled-market source payload is not a market list"}
    candidates=[]
    seen=set()
    for row in sorted((x for x in rows if isinstance(x,dict)),
                      key=lambda m:str(m.get("close_time") or ""),reverse=True):
        ticker=row.get("ticker")
        if not isinstance(ticker,str) or not ticker.startswith("KXBTC15M-") or ticker in seen:
            continue
        seen.add(ticker)
        if str(row.get("result") or "").lower() not in ("yes","no"):
            continue
        try:
            age=now-_utc_sec(row.get("close_time"))
        except (ValueError, TypeError, OverflowError):
            continue
        if 120 <= age <= MAX_LOOKBACK_SECONDS:
            candidates.append(row)
        if len(candidates)>=limit:
            break
    for market in candidates:
        ticker=market["ticker"]
        record={"ticker":ticker,"status":"NOT_VERIFIED",
                "opening_seconds":None,"closing_seconds":None}
        summary["checked"]+=1
        try:
            detail=src._public_market(session,ticker)
            if not isinstance(detail,dict):
                record["status"]="PENDING_DETAIL"
                summary["detail_pending"]+=1
                summary["records"].append(record)
                continue
            if (str(detail.get("status") or "").lower() not in ("settled","finalized")
                    or str(detail.get("result") or "").lower() not in ("yes","no")):
                record["status"]="PENDING_OFFICIAL_FINALITY"
                summary["detail_pending"]+=1
                summary["records"].append(record)
                continue
            if str(detail["result"]).lower()!=str(market["result"]).lower():
                record["status"]="CONFLICT"
                summary["conflicts"]+=1
                summary["records"].append(record)
                summary["status"]="CONFLICT"
                summary["reason"]="Official listing and finalized detail disagree"
                return summary
            if (not detail.get("open_time") or not detail.get("close_time")
                    or detail.get("floor_strike") is None
                    or detail.get("expiration_value") is None):
                record["status"]="PENDING_OFFICIAL_TERMS"
                summary["detail_pending"]+=1
                summary["records"].append(record)
                continue
            ticks,hours=src._load_hours(session,key_id,private_key,detail)
            reconciled=reconcile_contract(detail,ticks)
            record.update(status=reconciled["status"],
                opening_seconds=reconciled["windows"].get("opening",{}).get("sampled_seconds"),
                closing_seconds=reconciled["windows"].get("closing",{}).get("sampled_seconds"),
                reconstructed_winner_matches=bool(reconciled["winner_verified"]),
                signed_historical_hour_count=len(hours))
            if reconciled["status"]=="RECONCILED":
                summary["verified"]+=1
            elif (reconciled["status"]=="INCOMPLETE" and
                  reconciled["reason"]=="Missing true BRTI seconds in a reference window"):
                record["status"]="PENDING_INDEX_PUBLICATION"
                summary["publication_pending"]+=1
            else:
                summary["conflicts"]+=1
                summary["status"]="CONFLICT"
                summary["reason"]="Official index reconstruction is inconsistent or invalid"
                summary["records"].append(record)
                return summary
            summary["records"].append(record)
        except (requests.RequestException,ValueError,TypeError,KeyError,OverflowError) as exc:
            record["status"]="SOURCE_ERROR"
            record["reason"]=type(exc).__name__
            summary["source_errors"]+=1
            summary["status"]="SOURCE_ERROR"
            summary["records"].append(record)
            summary["reason"]="Cannot verify a cohort due to bounded source error"
            return summary
    if not summary["checked"]:
        summary["status"]="NOT_VERIFIED"
        summary["reason"]="No recent eligible, officially reported contract"
    elif summary["publication_pending"] or summary["detail_pending"]:
        summary["status"]="RECONCILED_WITH_PENDING" if summary["verified"] else "PENDING"
        summary["reason"]="Outstanding official publication/settlement evidence explicitly retained"
    else:
        summary["status"]="RECONCILED_ALL"
        summary["reason"]="Every inspected contract reconciled against genuine index"
        summary["all_checked_contracts_verified"]=True
    return summary


def main():
    key_id=os.environ.get("KALSHI_API_KEY_ID","").strip()
    secret=os.environ.get("KALSHI_PRIVATE_KEY_PEM","").strip()
    try:
        with requests.Session() as session:
            session.headers.update({"User-Agent":"AXIOM-BRTI-backfill-readonly/1.0",
                                    "Accept":"application/json"})
            result=inspect(session,key_id,secret)
    except Exception as exc:
        result={"kind":"BRTI_PUBLICATION_BACKFILL","status":"SOURCE_ERROR",
                "reason":type(exc).__name__,"all_checked_contracts_verified":False,
                "orders_placed":False,"records":[]}
    print("BRTI_BACKFILL "+json.dumps(result,sort_keys=True),flush=True)
    output=os.environ.get("AXIOM_BRTI_BACKFILL_EVIDENCE_PATH")
    if output:
        with open(output,"w",encoding="utf-8") as handle:
            json.dump(result,handle,indent=2,sort_keys=True)
    # Partial release data must remain explicitly unverified, even when some
    # older contracts reconcile. No fail-open "100% BRTI checked" claim.
    return 1 if result["status"] in ("CONFLICT","SOURCE_ERROR","NOT_VERIFIED") else 0


if __name__=="__main__":
    raise SystemExit(main())
