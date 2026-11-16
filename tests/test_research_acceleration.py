import json,time
import pytest
from research import historical_180 as H
from research.accelerate_historical_180 import AdaptiveClient,DeadlineReached


def test_adaptive_429_retries_same_request_without_changing_response(tmp_path,monkeypatch):
    client=AdaptiveClient(tmp_path);calls=[]
    class Response:
        content=b'{"trades":[]}'
        def __init__(self,status):self.status_code=status;self.headers={'Retry-After':'0.01'} if status==429 else {}
    def get(url,**kwargs):calls.append(url);return Response(429 if len(calls)==1 else 200)
    monkeypatch.setattr(client.session,'get',get);monkeypatch.setattr(time,'sleep',lambda *_:None)
    assert client.get('https://external-api.kalshi.com/trade-api/v2/historical/trades')==b'{"trades":[]}'
    assert len(set(calls))==1 and client.rps==2 and client.metrics['http_429']==1


def test_deadline_makes_no_new_source_request(tmp_path,monkeypatch):
    c=AdaptiveClient(tmp_path,deadline=time.time())
    monkeypatch.setattr(c.session,'get',lambda *_a,**_k:pytest.fail('No request allowed after deadline'))
    with pytest.raises(DeadlineReached):c.get('https://external-api.kalshi.com/trade-api/v2/markets')


def test_imported_raw_cache_is_verified_and_reused_without_request(tmp_path,monkeypatch):
    source=H.PublicSource(tmp_path/'old',delay=0,getter=lambda *a,**k:b'{"trades":[]}')
    obj,meta=source.fetch('/historical/trades',{'ticker':'KXBTC15M-TEST'})
    target=H.PublicSource(tmp_path/'new',delay=0,getter=lambda *_a,**_k:pytest.fail('Cached response must not be requested again'),cache_roots=[tmp_path/'old'])
    assert target.fetch('/historical/trades',{'ticker':'KXBTC15M-TEST'})[0]==obj
    assert target.network_requests==0 and target.cache_hits==1


def test_completed_contract_group_cannot_hide_missing_or_duplicate_contracts():
    from research.monitor_acceleration import complete_group
    status={'collection_completed':True,'contract_offset':16,'limited_validation_sample':False,
            'independent_audit':{'independent_complete_population_audit_passed':True},
            'contract_results':[{'ticker':'a'},{'ticker':'b'}]}
    assert complete_group(status,['a','b'],16)
    assert not complete_group(status,['a','b','c'],16)
    assert not complete_group(status,['a','b'],0)
    status['contract_results']=[{'ticker':'a'},{'ticker':'a'},{'ticker':'b'}]
    assert not complete_group(status,['a','b'],16)


def test_day_cutoff_marks_uncollected_contracts_incomplete(tmp_path,monkeypatch):
    index=tmp_path/'index';(index/'BY_DAY').mkdir(parents=True)
    H.write_jsonl(index/'BY_DAY/2026-05-20.jsonl.gz',[{'ticker':'KXBTC15M-A','open_time':'2026-05-20T00:00:00Z','close_time':'2026-05-20T00:15:00Z'}])
    H.write_json(index/'HISTORICAL_CUTOFF.json',{'market_settled_ts':'2026-09-16T00:00:00Z','trades_created_ts':'2026-09-16T00:00:00Z'})
    monkeypatch.setattr(H,'get',lambda *_a,**_k:pytest.fail('Deadline must prevent requests'))
    with pytest.raises(RuntimeError,match='Incomplete'):
        H.collect_day(tmp_path/'day',index,'2026-05-20',deadline_epoch=time.time())
    status=json.loads((tmp_path/'day/COLLECTION_STATUS.json').read_text())
    assert not status['collection_completed']
    assert status['deferred_contracts']==['KXBTC15M-A']
