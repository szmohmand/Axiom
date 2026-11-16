import datetime as dt
import tempfile
from pathlib import Path
import pytest
from research import export_brti_interval as I
from research import export_brti_30day as C


def test_interval_reuses_hour_boundaries_and_rejects_invalid_ranges():
    old = {k:getattr(C,k) for k in ('BEGIN','END','FIRST_HOUR','ROOT','INDEX_DIR')}
    try:
        I.configure('2026-08-06','2026-08-13','scratch')
        hours=list(C.iter_hours())
        assert len(hours)==169
        assert hours[0]==dt.datetime(2026,8,5,23,tzinfo=dt.timezone.utc)
        assert hours[-1]==dt.datetime(2026,8,12,23,tzinfo=dt.timezone.utc)
        for begin,end in [('2026-08-13','2026-08-06'),('2026-08-06','2026-10-01')]:
            with pytest.raises(ValueError):I.configure(begin,end,'scratch')
    finally:
        for k,v in old.items():setattr(C,k,v)


def test_raw_response_precision_and_retrieval_provenance_without_headers(tmp_path, monkeypatch):
    import gzip,json
    from research import export_shared_historical as S
    monkeypatch.chdir(tmp_path)
    raw=b'{"data":[{"time":1785970800000,"value":"12345.123456789012"}]}'
    def fake_get(url, headers=None, cap=0):
        assert headers=={'sensitive':'never serialize'}
        return raw
    monkeypatch.setattr(S,'get',fake_get)
    old={k:getattr(C,k) for k in ('BEGIN','END','FIRST_HOUR','ROOT','INDEX_DIR')}
    def fake_run():
        S.get(S.API+'/cfbenchmarks/history/values?id=BRTI', {'sensitive':'never serialize'})
        p=C.ROOT/'AUDIT';p.mkdir()
        (p/'BRTI_30DAY_MANIFEST.json').write_text('{}')
    monkeypatch.setattr(C,'run',fake_run)
    try:
        I.run()
        assert S.get is fake_get
        p=tmp_path/'interval_BRTI/ORIGINAL_RESPONSES'
        assert gzip.decompress((p/'hour_0000.json.gz').read_bytes())==raw
        manifest=(p/'retrieval_manifest.json').read_text()
        assert 'never serialize' not in manifest
        assert json.loads(manifest)[0]['retrieval_completed_utc']
        m=json.loads((tmp_path/'interval_BRTI/AUDIT/BRTI_30DAY_MANIFEST.json').read_text())
        assert m['utc_complete_days_covered_from']=='2026-08-06'
        assert m['utc_complete_days_covered_through']=='2026-08-12'
    finally:
        for k,v in old.items():setattr(C,k,v)


def test_resumption_replays_original_bytes_without_new_source_requests(tmp_path, monkeypatch):
    import json
    from research import export_shared_historical as S
    monkeypatch.chdir(tmp_path)
    for name in ('BEGIN','END','FIRST_HOUR','ROOT','INDEX_DIR'):
        monkeypatch.setattr(C,name,getattr(C,name))
    calls=[]
    raw=b'{"data":[{"time":1,"value":"2.123456789"}]}'
    monkeypatch.setattr(S,'get',lambda *a,**k:(calls.append(a[0]) or raw))
    def fake_run():
        assert S.get(S.API+'/cfbenchmarks/history/values?id=BRTI')==raw
        p=C.ROOT/'AUDIT';p.mkdir(exist_ok=True)
        (p/'BRTI_30DAY_MANIFEST.json').write_text('{}')
    monkeypatch.setattr(C,'run',fake_run)
    I.run();I.run()
    assert len(calls)==1
    status=json.loads((C.ROOT/'COLLECTION_STATUS.json').read_text())
    assert status['collection_completed'] is True
    assert status['original_responses_preserved']==1
