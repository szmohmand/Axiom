"""Regression branches for immutable first calls and optional shadow grading.

This tests that unavailable models or malformed shadow probabilities never
create calls or bogus scored model records in the live SQLite ledger.
"""
from app.storage import Ledger


def test_first_call_unavailable_model_stays_unwatched(tmp_path):
    db=Ledger(str(tmp_path/"ledger.sqlite3"))
    try:
        market={"ticker":"KXBTC15M-NO-CALL","seconds_left":600,"target":64000}
        for model in ({"available":False,"side":"ABOVE","prob_above":.95},
                      {"available":True,"side":"WAIT","prob_above":.95},
                      {"available":True,"side":"BELOW","prob_above":None}):
            assert db.first_call(market,model,64000,1800000000) is None
            assert db.watch_info(market["ticker"]) is None
        assert db.conn.execute("SELECT count(*) FROM first_calls").fetchone()[0]==0
    finally:
        db.conn.close()


def test_shadow_malformed_probability_cannot_enter_official_grade(tmp_path):
    db=Ledger(str(tmp_path/"ledger.sqlite3"))
    try:
        market={"ticker":"KXBTC15M-NO-SHADOW","target":64000,
                "seconds_left":600,"market_mid":.5}
        model={"available":True,"prob_above":.65,"side":"ABOVE","engines":[]}
        invalid_shadow={"available":True,"name":"nison_candlestick_challenger",
                        "votes_in_ensemble":False,"can_trigger_paper_or_orders":False,
                        "prob_above":True}
        assert db.engine_snapshots(market,model,1800000000,invalid_shadow)==1
        rows=db.conn.execute("SELECT engine FROM engine_snapshots").fetchall()
        assert [r[0] for r in rows]==["ensemble"]
        # Still grades the genuine independent model; no invented shadow row.
        db.grade(market["ticker"],"yes",1800000600)
        assert db.engine_scores()["samples"]==1
    finally:
        db.conn.close()
