"""Kalshi price research stays solely in post-forecast contract valuation."""
from app.orderbook import normalize_orderbook
from app.depth_intelligence import analyze_opportunities


def book(yes_bid, no_bid, now=1800007200):
    return normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[[str(yes_bid),"100"]],
        "no_dollars":[[str(no_bid),"100"]]}},
        "KXBTC15M-TEST",now)


def test_low_price_is_informational_not_an_arbitrary_buy_ban():
    now=1800007200
    forecast={"available":True,"side":"ABOVE","prob_above":.9}
    market={"ticker":"KXBTC15M-TEST","seconds_left":600,"target":64000}
    opportunity=analyze_opportunities(forecast,market,book(.06,.92,now),now)
    yes=next(x for x in opportunity["candidates"] if x["side"]=="YES")
    info=yes["pricing_research"]
    assert info["contract_price_band"]=="UNDER_10_CENTS"
    assert info["cheap_contract_settlement_bias_warning"] is True
    assert info["bias_is_proven_for_btc_15m"] is False
    assert info["bias_is_proven_for_intracontract_resale"] is False
    assert info["longshot_is_automatically_rejected"] is False
    assert info["taker_size_adjusted_ask"]==.08
    assert info["passive_maker_buy_reference"]==.06
    assert info["potential_price_saving_before_fees"]==.02
    assert info["passive_order_fill_guaranteed"] is False
    assert info["maker_fee_savings_assumed"] is False
    assert yes["eligible"] is True
    assert forecast=={"available":True,"side":"ABOVE","prob_above":.9}


def test_no_swept_depth_does_not_invent_maker_savings_or_probabilities():
    now=1800007200
    forecast={"available":True,"side":"ABOVE","prob_above":.85}
    market={"ticker":"KXBTC15M-TEST","seconds_left":600}
    expensive=analyze_opportunities(forecast,market,book(.56,.42,now),now)
    yes=next(x for x in expensive["candidates"] if x["side"]=="YES")
    research=yes["pricing_research"]
    assert research["contract_price_band"]=="AT_LEAST_10_CENTS"
    assert research["cheap_contract_settlement_bias_warning"] is False
    assert research["passive_maker_buy_reference"]==.56
    assert research["taker_size_adjusted_ask"]==.58
    assert research["potential_price_saving_before_fees"]==.02
    assert forecast["prob_above"]==.85
