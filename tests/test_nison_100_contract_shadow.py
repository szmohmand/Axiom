"""The passive Nison study never touches the existing bot, state or ledger."""
import math
import sqlite3

import pytest

from research.candlestick_shadow_study import (
    initialize, record_snapshot, make_report, read_results, get_live, MAX_CONTRACTS,
)


def snapshot(ticker, now, seconds=840, candles=None, p=0.55):
    if candles is None:
        origin=int(now//60)*60-60*40
        candles=[{"t":origin+i*60,
                  "open":60000+2*i, "high":60004+2*i,
                  "low":59998+2*i, "close":60001+2*i, "volume":10}
                 for i in range(40)]
    return {
        "ok":True,"status":"LIVE","last_attempt":now,
        "market":{"ticker":ticker,"seconds_left":seconds,
                  "close_ts":now+seconds,"market_mid":0.52},
        "model":{"available":True,"prob_above":p,
                 "engines":[{"name":"axiom_volatility","available":True,
                             "prob_above":0.6}]},
        "candles":candles,
    }


def test_no_signal_keeps_exact_baseline_and_original_state(tmp_path):
    conn=initialize(str(tmp_path/"study.db"))
    origin=1800002400
    warmup=snapshot("KXBTC15M-WARMUP",origin)
    assert record_snapshot(conn,warmup,origin+1)["status"]=="WARMUP"
    actual=snapshot("KXBTC15M-ONE",origin+900)
    saved=record_snapshot(conn,actual,origin+901)
    assert saved["status"]=="RECORDED"
    r=conn.execute("SELECT * FROM observations").fetchone()
    assert r["checkpoint"]=="14m"
    assert r["ensemble_p"]==r["challenger_p"]==.55
    assert r["candidate_used"]==0
    assert actual["model"]["prob_above"]==.55
    assert record_snapshot(conn,actual,origin+902)["status"]=="ALREADY_RECORDED"
    assert conn.execute("SELECT count(*) FROM observations").fetchone()[0]==1
    report=make_report(conn,{"KXBTC15M-ONE":"no"})
    assert report["contracts_enrolled"]==1
    assert report["contracts_settled"]==1
    assert report["complete"] is False
    assert report["checkpoint_results"]["14m"]["delta_brier_challenger_minus_baseline"]==0
    conn.close()


def test_completed_hammer_shift_is_graded_on_same_contract(tmp_path):
    conn=initialize(str(tmp_path/"study.db"))
    now=1800003600
    origin=now-40*60
    bars=[]
    for i in range(40):
        op=60000-10*i
        bars.append({"t":origin+60*i,"open":op,"high":op+3,
                     "low":op-8,"close":op-5,"volume":10})
    op=60000-10*39
    bars[-1]={"t":origin+60*39,"open":op,"high":op+3,
              "low":op-37,"close":op+1,"volume":100}
    record_snapshot(conn,snapshot("KXBTC15M-WARMUP",now),now+1)
    # Last candle ends at 'now'. No incomplete bar is consulted.
    s=snapshot("KXBTC15M-HAMMER",now,840,bars,0.55)
    outcome=record_snapshot(conn,s,now+1)
    assert outcome["status"]=="RECORDED" and outcome["candidate_used"]
    row=conn.execute("SELECT * FROM observations").fetchone()
    assert math.isclose(row["challenger_p"],.575)
    assert row["trigger"]=="HAMMER"
    report=make_report(conn,{"KXBTC15M-HAMMER":"yes"})
    metric=report["checkpoint_results"]["14m"]
    assert metric["n"]==1 and metric["adjusted"]==1
    assert metric["delta_brier_challenger_minus_baseline"]<0
    conn.close()


def test_ineligible_or_stale_snapshot_does_not_enter_trial(tmp_path):
    conn=initialize(str(tmp_path/"study.db"))
    now=1800003600
    record_snapshot(conn,snapshot("KXBTC15M-WARMUP",now),now)
    bad=snapshot("KXBTC15M-BAD",now)
    with pytest.raises(ValueError):
        record_snapshot(conn,bad,now+100)
    bad["ok"]=False
    with pytest.raises(ValueError):
        record_snapshot(conn,bad,now+1)
    bad["ok"]=True
    bad["model"]["available"]=False
    with pytest.raises(ValueError):
        record_snapshot(conn,bad,now+1)
    assert conn.execute("SELECT count(*) FROM contracts").fetchone()[0]==0
    conn.close()


def test_first_100_fixed_cohort_no_101st_or_reselection(tmp_path):
    conn=initialize(str(tmp_path/"study.db"))
    now=1800003600
    record_snapshot(conn,snapshot("KXBTC15M-WARMUP",now),now)
    for i in range(101):
        t=now+900*(i+1)
        result=record_snapshot(conn,snapshot(f"KXBTC15M-{i:03}",t),t)
        if i==100:
            assert result["status"]=="COHORT_COMPLETE"
    assert conn.execute("SELECT count(*) FROM contracts").fetchone()[0]==MAX_CONTRACTS
    assert conn.execute("SELECT count(*) FROM observations").fetchone()[0]==MAX_CONTRACTS
    conn.close()


def test_official_grades_are_read_only_and_dont_invent_results(tmp_path):
    ledger=tmp_path/"bot.sqlite3"
    c=sqlite3.connect(str(ledger))
    c.execute("CREATE TABLE engine_snapshots(ticker TEXT, result TEXT)")
    c.executemany("INSERT INTO engine_snapshots VALUES(?,?)",[
        ("KXBTC15M-1","yes"),("KXBTC15M-1","yes"),
        ("KXBTC15M-2",None),("KXBTC15M-3","yes"),
        ("KXBTC15M-3","no"),
    ])
    c.commit();c.close()
    before=ledger.stat().st_size
    assert read_results(str(ledger))=={"KXBTC15M-1":"yes"}
    after=ledger.stat().st_size
    assert before==after


def test_no_external_urls_are_ever_allowed():
    with pytest.raises(ValueError):
        get_live("https://api.evil.example/steal")
