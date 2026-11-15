#!/usr/bin/env python3
"""Collect public Kalshi bot repositories without executing any downloaded code.

Runs on Colab, a PC, or Codespaces. Does not use trading credentials and never
places any orders. Bundles downloaded repository snapshots in one archive.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'output'
TIMEOUT = 75
MAX_PER_REPO_MB = 80
UA = 'Kalshi-Public-Source-Collector/1.1 research-only'


def safe_name(s):
    return re.sub(r'[^a-zA-Z0-9._-]+', '_', s).strip('_')[:90]


def fetch(url, max_bytes=MAX_PER_REPO_MB*1024*1024):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'application/vnd.github+json',
        **({'Authorization': 'Bearer '+os.environ['GITHUB_TOKEN']}
           if os.environ.get('GITHUB_TOKEN') and url.startswith('https://api.github.com/') else {})
    })
    chunks = []
    n = 0
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        while True:
            block = response.read(1024*1024)
            if not block:
                break
            n += len(block)
            if n > max_bytes:
                raise ValueError('Repository archive exceeded size cap (%s MB)' % MAX_PER_REPO_MB)
            chunks.append(block)
    return b''.join(chunks)


def zip_type(content):
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names = z.namelist()
    langs = []
    if any(x.endswith('.xcodeproj/project.pbxproj') for x in names): langs.append('macOS/Xcode')
    if any(x.endswith(('pyproject.toml', 'requirements.txt', 'setup.py')) for x in names): langs.append('Python')
    if any(x.endswith('package.json') for x in names): langs.append('Node/JS')
    if any(x.endswith('Dockerfile') for x in names): langs.append('Docker')
    if any(x.endswith('.ipynb') for x in names): langs.append('Notebook')
    if not langs: langs.append('Inspect README')
    return ', '.join(langs), len(names)


def collect(item):
    name = item['name']
    kind = item['availability']
    repo = item.get('repository')
    if kind not in ('public_source', 'public_source_gitlab', 'public_strategy_specs'):
        return {'name': name, 'url': item.get('url'), 'status': 'not-public-original-source',
                'notes': kind, 'source_available': False}
    if not repo:
        return {'name': name, 'url': item.get('url'), 'status': 'missing_repo_id', 'source_available': False}
    errors = []
    urls = []
    if kind == 'public_source_gitlab':
        urls = [('default', f'https://gitlab.com/api/v4/projects/{repo}/repository/archive.zip')]
    else:
        for branch in ('main', 'master'):
            urls.append((branch, f'https://codeload.github.com/{repo}/zip/refs/heads/{branch}'))
    for branch, link in urls:
        try:
            data = fetch(link)
            if not zipfile.is_zipfile(io.BytesIO(data)):
                raise ValueError('Non-ZIP response')
            typ, files = zip_type(data)
            filename = safe_name(name) + '.zip'
            (OUTPUT/'repositories'/filename).write_bytes(data)
            return {'name': name, 'url': item.get('url'), 'status': 'downloaded',
                    'source_available': True, 'filename': filename, 'branch': branch,
                    'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                    'files_in_archive': files, 'detected_stack': typ}
        except Exception as exc:
            errors.append(f'{branch}: {str(exc)[:180]}')
    return {'name': name, 'url': item.get('url'), 'status': 'download_failed',
            'source_available': True, 'notes': ' | '.join(errors)}


def main():
    OUTPUT.mkdir(exist_ok=True, parents=True)
    (OUTPUT/'repositories').mkdir(exist_ok=True)
    items = json.loads((ROOT/'full_catalog.json').read_text())
    allowed = [x for x in items if x['availability'] in (
        'public_source', 'public_source_gitlab', 'public_strategy_specs')]
    rest = [x for x in items if x not in allowed]
    results = []
    print('Downloading', len(allowed), 'public source/strategy repositories; not executing any of them.')
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {pool.submit(collect, item): item for item in allowed}
        for job in as_completed(jobs):
            r = job.result()
            results.append(r)
            print(('[OK] ' if r['status']=='downloaded' else '[FAIL] ')+r['name']+' — '+r['status'], flush=True)
    results.extend(collect(x) for x in rest)
    results.sort(key=lambda a:a['name'].lower())
    (OUTPUT/'collection_report.json').write_text(json.dumps(results, indent=2)+'\n')
    (OUTPUT/'collection_report.csv').write_text('', encoding='utf8')
    keys = ['name','url','status','source_available','filename','branch','detected_stack','files_in_archive','bytes','sha256','notes']
    with (OUTPUT/'collection_report.csv').open('w', newline='', encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=keys, extrasaction='ignore');w.writeheader();w.writerows(results)
    ok = [r for r in results if r['status']=='downloaded']
    log = [f'Public code and strategy repositories downloaded: {len(ok)}/{len(allowed)}',
           'This is a collection of unexecuted original source snapshots, not a built or verified bot fleet.',
           'No source code was generated for closed-source/private systems. No orders were placed.',
           '', 'Downloaded:']
    log.extend(f"- {r['name']}: {r.get('detected_stack')}" for r in ok)
    log.append('');log.append('Unsuccessful public code downloads:')
    log.extend(f"- {r['name']}: {r.get('notes')}" for r in results if r['status']=='download_failed')
    (OUTPUT/'SUMMARY.txt').write_text('\n'.join(log)+'\n')
    bundle = OUTPUT/'ALL_PUBLIC_KALSHI_BOT_SOURCE.zip'
    with zipfile.ZipFile(bundle, 'w', allowZip64=True, compression=zipfile.ZIP_STORED) as z:
        for p in (OUTPUT/'collection_report.json', OUTPUT/'collection_report.csv', OUTPUT/'SUMMARY.txt', ROOT/'full_catalog.csv'):
            z.write(p, 'meta/'+p.name)
        for p in (OUTPUT/'repositories').glob('*.zip'):
            z.write(p, 'original_repositories/'+p.name)
    print('\nCOMPLETE:', bundle, 'size:', round(bundle.stat().st_size/1024/1024,2),'MB',flush=True)
    print('These are source snapshots. Running them requires project-specific prerequisites and review.')
    return bundle

if __name__=='__main__': main()
