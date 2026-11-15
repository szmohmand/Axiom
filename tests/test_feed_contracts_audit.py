"""Offline provider-boundary contract verification: no network or real orders."""
from datetime import datetime,timezone
import requests
import pytest
from app.feeds import LiveProvider,KALSHI,COINBASE

class FakeResponse:
    def __init__(self,data=None,status=200,url='https://example.test'):
        self.data=data;self.status_code=status;self.url=url
    def json(self): return self.data
    def raise_for_status(self):
        if self.status_code>=400:
            err=requests.HTTPError(f'{self.status_code} simulated')
            err.response=self
            raise err

class FakeSession:
    def __init__(self,routes):self.routes=routes;self.calls=[]
    def get(self,url,params=None,timeout=None):
        self.calls.append((url,params,timeout))
        obj=self.routes[url]
        return obj.pop(0) if isinstance(obj,list) else obj


def provider(routes):
    p=LiveProvider()
    p.session.close()
    p.session=FakeSession(routes)
    return p


def market(ticker,close,valid=True):
    return {'ticker':ticker,'floor_strike':95000 if valid else None,
            'close_time':datetime.fromtimestamp(close,timezone.utc).isoformat(),
            'yes_bid_dollars':'0.42','yes_ask_dollars':'0.44',
            'no_bid_dollars':'0.56','no_ask_dollars':'0.58',
            'status':'open'}


def test_real_provider_selects_nearest_open_active_contract_and_normalizes_quotes():
    now=1800000000
    v={'markets':[market('KXBTC15M-LATER',now+900),market('KXBTC15M-FIRST',now+450),market('KXBTC15M-PAST',now-15)]}
    p=provider({KALSHI+'/markets':FakeResponse(v)})
    m=p.market(now)
    assert m['ticker']=='KXBTC15M-FIRST' and m['seconds_left']==450
    assert m['target']==95000 and m['yes_ask']==.44 and m['no_bid']==.56
    assert p.session.calls[0][2]==9
    assert p.session.calls[0][1]['status']=='open'


def test_provider_coinbase_price_validation_and_candle_normalization():
    url=COINBASE+'/products/BTC-USD/ticker'
    candles_url=COINBASE+'/products/BTC-USD/candles'
    v=1800000000//60*60
    candles=[[v-i*60,95000+i,95030+i,95005+i,95020+i,4+i] for i in range(64,-1,-1)]
    p=provider({url:[FakeResponse({'price':'95123.25'}),FakeResponse({'price':'-10'}),FakeResponse({'price':'NaN'})],
                candles_url:FakeResponse(candles)})
    assert p.price()==95123.25
    for _ in range(2):
        with pytest.raises(ValueError):p.price()
    normalized=p.candles()
    assert len(normalized)==65
    assert normalized[0]['t']+64*60==normalized[-1]['t']
    assert all(b['t']-a['t']==60 for a,b in zip(normalized,normalized[1:]))
    assert p.session.calls[-1][1]['granularity']==60


def test_settlement_normal_and_historical_404_fallback():
    tick='KXBTC15M-26TEST123'
    primary=f'{KALSHI}/markets/{tick}'
    history=f'{KALSHI}/historical/markets/{tick}'
    p=provider({primary:FakeResponse(status=404),history:FakeResponse({'market':{'status':'settled','result':'yes'}})})
    assert p.settlement(tick)=='yes'
    assert [row[0] for row in p.session.calls]==[primary,history]
    for bad in ('OTHER-CONTRACT','KXBTC15M-..../evil'):
        with pytest.raises(ValueError):p.settlement(bad)


def test_settlement_open_results_remain_ungraded_and_http_errors_propagate():
    tick='KXBTC15M-26TEST456';uri=f'{KALSHI}/markets/{tick}'
    p=provider({uri:[FakeResponse({'market':{'status':'open','result':'yes'}}),FakeResponse(status=503)]})
    assert p.settlement(tick) is None
    with pytest.raises(requests.HTTPError):p.settlement(tick)


def test_provider_unavailable_market_returns_none_without_guessing_target():
    p=provider({KALSHI+'/markets':FakeResponse({'markets':[]})})
    assert p.market(1800000000) is None
