# AXIOM — period-specific real-source model comparison

**Research date:** November 15, 2026  
**Status:** CONDITIONAL retrospective analysis; no verified live edge.  
**Isolated branch:** research/window-specific-model-rerun-2026-11-15  
**Preserved verified AXIOM main:** b12be3758049b6766dda8fefad06611bf41ada2e  
**Dataset:** KalshiEye/kalshi-order-book-sample; CC BY-NC 4.0, noncommercial research.  
**Evidence:** [Period-specific replay with calibration](https://github.com/szmohmand/Axiom/actions/runs/43775966554).

## Direct answer — model with lowest held-out Brier score

| Requested time period | Historical leading independent candidate | Matched held-out contracts | Matched rows | Brier (lower better) | Direction accuracy | Contract-weighted 5-bin ECE |
|---|---|---:|---:|---:|---:|---:|
| First two minutes (15, 30, 60, 90, 120 seconds after opening) | Schen zero-drift minute-volatility proxy; virtually tied with HeadStart | 87 | 426 | 0.221991 | 65.75% | 0.077584 |
| Exactly ten minutes left | Schen zero-drift minute-volatility proxy; virtually tied with HeadStart | 87 | 87 | 0.181568 | 73.56% | 0.064816 |
| Exactly five minutes left | Independent candle-feature logistic, trained only on October 13 | 84 | 84 | 0.116884 | 83.33% | 0.097342 |
| Whole last minute (-60, -45, -30, -15, -5 seconds) | Independent candle-feature logistic, trained only on October 13 | 87 | 430 | 0.027000 | 96.55% | 0.018136 |

**None of the four top models has a statistically established Brier improvement over the existing AXIOM ensemble.** Paired 95% bootstrap intervals over contracts include zero in every requested period. Reported winners mean best in this one-day held-out sample, not suitable for promotion.

## Reproducible dataset and methodology

- Training day: October 13, 2026; 44 clean contracts, 522 checkpoint observations. All learned models trained separately at each exact checkpoint using only that date.
- Strictly held-out test day: October 25, 2026; 87 clean contracts, 1,027 timestamped observations total; no October 25 labels used in training.
- Clock definitions: opening +15, +30, +60, +90, +120 seconds; expiration −600 seconds; expiration −300 seconds; expiration −60, −45, −30, −15, −5 seconds.
- All independent models use the same observed BTC spot proxy, completed minute MID-QUOTE candles, contract strike and time remaining. No Kalshi contract price enters the independent probabilities.
- Same ticker and checkpoint set for all eligible independent models. For multi-checkpoint windows, score each contract equally regardless of how many of its observations survived source-quality exclusions.
- Five-bin calibration ECE uses equal contract influence, not naive weighting by raw observations.
- The contemporaneous Kalshi YES midpoint is reported as a separate benchmark; not blended.
- Historical realized outcome is the recorded official Kalshi yes/no settlement label, not Coinbase price or a calculated spot winner.
- Known recorder outage hours, stale quotes, uncompleted minute candles and missing inputs are excluded. The contract strike comes from an archived day-end market catalog with no independently verified original publication timestamp. Therefore **the as-of market-target availability is conditional, not confirmed.**

## Every model — Brier / eventual-contract directional accuracy

| Independent model | First 2min | 10min left | 5min left | Entire last minute |
|---|---:|---:|---:|---:|
| Schen M0 1-minute volatility proxy | **0.221991 / 65.75%** | **0.181568 / 73.56%** | 0.117913 / 82.14% | Not valid across full minute; at −60s alone: 0.030081 / 94.12% (85 contracts) |
| HeadStart adapted CDF | 0.222004 / 65.75% | 0.181576 / 73.56% | 0.117923 / 82.14% | 0.028866 / 95.86% |
| Trained independent logistic | 0.227760 / 59.71% | 0.184895 / 70.11% | **0.116884 / 83.33%** | **0.027000 / 96.55%** |
| AXIOM existing ensemble | 0.230783 / 60.29% | 0.182983 / 72.41% | 0.124625 / 83.33% | 0.029547 / 95.86% |
| AXIOM original volatility | 0.231800 / 59.37% | 0.184396 / 72.41% | 0.125702 / 83.33% | 0.030127 / 95.86% |
| Aaryann adapted fair-price equation | 0.235890 / 59.83% | 0.183337 / 73.56% | 0.139383 / 80.95% | 0.029984 / 96.09% |
| Trained BTC-only XGBoost subset | 0.346856 / 47.24% | 0.257355 / 59.77% | 0.149980 / 82.14% | 0.040864 / 95.86% |

**Critical interpretation:** Schen M0 and HeadStart have almost identical related mathematical structures. First-2-minute difference = 0.000013 Brier. Ten-minute difference = 0.000008 Brier. Those tiny decimal separations are not evidence of a distinct superior signal.

The five-minute logistic ties AXIOM's existing ensemble on directional accuracy (both 83.33%) and lowers Brier, but **its observed calibration ECE is worse**: logistic 0.097342 versus ensemble 0.055627. The final-minute logistic leads by Brier, calibration ECE and accuracy; this is late, easier direction prediction, not proof of predicting price movements before they occur.

## Opening two minutes, exact checkpoints

| Time from open | Eligible contracts | Schen M0 Brier | HeadStart Brier | Both models' direction accuracy |
|---|---:|---:|---:|---:|
| +15 seconds | 85 | 0.235959 | 0.235968 | 63.53% |
| +30 seconds | 86 | 0.234486 | 0.234496 | 59.30% |
| +60 seconds | 86 | 0.216655 | 0.216674 | 69.77% |
| +90 seconds | 83 | 0.217427 | 0.217441 | 66.27% |
| +120 seconds | 86 | 0.208491 | 0.208502 | 68.60% |

The experiment predicts the eventual winner, not the onset of an impending BTC move.

## Last minute, exact checkpoints

| Seconds left | Eligible contracts | Trained independent logistic Brier | Direction accuracy |
|---|---:|---:|---:|
| 60 | 85 | 0.029013 | 95.29% |
| 45 | 85 | 0.016615 | 97.65% |
| 30 | 87 | 0.031236 | 96.55% |
| 15 | 87 | 0.027891 | 97.70% |
| 5 | 86 | 0.031658 | 95.35% |

Original Schen M0 requires already accumulated official BRTI partial-average index ticks during the final 60 seconds. Those historical index ticks were not available. Therefore its proxy was scored at -60 seconds only, and was rightly excluded from the full final-minute ranking.

## Paired Brier difference versus current AXIOM ensemble

Positive delta = independent candidate better than the current ensemble, **on the same matched contracts and timestamps**. Resampling uses 2,000 whole-contract draws; uncertainty intervals are uncorrected for selecting the winner post hoc and adjacent-contract correlation.

| Window | Candidate | Mean Brier advantage | Approximate 95% paired bootstrap interval | Decision |
|---|---|---:|---|---|
| First 2min | Schen M0 | +0.008792 | -0.003666 to +0.021541 | Indeterminate |
| 10min left | Schen M0 | +0.001416 | -0.006274 to +0.010162 | Indeterminate |
| 5min left | Independent logistic | +0.007741 | -0.012123 to +0.027280 | Indeterminate |
| Last minute | Independent logistic | +0.002547 | -0.000842 to +0.006270 | Indeterminate |

XGBoost performed worse on this very small, reduced-feature training set, especially early. This is not evidence that full original XGBoost systems cannot forecast BTC.

## The Kalshi market-price benchmark is NOT independent

| Window | Market YES midpoint Brier | Direction accuracy | Matched benchmark coverage |
|---|---:|---:|---|
| First 2min | 0.221524 | 63.68% | 87 contracts, 425 rows |
| 10min left | 0.178174 | 71.26% | 87 contracts, 87 rows |
| 5min left | 0.103461 | 83.33% | 84 contracts, 84 rows |
| Last minute | 0.021878 | 97.52% | **Only 53 contracts, 126 rows**, versus 87/430 independent |

Do not directly compare the last-minute benchmark raw Brier with the 87-contract model score as if the observation sets matched. The replay independently calculates matched-sample benchmark differences.

## Causality, source fidelity and other limitations

1. Although spot quotes and book snapshots are limited to past receiver timestamps and completed candles, the recorded strike comes from a day-end catalog. **Its publication timestamp is not verified**. We cannot label this a fully verified as-of live backtest.
2. Coinbase recorder MID QUOTE bars do not equal Coinbase exchange OHLCV trade candles, and Coinbase prices are not the CF Benchmarks official BRTI settlement index. Official yes/no Kalshi outcomes are the grading truth.
3. The Schen implementation is a minute-volatility approximation, not his original second-by-second M0. The KalshiBot HeadStart variant is a feature mapping, not its complete trained predictor. Logistic and XGBoost are new reduced-feature research challengers, not full source-level ports or pre-trained original weights.
4. There are only two noncontiguous October days. The 44-contract train set, 87-contract test set and 12 historical checkpoint types are too narrow for robust generalization or for a claim of a statistically established winner.
5. 96% correct in the final seconds is **not** 96% accuracy at predicting a BTC price move 1–2 minutes before it starts, nor proof of any viable buying opportunity at the actual executable ask price.
6. No trading, deployment, merges to main, altered model outputs or real order execution are part of this study. Data license limits the research dataset to noncommercial uses.

## AXIOM engineering decision

**PASS:** isolated period-test source, strict timestamp boundaries, same-contract comparisons, per-contract weighting, benchmark separation, regression tests and existing-system regression suite where CI is green.  
**BLOCKED:** challenger model promotion, real profitability, actual predictive edge, first-move advance warnings, and source-level original-model equivalence.

Preserve AXIOM's verified system. Further research would need additional genuinely as-of market-target histories, source-faithful BRTI data, more holdout regimes, calibrated original-feature challengers, robust economic backtesting, and another complete no-regression cycle before any promotion.
