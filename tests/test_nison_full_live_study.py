"""Isolated independent full-Nison live collector does not affect original AXIOM."""
import sqlite3

from research.nison_full_shadow_study import connect,observe,report


def state(ticker,now,remaining=840):
    origin=int(now//60)*60-50*60
    bars=[]
    for i in range(50):
        o=62000-i*4
        bars.append({"t":origin+i*60,"open":o,"high":o+2,
                     "low":o-7,"close":o-3,"volume":10})
    return {
        "ok":True,"status":"LIVE","last_attempt":now,
        "market":{"ticker":ticker,"seconds_left":remaining,
                  "close_ts":now+remaining,"target":62000},
        "model":{"available":True,"prob_above":.55},
        "spot":bars[-1]["close"],
        "candles":bars,
    }


def test_independent_probe_and_original_prediction_unchanged(tmp_path):
    conn=connect(str(tmp_path/"full.db"))
    now=1800007200
    assert observe(conn,state("KXBTC15M-WARMUP",now),now)["status"]=="WARMUP"
    actual=state("KXBTC15M-ACTUAL",now+900)
    before=actual["model"]["prob_above"]
    item=observe(conn,actual,now+900)
    assert item["status"]=="RECORDED"
    row=conn.execute("SELECT * FROM probes").fetchone()
    assert row["baseline_p"]==before==.55
    assert row["independent_nison_p"] is not None
    assert 0<row["independent_nison_p"]<1
    assert actual["model"]["prob_above"]==.55
    assert observe(conn,actual,now+900)["status"]=="ALREADY_RECORDED"
    assert conn.execute("SELECT count(*) FROM probes").fetchone()[0]==1
    conn.close()


def test_first_100_cohort_and_readonly_official_grade(tmp_path):
    conn=connect(str(tmp_path/"full.db"))
    now=1800007200
    observe(conn,state("KXBTC15M-WARMUP",now),now)
    for i in range(101):
        ts=now+900*(i+1)
        result=observe(conn,state(f"KXBTC15M-{i:03}",ts),ts)
        if i==100: assert result["status"]=="COMPLETE"
    assert conn.execute("SELECT count(*) FROM cohort").fetchone()[0]==100
    assert conn.execute("SELECT count(*) FROM probes").fetchone()[0]==100

    ledger=tmp_path/"original.sqlite3"
    l=sqlite3.connect(str(ledger))
    l.execute("CREATE TABLE engine_snapshots(ticker TEXT,result TEXT)")
    l.execute("INSERT INTO engine_snapshots VALUES('KXBTC15M-000','yes')")
    l.commit();l.close()
    result=report(conn,str(ledger))
    assert result["contract_cohort_size"]==100
    assert result["officially_settled_contracts"]==1
    assert result["checkpoints"]["14m"]["paired_n"]==1
    assert result["checkpoints"]["14m"]["snapshots"]==100
    conn.close()
