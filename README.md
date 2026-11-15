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

On an iPhone/iPad, use a **new, separate hosting service** deployed from a **new repository**, not any existing project. This package does not create that new repository or deploy itself.

## Actual engines integrated in v2

| Engine | What it calculates | Provenance | Caveat |
|---|---|---|---|
| `kalshi_market` | Same-time Kalshi YES midpoint | Market baseline, NOT an independent prediction | Quotes can be thin or stale |
| `axiom_volatility` | Spot/strike distance and realized 1m volatility with capped drift | AXIOM v1 original engine | Experimental, uncalibrated |
| `aaryann_fair` | Lognormal expiry probability incorporating 5m return | Actual public MIT-licensed equation adapted from `aaryann123/kalshi-bot/bot.py` | Approximate spot proxy; source itself reported no validated edge |
| `kalshibot_headstart` | Normalized spot-versus-target distance with adjusted settlement horizon | Actual MIT-licensed head-start *feature* adapted from `jaldrich2023/KalshiBot/Predictor.swift` | **Not** its trained logistic model; illustrative CDF mapping |
| `ensemble` | Median of the three experimental probabilities (excluding Kalshi midpoint) | Original AXIOM v2 integration | Not trained, independent information overlap, uncalibrated |

**This does not mean all 17 public repositories have been combined or installed.** The two MIT methods above are genuine source-informed integrations into a working application. The research catalog includes other projects for future license, compatibility, data-feed, and outcome reviews; it is optional and not loaded into the app.

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
