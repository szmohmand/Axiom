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
         'errors':{},'paper_auto_enabled':AUTO_PAPER,'watch':None,'status':'STARTING',
         'settlement':{'status':'NOT_CHECKED','last_attempt':None,'last_success':None,
                       'checked':0,'failed':0}}
shutdown = threading.Event()
# Failed settlement lookups are retained by ticker. A successful market poll cannot
# accidentally erase them, and a successful retry clears only that ticker's error.
settlement_failures = {}


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
        elif not DEMO and now-candles[-1]['t']>200:
            # Don't let stale Coinbase candles masquerade as fresh signals.
            errors['coinbase_candles']='Candles stale'; candles=[]
    except Exception as e:
        errors['coinbase_candles']=_error_message(e); candles=[]
    model={'available':False,'side':'WAIT','prob_above':None,'reason':'No active market or input data'}
    scalp=scalp_signal(candles,spot)
    op={'side':'WAIT','edge':None,'entry_price':None,'reason':'No healthy market forecast'}
    watch=None
    if market:
        model=engine_pack(spot,market,candles)
        if not model.get('available') and not errors:
            errors['forecast']=model.get('reason','Model unavailable')
        if not errors and model.get('available'):
            op=execution_screen(model,market)
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
    with state_lock:
        # Keep unresolved grading failures visible, even across good feed polls.
        if 'settlement' in state['errors']:
            errors['settlement'] = state['errors']['settlement']
        state.update({'last_attempt':now,
            'market':market,'spot':spot,'candles':candles[-70:], 'model':model,'scalp':scalp,
            'opportunity':op,'engines':model.get('engines',[]),'errors':errors,'watch':watch})
        _refresh_status_locked()
        if state['status'] in ('LIVE','DEMO'):
            state['last_success'] = now
        return _view_locked(now)


def grade_once():
    now=time.time()
    attempted=[]
    try:
        tickers=ledger.unresolved(50)
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
            result=provider.settlement(ticker)
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
    cycle=0
    while not shutdown.is_set():
        try:
            update_once(); cycle+=1
            if cycle%4==0: grade_once()
        except Exception as e:
            with state_lock:
                state['status']='ERROR'; state['errors']['worker']=f'{type(e).__name__}: {str(e)[:200]}'
        shutdown.wait(POLL_SECONDS)

@asynccontextmanager
async def lifespan(_app):
    shutdown.clear()
    thread=threading.Thread(target=worker, name='research-data-worker',daemon=True)
    thread.start()
    yield
    shutdown.set()
    thread.join(timeout=3)

app=FastAPI(title='AXIOM Multi-Engine BTC Research Bot',version='2.0.0',lifespan=lifespan, docs_url=None,redoc_url=None)

@app.get('/')
def index(): return FileResponse(ROOT/'static'/'index.html')

@app.get('/health')
def health():
    with state_lock:
        snapshot=_view_locked(time.time())
        return {'ok':snapshot['ok'],'status':snapshot['status'],
                'mode':snapshot['mode'],'last_attempt':snapshot['last_attempt'],
                'last_success':snapshot['last_success'],
                'heartbeat_age_seconds':snapshot['heartbeat_age_seconds'],
                'errors':snapshot['errors'],'settlement':snapshot['settlement']}

@app.get('/api/state')
def get_state():
    now=time.time()
    with state_lock:
        d=_view_locked(now)
    d.update(ledger.data())
    d['engine_scores']=ledger.engine_scores()
    d['server_time']=now
    d['manual_paper_available']=bool(ADMIN_TOKEN)
    d['disclaimer']='Experimental models and gross simulated trading only. Coinbase is NOT the BRTI settlement index.'
    return JSONResponse(d,headers={'Cache-Control':'no-store'})

class PaperRequest(BaseModel):
    side: str

@app.post('/api/paper')
def paper(req:PaperRequest, authorization:str|None=Header(default=None)):
    if not ADMIN_TOKEN: raise HTTPException(403,'Manual paper trading disabled; configure BOT_ADMIN_TOKEN')
    if authorization != f'Bearer {ADMIN_TOKEN}': raise HTTPException(401,'Incorrect admin token')
    with state_lock: m=state.get('market'); ts=state.get('last_attempt')
    if not m or not ts or time.time()-ts > max(50,3*POLL_SECONDS):
        raise HTTPException(409,'Live market snapshot unavailable or stale')
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
