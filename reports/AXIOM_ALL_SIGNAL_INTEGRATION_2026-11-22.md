# AXIOM: all-signal forecasting upgrade and trained model provenance

This is the user-requested **forecast integration**, not background monitoring.
Code is scoped to `szmohmand/Axiom`; the running Oracle VM is not modified
by source commits, and no API order placement has been added.

## Active voting models

1. Original BTC 1-minute volatility model.
2. Original MIT-derived five-minute momentum/volatility fair-value model.
3. Original KalshiBot head-start-inspired fair-value model.
4. Original AXIOM spot/target-distance/acceleration model.
5. **New historically fitted residual gradient-boosted tree model**.
6. **New whole-methodology Japanese Nison independent candlestick forecaster**.
7. **New multi-signal context forecaster** containing completed 30m, 1h, 2h
   price structure; Kalshi near-depth order-book imbalance and liquidity walls;
   changes/replenishment of resting quotes; real Binance signed aggTrade CVD
   over observed 2m and 5m windows; unusually large aggressive Binance prints;
   published perpetual funding and mark/index basis; and time-ordered Binance
   spot moves against Kalshi quote updates, including a graded
   *possible quote absorption/slow repricing* indicator.

**All available engines can influence the probability** using a mean pool
in the integrated mode. No arbitrary probability-adjustment ceiling is
applied to Japanese candles or to learned trees. Missing observations remain
missing; e.g. unavailable funding cannot be invented.

The Kalshi YES bid/ask midpoint is NOT used as a ground-truth probability.
Kalshi depth-derived features are legitimate observed market positioning,
not independently verified Bitcoin order flow. Genuine BTC CVD comes from
signed Binance aggTrades; no fabricated whale wallet identities.

## Gradient boosting experiment: precise provenance

- 129,600 Binance BTCUSDT genuine 1m OHLCV bars from Aug 6 to Nov 3, 2026,
  source: `BTC_180Day_Independent_CrossSource_Validated_Research_PartialRawTransfer_2026-11-16.zip`
  in the user's Library.
- At every 15-minute anchor after enough history, generate 4 future horizons
  (1, 5, 10, 14 minutes) and 5 synthetic volatility-scaled candidate strikes.
  The target label is the **actual Binance BTC price at that future horizon**.
  This avoids assuming retroactively recovered Kalshi strikes were public
  at the prediction time.
- Train first 70% of minutes, compare on the next 15%, hold out last 15%.
  The features only use past and current OHLCV returns, volatility, EMA
  differential, candle body/wicks and volume, plus contemporaneous synthetic
  strike distance and time-to-horizon.
- Model: learned Newton residuals from normal-volatility reference with
  `DecisionTreeRegressor(max_depth=3,min_samples_leaf=180)`, sequential
  gradient boosting with learning rate 0.075. **The first 12 trees** are bundled
  in `app/boosted_model.py`, using Python-only inference.
- Sample sizes: 120,800 training examples, 25,920 validation examples,
  25,900 holdout examples. These examples are **correlated** by overlapping
  time intervals and synthetic thresholds; don't mistake them for 25,900
  independent contracts.

| Split | Normal-volatility baseline Brier | Boosted 12-tree Brier |
|---|---:|---:|
| Train | 0.143737 | 0.142947 |
| Validation | 0.141911 | 0.141593 |
| Later holdout | 0.143404 | 0.143096 |

A naïve 28-tree standard `GradientBoostingClassifier` performed **worse**
than the baseline (holdout Brier ~0.144083), which is why the residual-boosted
variant was used instead. This is a small **historical probability-score**
improvement, not evidence of settlement edge, order fills, or income.

**Feature training provenance matters:** The learned trees themselves are
trained on 1m BTC price/volume features, not historical funding, Kalshi L2, or
whale identities (those histories were unavailable). Those additional
observed signals influence forecasts in the independently auditable
multi-signal context model; they are not passed off as historically fitted.

## Why the candle recognizer was changed

New `app/nison_structures.py`: smoother turning points with data-adaptive
bandwidth; flexible three-peak/three-trough geometry; normalized dynamic
time warping; rounding-versus-line BIC comparison; data-selected three-stage
tower change points. Forming shapes and completed shapes are separate
labels. Genuine strict Japanese shadow-gap formations remain distinguishable
from gapless early rounded candidates.

## Engineering / access status

- Source changes modify the **integrated** forecasting code in `app/ensemble.py`
  and `app/main.py`; unlike the previous challenger, these models vote.
- The new code does **not** deploy to Oracle automatically.
- Existing tests that asserted Japanese signals could never change the
  active ensemble, or hard-coded an exact count of 5 engines, are **obsolete
  relative to the user-requested new model behavior**. They require updates;
  they have not been silently deleted, bypassed or redefined.
- Live external provider availability is independent of syntax and offline
  model tests. A Kalshi API / no active contract failure in GitHub Actions
  is not a passing live-market confirmation.
- No real-money Kalshi order API integration has been added.

## Explicitly unresolved, rather than hidden decisions

- Funding sign is **not** a proven bullish/bearish predictor. The integrated
  contribution is a direction-of-positioning *hypothesis*, and can be
  challenged by a contrarian alternative.
- Binance large prints are not identified whale wallets; public aggTrades
  do not identify a specific position owner's identity.
- Kalshi quote stickiness plus BTC CVD is not genuine BTC exchange-L2
  absorption; this is a cross-market **repricing proxy**. A genuine Binance
  L2 absorption model would require actual time-ordered Binance order-book
  depth/events or trade execution.
- Models can have correlated errors, and equal model pooling is a starting
  experiment, not automatically an optimal weighting rule.
