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
    records = []

    def capture(url, headers=None, cap=25_000_000):
        # Only the public endpoint and nonsensitive query are recorded.
        if not url.startswith(shared.API+'/cfbenchmarks/history/values?'):
            raise ValueError('Interval collector forbids unrelated endpoints')
        retrieved = dt.datetime.now(dt.timezone.utc).isoformat()
        raw = original_get(url, headers, cap)
        finished = dt.datetime.now(dt.timezone.utc).isoformat()
        name = f'hour_{len(records):04d}.json.gz'
        with gzip.open(raw_dir/name, 'wb') as f:
            f.write(raw)
        records.append(dict(file='ORIGINAL_RESPONSES/'+name, source_url=url,
                            request_started_utc=retrieved, retrieval_completed_utc=finished,
                            original_response_sha256=hashlib.sha256(raw).hexdigest()))
        (raw_dir/'retrieval_manifest.json').write_text(json.dumps(records, indent=2)+'\n')
        return raw

    shared.get = capture
    try:
        collector.run()
        manifest = collector.ROOT/'AUDIT/BRTI_30DAY_MANIFEST.json'
        m = json.loads(manifest.read_text())
        m['utc_complete_days_covered_from'] = begin
        m['utc_complete_days_covered_through'] = (collector.END-dt.timedelta(days=1)).date().isoformat()
        m['includes_extra_hour_preopening_warmup'] = collector.FIRST_HOUR.isoformat()
        m['raw_response_preservation'] = 'Original UTF-8 JSON bytes in gzip, including native precision; no request headers'
        manifest.write_text(json.dumps(m, indent=2)+'\n')
    finally:
        shared.get = original_get


if __name__ == '__main__':
    run()
