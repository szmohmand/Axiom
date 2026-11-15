import math
from datetime import datetime, timezone
import pytest
from app.engine import market_snapshot, normalize_candles, volatility_forecast, opportunity, paper_result, scalp_signal

NOW=1763172000

def market(yes_bid='0.44',yes_ask='0.47',floor_strike=90000):
    return {'ticker':'KXBTC15M-TEST-01', 'close_time':datetime.fromtimestamp(NOW+500,timezone.utc).isoformat(),
        'floor_strike':floor_strike,'yes_bid_dollars':yes_bid,'yes_ask_dollars':yes_ask,'status':'open'}

def candles(n=55, trend=.0001):
    raw=[]
    for i in range(n):
        cl=90000+12*i+17*math.sin(i/2)
        op=cl-3
        raw.append([NOW-60*(n-i),min(op,cl)-10,max(op,cl)+10,op,cl,2])
    return normalize_candles(raw)

def test_market_parses_quote_and_target():
    m=market_snapshot(market(),NOW)
    assert m['yes_ask']==.47 and m['no_bid']==.53
    assert m['target']==90000 and m['seconds_left']==500

def test_missing_target_not_invented():
    m=market_snapshot(market(floor_strike=None),NOW)
    assert m['target'] is None
    f=volatility_forecast(90100,m['target'],500,candles())
    assert not f['available']

def test_missing_quote_does_not_create_opportunity():
    m=market_snapshot(market(yes_bid=None,yes_ask=None),NOW)
    f=volatility_forecast(90400,90000,500,candles())
    assert f['available']
    assert opportunity(f,m)['side']=='WAIT'

def test_probabilities_coherent():
    f=volatility_forecast(90450,90000,400,candles())
    assert f['available'] and 0 < f['prob_above'] < 1
    assert abs(f['prob_above']+f['prob_below']-1)<1e-8
    assert f['side']=='ABOVE'

def test_opportunity_quote_math():
    m=market_snapshot(market(yes_bid='.35',yes_ask='.40'),NOW)
    f={'available':True,'prob_above':.65,'prob_below':.35}
    x=opportunity(f,m)
    assert x['side']=='YES' and x['edge']==.25

def test_paper_pnl_math():
    assert paper_result('YES',.86,'yes')==.14
    assert paper_result('YES',.86,'no')==-.86
    assert paper_result('NO',.25,'no')==.75
    with pytest.raises(ValueError):paper_result('YES',.5,'open')

def test_scalp_is_separate_from_kalshi():
    s=scalp_signal(candles(),90450)
    assert s['side'] in ('LONG','SHORT','WAIT')
    assert 'kalshi' not in s['reason'].lower() or s['side']=='WAIT'
