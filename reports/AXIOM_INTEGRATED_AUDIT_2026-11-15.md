# AXIOM — repeat end-to-end audit and corrective actions

**Date:** 2026-11-15  
**Authorized repository:** `szmohmand/Axiom` (existing `main`, no other repositories)  
**Scope:** BTC/Kalshi experimental research and *simulated* trade ledger; no real orders, credentials, deployment, external service configuration, or original v1/v2 archive modifications.

## Overall result

A complete synthetic 15-minute contract was exercised through its 14m/10m/5m/1m checkpoints, three experimental forecasts plus Kalshi baseline, independent scalp lens, paper position, first call, settlement grading, scorecards, CSV exports, server API and recovery. The existing complete-cycle and recovery tests remain intact. The second audit added regression cases for problems the earlier 36-test suite had not caught.

**Post-repair local verification:** 49 Python tests passing, frozen-archive integrity checker passing, Python compilation passing; running FastAPI server returned HTTP 200 with four model rows and 62 demo candles. Mobile Chromium rendering was exercised using the *real server HTML and JSON delivered by a browser-side fixture* because direct localhost Chromium navigation is blocked in this environment; healthy, feed-error and HTTP-503 ledger-error UI states all rendered correctly. This is *not* an on-device iPhone test and *not* a 24/7 production reliability test.

## Verified defects and repairs

| Finding | What was wrong | Corrective action / regression |
|---|---|---|
| **A1: NO-side spread incorrectly calculated** | `execution_screen` tested YES spread even when recommending a NO entry. A synthetic 20-cent NO spread falsely qualified when YES spread was 2 cents. | Calculate the chosen side's own ask-minus-bid and require `0 <= spread <= 0.04`; test tight/wide/crossed YES and NO books. |
| **A2: Manual paper entry during source outage** | Fresh Kalshi market data and an old current snapshot allowed `/api/paper` even with Coinbase feed failed and health DEGRADED. | Require current, healthy system snapshot; reject unhealthy/stale/crossed-quote paper entries. Dashboard buttons follow same health gate. |
| **A3: Stale directions still displayed** | Worker heartbeat could be stale while prior LONG/SHORT/YES/NO recommendation remained visible in `/api/state`. | Change current recommendations to WAIT and mark estimates unavailable on stale-worker detection; disable paper entry. |
| **A4: Invalid candle chronology** | Future-dated and discontinuous candles could be treated as current one-minute data, contaminating volatility/EMA calculations. | Detect future candles and missing/duplicate/non-1m intervals; fail closed and recover once fresh continuous candles return. |
| **A5: Confidence hold survived missing inputs** | Failed market poll did not reset `watches`; signal could claim a 10-second sustained hold across an unobserved interval. | Explicitly reset uncommitted confidence watches on feed/model error; immutable past calls unchanged. |
| **A6: Starved settlement grading** | Repeated `UNION ... LIMIT 50` returned the same 50 unresolved markets, preventing newer contracts from ever being checked. Reproduced with 70 contracts. | Deterministic sorted round-robin cursor with wraparound; newer settled markets graded without inventing results for older pending contracts. |
| **A7: Database error hidden by health** | `/api/state` crashed HTTP 500 on ledger read failure while `/health` still returned green. | Detect ledger read/connection errors, emit explicit health-DEGRADED HTTP 503 with JSON explanation, preserve the error until a successful probe/read, suspend simulated entries. |
| **A8: Browser hid actual 503 cause** | UI classified any non-200 `/api/state` as "cannot contact server" even when the server provided a structured ledger error. | Read and render the structured response even on HTTP 503, with unavailable historical metrics shown as dashes instead of fabricated zeros. |
| **A9: Automatic paper vs. manual health gate** | Automatic simulated entries could still be considered while prior settlement/ledger faults were active, inconsistent with manual readiness. | Pause paper opportunities/automatic entries during persistent settlement or ledger faults, without suppressing collection of valid independent forecast observations. |
| **A10: Health HTTP transport code** | Degraded status reported HTTP 200, so simple external health clients might count failures as healthy. | `/health` returns HTTP 503 for STARTING/DEGRADED/ERROR and HTTP 200 only for healthy DEMO/LIVE. |

## Repeat end-to-end evidence

- **Synthetic lifecycle:** 14m / 10m / 5m / 1m checkpoints; every engine and consensus snapshotted; first-call and simulated paper position; YES/NO official-result grading via controlled mock; repeated grading is idempotent; records survive SQLite reopen.
- **External feeds (separate read-only workflow):** Kalshi active 15-minute contract and official settled result, Coinbase BTC spot and 1-minute candles, three engines, scalp and opportunity check. No credentials or orders. GitHub Actions real-feed verification is tracked separately from synthetic tests.
- **HTTP/security:** `/`, `/health`, `/api/state`, authenticated simulated paper endpoint, four authorized CSV exports; rejected unauthenticated, duplicate, stale, expired, crossed-price and degraded-health entries.
- **Failure transitions:** market/spot/candle outages; future/gapped candles; stale worker; settlement API exception; invalid official result; ledger read/connection failure; rollback during grading; independent recovery of each error; no fabricated official results.
- **UI:** confirmed four engine rows and paper controls on healthy demo state; controls disabled and specific errors shown during injected feed and ledger errors; no live orders.
- **Integrity:** Phase 0 v1/v2 ZIP SHA-256 checks and archive provenance retained. No source archives, credentials, or deployment configuration were changed.

## Important limitations / separate development work

The passes above establish **functional consistency within the tested scenarios**, not actual probability calibration, profitability or sustained production uptime. In particular: Coinbase spot is not CF Benchmarks BRTI; forecasts are experimental and correlated; no verified historical out-of-sample accuracy or fill/slippage model exists; and there is no live deployed iPhone-accessible instance being monitored continuously. A public live-data snapshot or a single GitHub Actions run cannot prove all market conditions behave correctly. The archive's original historical Git commit and exact audit ZIP versions remain unresolved Phase 0 provenance items, not regressions introduced by this audit.

**Policy:** Preserve the two source ZIPs and the current project; continue only in `szmohmand/Axiom`. Any future performance assertions require a separate chronological real-market evaluation. No real trading was enabled.
