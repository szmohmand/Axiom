"""Single-process web server + live background research/paper-trading worker."""
from __future__ import annotations
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import csv
import io
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
         'errors':{},'paper_auto_enabled':AUTO_PAPER,'watch':None,'status':'STARTING'}
shutdown = threading.Event()

def update_once(now=None):
    now = time.time() if now is None else now
    errors={}; market=None; spot=None; candles=[]
    try: market=provider.market(now)
    except Exception as e: errors['kalshi']=f'{type(e).__name__}: {str(e)[:160]}'
    try: spot=provider.price()
    except Exception as e: errors['coinbase_ticker']=f'{type(e).__name__}: {str(e)[:160]}'
    try:
        candles=provider.candles()
        # Don't let stale Coinbase candles produce fresh forecasts.
        if candles and not DEMO and now-candles[-1]['t']>200:
            errors['coinbase_candles']='Candles stale'; candles=[]
    except Exception as e: errors['coinbase_candles']=f'{type(e).__name__}: {str(e)[:160]}'
    model={'available':False,'side':'WAIT','prob_above':None,'reason':'No active market or input data'}
    scalp=scalp_signal(candles,spot)
    op={'side':'WAIT','edge':None,'entry_price':None,'reason':'No live forecast'}
    watch=None
    if market:
        model=engine_pack(spot,market,candles)
        op=execution_screen(model,market)
        if not errors and spot is not None and model.get('available'):
            ledger.observed(market,model,spot,now)
            ledger.engine_snapshots(market,model,now)
            ledger.first_call(market,model,spot,now,hold_seconds=10,poll_gap=max(40,3*POLL_SECONDS))
            if AUTO_PAPER and op['side'] in ('YES','NO'):
                try:
                    ledger.trade(market,op['side'],now,
                                 model['prob_above'] if op['side']=='YES' else model['prob_below'], 'AUTO_RESEARCH')
                except ValueError: pass
            watch=ledger.watch_info(market['ticker'])
    with state_lock:
        state.update({'last_attempt':now, 'last_success':now if not errors and market and spot is not None else state['last_success'],
          'status': 'DEMO' if DEMO else ('LIVE' if not errors and market and spot is not None else 'DEGRADED'),
          'market':market,'spot':spot,'candles':candles[-70:], 'model':model,'scalp':scalp,
          'opportunity':op,'engines':model.get('engines',[]),'errors':errors,'watch':watch})
    return state.copy()

def grade_once():
    now=time.time()
    for ticker in ledger.unresolved(50):
        # Don't mark freshly open markets as settled; live provider guards on status.
        try:
            result=provider.settlement(ticker)
            if result: ledger.grade(ticker,result,now)
        except Exception: pass

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
        return {'ok':state['status'] in ('LIVE','DEMO'),'status':state['status'],
                'mode':state['mode'],'last_attempt':state['last_attempt'],'errors':state['errors']}

@app.get('/api/state')
def get_state():
    with state_lock: d=dict(state)
    d.update(ledger.data())
    d['engine_scores']=ledger.engine_scores()
    d['server_time']=time.time()
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
