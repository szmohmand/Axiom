"""Full aggregated Kalshi REST depth, forecast separation and manual execution."""
import math

import pytest

from app.orderbook import normalize_orderbook, sweep, current_book, unavailable
from app.depth_intelligence import analyze_opportunities, execution_guidance
from app.ensemble import engine_pack
from test_e2e_synthetic import env


TICKER = "KXBTC15M-DEPTH-TEST"


def makebook(now=12345., yes=None, no=None):
    payload={"orderbook_fp":{
        "yes_dollars": yes if yes is not None else [["0.56","20.00"],["0.60","8.00"]],
        "no_dollars": no if no is not None else [["0.23","100.00"],["0.28","7.00"],["0.32","3.00"]],
    }}
    return normalize_orderbook(payload,TICKER,now)


def forecast(p=.90):
    return {"available":True,"prob_above":p,"prob_below":1-p,
            "side":"ABOVE" if p>.5 else "BELOW"}


def market():
    return {"ticker":TICKER,"target":90000,"seconds_left":600,
            "market_mid":.5,"yes_ask":.68,"yes_bid":.60,
            "no_ask":.4,"no_bid":.32}


def test_full_levels_and_reciprocal_asks():
    b=makebook()
    assert b["available"] and b["is_full_aggregated_depth"]
    assert b["individual_orders_visible"] is False
    assert b["levels"]=={"YES":2,"NO":3}
    assert b["bids"]["NO"][0]=={"price":.32,"size":3.}
    assert b["asks"]["YES"]==[{"price":.68,"size":3.},
                             {"price":.72,"size":7.},
                             {"price":.77,"size":100.}]
    assert b["best"]["YES"]["bid"]==.60
    assert b["best"]["YES"]["ask"]==.68
    assert b["best"]["YES"]["spread"]==pytest.approx(.08)
    assert b["resting_bid_contracts"]["YES"]==28
    assert b["resting_bid_contracts"]["NO"]==110


def test_sweeps_walk_every_available_level_and_never_fake_a_fill():
    b=makebook()
    one=sweep(b,"YES","BUY",1)
    assert one["complete"] and one["average_price"]==.68
    ten=sweep(b,"YES","BUY",10)
    assert ten["complete"] and ten["levels_consumed"]==2
    assert ten["average_price"]==pytest.approx(.708)
    assert ten["total_notional"]==pytest.approx(7.08)
    assert ten["slippage_from_best"]==pytest.approx(.028)
    too_large=sweep(b,"YES","BUY",200)
    assert not too_large["complete"]
    assert too_large["available_contracts"]==110
    assert too_large["levels_consumed"]==3
    exit_=sweep(b,"YES","SELL",10)
    assert exit_["complete"] and exit_["average_price"]==pytest.approx(.592)


@pytest.mark.parametrize("payload",[
    {}, {"orderbook_fp":{}},
    {"orderbook_fp":{"yes_dollars":[["0.50","0"]],"no_dollars":[]}},
    {"orderbook_fp":{"yes_dollars":[["0.50","-1"]],"no_dollars":[]}},
    {"orderbook_fp":{"yes_dollars":[["0.50","nan"]],"no_dollars":[]}},
    {"orderbook_fp":{"yes_dollars":[["0.50","3"],["0.50","4"]],"no_dollars":[]}},
    {"orderbook_fp":{"yes_dollars":[["0.70","3"]],"no_dollars":[["0.40","4"]]}},
    {"orderbook_fp":{"yes_dollars":"not-an-array","no_dollars":[]}},
])
def test_malformed_or_crossed_books_do_not_produce_signal(payload):
    with pytest.raises(ValueError):
        normalize_orderbook(payload,TICKER,12345.)


def test_empty_book_is_explicitly_unavailable():
    b=normalize_orderbook({"orderbook_fp":{"yes_dollars":[],"no_dollars":[]}},TICKER,12345.)
    assert not b["available"]
    assert b["status"]=="UNAVAILABLE"
    assert not current_book(b,TICKER,12345.)


def test_book_age_wrong_ticker_and_future_timestamp_rejected():
    b=makebook()
    assert current_book(b,TICKER,12346.)
    assert not current_book(b,TICKER,12400.)
    assert not current_book(b,TICKER,12300.)
    assert not current_book(b,"KXBTC15M-OTHER",12346.)


def test_no_depth_prevents_opportunity_and_execution_without_affecting_forecast():
    f=forecast()
    m=market()
    absent=unavailable(TICKER,"timeout")
    op=analyze_opportunities(f,m,absent,12345.)
    x=execution_guidance(op,f,m,absent,12345.)
    assert op["side"]=="WAIT" and not op["candidates"]
    assert x["action"]=="WAIT" and not x["order_placed"]
    assert f==forecast()


def test_same_forecast_with_different_depth_changes_opportunity_not_probability():
    f=forecast(.90)
    m=market()
    tight=makebook(12345., yes=[["0.46","100"],["0.50","100"]],
                   no=[["0.42","100"],["0.46","100"]])
    expensive=makebook(12345.,yes=[["0.70","100"],["0.74","100"]],
                       no=[["0.10","100"],["0.13","100"]])
    a=analyze_opportunities(f,m,tight,12345.,size_contracts=10)
    b=analyze_opportunities(f,m,expensive,12345.,size_contracts=10)
    assert a["side"]=="YES" and a["selected"] is not None
    assert b["side"]=="WAIT"
    assert execution_guidance(a,f,m,tight,12345.)["action"]=="ENTER"
    assert execution_guidance(b,f,m,expensive,12345.)["action"]=="WAIT"
    assert f["prob_above"]==.90


def test_size_matters_and_thin_book_rejected():
    f=forecast(.90)
    b=makebook(12345.,yes=[["0.55","5"]],no=[["0.35","3"]])
    m=market()
    enough=analyze_opportunities(f,m,b,12345.,size_contracts=1)
    too_large=analyze_opportunities(f,m,b,12345.,size_contracts=20)
    assert enough["candidates"]
    assert too_large["status"]=="WAIT"
    assert all(not c["eligible"] for c in too_large["candidates"])


def test_position_exit_hold_and_no_depth_failure():
    b=makebook(12345.,yes=[["0.58","30"],["0.60","30"]],
               no=[["0.32","30"],["0.34","30"]])
    m=market()
    aligned=execution_guidance(None,forecast(.90),m,b,12345.,
                               position={"side":"YES","contracts":10})
    reversed_=execution_guidance(None,forecast(.10),m,b,12345.,
                                 position={"side":"YES","contracts":10})
    assert aligned["action"]=="HOLD" and not aligned["order_placed"]
    assert reversed_["action"]=="EXIT" and not reversed_["order_placed"]
    assert aligned["estimated_exit_price"]==pytest.approx(.60)
    denied=execution_guidance(None,forecast(.10),m,b,12345.,
                               position={"side":"NO","contracts":1000})
    assert denied["action"]=="WAIT"


def test_shown_market_quote_cannot_vote_in_forecast_and_book_can_change():
    prices=[]
    for i in range(65):
        x=90000 + i*3 + 12*math.sin(i/4)
        prices.append({"t":1700000000+i*60,"close":x,"open":x-2,
                       "high":x+8,"low":x-8,"volume":2.})
    m=market()
    f1=engine_pack(prices[-1]["close"],m,prices)
    f2=engine_pack(prices[-1]["close"],{**m,"market_mid":.01,
                                      "yes_bid":.01,"yes_ask":.02},prices)
    assert f1["prob_above"]==f2["prob_above"] and f1["side"]==f2["side"]


def test_full_depth_endpoint_is_GET_only_without_authentication():
    from app.feeds import LiveProvider, KALSHI
    p=LiveProvider()
    requests=[]
    def fake_get(url, params=None):
        requests.append((url,params))
        return {"orderbook_fp":{"yes_dollars":[["0.54","12"]],
                                "no_dollars":[["0.40","30"]]}}
    p.get=fake_get
    book=p.orderbook(market(),now=12345.)
    assert requests==[(f"{KALSHI}/markets/{TICKER}/orderbook",{"depth":0})]
    assert book["available"] and book["levels"]=={"YES":1,"NO":1}
    p.session.close()


def test_staged_pipeline_and_failure_keep_existing_forecast_and_ledger(env):
    main,clock,provider,client,_=env
    from app.engine import market_snapshot
    from datetime import datetime,timezone
    m=provider.market(clock.now)
    now=provider.close-600
    clock.now=now
    def book_reader(m,now):
        return normalize_orderbook({'orderbook_fp':{
            'yes_dollars':[['0.40','50'],['0.44','40']],
            'no_dollars':[['0.50','80'],['0.54','60']]}},m['ticker'],now)
    provider.orderbook=book_reader
    stage=main.update_once()
    assert stage["orderbook"]["available"]
    assert stage["depth_opportunity"]["read_only"]
    assert stage["depth_opportunity"]["status"]=='CANDIDATE'
    assert stage["execution_intelligence"]["action"]=='ENTER'
    assert stage["execution_intelligence"]["read_only"]
    assert stage["execution_intelligence"]["order_placed"] is False
    assert stage["model"]["available"]
    original=stage["model"]
    baseline=main.ledger.data()["count"]
    def fail(m,now):
        raise TimeoutError("orderbook unavailable")
    paper=main.ledger.trade(stage['market'],'NO',clock.now,source='MANUAL_PAPER')
    position=client.get('/api/state').json()['paper_position_execution']
    assert position['action']=='EXIT' and position['side']=='NO' and not position['order_placed']
    provider.orderbook=fail
    clock.now+=15
    degraded=main.update_once()
    assert degraded["orderbook"]["status"]=="UNAVAILABLE"
    assert degraded["depth_opportunity"]["side"]=="WAIT"
    assert degraded["execution_intelligence"]["action"]=="WAIT"
    assert degraded["model"]["prob_above"]==engine_pack(degraded["spot"],degraded["market"],degraded["candles"])["prob_above"]
    assert degraded["model"]["available"]
    assert degraded["status"]=="DEMO"
    assert main.ledger.data()["count"]["paper"]==baseline["paper"]+1
    provider.orderbook=book_reader
    clock.now+=15
    assert main.update_once()["orderbook"]["available"]


def test_mobile_ui_exposes_separate_depth_lanes():
    from pathlib import Path
    html=(Path(__file__).resolve().parents[1]/"app"/"static"/"index.html").read_text()
    for id_ in ["bookStatus","bookYesLevels","bookNoLevels","bookImbalance",
                "bookBidRows","bookAskRows","depthSide","depthCost",
                "depthEdge","execAction","execReason"]:
        assert f'id="{id_}"' in html
        assert f"set('{id_}'" in html or id_ in ("bookBidRows","bookAskRows")
    assert "No real orders" in html
