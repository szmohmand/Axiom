import os
import sys
import importlib
from types import SimpleNamespace
from fastapi.testclient import TestClient

def test_demo_app_offline(monkeypatch,tmp_path):
    monkeypatch.setenv('DEMO_MODE','1')
    monkeypatch.setenv('AUTO_PAPER','0')
    monkeypatch.setenv('BOT_ADMIN_TOKEN','test-secret')
    monkeypatch.setenv('DATA_PATH',str(tmp_path/'app.sqlite3'))
    # app.main import happens after env is configured
    sys.modules.pop('app.main',None)
    main=importlib.import_module('app.main')
    # Make paper-entry timing deterministic: a real clock can land in the
    # final 45 seconds and cause an intermittent expected HTTP 409.
    fixed_now=(1_800_000_000 // 900)*900 + 120
    monkeypatch.setattr(main, 'time', SimpleNamespace(time=lambda: fixed_now))
    from app import feeds
    monkeypatch.setattr(feeds, 'time', SimpleNamespace(time=lambda: fixed_now))
    main.update_once()
    with TestClient(main.app) as c:
        h=c.get('/health');assert h.status_code==200
        s=c.get('/api/state');assert s.status_code==200
        data=s.json()
        assert data['mode']=='DEMO' and data['market']['ticker'].startswith('KXBTC15M-DEMO')
        assert len(data['candles'])>=24
        assert c.get('/').status_code==200
        assert 'AXIOM' in c.get('/').text
        assert c.post('/api/paper',json={'side':'YES'}).status_code==401
        response=c.post('/api/paper',json={'side':'YES'},headers={'Authorization':'Bearer test-secret'})
        assert response.status_code==200
        assert c.get('/api/export/paper_trades',headers={'Authorization':'Bearer test-secret'}).status_code==200
