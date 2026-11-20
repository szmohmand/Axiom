"""AXIOM end-to-end external validation harness, *not* production code.
Exercising exactly the frozen app/ source from szmohmand/Axiom/main.
Synthetic markets are labeled and the provider does not access external networks.
"""
import os, sys, time, math, json, csv, io
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
import importlib
import pytest
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.engine import market_snapshot

class Clock:
    now=1_800_000_060.0

class Provider:
    def __init__(self,clock):
        self.clock=clock;self.close=1_800_000_900.0; self.ticker='KXBTC15M-E2E-SYNTH-1'
        self.fail_price=False;self.fail_candles=False;self.fail_market=False
        self.result='yes';self.settlement_calls=0
        self.target=90000.0;self.quote_ask=.46
    def market(self,now=None):
        if self.fail_market: raise RuntimeError('injected Kalshi outage')
        now=self.clock.now if now is None else now
        return market_snapshot({'ticker':self.ticker,'close_time':datetime.fromtimestamp(self.close,timezone.utc).isoformat(),
             'status':'open','floor_strike':self.target, 'yes_bid_dollars':str(self.quote_ask-.03),
             'yes_ask_dollars':str(self.quote_ask),'no_bid_dollars':str(1-self.quote_ask),
             'no_ask_dollars':str(1-self.quote_ask+.03),'title':'SYNTHETIC 15-min BTC outcome'}, now)
    def price(self):
        if self.fail_price: raise RuntimeError('injected Coinbase outage')
        return 90325.0
    def candles(self):
        if self.fail_candles: raise RuntimeError('injected Coinbase candle outage')
        now=int(self.clock.now//60)*60
        from app.engine import normalize_candles
        return normalize_candles([[now-(64-i)*60, (v:=90220+i*1.4+22*math.sin(i*.5))-28, v+28,
                 v-4,v,5] for i in range(65)])
    def settlement(self,ticker):
        self.settlement_calls+=1
        if ticker!=self.ticker: return None
        if self.clock.now < self.close+5:return None
        return self.result

@pytest.fixture
def env(monkeypatch,tmp_path):
    monkeypatch.setenv('DEMO_MODE','1')
    monkeypatch.setenv('AUTO_PAPER','0')
    monkeypatch.setenv('BOT_ADMIN_TOKEN','synthetic-local-testing-token')
    monkeypatch.setenv('DATA_PATH',str(tmp_path/'runtime.sqlite3'))
    sys.modules.pop('app.main',None)
    main=importlib.import_module('app.main')
    clk=Clock();p=Provider(clk)
    main.provider=p
    main.DEMO=True
    main.AUTO_PAPER=False
    monkeypatch.setattr(main,'time',SimpleNamespace(time=lambda:clk.now))
    client=TestClient(main.app)
    yield main,clk,p,client,tmp_path
    main.ledger.conn.close()
    client.close()


def test_full_contract_lifecycle_four_checkpoints_and_official_settlement(env):
    main,clock,provider,client,tmp=env
    main.AUTO_PAPER=True
    checkpoints=[(840,'14m'),(600,'10m'),(300,'5m'),(60,'1m')]
    for seconds, label in checkpoints:
        clock.now=provider.close-seconds
        updated=main.update_once()
        assert updated['market']['ticker']==provider.ticker
        assert updated['model']['available'] is True
        assert updated['btc_signals']['available'] is True
        assert updated['trade_decision']['order_placed'] is False
        assert len(updated['engines'])==5
        assert updated['model']['prob_above'] is not None
        assert updated['scalp']['side'] in ('LONG','SHORT','WAIT')
        assert updated['opportunity']['side'] in ('YES','NO','WAIT')
        assert updated['status']=='DEMO'
        rows=main.ledger.conn.execute('SELECT engine,checkpoint FROM engine_snapshots WHERE ticker=?',(provider.ticker,)).fetchall()
        assert sum(row['checkpoint']==label for row in rows)==6, f'{label} checkpoint has wrong engine count'
        if seconds==840:
            clock.now+=15
            main.update_once()
            assert main.ledger.data()['count']['calls']==1
            assert main.ledger.data()['count']['paper']==1
            assert main.ledger.data()['trades'][0]['source']=='AUTO_RESEARCH'
    pre=client.get('/api/state').json()
    assert pre['count']=={'calls':1,'paper':1}
    assert pre['engine_scores']['samples']==24
    assert pre['stats']['settled_paper_trades']==0
    assert len(pre['engine_scores']['scores'])==0
    assert len(pre['engines'])==5
    assert pre['manual_paper_available'] is True
    assert pre['disclaimer'].find('NOT the BRTI')>=0
    assert client.get('/health').json()['ok']
    assert 'AXIOM' in client.get('/').text
    assert '<script' in client.get('/').text
    assert client.post('/api/paper',json={'side':'YES'}).status_code==401
    assert client.post('/api/paper',json={'side':'YES'},headers={'Authorization':'Bearer synthetic-local-testing-token'}).status_code==409
    auth={'Authorization':'Bearer synthetic-local-testing-token'}
    for kind in ('engine_snapshots','observations','paper_trades','first_calls'):
        response=client.get('/api/export/'+kind,headers=auth)
        assert response.status_code==200
        assert response.headers['content-type'].startswith('text/csv')
        rows=list(csv.DictReader(io.StringIO(response.text)))
        assert rows,f'Expected records in {kind}'
        if kind=='engine_snapshots': assert len(rows)==24
        if kind=='paper_trades':assert len(rows)==1
    assert client.get('/api/export/engine_snapshots').status_code==401
    assert client.get('/api/export/invalid',headers=auth).status_code==404
    # This *official provider's* result is the ONLY label. The synthetic spot is held constant.
    clock.now=provider.close+6
    main.grade_once()
    final=client.get('/api/state').json()
    assert provider.settlement_calls>=1
    assert final['stats']['graded_calls']==1
    assert final['stats']['correct_calls']==1
    assert final['stats']['settled_paper_trades']==1
    assert final['stats']['gross_paper_pnl']==round(1-provider.quote_ask,4)
    assert len(final['engine_scores']['scores'])==24
    assert all(row['n']==1 for row in final['engine_scores']['scores'])
    assert all(row['validated_alpha'] is False for row in final['engine_scores']['scores'])
    assert len(main.ledger.unresolved())==0
    # idempotence: grading twice cannot change P&L, n, or counts
    main.grade_once()
    assert client.get('/api/state').json()['stats']==final['stats']
    # sqlite persistence after reopen, including engine predictions
    from app.storage import Ledger
    reopened=Ledger(str(tmp/'runtime.sqlite3'))
    assert reopened.data()['count']=={'calls':1,'paper':1}
    assert len(reopened.engine_scores()['scores'])==24
    reopened.conn.close()


def test_manual_trade_auth_duplicate_stale_and_near_expiry_guards(env):
    main,clock,provider,client,_=env
    clock.now=provider.close-500
    main.update_once()
    assert client.post('/api/paper',json={'side':'NO'},headers={'Authorization':'Bearer wrong'}).status_code==401
    assert client.post('/api/paper',json={'side':'DOG'},headers={'Authorization':'Bearer synthetic-local-testing-token'}).status_code==409
    assert client.post('/api/paper',json={'side':'NO'},headers={'Authorization':'Bearer synthetic-local-testing-token'}).status_code==200
    assert client.post('/api/paper',json={'side':'YES'},headers={'Authorization':'Bearer synthetic-local-testing-token'}).status_code==409
    # new market, no stale snapshot entry
    provider.ticker='KXBTC15M-E2E-SYNTH-2'
    clock.now=provider.close-400
    main.update_once()
    clock.now+=99
    assert client.post('/api/paper',json={'side':'YES'},headers={'Authorization':'Bearer synthetic-local-testing-token'}).status_code==409
    clock.now=provider.close-40
    main.update_once()
    assert client.post('/api/paper',json={'side':'YES'},headers={'Authorization':'Bearer synthetic-local-testing-token'}).status_code==409


def test_feed_failures_are_exposed_and_do_not_generate_new_ledger_entries(env):
    main,clock,provider,client,_=env
    main.DEMO=False
    clock.now=provider.close-600
    main.update_once()
    baseline=main.ledger.data()['count']
    success=main.state['last_success']
    provider.fail_price=True
    clock.now+=20
    next_state=main.update_once()
    assert next_state['status']=='DEGRADED'
    assert 'coinbase_ticker' in next_state['errors']
    assert not client.get('/health').json()['ok']
    assert next_state['last_success']==success
    assert main.ledger.data()['count']==baseline
    assert next_state['model']['available'] is False
    provider.fail_price=False
    provider.fail_market=True
    clock.now+=20
    next_state=main.update_once()
    assert next_state['status']=='DEGRADED'
    assert 'kalshi' in next_state['errors']
    assert next_state['market'] is None
    assert main.ledger.data()['count']==baseline
    provider.fail_market=False
    provider.fail_candles=True
    clock.now+=20
    next_state=main.update_once()
    assert 'coinbase_candles' in next_state['errors']
    assert next_state['model']['available'] is False
    assert main.ledger.data()['count']==baseline


def test_reconciliation_market_mid_does_not_change_independent_forecast(env):
    main,clock,provider,client,_=env
    from app.ensemble import engine_pack
    market=provider.market(clock.now)
    candles=__import__('app.engine',fromlist=['normalize_candles']).normalize_candles(provider.candles())
    original=engine_pack(provider.price(),market,candles)
    changed=engine_pack(provider.price(),{**market,'market_mid':.05,'yes_bid':.02,'yes_ask':.07,'no_bid':.93,'no_ask':.98},candles)
    assert original['prob_above']==changed['prob_above']
    assert original['engines'][0]['prob_above']!=changed['engines'][0]['prob_above']


def test_settlement_failure_is_exposed_in_health(env):
    # Characterize actual current behavior rather than claim this is a passing guard.
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    main.update_once()
    assert main.ledger.engine_scores()['samples']==6
    def broken_settlement(ticker): raise RuntimeError('injected result endpoint failure')
    provider.settlement=broken_settlement
    clock.now=provider.close+10
    main.grade_once()
    assert main.ledger.unresolved(), 'Failed settlement stays unresolved'
    assert 'settlement' in client.get('/api/state').json()['errors'], 'Settlement errors must be visible'


def test_demo_feed_failure_degrades_health(env):
    main,clock,provider,client,_=env
    provider.fail_price=True
    main.update_once()
    assert client.get('/health').json()['ok'] is False
    assert 'coinbase_ticker' in client.get('/api/state').json()['errors']



def test_no_side_manual_paper_result_and_regrade_idempotence(env):
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    main.update_once()
    auth={'Authorization':'Bearer synthetic-local-testing-token'}
    paper=client.post('/api/paper',json={'side':'NO'},headers=auth)
    assert paper.status_code==200
    assert paper.json()['side']=='NO'
    provider.result='no'
    clock.now=provider.close+6
    main.grade_once()
    response=client.get('/api/state').json()
    assert response['trades'][0]['status']=='SETTLED'
    assert response['trades'][0]['result']=='no'
    assert response['stats']['gross_paper_pnl']==round(1-(1-provider.quote_ask+.03),4)
    assert len(response['engine_scores']['scores'])==6
    main.grade_once()
    assert client.get('/api/state').json()['stats']==response['stats']