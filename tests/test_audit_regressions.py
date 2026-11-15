"""Second independent audit: side-specific prices, unhealthy operation, candle integrity and UI."""
import math
from test_e2e_synthetic import env
from app.ensemble import execution_screen


def test_no_side_uses_its_own_spread_not_yes_spread():
    model={'available':True,'side':'BELOW','prob_above':.05}
    wide_no={'seconds_left':600,'yes_ask':.16,'yes_bid':.14,'no_ask':.60,'no_bid':.40}
    result=execution_screen(model,wide_no)
    assert result['edge']>.08
    assert result['side']=='WAIT', 'NO 20-cent spread must not qualify because YES is tight'
    valid={**wide_no,'no_bid':.59}
    assert execution_screen(model,valid)['side']=='NO'
    crossed={**wide_no,'no_bid':.65}
    assert execution_screen(model,crossed)['side']=='WAIT'


def test_yes_spread_symmetric_and_crossed_quote_rejected():
    model={'available':True,'side':'ABOVE','prob_above':.95}
    market={'seconds_left':600,'yes_ask':.60,'yes_bid':.40,'no_ask':.42,'no_bid':.40}
    assert execution_screen(model,market)['side']=='WAIT'
    market['yes_bid']=.59
    assert execution_screen(model,market)['side']=='YES'
    market['yes_bid']=.65
    assert execution_screen(model,market)['side']=='WAIT'


def test_paper_entries_blocked_during_failed_feed_and_recover(env):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.update_once()
    p.fail_price=True
    clock.now+=15
    state=main.update_once()
    assert state['status']=='DEGRADED'
    assert client.get('/health').status_code==503
    assert client.get('/api/state').json()['manual_paper_available'] is False
    auth={'Authorization':'Bearer synthetic-local-testing-token'}
    resp=client.post('/api/paper',json={'side':'YES'},headers=auth)
    assert resp.status_code==409
    assert main.ledger.data()['count']['paper']==0
    p.fail_price=False
    clock.now+=15
    main.update_once()
    assert client.get('/health').status_code==200
    assert client.get('/api/state').json()['manual_paper_available'] is True
    assert client.post('/api/paper',json={'side':'YES'},headers=auth).status_code==200
    assert main.ledger.data()['count']['paper']==1


def test_stale_worker_does_not_show_copied_signals_or_take_paper_entry(env):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.update_once()
    main.state['opportunity']={'side':'YES','edge':.30,'entry_price':.20,'reason':'OLD'}
    main.state['scalp']={'side':'LONG','entry':90000,'stop':89000,'target':91000}
    clock.now+=max(60,3*main.POLL_SECONDS)+1
    response=client.get('/api/state').json()
    assert not response['ok'] and response['status']=='DEGRADED'
    assert response['opportunity']['side']=='WAIT'
    assert response['scalp']['side']=='WAIT'
    assert response['model']['available'] is False
    assert response['manual_paper_available'] is False
    assert client.post('/api/paper',json={'side':'YES'},headers={'Authorization':'Bearer synthetic-local-testing-token'}).status_code==409


def test_future_candles_fail_closed_and_recover(env):
    main,clock,p,client,_=env
    clock.now=p.close-600
    original=p.candles
    def future():
        return [{**c,'t':c['t']+3600} for c in original()]
    p.candles=future
    out=main.update_once()
    assert out['status']=='DEGRADED' and 'coinbase_candles' in out['errors']
    assert out['opportunity']['side']=='WAIT'
    assert not out['model']['available']
    assert main.ledger.data()['count']=={'calls':0,'paper':0}
    p.candles=original
    clock.now+=20
    assert main.update_once()['status']=='DEMO'


def test_gapped_candle_timeline_cannot_be_used_as_60_one_minute_returns(env):
    main,clock,p,client,_=env
    clock.now=p.close-600
    original=p.candles
    def gapped():
        rows=original()
        return [{**c,'t':c['t']-(600 if i<30 else 0)} for i,c in enumerate(rows)]
    p.candles=gapped
    res=main.update_once()
    assert res['status']=='DEGRADED'
    assert 'coinbase_candles' in res['errors']
    assert res['opportunity']['side']=='WAIT'
    p.candles=original
    clock.now+=20
    assert main.update_once()['status']=='DEMO'


def test_dashboard_disables_manual_buttons_when_unhealthy():
    from pathlib import Path
    html=(Path(__file__).resolve().parents[1]/'app/static/index.html').read_text()
    assert "$('paperYes').disabled=!s.ok||!s.manual_paper_available" in html
    assert "$('paperNo').disabled=!s.ok||!s.manual_paper_available" in html


def test_feed_failure_resets_first_call_hold_before_resuming(env):
    main,clock,p,client,_=env
    clock.now=p.close-840
    main.update_once()
    assert main.ledger.conn.execute('SELECT count(*) FROM watches').fetchone()[0]==1
    clock.now+=5
    p.fail_price=True
    main.update_once()
    assert main.ledger.conn.execute('SELECT count(*) FROM watches').fetchone()[0]==0
    p.fail_price=False
    clock.now+=7
    main.update_once()
    assert main.ledger.data()['count']['calls']==0
    clock.now+=11
    main.update_once()
    assert main.ledger.data()['count']['calls']==1


def test_settlement_batch_rotates_past_first_fifty_pending_contracts(env):
    main,clock,p,client,_=env
    main.AUTO_PAPER=False
    # Seventy separate unresolved markets. The first fifty never get an
    # official result, but the later twenty have already settled.
    for i in range(70):
        main.ledger.conn.execute(
            'INSERT INTO first_calls(ticker,side,probability,created,seconds_left) VALUES(?,?,?,?,?)',
            (f'KXBTC15M-SIM-{i:03d}','ABOVE',.85,float(i),600))
    main.ledger.conn.commit()
    queried=[]
    def settlement(ticker):
        queried.append(ticker)
        return 'yes' if int(ticker.rsplit('-',1)[1])>=50 else None
    p.settlement=settlement
    main.grade_once()
    assert main.ledger.data()['stats']['graded_calls']==0
    main.grade_once()
    assert main.ledger.data()['stats']['graded_calls']==20
    assert len(queried)==100
    assert len(set(queried))==70
    assert len(main.ledger.unresolved())==30
    # Earliest contracts still legitimately pending; no synthetic labels.
    assert all(main.ledger.conn.execute('SELECT result FROM first_calls WHERE ticker=?',
                     (f'KXBTC15M-SIM-{i:03d}',)).fetchone()[0] is None for i in range(50))


def test_unresolved_round_robin_wraps_without_duplicates(env):
    main,_,_,_,_=env
    for i in range(7):
        main.ledger.conn.execute(
            'INSERT INTO first_calls(ticker,side,probability,created,seconds_left) VALUES(?,?,?,?,?)',
            (f'KXBTC15M-ROUND-{i:02d}','ABOVE',.85,float(i),600))
    main.ledger.conn.commit()
    a=main.ledger.unresolved(4)
    b=main.ledger.unresolved(4,after_ticker=a[-1])
    assert len(a)==len(b)==4
    assert len(set(a+b))==7
    assert len(set(b))==4


def test_ledger_read_failure_is_visible_in_both_apis_and_recovers(env,monkeypatch):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.update_once()
    real_data=main.ledger.data
    monkeypatch.setattr(main.ledger,'data',lambda: (_ for _ in ()).throw(OSError('temporary read failure')))
    r=client.get('/api/state')
    assert r.status_code==503
    s=r.json()
    assert s['status']=='DEGRADED' and s['ledger_available'] is False
    assert s['manual_paper_available'] is False
    assert s['engine_scores']['status']=='UNAVAILABLE'
    assert 'ledger_read' in s['errors']
    h=client.get('/health')
    assert h.status_code==503 and 'ledger_read' in h.json()['errors']
    monkeypatch.setattr(main.ledger,'data',real_data)
    r=client.get('/api/state')
    assert r.status_code==200 and r.json()['ledger_available'] is True
    assert client.get('/health').status_code==200
    assert 'ledger_read' not in client.get('/health').json()['errors']


def test_ledger_connection_outage_health_is_not_false_green(env,monkeypatch):
    main,clock,p,client,_=env
    clock.now=p.close-600
    main.update_once()
    real_health=main.ledger.healthcheck
    monkeypatch.setattr(main.ledger,'healthcheck',lambda: (_ for _ in ()).throw(OSError('ledger disconnected')))
    response=client.get('/health')
    assert response.status_code==503 and not response.json()['ok']
    assert 'ledger_connection' in response.json()['errors']
    assert client.get('/api/state').json()['manual_paper_available'] is False
    monkeypatch.setattr(main.ledger,'healthcheck',real_health)
    assert client.get('/health').status_code==200


def test_auto_paper_is_paused_during_settlement_health_failure(env):
    main,clock,p,client,_=env
    clock.now=p.close-840
    main.AUTO_PAPER=False
    main.update_once()
    p.settlement=lambda ticker: (_ for _ in ()).throw(TimeoutError('settlement API down'))
    main.grade_once()
    assert client.get('/health').status_code==503
    main.AUTO_PAPER=True
    clock.now+=15
    out=main.update_once()
    assert out['opportunity']['side']=='WAIT'
    assert main.ledger.data()['count']['paper']==0
    p.settlement=lambda ticker: None
    main.grade_once()
    assert client.get('/health').status_code==200
    clock.now+=15
    out=main.update_once()
    assert out['status']=='DEMO'
    assert main.ledger.data()['count']['paper']==1
