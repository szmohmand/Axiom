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
from .storage import Ledger
from .settlement_research import shadow_forecast_from_candles, unavailable as unavailable_research_shadow

ROOT = Path(__file__).parent
DEMO = os.environ.get('DEMO_MODE', '0') == '1'
AUTO_PAPER = os.environ.get('AUTO_PAPER', '1') == '1'
POLL_SECONDS = max(5, int(os.environ.get('POLL_SECONDS', '15')))
DATA_PATH = os.environ.get('DATA_PATH', str(ROOT.parent/'data'/'bot.sqlite3'))
ADMIN_TOKEN = os.environ.get('BOT_ADMIN_TOKEN','')
provider = DemoProvider() if DEMO else LiveProvider()
ledger = Ledger(DATA_PATH)
state_lock = threading.RLock()
state = {'mode':'DEMO' if DEMO else 'LIVE','last_attempt':None,'last_success':None,
         'market':None,'spot':None,'model':None,'engines':[],'scalp':None,'opportunity':None,'candles':[],
         'research_shadow':unavailable_research_shadow('No completed research observation yet'),
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
    if 'worker_stale' in data['errors']:
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
        if market is None:
            errors['kalshi']='No active Kalshi BTC15M market available'
    except Exception as e:
        errors['kalshi']=_error_message(e)
    try:
        spot=provider.price()
        if spot is None or not isinstance(spot,(float,int)) or not math.isfinite(spot) or spot<=0:
            errors['coinbase_ticker']='Missing or invalid BTC spot price'; spot=None
    except Exception as e:
        errors['coinbase_ticker']=_error_message(e)
    try:
        candles=provider.candles()
        if not isinstance(candles,list) or len(candles)<31:
            errors['coinbase_candles']='Fewer than 31 candles available'; candles=[]
        else:
            # Returns and ATR treat every candle as one minute. Detect missing
            # intervals, duplicates and impossible future data before forecasting.
            recent=candles[-61:]
            timestamps=[c['t'] for c in recent]
            if (any(not isinstance(t,(int,float)) or not math.isfinite(t) for t in timestamps)
                    or any(b-a != 60 for a,b in zip(timestamps,timestamps[1:]))):
                errors['coinbase_candles']='Candles are missing, duplicated or not one-minute intervals'; candles=[]
            elif timestamps[-1] > now+60:
                errors['coinbase_candles']='Candles timestamped in the future'; candles=[]
            elif not DEMO and now-timestamps[-1]>200:
                errors['coinbase_candles']='Candles stale'; candles=[]
    except Exception as e:
        errors['coinbase_candles']=_error_message(e); candles=[]
    model={'available':False,'side':'WAIT','prob_above':None,'reason':'No active market or input data'}
    scalp=scalp_signal(candles,spot)
    op={'side':'WAIT','edge':None,'entry_price':None,'reason':'No healthy market forecast'}
    watch=None
    # Experimental research candidate is a shadow output only. Its state never
    # enters the ensemble, opportunity evaluation, ledger, or paper decisions.
    research_shadow = unavailable_research_shadow('Market or source candles unavailable')
    if market is not None and not errors:
        try:
            research_shadow = shadow_forecast_from_candles(candles, market, now)
        except Exception:
            # An optional research probe cannot interrupt the production poll.
            research_shadow = unavailable_research_shadow('Research model calculation failed')
    with state_lock:
        # Older unresolved settlement/ledger faults are independent of this
        # market poll. Preserve predictions, but suspend new paper decisions.
        persistent_faults = any(k in state['errors'] for k in
                                ('settlement','settlement_worker','ledger_read','ledger_connection'))
    if market:
        model=engine_pack(spot,market,candles)
        if not model.get('available') and not errors:
            errors['forecast']=model.get('reason','Model unavailable')
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
                ledger.engine_snapshots(market,model,now)
                ledger.first_call(market,model,spot,now,hold_seconds=10,poll_gap=max(40,3*POLL_SECONDS))
                if AUTO_PAPER and op['side'] in ('YES','NO'):
                    try:
                        ledger.trade(market,op['side'],now,
                                     model['prob_above'] if op['side']=='YES' else model['prob_below'], 'AUTO_RESEARCH')
                    except ValueError:
                        pass
                watch=ledger.watch_info(market['ticker'])
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
            'market':market,'spot':spot,'candles':candles[-70:], 'model':model,'scalp':scalp,
            'opportunity':op,'engines':model.get('engines',[]),'errors':errors,'watch':watch,
             'research_shadow':research_shadow,
            'candle_quality':({'status':'UNAVAILABLE','reason':errors['coinbase_candles']}
                              if 'coinbase_candles' in errors else getattr(provider,'candle_quality',None))})
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
    yield
    shutdown.set()
    market_thread.join(timeout=3)
    grading_thread.join(timeout=3)

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
        'errors':snapshot['errors'],'settlement':snapshot['settlement']},
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
    d['engine_scores']=scores
    d['ledger_available']=True
    d['server_time']=now
    # A token alone is not permission to record a position against stale or
    # broken market data. The UI and paper endpoint share the same readiness rule.
    d['manual_paper_available']=bool(ADMIN_TOKEN) and d['ok'] and bool(d.get('market'))
    d['disclaimer']='Experimental models and gross simulated trading only. Coinbase is NOT the BRTI settlement index.'
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
