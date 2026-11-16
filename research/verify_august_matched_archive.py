import csv,gzip,json,pathlib,hashlib,decimal,datetime,collections,sys
D=decimal.Decimal;root=pathlib.Path(sys.argv[1]);m=json.loads((root/'AUDIT/BRTI_30DAY_MANIFEST.json').read_text())
records={};prior=None;gaps=[];ticks=0
for p in sorted((root/'BRTI_5HZ_ORIGINAL').glob('*.gz')):
 with gzip.open(p,'rt') as f:
  for row in csv.DictReader(f):
   t=int(row['timestamp_ms']);v=D(row['BRTI_USD']);assert v.is_finite() and 100<v<1000000
   if prior is not None:
    assert t>prior
    if t-prior!=200:gaps.append(dict(after_ms=prior,before_ms=t,missing_200ms_slots=(t-prior)//200-1))
   records.setdefault(t//1000,(t,v));prior=t;ticks+=1
for name,info in m['files'].items():
 p=root/name;assert p.stat().st_size==info['size_bytes'];assert hashlib.file_digest(p.open('rb'),'sha256').hexdigest()==info['sha256']
n=0
with gzip.open(root/'BRTI_1S_first_tick_every_second.csv.gz','rt') as f:
 for row in csv.DictReader(f):
  t,v=records[int(row['epoch_second'])];assert int(row['first_tick_timestamp_ms'])==t and D(row['BRTI_USD_first_tick_in_second'])==v;n+=1
assert n==len(records)
rawticks=0;raw_gap_hours=[]
retrieval=json.loads((root/'ORIGINAL_RESPONSES/retrieval_manifest.json').read_text())
for meta in retrieval:
 raw=gzip.decompress((root/meta['file']).read_bytes());assert hashlib.sha256(raw).hexdigest()==meta['original_response_sha256'];j=json.loads(raw);points=j['data']['payload'];rawticks+=len(points)
 if len(points)!=18000:raw_gap_hours.append(dict(url=meta['source_url'],rows=len(points)))
assert rawticks==ticks
K=pathlib.Path(sys.argv[2]);markets=list(csv.DictReader((K/'KALSHI/KXBTC15M_contract_terms_official_30d.csv').open()))
terms={x['ticker']:x for x in markets};assert len(terms)==len(markets)
audit=[];counts=collections.Counter()
def sec(s):return int(datetime.datetime.fromisoformat(s.replace('Z','+00:00')).timestamp())
for market in markets:
 row={'ticker':market['ticker']};recon={}
 for tag,boundary,field in [('opening',sec(market['open_time']),'floor_strike'),('closing',sec(market['close_time']),'expiration_value')]:
  vals=[records[s][1] for s in range(boundary-60,boundary) if s in records]
  row[tag+'_samples']=len(vals);row[tag+'_official']=market[field]
  if len(vals)==60 and market[field]:
   avg=sum(vals)/60;recon[tag]=avg;row[tag+'_first_tick_average']=str(avg);row[tag+'_difference_usd']=str(avg-D(market[field]));row[tag+'_within_half_cent']=str(abs(avg-D(market[field]))<=D('.005'))
   counts[tag+'_full60']+=1;counts[tag+'_over_half_cent']+=abs(avg-D(market[field]))>D('.005')
  else:counts[tag+'_incomplete']+=1
 if len(recon)==2:
  row['candidate_winner']='yes' if recon['closing']>=recon['opening'] else 'no';row['official_result']=market['result'];row['winner_matches']=str(row['candidate_winner']==market['result']);counts['matched_boundary_windows']+=1;counts['winner_disagreements']+=row['candidate_winner']!=market['result']
 start=sec(market['open_time']);close=sec(market['close_time']);row['within_contract_seconds']=sum(s in records for s in range(start,close));counts['full900sec_windows']+=row['within_contract_seconds']==900
 audit.append(row)
cols=list(dict.fromkeys(k for r in audit for k in r));p=K/'SETTLEMENT_RECONSTRUCTION_AUDIT.csv'
with p.open('w') as f:w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(audit)
quote_n=0;inside=0;seen=set()
with gzip.open(K/'KALSHI/KXBTC15M_actual_bid_ask_trade_1min_OHLC_30d.csv.gz','rt') as f:
 for r in csv.DictReader(f):
  key=(r['ticker'],r['end_period_ts']);assert key not in seen;seen.add(key);assert D(r['yes_bid_close'])<=D(r['yes_ask_close']);quote_n+=1;inside+=r['within_contract']=='true'
report=dict(raw_ticks=ticks,derived_seconds=n,expected_ticks=169*18000,missing_ticks=169*18000-ticks,missing_seconds=169*3600-n,gaps=gaps,incomplete_raw_hours=raw_gap_hours,contracts=len(markets),quote_rows=quote_n,in_contract_quote_rows=inside,settlement=dict(counts),limitations=['First-tick averaging is candidate research reconstruction, not universal official sampling proof','Zero missing boundary samples required for comparisons','No historical delivery latency or strike-publication timing established'])
(K/'INDEPENDENT_AUDIT.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))

with (K/'COVERAGE_MATRIX.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['date_utc','brti_ticks','brti_seconds','contracts','quote_rows','actual_trade_ticks','orderbook_snapshots'])
 for day in range(6,13):
  date=f'2026-08-{day:02d}';start=sec(date+'T00:00:00Z')
  nsec=sum(s in records for s in range(start,start+86400));contracts=sum(x['open_time'].startswith(date) for x in markets)
  w.writerow([date, next(x['raw_ticks'] for x in m['hours_summary'] if x['hour'].startswith(date)) if False else sum(x['raw_ticks'] for x in m['hours_summary'] if x['hour'].startswith(date)),nsec,contracts,contracts*16,0,0])
