# AXIOM: Real BTC15m challenger research — November 15, 2026

**Result: conditional real-data research completed; no promotion, merge, deployment, or real trading.** This is the dated no-regression and scientific acceptance report. The latest verified production main remains b12be3758049b6766dda8fefad06611bf41ada2e; recovery ref verified/2026-11-15-b12be37 is unchanged. Previously verified runtime is 902f7d7dfd7a4a952b4afc2019f01a599af43355.

## Provenance and reproducibility

- Public historical source: https://huggingface.co/datasets/KalshiEye/kalshi-order-book-sample, **CC BY-NC 4.0 noncommercial research only**. Neither source data nor external executable code is committed to AXIOM.
- Genuine source on October 13 and October 25, 2026, including receipt-time nanosecond Coinbase/Bitstamp/Kraken quote midpoint streams, Kalshi market definitions, second-level Kalshi YES-side book, recorder incidents, and official yes/no + expiration index settlement records.
- Research replay execution: https://github.com/szmohmand/Axiom/actions/runs/43775190483 (SUCCESS on SHA 3db41cafcd87c8b35927a822d94e3d2e4e644027). Full original AXIOM historical regression/end-to-end test: https://github.com/szmohmand/Axiom/actions/runs/43775190485 (SUCCESS). Original real Kalshi/Coinbase read-only smoke: https://github.com/szmohmand/Axiom/actions/runs/43775190511 (SUCCESS). Exact final report-commit checks also required.
- Script: research/kalshieye_replay.py; source/schema probes: research/kalshieye_probe.py and research/kalshieye_schema.py. Test path: tests/test_kalshieye_replay.py. Optional pyarrow, XGBoost and sklearn installed only on ephemeral GitHub Actions runner.
- Historical original regression history now contains **21 permanent records**, including new A16 source integrity tests. A16 ensures official expiration_value is never replaced by auxiliary coin_price_end, along with missing candle and future lookahead guards. Original source archives preserved.
- Absolutely no production app source, UI, order path, Kalshi official grading, paper ledger, deployment setup, production requirements, underlying baseline, or GitHub recovery reference modified.
- Research result labels never fed into model features. Contemporaneous Kalshi YES book midpoint is an **external benchmark**, never blended with independent BTC forecast. The public market floor_strike was obtained from a later market catalog and has **no separately proven original publication timestamp**. This blocks certification of a truly point-in-time production replay, so all forecasting accuracy figures are **conditional historical research**.

## Real source sizes and exclusions

| Property | Oct 13 training | Oct 25 holdout |
|---|---:|---:|
| BTC quote records read | 4,679,193 | 2,784,579 |
| Nominal BTC15m contracts | 96 | 96 |
| Fully eligible unique contracts | 44 | 87 |
| Eligible fixed checkpoints (14, 12, 10, 5, 1 minutes) | 217 | 426 |
| Eligible recent Kalshi book comparisons | 166 | 393 |
| Recorded outage/incident hours | 7 | 1 |

Oct 13 recorder gaps included one hour at only 44.4% coverage. Contracts that overlap incident hours, miss an official label, lack a genuine contiguous 61-minute quote history, or have stale source quotes are excluded. No synthetic bars or outcomes were invented; 1-minute OHLC proxies here are built from **quote midpoints**, not Coinbase-trade candles or BRTI.

## Held-out prediction results: October 25, lower Brier is better

| Model | 14m (n=86) | 10m (n=87) | 5m (n=84) |
|---|---:|---:|---:|
| Original AXIOM ensemble | 0.226874 | 0.182983 | 0.124625 |
| Aaryann fair | 0.230575 | 0.183337 | 0.139383 |
| KalshiBot partial HeadStart CDF | 0.216674 | 0.181576 | 0.117923 |
| Schen M0-like zero drift with MINUTE volatility substitute | **0.216655** | 0.181568 | 0.117913 |
| Non-market-anchored logistic trained Oct13 | 0.220083 | 0.184895 | 0.116884 |
| Reduced BTC-only XGB trained Oct13 | 0.327017 | 0.257355 | 0.149980 |
| Kalshi price midpoint, benchmark ONLY | 0.215134 | **0.178174** | **0.103461** |

These are formula/feature challengers, **not the complete original trained third-party bots**. The 1m checkpoint has different model-versus-market coverage (market n=52, candidate n=85) and cannot be compared unpaired.

**Paired 2,000-resample matched-contract Brier difference, positive means first model is better:**

| First vs comparison | Checkpoint | n | Difference | Approx 95% interval | Conclusion |
|---|---|---:|---:|---|---|
| Schen-like M0 vs AXIOM ensemble | 14m | 86 | +0.010219 | −0.004436 to +0.025785 | Not conclusive |
| Schen-like M0 vs Kalshi quote | 14m | 86 | −0.001521 | −0.011191 to +0.007396 | Not conclusive |
| Learned logistic vs AXIOM ensemble | 14m | 86 | +0.006790 | −0.015878 to +0.028631 | Not conclusive |
| Reduced XGB vs AXIOM ensemble | 14m | 86 | −0.100144 | −0.163557 to −0.039661 | Worse on sample |
| Reduced XGB vs AXIOM ensemble | 10m | 87 | −0.074371 | −0.126195 to −0.023603 | Worse on sample |
| Schen-like M0 vs AXIOM ensemble | 10m | 87 | +0.001416 | −0.006709 to +0.009882 | Not conclusive |

All confidence intervals are approximate one-day per-contract resamples, not regime-independent multiweek statistical proof. The near-matching KalshiBot HeadStart and Schen M0 formulas are largely similar normalized distance-to-target models and should not be presumed independent information sources.

## Early-warning research on next-minute BTC movement — NOT demonstrated pre-onset prediction

Oct 13 training 1,015 minute observations and Oct 25 holdout **1,196** minute observations after excluding known recorder incident hours. An initial broader run had 1,230 test samples; this is superseded by the stricter 1,196-sample analysis.

| Holdout signal | n | Next-minute directional accuracy |
|---|---:|---:|
| Always predict UP | 1,196 | 48.83% |
| Prev-minute BTC momentum | 1,146 | **50.70%** |
| Coinbase price vs Bitstamp/Kraken dislocation sign | 1,196 | **48.83%** |
| Kalshi YES-side book bid-minus-ask size pressure sign, MARKET-DERIVED | 1,068 | **53.09%** |

On 325 *post-hoc* next-minute absolute moves of $20 or more, book pressure accuracy was 54.77%; this subset is selected based on the future and cannot be turned into a causal entry condition. The trained three-feature logistic (momentum + dislocation + market-derived book pressure) was trained on 864 Oct 13 samples and tested on 1,068 Oct 25 samples, with 51.22% directional accuracy and Brier **0.250038**, versus 0.250000 for a 50/50 forecast. No measurable practical edge shown.

**A correct sign over the next minute is not evidence of detecting the start of a move one or two minutes before the move becomes visible.** No move-onset first-notice ground truth was established. The market-derived book signal MUST NOT be blended into an independently sourced probability.

## Official BRTI versus exchange midpoint proxies: a real source-integrity finding

Kalshi official settlement index here is **settlements.expiration_value**. Separately recorded coin_price_start and coin_price_end fields are NOT the benchmark settlement index. An initial basis calculation mistakenly used coin_price_end; the resulting implausible errors were caught, corrected and turned into permanent A16 regression tests. Only the corrected official-value results below count.

For the subset with 60 genuine complete as-of 1-second quote midpoint values at the contract close:

| Day | Quote source | Comparable settled markets | Mean absolute difference vs official index | Apparent winner flips if proxy substituted |
|---|---|---:|---:|---:|
| Oct 13 | Coinbase | 46 | $2.7077 | 0 |
| Oct 13 | Bitstamp | 46 | $3.0801 | 0 |
| Oct 13 | Kraken | 36 | $3.1921 | 0 |
| Oct 25 | Coinbase | **72** | **$4.6463** | **4** |
| Oct 25 | Bitstamp | 91 | $3.3899 | 0 |
| Oct 25 | Kraken | 21 | $3.5958 | 0 |

October 25 Coinbase median absolute difference $3.8642, p95 $10.4928, maximum $14.204. **These are different samples**; this does NOT establish Bitstamp superiority. It establishes why replacing official Kalshi grading with Coinbase would be unsafe. Nothing in the deployed official settlement process changed.

**Spot source sensitivity in the original AXIOM ensemble** across the same three real quote feeds: on 86 Oct25 14m checkpoints mean between-feed forecast range was **5.0409 percentage points** (median 4.288 points); 37/86 exceeded 5 points and 7/86 exceeded 10 points. This is a relevant uncertainty source, not proof that any one spot feed is best.

## Hypothetical entry economics (NOT verified real P&L)

Earliest qualifying ask-price paper candidate, spread <= 4c, nominal modeled after-fee edge >= 8c, one entry per ticker, counts not matched. No actual fills, market-sized inventory, queue latency, capital costs, exact historical fee exceptions or slippage were verified.

| Model | Distinct selected contracts | Illustrative mean after-fee $/contract |
|---|---:|---:|
| AXIOM volatility | 43 | +0.029767 |
| AXIOM ensemble | 38 | +0.000526 |
| Aaryann | 51 | −0.028157 |
| Schen zero drift, KalshiBot HeadStart | 11 each | −0.150909 |
| Independent logistic | 29 | −0.008276 |
| BTC-only XGB | 84 | −0.032738 |

Because selections and contract prices differ, these do not rank executable profitability. Good Brier does not ensure cheap entries: outcome estimation and opportunity evaluation must remain separate.

## Safety and recommendations

- **PASS**: source hash and schema examined, nanosecond clocks preserved, future or incomplete book/spot source refused, true official source used for labeling, 21 historical Axiom permanent regression records, complete original synthetic lifecycle and real public GET smoke. GitHub Action evidence linked above.
- **BLOCKED for advancing**: target *original publication timing* at checkpoint not independently documented; only two separated sample days (44 training contracts), original full model feature/trainer parity not established; recorder/source outages; actual CF Benchmarks BRTI observations not input on October days; no demonstrated early onset prediction; no trading fills or robust profit.
- **Investigate further**: 1-second official index inputs from supported contemporary sources and true strike publication timestamps; additional chronological market days and regimes with after-source availability; comprehensive KalshiBot nonmarket trainer and true source EWMA/settlement samples; confidence intervals with day-block clustering; separate accurate pre-onset price move labels and execution bid/ask order-book replay.
- **Do not integrate XGB** on current evidence; Schen-like M0 is a reasonable *research challenger* but not proven to improve accuracy. Keep all active models unchanged and all new work on a draft research PR.
