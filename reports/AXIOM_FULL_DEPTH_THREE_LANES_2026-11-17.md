# AXIOM — Full Aggregated Order-Book / Three-Lane Upgrade (Nov 17, 2026)

## Scope and preserved baseline

- Repository: szmohmand/Axiom only. Preexisting three-model + non-voting shadow research branch at `881b3b8cca4be4fbb1ef6ab3874edca18a766cbe`; default `main` was `b12be3758049b6766dda8fefad06611bf41ada2e` during this work and is **not** modified.
- Candidate implementation branch: `research/full-depth-orderbook-three-lanes-2026-11-17`. No live deployment, real order placement, account trading operations, third-party repository changes, or database edits.

## Original limitation

Prior live code consumed Kalshi top YES/NO bid/ask fields only. It could not distinguish 1 contract from 100 at that ask, and could not estimate book-walk slippage or assess liquidity depth. Meanwhile, the existing paper-entry lane was explicitly based on top quotes. The unrelated independent forecast must not be driven by participant price.

## Exact implementation and dependency map

1. `app/orderbook.py` validates **all currently available aggregated price levels** from `orderbook_fp.yes_dollars` / `no_dollars`; NO bids imply YES asks at 1-price and vice versa; quantities come from fixed-point contract size. Duplicate, crossed, missing, nonfinite, negative or malformed snapshots are rejected. Tracks source ticker, local receipt time, side-specific bid/ask spreads, available quantities, price-level counts and near-best net volume imbalance. This does NOT expose individual order IDs, traders, cancellations, or WebSocket events.
2. `app/feeds.py`: public, read-only `GET /markets/{ticker}/orderbook` with `depth=0` (all available levels). A dedicated two-second timeout keeps optional depth from consuming the ordinary nine-second provider timeout. Separate synthetic demonstration book is explicitly labeled synthetic. No API key, auth, or order endpoint used.
3. `app/depth_intelligence.py`: independent opportunity lane walks the available book for a default illustrative **10 contracts**, computes volume-weighted entry, worst level, bid exit, incomplete depth, spread, slippage and approximate fees. It compares this amount against **AXIOM's independent forecast**; the book does NOT vote in forecasts. It returns a potential YES/NO candidate or WAIT. A separate manual execution lane returns ENTER/WAIT; with an explicitly supplied hypothetical position it can return HOLD/EXIT/WAIT. The code never places orders.
4. `app/main.py`: publishes `orderbook`, `depth_opportunity`, `execution_intelligence`, and optional `paper_position_execution` for **one simulated open paper contract**. Book polling errors do not stop independent BTC forecasting, scalp engine, SQLite history or settlement. Stale market workers suppress depth-entry advice and invalidate the displayed cached book. No changes to ensemble probability math, real-account linkage, paper-entry loop, database schema, or settlement grading.
5. `app/static/index.html`: independently labeled full aggregated book ladder (YES bids + YES asks inferred from NO bids, all available levels), depth-aware opportunity with illustrative size-adjusted entry and estimated discrepancy, manual execution intelligence and simulated-position HOLD/EXIT advice. Original paper widget explicitly labeled legacy top-quote paper screen, not depth-gated.
6. `tests/test_full_depth_lanes.py`: continuous regression coverage for all price levels, bid/ask complement, full/partial sweep, invalid/missing/stale/crossed/orderbook wrong-ticker rejection, forecast invariance to order prices, size-based WAIT, hypothetical entry/exit, source outage recovery, position abstention, bounded HTTP depth request, mobile UI wiring and no-order safety. `tests/live_readonly_smoke.py` now fetches real public full-depth REST and evaluates the distinct lanes.
7. `reports/REGRESSION_HISTORY.json` added A15 with permanent test selectors, retaining 19 previous historical defect records.

## Verified real API observation

At a real public Kalshi BTC15m market `KXBTC15M-26NOV171300-00`, live read-only GitHub Actions retrieved 148 YES bid price levels and 131 NO bid price levels, a published contract target, and valid spot candles. Actual opportunity and execution signals at that moment were WAIT; the independent forecast reported no directional consensus. This is a real API connectivity test, **not** live trading, continuous order-book coverage, verified profitability or market-predictive accuracy.

## Existing behavior and compatibility

- The prior three BTC-derived forecast models continue to vote independently of Kalshi market-price levels; Kalshi price remains a nonvoting comparison. Original non-voting settlement research shadow is preserved.
- Existing top-of-book `opportunity` and simulated paper paths remain operational and unchanged; they are labeled LEGACY and do not claim depth-aware fills. The new depth guidance is separately wired and cannot change that old paper ledger.
- Existing first-call confidence, Coinbase scalp, official Kalshi outcome grading, SQLite snapshots, health/status, admin-token paper controls and data exports remain unchanged.
- A bad or absent order-book response does not generate made-up liquidity or a BUY recommendation. It produces WAIT in the new depth/execution lanes while independent forecasting remains available.

## Verification / release gate

- Targeted unit/integration tests and full existing source-archive/regression-history/pytest suite: PASS on `a8bb15a378ff74dfa438a8c4524590d8606ebd50` (GitHub workflow https://github.com/szmohmand/Axiom/actions/runs/44141360535).
- Public Kalshi + Coinbase read-only smoke and actual app integration: PASS on same commit (https://github.com/szmohmand/Axiom/actions/runs/44141360540).
- Previously unaffected full lifecycle regression and stale/outage tests remain green. No existing regression test weakened or deleted. The historical regression manifest now contains 20 entries.
- **Main/production status:** not merged, not deployed. These tests validate implementation behavior, not order execution or profitability.

## Material limitations / subsequent work

- Kalshi REST returns aggregated price/quantity **levels**, not every individual order. Full continuous microstructure, precise cancellations/absorptions or queue position require validated WebSocket snapshots/deltas plus public trades; this is not implemented.
- A depth snapshot can become stale between receipt and manual entry, and the REST source is polled on the market worker's normal cadence. No guaranteed fill and no market-order endpoint.
- Fee estimate is illustrative; no date/series-specific official execution-fee confirmation. Depth-based edge is an uncalibrated model-price discrepancy, not verified alpha.
- Real user's portfolio/entries are not connected. HOLD/EXIT applies solely to a one-contract simulated paper position or an explicit hypothetical input. Old paper records still use assumed top asks and are not evidence of depth-aware fills.
- No Kalshi authorized trading, no real risk limits or production uptime validation, no official BRTI live calibration. These remain distinct requirements before any future deployment or real execution.

## Acceptance decision

PASS for this **isolated, read-only, non-deployed research integration**, with the stated limits. Does not approve release to main or real trading. Retain prior known-good commit and regression tests. Every later change requires separate validation.