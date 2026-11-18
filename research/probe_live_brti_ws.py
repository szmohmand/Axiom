"""Time-bounded REAL authenticated BRTI WebSocket capability/evidence probe.

No orders, portfolio, wallet, credentials, signatures, or raw WS frames are
written to artifacts. Captured as-received index events are NOT reconstructed
historic observations or evidence of a profitable forecast.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import threading
import time
from app.live_brti import BRTIObserver,run_stream

def main():
    duration=min(90,max(10,int(os.getenv('BRTI_PROBE_SECONDS','45'))))
    path=os.getenv('BRTI_PROBE_EVIDENCE_PATH','brti-probe-evidence.json')
    key=os.getenv('KALSHI_API_KEY_ID','').strip()
    pem=os.getenv('KALSHI_PRIVATE_KEY_PEM','')
    stop=threading.Event()
    observer=BRTIObserver()
    worker=threading.Thread(target=run_stream,args=(observer,stop),
                            kwargs={'key_id':key,'private_key':pem},daemon=True)
    started=time.time()
    worker.start()
    while time.time()-started < duration:
        with observer.lock:
            counts=dict(observer.stats)
            status=observer.status
        if (counts['accepted_1hz']>=4 and counts['accepted_5hz']>=4
                and status=='STREAMING'):
            break
        if status in ('AUTH_REJECTED','NOT_CONFIGURED'):
            break
        time.sleep(.5)
    read=observer.snapshot(now=time.time())
    stop.set()
    worker.join(timeout=5)
    result={'kind':'authentic_kalshi_brti_websocket_asof_probe',
            'status':'PASS' if (read['counts']['accepted_1hz']>=4 and
                                read['counts']['accepted_5hz']>=4) else 'NOT_VERIFIED',
            '1hz_ticks_received':read['counts']['accepted_1hz'],
            '5hz_ticks_received':read['counts']['accepted_5hz'],
            'last_1hz_event_ms':(read.get('latest_1hz') or {}).get('source_ts_ms'),
            'last_5hz_event_ms':(read.get('latest_5hz') or {}).get('source_ts_ms'),
            'last_1hz_kalshi_receipt_ms':(read.get('latest_1hz') or {}).get('kalshi_received_at_ms'),
            'last_5hz_local_receipt':(read.get('latest_5hz') or {}).get('local_received_at'),
            'elapsed_seconds':round(time.time()-started,2),
            'connection_status_before_stop':read['status'],
            'outcome_verified':False,'predictive_alpha_verified':False,
            'read_only':True,'orders_sent':0,'raw_frames_saved':False,
            'credential_values_in_artifact':False}
    Path(path).write_text(json.dumps(result,sort_keys=True,indent=2))
    print('LIVE_BRTI_WS_PROBE '+json.dumps(result,sort_keys=True),flush=True)
    return 0 if result['status']=='PASS' else 2

if __name__=='__main__':
    raise SystemExit(main())
