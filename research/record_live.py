"""One-shot read-only BTC15m challenger observation/official-result collector.

Not imported by app.main. Does not issue orders, alter AXIOM's SQLite
ledger, deploy any service or run a scheduled task. Local output under data/
is git-ignored. Re-run as explicitly desired at contract checkpoints.
"""
from __future__ import annotations
import argparse
import json
import math
import time
from pathlib import Path

from app.feeds import LiveProvider
from .challenger_lab import normalize_observation, normalize_settlement, ReplayError

DEFAULT_ROOT = Path("data/challenger_lab")


def _rows(path):
    if not path.exists():
        return []
    items=[]
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                items.append(json.loads(line))
    return items


def _append_new(path, document):
    """Append only, flush and sync to preserve explicit audit records."""
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8") as fh:
        fh.write(json.dumps(document,separators=(",",":"),sort_keys=True)+"\n")
        fh.flush()
        import os
        os.fsync(fh.fileno())


def observe(provider, root=DEFAULT_ROOT, clock=time.time):
    """Capture a genuine provider observation or fail closed; never guess strike."""
    root=Path(root)
    market=provider.market()
    market_time=clock()  # when response became observable; not an exchange quote timestamp
    if not market or not market.get("target") or not market.get("close_ts"):
        return {"status":"NO_KNOWN_TARGET"}
    spot=provider.price()
    spot_time=clock()
    candles=provider.candles()
    now=clock()
    if not isinstance(candles,list):
        return {"status":"INVALID_CANDLES"}
    complete=[c for c in candles if c.get("t",float("inf"))+60 <= now]
    doc={"ticker":market["ticker"],"ts":now,"spot_ts":spot_time,
         "target_ts":market_time,"open_ts":market["close_ts"]-900,
         "expires_ts":market["close_ts"],"spot":spot,"target":market["target"],
         "market_mid":market.get("market_mid"),"candles":complete,
         "observation_source":"read_only_kalshi_coinbase_public_rest",
         "source_quality":getattr(provider,"candle_quality",None)}
    if doc["market_mid"] is not None:
        doc["market_mid_ts"]=market_time
    try:
        validated=normalize_observation(doc)
    except ReplayError as exc:
        return {"status":"INPUT_WITHHELD","reason":str(exc)}
    if validated["checkpoint"] is None:
        return {"status":"NOT_CHECKPOINT","seconds_left":validated["seconds_left"]}
    path=root/"observations.jsonl"
    key=(doc["ticker"],validated["checkpoint"])
    for existing in _rows(path):
        if existing["ticker"]==key[0]:
            earlier=normalize_observation(existing)
            if earlier["checkpoint"]==key[1]:
                return {"status":"ALREADY_RECORDED","ticker":doc["ticker"],
                        "checkpoint":key[1]}
    # No source may contain the outcome. This record is immutable after append.
    _append_new(path,doc)
    return {"status":"RECORDED","ticker":doc["ticker"],"checkpoint":key[1],
            "market_mid_is_benchmark_only":True}


def grade(provider, root=DEFAULT_ROOT, clock=time.time):
    """Read official Kalshi yes/no results into a SEPARATE append-only file."""
    root=Path(root)
    observations=_rows(root/"observations.jsonl")
    done={r["ticker"]:r for r in _rows(root/"settlements.jsonl")}
    contracts={}
    for raw in observations:
        if raw["ticker"] in contracts and raw["expires_ts"]!=contracts[raw["ticker"]]:
            raise ReplayError("Conflicting expiration for a contract; refuse grading")
        contracts[raw["ticker"]]=raw["expires_ts"]
    graded=0; pending=0
    for ticker,expires in sorted(contracts.items()):
        if ticker in done:
            continue
        if clock() < expires + 5:
            pending+=1
            continue
        result=provider.settlement(ticker)
        if result is None:
            pending+=1
            continue
        doc={"ticker":ticker,"expires_ts":expires,"result":result,
             "settled_at":clock(),"source":"kalshi_official"}
        normalize_settlement(doc)
        _append_new(root/"settlements.jsonl",doc)
        graded+=1
    return {"status":"CHECKED","new_official_results":graded,
            "pending_or_unavailable":pending, "contracts_seen":len(contracts)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode",required=True,choices=("observe","grade"))
    parser.add_argument("--data-root",type=Path,default=DEFAULT_ROOT)
    args=parser.parse_args()
    if not str(args.data_root).startswith("data/"):
        parser.error("For this isolated collector keep files under git-ignored data/")
    provider=LiveProvider()
    try:
        result=observe(provider,args.data_root) if args.mode=="observe" else grade(provider,args.data_root)
        print(json.dumps(result,sort_keys=True))
    finally:
        provider.session.close()


if __name__=="__main__":
    main()
