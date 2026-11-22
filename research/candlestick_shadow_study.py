"""Passive, point-in-time, 100-contract Nison shadow experiment on an EXISTING AXIOM server.

Reads ONLY localhost /api/state. Writes ONLY its independent study SQLite.
Never imports the live worker, opens exchange connections, touches orders,
edits the live ledger, or changes active forecasts. No future OHLCV is used.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from app.candlestick_context import read_candlestick_context
from app.candlestick_challenger import derive_candlestick_challenger

CHECKPOINTS = {"14m": 840, "10m": 600, "5m": 300, "1m": 60}
DEFAULT_DB = "/var/lib/axiom-candle-study/study.sqlite3"
DEFAULT_LEDGER = "/var/lib/axiom/bot.sqlite3"
DEFAULT_URL = "http://127.0.0.1:8000/api/state"
MAX_CONTRACTS = 100


def initialize(path: str) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS contracts(
            ticker TEXT PRIMARY KEY, first_seen REAL NOT NULL,
            close_ts REAL NOT NULL, first_seconds_left INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS observations(
            ticker TEXT NOT NULL, checkpoint TEXT NOT NULL,
            observed_at REAL NOT NULL, seconds_left INTEGER NOT NULL,
            ensemble_p REAL NOT NULL, challenger_p REAL NOT NULL,
            candidate_used INTEGER NOT NULL, trigger TEXT,
            market_mid REAL, context_status TEXT NOT NULL,
            PRIMARY KEY(ticker,checkpoint),
            FOREIGN KEY(ticker) REFERENCES contracts(ticker));
        CREATE INDEX IF NOT EXISTS ix_study_first_seen ON contracts(first_seen);
    """)
    return conn


def get_live(url: str = DEFAULT_URL) -> dict:
    # The running AXIOM service provides an atomic read-only snapshot.
    # Do NOT talk to Kalshi, Coinbase, Binance, Oracle control plane or keys.
    if url != DEFAULT_URL:
        raise ValueError("Only the existing local AXIOM API is permitted")
    with urlopen(url, timeout=8) as resp:
        if resp.status != 200:
            raise ValueError("AXIOM live API is not healthy")
        data = json.loads(resp.read(2_000_000))
    if not isinstance(data, dict):
        raise ValueError("Expected an AXIOM JSON state object")
    return data


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return x if math.isfinite(x) else None


def _market_data(data: dict, clock: float):
    if data.get("ok") is not True or data.get("status") != "LIVE":
        raise ValueError("AXIOM not healthy LIVE; skipping")
    timestamp = _number(data.get("last_attempt"))
    if timestamp is None or not 0 <= clock - timestamp <= 75:
        raise ValueError("Cached or future-dated live snapshot")
    market, model = data.get("market"), data.get("model")
    if not isinstance(market, dict) or not isinstance(model, dict):
        raise ValueError("Missing live market or ensemble")
    ticker = market.get("ticker")
    if not isinstance(ticker, str) or not ticker.startswith("KXBTC15M-") or len(ticker) > 120:
        raise ValueError("Not a real KXBTC15M ticker")
    end = _number(market.get("close_ts"))
    seconds = _number(market.get("seconds_left"))
    if end is None or seconds is None or not 0 < seconds <= 900:
        raise ValueError("Invalid active contract window")
    if abs((end - timestamp) - seconds) > 35:
        raise ValueError("Inconsistent market expiry timestamps")
    baseline = _number(model.get("prob_above"))
    if model.get("available") is not True or baseline is None or not 0 < baseline < 1:
        raise ValueError("No independent forecast to compare")
    return ticker, end, int(seconds), baseline, timestamp


def record_snapshot(conn: sqlite3.Connection, data: dict,
                    clock: float | None = None) -> dict:
    """Record one eligible, immutable trial checkpoint. First contract is warmup.

    Never overwrite a checkpoint. A missing candle hypothesis is a ZERO-effect
    challenger: the first 100 observed contracts stay the prespecified cohort
    rather than cherry-picking only winning or active candle patterns.
    """
    now = time.time() if clock is None else clock
    ticker, end, seconds, baseline, observed_at = _market_data(data, now)
    with conn:
        meta = conn.execute("SELECT value FROM metadata WHERE key='warmup_ticker'").fetchone()
        if meta is None:
            conn.execute("INSERT INTO metadata(key,value) VALUES('warmup_ticker',?)", (ticker,))
            return {"status": "WARMUP", "ticker": ticker, "sampled": 0}
        if ticker == meta["value"]:
            return {"status": "WARMUP", "ticker": ticker, "sampled": 0}

        existing = conn.execute("SELECT 1 FROM contracts WHERE ticker=?", (ticker,)).fetchone()
        count = conn.execute("SELECT count(*) FROM contracts").fetchone()[0]
        if not existing and count >= MAX_CONTRACTS:
            return {"status": "COHORT_COMPLETE", "contracts": count}
        if not existing:
            conn.execute("""INSERT INTO contracts(ticker,first_seen,close_ts,first_seconds_left)
                            VALUES(?,?,?,?)""", (ticker, observed_at, end, seconds))
            count += 1
        eligible = [(name,abs(seconds - target)) for name,target in CHECKPOINTS.items()
                    if abs(seconds-target) <= 30]
        if not eligible:
            return {"status": "OBSERVING", "contracts": count, "ticker": ticker}
        checkpoint = min(eligible,key=lambda x:x[1])[0]
        if conn.execute("SELECT 1 FROM observations WHERE ticker=? AND checkpoint=?",
                        (ticker,checkpoint)).fetchone():
            return {"status": "ALREADY_RECORDED", "contracts": count,
                    "checkpoint": checkpoint}

        try:
            context = read_candlestick_context(data.get("candles"), observed_at)
            challenger = derive_candlestick_challenger(context, data["model"])
        except (TypeError, KeyError, IndexError, ValueError, ArithmeticError):
            context = {"available": False, "status": "READER_UNAVAILABLE"}
            challenger = {"available": False}
        candidate_p = _number(challenger.get("prob_above"))
        qualified = bool(challenger.get("available") and candidate_p is not None and
                         0 < candidate_p < 1 and
                         challenger.get("votes_in_ensemble") is False and
                         challenger.get("can_trigger_paper_or_orders") is False)
        p = candidate_p if qualified else baseline
        market_mid = _number((data.get("market") or {}).get("market_mid"))
        if market_mid is not None and not 0 < market_mid < 1:
            market_mid = None
        conn.execute("""INSERT INTO observations
                        (ticker,checkpoint,observed_at,seconds_left,ensemble_p,
                         challenger_p,candidate_used,trigger,market_mid,context_status)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
                     (ticker,checkpoint,observed_at,seconds,baseline,p,
                      int(qualified),str(challenger.get("trigger") or "NONE")[:100],
                      market_mid,str(context.get("status") or "UNAVAILABLE")[:100]))
        return {"status": "RECORDED", "contracts": count, "ticker": ticker,
                "checkpoint": checkpoint, "candidate_used": qualified}


def read_results(ledger_path: str) -> dict[str, str]:
    """Read existing official Kalshi result grades without mutating AXIOM DB."""
    uri = Path(ledger_path).absolute().as_uri().replace("file://", "file:") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        rows = conn.execute("""SELECT ticker, result
                               FROM engine_snapshots WHERE result IN ('yes','no')
                               GROUP BY ticker,result""").fetchall()
    finally:
        conn.close()
    outcomes = {}
    conflicts = set()
    for ticker,result in rows:
        if ticker in outcomes and outcomes[ticker] != result:
            conflicts.add(ticker)
        outcomes[ticker] = result
    for ticker in conflicts:
        outcomes.pop(ticker,None)
    return outcomes


def _metrics(rows: list[sqlite3.Row], result_map: dict[str, str]) -> dict:
    matched = [r for r in rows if r["ticker"] in result_map]
    n = len(matched)
    if not n:
        return {"n": 0, "adjusted": 0, "status": "NOT_YET_GRADED"}
    brier_baseline = brier_candidate = log_baseline = log_candidate = 0.0
    correct_baseline = correct_candidate = 0
    signal_n = signal_base = signal_candidate = 0.0
    quote_n = quote_brier = 0.0
    adjustments = 0
    for row in matched:
        y = float(result_map[row["ticker"]] == "yes")
        a,b = row["ensemble_p"],row["challenger_p"]
        b0=(a-y)**2
        b1=(b-y)**2
        brier_baseline+=b0
        brier_candidate+=b1
        log_baseline+=-(y*math.log(max(a,1e-9))+(1-y)*math.log(max(1-a,1e-9)))
        log_candidate+=-(y*math.log(max(b,1e-9))+(1-y)*math.log(max(1-b,1e-9)))
        correct_baseline+=int((a>=.5)==bool(y))
        correct_candidate+=int((b>=.5)==bool(y))
        if row["candidate_used"]:
            adjustments += 1
            signal_n+=1
            signal_base+=b0
            signal_candidate+=b1
        q = row["market_mid"]
        if q is not None and 0 < q < 1:
            quote_n += 1
            quote_brier += (q-y)**2
    return {
        "n":n, "adjusted":adjustments, "coverage":round(adjustments/n,4),
        "baseline_brier":round(brier_baseline/n,6),
        "challenger_brier":round(brier_candidate/n,6),
        "delta_brier_challenger_minus_baseline":round((brier_candidate-brier_baseline)/n,6),
        "baseline_logloss":round(log_baseline/n,6),
        "challenger_logloss":round(log_candidate/n,6),
        "baseline_accuracy":round(correct_baseline/n,4),
        "challenger_accuracy":round(correct_candidate/n,4),
        "signal_only_brier_delta":round((signal_candidate-signal_base)/signal_n,6)
                                    if signal_n else None,
        "market_mid_brier":round(quote_brier/quote_n,6) if quote_n else None,
        "quote_n":int(quote_n),
        "status":"DESCRIPTIVE_ONLY_NOT_PROFITABILITY",
    }


def make_report(conn: sqlite3.Connection, result_map: dict[str,str]) -> dict:
    contracts = [dict(r) for r in conn.execute(
        "SELECT * FROM contracts ORDER BY first_seen,ticker LIMIT ?", (MAX_CONTRACTS,))]
    enrolled = len(contracts)
    settled = sum(c["ticker"] in result_map for c in contracts)
    output = {"trial":"first_100_prospectively_observed_live_contracts",
              "contracts_enrolled": enrolled, "contracts_settled": settled,
              "complete":enrolled==MAX_CONTRACTS and settled==MAX_CONTRACTS,
              "checkpoint_results": {},
              "bias_controls":"Warmup contract excluded; first 100 seen tickers fixed; "
                              "no-signal calls scored as unchanged baseline; "
                              "only point-in-time snapshot and existing official grades used"}
    for name in CHECKPOINTS:
        rows=conn.execute("SELECT * FROM observations WHERE checkpoint=?", (name,)).fetchall()
        score = _metrics(rows,result_map)
        score["snapshots"] = len(rows)
        score["missing_snapshots"] = enrolled-len(rows)
        output["checkpoint_results"][name]=score
    output["note"]="Negative challenger-minus-baseline Brier means better. "
                   "No improvement, accuracy, or trading profit is assumed. "
                   "If checkpoints are missing, results do not represent all 100 contracts."
    return output


def main() -> int:
    parser=argparse.ArgumentParser(description="AXIOM isolated first-100 candlestick study")
    parser.add_argument("mode",choices=["collect","once","report"])
    parser.add_argument("--database",default=DEFAULT_DB)
    parser.add_argument("--ledger",default=DEFAULT_LEDGER)
    parser.add_argument("--interval",type=int,default=8)
    args=parser.parse_args()
    conn=initialize(args.database)
    try:
        if args.mode=="report":
            print(json.dumps(make_report(conn,read_results(args.ledger)),indent=2))
            return 0
        while True:
            try:
                result=record_snapshot(conn,get_live())
                if result["status"] in ("RECORDED","WARMUP","COHORT_COMPLETE"):
                    print(json.dumps(result),flush=True)
            except (OSError,sqlite3.Error,ValueError,TimeoutError,KeyError) as exc:
                print(json.dumps({"status":"SKIPPED","reason":type(exc).__name__}),
                      flush=True)
            if args.mode=="once":
                return 0
            # Even after 100 are enrolled, existing contracts can still collect
            # later checkpoints. No unbounded loop enrolling new tickers.
            time.sleep(max(5,min(60,args.interval)))
    finally:
        conn.close()


if __name__=="__main__":
    raise SystemExit(main())
