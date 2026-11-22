"""Regressions for non-voting Nison-inspired candle context and challenger.

No lookahead, fabricated OHLC, Kalshi quote input, automatic trade, baseline
ensemble mutation, or historical grade rewriting is permitted.
"""
import math

from app.candlestick_context import read_candlestick_context
from app.candlestick_challenger import derive_candlestick_challenger
from app.ensemble import engine_pack
from app.storage import Ledger
from test_e2e_synthetic import env


def declining_bars(n=40):
    start=1800000000//60*60
    values=[]
    for i in range(n):
        op=60000-10*i
        close=op-5
        values.append({"t":start+60*i, "open":op, "high":op+3,
                       "low":close-3, "close":close, "volume":10.0})
    # A hammer at the end of a decline, confirmed by actual elevated volume.
    op=60000-10*(n-1)
    values[-1]={"t":start+60*(n-1), "open":op,
                 "high":op+3, "low":op-37,
                 "close":op+1, "volume":100.0}
    return values


def test_completed_hammer_is_contextual_not_direct_trade():
    bars=declining_bars()
    now=bars[-1]["t"]+60
    context=read_candlestick_context(bars,now)
    assert context["available"]
    assert context["prior_trend"]=="DOWN"
    assert "HAMMER" in [x["name"] for x in context["formations"]]
    assert context["votes_in_ensemble"] is False
    assert context["changes_forecast_probability"] is False
    assert context["can_trigger_paper_or_orders"] is False
    ensemble={"available":True,"prob_above":0.6}
    challenger=derive_candlestick_challenger(context,ensemble)
    assert challenger["available"]
    assert math.isclose(challenger["prob_above"],.625,abs_tol=1e-9)
    assert challenger["independent"] is False
    assert challenger["votes_in_ensemble"] is False
    assert challenger["can_trigger_paper_or_orders"] is False
    assert ensemble["prob_above"]==.6


def test_unclosed_future_bar_cannot_leak_into_context():
    bars=declining_bars()
    now=bars[-1]["t"]+61
    original=read_candlestick_context(bars,now)
    new_bar={"t":bars[-1]["t"]+60,"open":65000,
             "high":99000,"low":64000,"close":98000,"volume":999999}
    after=read_candlestick_context(bars+[new_bar],now)
    assert original==after
    assert original["measurements"]["last_completed_bar_end"]<=now


def test_gap_invalid_and_stale_market_candles_fail_closed():
    bars=declining_bars()
    now=bars[-1]["t"]+60
    assert not read_candlestick_context(bars[:10]+bars[11:],now)["available"]
    assert not read_candlestick_context(bars,now+500)["available"]
    malformed=[dict(b) for b in bars]
    malformed[3]["high"]=float("nan")
    assert not read_candlestick_context(malformed,now)["available"]


def test_candle_name_alone_never_forces_direction():
    model={"available":True,"prob_above":.51}
    context={"available":True,"prior_trend":"UP","formations":[
        {"name":"DOJI","confluence":[]},
        {"name":"HANGING_MAN","confluence":["RELATIVE_VOLUME_SPIKE"]},
    ]}
    assert not derive_candlestick_challenger(context,model)["available"]
    assert model["prob_above"]==.51


def test_correlated_candidate_not_allowed_to_vote_in_original_ensemble():
    from app.engine import normalize_candles
    raw=[]
    start=1800000000//60*60
    for i in range(62):
        op=60000+i*3
        raw.append([start+i*60,op-4,op+8,op,op+2,20])
    bars=normalize_candles(raw)
    market={"target":60070,"seconds_left":600,"market_mid":.72}
    baseline=engine_pack(60090,market,bars)
    signal_context=read_candlestick_context(bars,bars[-1]["t"]+60)
    derive_candlestick_challenger(signal_context,baseline)
    after=engine_pack(60090,market,bars)
    assert baseline==after
    assert all(e["name"]!="nison_candlestick_challenger" for e in after["engines"])


def test_optional_shadow_grade_is_prospective_and_keeps_prior_rows(tmp_path):
    ledger=Ledger(str(tmp_path/"score.sqlite3"))
    model={"available":True, "prob_above":.61,
           "engines":[{"name":"axiom_volatility","available":True,"prob_above":.65}]}
    candle={"available":True,"name":"nison_candlestick_challenger",
            "prob_above":.635,"votes_in_ensemble":False,
            "can_trigger_paper_or_orders":False}
    first={"ticker":"KXBTC15M-NISON-1","seconds_left":600,"market_mid":.55}
    # Old API and scoring are byte-for-byte compatible when not opted in.
    assert ledger.engine_snapshots(first,model,1800000000)==2
    ledger.engine_snapshots(first,model,1800000000,candle)
    assert ledger.conn.execute("SELECT count(*) FROM engine_snapshots WHERE ticker=?",
                               (first["ticker"],)).fetchone()[0]==3
    second={"ticker":"KXBTC15M-NISON-2","seconds_left":600,"market_mid":.55}
    ledger.engine_snapshots(second,model,1800000900,candle)
    assert ledger.conn.execute("SELECT count(*) FROM engine_snapshots WHERE ticker=?",
                               (second["ticker"],)).fetchone()[0]==3
    ledger.grade(second["ticker"],"yes",1800001800)
    scores=ledger.engine_scores()["scores"]
    shadow=next(s for s in scores if s["engine"]=="nison_candlestick_challenger")
    assert shadow["n"]==1 and shadow["market_brier"] is not None
    assert shadow["validated_alpha"] is False


def test_live_pipeline_exposes_shadow_without_change_to_original_model(env):
    main,clock,p,client,_=env
    clock.now=p.close-600
    result=main.update_once()
    assert result["candlestick_context"]["votes_in_ensemble"] is False
    assert result["candlestick_challenger"]["votes_in_ensemble"] is False
    assert result["candlestick_challenger"]["can_trigger_paper_or_orders"] is False
    original=engine_pack(result["spot"],result["market"],result["candles"],
                         signals=result["btc_signals"])
    assert result["model"]==original
    assert all(e["name"]!="nison_candlestick_challenger"
               for e in result["engines"])
    got=client.get("/api/state").json()
    assert "candlestick_context" in got and "candlestick_challenger" in got
