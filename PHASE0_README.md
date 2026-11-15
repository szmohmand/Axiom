# AXIOM Phase 0 — isolated source freeze and transfer

**Scope:** A source-preserving AXIOM v2 checkpoint and reproducible local/CI tests.
Target repository: **`szmohmand/Axiom`**, existing `main` branch only. The dedicated GitHub repository was empty when verified on 2026-11-15. Do not create/delete branches or touch any other repositories.
No live orders or production resources are configured.

## Transfer baseline
The original ZIPs are pinned in `phase0/transfer_manifest.json` by SHA-256,
but do not contain Git history: do not report these as original Git commit SHAs.
The working source comes solely from `AXIOM_v2_Multi_Engine_Research_Bot.zip`.
The old v1 ZIP is preserved as a separate predecessor reference.
The two exact input ZIPs are checked into `phase0/source_archives/` and validated by SHA-256 in CI; the original ZIPs have not been edited.

**Documented test-only amendment:** `tests/test_app.py` uses a deterministic demo timestamp so a run near a 15-minute expiry does not intermittently return HTTP 409. The original archived file SHA is preserved as `original_sha256` in the manifest; the transferred file has its own new SHA. No trading logic was changed.

## Clean install
Python 3.13 and an internet-enabled package-index connection (or package cache) are required.

```sh
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock.txt
DEMO_MODE=1 AUTO_PAPER=0 python -m pytest -q
python phase0/verify_transfer.py --checkout . --require-archives
```

Never paste API keys into files, code, or chat. Admin token is not required for the
offline tests. For AXIOM research mode, run only with DEMO_MODE=1 and AUTO_PAPER=0.

## What is deliberately excluded
- `.env` files, actual tokens, private keys, SQLite files and cloud credentials
- auto-deploy configs (`render.yaml`, `Procfile`) and live deployment
- source code copied wholesale from external candidate repositories
- any pretense that the external audit archives have been reconciled

## Evidence and status
- `phase0/transfer_manifest.json`: original file hashes and source lineage
- `phase0/import_inventory.json`: Python static import scan
- `phase0/dependencies.json`: external dependencies and source inputs
- `phase0/SOURCE_RECONCILIATION.md`: provenance and open issues
- `phase0/ACCEPTANCE.md`: transfer gate and sign-off state

**Phase 0 gate is pending** until clean dependency installation and GitHub Actions are observed, the named audit archive versions and original commit reference are reconciled or explicitly waived, and the user signs off. A new GitHub commit pins this transfer *going forward* but is not an original legacy ZIP commit.
