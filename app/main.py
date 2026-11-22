"""Single-process web server + live background research/paper-trading worker."""
from __future__ import annotations
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import csv
import io
import math
import os
import threading
import time
import traceback
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from .feeds import LiveProvider, DemoProvider
from .engine import scalp_signal
from .ensemble import engine_pack, execution_screen
from .market_structure import BTCFlowTracker, timeframes
from .contract_repricing import ContractRepricingModel, unavailable as unavailable_contract_repricing
from .storage import Ledger
from .settlement_research import shadow_forecast_from_candles, unavailable as unavailable_research_shadow
from .candlestick_context import read_candlestick_context, unavailable as unavailable_candle_context
from .candlestick_challenger import derive_candlestick_challenger, unavailable as unavailable_candle_challenger
from .orderbook import unavailable as unavailable_book
from .execution_evidence import examine_liquidity
from .brti_live import BRTITracker, run_worker as brti_reference_worker
from .decision_signals import derive_signals, unavailable as unavailable_signals, execution_decision
from .intracontract import (IntracontractTracker, unavailable as unavailable_timeline,
                            wait as wait_resale, resale_screen, resale_position_review)
from .binance_telemetry import BinanceTelemetry, spot_worker as binance_spot_worker
from .lag_intelligence import BinanceKalshiLagTracker, wait as wait_binance_lag
from .depth_intelligence import (analyze_opportunities, execution_guidance,
                                  unavailable_opportunity, unavailable_execution)

ROOT = Path(__file__).parent
DEMO = os.environ.get('DEMO_MODE', '0') == '1'
AUTO_PAPER = os.environ.get('AUTO_PAPER', '1') == '1'
POLL_SECONDS = max(5, int(os.environ.get('POLL_SECONDS', '15')))
DATA_PATH = os.environ.get('DATA_PATH', str(ROOT.parent/'data'/'bot.sqlite3'))
ADMIN_TOKEN = os.environ.get('BOT_ADMIN_TOKEN','')
BRTI_LIVE_ENABLED = (not DEMO and os.environ.get('BRTI_LIVE_ENABLED','1') == '1')
BINANCE_INTELLIGENCE_ENABLED = (not DEMO and os.environ.get('BINANCE_INTELLIGENCE_ENABLED','1') == '1')
# Opt-in shadow grading ONLY: no voting, execution, or historical rewriting.
CANDLESTICK_SHADOW_GRADING_ENABLED = os.environ.get('CANDLESTICK_SHADOW_GRADING_ENABLED','0') == '1'
brti_tracker = BRTITracker(enabled=BRTI_LIVE_ENABLED)
binance_telemetry = BinanceTelemetry(enabled=BINANCE_INTELLIGENCE_ENABLED)
provider = DemoProvider() if DEMO else LiveProvider()
ledger = Ledger(DATA_PATH)
state_lock = threading.RLock()
movement_tracker = IntracontractTracker()
binance_lag_tracker = BinanceKalshiLagTracker()
market_flow_tracker = BTCFlowTracker()
contract_repricing_tracker = ContractRepricingModel()
state = {'mode':'DEMO' if DEMO else 'LIVE','last_attempt':None,'last_success':None,
         'market':None,'spot':None,'model':None,'engines':[],'scalp':None,'opportunity':None,'candles':[],
         'research_shadow':unavailable_research_shadow('No completed research observation yet'),
         'candlestick_context':unavailable_candle_context('Awaiting fresh completed BTC candles'),
         'candlestick_challenger':unavailable_candle_challenger('Awaiting independent ensemble and candle context'),
         'orderbook':unavailable_book(None,'No aggregated market depth yet'),
         'depth_opportunity':unavailable_opportunity('No independently evaluated depth yet'),
         'execution_intelligence':unavailable_execution('No independently evaluated depth yet'),
          'btc_signals':unavailable_signals('Awaiting fresh market inputs'),
          'trade_decision':execution_decision(None,None,None,None,None,time.time()),
          'intracontract':unavailable_timeline('Waiting for consecutive price snapshots'),
          'resale_setup':wait_resale('Waiting for observed intracontract moves'),
          'binance_intelligence':binance_telemetry.snapshot(),
          'binance_kalshi_delay':wait_binance_lag('Awaiting real Binance and Kalshi quotes'),
          'higher_timeframes':timeframes([],time.time()),
          'market_microstructure':{'available':False,'reason':'Awaiting genuine BTC exchange trade flow'},
          'contract_repricing':unavailable_contract_repricing('Waiting for observed quotes'),
         'errors':{},'paper_auto_enabled':AUTO_PAPER,'watch':None,'candle_quality':None,'status':'STARTING',
         'settlement':{'status':'NOT_CHECKED','last_attempt':None,'last_success':None,
                       'checked':0,'failed':0}}
shutdown = threading.Event()
# Failed settlement lookups are retained by ticker. A successful market poll cannot
# accidentally erase them, and a successful retry clears only that ticker's error.
settlement_failures = {}
last_grading_ticker = None  # round-robin cursor to prevent settlement queue starvation


def _error_message(exc):
    return f'{type(exc).__name__}: {str(exc)[:160]}'


def _refresh_status_locked():
    """Recompute operational status from the *combined* source and grading state.

    Called with state_lock held after each poll, grade, and worker failure.
    Synthetic DEMO is a mode label, not a blanket declaration of health.
    """
    if 'worker' in state['errors']:
        state['status'] = 'ERROR'
    elif state['errors']:
        state['status'] = 'DEGRADED'
    elif state['last_attempt'] is None:
        state['status'] = 'STARTING'
    elif (state['market'] is None or state['spot'] is None or
          not state['model'] or not state['model'].get('available') or
          len(state['candles']) < 31):
        state['status'] = 'DEGRADED'
    else:
        state['status'] = 'DEMO' if DEMO else 'LIVE'


def _view_locked(now):
    """Return a consistent read snapshot for both health and dashboard APIs.

    The worker may have stopped updating without raising an exception. In that
    case the last successful snapshot is NOT healthy indefinitely.
    """
    data = dict(state)
    data['errors'] = dict(state['errors'])
    data['settlement'] = dict(state['settlement'])
    data['live_briti'] = brti_tracker.snapshot()
    data['binance_intelligence'] = binance_telemetry.snapshot(now)
    attempted = state['last_attempt']
    data['heartbeat_age_seconds'] = None if attempted is None else max(0, round(now-attempted, 2))
    stale_limit = max(60, 3*POLL_SECONDS)
    if attempted is not None and now-attempted > stale_limit:
        data['errors']['worker_stale'] = f'Last market update is more than {stale_limit} seconds old'
    if data['status'] in ('LIVE','DEMO') and data['errors']:
        data['status'] = 'DEGRADED'
    data['ok'] = data['status'] in ('LIVE','DEMO') and not data['errors']
    if not data['ok']:
        # Previous opportunity quotes must not look actionable during an
        # outage even if they were calculated before the failure became known.
        data['opportunity'] = {'side':'WAIT','edge':None,'entry_price':None,
                               'reason':'System not healthy; paper opportunities paused'}
        data['depth_opportunity'] = unavailable_opportunity('System unhealthy; no depth-based entry advice')
        data['execution_intelligence'] = unavailable_execution('System unhealthy; no execution guidance')
        data['trade_decision'] = execution_decision(None,None,None,None,None,now)
        data['candlestick_context'] = unavailable_candle_context('Operational health degraded')
        data['candlestick_challenger'] = unavailable_candle_challenger('Operational health degraded')
        data['intracontract'] = unavailable_timeline('Operational health degraded')
        data['resale_setup'] = wait_resale('Operational health degraded')
        data['contract_repricing'] = unavailable_contract_repricing('Operational health degraded')
        data['binance_kalshi_delay'] = wait_binance_lag('Operational health degraded',data['binance_intelligence'])
    if 'worker_stale' in data['errors']:
        data['contract_repricing'] = unavailable_contract_repricing('Market worker stale')
        data['orderbook'] = unavailable_book(data['market'].get('ticker') if data['market'] else None,
                                               'Market worker stale; cached book invalid')
        data['research_shadow'] = unavailable_research_shadow('Market update worker is stale')
        # Preserve prior historical rows but never advertise a cached direction
        # as a current signal if the worker has stopped updating.
        data['model'] = {'available':False,'side':'WAIT','prob_above':None,
                         'prob_below':None,'reason':'Market update worker is stale'}
        data['engines'] = []
        data['opportunity'] = {'side':'WAIT','edge':None,'entry_price':None,
                               'reason':'Market updates stale; entries suspended'}
        data['scalp'] = {'side':'WAIT','entry':None,'stop':None,'target':None,
                         'reason':'Market updates stale; scalp suspended','atr':None}
    return data


def update_once(now=None):
    now = time.time() if now is None else now
    errors={}; market=None; spot=None; candles=[]
    try:
        market=provider.market(now)
        if market is not None and not DEMO:
            brti_tracker.observe_market(market)
        if market is None:
            errors['kalshi']='No active Kalshi BTC15M market available'
    except Exception as e:
        errors['kalshi']=_error_message(e)
    # Production forecasting is BRTI-FIRST, never Coinbase spot or candles.
    # Demo explicitly retains its own synthetic feed for offline acceptance.
    brti_now = (brti_tracker.snapshot(now_ms=int(now*1000))
                if not DEMO else None)
    if not DEMO:
        if not isinstance(brti_now,dict) or brti_now.get('status')!='STREAMING':
            errors['brti_stream']='Authenticated CF Benchmarks BRTI stream unavailable'
        else:
            spot = float(brti_now['latest_value_usd'])
            candles = brti_now.get('btc_1m_candles') or []
            if not math.isfinite(spot) or spot <= 0:
                spot = None
                errors['brti_stream']='Invalid authenticated CF Benchmarks BRTI index value'
            if len(candles)<31:
                errors['brti_candles']='Warming up real CF Benchmarks BRTI 1m history (need 31 completed minutes)'
    else:
        try:
            spot=provider.price()
            if spot is None or not isinstance(spot,(float,int)) or not math.isfinite(spot) or spot<=0:
                errors['demo_ticker']='Missing or invalid synthetic BTC spot'; spot=None
        except Exception as e:
            errors['demo_ticker']=_error_message(e)
        try:
            candles=provider.candles()
            if not isinstance(candles,list) or len(candles)<31:
                errors['demo_candles']='Fewer than 31 synthetic candles available'; candles=[]
            else:
                recent=candles[-61:]
                timestamps=[c['t'] for c in recent]
                if (any(not isinstance(t,(int,float)) or not math.isfinite(t) for t in timestamps)
                        or any(b-a != 60 for a,b in zip(timestamps,timestamps[1:]))):
                    errors['demo_candles']='Candles are missing, duplicated or not one-minute intervals'; candles=[]
                elif timestamps[-1] > now+60:
                    errors['demo_candles']='Candles timestamped in the future'; candles=[]
        except Exception as e:
            errors['demo_candles']=_error_message(e); candles=[]
    model={'available':False,'side':'WAIT','prob_above':None,'reason':'No active market or input data'}
    signals=unavailable_signals('Market/price/candles unavailable or invalid')
    trade_decision=execution_decision(None,None,None,None,None,now)
    scalp=scalp_signal(candles,spot)
    # Capture exchange trade BEFORE requesting Kalshi book: source ordering
    # is essential to detect candidate stale quotes, never inferred from
    # after-the-fact midpoint comparisons.
    binance_before_book=binance_telemetry.snapshot(time.time())
    book=unavailable_book(market.get('ticker') if market else None,
                          'No active market or validated full depth yet')
    if market is not None:
        book_reader=getattr(provider,'orderbook',None)
        if callable(book_reader):
            try:
                book=book_reader(market,now)
            except Exception as e:
                # Depth failure affects depth intelligence, not independent
                # forecast, ledger, settlement, or BTC spot scalping.
                book=unavailable_book(market['ticker'],_error_message(e))
        else:
            book=unavailable_book(market['ticker'],'Provider has no full-depth API')
    # BTC-only predictive features. Kalshi book/quotes remain in the
    # separate entry/exit/price-evaluation path BELOW the forecast.
    # No forecasting function sees Kalshi bids, asks, midpoints, walls or
    # book-derived price delay as predictive inputs.
    higher=timeframes([],now)
    if market is not None:
        if not DEMO:
            higher=timeframes((brti_now or {}).get('btc_5m_candles') or [],now)
        else:
            reader=getattr(provider,'timeframe_candles',None)
            if callable(reader):
                try:
                    higher=timeframes(reader(),time.time())
                except Exception:
                    higher=timeframes([],now)
    try:
        flow=market_flow_tracker.observe(binance=binance_before_book,
                                         now=time.time())
    except (TypeError,ValueError,ArithmeticError,KeyError,IndexError):
        flow={'available':False,'reason':'Flow feature calculation unavailable',
              'directional_components':{}}
    advanced_context={'timeframes':higher,'microstructure':flow}
    if not DEMO:
        advanced_context['brti']=brti_now
    depth_op=unavailable_opportunity('Independent forecast or depth not available')
    depth_exec=unavailable_execution('No verified live order-book opportunity')
    op={'side':'WAIT','edge':None,'entry_price':None,'reason':'No healthy market forecast'}
    watch=None
    # Experimental research candidate is a shadow output only. Its state never
    # enters the ensemble, opportunity evaluation, ledger, or paper decisions.
    research_shadow = unavailable_research_shadow('Market or source candles unavailable')
    if market is not None and not errors:
        try:
            research_shadow = shadow_forecast_from_candles(candles,
                {k:market[k] for k in ('ticker','target','seconds_left','close_ts')
                 if k in market}, now)
        except Exception:
            # An optional research probe cannot interrupt the production poll.
            research_shadow = unavailable_research_shadow('Research model calculation failed')
    # Nison-style market-pressure context uses ONLY fully completed 1m bars.
    # Optional feature failures never degrade the active trading safeguards.
    candle_context = unavailable_candle_context('Missing valid completed BTC candles')
    if candles and not errors:
        try:
            candle_context = read_candlestick_context(candles, now)
        except (TypeError, ValueError, ArithmeticError, KeyError, IndexError):
            candle_context = unavailable_candle_context('Candle feature computation unavailable')
    candle_challenger = unavailable_candle_challenger('No ensemble forecast yet')
    with state_lock:
        # Older unresolved settlement/ledger faults are independent of this
        # market poll. Preserve predictions, but suspend new paper decisions.
        persistent_faults = any(k in state['errors'] for k in
                                ('settlement','settlement_worker','ledger_read','ledger_connection'))
    if market:
        # Contract strike and expiration are valid prediction questions;
        # contract YES/NO QUOTES ARE NOT. Restrict model inputs at the caller.
        forecast_contract={k:market[k] for k in
                           ('ticker','target','seconds_left','close_ts')
                           if k in market}
        try:
            signals=derive_signals(forecast_contract,spot,candles,now,
                brti=brti_now,
                spot_received_at=None if not DEMO else getattr(provider,'price_received_at',None),
                spot_source_at=None if not DEMO else getattr(provider,'price_source_at',None))
        except (ArithmeticError,TypeError,ValueError,KeyError):
            signals=unavailable_signals('BTC feature calculation rejected invalid inputs')
            errors['btc_signals']='BTC feature calculation rejected invalid inputs'
        model=engine_pack(spot,forecast_contract,candles,signals=signals,
                          context=advanced_context,now=now)
        try:
            candle_challenger = derive_candlestick_challenger(candle_context,model)
        except (TypeError, ValueError, ArithmeticError, KeyError, IndexError):
            candle_challenger = unavailable_candle_challenger('Candle candidate computation unavailable')
        if not model.get('available') and not errors:
            errors['forecast']=model.get('reason','Model unavailable')
        if not errors and not persistent_faults:
            try:
                # The book has a *receipt* time after the initial quote/spot
                # reads; do not label genuine fresh depth as future-dated.
                depth_now=max(now,float(book.get('received_at') or now))
                depth_op=analyze_opportunities(model,market,book,depth_now,signals=signals)
                depth_exec=execution_guidance(depth_op,model,market,book,depth_now)
            except Exception as e:
                # Optional, non-executable execution intelligence cannot break
                # the original ledger or turn an unknown depth into BUY.
                depth_op=unavailable_opportunity('Depth analysis failed: '+_error_message(e))
                depth_exec=unavailable_execution('Depth analysis failed')
        if not errors and not persistent_faults:
            trade_decision=execution_decision(signals,model,market,book,depth_op,
                                      max(now,float(book.get('received_at') or now)))
        if not errors and model.get('available'):
            if not persistent_faults:
                op=execution_screen(model,market)
            else:
                op['reason']='Paper entries suspended while settlement or ledger health is degraded'
            # A poll is one consistent ledger event. If any later write fails,
            # none of this poll's observation, snapshots, watch, or paper entry
            # may survive. Ledger also serializes concurrent manual writes.
            with ledger.atomic_cycle():
                ledger.observed(market,model,spot,now)
                if CANDLESTICK_SHADOW_GRADING_ENABLED:
                    ledger.engine_snapshots(market,model,now,candle_challenger)
                else:
                    ledger.engine_snapshots(market,model,now)
                ledger.first_call(market,model,spot,now,hold_seconds=10,poll_gap=max(40,3*POLL_SECONDS))
                if AUTO_PAPER and op['side'] in ('YES','NO'):
                    try:
                        ledger.trade(market,op['side'],now,
                                     model['prob_above'] if op['side']=='YES' else model['prob_below'], 'AUTO_RESEARCH')
                    except ValueError:
                        pass
                watch=ledger.watch_info(market['ticker'])
    # Independent, read-only Binance-first detector using actual spot trades.
    # Public provider outages fail WAIT.
    if market and not errors and not persistent_faults and model.get('available'):
        try:
            binance_lag=binance_lag_tracker.observe(market,book,binance_before_book,
                model,max(now,float(book.get('received_at') or now)))
        except (ValueError,TypeError,ArithmeticError,KeyError):
            binance_lag_tracker.reset()
            binance_lag=wait_binance_lag('Malformed Binance/Kalshi market pair',binance_before_book)
    else:
        binance_lag_tracker.reset()
        binance_lag=wait_binance_lag('Missing healthy synchronized market inputs',binance_before_book)
    # Quote repricing belongs ONLY to the execution/valuation lane, after
    # independent BTC forecast and ledger writes. Never feed its result back
    # into engine_pack, BTC probability, or settlement model weights.
    contract_repricing=unavailable_contract_repricing('Awaiting healthy contract and quote')
    if market and not errors and not persistent_faults and model.get('available'):
        try:
            contract_repricing=contract_repricing_tracker.observe(
                market,book,model,signals,
                max(now,float(book.get('received_at') or now)),btc_flow=flow)
        except (KeyError,TypeError,ValueError,ArithmeticError,IndexError):
            contract_repricing=unavailable_contract_repricing('Quote repricing learner failed')
    else:
        contract_repricing_tracker.pending=None
    # Read-only intracontract intelligence, after transactional ledger writes.
    if market and not errors and not persistent_faults and model.get('available'):
        try:
            observed_at=max(now,float(book.get('received_at') or now))
            intracontract=movement_tracker.observe(market,book,signals,observed_at)
            resale_setup=resale_screen(market,book,signals,intracontract,observed_at)
        except (ValueError,TypeError,ArithmeticError,KeyError):
            movement_tracker.reset()
            intracontract=unavailable_timeline('Invalid quote-history observation')
            resale_setup=wait_resale('Invalid quote-history observation')
    else:
        movement_tracker.reset()
        intracontract=unavailable_timeline('No healthy market/forecast cycle')
        resale_setup=wait_resale('No healthy market/forecast cycle')
    if errors:
        # A missing poll must break the ten-second first-call confidence hold;
        # otherwise a short feed outage can be counted as sustained evidence.
        ledger.reset_watches()
    with state_lock:
        # Keep unresolved grading failures visible, even across good feed polls.
        for component in ('settlement','settlement_worker','ledger_read','ledger_connection'):
            if component in state['errors']:
                errors[component] = state['errors'][component]
        state.update({'last_attempt':now,
            'market':market,'spot':spot,'candles':candles[-75:], 'model':model,'scalp':scalp,
            'price_source':'SYNTHETIC_DEMO' if DEMO else 'CF_BENCHMARKS_BRTI',
            'opportunity':op,'engines':model.get('engines',[]),'errors':errors,'watch':watch,
             'research_shadow':research_shadow,
             'candlestick_context':candle_context,
             'candlestick_challenger':candle_challenger,
             'orderbook':book,'depth_opportunity':depth_op,
             'execution_intelligence':depth_exec,
             'btc_signals':signals,'trade_decision':trade_decision,
             'intracontract':intracontract,'resale_setup':resale_setup,
              'contract_repricing':contract_repricing,
             'binance_intelligence':binance_before_book,'binance_kalshi_delay':binance_lag,
             'higher_timeframes':higher,'market_microstructure':flow,
            'candle_quality':((brti_now or {}).get('candle_quality') if not DEMO
                              else getattr(provider,'candle_quality',None))})
        _refresh_status_locked()
        if state['status'] in ('LIVE','DEMO'):
            state['last_success'] = now
        return _view_locked(now)


def grade_once(settlement_provider=None):
    source = settlement_provider if settlement_provider is not None else provider
    global last_grading_ticker
    now=time.time()
    attempted=[]
    try:
        tickers=ledger.unresolved(50, after_ticker=last_grading_ticker)
        last_grading_ticker=tickers[-1] if tickers else None
    except Exception as e:
        # Even enumerating unresolved contracts can fail (for example, database
        # downtime). It is a grading failure, never an empty/healthy queue.
        with state_lock:
            settlement_failures['__ledger__'] = 'Cannot list unresolved contracts: ' + _error_message(e)
            _record_settlement_locked(now, attempted, pending=None)
        return
    with state_lock:
        settlement_failures.pop('__ledger__', None)
        if not tickers:
            settlement_failures.clear()
    for ticker in tickers:
        attempted.append(ticker)
        try:
            # The provider returns None while settlement is legitimately pending.
            # We never substitute the Coinbase spot result for an official label.
            result=source.settlement(ticker)
            if result is not None:
                if result not in ('yes','no'):
                    raise ValueError('Provider returned an invalid official result')
                ledger.grade(ticker,result,now)
        except Exception as e:
            with state_lock:
                settlement_failures[ticker] = _error_message(e)
        else:
            with state_lock:
                settlement_failures.pop(ticker,None)
    # One last database read distinguishes genuinely pending results from
    # contracts which have all been graded successfully in this batch.
    try:
        pending=bool(ledger.unresolved(1))
    except Exception as e:
        pending=None
        with state_lock:
            settlement_failures['__ledger__']='Cannot confirm remaining settlement queue: ' + _error_message(e)
    with state_lock:
        _record_settlement_locked(now, attempted, pending)


def _record_settlement_locked(now, attempted, pending):
    """Publish grading errors atomically without destroying feed/worker errors."""
    count=len(settlement_failures)
    if count:
        ticker,reason=next(iter(settlement_failures.items()))
        state['errors']['settlement'] = f'{count} settlement check(s) failed; {ticker}: {reason}'
    else:
        state['errors'].pop('settlement',None)
    previous_success=state['settlement']['last_success']
    if not count:
        previous_success=now
    state['settlement']={
        'status':'ERROR' if count else ('PENDING' if pending else ('CHECKED' if attempted else 'IDLE')),
        'last_attempt':now,'last_success':previous_success,
        'checked':len(attempted),'failed':count,
    }
    _refresh_status_locked()


def worker():
    """Market polling must not wait for slow official-settlement lookups."""
    while not shutdown.is_set():
        try:
            update_once()
        except Exception as e:
            with state_lock:
                state['status']='ERROR'; state['errors']['worker']=f'{type(e).__name__}: {str(e)[:200]}'
        shutdown.wait(POLL_SECONDS)


def grading_worker():
    """Grade on a separate worker and (in live mode) separate HTTP session.

    A settlement backlog may contain many slow API lookups; it cannot block
    the price/forecast loop. The ledger's RLock serializes database writes.
    """
    settlement_provider = LiveProvider() if isinstance(provider, LiveProvider) else provider
    try:
        while not shutdown.wait(4*POLL_SECONDS):
            try:
                grade_once(settlement_provider)
            except Exception as e:
                with state_lock:
                    state['errors']['settlement_worker']=_error_message(e)
                    _refresh_status_locked()
            else:
                with state_lock:
                    state['errors'].pop('settlement_worker',None)
                    _refresh_status_locked()
    finally:
        if settlement_provider is not provider:
            settlement_provider.session.close()


@asynccontextmanager
async def lifespan(_app):
    shutdown.clear()
    market_thread=threading.Thread(target=worker, name='research-data-worker',daemon=True)
    grading_thread=threading.Thread(target=grading_worker, name='research-settlement-worker',daemon=True)
    market_thread.start()
    grading_thread.start()
    brti_thread = None
    if BRTI_LIVE_ENABLED:
        brti_thread = threading.Thread(target=brti_reference_worker,
            args=(brti_tracker,shutdown),name='read-only-live-brti-worker',daemon=True)
        brti_thread.start()
    binance_threads=[]
    if BINANCE_INTELLIGENCE_ENABLED:
        for target,name in ((binance_spot_worker,'read-only-binance-spot-worker'),):
            thread=threading.Thread(target=target,args=(binance_telemetry,shutdown),name=name,daemon=True)
            thread.start()
            binance_threads.append(thread)
    yield
    shutdown.set()
    market_thread.join(timeout=3)
    grading_thread.join(timeout=3)
    if brti_thread is not None:
        brti_thread.join(timeout=3)
    for thread in binance_threads:
        thread.join(timeout=3)

app=FastAPI(title='AXIOM Multi-Engine BTC Research Bot',version='2.0.0',lifespan=lifespan, docs_url=None,redoc_url=None)

@app.get('/')
def index(): return FileResponse(ROOT/'static'/'index.html')

@app.get('/health')
def health():
    try:
        ledger.healthcheck()
    except Exception as e:
        ledger_error=_error_message(e)
    else:
        ledger_error=None
    with state_lock:
        if ledger_error:
            state['errors']['ledger_connection']=ledger_error
        else:
            state['errors'].pop('ledger_connection',None)
        _refresh_status_locked()
        snapshot=_view_locked(time.time())
    return JSONResponse({'ok':snapshot['ok'],'status':snapshot['status'],
        'mode':snapshot['mode'],'last_attempt':snapshot['last_attempt'],
        'last_success':snapshot['last_success'],
        'heartbeat_age_seconds':snapshot['heartbeat_age_seconds'],
        'errors':snapshot['errors'],'settlement':snapshot['settlement'],
        'live_briti':snapshot['live_briti'],
        'binance_intelligence':snapshot['binance_intelligence'],
        'binance_kalshi_delay':snapshot.get('binance_kalshi_delay')},
        status_code=200 if snapshot['ok'] else 503,headers={'Cache-Control':'no-store'})

@app.get('/api/state')
def get_state():
    now=time.time()
    try:
        ledger_rows=ledger.data()
        scores=ledger.engine_scores()
    except Exception as e:
        # Return an explicit, machine-readable outage instead of HTTP 500 with
        # an apparently healthy /health endpoint or fabricated empty history.
        with state_lock:
            state['errors']['ledger_read']=_error_message(e)
            _refresh_status_locked()
            d=_view_locked(now)
        d['execution_evidence']=examine_liquidity(d.get('orderbook'), d.get('market'),now)
        d['engine_scores']={'status':'UNAVAILABLE','samples':None,'scores':[]}
        d['ledger_available']=False
        d['manual_paper_available']=False
        d['server_time']=now
        return JSONResponse(d,status_code=503,headers={'Cache-Control':'no-store'})
    with state_lock:
        state['errors'].pop('ledger_read',None)
        _refresh_status_locked()
        d=_view_locked(now)
    d.update(ledger_rows)
    # Optional review of ONE paper contract, never a real Kalshi account.
    # The existing paper ledger represents one contract per row; user holdings
    # and real order/fill history are NOT available to AXIOM.
    d['paper_position_execution']=unavailable_execution('No open matching simulated position')
    d['resale_position_review']=wait_resale('No matching simulated position')
    active=d.get('market')
    if active and d.get('ok'):
        for trade in d.get('trades',[]):
            if trade.get('ticker')==active['ticker'] and trade.get('status')=='OPEN':
                try:
                    d['resale_position_review']=resale_position_review(trade,active,
                        d.get('orderbook'),d.get('btc_signals'),d.get('intracontract'),now)
                    d['paper_position_execution']=execution_guidance(
                        d.get('depth_opportunity'),d.get('model'),active,d.get('orderbook'),now,
                        position={'side':trade['side'],'contracts':1.0})
                except Exception:
                    d['resale_position_review']=wait_resale('Paper-position resale check unavailable')
                    d['paper_position_execution']=unavailable_execution('Paper position depth review unavailable')
                break
    d['execution_evidence']=examine_liquidity(d.get('orderbook'), d.get('market'),now)
    d['engine_scores']=scores
    d['ledger_available']=True
    d['server_time']=now
    # A token alone is not permission to record a position against stale or
    # broken market data. The UI and paper endpoint share the same readiness rule.
    d['manual_paper_available']=bool(ADMIN_TOKEN) and d['ok'] and bool(d.get('market'))
    d['disclaimer']='Experimental models and gross simulated trading only. Live forecast inputs are authentic CF Benchmarks BRTI; exchange-only signed trade flow is separately identified. BRTI has no traded volume. Kalshi aggregated depth is a participant-order snapshot; no real orders are placed.'
    return JSONResponse(d,headers={'Cache-Control':'no-store'})

class PaperRequest(BaseModel):
    side: str

@app.post('/api/paper')
def paper(req:PaperRequest, authorization:str|None=Header(default=None)):
    if not ADMIN_TOKEN: raise HTTPException(403,'Manual paper trading disabled; configure BOT_ADMIN_TOKEN')
    if authorization != f'Bearer {ADMIN_TOKEN}': raise HTTPException(401,'Incorrect admin token')
    with state_lock:
        snapshot=_view_locked(time.time())
        m=snapshot.get('market'); ts=snapshot.get('last_attempt')
    if (not snapshot['ok'] or not m or not ts or
            time.time()-ts > max(50,3*POLL_SECONDS)):
        raise HTTPException(409,'Market snapshot unhealthy, unavailable or stale')
    ask=m.get('yes_ask' if req.side.upper()=='YES' else 'no_ask')
    bid=m.get('yes_bid' if req.side.upper()=='YES' else 'no_bid')
    if req.side.upper() in ('YES','NO') and (ask is None or bid is None or ask < bid):
        raise HTTPException(409,'Invalid or crossed contract quote')
    if m['seconds_left'] < 45 or m['close_ts'] < time.time()+45:
        raise HTTPException(409,'Contract too close to close')
    try: entry=ledger.trade(m,req.side,time.time(),source='MANUAL_PAPER')
    except ValueError as e: raise HTTPException(409,str(e))
    return entry

@app.get('/api/export/{kind}')
def export(kind:str,authorization:str|None=Header(default=None)):
    if not ADMIN_TOKEN or authorization != f'Bearer {ADMIN_TOKEN}':
        raise HTTPException(401,'Export requires BOT_ADMIN_TOKEN')
    try: headers,rows=ledger.export(kind)
    except ValueError: raise HTTPException(404,'Unknown dataset')
    buf=io.StringIO(); w=csv.writer(buf); w.writerow(headers); w.writerows(rows)
    return Response(content=buf.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{kind}.csv"'})
