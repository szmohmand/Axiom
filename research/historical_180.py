"""Read-only public KXBTC15M collection with immutable response caching.

No credentials, account endpoints, order submissions or live orderbook calls.
Raw JSON is preserved independently from normalized research tables.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,decimal,gzip,hashlib,json,pathlib,time,urllib.parse,shutil,os
from collections import Counter
from research.export_shared_historical import API,get

GZIP_LEVEL=int(os.environ.get("RESEARCH_GZIP_LEVEL","4"))
UTC=dt.timezone.utc
BEGIN=dt.date(2026,5,20)
END=dt.date(2026,11,16)
ALLOWED=('/historical/markets','/historical/trades','/historical/cutoff',
         '/markets','/series/KXBTC15M')

def stamp():return dt.datetime.now(UTC).isoformat()
def sec(value):
    if isinstance(value,(int,float)):return int(value)
    return int(dt.datetime.fromisoformat(value.replace('Z','+00:00')).timestamp())
def digest(path):
    with open(path,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,indent=2)+'\n');temp.replace(path)
def iter_jsonl(path):
    with gzip.open(path,'rt') as f:
        for line in f:
            if line.strip():yield json.loads(line)
def write_jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(path,'wt',compresslevel=GZIP_LEVEL) as f:
        for row in rows:f.write(json.dumps(row,separators=(',',':'))+'\n')

class PublicSource:
    def __init__(self,root,delay=1.0,getter=None,cache_roots=()):
        self.root=pathlib.Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.delay=delay;self.last=0.0;self.network_requests=0;self.cache_hits=0
        self.getter=getter or get;self.cache_roots=[pathlib.Path(p) for p in cache_roots]
    def fetch(self,path,params=None):
        if not any(path==p or path.startswith(p+'/') for p in ALLOWED):
            raise ValueError('Endpoint outside authorized public research scope')
        url=API+path+('?' + urllib.parse.urlencode(sorted(params.items())) if params else '')
        key=hashlib.sha256(url.encode()).hexdigest()
        data=self.root/(key+'.json.gz');meta=self.root/(key+'.provenance.json')
        if not (data.exists() and meta.exists()):
            for prior in self.cache_roots:
                old_data=prior/data.name;old_meta=prior/meta.name
                if old_data.exists() and old_meta.exists():
                    info=json.loads(old_meta.read_text());raw=gzip.decompress(old_data.read_bytes())
                    if info['url']!=url or hashlib.sha256(raw).hexdigest()!=info['original_sha256']:
                        raise ValueError('Imported source response failed integrity check')
                    shutil.copyfile(old_data,data);shutil.copyfile(old_meta,meta);break
        if data.exists() and meta.exists():
            info=json.loads(meta.read_text());raw=gzip.decompress(data.read_bytes())
            if info['url']!=url or hashlib.sha256(raw).hexdigest()!=info['original_sha256']:
                raise ValueError('Cached source response failed integrity check')
            self.cache_hits+=1
        else:
            time.sleep(max(0,self.delay-(time.monotonic()-self.last)))
            started=stamp();self.last=time.monotonic();raw=self.getter(url,cap=30_000_000)
            with gzip.open(data,'wb',compresslevel=GZIP_LEVEL) as f:f.write(raw)
            info={'url':url,'request_started_utc':started,'retrieval_completed_utc':stamp(),
                  'original_sha256':hashlib.sha256(raw).hexdigest(),'original_bytes':len(raw)}
            write_json(meta,info);self.network_requests+=1
        obj=json.loads(raw)
        if not isinstance(obj,dict):raise ValueError('Expected official JSON envelope')
        return obj,{'response_file':str(data),'provenance_file':str(meta),**info}


def paginated(source,path,params,key):
    cursor=None;seen=set()
    for _ in range(10000):
        q=dict(params)
        if cursor:q['cursor']=cursor
        obj,provenance=source.fetch(path,q)
        rows=obj.get(key)
        if not isinstance(rows,list):raise ValueError('Invalid source page')
        yield rows,provenance
        cursor=obj.get('cursor')
        if not cursor:return
        if cursor in seen:raise ValueError('Repeated pagination cursor')
        seen.add(cursor)
    raise ValueError('Pagination safety boundary reached; checkpoint retained')


def build_index(root,seed):
    root=pathlib.Path(root);source=PublicSource(root/'ORIGINAL_RESPONSES')
    lo=sec(BEGIN.isoformat()+'T00:00:00Z');hi=sec(END.isoformat()+'T00:00:00Z')
    markets={};references=[];source_duplicates=0
    def accept(rows,provenance):
        nonlocal source_duplicates
        for m in rows:
            ticker=m.get('ticker','')
            if not ticker.startswith('KXBTC15M-'):continue
            try:start=sec(m['open_time']);sec(m['close_time'])
            except (KeyError,ValueError,TypeError):continue
            if not lo<=start<hi:continue
            if ticker in markets:
                source_duplicates+=1
                if markets[ticker]!=m:
                    references.append({'ticker':ticker,'revision_or_source_difference':True,
                                       'prior_record':markets[ticker],'new_record':m,'source':provenance})
            markets[ticker]=m
            references.append({'ticker':ticker,'source':provenance})
    seed=pathlib.Path(seed)
    seed_manifest=seed/'ORIGINAL_RESPONSES/retrieval_manifest.json'
    if seed_manifest.exists():
        for record in json.loads(seed_manifest.read_text()):
            p=seed/'ORIGINAL_RESPONSES'/record['file']
            raw=gzip.decompress(p.read_bytes())
            if hashlib.sha256(raw).hexdigest()!=record['original_sha256']:raise ValueError('Seed source hash mismatch')
            obj=json.loads(raw)
            if isinstance(obj.get('markets'),list):
                target=root/'SEED_ORIGINAL_RESPONSES'/p.name;target.parent.mkdir(exist_ok=True)
                shutil.copyfile(p,target)
                accept(obj['markets'],{**record,'preserved_seed_response':str(target)})
    else:
        for rows,provenance in paginated(source,'/historical/markets',{'series_ticker':'KXBTC15M','limit':1000},'markets'):
            accept(rows,provenance)
    for rows,provenance in paginated(source,'/markets',{'series_ticker':'KXBTC15M','min_close_ts':lo+1,'max_close_ts':hi+1,'limit':1000},'markets'):
        accept(rows,provenance)
    ordered=sorted(markets.values(),key=lambda m:(sec(m['open_time']),m['ticker']))
    write_jsonl(root/'contracts_180day_original_fields.jsonl.gz',ordered)
    write_jsonl(root/'contracts_source_cross_reference.jsonl.gz',references)
    days={};missing=[]
    for n in range(180):
        day=BEGIN+dt.timedelta(days=n);daylo=sec(day.isoformat()+'T00:00:00Z')
        found=[m for m in ordered if m['open_time'].startswith(day.isoformat())]
        write_jsonl(root/'BY_DAY'/(day.isoformat()+'.jsonl.gz'),found)
        starts={sec(m['open_time']) for m in found}
        absent=[dt.datetime.fromtimestamp(t,UTC).isoformat() for t in range(daylo,daylo+86400,900) if t not in starts]
        missing.extend(absent)
        days[day.isoformat()]={'contracts':len(found),'unique_opening_windows':len(starts),
             'missing_theoretical_windows':len(absent),'non_15minute_contracts':sum(sec(m['close_time'])-sec(m['open_time'])!=900 for m in found),
             'yes':sum(m.get('result')=='yes' for m in found),'no':sum(m.get('result')=='no' for m in found)}
    cutoff,_=source.fetch('/historical/cutoff');write_json(root/'HISTORICAL_CUTOFF.json',cutoff)
    fees,_=source.fetch('/series/KXBTC15M');write_json(root/'CURRENT_SERIES_METADATA_NOT_HISTORICAL_FEES.json',fees)
    report={'scope':[BEGIN.isoformat(),(END-dt.timedelta(days=1)).isoformat()],
        'unique_tickers':len(markets),'theoretical_windows':17280,'missing_opening_windows':missing,
        'source_duplicate_records':source_duplicates,'days':days,
        'limitations':['Post-settlement terms do not prove original strike publication time',
                      'Current series fee metadata does not establish past effective fee schedules',
                      'Missing theoretical windows are not fabricated; source cause unverified']}
    write_json(root/'CONTRACT_INDEX_MANIFEST.json',report)
    with (root/'COVERAGE_MATRIX.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=['date_utc',*next(iter(days.values()))]);w.writeheader()
        for d,counts in days.items():w.writerow({'date_utc':d,**counts})
    print('CONTRACT_INDEX',json.dumps({'contracts':len(markets),'missing_windows':len(missing),'days':len(days)}),flush=True)
    return report


def collect_day(root,index,day,quotes=True,trades=True,max_contracts=None,contract_offset=0,contract_limit=None,deadline_epoch=None):
    day=dt.date.fromisoformat(day)
    if not BEGIN<=day<END:raise ValueError('Day outside authorized 180-day interval')
    root=pathlib.Path(root);source=PublicSource(root/'ORIGINAL_RESPONSES');root.mkdir(parents=True,exist_ok=True)
    contracts=list(iter_jsonl(pathlib.Path(index)/'BY_DAY'/(day.isoformat()+'.jsonl.gz')))
    total_day_contracts=len(contracts)
    if contract_offset<0 or (contract_limit is not None and contract_limit<=0):raise ValueError('Invalid contract partition')
    contracts=contracts[contract_offset:contract_offset+contract_limit if contract_limit else None]
    if max_contracts:contracts=contracts[:max_contracts]
    cutoff=json.loads((pathlib.Path(index)/'HISTORICAL_CUTOFF.json').read_text())
    market_cut=sec(cutoff['market_settled_ts']);trade_cut=sec(cutoff['trades_created_ts'])
    summary={'date_utc':day.isoformat(),'contracts_requested':len(contracts),'quotes_requested':quotes,
             'trades_requested':trades,'contract_results':[],'collection_completed':False,
             'limited_validation_sample':bool(max_contracts),'contract_offset':contract_offset,'contract_limit':contract_limit,'total_day_contracts':total_day_contracts}
    write_json(root/'COLLECTION_STATUS.json',summary)
    errors=[]
    for i,m in enumerate(contracts,1):
        if deadline_epoch and time.time()+45>=deadline_epoch:break
        ticker=m['ticker'];start=sec(m['open_time']);close=sec(m['close_time'])
        result={'ticker':ticker,'opening_utc':m['open_time'],'closing_utc':m['close_time']}
        try:
            if quotes:
                archived=sec(m.get('settlement_ts') or m['close_time'])<market_cut
                endpoint=('/historical/markets/'+ticker+'/candlesticks') if archived else '/markets/candlesticks'
                q={'start_ts':start-60,'end_ts':close+60,'period_interval':1}
                if not archived:q['market_tickers']=ticker
                obj,provenance=source.fetch(endpoint,q)
                if archived:bars=obj.get('candlesticks')
                else:
                    blocks=obj.get('markets',[])
                    match=[b for b in blocks if b.get('market_ticker')==ticker]
                    if len(match)!=1:raise ValueError('Missing/ambiguous official candle block')
                    bars=match[0].get('candlesticks')
                if not isinstance(bars,list):raise ValueError('Malformed candle population')
                seen=set();inside=0;missing_bid_ask=0;crossed=0;rows=[]
                for bar in bars:
                    t=int(bar['end_period_ts'])
                    if t in seen:raise ValueError('Duplicate original candle timestamp')
                    seen.add(t);inside+=start<t<=close
                    def closing(name):
                        item=bar.get(name,{})
                        return item.get('close_dollars',item.get('close'))
                    bid=closing('yes_bid');ask=closing('yes_ask')
                    if bid is None or ask is None:missing_bid_ask+=1
                    elif not decimal.Decimal('0')<=decimal.Decimal(str(bid))<=decimal.Decimal(str(ask))<=1:crossed+=1
                    rows.append({'ticker':ticker,'within_contract':start<t<=close,'original_candlestick':bar,
                                 'source_response':provenance['response_file'],
                                 'retrieval_completed_utc':provenance['retrieval_completed_utc']})
                write_jsonl(root/'QUOTES'/(ticker+'.jsonl.gz'),rows)
                result.update({'quote_rows':len(bars),'in_contract_candles':inside,
                               'missing_closing_bid_ask':missing_bid_ask,'crossed_or_invalid_closing_quotes':crossed,
                               'quote_collection_completed':True,'full_in_contract_minute_population':inside==(close-start)//60})
            if trades:
                # Per-contract full cursor exhaustion, not a sample or selected profitable trades.
                endpoint='/historical/trades' if close<trade_cut else '/markets/trades'
                seen_ids=set();trade_count=0;pages=0;total_size=decimal.Decimal(0)
                trade_path=root/'TRADES'/(ticker+'.jsonl.gz');trade_path.parent.mkdir(parents=True,exist_ok=True)
                with gzip.open(trade_path,'wt',compresslevel=GZIP_LEVEL) as destination:
                    for page,provenance in paginated(source,endpoint,
                          {'ticker':ticker,'min_ts':start-1,'max_ts':close+1,'limit':1000},'trades'):
                        pages+=1
                        for trade in page:
                            tid=trade.get('trade_id')
                            if not tid or trade.get('ticker')!=ticker:raise ValueError('Invalid trade identity')
                            if tid in seen_ids:raise ValueError('Duplicate transaction ID across pages')
                            seen_ids.add(tid)
                            t=sec(trade['created_time'])
                            if not start-1<=t<=close+1:raise ValueError('Trade outside requested contract window')
                            size=decimal.Decimal(str(trade.get('count_fp',trade.get('count'))))
                            yp=decimal.Decimal(str(trade.get('yes_price_dollars')))
                            np=decimal.Decimal(str(trade.get('no_price_dollars')))
                            if not size.is_finite() or size<=0 or not 0<=yp<=1 or not 0<=np<=1:
                                raise ValueError('Invalid trade price or quantity')
                            total_size+=size
                            destination.write(json.dumps({'original_trade':trade,'source_response':provenance['response_file'],
                                         'retrieval_completed_utc':provenance['retrieval_completed_utc']},separators=(',',':'))+'\n')
                            trade_count+=1
                result.update({'trade_ticks':trade_count,'trade_pages':pages,'trade_quantity_sum':str(total_size),
                               'trade_cursor_exhausted':True,'reported_market_volume_fp':m.get('volume_fp'),
                               'volume_reconciliation':'not assumed equal: market volume may include records outside requested time boundaries'})
                if not trade_count and decimal.Decimal(str(m.get('volume_fp') or '0'))>0:
                    raise ValueError('Zero historical trades returned for nonzero reported market volume')
        except Exception as e:
            result['failure_type']=type(e).__name__;result['failure_message']=str(e)
            errors.append(ticker)
        summary['contract_results'].append(result)
        write_json(root/'COLLECTION_STATUS.json',summary)
        if i%8==0:print('PUBLIC_DAY_PROGRESS',day.isoformat(),i,'of',len(contracts),'failures',len(errors),flush=True)
    summary['collection_completed']=not errors and len(summary['contract_results'])==len(contracts)
    summary['deferred_contracts']=[m['ticker'] for m in contracts[len(summary['contract_results']):]]
    summary['failed_contracts']=errors
    summary['source_network_requests']=source.network_requests
    summary['replayed_source_requests']=source.cache_hits
    summary['limitations']=['Quotes are minute summaries, not continuous executable L2',
        'Actual exchange trades are not user account fills', 'No historical book quantities inferred',
        'No original quote receipt latency or strike publication time proven']
    write_json(root/'COLLECTION_STATUS.json',summary)
    print('PUBLIC_DAY_SUMMARY',json.dumps({k:v for k,v in summary.items() if k!='contract_results'}),flush=True)
    if not summary['collection_completed']:raise RuntimeError('Incomplete contracts; original responses and checkpoints retained')
    return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['index','day']);p.add_argument('--root',required=True)
    p.add_argument('--seed',default='seed');p.add_argument('--index',default='contract_index')
    p.add_argument('--day');p.add_argument('--no-quotes',action='store_true');p.add_argument('--no-trades',action='store_true')
    p.add_argument('--max-contracts',type=int)
    a=p.parse_args()
    if a.mode=='index':build_index(a.root,a.seed)
    else:collect_day(a.root,a.index,a.day,not a.no_quotes,not a.no_trades,a.max_contracts)
if __name__=='__main__':main()
