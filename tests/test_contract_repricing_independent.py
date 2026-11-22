"""Online supervised quote change predictor is a POST-forecast output only."""
from app.contract_repricing import ContractRepricingModel
from app.orderbook import normalize_orderbook


def makebook(yes, no, ts):
    return normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[[str(yes),"100"]],
        "no_dollars":[[str(no),"100"]]}},
        "KXBTC15M-QUOTE-LEARNING",ts)


def forecast():
    return {"available":True,"prob_above":.82,"side":"ABOVE"}


def market():
    return {"ticker":"KXBTC15M-QUOTE-LEARNING",
            "target":64000,"seconds_left":600}


def signals():
    return {"available":True,"price_reference":"COINBASE_PROXY_NOT_SETTLEMENT",
            "momentum_bps_per_min":3.2}


def test_learning_uses_only_later_observed_quotes_and_not_future_data():
    m=ContractRepricingModel()
    f=forecast()
    first=m.observe(market(),makebook(.37,.57,1000),f,signals(),1000)
    assert first["available"] is False
    assert first["training_transitions"]==0
    assert first["predicted_yes_mid_change_30s"] is None

    # Book at t=1010 arrives AFTER the observation at t=1000.
    second=m.observe(market(),makebook(.39,.55,1010),f,signals(),1010)
    assert second["available"] is True
    assert second["training_transitions"]==1
    assert second["predicted_yes_mid_change_30s"] is not None
    assert second["target"]=="next_30s_yes_quote_midpoint_change_not_btc_outcome"
    assert second["independent_btc_forecast_changed"] is False
    assert f=={"available":True,"prob_above":.82,"side":"ABOVE"}
    assert second["future_exit_bid_verified"] is False


def test_same_receipt_twice_does_not_train_or_change_model():
    m=ContractRepricingModel()
    m.observe(market(),makebook(.37,.57,1000),forecast(),signals(),1000)
    a=m.observe(market(),makebook(.39,.55,1010),forecast(),signals(),1010)
    b=m.observe(market(),makebook(.40,.54,1010),forecast(),signals(),1010)
    assert a==b
    assert len(m.samples)==1


def test_learning_rollover_does_not_link_two_different_contracts():
    m=ContractRepricingModel()
    m.observe(market(),makebook(.37,.57,1000),forecast(),signals(),1000)
    other={**market(),"ticker":"KXBTC15M-OTHER"}
    b=normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[["0.90","100"]],"no_dollars":[["0.08","100"]]}},
        "KXBTC15M-OTHER",1010)
    r=m.observe(other,b,forecast(),signals(),1010)
    assert r["training_transitions"]==0
    assert r["available"] is False


def test_quote_model_is_separate_from_btc_outcome_ensemble():
    from app.ensemble import engine_pack
    import math
    now=1800007200
    bars=[]
    for i in range(75):
        p=64000+i*3+math.sin(i)
        bars.append({"t":now-4500+60*i,"open":p-1,"close":p,
                     "high":p+2,"low":p-2,"volume":10})
    spot=bars[-1]["close"]
    original={"ticker":"KXBTC15M-QUOTE-LEARNING","target":spot+10,
              "seconds_left":600,"close_ts":now+600,"market_mid":.35,
              "yes_bid":.34,"yes_ask":.36}
    changed={**original,"market_mid":.95,"yes_bid":.94,"yes_ask":.96}
    a=engine_pack(spot,original,bars,context={},now=now)
    b=engine_pack(spot,changed,bars,context={},now=now)
    assert a==b
    assert "axiom_contract_repricing" not in a["active_predictive_models"]
