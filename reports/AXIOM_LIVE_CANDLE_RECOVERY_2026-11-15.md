# AXIOM live-data recovery and whole-system non-regression audit

**Date:** November 15, 2026  
**Repository:** `szmohmand/Axiom` only  
**Previously verified and untouched `main` checkpoint:** `2694dd0faf01479dea396e81535605dbf6e2111f`; recovery branch `verified/2026-11-15-2694dd0`  
**Candidate:** `audit/coinbase-candle-authentic-recovery-2026-11-15` (Axiom-only isolated branch)  
**Scope:** Actual public read-only Coinbase/Kalshi data and unchanged experimental BTC15m decision engines; no real orders, server deployment, credential or infrastructure changes.

## Finding A14 — unavailable forecasts after authentic Coinbase one-minute candle gaps

- **Original observed failure:** At 2026-11-15 17:55 UTC Coinbase Exchange's BTC-USD one-minute candle endpoint omitted an entire minute, producing a 120-second jump. The app's correctly strict 61-minute guard rejected the entire modeled lookback. At that stage it would not resume forecasts until the omitted minute aged beyond the fixed 61-bar window.
- **Independent observation:** Coinbase's public Advanced Trade endpoint omits that same historical minute; switching APIs is not a valid recovery. [Public source comparison](https://github.com/szmohmand/Axiom/actions/runs/43755527793).
- **Data coverage:** A separate **12-hour** source audit inspected 720 expected minutes and found 719 authentic candles and **one** absent minute (17:55 UTC). No other gaps or HTTP retrieval failures occurred in that bounded sample. This does not establish universal or future data completeness. [Coverage evidence](https://github.com/szmohmand/Axiom/actions/runs/43757343909).
- **Repair:** The read-only Coinbase feed now isolates the most recent consecutive suffix after any older authentic whole-minute gap. **Only if at least 31 real, consecutive, one-minute bars remain**, the existing engines may use the shorter history. No missing candle is synthesized, interpolated, duplicated or re-timestamped. If the gap lies within the newest 30 bars, or cadence is not one-minute, the strict existing guard still returns DEGRADED, withholds trade opportunities and keeps paper entry gates closed.
- **Original-behavior preservation:** With fully continuous source history, the feed returns its original normalized data **without modification** and all original model and scalping formula code is untouched. All historical permanent regressions still run.
- **Transparency:** The source quality and genuine-bar count are exposed in `/api/state.candle_quality`; the mobile source-health panel explicitly identifies shortened authentic history, without falsely reporting full historical coverage.
- **Actual missing-minute replay:** [Read-only source and recovery run](https://github.com/szmohmand/Axiom/actions/runs/43756458343) fetched the real history covering the incident, verified the source still omitted 17:55, selected **60 genuinely present consecutive candles** and confirmed **zero fabricated records**.

## Separate Kalshi rollover timing observation

A single live integration check at approximately **2026-11-15 20:15:25 UTC** encountered **no active Kalshi KXBTC15M contract** during market rollover. AXIOM correctly reported `DEGRADED`, HTTP 503, and no actionable Kalshi opportunity; a separate BTC spot scalp lens remained independent. A one-time health check should not label a correctly fail-closed 15-minute boundary as a permanent application defect.

The live smoke test was strengthened to retry a bounded number of times, **only** when the sole error is "No active Kalshi BTC15M market available." It explicitly verifies the degraded failure state on each retry, requires a **real active contract** for success and fails if the absence persists. No fake or stale contract is substituted.

## Historical / current / foreseeable-impact review

| Component and boundary | Verification | Disposition |
|---|---|---|
| Frozen original v1/v2 archives, provenance, permanent older regressions | Existing GitHub full CI gate and 19 permanent regression records | PASS on candidate CI |
| Coinbase source parser and genuine history identity | No-gap identity test, real-normalization test, missing older minute and 31/30 boundary tests, nonminute/duplicate/reversed rejection | PASS |
| Kalshi contract and prices | Existing market/quote/provider tests; bounded rollover failure and recovery behavior | PASS for tested conditions |
| Three experimental forecasts, Kalshi comparison, scalping and execution | Existing engine tests, full synthetic cycle and new real-history 31+ model test | PASS functional only, no probability calibration claim |
| Paper entry, observation, snapshots, SQLite rollback, settlement and restart | All prior end-to-end, persistence, concurrency and failure tests kept | PASS on candidate full suite |
| HTTP and mobile UI | Prior API/browser regressions; new `/api/state` quality metadata and explicit mobile source notice; degraded status still fail-closed | PASS for automated tested paths |
| Historical exact 17:55 source absence | Separate actual Coinbase historical query and recovery assertions | PASS |
| 12-hour current-source completeness | 719 genuine/720 expected one-minute bars | OBSERVED (not guarantee of continuity) |
| Ongoing 15-minute real-market observation | Dedicated read-only continuity workflow including contract rollover | **PENDING until completed and inspected** |
| True deployed production operation | No Axiom hosting or service deployment authorized/verified in this code-only audit | NOT ESTABLISHED |

## Acceptance rules

- **No alteration to pricing/formula methods, paper settlement rules, original source archives, credentials, or other repositories.**
- New finding `A14` has permanent synthetic and provider regression tests in `tests/test_coinbase_real_candle_recovery.py` and the non-shrinking `reports/REGRESSION_HISTORY.json`.
- No historical test is deleted, skipped or changed to expected failure; run the complete original+new suite on the exact proposed commit, frozen source integrity checks, actual HTTP read-only feeds, full synthetic lifecycle, recovery, concurrency, idempotence and timing checks.
- Read-only provider recovery does **not** establish forecasting accuracy, real trades, fills or official CF BRTI equality. It is impossible to guarantee that future source omissions won't happen. If the last 31 genuine minutes are not consecutive, the system correctly withholds estimates.
- A passing clean-install or one-point API check is insufficient to certify sustained live reliability. **Decision remains BLOCKED until the live continuity observation and all proposed-commit CI checks are inspected.** If a consequential failure occurs, repair in the isolated branch and repeat the full gates; do not merge a failing candidate.

## Evidence links

- [Read-only source comparison](https://github.com/szmohmand/Axiom/actions/runs/43755527793)
- [Real missing-minute source and recovery](https://github.com/szmohmand/Axiom/actions/runs/43756458343)
- [12-hour source completeness investigation](https://github.com/szmohmand/Axiom/actions/runs/43757343909)
- [Full-suite, integrity and 19 historical regression checks](https://github.com/szmohmand/Axiom/actions/runs/43757348769)
- [Axiom-only draft pull request #5](https://github.com/szmohmand/Axiom/pull/5)
