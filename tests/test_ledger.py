import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from app.storage import Ledger

M={'ticker':'KXBTC15M-UNIT-01','seconds_left':500,'target':90000,'yes_ask':.40,'no_ask':.62,'market_mid':.39}
F={'available':True,'prob_above':.91,'prob_below':.09,'side':'ABOVE'}

def test_hold_rule_and_first_call_is_immutable():
    with TemporaryDirectory() as d:
        x=Ledger(str(Path(d)/'a.db'))
        assert x.first_call(M,F,90100,100,hold_seconds=10) is None
        assert x.first_call(M,F,90100,107,hold_seconds=10) is None
        assert x.first_call(M,F,90100,111,hold_seconds=10)['side']=='ABOVE'
        assert x.first_call(M,F,90100,115,hold_seconds=10) is None
        assert x.data()['count']['calls']==1
        x.grade(M['ticker'],'yes',120)
        assert x.data()['stats']['first_call_accuracy']==1

def test_gate_resets_when_signal_lost_or_stale():
    with TemporaryDirectory() as d:
        x=Ledger(str(Path(d)/'a.db'))
        x.first_call(M,F,90100,100)
        x.first_call(M,{**F,'prob_above':.50},90100,106)
        assert x.first_call(M,F,90100,115) is None
        assert x.first_call(M,F,90100,126)['side']=='ABOVE'

def test_one_paper_trade_per_market_and_official_settlement():
    with TemporaryDirectory() as d:
        x=Ledger(str(Path(d)/'a.db'))
        pos=x.trade(M,'YES',100,source='AUTO_RESEARCH')
        assert pos['entry']==.40
        with pytest.raises(ValueError): x.trade(M,'NO',111)
        x.grade(M['ticker'],'no',121)
        data=x.data()
        assert data['trades'][0]['pnl']==-.40
        assert data['stats']['paper_win_rate']==0
        assert data['stats']['gross_paper_pnl']==-.40

def test_export_and_restart_persists():
    with TemporaryDirectory() as d:
        path=str(Path(d)/'db.sqlite3')
        x=Ledger(path);x.trade(M,'YES',100)
        h,rows=x.export('paper_trades'); assert 'entry' in h and len(rows)==1
        y=Ledger(path); assert y.data()['count']['paper']==1
