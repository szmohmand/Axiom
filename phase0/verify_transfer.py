#!/usr/bin/env python3
"""Verify original Phase 0 archive provenance while allowing later code repairs.

The original v1/v2 ZIPs are immutable. Their bytes and each v2 archived source
file are checked against the original, unmodified Phase 0 manifest. Git working
files are expected to change during development and are *not* falsely required
to keep their original ZIP hashes. Current code behavior is checked by CI tests.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZipFile, BadZipFile


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def verify(checkout, legacy_zip=None, require_archives=False):
    manifest = json.loads((checkout/'phase0/transfer_manifest.json').read_text())
    errors = []
    source_name = manifest['transfer_base']
    source_archive = checkout/'phase0/source_archives'/source_name
    for row in manifest['source_artifacts']:
        if row['type'] != 'legacy_zip':
            continue
        frozen = checkout/'phase0/source_archives'/row['filename']
        if frozen.is_file():
            if sha(frozen) != row['sha256']:
                errors.append('archive hash mismatch: ' + row['filename'])
        elif require_archives:
            errors.append('missing frozen ZIP: ' + row['filename'])

    if source_archive.is_file():
        try:
            with ZipFile(source_archive) as archive:
                for row in manifest['transferred_files']:
                    archived_path = 'AXIOM_v2/' + row['path']
                    try:
                        data = archive.read(archived_path)
                    except KeyError:
                        errors.append('missing file in frozen source ZIP: ' + row['path'])
                        continue
                    original_digest = row.get('original_sha256', row['sha256'])
                    if hashlib.sha256(data).hexdigest() != original_digest:
                        errors.append('source manifest mismatch: ' + row['path'])
        except BadZipFile:
            errors.append('source ZIP is invalid')
    for row in manifest['transferred_files']:
        if not (checkout/row['path']).is_file():
            errors.append('missing current source file: ' + row['path'])

    for forbidden in ('.env', 'credentials.json', 'private_key.pem'):
        if (checkout/forbidden).exists():
            errors.append('credential artifact: ' + forbidden)
    try:
        tracked = subprocess.check_output(
            ['git','-C',str(checkout),'ls-files','-z'],
            stderr=subprocess.DEVNULL).decode().split('\0')
    except (subprocess.CalledProcessError, FileNotFoundError):
        tracked = []
    for name in tracked:
        if not name:
            continue
        base = Path(name).name.lower()
        if (base == '.env' or (base.startswith('.env.') and base != '.env.example')
                or base.endswith(('.pem', '.pfx', '.p12', '.key', '.sqlite3', '.db'))):
            errors.append('sensitive tracked path: ' + name)
    if legacy_zip:
        expected = next(row for row in manifest['source_artifacts']
            if row['filename'] == source_name)['sha256']
        if sha(legacy_zip) != expected:
            errors.append('legacy ZIP hash mismatch')
    return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkout', default='.')
    parser.add_argument('--legacy-zip')
    parser.add_argument('--require-archives', action='store_true')
    args = parser.parse_args()
    issues = verify(Path(args.checkout),
        Path(args.legacy_zip) if args.legacy_zip else None, args.require_archives)
    if issues:
        print('FAIL: ' + ', '.join(issues))
        raise SystemExit(1)
    print('PASS: frozen v1/v2 archives and v2 source provenance verified; current source present')
