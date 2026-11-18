"""AXIOM authenticated BRTI 1Hz + 5Hz nonvoting read-only acceptance.

The fixture messages have Kalshi's documented actual schema, but values
are synthetic and are NEVER represented as observed historical index data.
No orders, API credentials, network, or external account requests.
"""
import json
import threading
import time
from unittest.mock import patch
import pytest

from app.live_brti import BRTIObserver, _average, _price, run_stream, WS_PATH, CHANNELS

T=1794957700.
MS=int(T*1000)


def frame(channel='cfbenchmarks_value',t=MS,value='64000.12',closing=False):
    msg={'index_id':'BRTI','received_at':t+11}
    if channel==CHANNELS[0]:
        msg.update(data=json.dumps({'type':'value','id':'BRTI','time':t,'value':value}),
            avg_60s_data={'value':value,'window_size':60,
                'window_start_ts_ms':t-60000,'window_end_ts_exclusive':t})
        if closing:
            msg['last_60s_windowed_average_15min']={
                'value':'64001.25','window_size':45,
                'window_start_ts_ms':t-45000,'window_end_ts_exclusive':t}
    else:
        msg.update(value_usd=value,source_ts_ms=t,
                   data=json.dumps({'type':'value','id':'BRTI','time':t,'value':value}))
    return {'type':channel,'msg':msg}


def test_real_channel_shapes_canonical_receipt_times_and_stale_fail_closed():
    o=BRTIObserver()
    assert o.ingest(frame(),received_at=T+.1)
    assert o.ingest(frame(CHANNELS[1],MS+200),received_at=T+.3)
    d=o.snapshot({'target':64000.,'close_ts':T+20},now=T+.4)
    assert d['fresh'] and d['current_value_usd']==64000.12
    assert d['counts']['accepted_1hz']==1 and d['counts']['accepted_5hz']==1
    assert d['observed_distance_to_published_strike_usd']==.12
    assert d['published_trailing_60s']['window_size']==60
    assert d['votes_in_forecast'] is False
    assert d['triggers_orders'] is False
    assert d['verified_final_settlement'] is False
    assert d['verified_strike_publication_time'] is False
    assert d['local_received_at']>=d['source_timestamp_ms']/1000
    assert not o.ingest(frame(),received_at=T+.5)
    assert o.stats['duplicate_or_reversed']==1
    stale=o.snapshot(now=T+40)
    assert stale['status']=='STALE' and not stale['fresh']
    assert stale['current_value_usd'] is None


def test_invalid_or_foreign_index_and_future_times_never_look_live():
    o=BRTIObserver()
    candidates=[None,{},[],{'type':CHANNELS[0],'msg':{'index_id':'BRTI','data':'not-json'}},
        frame(t=MS+100000),frame(value='NaN'),frame(value='-1'),
        frame(value=0),frame(value='Infinity')]
    for bad in candidates:
        assert not o.ingest(bad,received_at=T+.1)
    x=frame(); x['msg']['index_id']='ETHUSD_RTI'
    assert not o.ingest(x,received_at=T+.1)
    x=frame(); x['msg']['received_at']=MS+200000
    assert not o.ingest(x,received_at=T+.1)
    assert o.snapshot(now=T+.1)['current_value_usd'] is None


def test_progressive_15m_provider_average_is_nonsettlement_and_market_scoped():
    o=BRTIObserver()
    assert o.ingest(frame(closing=True),received_at=T+.1)
    one=o.snapshot({'target':64000.,'close_ts':T+10},now=T+.2)
    assert one['progressive_close_window']['value_usd']==64001.25
    assert one['progressive_close_window']['window_size']==45
    assert one['verified_final_settlement'] is False
    different=o.snapshot({'target':64000.,'close_ts':T+900},now=T+.2)
    assert different['progressive_close_window'] is None
    assert o.snapshot({'target':None},now=T+.2)['observed_distance_to_published_strike_usd'] is None


def test_sanitized_optional_append_only_trace(tmp_path):
    path=tmp_path/'records'/'real-observed-locally-only.jsonl'
    o=BRTIObserver(path)
    assert o.ingest(frame(),received_at=T+.1)
    assert o.ingest(frame(CHANNELS[1],MS+200),received_at=T+.3)
    records=[json.loads(line) for line in path.read_text().splitlines()]
    assert len(records)==2
    assert {r['channel'] for r in records}=={'1hz','5hz'}
    assert all('KALSHI-ACCESS' not in str(r) for r in records)
    assert all(r['local_received_at']>=r['source_ts_ms']/1000 for r in records)


def test_bad_average_never_replaced_with_fake_full_60_seconds():
    good={'value':'64000','window_size':30,'window_start_ts_ms':MS-30000,
          'window_end_ts_exclusive':MS}
    assert _average(good)['window_size']==30
    for invalid in ({**good,'window_size':True},{**good,'window_size':0},
                    {**good,'window_start_ts_ms':MS+1000},
                    {**good,'value':'NaN'},{**good,'window_size':301}):
        assert _average(invalid) is None
    for invalid in (None,'nan','Infinity',False,True,0,'-1',object()):
        assert _price(invalid) is None


def test_missing_credentials_fail_closed_without_websocket():
    o=BRTIObserver()
    run_stream(o,threading.Event(),key_id='',private_key='')
    d=o.snapshot()
    assert d['status']=='NOT_CONFIGURED' and not d['fresh']
    assert d['current_value_usd'] is None


def test_socket_signing_path_and_two_distinct_channel_subscriptions(monkeypatch):
    from research import verify_official_brti_live
    import websocket
    stop=threading.Event()
    ticks=[]
    now=time.time()
    ms=int((now-0.08)*1000)
    a=frame(t=ms,value='75000.5')
    b=frame(CHANNELS[1],t=ms+30,value='75000.5')
    class FakeWS:
        def __init__(self):
            self.sent=[]
            self.queue=[json.dumps(a),json.dumps(b)]
            self.closed=False
        def settimeout(self,t):
            assert t==2
        def send(self,s):
            self.sent.append(json.loads(s))
        def recv(self):
            value=self.queue.pop(0)
            ticks.append(value)
            if not self.queue: stop.set()
            return value
        def close(self):
            self.closed=True
    ws=FakeWS()
    headers=[]
    def fake_connect(url,header,timeout,enable_multithread):
        headers.extend(header)
        assert url.startswith('wss://external-api-ws.kalshi.com/')
        assert timeout==10 and enable_multithread
        return ws
    monkeypatch.setattr(verify_official_brti_live,'_signed_headers',
        lambda kid,key,path:{'KALSHI-ACCESS-KEY':kid,'KALSHI-ACCESS-SIGNATURE':'synthetic',
                             'KALSHI-ACCESS-TIMESTAMP':'1794957700000'})
    monkeypatch.setattr(websocket,'create_connection',fake_connect)
    o=BRTIObserver()
    run_stream(o,stop,key_id='fake-key-id',private_key='fake-in-memory-only')
    assert ws.closed
    assert len(ws.sent)==2
    assert ws.sent[0]['params']=={'channels':['cfbenchmarks_value'],'index_ids':['BRTI']}
    assert ws.sent[1]['params']=={'channels':['cfbenchmarks_value_5hz'],'index_ids':['BRTI']}
    assert any('KALSHI-ACCESS-KEY:' in h for h in headers)
    assert o.stats['accepted_1hz']==1 and o.stats['accepted_5hz']==1
    assert o.status=='STOPPED'


from test_e2e_synthetic import env


def test_fastapi_snapshot_never_uses_brti_as_forecast_or_verified_profit(env,monkeypatch):
    main,clock,p,client,_=env
    clock.now=p.close-600
    out=main.update_once()
    assert out['model']['available'] and len(out['engines'])==4
    assert 'live_brti' in out and 'strike_observation' in out
    assert out['live_brti']['votes_in_forecast'] is False
    assert out['live_brti']['verified_final_settlement'] is False
    assert not out['strike_observation']['official_publication_timestamp_verified']
    history=client.get('/api/state').json()
    assert history['live_brti']['triggers_orders'] is False
    health=client.get('/health').json()
    assert 'live_brti_status' in health and 'live_brti_fresh' in health
