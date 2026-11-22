# AXIOM BRTI-first price-source conversion — 22 November 2026

**Repository scope:** `szmohmand/Axiom` only. Existing Oracle VM, Tailscale, historical SQLite ledger, no real-order endpoints, no billable resources changed by this source update.

## Definitive production price inputs

- The **primary live BTC reference is authenticated, current CF Benchmarks BRTI**, from the existing signed Kalshi 1Hz and up-to-5Hz BRTI WebSocket. Coinbase's ticker, completed candles, and 5-minute candles are no longer queried by the live forecast worker. `DEMO_MODE=1` still uses unmistakably synthetic test feeds.
- Compute **real, received BRTI 1-minute price-only OHLC** from actual received timestamps and first per-second index observations; reject missing, stale, out-of-order or noncontiguous minutes rather than filling prices. `volume=None`, never a fabricated trade size.
- BRTI price candles now drive spot-to-target distance, realized 1m volatility, acceleration, EMA, ATR, scalp lens, completed-candle/Nison patterns, RSI/MACD and support/resistance structures, the 5m aggregation and 30m/1h/2h trend features, legacy analytic fair-price engines, BRTI-specific shadow, and the gradient-boosted classifier.
- **New BRTI 60-second average settlement engine:** the future full-minute average has lower variance than an endpoint price. In the final minute it conditions on the actual contiguous observed prefix of authentic BRTI seconds; it cannot manufacture an unseen second.
- **Binance signed CVD, taker imbalance and actual large-trade prints remain separate.** These require individual executed exchange trades; CF Benchmarks is a price index and cannot supply actual taker/volume data. Binance-to-Kalshi quote delay and Kalshi depth/contract pricing are separately labeled market/exec research, not CF BRTI prices.
- No Kalshi YES/NO quote/ask/bid/orderbook data enters the primary BTC settlement forecast. Official strike, expiry, and settlement outcomes still come from Kalshi.

## New 180-day BRTI-trained booster (replacing previous Binance-trained artifact)

Source: user's prior `BTC_180Day_Independent_CrossSource_Validated_Research_PartialRawTransfer_2026-11-16.zip` archive; `BRTI_180Day_1Minute_Presettlement_EventTime_Features.csv.gz`. Only actually observed complete 60-second BRTI minutes; May 20–Nov 15, 2026. Features: previously observed BRTI minute OHLC, log returns, volatility, EMA and **zero-volume sentinel**. Targets: actual forward full-minute BRTI first-tick mean, with hypothetical volatility-scaled strikes; **NOT** known point-in-time Kalshi strike snapshots.

12-tree depth-three residual gradient boosting; random seed and learning-rate protocol fixed. Chronological train/validation/holdout by 15m anchor, 229,720/49,220/49,240 **correlated** feature/strike/horizon examples across 16,409 anchors.

| Probability Brier | Analytic baseline | BRTI residual boosted |
|---|---:|---:|
| Train | 0.147769 | 0.147295 |
| Validation | 0.150974 | 0.150811 |
| Later holdout | 0.150571 | **0.150301** |

This improvement is small; it is not a validated out-of-sample real-Kalshi settlement edge, automatic trading rule, guaranteed income, or evidence of greater accuracy than the Kalshi quote. The training input-feature distribution comes from historic event time rather than signed live receipt time; the live collector explicitly cannot pretend that historical observation timestamps prove contemporaneous availability. No full original BRTI dataset is committed to GitHub.

## Safety and rollout

- Mandatory BRTI authentication: missing/stale feed => **forecast WAIT, execution WAIT, degraded health; no Coinbase fallback**.
- Once authenticated BRTI connects, genuine recent index history needs approximately **31 completed 1-minute bars** for the main forecast, **62 bars** for the trained booster, **125 actual 5-minute bars** for 2-hour features (approximately 2 hours of history). A newly restarted live worker shows **LIVE transport and WARMING forecast** during that accumulation; no predictions or manual/automatic paper entries until ready. 30/60/120-minute higher-timeframe coverage grows with actual observations, not interpolation.
- Existing Oracle upgrade script now checks the existing root-only `/etc/axiom/axiom.env` contains `BRTI_LIVE_ENABLED=1` and nonempty Kalshi WebSocket signer ID/private key before staging. It does not display credentials. Upgrade must preserve previous service/version, SQLite backup/recovery, and full tests. **No server deployment can be claimed until the actual VM confirms it**.
- Tests: full regression suite, true BRTI index candle generation, index-only model vote, 60-second final-minute partial-average, quote independence, missing-second refusal, live warmup without pretending a prediction exists, Binance signed-trade isolation, read-only Kalshi provider GET and no Coinbase fallback.
