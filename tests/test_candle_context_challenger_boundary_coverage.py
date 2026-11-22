"""Meaningful coverage of candle-context decisions and the isolated challenger.

All fixtures are closed, chronological BTC one-minute OHLCV; no Kalshi
quote fields or imagined fills enter any of these decisions.
"""
import math
import pytest
from app import candlestick_context as cc
from app import candlestick_challenger as ch

NOW=1800009600


def candle_bars(trend=0,n=61):
    out=[]
    for i in range(n):
        t=NOW-n*60+i*60
        close=1000+trend*2*i
        out.append({"t":t,"open":close-0.5,"close":close,
                    "high":close+2,"low":close-2,"volume":8.})
    return out


def replace_tail(out,o,c,up=1,down=1,volume=25):
    # Use the immediately previous close as the independent price anchor.
    p=out[-2]["close"]
    out[-1].update(open=p+o,close=p+c,high=p+max(o,c)+up,
                   low=p+min(o,c)-down,volume=volume)
    return out


def names(snapshot):
    assert snapshot["available"], snapshot["reason"]
    assert not snapshot["votes_in_ensemble"]
    assert not snapshot["changes_forecast_probability"]
    return {e["name"] for e in snapshot["formations"]}


@pytest.mark.parametrize("variant",[
    "bad_clock","bool_clock","bad_list","row_not_dict","bad_number",
    "bad_gap","future","bad_ohlc","bad_volume","short","stale","zero_range",
])
def test_candle_context_defensively_rejects_invalid_raw_data(variant):
    data=candle_bars(-1)
    now=NOW
    if variant=="bad_clock":now=float("nan")
    if variant=="bool_clock":now=True
    if variant=="bad_list":data=None
    if variant=="row_not_dict":data[0]=False
    if variant=="bad_number":data[0]["open"]=float("inf")
    if variant=="bad_gap":data[3]["t"]+=60
    if variant=="future":
        # Entire time series remains strictly 60-second spaced; only the
        # as-of future-timestamp defense may reject these real-shaped bars.
        for row in data:row["t"]+=3600
    if variant=="bad_ohlc":data[0]["high"]=0
    if variant=="bad_volume":data[0]["volume"]=-1
    if variant=="short":data=data[:10]
    if variant=="stale":now=NOW+500
    if variant=="zero_range":
        for row in data:
            row["open"]=1000.
            row["close"]=1000.
            row["high"]=1000.
            row["low"]=1000.
    result=cc.read_candlestick_context(data,now)
    assert result["available"] is False,variant


def test_candle_context_short_trend_and_missing_volume_path():
    assert cc._trend_before(candle_bars()[:5],1,2)=="UNKNOWN"
    assert cc._trend_before(candle_bars(1),1,2)=="UP"
    assert cc._trend_before(candle_bars(-1),1,2)=="DOWN"
    assert cc._trend_before(candle_bars(0),1,2)=="RANGE"
    data=candle_bars()
    data[-10]["volume"]=None
    result=cc.read_candlestick_context(data,NOW)
    assert result["available"]
    assert result["measurements"]["relative_volume_to_previous_20_median"] is None
    data=candle_bars()
    for row in data:row["volume"]=0
    assert cc.read_candlestick_context(data,NOW)["available"]


@pytest.mark.parametrize("label,trend,o,c,up,down",[
    ("HANGING_MAN",1,8,9,0.2,15),
    ("SHOOTING_STAR",1,0,0.2,15,0.1),
    ("INVERTED_HAMMER",-1,0,0.2,15,0.1),
    ("HAMMER",-1,8,9,0.2,15),
    ("LONG_BODY_WITH_TREND",1,0,13,.5,.5),
    ("LOWER_WICK_REJECTION",0,0,8,.1,10),
    ("UPPER_WICK_REJECTION",0,8,0,10,.1),
])
def test_completed_context_wicks_and_trend(label,trend,o,c,up,down):
    data=replace_tail(candle_bars(trend),o,c,up,down)
    actual=names(cc.read_candlestick_context(data,NOW))
    assert label in actual,(label,actual)


@pytest.mark.parametrize("label,trend,prior,current",[
    ("BULLISH_ENGULFING",-1,(12,0),(-1,14)),
    ("BEARISH_ENGULFING",1,(0,12),(14,-1)),
])
def test_engulfing_requires_body_not_just_wick(label,trend,prior,current):
    d=candle_bars(trend)
    anchor=d[-3]["close"]
    for j,(o,c) in enumerate((prior,current)):
        d[-2+j].update(open=anchor+o,close=anchor+c,
                       high=anchor+max(o,c)+1,
                       low=anchor+min(o,c)-1,volume=25.)
    assert label in names(cc.read_candlestick_context(d,NOW))


@pytest.mark.parametrize("label,o,c,up,down",[
    ("SPRING",0,1,1,9),
    ("UPTHRUST",0,-1,9,1),
    ("BOX_BREAKOUT_UP",0,12,1,1),
    ("BOX_BREAKOUT_DOWN",0,-12,1,1),
])
def test_volume_confirmed_prior_range_events(label,o,c,up,down):
    d=replace_tail(candle_bars(0),o,c,up,down,volume=60)
    assert label in names(cc.read_candlestick_context(d,NOW))


def test_doji_pause_and_default_read_without_causal_claims():
    flat=candle_bars()
    flat[-1].update(open=1000,close=1000,high=1010,low=990)
    r=cc.read_candlestick_context(flat,NOW)
    assert r["available"] and "DOJI" in names(r)
    assert r["market_read"] in ("TREND_STALL_WARNING","NO_DISTINCTIVE_FORMATION")
    assert r["reason"].startswith("Descriptive")
    trend=candle_bars(1)
    trend[-1].update(open=trend[-2]["close"],close=trend[-2]["close"],
                     high=trend[-2]["close"]+10,low=trend[-2]["close"]-10)
    assert cc.read_candlestick_context(trend,NOW)["market_read"]=="TREND_STALL_WARNING"


def test_challenger_invalid_ensemble_forms_and_conflicting_signals():
    valid={"available":True,"prior_trend":"UP","formations":[]}
    base={"available":True,"prob_above":.6}
    for context in (None,{},{"available":False},):
        assert not ch.derive_candlestick_challenger(context,base)["available"]
    for ens in (None,{},{"available":False},):
        assert not ch.derive_candlestick_challenger(valid,ens)["available"]
    for v in (True,"unknown",float("inf"),-1,1.2):
        assert not ch.derive_candlestick_challenger(valid,
             {"available":True,"prob_above":v})["available"]
    for formations in (None,{"not":"list"},[None],[{"name":"HAMMER","confluence":None}]):
        assert not ch.derive_candlestick_challenger(
            {**valid,"formations":formations},base)["available"]
    conflict=[{"name":"HAMMER","confluence":["PRIOR_SUPPORT"]},
              {"name":"SHOOTING_STAR","confluence":["PRIOR_RESISTANCE"]}]
    assert "Conflicting" in ch.derive_candlestick_challenger(
        {**valid,"formations":conflict},base)["reason"]


def test_challenger_takes_correlated_observations_only_when_supported():
    base={"available":True,"prob_above":.56}
    for trend,p in (("UP",.575),("DOWN",.545)):
        context={"available":True,"prior_trend":trend,
                 "formations":[{"name":"LONG_BODY_WITH_TREND",
                                "confluence":["RELATIVE_VOLUME_SPIKE"]}]}
        result=ch.derive_candlestick_challenger(context,base)
        assert result["available"] and result["prob_above"]==pytest.approx(p)
        assert not result["votes_in_ensemble"]
    invalid={"available":True,"prior_trend":"RANGE",
             "formations":[{"name":"LONG_BODY_WITH_TREND",
                            "confluence":["RELATIVE_VOLUME_SPIKE"]}]}
    assert not ch.derive_candlestick_challenger(invalid,base)["available"]
    for prob,direction in ((.995,1),(.005,-1)):
        candidate={"available":True,"prior_trend":"UP" if direction>0 else "DOWN",
                   "formations":[{"name":"HAMMER" if direction>0 else "UPTHRUST",
                                  "confluence":["RELATIVE_VOLUME_SPIKE"]}]}
        result=ch.derive_candlestick_challenger(
            candidate,{"available":True,"prob_above":prob})
        assert not result["available"] and "cap" in result["reason"]


def test_wick_only_rejection_has_its_own_market_read_not_forced_breakout():
    data=replace_tail(candle_bars(0),0,4,up=1,down=7,volume=8)
    result=cc.read_candlestick_context(data,NOW)
    assert result["available"]
    assert result["market_read"]=="LOCAL_REJECTION_OBSERVED"
    assert "LOWER_WICK_REJECTION" in names(result)
    # Recognized but uncorroborated pattern does not vote in the legacy shadow.
    context={"available":True,"prior_trend":"DOWN",
             "formations":[{"name":"HAMMER","confluence":[]}]}
    assert not ch.derive_candlestick_challenger(
        context,{"available":True,"prob_above":.55})["available"]
