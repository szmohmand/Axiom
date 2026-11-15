# AXIOM Phase 0 — Transfer manifest sign-off record

**Source baseline:** `AXIOM_v2_Multi_Engine_Research_Bot.zip`, SHA-256 in `transfer_manifest.json`.

**Prepared by:** AXIOM Phase 0 technical transfer (local verification only)

**Technical evidence:** 20 copied files match source archive; 21/21 offline tests pass; 22 Python dependency versions pinned from local Python 3.13 installation; public source references noted; no actual credentials migrated.

**Exceptions requiring disposition before acceptance:**

1. Original source Git commit SHA is not recoverable from the ZIP alone; archive SHA-256 is the exact alternative. Record acceptance of hash-only provenance, or provide original repo/commit evidence.
2. Named audit archive versions are not present among the AXIOM source ZIPs; research PDFs are identified separately and must not be treated as formal audit archives. Supply those archives or explicitly exclude them from this transfer's source of truth.
3. A fresh install in an empty Python venv could not be completed without network/cache access. Run `requirements.lock.txt` in network-enabled CI and preserve logs.
4. Remote private GitHub repository creation / hosted CI execution is not possible using current available GitHub connector actions. Local Git bundle is provided for import into a new private repository.

**Sign-off:** PENDING. No user, independent reviewer, or production owner has approved this manifest.

Reviewer: _not yet signed_

Date: _not yet signed_

Disposition of exceptions: _not yet recorded_

Decision: `PENDING` (not PASS)
