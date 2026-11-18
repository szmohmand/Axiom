"""Targeted hard-to-reach validation paths, without weakening existing gates."""
from datetime import datetime
import pytest
from app import engine,orderbook,settlement_reference,depth_intelligence
from test_e2e_synthetic import env


def test_participant_quote_fallback_is_explicitly_not_a_forecast():
    m=engine.market_snapshot({
        "ticker":"KXBTC15M-TEST","close_time":"2026-11-17T18:00:00Z",
        "floor_strike":"90000","yes_bid_dollars":".60","yes_ask_dollars":".40",
        "no_bid_dollars":".55","no_ask_dollars":".50"},1794938000)
    assert m["market_mid"]==.45
    assert m["market_price_is_forecast"] is False


def test_unattractive_model_quote_discrepancy_does_not_generate_entry():
    m={"yes_ask":.85,"no_ask":.85,"seconds_left":600}
    r=engine.opportunity({"available":True,"prob_above":.5},m)
    assert r["side"]=="WAIT"
    assert r["edge"]<0


def test_book_price_level_safety_bound_and_invalid_ticker():
    with pytest.raises(ValueError,match="safety bound"):
        orderbook.normalize_orderbook({"orderbook_fp":{
            "yes_dollars":[[".1","1"]]*10001,"no_dollars":[]}},"KXBTC15M-TEST",1000)
    with pytest.raises(ValueError,match="active BTC15m"):
        orderbook.normalize_orderbook({"orderbook_fp":{
            "yes_dollars":[],"no_dollars":[]}},"OTHER",1000)


def test_settlement_timestamp_rejects_microsecond_boundary():
    with pytest.raises(ValueError,match="exact second"):
        settlement_reference._time("2026-11-17T18:00:00.000001Z")


def test_fee_empty_sweep_explicitly_zero_and_never_an_official_quote():
    assert depth_intelligence._fee_estimate({"available_contracts":0,"average_price":None},"YES")==0


def test_main_health_rejects_absent_model_without_a_source_exception(env):
    main,clock,p,client,_=env
    with main.state_lock:
        main.state.update({"errors":{},"last_attempt":clock.now,
                           "market":None,"spot":None,"model":None,"candles":[]})
        main._refresh_status_locked()
        assert main.state["status"]=="DEGRADED"
