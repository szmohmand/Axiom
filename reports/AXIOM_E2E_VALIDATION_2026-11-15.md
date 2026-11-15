# AXIOM v2 — End-to-End Integration Validation

**Test date:** November 15, 2026 (America/New_York)  
**Repository:** [`szmohmand/Axiom`](https://github.com/szmohmand/Axiom), `main` only  
**Validated source checkpoint:** `023fe7c2b2ec95b2cd5837c7579134323cbc5c50`  
**Scope:** current prototype, synthetic full-contract lifecycle, local HTTP service and browser, real **public read-only** feed smoke. No user funds, live orders, deployments or credentials.  
**Overall decision:** **PARTIAL PASS — connected happy-path operations work, but two fault-health defects remain and sustained real-world operation is not yet validated.**

## 1. Methodology and source integrity

- Confirmed locally executed application source files `app/main.py`, `app/engine.py`, `app/ensemble.py`, `app/feeds.py`, `app/storage.py` matched the corresponding `szmohmand/Axiom/main` Git blob SHA values exactly, prior to the read-only test additions.
- The existing 21 automated tests passed unmodified. The new 7-scenario synthetic integration module was added in `tests/test_e2e_synthetic.py`. It includes 5 passing correctness checks and **2 strict expected failures** (`xfail`) representing confirmed deficiencies; the final GitHub CI run passed **26 tests with 2 expected failures**. Expected failure does not mean functionality is correct.
- Inspected API and forecasting code, added a separate provider smoke test (`tests/live_readonly_smoke.py`) and a manual-dispatch/read-only workflow (`.github/workflows/axiom-live-readonly-smoke.yml`). **No changes** were made to the application/strategy code.
- Repeated the FastAPI server and worker in an isolated subprocess with unique local SQLite files and demo mode. Browser presentation was checked using Chromium/Playwright and the unmodified dashboard with actual local API JSON injected into its fetch call. Direct browser navigation to localhost was blocked by this sandbox; the HTTP routes were exercised by real HTTP requests separately.

## 2. Component-by-component test outcomes

| Component / boundary | Test | Status | Finding |
|---|---|---|---|
| Clean install, locked dependencies, original source archive checks | GitHub Actions CI | **PASS** | Fresh Python 3.13 install; original source/ZIP checks passed. |
| Kalshi live contract discovery | Live public GET, Nov. 15 2026 ~10:16 ET | **PASS (snapshot)** | Open `KXBTC15M` contract returned with target, expiry, YES ask. |
| Coinbase spot and candles | Live public GET | **PASS (snapshot)** | BTC ticker returned; 65 one-minute candles, newest timestamp age 16 s. |
| Data → three prediction engines + Kalshi baseline | Live public data and 7 synthetic scenarios | **PASS (functional)** | All three engine values available; independent forecast did not change when only Kalshi midpoint was changed. Calibration is not established. |
| Independent BTC spot scalping calculation | Live public data and synthetic lifecycle | **PASS (functional)** | Real snapshot yielded `SHORT`; synthetic tests exercised LONG/SHORT/WAIT decision boundary. Not profitability-validated. |
| Contract opportunity screen | Live public data and synthetic lifecycle | **PASS (functional)** | Returned `WAIT` on live snapshot; fee and quote checks ran. Does not verify actual fill costs. |
| 15-minute lifecycle and snapshots | Synthetic clock, one complete contract | **PASS (synthetic)** | 14m/10m/5m/1m checkpoints produced 5 rows each = 20 forecasts and baseline snapshots. |
| Immutable first call and automatic simulated paper entry | Synthetic lifecycle | **PASS (synthetic)** | First call after sustained confidence; one simulated contract entry. Duplicate prevention validated. |
| Manual YES and NO simulated entries | FastAPI TestClient | **PASS (synthetic)** | Authorized YES/NO, invalid side/credentials rejected; late/stale snapshots rejected. |
| Official-result grading and model scorecards | Synthetic result provider plus read-only real Kalshi historical result | **PASS (functional)** | YES and NO synthetic outcomes graded correctly; Kalshi historical result lookup matched results listing. No live forecast outcome was observed end to end. |
| Paper P&L and grading idempotence | Synthetic ledger | **PASS (synthetic)** | Gross payoff computed for YES/NO; repeat grading did not double-count. Fees and slippage not included in gross ledger. |
| SQLite persistence and worker restart | Live local server, two process starts | **PASS (synthetic)** | Observation rows 1→3 before restart, then 4→5 after restart; 0 automatic paper entries. |
| CSV export / HTTP authorization | Local real HTTP + TestClient | **PASS (local)** | All four CSV kinds returned with authorization; unauthenticated export blocked. |
| Dashboard API + mobile/desktop DOM | Uvicorn real HTTP, Chromium injected local API JSON | **PASS with limitation** | `/health`, `/api/state`, `/` served; responsive layouts 390px/1280px showed engine data, no JS errors or horizontal overflow. Browser direct `127.0.0.1` blocked by sandbox administrator; no hosted mobile test. |
| Kalshi/Coinbase injected failures in LIVE mode | Synthetic provider fault injection | **PASS (specific cases)** | Provider errors surfaced; status degraded; no new unreliable ledger entries. |
| Settlement endpoint exception visibility | Synthetic fault injection | **FAIL — confirmed defect** | `grade_once()` swallows settlement errors. Unresolved records remain, but user-facing health does not report settlement outage. |
| DEMO feed exception health | Synthetic fault injection | **FAIL — confirmed defect** | `status='DEMO'` and `/health.ok=true` can remain despite a failing demo feed; `/api/state.errors` contains the error. |
| Sustained real 15-minute contract lifecycle / long-term benchmark accuracy | Outside test scope | **NOT VERIFIED** | Single real feed snapshot is not longitudinal data. No accuracy, calibration, profitability or production uptime claim. |

## 3. Actual recorded evidence

- **GitHub CI after installing permanent E2E regression tests:** [run 43729645604](https://github.com/szmohmand/Axiom/actions/runs/43729645604), success, 26 passing, 2 marked `xfail`.
- **Live public feed and model pipeline (read-only):** [run 43728909683](https://github.com/szmohmand/Axiom/actions/runs/43728909683), success, at `2026-11-15T15:16:16Z`. Kalshi market `KXBTC15M-26NOV151030-30` returned with 824 seconds remaining and a published target; Coinbase candle count 65; all three independent model modules and quote-derived market baseline returned available outputs; scalp `SHORT`, opportunity `WAIT`. Historical settlement readback for `KXBTC15M-26NOV151015-15` agreed with public resolved-market listing. Note: engine estimates are separate formulas, not statistically independent information sources.
- **Local complete synthetic lifecycle:** 7 external scenario tests passed; permanent regression version shows 5 correctness passes and 2 expected failure cases. Synthetic paper outcome YES and NO pathways validated; 20 same-contract engine/checkpoint rows in the YES case.
- **Local real Uvicorn HTTP smoke:** `/`, `/health`, `/api/state`, authorized and unauthorized CSV exports all behaved as tested; no real order API was invoked.
- **Browser screen capture:** `AXIOM_mobile_e2e.png` at 390×4520 and `AXIOM_desktop_e2e.png` at 1280×2656. In-browser AJAX was fed the real local API snapshot because direct loopback navigation was administratively blocked.
- **Worker/restart:** `worker_lifecycle_results.json` confirms periodic observations persisted across process restart.

## 4. Defects and recommended minimal corrections

**D1 — Settlement failures hidden (medium severity, high diagnostic impact).** `app/main.py:grade_once` catches exceptions and immediately drops them (`except Exception: pass`). The bot retains unresolved records and does not fake settlements, but it cannot tell the operator that official-result retrieval is failing. **Minimal correction:** record a bounded `settlement` error in shared state and health, preserve unresolved rows, clear the error only on successful subsequent retrieval, and test network errors, rate limits and invalid responses. Keep outcome labels based only on the real Kalshi result.

**D2 — Demo health shows false green (low-to-medium severity).** `app/main.py:update_once` always sets the visible status to `DEMO` when `DEMO_MODE=1`, even when it captures feed errors. `/health.ok` therefore says `true` in such scenarios. **Minimal correction:** preserve a separate `mode='DEMO'` label while setting health `status='DEGRADED'` on errors; include a regression test that must then pass.

Neither defect requires rewriting forecasting algorithms, changing database schema, connecting trading accounts, or migrating credentials. The two regression tests are intentionally marked as expected failures until corrected.

## 5. What this proves — and what it does not

**Supported:** The existing integrated forecasting, separate scalp calculation, hypothetical opportunity selection, local UI/API, authenticated manual paper entry, immutable snapshots, official-result grading logic, exports and SQLite persistence can work together in fully controlled synthetic scenarios. The current public Kalshi/Coinbase read-only integrations completed one real-market pass. The background worker persisted state over repeated polls and restart.

**Not supported:** A proven trading edge; calibrated probabilities; accurate CF Benchmarks BRTI-based predictive input; any actual trades/fills; real-world 15-minute forward accuracy; a live deployed mobile site; continuous production stability; performance under high load; full security audit; or every possible API/provider failure mode. The `WAIT` decision in the real-market example is expected and does not signal a malfunction.

**Repository safeguards:** Only `szmohmand/Axiom` `main` was used. No branches or other repositories were created/modified, no live orders, and no Render or Supabase deployments. Code changes were limited to **new test scripts/workflows**; application source remains as it was before this E2E examination.

**Disposition:** **Functional E2E baseline usable for next development step, but not all-component PASS.** Fix D1 and D2 with small changes, then rerun the same synthetic and live-read-only CI gates before accepting health reliability.