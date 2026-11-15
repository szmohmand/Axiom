"""Permanent regression A14: authentic Coinbase 1m gap recovery without synthetic bars.

Requirements: preserve full-history behavior on complete inputs, allow the
existing 31+ model minimum using only consecutive genuine observations, and
fail closed for gaps in the newest 31 bars or non-one-minute cadence.
"""
from test_e2e_synthetic import env
from app.feeds import LiveProvider, COINBASE, contiguous_real_candle_suffix


def bars(count=65):
    base=1800000000 // 60 * 60
    return [{'t':base+i*60,'low':89000+i,'high':89100+i,'open':89030+i,
             'close':89050+i,'volume':10} for i in range(count)]


def test_full_history_is_byte_equivalent_for_contiguous_live_bars():
    original=bars()
    result,meta=contiguous_real_candle_suffix(original)
    assert result is original, "Normal input identity and model lookback must not change"
    assert meta['status']=='FULL'
    assert meta['bars_used']==65
    assert meta['missing_candles_filled']==0


def test_older_missing_coinbase_minute_recovers_genuine_recent_suffix():
    original=bars()
    missing=original[-43]['t']
    incomplete=[c for c in original if c['t'] != missing]
    result,meta=contiguous_real_candle_suffix(incomplete)
    assert meta['status']=='RECOVERED_REAL_CONTIGUOUS'
    assert meta['bars_used']==42
    assert meta['source_gap_minutes']==1
    assert meta['missing_candles_filled']==0
    assert result==incomplete[-42:]
    assert all(x in incomplete for x in result)
    assert all(b['t']-a['t']==60 for a,b in zip(result,result[1:]))


def test_recent_missing_minute_is_never_fabricated_or_accepted():
    original=bars()
    missing=original[-13]['t']
    incomplete=[c for c in original if c['t'] != missing]
    result,meta=contiguous_real_candle_suffix(incomplete)
    assert meta['status']=='GAP_TOO_RECENT'
    assert meta['recent_valid_bars']==12
    assert result is incomplete
    assert missing not in [c['t'] for c in result]


def test_non_minute_cadence_and_duplicate_are_not_mistaken_for_recoverable_gap():
    for change in ('thirty_seconds','duplicate','reverse'):
        original=bars()
        if change=='thirty_seconds': original[-34]={**original[-34],'t':original[-34]['t']+30}
        elif change=='duplicate': original[-34]={**original[-34],'t':original[-35]['t']}
        else: original[-34]={**original[-34],'t':original[-36]['t']}
        result,meta=contiguous_real_candle_suffix(original)
        assert result is original
        assert meta['status']=='INVALID_CADENCE'


def test_actual_live_provider_keeps_only_canonical_coinbase_candle_values(monkeypatch):
    from test_feed_contracts_audit import FakeResponse, provider
    original=bars()
    removed=original[-39]['t']
    available=[x for x in original if x['t'] != removed]
    raw=[[x['t'],x['low'],x['high'],x['open'],x['close'],x['volume']] for x in available]
    p=provider({COINBASE+'/products/BTC-USD/candles':FakeResponse(list(reversed(raw)))})
    got=p.candles()
    assert got == available[-38:]
    assert p.candle_quality['status']=='RECOVERED_REAL_CONTIGUOUS'
    assert p.candle_quality['bars_used']==38
    assert p.candle_quality['missing_candles_filled']==0


def test_real_gap_recovery_flows_through_entire_experimental_pipeline(env):
    main,clock,p,client,_=env
    clock.now=p.close-600
    original=p.candles
    baseline=original()
    without=[x for x in baseline if x['t']!=baseline[-43]['t']]
    recovered,quality=contiguous_real_candle_suffix(without)
    p.candle_quality=quality
    p.candles=lambda: recovered
    state=main.update_once()
    assert state['ok'] is True and state['status']=='DEMO'
    assert state['candle_quality']['status']=='RECOVERED_REAL_CONTIGUOUS'
    assert state['candle_quality']['bars_used']==42
    assert len(state['engines'])==4
    assert state['model']['available'] is True
    assert all(b['t']-a['t']==60 for a,b in zip(state['candles'],state['candles'][1:]))
    assert client.get('/api/state').json()['candle_quality']['missing_candles_filled']==0


def test_real_gap_in_latest_31_minutes_still_blocks_forecast_and_paper(env):
    main,clock,p,client,_=env
    clock.now=p.close-600
    original=p.candles()
    without=[x for x in original if x['t']!=original[-13]['t']]
    incomplete,meta=contiguous_real_candle_suffix(without)
    p.candle_quality=meta
    p.candles=lambda: incomplete
    state=main.update_once()
    assert state['status']=='DEGRADED'
    assert not state['ok']
    assert not state['model']['available']
    assert state['opportunity']['side']=='WAIT'
    assert state['candle_quality']['status']=='UNAVAILABLE'
    assert main.ledger.data()['count']=={'calls':0,'paper':0}
