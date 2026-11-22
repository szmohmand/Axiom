"""Permanent regression tests for the optional, research-only shadow model."""
from __future__ import annotations

import math

import pytest

from app.settlement_research import shadow_forecast_from_candles


def candles(n=62, step=60, start=1799000000):
    return [
        {'t': start+i*step, 'close': 80000 + i + 7*math.sin(i/3),
         'open': 80000 + i, 'high': 80020+i, 'low': 79980+i, 'volume': 2.0}
        for i in range(n)
    ]


def inputs(bars=None, seconds=300):
    c = candles() if bars is None else bars
    now = c[-1]['t'] + 60
    m = {'ticker':'KXBTC15M-SHADOW-TEST','target':80040,
         'seconds_left':seconds,'market_mid':.53,'yes_bid':.51,
         'yes_ask':.55,'no_bid':.45,'no_ask':.49}
    return c, now, m


def test_shadows_never_trade_and_are_explicitly_coinbase_proxies():
    c, now, m = inputs()
    p = shadow_forecast_from_candles(c, m, now)
    assert p['available']
    assert p['research_only'] and not p['votes_in_ensemble']
    assert not p['can_trigger_paper_or_orders']
    assert p['source']=='COINBASE_SPOT_PROXY_NOT_BRTI'
    assert p['status']=='PROXY_ONLY_NOT_CALIBRATED'
    assert p['completed_bar_end'] <= now
    assert p['prob_above'] + p['prob_below'] == pytest.approx(1, abs=1e-6)


def test_shadows_do_not_read_contract_prices():
    c, now, m = inputs()
    a = shadow_forecast_from_candles(c, m, now)
    b = shadow_forecast_from_candles(c, {**m, 'market_mid':.02, 'yes_ask':.99}, now)
    assert a['prob_above']==b['prob_above']


def test_incomplete_current_bar_cannot_pollute_research():
    c, now, m = inputs()
    base = shadow_forecast_from_candles(c, m, now)
    plus = shadow_forecast_from_candles(c+[{'t':now,'close':1e9}],m,now+10)
    assert plus['prob_above'] == base['prob_above']


@pytest.mark.parametrize('scenario', [
    'short', 'gap', 'duplicate', 'future', 'stale', 'zero-vol',
    'missing-strike', 'expired', 'missing-market'
])
def test_unavailable_instead_of_invented_price_or_probability(scenario):
    c,now,m=inputs()
    if scenario=='short': c=c[-25:]
    if scenario=='gap': c=candles(step=120);now=c[-1]['t']+60
    if scenario=='duplicate': c=c[:30]+[c[29]]+c[30:]
    if scenario=='future': c=c+[{'t':now+120,'close':80000}]
    if scenario=='stale': now+=250
    if scenario=='zero-vol': c=[{**x,'close':80000} for x in c]
    if scenario=='missing-strike': m={**m,'target':None}
    if scenario=='expired': m={**m,'seconds_left':0}
    if scenario=='missing-market': m=None
    x=shadow_forecast_from_candles(c,m,now)
    assert not x['available'] and x['side']=='WAIT'
    assert x['prob_above'] is None
    assert not x['can_trigger_paper_or_orders']


def test_near_target_abstention():
    c,now,m=inputs()
    x=shadow_forecast_from_candles(c,{**m,'target':c[-1]['close']},now)
    assert x['side']=='WAIT' and x['near_target_uncertainty']
    assert x['prob_above']==pytest.approx(.5)


def test_30_completed_minute_history_supported():
    c,now,m=inputs(candles(31))
    x=shadow_forecast_from_candles(c,m,now)
    assert x['available'] and x['vol_minutes']==30


def test_existing_forecast_is_unchanged_and_shadow_publishes_without_voting(monkeypatch,tmp_path):
    from app import main
    from app.ensemble import engine_pack
    from app.storage import Ledger
    c,now,m=inputs()
    class Provider:
        def market(self, now=None): return m
        def price(self): return c[-1]['close']
        def candles(self): return c
    monkeypatch.setattr(main,'provider',Provider())
    monkeypatch.setattr(main,'ledger',Ledger(str(tmp_path/'shadow.sqlite3')))
    monkeypatch.setattr(main,'AUTO_PAPER',False)
    monkeypatch.setattr(main,'DEMO',True)
    # This optional feature must not change normal ensemble outputs.
    state=main.update_once(now=now)
    original=engine_pack(c[-1]['close'],m,c,
        signals=state['btc_signals'],
        context={'timeframes':state['higher_timeframes'],
                 'microstructure':state['market_microstructure']},now=now)
    assert state['model']==original
    expected={'axiom_volatility','aaryann_fair','kalshibot_headstart',
              'axiom_gradient_boosted_btc','axiom_full_nison',
              'axiom_multi_signal_context'}
    if state['btc_signals']['available']:
        expected.add('axiom_target_dynamics')
    # Target dynamics is included only when its own BTC source signals exist.
    assert {e['name'] for e in state['model']['engines']}==expected
    assert state['research_shadow']['research_only']
    assert not state['research_shadow']['votes_in_ensemble']
    assert not state['research_shadow']['can_trigger_paper_or_orders']
    # Source outages in the main app must not expose a cached shadow direction.
    stale=main._view_locked(now+200)
    assert stale['research_shadow']['side']=='WAIT'
    assert not stale['research_shadow']['available']


def test_shadow_exception_does_not_interrupt_existing_poll(monkeypatch,tmp_path):
    from app import main
    from app.ensemble import engine_pack
    from app.storage import Ledger
    c,now,m=inputs()
    class Provider:
        def market(self, now=None): return m
        def price(self): return c[-1]['close']
        def candles(self): return c
    monkeypatch.setattr(main,'provider',Provider())
    monkeypatch.setattr(main,'ledger',Ledger(str(tmp_path/'unavailable.sqlite3')))
    monkeypatch.setattr(main,'AUTO_PAPER',False)
    monkeypatch.setattr(main,'DEMO',True)
    def boom(*args): raise RuntimeError('simulated shadow outage')
    monkeypatch.setattr(main,'shadow_forecast_from_candles',boom)
    state=main.update_once(now=now)
    assert state['model']==engine_pack(c[-1]['close'],m,c,
        signals=state['btc_signals'],
        context={'timeframes':state['higher_timeframes'],
                 'microstructure':state['market_microstructure']},now=now)
    assert state['research_shadow']['side']=='WAIT'
    assert 'Research model calculation failed' in state['research_shadow']['reason']


def test_dashboard_exposes_nonvoting_shadow_without_changing_trade_controls():
    from pathlib import Path
    markup = (Path(__file__).resolve().parents[1] / 'app' / 'static' / 'index.html').read_text()
    for identifier in ('shadowSide', 'shadowZ', 'shadowBars', 'shadowReason'):
        assert 'id="' + identifier + '"' in markup
        assert "set('" + identifier + "'" in markup
    assert 'SHADOW · NON-VOTING' in markup
    assert 'BTC proxy study · not the BRTI index' in markup

