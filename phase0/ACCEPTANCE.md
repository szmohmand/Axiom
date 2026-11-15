# AXIOM Phase 0 Gate — acceptance checklist

| Criterion | Status | Evidence |
|---|---|---|
| Frozen legacy ZIP bytes | PASS | transfer_manifest.json includes exact v1/v2 SHA-256 |
| Original legacy ZIP Git commit | OPEN | historical commit unavailable in ZIP |
| Copied-source checksum verification | PASS | 19 byte-identical originals + 1 documented test-only amendment; original ZIP hash independently checked |
| Audit archive versions | OPEN | research PDFs hashed, but not the specified archived audit ZIP versions |
| New AXIOM requirements pinned | PASS (scope register) | NEW_BOT_REQUIREMENTS.md; gaps explicitly noted |
| Reusable files/imports/licenses/dependencies | PASS (inventory) | REUSABLE_CODE_INVENTORY.md + import_inventory.json, dependencies.json, third_party_pins.json |
| No migrated secrets | PASS (scoped inspection) | no actual credentials, keys, databases copied; common secret-pattern scan: no candidates |
| Isolated local Git repository | PASS | verified local source snapshot and 21 tests |
| Dedicated GitHub repository | READY FOR INITIAL COMMIT | existing public `szmohmand/Axiom` was verified empty; **main only**, no branch creation |
| CI workflow defined | PASS (config only) | `.github/workflows/phase0-ci.yml` (networked CI execution not observed) |
| Original AXIOM v2 source tests | PASS AFTER TEST AMENDMENT | 19 tests; one demo-boundary flaky test fixed without changing app code |
| New Phase 0 tests | PASS | 2/2 tests |
| Fresh-venv offline dependency install | BLOCKED | New 3.13 virtualenv cannot resolve `annotated-doc==0.0.4` from offline cache; GitHub Actions must prove fresh install |
| Manifest signed off | PENDING | No user sign-off or final original-commit/audit reconciliation |

**Gate status: NOT PASSED / SIGN-OFF PENDING.**

The local source snapshot and tests are ready for a network-enabled clean-install/CI run. No live trade operation has been tested or approved.
