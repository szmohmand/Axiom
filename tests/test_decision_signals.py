"""Regression tests: live-wired signals, stale guards, touch vs direction and execution."""
from math import sin
from app.decision_signals import derive_signals, execution_decision

T=1800000000
def fixture():
    candles=[]
    for i in range(61):
        t=T-3600+i*60
        price=60000+i*2+6*sin(i*.7)
        candles.append({"t":t,"close":price,"open":price-1.5,"high":price+3,"low":price-3,"volume":3})
    market={"ticker":"KXBTC15M-TEST","target":60090,"close_ts":T+300,
            "seconds_left":300,"market_mid":.5}
    return market, candles[-1]["close"],candles

def test_distance_time_acceleration_magnitude_and_touch_are_wired():
    m,s,c=fixture()
    d=derive_signals(m,s,c,T,spot_received_at=T,spot_source_at=T)
    assert d["available"] and 0<d["prob_above"]<1
    assert d["price_reference"]=="COINBASE_PROXY_NOT_SETTLEMENT"
    assert 0<=d["target_touch_probability"]<=1
    assert 0<=d["movement_2m_probability_5bp"]<=1
    assert not d["immediate_direction_from_move_probability"]
    assert d["acceleration_bps_per_min"] is not None
    assert d["distance_volatility_z"] is not None
    assert d["forecast_type"]=="end_of_contract"
    d2=derive_signals({**m,"close_ts":T+30},s,c,T)
    assert d2["prob_above"]!=d["prob_above"]

def test_fresh_brti_is_distinct_from_spot_proxy():
    m,s,c=fixture()
    b={"status":"STREAMING","authenticated_stream_verified":True,
       "latest_value_usd":60120,"source_ts_ms":T*1000,
       "axiom_received_at_ms":T*1000}
    d=derive_signals(m,s,c,T,brti=b)
    assert d["price_reference"]=="AUTHENTICATED_LIVE_BRTI"
    assert d["reference_value"]==60120
    b["source_ts_ms"]=(T-200)*1000
    assert derive_signals(m,s,c,T,brti=b)["settlement_proxy_warning"]

def test_stale_bad_candles_and_bad_receipt_fail_closed():
    m,s,c=fixture()
    assert not derive_signals(m,s,c,T,spot_received_at=T-120)["available"]
    assert not derive_signals(m,s,c,T+700)["available"]
    c[12]["t"] += 5
    assert not derive_signals(m,s,c,T)["available"]

def test_early_displacement_and_reversal_flag():
    m,s,c=fixture()
    d=derive_signals(m,s,c,T)
    assert d["early_displacement_bps"] is not None
    assert d["first_two_minute_reversal_flag"] in ("NO","EARLY_DOWN_REBOUND_TENDENCY","EARLY_UP_NO_RELIABLE_REVERSAL")

def test_execution_50_50_filter_and_missing_liquidity():
    m,s,c=fixture()
    d=derive_signals(m,s,c,T)
    f={"available":True,"prob_above":.62,"side":"ABOVE"}
    choice={"side":"YES","spread":.02,"size_contracts":10.,
            "ask_sweep":{"average_price":.38},"bid_sweep":{"average_price":.36},
            "net_estimated_model_minus_cost":.18}
    op={"status":"CANDIDATE","selected":choice}
    book={"available":True,"ticker":m["ticker"],"received_at":T}
    assert execution_decision(d,f,m,book,op,T+60)["action"]=="WAIT"
    assert execution_decision(d,f,m,book,op,T)["action"]=="WAIT"
    m["market_mid"] = .37
    assert execution_decision(d,f,m,book,op,T)["action"]=="BUY_CANDIDATE"
    assert not execution_decision(d,f,m,book,op,T)["order_placed"]
