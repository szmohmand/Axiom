"""Build the explicit daily collection plan, preserving earlier verified archives."""
import collections,csv,datetime as dt,gzip,json,os,pathlib,sys
from research.historical_180 import BEGIN,END,iter_jsonl,write_json
root=pathlib.Path(sys.argv[1]);seed=pathlib.Path(sys.argv[2]);reused=pathlib.Path(sys.argv[3]);thirty=os.getenv('REUSE_THIRTY')=='true'
index={m['ticker']:m for m in iter_jsonl(root/'contracts_180day_original_fields.jsonl.gz')}
reuse={}
def quote_counts(path):
    counts=collections.Counter()
    with gzip.open(path,'rt') as f:
        for row in csv.DictReader(f):
            if row['ticker'] in index:counts[index[row['ticker']]['open_time'][:10]]+=1
    return dict(counts)
reuse['august_quote_rows']=quote_counts(seed/'KALSHI/KXBTC15M_actual_bid_ask_trade_1min_OHLC_30d.csv.gz')
reuse['august_quotes_artifact']='https://github.com/szmohmand/Axiom/actions/runs/43805271303/artifacts/14198141445'
if thirty:
    reuse['thirty_day_quote_rows']=quote_counts(reused/'KALSHI/KXBTC15M_actual_bid_ask_trade_1min_OHLC_30d.csv.gz')
    p=reused/'AUDIT/KALSHI_30DAY_MANIFEST.json';man=json.loads(p.read_text());reuse['original_30day_manifest']=man
    if man['executed_trade_tick_subset'].get('errors_by_ticker'):reuse['reuse_two_trade_days']=False
    else:reuse['reuse_two_trade_days']=True
else:reuse['reuse_two_trade_days']=False
plan=[]
for n in range((END-BEGIN).days):
    day=(BEGIN+dt.timedelta(days=n)).isoformat()
    q=day not in reuse['august_quote_rows'] and day not in reuse.get('thirty_day_quote_rows',{})
    t=not (reuse['reuse_two_trade_days'] and day in ('2026-11-13','2026-11-14'))
    if q or t:plan.append({'day':day,'quotes':q,'trades':t})
write_json(root/'REUSE_MANIFEST.json',reuse);write_json(root/'DAY_PLAN.json',plan)
print(json.dumps(plan,separators=(',',':')))
