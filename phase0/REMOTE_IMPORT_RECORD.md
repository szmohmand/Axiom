# AXIOM Phase 0 — verified remote import record

- Repository: [szmohmand/Axiom](https://github.com/szmohmand/Axiom) (**public**)
- Target: existing `main`; **no new branch was needed**.
- Frozen-source import commit: [`5537d61752d3212f0934b727d664ad63c1c1a850`](https://github.com/szmohmand/Axiom/commit/5537d61752d3212f0934b727d664ad63c1c1a850)
- Clean-install/transfer/21-test verification: [Actions run #43723325225](https://github.com/szmohmand/Axiom/actions/runs/43723325225), **SUCCESS** (November 15, 2026).
- Two original ZIPs: `phase0/source_archives/`, verified with source SHA-256 checksums in `transfer_manifest.json`.
- Requirement lock now includes `httpx==0.28.1` and `httpcore==1.0.9`, which the fresh install exposed as missing test dependencies.
- CSV CRLF line endings were restored to match the source ZIP exactly.
- Nothing deployed or automatically traded; no repository outside `szmohmand/Axiom` accessed or modified during this import.
- Original ZIP historical Git commit and audit-archive ZIP versions remain unknown; owner sign-off pending.

This document records verification of the **source checkpoint**, not performance of the live trading model.
