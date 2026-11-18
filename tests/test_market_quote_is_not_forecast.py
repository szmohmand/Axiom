"""Regression: Kalshi contract prices are order-book quotes, not Kalshi predictions.

No changes here should require or trigger real orders, an account, or
official CF Benchmarks BRTI access. Existing forecast and fee math is preserved.
"""
from __future__ import annotations

import math
from pathlib import Path

from app.engine import market_snapshot
from app.ensemble import engine_pack, execution_screen
from app.storage import Ledger


def sample():
    candles=[]
    for i in range(65):
        p=90000+3*i+20*math.sin(i/4)
        candles.append({'t':1700000000+60*i, 'close':p, 'open':p-2,
                        'high':p+12, 'low':p-12, 'volume':2})
    market={'ticker':'KXBTC15M-MARKET-QUOTE-TEST','seconds_left':600,
            'target':90090,'market_mid':.70,
            'yes_bid':.68,'yes_ask':.72,'no_bid':.28,'no_ask':.32}
    return market,candles,candles[-1]['close']


def test_snapshot_provenance_identifies_order_book_not_a_prediction():
    import datetime
    raw={'ticker':'KXBTC15M-MARKET-QUOTE-TEST',
         'close_time':datetime.datetime.fromtimestamp(1710000900,datetime.timezone.utc).isoformat(),
         'floor_strike':90090,
         'yes_bid_dollars':'0.68', 'yes_ask_dollars':'0.72',
         'no_bid_dollars':'0.28', 'no_ask_dollars':'0.32'}
    m=market_snapshot(raw,now=1710000000)
    assert m['yes_bid']==.68 and m['yes_ask']==.72
    assert m['market_mid']==.70
    assert m['market_price_source']=='participant_order_book'
    assert m['market_price_is_forecast'] is False
    assert m['market_mid_role']=='yes_quote_midpoint_not_objective_probability'


def test_large_changes_in_order_book_quotes_cannot_change_independent_forecast():
    market,candles,spot=sample()
    a=engine_pack(spot,market,candles)
    changed={**market, 'market_mid':.10,'yes_bid':.08,'yes_ask':.12,
             'no_bid':.88,'no_ask':.92}
    b=engine_pack(spot,changed,candles)
    assert a['available'] and b['available']
    assert a['side']==b['side']
    assert a['prob_above']==b['prob_above']
    assert a['prob_below']==b['prob_below']
    assert a['spread']==b['spread']
    assert a['agreement']==b['agreement']
    assert a['forecast_minus_quote_mid']!=b['forecast_minus_quote_mid']
    assert a['quote_discrepancy_is_validated_alpha'] is False


def test_quote_benchmark_is_never_an_independent_direction_signal():
    market,candles,spot=sample()
    e=engine_pack(spot,market,candles)
    book=next(x for x in e['engines'] if x['name']=='kalshi_market')
    assert book['prob_above']==.70  # legacy numeric quote-as-benchmark only
    assert book['role']=='participant_order_book_price_benchmark'
    assert book['method']=='orderbook-quote-benchmark'
    assert book['independent'] is False
    assert book['is_model_prediction'] is False
    assert book['side']=='N/A'
    real=[x for x in e['engines'] if x['name']!='kalshi_market']
    assert len(real)==3 and all(x['independent'] for x in real)


def test_quotes_change_paper_entry_value_not_model_prediction():
    model={'available':True,'side':'ABOVE','prob_above':.80}
    market,candles,spot=sample()
    cheap={**market,'yes_bid':.36,'yes_ask':.38,'no_bid':.62,'no_ask':.64}
    expensive={**market,'yes_bid':.78,'yes_ask':.80,'no_bid':.20,'no_ask':.22}
    a=execution_screen(model,cheap)
    b=execution_screen(model,expensive)
    assert a['side']=='YES'
    assert a['entry_price']==.38
    assert b['side']=='WAIT'
    assert b['entry_price']==.80
    assert b['edge']<a['edge']
    assert model['prob_above']==.80


def test_quote_brier_benchmark_is_labeled_not_proven_alpha(tmp_path):
    market,candles,spot=sample()
    model=engine_pack(spot,market,candles)
    db=Ledger(str(tmp_path/'quotes.sqlite3'))
    assert db.engine_snapshots(market,model,1700004000)==5
    db.grade(market['ticker'],'yes',1700004900)
    stats=db.engine_scores()
    assert len(stats['scores'])==5
    assert 'participant quotes' in stats['note'] or 'Order-book' in stats['note']
    assert all(x['benchmark_kind']=='participant_order_book_yes_midpoint'
               for x in stats['scores'])
    assert all(x['market_price_is_kalshi_prediction'] is False
               for x in stats['scores'])
    assert all(x['validated_alpha'] is False for x in stats['scores'])


def test_dashboard_distinguishes_cents_from_probabilities():
    html=(Path(__file__).resolve().parents[1]/'app'/'static'/'index.html').read_text()
    assert 'Kalshi YES · Quote midpoint' in html
    assert "set('marketProb',cents(m?.market_mid))" in html
    assert "set('modelProb',pct(f?.prob_above))" in html
    assert "quote?cents(e.prob_above):pct(e.prob_above)" in html
    assert 'QUOTE ONLY' in html
    assert 'Kalshi order-book quote' in html
    assert "id=\"opReason\"" in html
    assert 'traders' in html.lower()
