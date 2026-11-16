import json
import pytest
from research import export_august_archived_kalshi as E
from research import export_kalshi_30day as K
from research import export_shared_historical as S


def test_empty_archived_source_is_preserved_and_shared_helpers_restore(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in ('BEGIN','END','LO','HI','ROOT','OUT','json_get'):
        monkeypatch.setattr(K,key,getattr(K,key))
    urls=[]
    def get(url,headers=None,cap=0):
        assert headers is None
        urls.append(url)
        return b'{"markets":[]}'
    monkeypatch.setattr(S,'get',get)
    original_json=K.json_get
    with pytest.raises(ValueError,match='No Kalshi'):
        E.run()
    assert S.get is get
    assert K.json_get is original_json
    assert '/historical/markets?' in urls[0]
    assert 'min_close_ts' not in urls[0]
    root=tmp_path/'august_KALSHI'
    assert (root/'ORIGINAL_RESPONSES/response_0000.json.gz').exists()
    assert json.loads((root/'FAILURE.json').read_text())['requests_preserved']==1


def test_public_research_helpers_import_without_signing_dependency():
    import subprocess,sys
    code='''
import sys,importlib.abc
class BlockSigning(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='cryptography' or fullname.startswith('cryptography.'):
            raise ModuleNotFoundError('Signing dependency intentionally absent')
sys.meta_path.insert(0,BlockSigning())
from research import export_shared_historical as S
from research import export_august_archived_kalshi
assert list(S.walk_values({'data':[{'time':1,'value':'2'}]}))==[{'time':1,'value':'2'}]
'''
    subprocess.run([sys.executable,'-c',code],check=True)
