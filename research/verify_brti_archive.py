import csv,gzip,json,hashlib,pathlib,decimal,datetime
import sys
root=pathlib.Path(sys.argv[1]);m=json.loads((root/'AUDIT/BRTI_30DAY_MANIFEST.json').read_text())
results=[];previous=None;total=0;sample_count=0
with gzip.open(root/'BRTI_1S_first_tick_every_second.csv.gz','rt') as f:
 seconds=iter(csv.DictReader(f))
 for p in sorted((root/'BRTI_5HZ_ORIGINAL').glob('*.gz')):
  n=0;bad=0;first=None;last=None
  assert hashlib.file_digest(p.open('rb'),'sha256').hexdigest()==m['files'][str(p.relative_to(root))]['sha256']
  with gzip.open(p,'rt') as g:
   for row in csv.DictReader(g):
    t=int(row['timestamp_ms']);v=decimal.Decimal(row['BRTI_USD'])
    assert v.is_finite() and 100<v<1000000
    assert previous is None or t-previous==200,(previous,t)
    assert row['timestamp_utc']==datetime.datetime.fromtimestamp(t/1000,datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
    if previous is None or previous//1000!=t//1000:
     s=next(seconds);assert int(s['epoch_second'])==t//1000 and int(s['first_tick_timestamp_ms'])==t
     assert decimal.Decimal(s['BRTI_USD_first_tick_in_second'])==v
     sample_count+=1
    previous=t;n+=1;first=t if first is None else first;last=t
  total+=n;results.append(dict(file=p.name,rows=n,first_ms=first,last_ms=last))
 assert next(seconds,None) is None
for name,info in m['files'].items():
 p=root/name;assert p.stat().st_size==info['size_bytes'];assert hashlib.file_digest(p.open('rb'),'sha256').hexdigest()==info['sha256']
report=dict(status='PASS',raw_rows=total,derived_second_rows=sample_count,files=results,checks=['all manifest hashes and sizes','200ms cadence across all rows','positive finite values','UTC/native timestamps agree','independent first tick per second matches all derived rows'],limitations=['Original JSON envelopes and native value strings were not retained by existing collector','Per-request retrieval times and provider revisions are absent','Settlement comparisons pending Kalshi artifact'])
(root/'INDEPENDENT_AUDIT.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
