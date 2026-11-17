"""One-off AXIOM public-data integration probe. GET requests ONLY.

Run in GitHub Actions with DEMO_MODE=0, AUTO_PAPER=0. No keys, database,
paper orders, account endpoints, or trading actions are used. A failure
is evidence about provider/schema availability, not trading performance.
"""
import json
import time

from app.feeds import LiveProvider, KALSHI
from app.engine import scalp_signal
from app.ensemble import engine_pack, execution_screen
from app.depth_intelligence import analyze_opportunities, execution_guidance

def probe():
    p=LiveProvider()
    results={'source':'real public Kalshi + Coinbase GET endpoints',
             'read_only':True,'time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
             'checks':{},'warnings':[]}
    failures=[]
    try:
        btc=p.price()
        results['checks']['coinbase_ticker']={'ok':True,'positive':btc>0}
        if btc<=0:failures.append('nonpositive Coinbase price')
    except Exception as e:
        btc=None
        results['checks']['coinbase_ticker']={'ok':False,'error':type(e).__name__+': '+str(e)[:160]}
        failures.append('Coinbase ticker unavailable')
    try:
        candles=p.candles()
        last_age=round(time.time()-candles[-1]['t']) if candles else None
        results['checks']['coinbase_candles']={'ok':len(candles)>=31,
            'count':len(candles),'newest_age_seconds':last_age}
        if len(candles)<31 or last_age is None or last_age>200:
            failures.append('Coinbase candles missing or stale')
    except Exception as e:
        candles=[]
        results['checks']['coinbase_candles']={'ok':False,'error':type(e).__name__+': '+str(e)[:160]}
        failures.append('Coinbase candles unavailable')
    try:
        market=p.market()
        results['checks']['kalshi_open_market']={
            'ok':bool(market),'ticker':market['ticker'] if market else None,
            'seconds_left':market['seconds_left'] if market else None,
            'has_target':market.get('target') is not None if market else False,
            'yes_ask_present':market.get('yes_ask') is not None if market else False}
        if not market:results['warnings'].append('No active KXBTC15M contract returned; forecast cannot be certified')
    except Exception as e:
        market=None
        results['checks']['kalshi_open_market']={'ok':False,'error':type(e).__name__+': '+str(e)[:160]}
        failures.append('Kalshi market endpoint failed')
    # Verify actual Kalshi full-depth GET, with no authentication or order submission.
    book=None
    if market:
        try:
            book=p.orderbook(market)
            results['checks']['kalshi_full_aggregated_depth']={
                'ok':book.get('available',False),'ticker':book.get('ticker'),
                'levels':book.get('levels'), 'source':book.get('source'),
                'read_only':True, 'individual_orders_visible':False}
            if not book.get('available'):
                results['warnings'].append('Active contract has no resting depth; execution signals must WAIT')
        except Exception as e:
            results['checks']['kalshi_full_aggregated_depth']={'ok':False,
                'error':type(e).__name__+': '+str(e)[:160]}
            failures.append('Kalshi live full-depth endpoint failed')
    if market and btc and candles:
        try:
            models=engine_pack(btc,market,candles)
            scalp=scalp_signal(candles,btc)
            opportunity=execution_screen(models,market)
            depth_op=analyze_opportunities(models,market,book,time.time())
            advice=execution_guidance(depth_op,models,market,book,time.time())
            results['checks']['real_feed_pipeline']={
                'ok':models.get('available',False),
                'engine_names':[x.get('name') for x in models['engines']],
                'available_engines':[x.get('name') for x in models['engines'] if x.get('available')],
                'scalp_side':scalp['side'],'contract_screen':opportunity['side'],
                'depth_opportunity':depth_op['side'], 'manual_execution_action':advice['action'],
                'execution_is_read_only':advice['read_only'],
                'reason':models.get('reason')}
            if not models.get('available',False): failures.append('Real-feed forecast unavailable')
        except Exception as e:
            results['checks']['real_feed_pipeline']={'ok':False,'error':type(e).__name__+': '+str(e)[:160]}
            failures.append('Real-feed forecast/scalp pipeline threw exception')
    # Check settlement retrieval on a reported settled contract, if one is available.
    try:
        payload=p.get(KALSHI+'/markets',
             {'series_ticker':'KXBTC15M','status':'settled','mve_filter':'exclude','limit':10})
        settled=[m for m in payload.get('markets',[]) if m.get('result') in ('yes','no')]
        if settled:
            item=settled[0]
            outcome=p.settlement(item['ticker'])
            ok=outcome==item['result']
            results['checks']['kalshi_settlement']={'ok':ok,'result_present':True,
                'source_ticker':item['ticker'],'lookup_matched_list':ok}
            if not ok:failures.append('Settlement lookup disagrees with reported result')
        else:
            results['checks']['kalshi_settlement']={'ok':None,'result_present':False}
            results['warnings'].append('No settled KXBTC15M returned in first page; outcome readback unverified')
    except Exception as e:
        results['checks']['kalshi_settlement']={'ok':False,'error':type(e).__name__+': '+str(e)[:160]}
        failures.append('Kalshi settled-market lookup failed')
    results['failed_checks']=failures
    print(json.dumps(results,indent=2,sort_keys=True))
    if failures:raise SystemExit(1)

if __name__=='__main__':
    probe()
