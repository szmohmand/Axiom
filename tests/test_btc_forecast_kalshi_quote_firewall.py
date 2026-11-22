"""Strict boundary: Kalshi determines the question and entry price, NOT forecast.

Never feed Kalshi YES/NO bids, asks, quote midpoints, walls, liquidity or
stale-price delays into a model that predicts BTC above/below its target.
BTC source candles, real exchange trades, the published strike and expiry
are the only inputs. Kalshi quotes remain available for price/entry decisions.
"""
import math

from app.market_structure import DepthFlowTracker, pressure_forecast, timeframes
from app.ensemble import engine_pack, execution_screen
from app.orderbook import normalize_orderbook


def candles(now,n=75):
    start=int(now//60)*60-n*60
    out=[]
    for i in range(n):
        price=64000+3*i+2*math.sin(i/7)
        out.append({"t":start+i*60,"open":price-1.5,
                    "close":price,"high":price+4,"low":price-4,
                    "volume":10+i*.1})
    return out


def test_extreme_kalshi_bid_ask_midpoint_changes_cannot_modify_any_forecast_engine():
    now=1800007200
    bars=candles(now)
    spot=bars[-1]["close"]
    ordinary={"ticker":"KXBTC15M-TEST","target":spot+15,
              "close_ts":now+600,"seconds_left":600,
              "market_mid":.51,"yes_bid":.50,"yes_ask":.52,
              "no_bid":.48,"no_ask":.50,"volume":123}
    reversed_prices={**ordinary,"market_mid":.99,"yes_bid":.98,"yes_ask":.99,
                     "no_bid":.01,"no_ask":.02,"volume":999999,
                     "kalshi_yes_price_probability":.999}
    context={"timeframes":{"available":True,"directional_components":{
                  "30m_efficiency":.7,"1h_close_location":.4}},
             "microstructure":{"available":True,"directional_components":{
                  "btc_taker_cvd_2m":.35,"btc_large_aggressive_prints":.15}}}
    a=engine_pack(spot,ordinary,bars,context=context,now=now)
    b=engine_pack(spot,reversed_prices,bars,context=context,now=now)
    assert a==b
    assert a["available"] and a["all_signal_integration_active"]
    assert "kalshi_market" not in {e["name"] for e in a["engines"]}
    assert a["forecast_minus_quote_mid"] is None
    assert a["alpha_vs_market"] is None


def test_kalshi_orderbook_walls_and_repricing_dont_affect_btc_flow_forecast():
    now=1800007200
    ticker="KXBTC15M-TEST"
    book_a=normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[["0.30","12000"]],"no_dollars":[["0.65","1"]]}},ticker,now)
    book_b=normalize_orderbook({"orderbook_fp":{
        "yes_dollars":[["0.94","1"]],"no_dollars":[["0.03","12000"]]}},ticker,now)
    binance={"status":"STREAMING","cvd_2m":{"trades_seen":150,"taker_imbalance":.45},
             "cvd_5m":{"trades_seen":400,"taker_imbalance":.2},
             "large_trade_activity":{"net_taker_usdt":50000.,
                                      "large_trade_threshold_usdt":10000.,
                                      "large_print_count":4}}
    tracker=DepthFlowTracker()
    a=tracker.observe(book_a,{"ticker":ticker,"market_mid":.30},binance,64000,now)
    b=tracker.observe(book_b,{"ticker":ticker,"market_mid":.94},binance,64000,now+15)
    c=tracker.observe(None,None,binance,64000,now)
    assert a==b==c
    assert a["available"]
    assert {"btc_taker_cvd_2m","btc_taker_cvd_5m","btc_large_aggressive_prints"} <= set(a["directional_components"])


def test_even_injected_kalshi_prediction_features_are_rejected():
    base={"timeframes":{"directional_components":{"30m_efficiency":.8}},
          "microstructure":{"directional_components":{"btc_taker_cvd_2m":.5}}}
    poisoned={"timeframes":{"directional_components":{
                   **base["timeframes"]["directional_components"],
                   "kalshi_probability":-1,"kalshi_yes_mid":-1}},
              "microstructure":{"directional_components":{
                   **base["microstructure"]["directional_components"],
                   "kalshi_near_book_imbalance":-1,
                   "kalshi_liquidity_wall_bias":-1,
                   "btc_vs_kalshi_quote_absorption_proxy":-1,
                   "btc_price_first_repricing_proxy":-1}}}
    market={"ticker":"KXBTC15M-TEST","target":64000,"seconds_left":600}
    assert pressure_forecast(64000,market,.5,base)==pressure_forecast(
        64000,{**market,"market_mid":.01,"yes_ask":.99},.5,poisoned)


def test_kalshi_prices_do_affect_trade_valuation_but_not_btc_prediction():
    model={"available":True,"side":"ABOVE","prob_above":.80}
    contract={"ticker":"KXBTC15M-TEST","seconds_left":600}
    cheap={**contract,"yes_bid":.36,"yes_ask":.38,
           "no_bid":.62,"no_ask":.64}
    expensive={**contract,"yes_bid":.78,"yes_ask":.80,
               "no_bid":.20,"no_ask":.22}
    a=execution_screen(model,cheap)
    b=execution_screen(model,expensive)
    assert a["side"]=="YES" and a["entry_price"]==.38
    assert b["side"]=="WAIT" and b["entry_price"]==.80
    assert a["edge"]>b["edge"]
    assert model=={"available":True,"side":"ABOVE","prob_above":.80}
