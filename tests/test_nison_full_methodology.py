"""Nison whole-methodology shadow: deterministic behavioral, integrity and safety tests."""
import math

from app.nison_methodology import (
    _COVERAGE, _WEIGHTS, scan_nison, forecast_nison_independent,
)


def descending(now, n=50):
    origin = int(now // 60) * 60 - n * 60
    out = []
    for i in range(n):
        op = 65000 - 10*i
        out.append({"t":origin+i*60, "open":op,"high":op+3,
                    "low":op-9, "close":op-6,"volume":10})
    return out


def test_whole_book_inventory_and_nonvoting_safety():
    assert set(_COVERAGE) == set(str(i) for i in range(3,18))
    assert len(_WEIGHTS) >= 30
    now=1800007200
    x=scan_nison(descending(now),now)
    assert x["available"] is True
    assert x["independent"] is True
    assert x["votes_in_ensemble"] is False
    assert x["can_trigger_paper_or_orders"] is False
    assert set(("pattern_evidence","western_context","convergence","methodology_status")) <= x.keys()
    assert x["western_context"]["completed_candles"]==50


def test_strong_hammer_after_downtrend_and_separate_expiry_forecast():
    now=1800007200
    bars=descending(now)
    last=bars[-1]
    op=last["open"]
    bars[-1]={**last,"open":op,"high":op+2,"low":op-35,"close":op+1,"volume":50}
    report=scan_nison(bars,now)
    signals={p["name"] for p in report["pattern_evidence"]}
    assert "HAMMER" in signals,signals
    assert report["convergence"]["directional_bias"]=="UP"
    p=forecast_nison_independent(report,{"target":bars[-1]["close"]+50,
        "close_ts":now+600},bars[-1]["close"],now)
    assert p["available"] and 0<p["prob_above"]<1
    assert p["independent_from_axiom_ensemble"] is True
    assert p["votes_in_ensemble"] is False
    assert p["can_trigger_paper_or_orders"] is False
    assert p["calibrated"] is False


def test_no_lookahead_future_or_incomplete_bar_affects_pattern():
    now=1800007200
    bars=descending(now)
    original=scan_nison(bars,now)
    # A 1-minute live bar starting at now is NOT closed yet.
    incomplete={"t":now,"open":1,"high":1000000,"low":1,
                "close":900000,"volume":1000000}
    injected=scan_nison(bars+[incomplete],now)
    assert injected["available"]
    assert original["pattern_evidence"]==injected["pattern_evidence"]
    assert original["western_context"]==injected["western_context"]
    # Future bars beyond the present are invalid input.
    future={**incomplete,"t":now+120}
    assert not scan_nison(bars+[incomplete,{**incomplete,"t":now+60},future],now)["available"]


def test_no_genuine_window_or_dark_cloud_without_real_gap():
    now=1800007200
    bars=descending(now)
    # Oscillating contiguous one-minute candles with overlapping real bars.
    for i,b in enumerate(bars):
        b["open"]=65000+i*.01
        b["high"]=65005+i*.01
        b["low"]=64995+i*.01
        b["close"]=65000+(i+1)*.01
    report=scan_nison(bars,now)
    assert report["available"]
    assert "DARK_CLOUD_COVER" not in {x["name"] for x in report["pattern_evidence"]}
    assert "PIERCING_PATTERN" not in {x["name"] for x in report["pattern_evidence"]}
    assert "RISING_WINDOW" not in {x["name"] for x in report["pattern_evidence"]}
    assert "FALLING_WINDOW" not in {x["name"] for x in report["pattern_evidence"]}


def test_stale_missing_bars_and_bad_ohlcv_fail_closed():
    now=1800007200
    bars=descending(now)
    assert not scan_nison(bars[:21],now)["available"]
    assert not scan_nison(bars[:-1]+[{**bars[-1],"t":bars[-1]["t"]+60}],now)["available"]
    assert not scan_nison([{**x,"t":x["t"]-600} for x in bars],now)["available"]
    bad=list(bars);bad[-1]={**bad[-1],"high":bad[-1]["low"]-1}
    assert not scan_nison(bad,now)["available"]


def test_no_target_no_kalshi_forecast_from_directional_candle_only():
    now=1800007200
    report=scan_nison(descending(now),now)
    assert not forecast_nison_independent(report,{"target":None,
        "close_ts":now+600},65000,now)["available"]
    assert not forecast_nison_independent(report,{"target":65000,
        "close_ts":now+600},None,now)["available"]
    assert not forecast_nison_independent(report,{"target":65000,
        "close_ts":now-1},65000,now)["available"]


def test_transparent_untrained_weights_and_discretionary_gaps():
    report=scan_nison(descending(1800007200),1800007200)
    assert "AXIOM_HEURISTICS_NOT_NISON_STATISTICS" == report["convergence"]["weight_provenance"]
    assert "human_discretion_for_mountains_rivers_towers_dumpling_frypan" in report["western_context"]["missing_context"]
    assert "unverified_price_gap_equivalence" in report["western_context"]["missing_context"]
    assert report["reason"].find("no validated")>=0
