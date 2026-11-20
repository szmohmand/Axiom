# AXIOM v2 — Multi-engine Bitcoin/Kalshi Research Bot

**Status:** Running local prototype, 19 offline tests passing (see `TEST_REPORT.md`). **Not publicly deployed or live-market verified.** No real orders. No existing GitHub repositories or branches were modified.

This is one web app: one 15-minute Kalshi contract, multiple BTC forecasting engines, one experimental consolidated direction, one independent spot scalping lens, and a paper-trading ledger. It runs on a cloud Python server or locally, and the responsive dashboard works in a mobile browser.

## Quick start

Python 3.10+:

```bash
pip install -r requirements.txt
DEMO_MODE=1 AUTO_PAPER=0 uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Open http://127.0.0.1:8000 (on the machine running the server). Demo mode uses clearly labeled synthetic prices/outcomes. **For public live read-only feeds**, remove `DEMO_MODE=1` or set `DEMO_MODE=0` and use a machine with internet access.

On iPhone/iPad, use a single-worker HTTPS hosting service deployed from this same dedicated AXIOM repository after confirming the hosting workspace. Never create a different repository for this system.

## Actual engines integrated in v2

| Engine | What it calculates | Provenance | Caveat |
|---|---|---|---|
| `kalshi_market` | Same-time Kalshi YES midpoint | Market baseline, NOT an independent prediction | Quotes can be thin or stale |
| `axiom_volatility` | Spot/strike distance and realized 1m volatility with capped drift | AXIOM v1 original engine | Experimental, uncalibrated |
| `aaryann_fair` | Lognormal expiry probability incorporating 5m return | Actual public MIT-licensed equation adapted from `aaryann123/kalshi-bot/bot.py` | Approximate spot proxy; source itself reported no validated edge |
| `kalshibot_headstart` | Normalized spot-versus-target distance with adjusted settlement horizon | Actual MIT-licensed head-start *feature* adapted from `jaldrich2023/KalshiBot/Predictor.swift` | **Not** its trained logistic model; illustrative CDF mapping |
| `ensemble` | Median of the three experimental probabilities (excluding Kalshi midpoint) | Original AXIOM v2 integration | Not trained, independent information overlap, uncalibrated |

**This does not mean all 17 public repositories have been combined or installed.** The two MIT methods above are genuine source-informed integrations into a working application. The research catalog includes other projects for future license, compatibility, data-feed, and outcome reviews; it is optional and not loaded into the app.

## Contract price versus forecast: mandatory separation

**Kalshi is not running AXIOM's forecasting model.** YES/NO contract prices emerge from orders placed by traders and market makers. A 70-cent YES quote midpoint is a market price, **not** an official Kalshi prediction that YES will win 70% of the time, and **not** a guaranteed true probability.

AXIOM therefore maintains four separate roles:

1. **Market data:** Kalshi supplies the published target, live YES/NO participant bid/ask quotes, and official settled result. `market_mid` is an order-book YES quote midpoint used for scoring comparison; it never votes in the forecast. The legacy `kalshi_market` identifier in scored snapshots represents this **non-voting quote benchmark**, not a Kalshi forecasting algorithm.
2. **Independent experimental forecast:** BTC/volatility-based engines and their consensus estimate ABOVE/BELOW without using YES/NO contract prices as forecasting inputs. The research shadow is also non-voting. Changing quoted prices alone cannot change the forecast.
3. **Opportunity comparison:** The independently estimated probability is compared to participant **ask** prices with illustrative fees. A model-minus-quote difference is **not** verified mispricing, guaranteed profit, or proven alpha. Fill size, slippage, and date-specific fee rules require separate validation.
4. **Settlement:** The official Kalshi market result determines grading, not the contract price or Coinbase spot. Historical quote-versus-forecast Brier comparisons evaluate descriptive probability skill, not actual trading returns.

**Compatibility:** `market_prob` and `alpha_vs_market` are legacy API/database fields: the former stores the participant YES midpoint; the latter represents experimental model-minus-midpoint difference. Neither is a Kalshi-issued forecast or validated investment alpha. Additional fields (`market_price_source`, `market_mid_role`, `market_price_is_forecast`, `forecast_minus_quote_mid`, `quote_discrepancy_is_validated_alpha`) document their true meaning. The dashboard renders quote midpoints in cents and model estimates as uncalibrated percentages.

Permanent regression suite `tests/test_market_quote_is_not_forecast.py` checks forecast invariance when participant quotes change and verifies that bid/ask prices still affect hypothetical opportunity assessments.

## How the combined forecast works

1. Read a live open `KXBTC15M` market, the official Kalshi target where published, and Coinbase BTC spot/candles (a **proxy**, not settlement-index BRTI).
2. Each engine produces a probability of ABOVE from the *same* snapshot. Missing inputs cause that engine to report unavailable rather than invent output.
3. Take the median of at least two available experimental engines. Market prices are only for comparison and paper-opportunity evaluation.
4. Output `WAIT` if the median is between 40% and 60% or if the highest and lowest experimental estimates differ by over 30 percentage points. The individual probabilities remain visible even when consensus says `WAIT`.
5. Use the final consensus to screen hypothetical YES/NO opportunities at the quoted ask, subtracting an **illustrative** taker fee. It checks spread, entry price, model confidence, time left, and edge. Real fee schedules may differ.
6. Independently, the existing EMA(9/21)+ATR(14) BTC scalp lens reports `LONG`, `SHORT`, or `WAIT` with indicative entry/stop/target. No actual scalp trades are executed or P&L tracked.

## Individual model evaluations

AXIOM v2 records an immutable, same-market snapshot of every available engine at **14, 10, 5 and 1 minutes remaining** (within 30 seconds of the corresponding checkpoint). It includes the Kalshi midpoint for a fair paired comparison.

After **official Kalshi settlement** is available, predictions are graded and the dashboard reports:

- Number of independently resolved contracts per engine/checkpoint
- Correct-outcome accuracy
- Brier score (lower is better)
- Kalshi midpoint Brier on exactly the same observations
- Difference in Brier vs Kalshi (positive = better), descriptive only
- Log loss in CSV/API output

These scorecards do **not** automatically verify predictive alpha or choose weights. They are prerequisites for later chronological out-of-sample testing. A small winning streak or a backtest is insufficient.

## Full aggregated Kalshi order book and three independent decision lanes

**Forecasting is separate from contract pricing.** AXIOM's preexisting consensus of BTC spot/volatility-derived research engines is unchanged. Kalshi's trader-set quote midpoint and the full order book are NOT inputs to the winner estimate. Contract pricing cannot override or vote in the forecasting models.

**Full market depth:** LiveProvider uses the public GET `/markets/{ticker}/orderbook?depth=0` REST endpoint with no API key or real order placement. It retrieves all **currently available aggregated bid price levels** and their fixed-point contract quantities for YES and NO. The server independently constructs YES asks from `1 - NO bid` and NO asks from `1 - YES bid`. It does not provide every individual order, trader identity, cancellation/trade event, or guaranteed available liquidity. The book has local received-at timestamp and market ticker; missing, malformed, crossed, stale, or mismatched books cause the new opportunity and execution lanes to WAIT.

**Opportunity detection (new, read-only):** `app/depth_intelligence.py` compares AXIOM's independent estimate to the participant order book, using a hypothetical **10-contract book walk** by default instead of presuming all contracts can be bought at best ask. Computes size-adjusted average/worst entry price, spread, displayed size, estimated fees, potential model-price discrepancy, and explicit WAIT/YES/NO candidate. Unvalidated forecast probabilities, unverified execution costs and unobservable future fills prevent any proven-alpha claim. Price/quote inputs affect the opportunity, not the forecast.

**Execution intelligence (new, read-only):** Separate `execution_intelligence` describes ENTER or WAIT for fresh, sized entry candidates. `paper_position_execution` separately assesses a **one-contract simulated paper position**, if present, to show HOLD or a hypothetical EXIT at size-adjusted resting bids. This cannot read personal/real Kalshi portfolio positions, and it **never** creates/updates real orders. The offline demo includes a clearly labeled synthetic depth feed.

**Dashboard/API:** `GET /api/state` includes `orderbook` with all available levels (plus `best`, level counts, volumes, 5-cent bid imbalance), `depth_opportunity`, `execution_intelligence`, and optional `paper_position_execution`. Mobile UI shows full available YES bid and implied YES ask ladders, the new sized opportunity, and separated execution advice.

**Backward compatibility:** Existing `opportunity` and existing one-contract automatic/manual **paper ledger** remain unchanged and are explicitly labeled a *legacy top-quote paper screen*. No existing positions, historical grades, forecasts, or scoring records were rewritten. The new depth execution recommendations do **not** drive those legacy simulated entries; their entry/exit prices remain hypothetical. This distinction prevents accidentally claiming historical paper trades were full-depth matched.

**Latency and future work:** REST book is a point-in-time snapshot re-polled by AXIOM; it is not a WebSocket update stream and cannot attribute net level changes to cancellations versus trades. Before real or high-speed trading, separately validate authenticated/live exchange connectivity and rate limits, WebSocket snapshot/delta continuity, actual fee schedule, fill availability, risk limits and out-of-sample signal performance. No auto-trading authorization exists.

## Paper trade handling

- Automatic paper entries are optional (`AUTO_PAPER=1`) and capped to one synthetic entry per market. Default in the sample configuration remains enabled, but no actual orders are placed.
- Manual YES/NO paper entries and CSV exports require a `BOT_ADMIN_TOKEN` environment variable. Do not put credentials in source code.
- P&L is currently **gross**: settlement payoff minus the observed ask, before fees/slippage. The decision screen separately displays an indicative after-fee edge.
- Settlement is read back from Kalshi's public market-specific settled result, **never derived from Coinbase spot**. Demo mode instead uses synthetic settlement and should be kept in a separate database.
- All SQLite writes are local. In the cloud, use a persistent disk, **one** worker/instance, and a private admin token. On ephemeral hosting the ledger may disappear on restart.

## API

- `GET /` — responsive AXIOM v2 dashboard
- `GET /health` — app status
- `GET /api/state` — all live model, consensus, opportunity, ledger and scoring data
- `POST /api/paper` — manual simulated entry with admin token
- `GET /api/export/{first_calls|paper_trades|observations|engine_snapshots}` — CSV export with admin token

## Tests

```bash
python -m pytest -q
```

Tests cover provider-normalization, model mathematics, market independence, missing inputs, quote/fee gating, immutable scoring snapshots, official-result scoring, CSV export and mobile HTTP route. `DEMO_MODE=1` supports offline smoke tests.

## Optional source provenance catalog

`research_sources/` holds a catalog of the candidates named across both Deep Research investigations and a standalone collector to download public **source snapshots** in a network-enabled environment. This collector **does not run or integrate** that external code and is not needed to launch AXIOM v2.

See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for exact file provenance and license text. All remaining candidate repositories with other/unknown licenses are *not* vendored into this app.

## Important limitations

- No live trading, no keys, no auto-deploy, no publicly accessible URL yet.
- No claims of calibrated model probabilities, audited historical accuracy or proven economic alpha.
- Coinbase is not the CF Benchmarks official settlement value; edge screening near target is vulnerable to basis error.
- The three nonmarket forecasts use similar price/volatility inputs, so they are distinct algorithms **but not statistically independent information sources**.
- External public API behavior and market availability were not verifiable from this offline environment. Deployment needs a real-market smoke test before interpreting the signals.
- Exact implementations of third-party proprietary systems and unlicensed public repositories are **not** included.

**Isolation:** This entire v2 was created only in `/mnt/data/AXIOM_v2_Research_Bot/`. No original GitHub project, branch, Render service, or database was modified.

## Live authenticated BRTI reference (integration candidate)

Set `BRTI_LIVE_ENABLED=1`, `KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY_PEM` in *server-side* environment secrets. AXIOM subscribes to Kalshi's authenticated `cfbenchmarks_value` and `cfbenchmarks_value_5hz` channels for BRTI only. `/api/state.live_briti` displays source and receipt timestamps and provider-reported 60-second/15-minute-window information without exporting credentials or raw frames. It does NOT vote in the uncalibrated forecasting ensemble, trigger paper trades or place real orders. Missing/stale data is marked unavailable. AXIOM's first-observed strike time is not proof of the exchange's first publication. Validate real stream capability using `python -m research.live_brti_probe`. Kalshi official documentation: https://docs.kalshi.com/websockets/cfbenchmarks-value and https://docs.kalshi.com/websockets/cfbenchmarks-value-5hz.

## Integrated intracontract movement and resale intelligence
The live AXIOM application now tracks successive real Kalshi full-depth
snapshots, YES quote-midpoint changes, the matching BTC/BRTI movement,
net quoted additions/removals at price levels, book imbalance changes and
swing-rejection proxies. A separate read-only resale lane reports
BUY_CANDIDATE/WAIT without assuming the chosen contract will win settlement;
for an existing simulated paper position it calculates a depth-backed,
illustrative after-fee exit review. A threshold future bid is NOT a predicted
price or an executable fill, and quote-movement correlations are not proven
trading alpha. Funding rates are intentionally marked NOT_CONNECTED, as
no verified live funding feed is configured. No real order endpoints exist.

## Public Binance spot-first and perpetual funding intelligence
The complete FastAPI bot now connects Binance's public BTCUSDT aggregate
trade WebSocket and the USD-M perpetual published funding/mark-index REST
reference. It timestamps source events and receipts, checks for stale or
blocked feeds, and compares Binance-first moves to *later observed* Kalshi
full-depth quote snapshots on the same BTC15M contract. The lag lane may
show WATCH or a gated, depth/fee-aware BUY_CANDIDATE without asserting
that a subsequent price change, fill or profit will occur. Funding sign
shows who pays whom and mark-index basis but NEVER votes on YES/NO.
Coinbase/BRTI remain the original outcome/settlement sources and Binance
USDT is not BRTI USD. Region-restricted feeds stay explicitly unavailable;
no quiet venue substitution is performed. Both workers are read-only.
