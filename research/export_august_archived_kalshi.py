import sys,datetime as dt,pathlib,json,gzip,hashlib
from research import export_kalshi_30day as K
from research import export_shared_historical as S
K.BEGIN=dt.datetime(2026,8,6,tzinfo=dt.timezone.utc);K.END=dt.datetime(2026,8,13,tzinfo=dt.timezone.utc)
K.LO=int(K.BEGIN.timestamp());K.HI=int(K.END.timestamp());K.ROOT=pathlib.Path('august_KALSHI');K.OUT=K.ROOT/'KALSHI';K.ROOT.mkdir(exist_ok=True)
rawdir=K.ROOT/'ORIGINAL_RESPONSES';rawdir.mkdir(exist_ok=True);logs=[];old=S.get

def capture(url,headers=None,cap=25000000):
 assert headers is None
 started=dt.datetime.now(dt.timezone.utc).isoformat();raw=old(url,None,cap)
 name=f'response_{len(logs):04d}.json.gz'
 with gzip.open(rawdir/name,'wb') as f:f.write(raw)
 logs.append(dict(file=name,url=url,retrieved_utc=dt.datetime.now(dt.timezone.utc).isoformat(),request_started_utc=started,original_sha256=hashlib.sha256(raw).hexdigest()))
 (rawdir/'retrieval_manifest.json').write_text(json.dumps(logs,indent=2))
 return raw
S.get=capture
original_json=K.json_get

def historical_json(path,params=None,auth=None):
 if path=='/markets':
  allmarkets=[];cursor=None;seen=set()
  for page in range(30):
   q={'series_ticker':'KXBTC15M','limit':1000}
   if cursor:q['cursor']=cursor
   obj=original_json('/historical/markets',q)
   markets=obj.get('markets',[]);allmarkets.extend(markets)
   cursor=obj.get('cursor')
   print('HISTORICAL_TERMS_PAGE',page,len(markets),flush=True)
   # No date filter is documented for historical markets: preserve all pages.
   if not cursor:break
   if cursor in seen:raise ValueError('Repeated archived cursor')
   seen.add(cursor)
  else:raise ValueError('Historical pagination limit')
  return {'markets':allmarkets}
 if path=='/markets/candlesticks':
  blocks=[]
  for ticker in params['market_tickers'].split(','):
   obj=original_json('/historical/markets/'+ticker+'/candlesticks',{k:v for k,v in params.items() if k!='market_tickers'})
   blocks.append({'market_ticker':ticker,'candlesticks':obj.get('candlesticks',[])})
  return {'markets':blocks}
 return original_json(path,params,auth)
K.json_get=historical_json
try:
 markets,terms=K.fetch_terms();candles=K.fetch_candles(markets)
 terms['expected_30_days_96_windows_per_day']=672;terms['missing_or_non15min_starts']=672-len(markets)
 report=dict(scope=['2026-08-06','2026-08-12'],terms=terms,candles=candles,limitations=['Existing output filenames contain 30d but this invocation covers seven days only','No transactions or depth collected by this invocation','Raw JSON response bytes retained separately','Strike first-publication time unverified'])
 (K.ROOT/'AUGUST_MANIFEST.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
except Exception as e:
 (K.ROOT/'FAILURE.json').write_text(json.dumps(dict(error_type=type(e).__name__,message=str(e),requests_preserved=len(logs))));raise
