"""Research tests for flexible large Japanese formations, as-of-only candles."""
import math
import random

from app.nison_structures import scan_structural_formations


def candles(prices,gap=None):
    start=1800007200-len(prices)*60
    data=[]
    for i,p in enumerate(prices):
        opening=prices[i-1] if i else p
        high=max(opening,p)+.7
        low=min(opening,p)-.7
        if gap=="UP" and i==len(prices)-1:
            opening=prices[i-1]+4
            p=opening+2
            low=opening
            high=p+.7
        if gap=="DOWN" and i==len(prices)-1:
            opening=prices[i-1]-4
            p=opening-2
            high=opening
            low=p-.7
        data.append({"t":start+i*60,"open":opening,"high":high,
                     "low":low,"close":p,"volume":10})
    return data


def patterns(data):
    return {p["name"]:p for p in scan_structural_formations(data,3.)}


def test_rounded_without_gap_is_early_candidate_not_completed_nison_pattern():
    prices=[65000+18*(2*i/47-1)**2+.12*math.sin(i*3) for i in range(48)]+[65020]
    found=patterns(candles(prices))
    assert "ROUNDING_BOTTOM_CANDIDATE" in found
    assert "FRYPAN_BOTTOM" not in found
    assert "TOWER_BOTTOM" not in found
    assert found["ROUNDING_BOTTOM_CANDIDATE"]["details"]["status"]=="FORMING_NO_WINDOW"


def test_rounded_frypan_and_dumpling_require_real_window_and_have_bic_evidence():
    bottom=[65000+18*(2*i/47-1)**2+.12*math.sin(i*3) for i in range(48)]+[65020]
    top=[65000-18*(2*i/47-1)**2+.12*math.sin(i*3) for i in range(48)]+[64980]
    a=patterns(candles(bottom,"UP"))
    b=patterns(candles(top,"DOWN"))
    assert "FRYPAN_BOTTOM" in a,a
    assert "DUMPLING_TOP" in b,b
    assert a["FRYPAN_BOTTOM"]["details"]["strict_nison_window"] is True
    assert b["DUMPLING_TOP"]["details"]["bic_improvement"]>0
    assert a["FRYPAN_BOTTOM"]["details"]["curve_fit"]=="QUADRATIC_APPROXIMATION_NOT_ELLIPSE"


def test_three_mountains_allow_different_highs_and_use_dtw():
    x=[65000+8*math.cos(i*6*math.pi/45)+i*.04 for i in range(46)]+[64990]*5
    found=patterns(candles(x))
    assert "THREE_MOUNTAIN_TOP" in found,found
    shape=found["THREE_MOUNTAIN_TOP"]["details"]
    assert shape["unequal_extrema_allowed"] is True
    assert shape["dtw_normalized_distance"]>=0
    assert len(shape["turning_point_indices"])==5


def test_tower_change_points_detect_strong_move_lull_and_reverse():
    prices=[65000+2*i if i<15 else
            65030+.05*(i-15) if i<32 else
            65030-3*(i-32) for i in range(50)]
    result=patterns(candles(prices))
    assert "TOWER_TOP" in result,result
    assert result["TOWER_TOP"]["details"]["bic_improvement"]>0
    assert len(result["TOWER_TOP"]["details"]["learned_segment_boundaries"])==2


def test_random_walk_and_monotonic_do_not_automatically_become_large_patterns():
    random.seed(2)
    walk=[65000]
    for _ in range(50):
        walk.append(walk[-1]+random.gauss(0,1.8))
    assert patterns(candles(walk))=={}
    falling=[65000-3*i for i in range(50)]
    assert patterns(candles(falling))=={}


def test_every_result_is_experimental_evidence_and_never_an_order():
    samples=[
        [65000+18*(2*i/47-1)**2 for i in range(48)]+[65020],
        [65000+8*math.cos(i*6*math.pi/45)+i*.04 for i in range(46)]+[64990]*5,
    ]
    for data in samples:
        for r in scan_structural_formations(candles(data),3.):
            assert r["chapter"]==6
            assert abs(r["experimental_weight"])<=.8
            assert r["details"]["not_calibrated_win_probability"] is True
            assert r["details"]["rule_type"]=="DATA_ADAPTIVE_FORMAL_GEOMETRY"
            assert r["details"]["adaptive_kernel_bandwidth_bars"]>0
