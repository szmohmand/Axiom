"""Independent Nison whole-book shadow live study, separate from existing AXIOM.

No imports from app.main, no orders, no authenticated Kalshi calls, no edits
to main, and no changes to the *existing* simpler Nison study.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import time
from pathlib import Path

from app.nison_methodology import scan_nison, forecast_nison_independent
from research.candlestick_shadow_study import get_live, read_results, _market_data

DB="/var/lib/axiom-nison-full-study/study.sqlite3"
LEDGER="/var/lib/axiom/bot.sqlite3"
CHECKPOINTS={"14m":840,"10m":600,"5m":300,"1m":60}


def connect(path=DB):
    directory=Path(path).parent
    directory.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(path,timeout=10)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cohort(
            ticker TEXT PRIMARY KEY,first_seen REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS probes(
            ticker TEXT NOT NULL,checkpoint TEXT NOT NULL,
            ts REAL NOT NULL,seconds_left REAL NOT NULL,
            baseline_p REAL NOT NULL,independent_nison_p REAL,
            candle_direction TEXT,experiment_score REAL,
            pattern_names TEXT NOT NULL,
            nison_status TEXT NOT NULL,
            PRIMARY KEY(ticker,checkpoint));
    """)
    return conn


def observe(conn,state,now=None):
    clock=time.time() if now is None else now
    ticker,end,seconds,baseline,ts=_market_data(state,clock)
    with conn:
        warm=conn.execute("SELECT value FROM meta WHERE key='warmup_ticker'").fetchone()
        if not warm:
            conn.execute("INSERT INTO meta VALUES('warmup_ticker',?)",(ticker,))
            return {"status":"WARMUP","ticker":ticker}
        if ticker==warm["value"]:
            return {"status":"WARMUP","ticker":ticker}
        present=conn.execute("SELECT 1 FROM cohort WHERE ticker=?",(ticker,)).fetchone()
        n=conn.execute("SELECT count(*) FROM cohort").fetchone()[0]
        if not present and n>=100:
            return {"status":"COMPLETE","cohort":n}
        if not present:
            conn.execute("INSERT INTO cohort VALUES(?,?)",(ticker,ts));n+=1
        eligible=[(k,abs(seconds-s)) for k,s in CHECKPOINTS.items()
                  if abs(seconds-s)<=30]
        if not eligible:return {"status":"OBSERVING","cohort":n}
        checkpoint=min(eligible,key=lambda x:x[1])[0]
        if conn.execute("SELECT 1 FROM probes WHERE ticker=? AND checkpoint=?",
                       (ticker,checkpoint)).fetchone():
            return {"status":"ALREADY_RECORDED","cohort":n}
        report=scan_nison(state.get("candles"),ts)
        independent=forecast_nison_independent(report,state.get("market"),
                                              state.get("spot"),ts)
        p=independent.get("prob_above")
        if (p is not None and (isinstance(p,bool) or
             not isinstance(p,(int,float)) or not math.isfinite(p) or
             not 0<p<1)):
            p=None
        pattern_names=[e["name"] for e in report.get("pattern_evidence",[])]
        convergence=report.get("convergence") or {}
        conn.execute("""INSERT INTO probes VALUES(?,?,?,?,?,?,?,?,?,?)""",
                     (ticker,checkpoint,ts,seconds,baseline,p,
                      convergence.get("directional_bias"),
                      convergence.get("raw_experimental_direction_score"),
                      json.dumps(pattern_names,sort_keys=True),
                      independent.get("status","SHADOW_UNAVAILABLE")))
        return {"status":"RECORDED","cohort":n,"ticker":ticker,
                "checkpoint":checkpoint,"independent_available":p is not None,
                "patterns":pattern_names}


def _score(rows,outcomes):
    settled=[r for r in rows if r["ticker"] in outcomes]
    paired=[r for r in settled if r["independent_nison_p"] is not None]
    info={"snapshots":len(rows),"officially_settled":len(settled),
          "paired_n":len(paired),"independent_abstained":len(settled)-len(paired),
          "status":"NO_PAIRABLE_SETTLED_OBSERVATIONS" if not paired else "DESCRIPTIVE_NOT_ALPHA"}
    if not paired:return info
    baseline_brier=independent_brier=0.0
    baseline_acc=independent_acc=0
    for r in paired:
        y=1 if outcomes[r["ticker"]]=="yes" else 0
        p=r["baseline_p"]; q=r["independent_nison_p"]
        baseline_brier+=(p-y)**2
        independent_brier+=(q-y)**2
        baseline_acc+=int((p>=.5)==bool(y))
        independent_acc+=int((q>=.5)==bool(y))
    n=len(paired)
    return {**info,"baseline_brier":round(baseline_brier/n,6),
            "independent_nison_brier":round(independent_brier/n,6),
            "delta_nison_minus_baseline":round((independent_brier-baseline_brier)/n,6),
            "baseline_accuracy":round(baseline_acc/n,4),
            "independent_nison_accuracy":round(independent_acc/n,4)}


def report(conn,ledger=LEDGER):
    outcomes=read_results(ledger)
    n=conn.execute("SELECT count(*) FROM cohort").fetchone()[0]
    settled=conn.execute("SELECT ticker FROM cohort ORDER BY first_seen").fetchall()
    return {"trial":"independent_whole_book_nison_first_100_post_warmup",
            "contract_cohort_size":n,
            "officially_settled_contracts":sum(r["ticker"] in outcomes for r in settled),
            "checkpoints":{checkpoint:_score(conn.execute(
                "SELECT * FROM probes WHERE checkpoint=?",(checkpoint,)).fetchall(),
                outcomes) for checkpoint in CHECKPOINTS},
            "cautions":["No pattern reweighting based on these outcomes",
                        "Independent Nison probability is uncalibrated and uses spot as a proxy for BRTI",
                        "Do not equate forecasting accuracy with profitable executable trades",
                        "Separate start time may mean this and previous shadow study have different 100-contract cohorts"]}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=["once","collect","report"])
    p.add_argument("--db",default=DB)
    p.add_argument("--ledger",default=LEDGER)
    args=p.parse_args()
    if args.mode=="once":
        state=get_live()
        clock=time.time()
        if abs(clock-float(state["last_attempt"]))>75 or not state.get("ok"):
            raise SystemExit("Live state is unavailable or stale; no forecast")
        raw=scan_nison(state.get("candles"),state["last_attempt"])
        forecast=forecast_nison_independent(raw,state.get("market"),state.get("spot"),
                                             state["last_attempt"])
        print(json.dumps({"observed_at":state["last_attempt"],
              "ticker":(state.get("market") or {}).get("ticker"),
              "nison_forecast":forecast,
              "pattern_evidence":raw.get("pattern_evidence",[]),
              "convergence":raw.get("convergence"),
              "western_context":raw.get("western_context"),
              "methodology_status":raw.get("methodology_status")},
              indent=2))
        return
    conn=connect(args.db)
    if args.mode=="report":
        try:print(json.dumps(report(conn,args.ledger),indent=2))
        finally:conn.close()
        return
    try:
        while True:
            try:
                event=observe(conn,get_live())
                if event["status"] in ("RECORDED","WARMUP","COMPLETE"):
                    print(json.dumps(event),flush=True)
                if event["status"]=="COMPLETE":
                    return
            except (OSError,TypeError,KeyError,ValueError,sqlite3.Error,
                    ArithmeticError,TimeoutError) as ex:
                print(json.dumps({"status":"SKIPPED","reason":type(ex).__name__}),
                      flush=True)
            time.sleep(8)
    finally:
        conn.close()


if __name__=="__main__":
    main()
