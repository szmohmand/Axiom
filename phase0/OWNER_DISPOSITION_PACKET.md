# AXIOM Phase 0 — owner disposition packet (not a signature)

**Status: PENDING OWNER DISPOSITION.** This packet closes the *documentation gap*, not the historical evidence gap. No agent may sign for the owner or invent unavailable upstream history.

## What is technically verified

- The immutable original v1 ZIP (`AXIOM_Kalshi_BTC_Bot_v1.zip`) is stored at `phase0/source_archives/`; SHA-256 `6657e895ba4e9a850f15c1c9cdc9c7e2c64dc2139e4e82cfbb3e53504066ea43`.
- The immutable original v2 ZIP (`AXIOM_v2_Multi_Engine_Research_Bot.zip`) is stored there; SHA-256 `bdb17eac22d54cd3f2a34704f71a88c11830509624a131150a78fc334c5a6323`.
- The frozen v2 source transfer has 20 individually verified source file identities; the deterministic test amendment has its original ZIP hash and later test hash separately documented.
- The new AXIOM repository import checkpoint is `5537d61752d3212f0934b727d664ad63c1c1a850`, **not** the unknown historical source commit.
- Exact source byte identity and archived file integrity are checked by `python phase0/verify_transfer.py --checkout . --require-archives` and by independent corruption/credential failure tests.
- Three historical research PDFs have hashes in `phase0/transfer_manifest.json`, but are **not** substituted for missing audit archive ZIP versions.

## Missing original facts that cannot be manufactured

1. The ZIPs do not contain original upstream Git history. An original upstream commit SHA cannot be reconstructed from file hashes.
2. The separately named historical AXIOM audit archive ZIP versions were not present among the identified original transfer artifacts. A PDF is not an archive.
3. The owner has not provided an explicit disposition or signed the historical exceptions.

## Decision for owner (choose explicitly in a later authorized review)

- **Accept documented source-hash provenance** instead of an unavailable upstream commit and acknowledge the unavailable exact audit ZIP versions, without claiming they were recovered; or
- **Supply the missing upstream repository evidence and exact audit archives** for independent verification.

Until the owner chooses, `phase0/ACCEPTANCE.md` and `phase0/SIGNOFF_TEMPLATE.md` remain **PENDING**, correctly. This does not prevent safe research-only testing of independently verified current code; it prevents falsely certifying a formal historical transfer sign-off.

**No real trading, deployment, credential upload, private account export or GitHub merge authorized by this packet.**
