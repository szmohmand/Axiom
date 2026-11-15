# AXIOM isolated challenger safety / acceptance report — 2026-11-15

## Exact scope and acceptance decision

**Candidate branch:** research/isolated-btc-challengers-2026-11-15
**Preserved base:** b12be3758049b6766dda8fefad06611bf41ada2e
**Existing recovery reference:** verified/2026-11-15-b12be37 (must never move)
**Protected application runtime:** 902f7d7dfd7a4a952b4afc2019f01a599af43355
**Base CI:** full suite https://github.com/szmohmand/Axiom/actions/runs/43764899404 and real read-only https://github.com/szmohmand/Axiom/actions/runs/43764899402

**Current engineering decision:** PASS for an isolated, opt-in, read-only
research candidate's existing-system non-regression in recorded tests.
**Scientific/rollout decision:** BLOCKED for any claim that the original
complete source bots have been ported or any challenger has demonstrated an
accuracy/alpha improvement. No real matched historical dataset or model
performance report has been collected in this phase. Do not merge into the
active model path, deploy, schedule collector, or execute orders.

This report records a bounded test result. It cannot certify every possible
future API change, market condition, or as-yet-unwritten code change.

## Impact map: what changed, what must remain identical

Candidate additions: research/challenger_lab.py, research/record_live.py,
research/README.md, tests/test_challenger_lab.py, this evidence document.
Policy-only additions: A15 entry in reports/REGRESSION_HISTORY.json and
corresponding A15 required floor in phase0/check_regression_history.py.

**No edits to:** app/engine.py, app/ensemble.py, app/feeds.py, app/main.py,
app/storage.py, app/static/index.html, frozen v1/v2 source archives,
requirements or lockfile, any deployment configuration, workers,
endpoints, order/paper permissions, settlement outcomes or database schema.

Read-only research imports AXIOM's existing engine_pack for offline
comparison, but the application never imports or invokes research. The
standalone recorder imports the existing LiveProvider GET interfaces, never
app.main or AXIOM's SQLite Ledger. The collector writes only to ignored
data/challenger_lab and runs only when explicitly called by a Python command.

## Historical / current / foreseeable safety evidence

| Dimension | Evidence reviewed | Decision |
|---|---|---|
| Previously verified historical baseline | immutable recovery refs b12be and 902f; existing archive integrity checker and all historical pytest selectors | PASS for tested scope |
| Permanent regressions | 19 original records retained; new A15 protects causal input timing, independent probabilities, result separation and checkpoint immutability | PASS for tested scope |
| Existing forecasting, Kalshi quotes and scalping | no application source diff; existing full synthetic and individual model tests run as part of complete suite | PASS for regression scope, not performance |
| Real sources and fail-closed behavior | original real Kalshi/Coinbase read-only app smoke CI unchanged; candidate guards missing target, nonminute candles, future input timestamps, stale spot/quotes, insufficient bars | PASS for bounded source checks |
| Ledger, paper controls, official settlement worker, storage and restart | zero application/ledger edits; all existing end-to-end, security, consistency, rollback, concurrency, grading and restart tests remain in full suite | PASS for unchanged behavior in tests |
| Research output integrity | contract-level chronological holds, no labels in observations, official results in separate file, no source price substituted for official outcome, duplicate prevention, paired Brier on identical ticker/checkpoint | PASS for synthetic methodological fixtures |
| One-shot collector | deterministic fake-provider tests verify one append per contract/checkpoint, unknown targets fail closed, separate official settlement record is idempotent | PASS for tested offline path only |
| Real training and raw market replay | Original historical AXIOM engine_snapshots lack the necessary raw point-in-time feature inputs; real challenger observations and outcomes not yet supplied | BLOCKED for real performance claims |
| Model implementation parity | Schen original uses per-second EWMA; our M0 uses one-minute volatility proxy. KalshiBot full Swift promotion and tick inputs are not ported. XGB source contains Kalshi-quote-dependent features removed from isolated nine-feature retraining design | BLOCKED for source-level original-model equivalence |
| External and future conditions | Exchange-side quote timestamps, short-lived source outages, genuine BRTI basis, missing index ticks, XGB optional dependency, calendar/multiple volatility regimes | DOCUMENTED; live reliability and alpha not verified |

## Actual GitHub tests recorded

- Earlier candidate with tests had two **test-fixture** failures, visible at https://github.com/szmohmand/Axiom/actions/runs/43765728697. The assertion wrongly assumed no other pytest file had imported app.main and used non-minute-aligned synthetic bars in a 45s test. Both were corrected in the test fixture only, without weakening the application's regression checks.
- Corrected candidate full suite and read-only integration passed: https://github.com/szmohmand/Axiom/actions/runs/43765837585 and https://github.com/szmohmand/Axiom/actions/runs/43765837592.
- Candidate with actual one-shot collection and grading code, plus tests, full suite and smoke passed: https://github.com/szmohmand/Axiom/actions/runs/43766032145 and https://github.com/szmohmand/Axiom/actions/runs/43766032116.
- After making new research A15 regression tests permanent, full suite and read-only smoke passed on commit 0d8b6997753b3f1c7380608d12b37dc07a668f1b:
  https://github.com/szmohmand/Axiom/actions/runs/43766364516 and
  https://github.com/szmohmand/Axiom/actions/runs/43766364564.
- Final candidate commit should also have both workflows passing before any review/merge; this report alone never waives CI.

## Research validity / what has not happened

No original external bot was vendored or executed. Their named ideas have
been implemented as **isolated surrogate challengers**, not exact original
versions. Kalshi midpoint is recorded and scored only as an independent
comparison. No XGBoost package was installed into production. No real
point-in-time contract collection or official challenger grading has been
started, no prediction models have been retrained on real outcomes, and no
economic performance or one-to-two-minute movement foresight is established.

To finish the intended experiment:
collect authentic independent checkpoint inputs and official results;
implement source-level parity where possible; run actual independent
XGBoost training with pinned optional dependencies; verify each model's
causal train/serve parity; evaluate on identical held-out contract groups;
report sample counts, calibration, Brier, comparative CIs, lead time,
regime-specific reliability, and any BRTI basis errors. Only after complete
AXIOM rules and defensible data may a separate promotion proposal be
considered. If a candidate fails, leave the runtime on the preserved baseline.

**Decision:** No change to the live AXIOM decision path is authorized or
needed by this research candidate. PASS of the existing-system check is not
a performance or production release clearance.
