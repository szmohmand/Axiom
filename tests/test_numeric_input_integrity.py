"""Permanent guards for nonfinite probabilities, underflow and timestamp integrity."""
import math
from app import engine, settlement_research, orderbook


def changing_candles():
    out=[]
    for i in range(61):
        v=90000+math.sin(i*.73)*70+i*.3
        out.append({"t":1794938400-61*60+i*60,"close":v,"high":v+3,"low":v-3})
    return out


def test_nonfinite_or_unrepresentable_volatility_inputs_never_produce_direction():
    cs=changing_candles()
    for vals in ((float("nan"),90000,600),(float("inf"),90000,600),
                 (90000,float("nan"),600),(90000,float("inf"),600),
                 (90000,90000,float("nan")),(90000,90000,float("inf")),
                 (10**1000,90000,600),(90000,90000,10**1000),
                 (True,90000,600),(90000,False,600),(90000,90000,False)):
        out=engine.volatility_forecast(*vals,cs)
        assert out["available"] is False and out["side"]=="WAIT", vals
        assert out["prob_above"] is None and out["prob_below"] is None
    assert engine.numeric(10**1000) is None
    assert engine.utc_timestamp(float("nan")) is None
    assert engine.utc_timestamp(True) is None


def test_subsecond_or_underflowing_shadow_expiration_fails_closed():
    for remaining in (5e-324,1e-320,.00001,.99,0,-1):
        out=settlement_research.shadow_forecast_from_candles(
            changing_candles(),{"target":90000,"seconds_left":remaining},1794938400)
        assert out["available"] is False and out["side"]=="WAIT", remaining
        assert not out["can_trigger_paper_or_orders"]


def test_boolean_received_at_is_not_a_real_exchange_snapshot_timestamp():
    payload={"orderbook_fp":{"yes_dollars":[[".4","25"]],
                             "no_dollars":[[".4","25"]]}}
    ticker="KXBTC15M-NUMERIC-TEST"
    for t in (True,False,float("inf"),float("nan")):
        try:
            orderbook.normalize_orderbook(payload,ticker,t)
        except ValueError:
            pass
        else:
            raise AssertionError("Accepted invalid receipt time")
    valid=orderbook.normalize_orderbook(payload,ticker,2.)
    assert orderbook.current_book(valid,ticker,2.)
    valid["received_at"]=True
    assert not orderbook.current_book(valid,ticker,2.)


def test_valid_finite_forecast_and_full_depth_keep_previous_behavior():
    cs=changing_candles()
    result=engine.volatility_forecast(90000.,90000.,600,cs)
    assert result["available"] and result["side"] in ("ABOVE","BELOW")
    assert .005<=result["prob_above"]<=.995
    assert result["prob_above"]+result["prob_below"]==1
    ticker="KXBTC15M-NUMERIC-TEST"
    b=orderbook.normalize_orderbook(
        {"orderbook_fp":{"yes_dollars":[[".4","10"]],"no_dollars":[[".4","10"]]}},
        ticker,1234.)
    assert b["available"] and b["is_full_aggregated_depth"]
    assert orderbook.current_book(b,ticker,1234.)
