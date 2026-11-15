# AXIOM — whole-system acceptance audit and corrective record
**Date:** 2026-11-15. **Authorized repository:** `szmohmand/Axiom` only. **Change branch:** `audit/2026-11-15-system-acceptance`. **Last verified baseline:** `88957587e1b4e5a94acc78956821ef3e8ebfdf44` preserved at `verified/2026-11-15-8895758`. **Candidate repair:** `ae772308b62cc3cf4875ca2b87ce8fca40614fd4` plus this evidence/history update. **No live orders, deployment, external account changes, or original archive changes.**

## Decision / applicable scope
**Functionality acceptance candidate: all locally and GitHub-tested controls PASS on the audited branch.** Final promotion is conditional on the PR's full test and read-only integration checks also passing without regression. A clean CI run is evidence about tested code, **not** certification of 24/7 live operation, forecast calibration, BRTI equivalence, financial returns, or unknowable future changes.

## Historical check: what remains unchanged
- Inspected source files, all existing permanent regression tests, Phase 0 frozen v1/v2 archives, the GitHub current verified source checkpoint, and the last integrated audit. Verified original source ZIP fingerprints with `phase0/verify_transfer.py`.
- Application forecast model (`app/engine.py`), experimental ensemble math and fee/quote rules (`app/ensemble.py`), provider adapters (`app/feeds.py`), mobile markup/JS (`app/static/index.html`), original Phase 0 archives and research catalog were **not** edited by this repair. Changes are restricted to forecast polling and grading orchestration, transaction handling, regression tests and audit documents.
- The 15 previous regression classes remain permanently tested, with 3 additional classes A11–A13 appended.

## Confirmed defects (reproduced RED on the preserved implementation)
| ID | Original defect reproduced | Focused correction | Result |
|---|---|---|---|
| A11 | A continuous series of 30-second bars was reported healthy and used as 60-second input. | Require exactly 60-second intervals between normalized one-minute candles; fail closed on bad intervals. | PASS: rejects incorrect cadence and recovers on valid data |
| A12 | An injected failure during engine snapshot persistence left an observation committed, creating a partial research cycle. | Wrap all forecast-cycle observations, immutable snapshots, watches, and optional paper entries in one SQLite transaction under the preexisting re-entrant lock; defer internal commits until success. | PASS: failures of snapshot, first-call and paper recording roll back the entire cycle |
| A13 | A deliberately stalled official settlement check stopped market polling after four cycles. | Separate periodic market polling and settlement grading; use a distinct read-only HTTP session for settlement lookups in live mode. Preserve the existing shared database lock and grading retry rules. | PASS: market polling continues while grading is blocked |

## Component-by-component and connected checks
| Implemented component | Evidence | Gate |
|---|---|---|
| Kalshi / Coinbase adapters | Five new offline contract tests cover active-contract selection, quotes, price/candle normalization, unsettled outcomes, 404 historical fallback, malformed prices and HTTP errors. Live read-only provider smoke also executed on the candidate. | PASS |
| Forecast / ensemble / scalping | Original complete engine tests plus 400 seeded price, volatility, quote and expiration scenarios; unchanged formula blobs compared with baseline. | PASS (functional, not accuracy validation) |
| YES/NO opportunities and guards | Original quote/fee, stale-input, health, crossed-book and paper authorization tests. | PASS |
| Time and input integrity | Future/gapped/duplicated candles, 30-second cadence, stale worker, recovered feed and 15-minute expiry checkpoints tested. | PASS |
| Forecast, watch and paper ledger | Original full contract and idempotent official-result grading, forced snapshot/watch/paper failures, full rollback, 32 concurrent simulated entry attempts and SQLite integrity. | PASS |
| Settlement & scheduler | Repeated grading, 70-contract cursor fairness, result failure/recovery, separate worker during blocked grading, full FastAPI lifespan polling and data persistence after DB reopen. | PASS within simulated conditions |
| HTTP/UI | Started actual FastAPI demo server; `/health` and `/api/state` returned 200 when healthy, complete four-engine state and 62 candles. Chromium mobile view used actual server HTML/JSON via a sandbox-compatible fetch shim. Healthy, failed feed, and ledger HTTP 503 views rendered; degraded paper controls disabled. | PASS for tested HTTP/browser conditions |
| Dependencies and provenance | Original ZIP fingerprint verification, Python compile, clean Python 3.13 GitHub CI install, permanent regression checker. | PASS |

## Verification artifacts
- Local: whole-suite pytest **62 passing tests** on the tested local source set (prior to GitHub integration; counts may differ if the exact prior source suite contains an additional baseline test). Regression-history checker and original source integrity both PASS.
- Candidate GitHub clean-install/full tests: [GitHub Actions #43743256143](https://github.com/szmohmand/Axiom/actions/runs/43743256143), **SUCCESS** for candidate application/tests commit `ae772308b62cc3cf4875ca2b87ce8fca40614fd4`.
- Candidate public **read-only** Kalshi/Coinbase + actual app integration: [GitHub Actions #43743256164](https://github.com/szmohmand/Axiom/actions/runs/43743256164), **SUCCESS**; automatic paper entries disabled, no real orders.
- Proof of defects: A11 and A12 targeted tests failed on the previous implementation; A13 slow-grading poll test failed after four polls. After the fixes all three and historical tests passed locally.

## Forward risks and limitations
- External availability may change; a single successful read-only feed snapshot is not sustained operational testing.
- The calculation uses Coinbase as a **proxy**, not the official CF Benchmarks BRTI price; no calibration or profitable predictive edge is claimed.
- Demo and synthetic contract results cannot substitute for chronological live-contract settlement evaluation.
- Background grading in live mode can still be delayed by provider timeouts and large backlogs; separation prevents it from blocking the market poll, but this audit does not establish a maximum grading latency for unbounded queues.
- Browser rendering was tested with Chromium and real HTML/API responses using an injected fetch shim because direct browser localhost navigation is restricted; this is **not** a native iPhone test.
- Historical upstream ZIP Git commit and exact historical audit archive versions remain unverified provenance questions; no false reconstruction was made.
- Server-side GitHub branch protection could not be confirmed through the connected app; PR/test gate is followed as the AXIOM project engineering rule.

## Acceptance rule
Reject a candidate with any reproduced regression or missing applicable test; use the fixed verified SHA recovery branch instead. This audit does not claim that every imaginable future event is harmless. Each subsequent change must repeat historical/current/foreseeable-impact review and permanent regression tests.
