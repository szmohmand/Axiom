"""Live Kalshi CF Benchmarks BRTI observation: read-only, as-received, non-voting.

Two authenticated channels: cfbenchmarks_value (1Hz and published rolling /
quarter-hour reference averages) and cfbenchmarks_value_5hz (raw up-to-5Hz ticks).
Historical REST is separate and NEVER represented as live observation.
"""
from __future__ import annotations
from collections import deque
from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
import threading
import time

WS_URL = 'wss://external-api-ws.kalshi.com/trade-api/ws/v2'
WS_PATH = '/trade-api/ws/v2'
CHANNELS = ('cfbenchmarks_value', 'cfbenchmarks_value_5hz')


def _price(v):
    if v is None or isinstance(v, bool): return None
    try: x=Decimal(str(v))
    except (ValueError, TypeError, InvalidOperation): return None
    if not x.is_finite() or not (Decimal('100') < x < Decimal('100000000')): return None
    return float(x)


def _milliseconds(v):
    if v is None or isinstance(v, bool): return None
    try: n=int(v)
    except (ValueError, TypeError, OverflowError): return None
    return n if 1_600_000_000_000 <= n < 10_000_000_000_000 else None


def _average(node):
    if not isinstance(node, dict): return None
    p=_price(node.get('value')); count=node.get('window_size')
    a=_milliseconds(node.get('window_start_ts_ms'))
    b=_milliseconds(node.get('window_end_ts_exclusive'))
    if (p is None or isinstance(count,bool) or not isinstance(count,int)
            or not (1<=count<=300) or a is None or b is None or b<=a or b-a>120000):
        return None
    return {'value_usd':p,'window_size':count,'window_start_ts_ms':a,
            'window_end_ts_exclusive':b}


class BRTIObserver:
    """Thread-safe bounded in-memory BRTI with optional sanitized append-only trace."""
    def __init__(self, observation_path=None):
        self.lock=threading.RLock()
        self.status='NOT_CONNECTED'
        self.reason='No authenticated live BRTI observation yet'
        self.connected=False
        self.by_channel={}
        self.stats={'accepted_1hz':0,'accepted_5hz':0,'rejected':0,
                    'duplicate_or_reversed':0,'reconnects':0}
        self.recent=deque(maxlen=6000)
        self.path=Path(observation_path) if observation_path else None

    def mark(self,status,reason):
        # REASON IS A CONSTANT, NEVER THE EXCEPTION OR A SECRET.
        with self.lock:
            self.status=status; self.connected=status=='CONNECTED'
            self.reason=reason
            if status=='CONNECTED': self.stats['reconnects']+=1

    def _append(self, record):
        if self.path is None: return
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            line=(json.dumps(record,allow_nan=False,separators=(',',':'))+'\n').encode()
            fd=os.open(str(self.path),os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
            try: os.write(fd,line)
            finally: os.close(fd)
        except OSError:
            self.reason='Trace write failed; live observation not persistently archived'

    def ingest(self,frame,received_at=None):
        now=time.time() if received_at is None else float(received_at)
        if not isinstance(frame,dict) or frame.get('type') not in CHANNELS:
            return False
        channel=frame['type']; msg=frame.get('msg')
        if not isinstance(msg,dict) or msg.get('index_id')!='BRTI':
            with self.lock: self.stats['rejected']+=1
            return False
        if channel=='cfbenchmarks_value':
            try: raw=json.loads(msg.get('data') or '')
            except (ValueError,TypeError): raw=None
            if not isinstance(raw,dict) or raw.get('id')!='BRTI':
                with self.lock: self.stats['rejected']+=1
                return False
            source_ms=_milliseconds(raw.get('time'))
            value=_price(raw.get('value'))
            average=_average(msg.get('avg_60s_data'))
            closing=_average(msg.get('last_60s_windowed_average_15min'))
        else:
            source_ms=_milliseconds(msg.get('source_ts_ms'))
            value=_price(msg.get('value_usd'))
            average=closing=None
        exchange_ms=_milliseconds(msg.get('received_at'))
        if (source_ms is None or value is None or exchange_ms is None
                or not math.isfinite(now) or source_ms/1000>now+3
                or exchange_ms/1000>now+3):
            with self.lock: self.stats['rejected']+=1
            return False
        rec={'channel':'1hz' if channel==CHANNELS[0] else '5hz',
             'index_id':'BRTI','source_ts_ms':source_ms,
             'kalshi_received_at_ms':exchange_ms,
             'local_received_at':now,'value_usd':value,
             'avg_60s':average,'quarter_hour_closing_average':closing}
        with self.lock:
            prev=self.by_channel.get(channel)
            if prev is not None and source_ms<=prev['source_ts_ms']:
                self.stats['duplicate_or_reversed']+=1
                return False
            self.by_channel[channel]=rec
            self.recent.append(rec)
            self.stats['accepted_1hz' if rec['channel']=='1hz' else 'accepted_5hz']+=1
            self.status='STREAMING'
            self.connected=True
            self.reason='Authenticated as-received BRTI (not a verified final settlement)'
            self._append(rec)
        return True

    def snapshot(self,market=None,now=None):
        now=time.time() if now is None else now
        with self.lock:
            one=self.by_channel.get(CHANNELS[0])
            fast=self.by_channel.get(CHANNELS[1])
            tick=max((x for x in (one,fast) if x is not None),
                key=lambda x:x['local_received_at'],default=None)
            age=None if tick is None else max(0.,round(now-tick['local_received_at'],3))
            fresh=bool(tick and self.connected and self.status=='STREAMING'
                and age<=10 and now-tick['source_ts_ms']/1000<=20)
            status=('STALE' if tick and not fresh else self.status)
            close=market.get('close_ts') if isinstance(market,dict) else None
            target=_price(market.get('target')) if isinstance(market,dict) else None
            delta=round(tick['value_usd']-target,4) if fresh and target is not None else None
            final=one['quarter_hour_closing_average'] if one else None
            if (final and (not isinstance(close,(int,float)) or
                    abs(final['window_end_ts_exclusive']/1000-close)>60)):
                final=None
            return {
                'status':status,'source':'KALSHI_CF_BENCHMARKS_AUTH_WS',
                'configured':status not in ('NOT_CONFIGURED','DISABLED'),'connected':self.connected,
                'fresh':fresh,'last_sample_age_seconds':age,
                'current_value_usd':tick['value_usd'] if fresh else None,
                'latest_1hz':dict(one) if one else None,
                'latest_5hz':dict(fast) if fast else None,
                'source_timestamp_ms':tick['source_ts_ms'] if tick else None,
                'provider_received_at_ms':tick['kalshi_received_at_ms'] if tick else None,
                'local_received_at':tick['local_received_at'] if tick else None,
                'published_trailing_60s':one['avg_60s'] if one else None,
                'progressive_close_window':final if fresh else None,
                'observed_distance_to_published_strike_usd':delta,
                'verified_strike_publication_time':False,
                'verified_final_settlement':False,
                'votes_in_forecast':False,'triggers_orders':False,
                'source_warnings':self.reason if status!='STREAMING' else None,
                'counts':dict(self.stats)}


def run_stream(observer,stop,*,key_id,private_key):
    """Read-only authenticated market-data channel. Never places an order."""
    if not key_id or not private_key:
        observer.mark('NOT_CONFIGURED','Kalshi WebSocket key ID and PEM not configured')
        return
    from research.verify_official_brti_live import _signed_headers
    import websocket
    backoff=2
    while not stop.is_set():
        ws=None
        try:
            observer.mark('CONNECTING','Signing read-only Kalshi BRTI WebSocket')
            headers=_signed_headers(key_id,private_key,WS_PATH)
            ws=websocket.create_connection(WS_URL,
                header=[f'{k}: {v}' for k,v in headers.items()],
                timeout=10,enable_multithread=True)
            ws.settimeout(2)
            observer.mark('CONNECTED','Awaiting BRTI ticks')
            for i,channel in enumerate(CHANNELS,1):
                ws.send(json.dumps({'id':i,'cmd':'subscribe',
                    'params':{'channels':[channel],'index_ids':['BRTI']}}))
            backoff=2
            while not stop.is_set():
                try: raw=ws.recv()
                except websocket.WebSocketTimeoutException: continue
                if not raw: raise ConnectionError('Socket closed')
                if len(raw)>100000:
                    observer.mark('SOURCE_ERROR','WebSocket frame exceeds limit')
                    continue
                try: frame=json.loads(raw)
                except ValueError:
                    observer.mark('SOURCE_ERROR','Malformed Kalshi WebSocket message')
                    continue
                if isinstance(frame,dict) and frame.get('type')=='error':
                    observer.mark('SOURCE_ERROR','Kalshi BRTI subscription rejected')
                    continue
                observer.ingest(frame)
        except websocket.WebSocketBadStatusException as exc:
            if exc.status_code in (401,403):
                observer.mark('AUTH_REJECTED','WebSocket authentication or BRTI entitlement denied')
                return
            observer.mark('SOURCE_ERROR','Kalshi WebSocket handshake unavailable')
        except (websocket.WebSocketException,OSError,ValueError,TypeError,
                ImportError,ConnectionError):
            observer.mark('SOURCE_ERROR','BRTI stream disconnected or signer unavailable')
        finally:
            if ws is not None:
                try: ws.close()
                except OSError: pass
        if stop.wait(backoff): break
        backoff=min(60,backoff*2)
    observer.mark('STOPPED','BRTI observer stopped cleanly')
