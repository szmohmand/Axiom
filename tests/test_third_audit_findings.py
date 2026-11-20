"""New audit findings; start RED against preserved verified baseline."""
from test_e2e_synthetic import env


def test_non_one_minute_candles_do_not_generate_forecast_or_records(env):
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    prior=provider.candles
    def half_minute():
        rows=prior()
        start=clock.now-(len(rows)-1)*30
        return [{**c,'t':start+i*30} for i,c in enumerate(rows)]
    provider.candles=half_minute
    output=main.update_once()
    assert output['status']=='DEGRADED', '30-second bars were mistakenly accepted as 1-minute candles'
    assert 'coinbase_candles' in output['errors']
    assert output['model']['available'] is False
    assert output['opportunity']['side']=='WAIT'
    assert main.ledger.data()['count']=={'calls':0,'paper':0}
    provider.candles=prior
    clock.now+=15
    assert main.update_once()['status']=='DEMO'


def test_forecast_cycle_failure_does_not_write_orphan_observation(env,monkeypatch):
    main,clock,p,client,_=env
    clock.now=p.close-600
    original=main.ledger.engine_snapshots
    def fail_snapshots(*args,**kwargs):
        raise OSError('snapshots database unavailable')
    monkeypatch.setattr(main.ledger,'engine_snapshots',fail_snapshots)
    import pytest
    with pytest.raises(OSError):
        main.update_once()
    obs_count=main.ledger.conn.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
    assert obs_count==0,'Partial forecast cycle persisted despite later snapshot failure'
    monkeypatch.setattr(main.ledger,'engine_snapshots',original)


def test_first_call_write_failure_rolls_back_entire_poll(env,monkeypatch):
    import pytest
    main,clock,provider,client,_=env
    clock.now=provider.close-840
    original=main.ledger.first_call
    def break_call(*args,**kwargs):
        raise OSError('injected first-call persistence interruption')
    monkeypatch.setattr(main.ledger,'first_call',break_call)
    with pytest.raises(OSError): main.update_once()
    for table in ('observations','engine_snapshots','watches','first_calls','paper_trades'):
        assert main.ledger.conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==0,table
    monkeypatch.setattr(main.ledger,'first_call',original)
    main.update_once()
    assert main.ledger.conn.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==1
    assert main.ledger.conn.execute('SELECT COUNT(*) FROM watches').fetchone()[0]==1


def test_auto_paper_database_error_rolls_back_all_poll_writes(env,monkeypatch):
    import pytest
    main,clock,provider,client,_=env
    clock.now=provider.close-840
    main.AUTO_PAPER=True
    original=main.ledger.trade
    def break_paper(*args,**kwargs):
        raise OSError('injected auto-paper database failure')
    monkeypatch.setattr(main.ledger,'trade',break_paper)
    with pytest.raises(OSError): main.update_once()
    for table in ('observations','engine_snapshots','watches','first_calls','paper_trades'):
        assert main.ledger.conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==0,table
    monkeypatch.setattr(main.ledger,'trade',original)
    main.update_once()
    assert main.ledger.conn.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==1
    assert main.ledger.conn.execute('SELECT COUNT(*) FROM engine_snapshots').fetchone()[0]==6
    assert main.ledger.conn.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0]==1


def test_competing_manual_entries_record_at_most_one_position(env):
    from concurrent.futures import ThreadPoolExecutor
    main,clock,provider,client,_=env
    clock.now=provider.close-600
    main.update_once()
    market=provider.market(clock.now)
    def try_entry(i):
        try:
            return main.ledger.trade(market, 'YES' if i%2==0 else 'NO',clock.now)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=12) as pool:
        results=list(pool.map(try_entry,range(32)))
    assert sum(x is not None for x in results)==1
    assert main.ledger.conn.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0]==1
    assert main.ledger.conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_slow_settlement_grading_cannot_stop_market_polling(env, monkeypatch):
    """An isolated grade backend can stall, but the market loop must keep polling."""
    import threading
    main,clock,p,client,_=env
    class Bounded:
        def __init__(self): self.polls=0
        def is_set(self): return self.polls>=10
        def wait(self,delay): pass
    ctl=Bounded(); entered=threading.Event(); release=threading.Event()
    def market_poll(): ctl.polls+=1
    def grade_block(*args,**kwargs):
        entered.set()
        release.wait(timeout=2)
    monkeypatch.setattr(main,'shutdown',ctl)
    monkeypatch.setattr(main,'update_once',market_poll)
    monkeypatch.setattr(main,'grade_once',grade_block)
    thread=threading.Thread(target=main.worker,daemon=True)
    thread.start()
    for _ in range(60):
        if ctl.polls>=10 or entered.is_set(): break
        threading.Event().wait(.005)
    progressed=ctl.polls
    release.set();thread.join(timeout=2)
    assert progressed>=10, f'Only {progressed} market polls completed before slow settlement stalled the loop'


def test_background_grading_isolation_with_actual_server_lifespan(env,monkeypatch):
    """The actual FastAPI lifespan must poll during an in-flight slow grade."""
    import threading,time
    from fastapi.testclient import TestClient
    main,clock,provider,_,_=env
    events={'polls':0}
    started=threading.Event();finish=threading.Event()
    def fast_poll(): events['polls']+=1
    def blocked_grade(*args,**kwargs):
        started.set()
        finish.wait(timeout=1)
    monkeypatch.setattr(main,'update_once',fast_poll)
    monkeypatch.setattr(main,'grade_once',blocked_grade)
    monkeypatch.setattr(main,'POLL_SECONDS',.01)
    try:
        with TestClient(main.app):
            assert started.wait(.45), 'Separate grading scheduler never ran'
            count=events['polls']
            time.sleep(.09)
            assert events['polls']>=count+4, 'In-flight settlement request blocked market worker'
    finally:
        finish.set()


def test_market_calculation_invariants_across_foreseeable_price_volatility_and_expiry_cases():
    """Deterministic property-style check, no external providers or real orders."""
    import random, math
    from app.ensemble import engine_pack,execution_screen
    from app.engine import scalp_signal
    rng=random.Random(20261115)
    for scenario in range(400):
        reference=rng.uniform(50000,150000)
        level=reference*(1+rng.uniform(-.007,.007))
        price=reference
        candles=[]
        for i in range(65):
            old=price;price=max(100,price*(1+rng.gauss(0,.0005)))
            low=min(old,price)-rng.uniform(1,8)
            high=max(old,price)+rng.uniform(1,8)
            candles.append({'t':1800000000-64*60+i*60,'open':old,'close':price,
                            'low':low,'high':high,'volume':rng.uniform(.1,200)})
        mid=rng.uniform(.03,.97); bid=max(.01,mid-.015);ask=min(.99,mid+.015)
        market={'ticker':f'KXBTC15M-SCEN-{scenario}', 'target':level,
                'seconds_left':rng.choice([60,90,120,300,600,840,900]),
                'market_mid':mid,'yes_bid':bid,'yes_ask':ask,'no_bid':1-ask,'no_ask':1-bid}
        model=engine_pack(price,market,candles)
        assert len(model['engines'])==4
        assert model['available']
        assert model['side'] in ('ABOVE','BELOW','WAIT')
        assert all(0<e['prob_above']<1 for e in model['engines'] if e['available'])
        assert math.isclose(model['prob_above']+model['prob_below'],1,abs_tol=.000001)
        baseline=engine_pack(price,{**market,'market_mid':max(.01,1-mid)},candles)
        assert baseline['prob_above']==model['prob_above']
        scalp=scalp_signal(candles,price)
        assert scalp['side'] in ('LONG','SHORT','WAIT')
        decision=execution_screen(model,market)
        assert decision['side'] in ('YES','NO','WAIT')
        if decision['side']!='WAIT':
            assert model['side']==('ABOVE' if decision['side']=='YES' else 'BELOW')
            assert market['seconds_left']>=120
            assert decision['edge']>=.08
            selected=decision['side'].lower()
            assert 0<=market[f'{selected}_ask']-market[f'{selected}_bid']<=.04
