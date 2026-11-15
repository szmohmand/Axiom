import json
from pathlib import Path
from phase0.verify_transfer import verify

ROOT=Path(__file__).resolve().parents[1]


def test_transfer_manifest_source_hashes():
    assert verify(ROOT)==[]


def test_no_secrets_or_live_configs_in_transfer():
    assert not (ROOT/'.env').exists()
    assert not (ROOT/'render.yaml').exists()
    assert not (ROOT/'Procfile').exists()
    m=json.loads((ROOT/'phase0/transfer_manifest.json').read_text())
    assert m['secrets_migrated'] is False
    assert m['approval']['user_sign_off']=='PENDING'
