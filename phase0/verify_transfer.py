#!/usr/bin/env python3
"""Verify AXIOM Phase 0 source provenance without executing imported code.

This checks copied source bytes against the frozen transfer manifest. Optional
--legacy-zip verifies the supplied original v2 ZIP SHA; CI has no archive.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def verify(checkout, legacy_zip=None, require_archives=False):
    manifest=json.loads((checkout/'phase0/transfer_manifest.json').read_text())
    errors=[]
    for row in manifest['transferred_files']:
        path=checkout/row['path']
        if not path.is_file():
            errors.append('missing: '+row['path'])
        elif sha(path)!=row['sha256']:
            errors.append('modified from frozen ZIP: '+row['path'])
    # Verify original ZIP archives independently when stored in this repository.
    for row in manifest['source_artifacts']:
        if row['type'] != 'legacy_zip':
            continue
        frozen = checkout/'phase0'/'source_archives'/row['filename']
        if frozen.is_file():
            if sha(frozen) != row['sha256']:
                errors.append('archive hash mismatch: '+row['filename'])
        elif require_archives:
            errors.append('missing frozen ZIP: '+row['filename'])
    for forbidden in ('.env','credentials.json','private_key.pem'):
        if (checkout/forbidden).exists(): errors.append('credential artifact: '+forbidden)
    # If the checkout is a Git repo, refuse sensitive filenames anywhere in tracked contents.
    try:
        tracked=subprocess.check_output(['git','-C',str(checkout),'ls-files','-z'],stderr=subprocess.DEVNULL).decode().split('\0')
    except (subprocess.CalledProcessError, FileNotFoundError):
        tracked=[]
    for name in tracked:
        if not name: continue
        base=Path(name).name.lower()
        if base == '.env' or (base.startswith('.env.') and base!='.env.example') or base.endswith(('.pem','.pfx','.p12','.key','.sqlite3','.db')):
            errors.append('sensitive tracked path: '+name)
    if legacy_zip:
        expect=next(row for row in manifest['source_artifacts'] if row['filename']=='AXIOM_v2_Multi_Engine_Research_Bot.zip')['sha256']
        if sha(legacy_zip)!=expect: errors.append('legacy ZIP hash mismatch')
    return errors


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--checkout',default='.')
    parser.add_argument('--legacy-zip')
    parser.add_argument('--require-archives', action='store_true')
    args=parser.parse_args()
    e=verify(Path(args.checkout),Path(args.legacy_zip) if args.legacy_zip else None, args.require_archives)
    if e:
        print('FAIL: '+', '.join(e));raise SystemExit(1)
    print('PASS: transferred files match pinned source SHA-256 fingerprints')
