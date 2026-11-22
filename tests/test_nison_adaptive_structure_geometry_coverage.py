"""Mathematical geometry and data-selected segmentation checks for Nison
large chart formations. Actual as-of candle objects, no Kalshi quote inputs.
"""
import math
import pytest
from app import nison_structures as ns


def bars_from_closes(values,width=2.):
    return [{"t":1800000000+i*60,"open":v-.5,"close":float(v),
             "high":v+width,"low":v-width,"volume":8.}
            for i,v in enumerate(values)]


def test_kernel_smoothing_bandwidth_and_extrema_noise_are_deterministic():
    line=[100+math.sin(i*.37)*5+i*.02 for i in range(75)]
    assert ns._auto_bandwidth(line)==ns._auto_bandwidth(line)
    assert ns._auto_bandwidth(line)>0
    assert ns._auto_bandwidth([1,1,1])>=1.5
    smooth=ns._smooth(line,ns._auto_bandwidth(line))
    assert len(smooth)==len(line)
    noise,atr=ns._noise_and_atr(bars_from_closes(line),smooth)
    assert noise>0 and atr>0
    turns=ns._turns(line,1)
    assert turns and all(x[1] in ("peak","trough") for x in turns)
    assert ns._turns([1,2,3,4],1)==[]
    assert len(ns._resample([.5]))==21
    assert ns._resample([.5])==[.5]*21
    assert ns._dtw_distance([0,1,0],[0,1,0])==pytest.approx(0)
    assert ns._dtw_distance([0,1,0],[1,0,1])>0
    assert ns._event("DEMO",1,100)["details"]["strength_unfitted"]==1
    assert ns._event("DEMO",-1,-99)["details"]["strength_unfitted"]==.01


@pytest.mark.parametrize("kind,highs,expected",[
    ("peak",[105,103,106],"THREE_MOUNTAIN_TOP"),
    ("peak",[104,111,105],"THREE_BUDDHA_TOP"),
    ("trough",[95,97,94],"THREE_RIVER_BOTTOM"),
    ("trough",[96,89,95],"INVERTED_THREE_BUDDHA"),
])
def test_confirmed_three_pivots_and_historical_neckline(kind,highs,expected):
    # All turning points are observed no later than the prior closed candle.
    is_top=kind=="peak"
    turns=[
        (5,kind,highs[0]),(10,"trough" if is_top else "peak",90 if is_top else 109),
        (15,kind,highs[1]),(20,"trough" if is_top else "peak",89 if is_top else 110),
        (25,kind,highs[2])]
    if not is_top:
        turns[1]=(10,"peak",109)
        turns[3]=(20,"peak",110)
    values=[100. for _ in range(30)]
    values[-1]=87 if is_top else 112
    candles=bars_from_closes(values)
    x=ns._triples(candles,turns,1,2)
    assert x and x[0]["name"]==expected
    assert x[0]["details"]["status"]=="CONFIRMED"
    assert x[0]["details"]["confirmed_close_beyond_both_counter_swings"]
    assert len(x[0]["details"]["turning_point_indices"])==5
    values[-1]=93 if is_top else 108
    incomplete=ns._triples(bars_from_closes(values),turns,1,2)
    assert incomplete and incomplete[0]["name"]==expected+"_FORMING"


def test_triples_reject_without_between_swings_or_with_small_extrema():
    values=[100.]*30
    candles=bars_from_closes(values)
    peaks=[(5,"peak",105),(15,"peak",105),(25,"peak",105)]
    assert ns._triples(candles,peaks,1,2)==[]
    alternating=[(5,"peak",101),(10,"trough",100),(15,"peak",101),
                 (20,"trough",100),(25,"peak",101)]
    assert ns._triples(candles,alternating,5,2)==[]


@pytest.mark.parametrize("curvature,expected,confirmed",[
    (1.0,"FRYPAN_BOTTOM",True),
    (-1.0,"DUMPLING_TOP",True),
    (1.0,"ROUNDING_BOTTOM_CANDIDATE",False),
    (-1.0,"ROUNDING_TOP_CANDIDATE",False),
])
def test_curved_geometry_bic_and_strict_gap(curvature,expected,confirmed):
    # Quadratic arc on previous completed bars; not hand-labelled.
    values=[1000+curvature*.09*(i-30)**2 for i in range(60)]
    prev=values[-1]
    values.append(prev+(20 if curvature>0 and confirmed else
                        -20 if curvature<0 and confirmed else 0))
    bars=bars_from_closes(values,width=.5)
    if confirmed and curvature>0:
        bars[-1].update(open=values[-1],high=values[-1]+.5,
                        low=values[-1]-.5,close=values[-1])
    if confirmed and curvature<0:
        bars[-1].update(open=values[-1],high=values[-1]+.5,
                        low=values[-1]-.5,close=values[-1])
    x=ns._rounded(bars,2)
    assert x and x[0]["name"]==expected
    assert x[0]["details"]["strict_nison_window"] is confirmed
    assert x[0]["details"]["bic_improvement"]>0


@pytest.mark.parametrize("direction",[-1,1])
def test_segmented_tower_and_change_point_structure(direction):
    # Three distinct legs: directional move, low-volatility pause, reversal.
    values=[]
    for i in range(12):values.append(1000+direction*i*5)
    for i in range(12):values.append(values[-1]+.02*math.sin(i))
    start=values[-1]
    for i in range(12):values.append(start-direction*(i+1)*6)
    bars=bars_from_closes(values,width=1.5)
    report=ns._towers(bars,3)
    assert report
    assert any("TOWER" in x["name"] for x in report)
    assert report[0]["details"]["selected_by"]=="THREE_SEGMENT_BIC_VS_LINE_AND_QUADRATIC"
    assert len(report[0]["details"]["learned_segment_boundaries"])==2


def test_structure_chooser_uses_strongest_not_duplicate_pattern(monkeypatch):
    bars=bars_from_closes([1000+math.sin(i/3) for i in range(40)])
    assert ns.scan_structural_formations(bars[:20],2)==[]
    assert ns.scan_structural_formations(bars,-1)==[]
    assert ns.scan_structural_formations(bars,float("nan"))==[]
    weak=ns._event("THREE_RIVER_BOTTOM",1,.12)
    strong=ns._event("THREE_RIVER_BOTTOM",1,.8)
    monkeypatch.setattr(ns,"_triples",lambda *a:[weak,strong])
    monkeypatch.setattr(ns,"_rounded",lambda *a:[])
    monkeypatch.setattr(ns,"_towers",lambda *a:[])
    result=ns.scan_structural_formations(bars,2)
    assert len(result)==1
    assert result[0]["experimental_weight"]==strong["experimental_weight"]
    assert result[0]["details"]["observed_closed_bars"]==len(bars)
    assert result[0]["details"]["adaptive_kernel_bandwidth_bars"]>0
