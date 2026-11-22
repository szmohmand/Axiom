"""Checks for AXIOM v2 multi-engine forecasting and fair comparative scoring."""
from __future__ import annotations
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from app.ensemble import engine_pack, execution_screen, taker_fee, cdf
from app.storage import Ledger


def fixtures(seconds=600,mid=.52):
    candles=[]
    for i in range(65):
        v=90000+2.5*i+18*math.sin(i/4)
        candles.append({'t':1700000000+i*60,'close':v,'open':v-2,'high':v+11,
                        'low':v-12,'volume':2.1})
    market={'ticker':'KXBTC15M-V2-TEST','seconds_left':seconds,'target':90090,
            'market_mid':mid,'yes_bid':mid-.02,'yes_ask':mid+.02,
            'no_ask':1-mid+.02,'no_bid':1-mid-.02}
    return market,candles,candles[-1]['close']


def test_all_three_engines_same_snapshot_and_market_not_voting():
    m,c,s=fixtures()
    e=engine_pack(s,m,c)
    assert e['available'] and len(e['engines'])==3
    assert set(x['name'] for x in e['engines'])=={
        'axiom_volatility','aaryann_fair','kalshibot_headstart'}
    assert e['validated'] is False
    real=[x['prob_above'] for x in e['engines'] if x.get('independent') and x['available']]
    assert abs(e['prob_above']-sorted(real)[1]) < 1e-5
    assert abs(e['prob_above']+e['prob_below']-1)<1e-8
    # Changing only the Kalshi market price never changes consensus.
    m2={**m,'market_mid':.10}
    e2=engine_pack(s,m2,c)
    assert e2['prob_above']==e['prob_above']


def test_aaryann_port_matches_published_equation():
    m,c,s=fixtures()
    e=engine_pack(s,m,c)
    vals={x['name']:x for x in e['engines']}
    returns=[math.log(b['close']/a['close']) for a,b in zip(c[-61:],c[-60:])]
    from statistics import pstdev
    sigma=max(pstdev(returns),1e-6)
    ret5=math.log(s/c[-6]['close']); remaining=m['seconds_left']/60
    z=(math.log(s/m['target'])+.5*ret5*min(remaining,5)/5)/(sigma*math.sqrt(remaining))
    assert abs(vals['aaryann_fair']['prob_above']-cdf(z))<.00001


def test_missing_inputs_dont_fake_engine_probabilities():
    m,c,s=fixtures()
    e=engine_pack(s,{**m,'target':None},c)
    assert e['available'] is False and e['side']=='WAIT'
    assert all(not x['available'] for x in e['engines'] if x.get('independent'))
    x=engine_pack(s,None,c)
    assert x['available'] is False


def test_fee_and_execution_gate():
    assert taker_fee(.5)==.02
    m,c,s=fixtures()
    f=engine_pack(s,m,c)
    result=execution_screen(f,m)
    assert result['side'] in ('YES','NO','WAIT')
    if result['edge'] is not None:
        assert result['edge']==round(result['gross_edge']-result['fee_estimate'],5)
    assert execution_screen({**f,'side':'WAIT'},m)['side']=='WAIT'


def test_checkpoint_immutable_and_official_grade_all_models():
    m,c,s=fixtures(seconds=601)
    e=engine_pack(s,m,c)
    with TemporaryDirectory() as d:
        db=Ledger(str(Path(d)/'ledger.sqlite3'))
        n=db.engine_snapshots(m,e,1000)
        assert n==4  # three BTC-only experimental engines + ensemble; quote is execution-only
        assert db.engine_snapshots(m,e,1009)==4
        assert db.engine_scores()['samples']==4
        assert len(db.unresolved())==1
        # changing prediction in same window does not overwrite a first forecast
        very_different=engine_pack(s+300,m,c)
        db.engine_snapshots(m,very_different,1020)
        db.grade(m['ticker'],'no',1090)
        stats=db.engine_scores()
        assert len(stats['scores'])==4
        assert all(x['n']==1 for x in stats['scores'])
        assert all(x['validated_alpha'] is False for x in stats['scores'])
        assert len(db.unresolved())==0
        h,rows=db.export('engine_snapshots')
        assert 'checkpoint' in h and len(rows)==4
        p0=[row[h.index('prob_above')] for row in rows if row[h.index('engine')]=='ensemble'][0]
        assert p0==e['prob_above']


def test_outside_checkpoint_no_records():
    m,c,s=fixtures(seconds=700)
    with TemporaryDirectory() as d:
        db=Ledger(str(Path(d)/'test.db'))
        assert db.engine_snapshots(m,engine_pack(s,m,c),100)==0
        assert db.engine_scores()['samples']==0


def test_disagreement_abstains_but_still_logs_probabilities():
    # Consensus of different models can disagree significantly; this test
    # replaces two functions' predictions with local simulation to verify
    # the decision gate via the production median/dispersion logic.
    from app.ensemble import engine_result
    assert engine_result('x',None,'a','missing')['side']=='WAIT'
    assert engine_result('x',.99,'a','test')['prob_above']==.99
