# Phase 0 — source reconciliation and exceptions

## Definitively frozen

- The exact v1 and v2 AXIOM ZIPs are identified by their SHA-256 values in `transfer_manifest.json`.
- Every transferred file has a SHA-256 and byte count. One test (`tests/test_app.py`) was deliberately amended after the source freeze; its original ZIP hash is retained in `original_sha256`, and the new test hash is separately recorded. No application code was modified.
- Actual AXIOM v2 implementation requirements are recorded from its README and test suite.
- Research papers are referenced as research PDFs by file hash, **not as audit ZIPs**.
- The destination was the initially empty `szmohmand/Axiom` repository. Its existing `main` branch now holds the transfer; no other repository, branch or deployment was touched. Branches within `Axiom` may be created in future if needed, as authorized subsequently.
- Only the transferred AXIOM-owned source is in this clean baseline; experimental imports
  from external codebases have not been added.

## Inherited AXIOM v2 behavior (not live performance certification)

- BTC 15-minute Kalshi forecasting, 3 experimental engines and a market-price baseline.
- Independent EMA/ATR spot scalping guidance, simulated-only trading and immutable forecast scoring.
- Kalshi-reported outcomes for grading, with Coinbase spot as imperfect BRTI proxy.
- FastAPI app with mobile HTML UI; CSV exports and SQLite file storage.
- One-instance prototype, no automated live orders, no deployment or real-money credentials.

## Conflicting or missing evidence — not silently reconciled

1. **Original commit**: no `.git` metadata inside v1 or v2 ZIP; exact artifact hash is known,
   original upstream commit is not. A new local Phase 0 commit cannot replace that historical SHA.
2. **Audit archive versions**: no exact AXIOM audit archive ZIP with declared archive version
   accompanies the retrieved AXIOM source materials. Three research PDFs are recorded
   separately by hash; they are not promoted to authoritative audit archives.
3. **Different project requirements**: the 2026-11-06 *BTC Intelligence Engine — Phase 0*
   specification refers to a different, more general project and had a no-Kalshi-integration
   scope. It is not silently treated as the AXIOM spec. AXIOM v2's README and user directions
   take precedence for this AXIOM-only baseline.
4. **Live validity**: 19 previous offline tests and simulated full-cycle check do not establish
   live reliability, forecast calibration, or trading profitability.
5. **Third-party candidates**: research shows publicly accessible projects, but only two
   adapted methods were present in AXIOM v2. Further additions need their own source snapshots,
   attribution, and tests; no vendor source code has been transferred here.

## Safety boundaries

Do not migrate secrets, publish private records, access or alter other repositories/branches, or change Render/Supabase services. The only authorized remote is `szmohmand/Axiom`, currently using `main`; future in-repository branches are permitted as needed. Its public visibility was verified and original source ZIPs were scanned for common credential patterns before publishing.
