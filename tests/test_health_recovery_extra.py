"""Regression scenarios for settlement/feed status, recovery and atomic grading."""
from test_e2e_synthetic import env

def test_health_stale_worker_and_recovery(env):
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    main.update_once()
    assert client.get('/health').json()['ok'] is True
    last_success=main.state['last_success']
    clock.now += max(60,3*main.POLL_SECONDS)+1
    for path in ('/health','/api/state'):
        response=client.get(path).json()
        assert response['status']=='DEGRADED'
        assert response['ok'] is False
        assert 'worker_stale' in response['errors']
    assert main.state['last_success']==last_success
    main.update_once()
    assert client.get('/health').json()['ok'] is True
    assert 'worker_stale' not in client.get('/api/state').json()['errors']


def test_missing_active_market_and_empty_candles_are_not_healthy(env):
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    main.update_once()
    old_market=provider.market
    provider.market=lambda now=None: None
    clock.now+=15
    result=main.update_once()
    assert result['status']=='DEGRADED'
    assert 'kalshi' in result['errors']
    assert result['opportunity']['side']=='WAIT'
    provider.market=old_market
    old_candles=provider.candles
    provider.candles=lambda: []
    clock.now+=15
    result=main.update_once()
    assert result['status']=='DEGRADED'
    assert 'coinbase_candles' in result['errors']
    assert result['opportunity']['side']=='WAIT'
    assert result['model']['available'] is False
    provider.candles=old_candles
    clock.now+=15
    main.update_once()
    assert client.get('/health').json()['ok'] is True
    assert client.get('/api/state').json()['errors']=={}


def test_settlement_failures_are_individually_tracked_and_retried(env):
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    first_ticker=provider.ticker
    main.update_once()
    second_ticker='KXBTC15M-E2E-SYNTH-SECOND'
    provider.ticker=second_ticker
    main.update_once()
    first_attempts=[]
    def sometimes_fails(ticker):
        first_attempts.append(ticker)
        if ticker==first_ticker:
            raise TimeoutError('simulated grading outage')
        return 'no'
    provider.settlement=sometimes_fails
    main.grade_once()
    s=client.get('/api/state').json()
    assert s['status']=='DEGRADED'
    assert s['settlement']['failed']==1
    assert first_ticker in s['errors']['settlement']
    assert main.ledger.conn.execute('SELECT count(*) FROM engine_snapshots WHERE result IS NULL').fetchone()[0] == 6
    assert main.ledger.conn.execute('SELECT count(*) FROM engine_snapshots WHERE result=?',('no',)).fetchone()[0] == 6
    assert second_ticker in first_attempts and first_ticker in first_attempts
    main.update_once()
    assert 'settlement' in client.get('/health').json()['errors']
    provider.settlement=lambda ticker:'yes'
    main.grade_once()
    s=client.get('/api/state').json()
    assert s['status']=='DEMO'
    assert s['settlement']['failed']==0
    assert s['settlement']['status']=='CHECKED'
    assert 'settlement' not in s['errors']
    assert len(main.ledger.unresolved())==0
    before=main.ledger.engine_scores()
    main.grade_once()
    assert main.ledger.engine_scores()==before
    assert client.get('/health').json()['settlement']['status']=='IDLE'


def test_settlement_queue_lookup_failure_is_reported_and_recovers(env, monkeypatch):
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    main.update_once()
    real_unresolved=main.ledger.unresolved
    def broken_unresolved(*args,**kwargs):
        raise OSError('database temporarily unavailable')
    monkeypatch.setattr(main.ledger,'unresolved',broken_unresolved)
    main.grade_once()
    s=client.get('/health').json()
    assert s['ok'] is False and s['status']=='DEGRADED'
    assert '__ledger__' in s['errors']['settlement']
    monkeypatch.setattr(main.ledger,'unresolved',real_unresolved)
    main.grade_once()
    s=client.get('/health').json()
    assert s['ok'] is True
    assert s['settlement']['status']=='PENDING'
    assert 'settlement' not in s['errors']


def test_invalid_official_result_is_not_graded(env):
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    main.update_once()
    provider.settlement=lambda ticker:'TIE_INVALID'
    main.grade_once()
    assert client.get('/health').json()['status']=='DEGRADED'
    assert 'settlement' in client.get('/api/state').json()['errors']
    assert len(main.ledger.unresolved())==1
    assert main.ledger.conn.execute('SELECT count(*) FROM engine_snapshots WHERE result IS NOT NULL').fetchone()[0] == 0
    provider.settlement=lambda ticker:'no'
    main.grade_once()
    assert client.get('/health').json()['ok'] is True
    assert len(main.ledger.unresolved())==0


def test_official_grading_rolls_back_if_paper_write_fails(env, monkeypatch):
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    main.update_once()
    auth={'Authorization':'Bearer synthetic-local-testing-token'}
    assert client.post('/api/paper',json={'side':'YES'},headers=auth).status_code==200
    import app.storage as storage
    real_paper_result=storage.paper_result
    def broken_paper_result(*args): raise RuntimeError('injected ledger write failure')
    monkeypatch.setattr(storage,'paper_result',broken_paper_result)
    provider.settlement=lambda ticker:'yes'
    main.grade_once()
    assert client.get('/health').json()['ok'] is False
    assert 'settlement' in client.get('/api/state').json()['errors']
    assert main.ledger.conn.execute('SELECT count(*) FROM engine_snapshots WHERE result IS NOT NULL').fetchone()[0] == 0
    assert main.ledger.conn.execute('SELECT count(*) FROM paper_trades WHERE result IS NOT NULL').fetchone()[0] == 0
    monkeypatch.setattr(storage,'paper_result',real_paper_result)
    main.grade_once()
    assert client.get('/health').json()['ok'] is True
    assert main.ledger.conn.execute('SELECT count(*) FROM engine_snapshots WHERE result IS NOT NULL').fetchone()[0] == 6
    assert main.ledger.conn.execute('SELECT count(*) FROM paper_trades WHERE result IS NOT NULL').fetchone()[0] == 1


def test_settlement_recovery_does_not_clear_independent_feed_failure(env):
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    main.update_once()
    provider.fail_price=True
    main.update_once()
    provider.settlement=lambda ticker: (_ for _ in ()).throw(TimeoutError('settlement inaccessible'))
    main.grade_once()
    assert {'settlement','coinbase_ticker'} <= set(client.get('/api/state').json()['errors'])
    provider.settlement=lambda ticker: None
    main.grade_once()
    health=client.get('/health').json()
    assert 'settlement' not in health['errors']
    assert 'coinbase_ticker' in health['errors']
    assert health['status']=='DEGRADED' and health['ok'] is False
    provider.fail_price=False
    main.update_once()
    assert client.get('/health').json()['ok'] is True


def test_worker_error_and_recovery_are_visible(env, monkeypatch):
    main,clock,provider,client,_=env
    class OneCycle:
        def __init__(self): self.called=0
        def is_set(self):
            self.called+=1
            return self.called>1
        def wait(self,seconds): pass
    real_update=main.update_once
    monkeypatch.setattr(main,'shutdown',OneCycle())
    def exploding_poll(): raise RuntimeError('injected worker processing failure')
    monkeypatch.setattr(main,'update_once',exploding_poll)
    main.worker()
    h=client.get('/health').json()
    assert h['status']=='ERROR'
    assert h['ok'] is False and 'worker' in h['errors']
    monkeypatch.setattr(main,'update_once',real_update)
    clock.now=provider.close-600
    main.update_once()
    assert client.get('/health').json()['ok'] is True
    assert 'worker' not in client.get('/api/state').json()['errors']


def test_initial_health_is_not_a_false_success(env):
    main,clock,provider,client,_=env
    h=client.get('/health').json()
    assert h['status']=='STARTING' and h['ok'] is False
    assert h['last_attempt'] is None
    main.update_once()
    h=client.get('/health').json()
    assert h['ok'] is True and h['status']=='DEMO'
