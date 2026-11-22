"""Whole-book Nison pattern-grammar acceptance with real completed OHLC candles.

Each case is a controlled chronological market shape. Strict gaps are genuine
OHLC shadow gaps (not fabricated overlap tolerance). The structural detector
is tested independently so single-/multi-candle pattern behavior is isolated.
"""
import math
import pytest
from app import nison_methodology as nm


NOW=1800009600


def cb(o,c,hi=1,lo=1,vol=8):
    return (float(o),max(o,c)+hi,min(o,c)-lo,float(c),float(vol))


def bars(trend, tail, n=61, vol=8):
    assert len(tail)<n
    start=NOW-n*60
    out=[]
    for i in range(n):
        p=1000+2*trend*i
        if trend==0:p=1000
        out.append({"t":start+i*60,"open":p-.5,"close":p,
                    "high":p+2,"low":p-2,"volume":vol})
    anchor=out[-len(tail)-1]["close"] if tail else 0
    for j,v in enumerate(tail,1):
        o,h,l,c,volume=v
        assert l<=min(o,c)<=max(o,c)<=h
        out[-len(tail)-1+j].update(open=anchor+o,high=anchor+h,
                                   low=anchor+l,close=anchor+c,volume=volume)
    return out


def found(trend,tail,monkeypatch,n=61):
    monkeypatch.setattr(nm,"scan_structural_formations",lambda *a:[])
    report=nm.scan_nison(bars(trend,tail,n),NOW)
    assert report["available"],report["reason"]
    assert report["status"]=="READ_ONLY_UNCALIBRATED"
    assert report["votes_in_ensemble"] is False
    return {e["name"] for e in report["pattern_evidence"]}


CASES=[
    ("DARK_CLOUD_COVER",+1,[cb(0,12,1,1), (17,18,4,5,8)]),
    ("PIERCING_PATTERN",-1,[cb(12,0,1,1),(-5,8,-6,7,8)]),
    ("ON_NECK_PATTERN",-1,[cb(12,0,1,1),(-5,10,-6,-1,8)]),
    ("IN_NECK_PATTERN",-1,[cb(12,0,1,1),(-5,14,-6,1,8)]),
    ("THRUSTING_PATTERN",-1,[cb(12,0,1,1),(-5,8,-6,3,8)]),
    ("MORNING_DOJI_STAR",-1,[cb(12,0),(-1,1,-3,-1,8),cb(0,13)]),
    ("EVENING_DOJI_STAR",+1,[cb(0,12),(13,15,11,13,8),cb(13,-1)]),
    ("ABANDONED_BABY_BOTTOM",-1,[cb(12,0),(-8,-6,-10,-8,8),cb(0,12)]),
    ("ABANDONED_BABY_TOP",+1,[cb(0,12),(20,22,19,20,8),cb(12,0)]),
    ("THREE_WHITE_SOLDIERS",-1,[cb(0,12),cb(10,22),cb(20,32)]),
    ("THREE_BLACK_CROWS",+1,[cb(12,0),cb(2,-10),cb(-8,-20)]),
    ("BULLISH_HARAMI_CROSS",-1,[cb(12,0),(2,8,-1,2,8)]),
    ("BEARISH_HARAMI_CROSS",+1,[cb(0,12),(8,13,3,8,8)]),
    ("TWEEZERS_BOTTOM",-1,[cb(12,0),(0,8,-1,7,8)]),
    ("TWEEZERS_TOP",+1,[cb(0,12),(12,13,4,5,8)]),
    ("BULLISH_COUNTERATTACK",-1,[cb(12,0),(-4,1,-5,0,8)]),
    ("BEARISH_COUNTERATTACK",+1,[cb(0,12),(17,18,11,12,8)]),
    ("BULLISH_SEPARATING_LINES",+1,[cb(10,0),cb(10,20)]),
    ("BEARISH_SEPARATING_LINES",-1,[cb(0,10),cb(0,-10)]),
    ("UPSIDE_TASUKI_GAP",0,[cb(0,4),(9,13,8,12,8),(14,15,5.5,6,8)]),
    ("DOWNSIDE_TASUKI_GAP",0,[cb(10,6),(1,2,-3,-2,8),(-3,4,-4,3,8)]),
    ("BULLISH_GAPPING_SIDE_BY_SIDE",0,[cb(0,4),cb(10,13),cb(10,14)]),
    ("BEARISH_GAPPING_SIDE_BY_SIDE",0,[cb(0,4),cb(-8,-5),cb(-8,-4)]),
    ("RISING_THREE_METHODS",0,[cb(0,20),cb(10,11,2,2),cb(11,10,2,2),cb(17,26)]),
    ("FALLING_THREE_METHODS",0,[cb(20,0),cb(10,11,2,2),cb(11,10,2,2),cb(5,-8)]),
    ("HIGH_PRICE_GAPPING_PLAY",0,[cb(0,20),cb(17,18,2,1),cb(17,18,2,1),
                                   cb(17,18,2,1),cb(17,18,2,1),cb(25,30)]),
    ("LOW_PRICE_GAPPING_PLAY",0,[cb(20,0),cb(2,3,2,1),cb(2,3,2,1),
                                  cb(2,3,2,1),cb(2,3,2,1),cb(-4,-8)]),
    ("DRAGONFLY_DOJI",0,[(0,0,-10,0,8)]),
    ("GRAVESTONE_DOJI",0,[(0,10,0,0,8)]),
    ("LONG_LEGGED_DOJI",0,[(0,10,-10,0,8)]),
    ("BULLISH_CONFIRMATION",-1,[(0,2,-10,0,8),cb(1,5)]),
    ("BEARISH_CONFIRMATION",+1,[(0,10,-2,0,8),cb(-1,-5)]),
    ("SPRING",0,[(0,2,-10,1,25)]),
    ("UPTHRUST",0,[(0,10,-2,-1,25)]),
    ("BOX_BREAKOUT_UP",0,[cb(0,12,1,1,25)]),
    ("BOX_BREAKOUT_DOWN",0,[cb(0,-12,1,1,25)]),
]

@pytest.mark.parametrize("expected,trend,tail",CASES,ids=[x[0] for x in CASES])
def test_precise_completed_nison_candle_conditions(expected,trend,tail,monkeypatch):
    observed=found(trend,tail,monkeypatch)
    assert expected in observed,(expected,sorted(observed))


def test_nison_rough_candle_state_and_missing_volume(monkeypatch):
    monkeypatch.setattr(nm,"scan_structural_formations",lambda *a:[])
    d=bars(0,[(0,10,-10,0,8)])
    d[-1]["volume"]=None
    assert nm.scan_nison(d,NOW)["western_context"]["relative_volume"] is None
    d=bars(0,[cb(0,1)])
    x=nm.scan_nison(d,NOW)
    assert x["available"] and x["convergence"]["directional_bias"] in ("UP","DOWN","INDETERMINATE")


@pytest.mark.parametrize("modify",[
    lambda c:c.__delitem__(slice(0,40)),
    lambda c:c.__setitem__(0,False),
    lambda c:c.__setitem__(0,{**c[0],"high":float("nan")}),
    lambda c:c.__setitem__(0,{**c[0],"volume":-1}),
    lambda c:c.__setitem__(0,{**c[0],"t":c[0]["t"]+1}),
    lambda c:c.__setitem__(10,{**c[10],"t":c[10]["t"]+60}),
    lambda c:c.__setitem__(1,{**c[1],"close":-100}),
])
def test_nison_invalid_ohlc_timestamps_gap_and_volume_rejected(modify):
    data=bars(1,[])
    modify(data)
    assert nm.scan_nison(data,NOW)["available"] is False


def test_nison_short_future_stale_and_helper_defenses():
    with pytest.raises(ValueError,match="Boolean"):
        nm._number(True)
    with pytest.raises(ValueError,match="Nonfinite"):
        nm._number(float("inf"))
    assert nm._ema([],9) is None
    assert nm._rsi([1,2]) is None
    assert nm._stochastic([{"close":1,"high":2,"low":0}]) is None
    assert nm._linreg([1,2]) is None
    assert nm._trend([])=="UNKNOWN"
    assert nm.scan_nison(None,NOW)["available"] is False
    data=bars(0,[],31)
    assert nm.scan_nison(data,NOW)["available"]
    assert not nm.scan_nison(data[:-1],NOW)["available"]
    assert not nm.scan_nison(data,NOW+200)["available"]
    assert not nm.scan_nison(data,NOW-600)["available"]


def test_independent_nison_hypothesis_requires_real_strike_and_valid_clock(monkeypatch):
    monkeypatch.setattr(nm,"scan_structural_formations",lambda *a:[])
    data=bars(1,[cb(0,12)])
    r=nm.scan_nison(data,NOW)
    market={"target":1100,"close_ts":NOW+600,"seconds_left":600}
    forecast=nm.forecast_nison_independent(r,market,1101,NOW)
    assert forecast["available"]
    assert forecast["independent_from_axiom_ensemble"]
    assert not forecast["votes_in_ensemble"]
    assert not forecast["can_trigger_paper_or_orders"]
    for bad in [
        (None,market,1101,NOW),
        (r,None,1101,NOW),
        (r,{**market,"target":None},1101,NOW),
        (r,{**market,"close_ts":NOW-1},1101,NOW),
        (r,market,-1,NOW),
        (r,market,1101,float("inf")),
    ]:
        assert nm.forecast_nison_independent(*bad)["available"] is False


def test_nison_flag_and_pennant_impulses(monkeypatch):
    monkeypatch.setattr(nm,"scan_structural_formations",lambda *a:[])
    for direction in (-1,1):
        seq=[]
        for j in range(7):
            a=direction*j*10
            seq.append(cb(a,a+direction*9,1,1))
        end=direction*68
        seq.extend([cb(end+(j%2)*.3,end+(j%2)*.3,2,2) for j in range(7)])
        seq.append(cb(end+direction*6,end+direction*16))
        result=nm.scan_nison(bars(0,seq),NOW)
        assert result["available"]
        names={p["name"] for p in result["pattern_evidence"]}
        assert ("BULL_FLAG_BREAKOUT" if direction>0 else "BEAR_FLAG_BREAKOUT") in names
