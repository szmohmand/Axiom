"""Realistic, deterministic offline acceptance of both read-only Nison studies.

The point is to exercise their previously unreviewed paths with real SQLite,
genuine as-of chronological OHLCV fixtures, explicit erroneous provider
responses, and guarded CLI loops. Never contacts networks or live deployments.
"""
import json
import math
import runpy
import sqlite3
import sys
from types import SimpleNamespace
import pytest

from research import candlestick_shadow_study as candle
from research import nison_full_shadow_study as full


CLOCK=1800000840.


def market_data(ticker="KXBTC15M-STUDY",clock=CLOCK,seconds=600,ok=True,mid=.40):
    bars=[]
    for i in range(61):
        p=63000+2*i+3*math.sin(i/5)
        bars.append({"t":int(clock-61*60+i*60),"open":p-1,
                     "close":p,"high":p+3,"low":p-3,"volume":3.0})
    return {"ok":ok,"status":"LIVE" if ok else "DEGRADED",
            "last_attempt":clock,"market":{
                "ticker":ticker,"seconds_left":seconds,
                "close_ts":clock+seconds,"target":63125,"market_mid":mid},
            "model":{"available":True,"prob_above":.65,"side":"ABOVE"},
            "spot":bars[-1]["close"],"candles":bars}


def test_passive_http_reader_never_accepts_other_host_or_non_200_or_json_array(monkeypatch):
    with pytest.raises(ValueError,match="local"):
        candle.get_live("http://malicious.example/api/state")
    class Response:
        def __init__(self, data, status=200):
            self.data=data;self.status=status
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self,n):return json.dumps(self.data).encode()
    monkeypatch.setattr(candle,"urlopen",lambda *a,**k:Response({},503))
    with pytest.raises(ValueError,match="healthy"):
        candle.get_live()
    monkeypatch.setattr(candle,"urlopen",lambda *a,**k:Response([1,2]))
    with pytest.raises(ValueError,match="JSON"):
        candle.get_live()
    monkeypatch.setattr(candle,"urlopen",lambda *a,**k:Response({"status":"LIVE"}))
    assert candle.get_live()["status"]=="LIVE"
    assert candle._number(True) is None
    assert candle._number("bad") is None
    assert candle._number(float("nan")) is None
    assert candle._number("4.0")==4.


@pytest.mark.parametrize("modify",[
    lambda s:s.update(ok=False),
    lambda s:s.update(last_attempt=CLOCK-80),
    lambda s:s.update(last_attempt=CLOCK+3),
    lambda s:s.update(market=None),
    lambda s:s["market"].update(ticker="WRONG"),
    lambda s:s["market"].update(ticker="KXBTC15M-"+("Z"*120)),
    lambda s:s["market"].update(seconds_left=0),
    lambda s:s["market"].update(seconds_left=920),
    lambda s:s["market"].update(close_ts=CLOCK+300),
    lambda s:s["model"].update(available=False),
    lambda s:s["model"].update(prob_above=1.3),
])
def test_research_live_validation_rejects_bad_asof_or_contract(modify):
    s=market_data()
    modify(s)
    with pytest.raises(ValueError):
        candle._market_data(s,CLOCK)


def test_first100_cohort_warmup_multiple_checkpoints_immutable_and_full(tmp_path,monkeypatch):
    db=candle.initialize(str(tmp_path/"study.sqlite3"))
    try:
        first=market_data("KXBTC15M-WARMUP")
        assert candle.record_snapshot(db,first,CLOCK)["status"]=="WARMUP"
        assert candle.record_snapshot(db,first,CLOCK)["status"]=="WARMUP"
        second=market_data("KXBTC15M-SECOND",mid=1.2)
        first_result=candle.record_snapshot(db,second,CLOCK)
        assert first_result["status"]=="RECORDED"
        assert first_result["checkpoint"]=="10m"
        assert candle.record_snapshot(db,second,CLOCK)["status"]=="ALREADY_RECORDED"
        assert db.execute("SELECT market_mid FROM observations").fetchone()[0] is None
        unexpected=market_data("KXBTC15M-THIRD",seconds=190)
        assert candle.record_snapshot(db,unexpected,CLOCK)["status"]=="OBSERVING"
        assert db.execute("SELECT count(*) FROM contracts").fetchone()[0]==2
        # A local candidate, even if available, must explicitly be nonvoting.
        monkeypatch.setattr(candle,"read_candlestick_context",
                            lambda *a:{"available":True,"status":"CLOSED"})
        monkeypatch.setattr(candle,"derive_candlestick_challenger",
                            lambda *a:{"available":True,"prob_above":.72,
                                       "votes_in_ensemble":False,
                                       "can_trigger_paper_or_orders":False,
                                       "trigger":"HAMMER"})
        fourth=market_data("KXBTC15M-FOURTH",seconds=840,mid=.22)
        assert candle.record_snapshot(db,fourth,CLOCK)["candidate_used"] is True
        row=db.execute("SELECT * FROM observations WHERE ticker=?",("KXBTC15M-FOURTH",)).fetchone()
        assert row["challenger_p"]==.72 and row["market_mid"]==.22
        # A broken pattern reader must become baseline, never an invented shift.
        monkeypatch.setattr(candle,"read_candlestick_context",
                            lambda *a:(_ for _ in ()).throw(ValueError("bad bar")))
        fifth=market_data("KXBTC15M-FIFTH",seconds=300)
        assert candle.record_snapshot(db,fifth,CLOCK)["candidate_used"] is False
        assert db.execute("SELECT challenger_p FROM observations WHERE ticker=?",
                          ("KXBTC15M-FIFTH",)).fetchone()[0]==.65
        for i in range(96):
            db.execute("INSERT INTO contracts VALUES(?,?,?,?)",
                       (f"KXBTC15M-COHORT-{i}",CLOCK,CLOCK+900,900))
        db.commit()
        assert db.execute("SELECT count(*) FROM contracts").fetchone()[0]==100
        assert candle.record_snapshot(db,market_data("KXBTC15M-OVERFLOW"),CLOCK)["status"]=="COHORT_COMPLETE"
    finally:
        db.close()


def test_official_result_conflicts_stay_ungraded_and_metrics_are_paired(tmp_path):
    ledger=tmp_path/"bot.sqlite3"
    with sqlite3.connect(ledger) as c:
        c.execute("CREATE TABLE engine_snapshots(ticker TEXT,result TEXT)")
        c.executemany("INSERT INTO engine_snapshots VALUES(?,?)",[
            ("KXBTC15M-A","yes"),("KXBTC15M-B","no"),
            ("KXBTC15M-CONFLICT","yes"),("KXBTC15M-CONFLICT","no"),
            ("KXBTC15M-OPEN",None)])
    grades=candle.read_results(str(ledger))
    assert grades=={"KXBTC15M-A":"yes","KXBTC15M-B":"no"}
    db=candle.initialize(str(tmp_path/"study.sqlite3"))
    try:
        db.executemany("INSERT INTO contracts VALUES(?,?,?,?)",[
            ("KXBTC15M-A",CLOCK,CLOCK+600,600),
            ("KXBTC15M-B",CLOCK+900,CLOCK+1500,600)])
        db.executemany("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)",[
            ("KXBTC15M-A","10m",CLOCK,600,.60,.72,1,"HAMMER",.35,"CLOSED"),
            ("KXBTC15M-B","10m",CLOCK,600,.65,.65,0,"NONE",None,"NO_SIGNAL")])
        db.commit()
        report=candle.make_report(db,grades)
        score=report["checkpoint_results"]["10m"]
        assert score["n"]==2 and score["adjusted"]==1
        assert score["quote_n"]==1 and score["market_mid_brier"] is not None
        assert score["signal_only_brier_delta"] is not None
        assert report["checkpoint_results"]["14m"]["status"]=="NOT_YET_GRADED"
        assert report["contracts_enrolled"]==2 and report["contracts_settled"]==2
    finally:
        db.close()


def test_isolated_candle_study_cli_modes_and_exception_recovery(tmp_path,monkeypatch,capsys):
    db=str(tmp_path/"study.sqlite3")
    monkeypatch.setattr(candle,"get_live",lambda:market_data())
    monkeypatch.setattr(candle,"record_snapshot",lambda *a:{"status":"COHORT_COMPLETE"})
    monkeypatch.setattr(sys,"argv",["study","collect","--database",db])
    assert candle.main()==0
    monkeypatch.setattr(sys,"argv",["study","once","--database",db])
    assert candle.main()==0
    monkeypatch.setattr(candle,"record_snapshot",
                        lambda *a:(_ for _ in ()).throw(ValueError("outage")))
    assert candle.main()==0
    assert '"status": "SKIPPED"' in capsys.readouterr().out
    monkeypatch.setattr(candle,"record_snapshot",lambda *a:{"status":"OBSERVING"})
    assert candle.main()==0  # No false claim that a checkpoint was recorded.
    ledger=str(tmp_path/"bot.sqlite3")
    with sqlite3.connect(ledger) as con:
        con.execute("CREATE TABLE engine_snapshots(ticker TEXT,result TEXT)")
    monkeypatch.setattr(sys,"argv",["study","report","--database",db,"--ledger",ledger])
    assert candle.main()==0
    assert "checkpoint_results" in capsys.readouterr().out
    class LoopTerminated(Exception): pass
    monkeypatch.setattr(sys,"argv",["study","collect","--database",db,"--interval","5"])
    monkeypatch.setattr(candle.time,"sleep",
                        lambda seconds:(_ for _ in ()).throw(LoopTerminated(seconds)))
    with pytest.raises(LoopTerminated):
        candle.main()


def test_nison_full_study_observe_and_score_all_cases(tmp_path,monkeypatch):
    db=full.connect(str(tmp_path/"whole.sqlite3"))
    try:
        state=market_data("KXBTC15M-WARM")
        assert full.observe(db,state,CLOCK)["status"]=="WARMUP"
        assert full.observe(db,state,CLOCK)["status"]=="WARMUP"
        next_state=market_data("KXBTC15M-SECOND")
        observed=full.observe(db,next_state,CLOCK)
        assert observed["status"]=="RECORDED"
        assert observed["checkpoint"]=="10m"
        assert full.observe(db,next_state,CLOCK)["status"]=="ALREADY_RECORDED"
        assert full.observe(db,market_data("KXBTC15M-NONCHECK",seconds=460),
                            CLOCK)["status"]=="OBSERVING"
        # Unusable outputs cannot become invented probabilities.
        monkeypatch.setattr(full,"scan_nison",
                            lambda *a:{"available":True,"pattern_evidence":[
                                {"name":"HAMMER"}],"convergence":{"directional_bias":"UP"}})
        monkeypatch.setattr(full,"forecast_nison_independent",
                            lambda *a:{"prob_above":float("nan"),"status":"NO_DATA"})
        bad=full.observe(db,market_data("KXBTC15M-BAD",seconds=840),CLOCK)
        assert bad["status"]=="RECORDED" and not bad["independent_available"]
        assert db.execute("SELECT independent_nison_p FROM probes WHERE ticker=?",
                          ("KXBTC15M-BAD",)).fetchone()[0] is None
        grades={"KXBTC15M-SECOND":"yes","KXBTC15M-BAD":"no"}
        rows=db.execute("SELECT * FROM probes").fetchall()
        aggregate=full._score(rows,grades)
        assert aggregate["officially_settled"]==2
        assert aggregate["independent_abstained"]>=1
        assert full._score(rows,{}).get("status")=="NO_PAIRABLE_SETTLED_OBSERVATIONS"
        monkeypatch.setattr(full,"read_results",lambda path:grades)
        assert full.report(db,"dummy")["contract_cohort_size"]>=3
        for i in range(97):
            db.execute("INSERT INTO cohort VALUES(?,?)",(f"KXBTC15M-{i}",CLOCK+i))
        db.commit()
        assert db.execute("SELECT count(*) FROM cohort").fetchone()[0]==100
        assert full.observe(db,market_data("KXBTC15M-OVERFLOW"),CLOCK)["status"]=="COMPLETE"
    finally:
        db.close()


def test_nison_full_study_cli_once_report_collect(tmp_path,monkeypatch,capsys):
    db=str(tmp_path/"whole.sqlite3")
    monkeypatch.setattr(full,"get_live",lambda:market_data())
    monkeypatch.setattr(full.time,"time",lambda:CLOCK)
    monkeypatch.setattr(sys,"argv",["full","once","--db",db])
    assert full.main() is None
    assert "nison_forecast" in capsys.readouterr().out
    monkeypatch.setattr(full,"get_live",lambda:market_data(ok=False))
    with pytest.raises(SystemExit,match="stale"):
        full.main()
    monkeypatch.setattr(full,"read_results",lambda _: {})
    monkeypatch.setattr(sys,"argv",["full","report","--db",db])
    assert full.main() is None
    assert "checkpoints" in capsys.readouterr().out
    monkeypatch.setattr(full,"observe",lambda *a:{"status":"COMPLETE"})
    monkeypatch.setattr(full,"get_live",lambda:market_data())
    monkeypatch.setattr(sys,"argv",["full","collect","--db",db])
    assert full.main() is None
    class LoopTerminated(Exception): pass
    monkeypatch.setattr(full,"observe",lambda *a:{"status":"RECORDED"})
    monkeypatch.setattr(full.time,"sleep",
                        lambda seconds:(_ for _ in ()).throw(LoopTerminated(seconds)))
    with pytest.raises(LoopTerminated):
        full.main()
    assert '"status": "RECORDED"' in capsys.readouterr().out
    monkeypatch.setattr(full,"observe",
                        lambda *a:(_ for _ in ()).throw(ValueError("test fault")))
    monkeypatch.setattr(full.time,"sleep",
                        lambda seconds:(_ for _ in ()).throw(LoopTerminated(seconds)))
    with pytest.raises(LoopTerminated):
        full.main()
    assert '"status": "SKIPPED"' in capsys.readouterr().out


def test_standalone_report_cli_entrypoints_without_network(tmp_path,monkeypatch):
    ledger=str(tmp_path/"grades.sqlite3")
    with sqlite3.connect(ledger) as db:
        db.execute("CREATE TABLE engine_snapshots(ticker TEXT,result TEXT)")
    monkeypatch.setattr(sys,"argv",["candle","report","--database",
         str(tmp_path/"candle.sqlite3"),"--ledger",ledger])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(candle.__file__,run_name="__main__")
    assert exc.value.code==0
    monkeypatch.setattr(sys,"argv",["full","report","--db",
         str(tmp_path/"full.sqlite3"),"--ledger",ledger])
    # This module's entrypoint calls main() directly and returns.
    runpy.run_path(full.__file__,run_name="__main__")
