import gzip,json
from pathlib import Path
import pytest
from research import historical_180 as H


def test_public_cache_replays_verified_bytes_and_rejects_account_endpoints(tmp_path,monkeypatch):
    calls=[]
    def fake(url,**kwargs):calls.append(url);return b'{"markets":[]}'
    monkeypatch.setattr(H,'get',fake)
    s=H.PublicSource(tmp_path,delay=0)
    obj,meta=s.fetch('/markets',{'series_ticker':'KXBTC15M'})
    assert obj=={'markets':[]}
    assert s.fetch('/markets',{'series_ticker':'KXBTC15M'})[0]==obj
    assert len(calls)==1 and s.cache_hits==1
    with pytest.raises(ValueError,match='scope'):s.fetch('/portfolio/orders')
    Path(meta['response_file']).write_bytes(gzip.compress(b'{"markets":[1]}'))
    with pytest.raises(ValueError,match='integrity'):s.fetch('/markets',{'series_ticker':'KXBTC15M'})


def test_pagination_cannot_silently_repeat_cursor():
    class Fake:
        def fetch(self,*args):return {'trades':[],'cursor':'same'},{}
    with pytest.raises(ValueError,match='Repeated'):
        list(H.paginated(Fake(),'/historical/trades',{},'trades'))


def test_daily_trade_identity_and_original_precision_are_preserved(tmp_path,monkeypatch):
    index=tmp_path/'index';(index/'BY_DAY').mkdir(parents=True)
    market={'ticker':'KXBTC15M-TEST','open_time':'2026-05-20T00:00:00Z',
            'close_time':'2026-05-20T00:15:00Z','volume_fp':'1.25'}
    H.write_jsonl(index/'BY_DAY/2026-05-20.jsonl.gz',[market])
    H.write_json(index/'HISTORICAL_CUTOFF.json',{'market_settled_ts':'2026-09-16T00:00:00Z','trades_created_ts':'2026-09-16T00:00:00Z'})
    trade={'ticker':market['ticker'],'trade_id':'a','created_time':'2026-05-20T00:01:00.123456Z',
           'count_fp':'1.25','yes_price_dollars':'0.1234','no_price_dollars':'0.8766'}
    monkeypatch.setattr(H,'get',lambda *a,**k:json.dumps({'trades':[trade]}).encode())
    monkeypatch.setattr(H.time,'sleep',lambda *_:None)
    report=H.collect_day(tmp_path/'day',index,'2026-05-20',quotes=False)
    assert report['collection_completed']
    result=report['contract_results'][0]
    assert result['trade_ticks']==1 and result['trade_quantity_sum']=='1.25'
    rows=list(H.iter_jsonl(tmp_path/'day/TRADES/KXBTC15M-TEST.jsonl.gz'))
    assert rows[0]['original_trade']==trade
    from research.verify_public_180_day import verify
    assert verify(tmp_path/'day')['independent_complete_population_audit_passed']
    rows[0]['original_trade']['yes_price_dollars']='0.9999'
    H.write_jsonl(tmp_path/'day/TRADES/KXBTC15M-TEST.jsonl.gz',rows)
    with pytest.raises(ValueError,match='differs'):
        verify(tmp_path/'day')


def test_failed_trade_population_retains_checkpoint_and_original_response(tmp_path,monkeypatch):
    index=tmp_path/'index';(index/'BY_DAY').mkdir(parents=True)
    H.write_jsonl(index/'BY_DAY/2026-05-20.jsonl.gz',[{'ticker':'KXBTC15M-TEST',
        'open_time':'2026-05-20T00:00:00Z','close_time':'2026-05-20T00:15:00Z','volume_fp':'9'}])
    H.write_json(index/'HISTORICAL_CUTOFF.json',{'market_settled_ts':'2026-09-16T00:00:00Z','trades_created_ts':'2026-09-16T00:00:00Z'})
    monkeypatch.setattr(H,'get',lambda *a,**k:b'{"trades":[]}')
    monkeypatch.setattr(H.time,'sleep',lambda *_:None)
    with pytest.raises(RuntimeError,match='Incomplete'):
        H.collect_day(tmp_path/'day',index,'2026-05-20',quotes=False)
    status=json.loads((tmp_path/'day/COLLECTION_STATUS.json').read_text())
    assert not status['collection_completed'] and status['failed_contracts']==['KXBTC15M-TEST']
    assert list((tmp_path/'day/ORIGINAL_RESPONSES').glob('*.json.gz'))
