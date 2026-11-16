"""Independent native-record and raw-fingerprint audit of a daily archive."""
import collections,gzip,hashlib,json,pathlib,sys
from research.historical_180 import iter_jsonl,write_json

def fingerprint(row):return hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def verify(root):
    root=pathlib.Path(root);status=json.loads((root/'COLLECTION_STATUS.json').read_text())
    raw_trades=collections.Counter();raw_quotes=collections.Counter();raw_files=0
    for meta in (root/'ORIGINAL_RESPONSES').glob('*.provenance.json'):
        info=json.loads(meta.read_text());data=meta.with_name(meta.name.replace('.provenance.json','.json.gz'))
        raw=gzip.decompress(data.read_bytes())
        if hashlib.sha256(raw).hexdigest()!=info['original_sha256']:raise ValueError('Raw response fingerprint changed')
        raw_files+=1;obj=json.loads(raw)
        if 'trades' in obj:
            raw_trades.update(fingerprint(t) for t in obj['trades'])
        if 'candlesticks' in obj:
            ticker=info['url'].split('/historical/markets/',1)[1].split('/')[0]
            raw_quotes.update((ticker,fingerprint(b)) for b in obj['candlesticks'])
        for block in obj.get('markets',[]):
            if 'candlesticks' in block:
                raw_quotes.update((block['market_ticker'],fingerprint(b)) for b in block['candlesticks'])
    observed_trades=collections.Counter();observed_quotes=collections.Counter();ids=set()
    for p in (root/'TRADES').glob('*.jsonl.gz'):
        for row in iter_jsonl(p):
            t=row['original_trade'];key=(t['ticker'],t['trade_id'])
            if key in ids:raise ValueError('Duplicate transaction identity in normalized records')
            ids.add(key);observed_trades[fingerprint(t)]+=1
    for p in (root/'QUOTES').glob('*.jsonl.gz'):
        for row in iter_jsonl(p):observed_quotes[(row['ticker'],fingerprint(row['original_candlestick']))]+=1
    complete=status.get('collection_completed',False)
    if complete:
        if raw_trades!=observed_trades or raw_quotes!=observed_quotes:
            raise ValueError('Normalized population differs from original source records')
        if sum(r.get('trade_ticks',0) for r in status['contract_results'])!=sum(observed_trades.values()):
            raise ValueError('Reported transaction count differs from independent row count')
        if sum(r.get('quote_rows',0) for r in status['contract_results'])!=sum(observed_quotes.values()):
            raise ValueError('Reported quote count differs from independent row count')
    report={'original_response_files_verified':raw_files,'collection_completed':complete,
            'independent_complete_population_audit_passed':complete,
            'actual_trade_ticks':sum(observed_trades.values()),'minute_quote_rows':sum(observed_quotes.values()),
            'partial_raw_source_archive_only':not complete,
            'checks':['all uncompressed raw SHA256 fingerprints','native original-record equality',
                      'independent transaction identity uniqueness','independent reported/exported row counts']}
    write_json(root/'INDEPENDENT_AUDIT.json',report)
    status['independent_audit']=report;write_json(root/'COLLECTION_STATUS.json',status)
    print(json.dumps(report))
    return report
if __name__=='__main__':verify(sys.argv[1])
