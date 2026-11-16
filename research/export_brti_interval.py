"""Reuse the verified collector for bounded intervals, retaining original responses.

Only authenticated historical GETs; credentials and headers never reach disk.
Raw response bytes are preserved alongside retrieval times and request parameters.
"""
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
from research import export_brti_30day as collector
from research import export_shared_historical as shared


def configure(begin, end, root):
    start = dt.datetime.fromisoformat(begin).replace(tzinfo=dt.timezone.utc)
    stop = dt.datetime.fromisoformat(end).replace(tzinfo=dt.timezone.utc)
    if not 0 < (stop-start).total_seconds() <= 31*86400:
        raise ValueError('Require a positive interval of at most 31 days')
    collector.BEGIN, collector.END = start, stop
    collector.FIRST_HOUR = start-dt.timedelta(hours=1)
    collector.ROOT = Path(root)
    collector.INDEX_DIR = collector.ROOT/'BRTI_5HZ_ORIGINAL'


def run():
    begin = os.environ.get('RESEARCH_BEGIN', '2026-08-06')
    end = os.environ.get('RESEARCH_END', '2026-08-13')
    configure(begin, end, 'interval_BRTI')
    raw_dir = collector.ROOT/'ORIGINAL_RESPONSES'
    raw_dir.mkdir(parents=True, exist_ok=True)
    original_get = shared.get
    retrieval_path = raw_dir/'retrieval_manifest.json'
    records = json.loads(retrieval_path.read_text()) if retrieval_path.exists() else []
    cached = {record['source_url']: record for record in records}
    completed = False

    def capture(url, headers=None, cap=25_000_000):
        # Only the public endpoint and nonsensitive query are recorded.
        if not url.startswith(shared.API+'/cfbenchmarks/history/values?'):
            raise ValueError('Interval collector forbids unrelated endpoints')
        if url in cached:
            record = cached[url]
            raw = gzip.decompress((collector.ROOT/record['file']).read_bytes())
            if hashlib.sha256(raw).hexdigest() != record['original_response_sha256']:
                raise ValueError('Cached source response hash mismatch')
            return raw
        retrieved = dt.datetime.now(dt.timezone.utc).isoformat()
        raw = original_get(url, headers, cap)
        finished = dt.datetime.now(dt.timezone.utc).isoformat()
        name = f'hour_{len(records):04d}.json.gz'
        with gzip.open(raw_dir/name, 'wb') as f:
            f.write(raw)
        records.append(dict(file='ORIGINAL_RESPONSES/'+name, source_url=url,
                            request_started_utc=retrieved, retrieval_completed_utc=finished,
                            original_response_sha256=hashlib.sha256(raw).hexdigest()))
        cached[url] = records[-1]
        retrieval_path.write_text(json.dumps(records, indent=2)+'\n')
        return raw

    shared.get = capture
    try:
        if os.environ.get('RESEARCH_PREFLIGHT') == '1':
            keyid = os.environ['KALSHI_API_KEY_ID'].strip()
            key, _ = collector.load_key(os.environ['KALSHI_PRIVATE_KEY_PEM'])
            endpoint = '/cfbenchmarks/history/values'
            response = shared.json_get(endpoint, {'id':'BRTI', 'timespan':'HOUR',
                'timestamp':collector.BEGIN.strftime('%Y-%m-%dT%H:00:00.000Z')},
                collector.sign_headers(keyid,key,'GET','/trade-api/v2'+endpoint))
            print('BRTI_PREFLIGHT_HOUR_AVAILABLE', any(shared.walk_values(response)), flush=True)
            # Empty probes do not justify discarding other hours in the interval.
        collector.run()
        manifest = collector.ROOT/'AUDIT/BRTI_30DAY_MANIFEST.json'
        m = json.loads(manifest.read_text())
        m['utc_complete_days_covered_from'] = begin
        m['utc_complete_days_covered_through'] = (collector.END-dt.timedelta(days=1)).date().isoformat()
        m['includes_extra_hour_preopening_warmup'] = collector.FIRST_HOUR.isoformat()
        m['raw_response_preservation'] = 'Original UTF-8 JSON bytes in gzip, including native precision; no request headers'
        manifest.write_text(json.dumps(m, indent=2)+'\n')
        completed = True
    finally:
        shared.get = original_get
        status = {'begin_inclusive':begin,'end_exclusive':end,
                  'collection_completed':completed,'original_responses_preserved':len(records),
                  'expected_hour_requests':int((collector.END-collector.FIRST_HOUR).total_seconds()/3600),
                  'resume_policy':'replay checksum-verified original responses; fetch only missing URLs'}
        (collector.ROOT/'COLLECTION_STATUS.json').write_text(json.dumps(status,indent=2)+'\n')


if __name__ == '__main__':
    run()
