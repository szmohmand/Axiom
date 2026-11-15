# AXIOM Phase 0 — technical transfer acceptance

**Technical transfer: VERIFIED on `szmohmand/Axiom` (main).** Formal complete gate is **PENDING HISTORICAL DISPOSITION + OWNER SIGN-OFF**.

| Criterion | Status | Evidence |
|---|---|---|
| Frozen v1/v2 original ZIP files | PASS | `phase0/source_archives/`, exact SHA-256 in `transfer_manifest.json` |
| V2 transferred source identity | PASS | CI `verify_transfer.py` validates all 20 transferred source hashes, including documented one-file test amendment |
| Reusable code, imports, licenses and external dependencies | PASS | Existing inventories, source catalog and notices retained |
| New bot requirements | PASS (transfer scope) | `phase0/NEW_BOT_REQUIREMENTS.md`; no claims of live validation |
| No credentials, data stores or real orders migrated | PASS (scoped inspection) | Protected `.gitignore`; code only; no secrets copied |
| Dedicated GitHub repository | PASS | [Axiom repository](https://github.com/szmohmand/Axiom) on `main`, initialized without any other repo or branch changes |
| Clean Python 3.13 dependency install | PASS | [GitHub Actions run](https://github.com/szmohmand/Axiom/actions/runs/43723325225), install locked 24 dependencies |
| Source and frozen ZIP integrity in GitHub CI | PASS | [GitHub Actions run](https://github.com/szmohmand/Axiom/actions/runs/43723325225), transfer verification success |
| Original 19 + Phase 0 2 offline tests | PASS (21/21) | [GitHub Actions run](https://github.com/szmohmand/Axiom/actions/runs/43723325225); synthetic/offline only |
| CI workflow installed and executable | PASS | `.github/workflows/phase0-ci.yml`; push to `main` and manual dispatch |
| Original legacy ZIP Git commit SHA | UNRESOLVED | Original ZIPs have no Git history; SHA-256 is byte-identity substitute |
| Exact AXIOM audit archive ZIP versions | UNRESOLVED | Available research PDFs are hashed but not validated audit ZIPs |
| User's transfer manifest sign-off | PENDING | No explicit signed acceptance of exceptions recorded |

**Frozen source import checkpoint:** [`5537d61752d3`](https://github.com/szmohmand/Axiom/commit/5537d61752d3212f0934b727d664ad63c1c1a850).

**Interpretation:** repository/CI infrastructure is ready for ongoing research development. This does **not** prove any live forecast accuracy, model calibration, trading profitability, or approval for automatic order execution. Do not present the formal historical-source/sign-off gate as completed.
