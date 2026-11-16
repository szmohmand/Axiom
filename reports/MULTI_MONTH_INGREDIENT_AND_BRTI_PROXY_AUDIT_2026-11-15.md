# AXIOM: large multi-month model-ingredient replication & settlement-reference audit

**Research executed:** November 15, 2026 ET / November 16, 2026 UTC  
**Status:** EXPLORATORY, retrospective BTC/USDT-proxy historical research — **NOT** fully verified BRTI point-in-time model accuracy, trading profit, original full-bot parity, or evidence of pre-move foresight.  
**No implementation or deployment:** all active AXIOM services, model code, contracts, order execution, paper ledger, dashboard, and verified main remain unchanged.  
**Preserved main/recovery SHA:** b12be3758049b6766dda8fefad06611bf41ada2e  
**Research child branch:** research/monthly-cohort-independent-validation-2026-11-15 (stacked over research/feature-ablation-and-audit-2026-11-15)  
**Underlying source:** DegenHedge/kalshi-btc-15m dataset v2026.10.1 (Kalshi's original market facts; DegenHedge-created fields CC BY 4.0), and Binance public monthly BTCUSDT spot market 1-minute OHLCV trade klines.

## 1. Executive conclusion

**The main ingredient finding REPLICATED: BTC's volatility-normalized distance from the contract target is overwhelmingly more useful than momentum and RSI.** This held across 25,302 valid historical contracts, multiple months, four recorded 15m checkpoints, and two explicit alternative approximations of the unavailable BRTI opening index.

**The purported five-minute/final-minute superiority of a trained full logistic model did NOT reliably replicate.** A simple adapted HeadStart calculation, its near-equivalent Schen zero-drift proxy, and a near-fixed logistic mapping frequently had Brier differences measured only in the fourth or fifth decimal place. A July-August validation-selected model switch generally did NOT clearly beat unmodified HeadStart on September-October data.

**Most important newly verified source limitation:** The post-hoc Binance-to-BRTI basis correction was imperfect enough to change the *winner* for 3.26%–7.02% of 25,302 official contracts, depending only on which plausible 1-minute opening reference formula we used. These official-outcome discrepancies show that this corpus **cannot** certify true Kalshi BRTI probability calibration or a production edge.

**Market uncertainty remains where the user most needs it:** near the target, even with only 60 seconds left, the best simple model was only around 52%–57% directionally correct in some tested proxy-defined subgroups, whereas far-ahead contracts were about 98% correct. Late aggregate hit rate is strongly influenced by easy contracts already far from the target; not by validated advance prediction of an impending move.

## 2. Authentic source evidence & eligibility

| Source / partition | Verified count | Notes |
|---|---:|---|
| Kalshi published KXBTC15M outcome rows | 25,370 | January 10–October 4, 2026 |
| Excluded because official strike was flagged/missing | 68 | No made-up target |
| **Accepted official labels and strike rows** | **25,302** | Result stays Kalshi's YES or NO |
| Binance published BTCUSDT 1m trade candles | **437,760** | Jan–Oct 2026, all 10 monthly ZIP checksums verified |
| Training (Jan–Jun) | **16,212 contracts / 172 UTC days** | 81,060 checkpoint samples |
| Chronological validation (Jul–Aug) | **5,867 contracts / 62 UTC days** | 29,335 checkpoint samples |
| Later research test (Sep–Oct 4) | **3,223 contracts / 34 UTC days** | 16,115 checkpoint samples |
| Total retained checkpoint observations | **126,510** | Every contract has the SAME five eligible minute checkpoints |

No artificial interpolation of missing one-minute trading bars. Exact per-month source archive SHA256 and Kalshi fingerprint are emitted into the reproducible run log and JSON output. Kalshi windows.csv **pinned SHA256**: 9fd4f92f7b85038c825c7468e4e982ca17f7f4c4bb4cba75f1760f51262078d7.

## 3. Measurement periods, authentic data and major qualification

Historical checkpoint periods:
1. **First two minutes:** opening **+60 seconds and +120 seconds**. Both checkpoints are averaged **within each contract**, then contracts equally weighted.
2. **10 minutes left:** 300 seconds after opening.
3. **5 minutes left:** 600 seconds after opening.
4. **Final minute:** **60 seconds left ONLY**. The dataset has no 15-, 5-, or 1-second contemporaneous trading snapshots, so this is **not** a claim about the complete final 60-second interval.

At each time the calculations use 61 completed authentic one-minute Binance trading OHLC bars, the published official Kalshi target as a conditional retrospective input, and time to expiration. The target is read from a **historical Kalshi API-derived file whose original first-publication timestamp was not recorded.** The historical true official BRTI opening and preceding 60-second index observations are not available. This is therefore **not a strictly point-in-time-valid live replay**.

To stress-test price-reference sensitivity, both historical models use the official target but independently shift the Binance historical price series by:
- **OHLC4 anchor:** official strike minus the mean of the open/high/low/close of Binance's minute immediately before the window opens;
- **Pre-open last-close anchor:** official strike minus that Binance candle's final trade close.

Shifting by the after-the-fact official strike is a deliberate *conditional proxy experiment*, not evidence that the equivalent Binance/BRTI basis was known or tradable at the decision time. Both anchors use the SAME official outcome truth; neither is the settlement source.

No Kalshi YES/NO contract prices enter independently computed probabilities, and no after-expiration official index is used as a prediction feature.

## 4. Larger held-out results: original formulas vs trained alternatives

Each cell is **Brier score / directional accuracy** on the **same 3,223 contracts**, lower Brier better. The first table uses the more accurate (but still imperfect) OHLC4 price proxy. The second repeats with pre-open last-close proxy.

### 4a. OHLC4 opening anchor (September–October 4 research test)

| Model | First 2m | 10m left | 5m left | 60s left |
|---|---|---|---|---|
| Untrained adapted HeadStart | 0.229740 / 61.96% | 0.192620 / 70.34% | 0.132790 / 80.73% | 0.050965 / 93.05% |
| Schen zero-drift 1m proxy | 0.229759 / 61.65% | 0.192616 / 70.49% | 0.132803 / 80.73% | 0.050975 / 93.02% |
| Trained logistic, HeadStart alone | 0.229735 / 61.77% | 0.192601 / 70.37% | 0.132836 / 80.83% | 0.050987 / 93.02% |
| Trained logistic, HeadStart+momentum+RSI | 0.229812 / 61.57% | 0.192545 / 70.37% | 0.132891 / 80.76% | 0.050984 / 93.02% |
| Trained logistic WITHOUT HeadStart | 0.240310 / 58.61% | 0.197227 / 69.93% | 0.170084 / 75.12% | 0.118338 / 88.55% |
| Current AXIOM ensemble | 0.233990 / 61.14% | 0.194695 / 70.25% | 0.134145 / 80.67% | 0.052502 / 92.86% |
| AXIOM original volatility | 0.234520 / 61.12% | 0.195224 / 70.25% | 0.134099 / 80.67% | 0.052396 / 92.86% |
| Aaryann momentum fair calculation | 0.236637 / 61.17% | 0.196524 / 70.21% | 0.139666 / 80.30% | 0.053399 / 93.02% |

Within this source assumption, the best nominal Brier was the fixed sigmoid(1.7*HeadStart) probability mapping at the first 2m (0.229734), 5m (0.132708), and 60s (0.050906); at 10m, logistic WITHOUT momentum was 0.192545. The wins over direct HeadStart are **tiny** and highly prone to hindsight selection. Scores vary substantially more by time and proxy assumption than by which of these closely related formulas was used.

### 4b. Pre-open last-close anchor (September–October 4 research test)

| Model | First 2m | 10m left | 5m left | 60s left |
|---|---|---|---|---|
| Untrained adapted HeadStart | 0.230440 / 61.29% | 0.193562 / 69.25% | 0.134112 / 81.07% | 0.060260 / 91.68% |
| Schen zero-drift 1m proxy | 0.230457 / 61.20% | 0.193556 / 69.25% | 0.134123 / 81.17% | 0.060281 / 91.68% |
| Trained logistic, HeadStart alone | 0.230394 / 61.32% | 0.193490 / 69.13% | 0.134079 / 81.14% | 0.059378 / 91.68% |
| Trained logistic, full features | 0.230215 / 61.36% | 0.193475 / 69.47% | 0.133910 / 81.32% | 0.059377 / 91.68% |
| Trained logistic WITHOUT HeadStart | 0.240310 / 58.61% | 0.197227 / 69.93% | 0.170084 / 75.12% | 0.118338 / 88.55% |
| Current AXIOM ensemble | 0.232533 / 61.17% | 0.195923 / 69.25% | 0.135609 / 80.58% | 0.059212 / 91.84% |
| AXIOM original volatility | 0.232973 / 61.23% | 0.196457 / 69.25% | 0.135619 / 80.58% | **0.058914 / 91.84%** |
| Aaryann momentum fair calculation | 0.235005 / 61.22% | 0.197795 / 69.25% | 0.141214 / 79.74% | 0.059956 / 91.65% |

**AXIOM's original volatility, not the early HeadStart formula or the full logistic, had the best nominal Brier 60 seconds before expiry with this second proxy**. That unstable ranking blocks a claim that learned late calibration is generally best.

## 5. Main ingredient ablation: remove HeadStart and RE-FIT momentum and RSI

Change in Brier when the learned logistic is re-fitted without normalized target-distance/volatility HeadStart; **positive means degraded forecasting**, same 3,223 contracts and 34 holdout days.

| Held-out window | Brier penalty, OHLC4 | 95% day-block bootstrap interval |
|---|---:|---|
| First two minutes | +0.010498 | +0.007722 to +0.013684 |
| 10 minutes left | +0.004681 | +0.001957 to +0.007494 |
| 5 minutes left | **+0.037192** | **+0.031590 to +0.042612** |
| 60 seconds left | **+0.067354** | **+0.059445 to +0.074885** |

This is the clearest replicated model-ingredient finding: **distance relative to target, scaled by volatility and remaining time, is essential to the logistic's historical ability to estimate final YES/NO**. Refit momentum and RSI cannot recover it. The mechanism is unsurprising but empirically important. It is NOT a newly discovered pre-movement price signal.

Changes from removing momentum or RSI (with refitting) were only around a few 0.00001 to 0.0001 Brier in most out-of-training periods, frequently changed signs between validation/test, and generally had bootstrap confidence intervals crossing zero. An elaborate feature stack is **not justified** by these results.

Schen and adapted HeadStart share almost the same normalized-distance/horizon formula, differ by tiny log/linear and Ito corrections and confidence caps, and are **not** independent ensemble intelligence sources.

## 6. Chronological adaptive model switching: prospective *within the archived data* but not a genuine live trial

We pre-specified **four** possible period candidates in this experiment: HeadStart direct, learned HeadStart-only logistic, learned full logistic, and existing AXIOM ensemble. Fit logistic on Jan–Jun; select the lowest July–August Brier among these four independently **for each of four time windows**; evaluate that frozen selection on Sep–Oct 4. No Sept–Oct outcomes used to select the candidate within this archival split.

### OHLC4 model selected by validation then tested

| Window | July–August selected model | Test Brier | Test advantage vs direct HeadStart | 95% day-bootstrap CI on difference |
|---|---|---:|---:|---|
| First 2m | Logistic HeadStart-only | 0.229735 | +0.000005 | −0.000181 to +0.000180 |
| 10m left | Logistic HeadStart-only | 0.192601 | +0.000019 | −0.000237 to +0.000258 |
| 5m left | Logistic full | 0.132891 | **−0.000101** | −0.000561 to +0.000359 |
| 60s left | Logistic full | 0.050984 | **−0.000019** | −0.000189 to +0.000139 |

*Positive advantage means lower Brier than direct HeadStart. The confidence intervals include zero in ALL FOUR WINDOWS.* The validation-selected schedule **did not establish a repeatable performance improvement** over a single direct HeadStart formula. With the second proxy, one late model improvement of only ~0.000883 Brier was apparent, but the same second proxy misidentified the underlying official winner in 7.02% of contracts; the result is not robust across input references.

The model hypothesis itself was informed by our previously inspected October 25 data and modern code research. Although the split is chronological WITHIN this corpus, the Sep–Oct labels precede the prior October 25 analysis: we **cannot call it truly untouched prospective market confirmation**.

## 7. Official Kalshi settlement-versus-Binance proxy basis audit

**THIS IS THE MOST IMPORTANT SOURCE-FIDELITY FINDING IN THE BATCH.** We never replace the official YES/NO result, but compare whether a simple Binance opening-offset, close-price approximation would have declared the same contract winner.

| Basis audit statistic | OHLC4 opening-anchor proxy | Pre-open close anchor proxy |
|---|---:|---:|
| Official labeled contracts compared | 25,302 | 25,302 |
| Official numeric BRTI expiration values available | 24,941 | 24,941 |
| **Different eventual winner from official result** | **825** | **1,777** |
| **Proxy error rate** | **3.26061%** | **7.02316%** |
| Mean absolute proxy minus official BRTI expiration value | **$9.10** | **$20.33** |
| Median absolute difference | **$6.28** | **$12.93** |
| 95th-percentile absolute difference | **$26.60** | **$63.40** |
| Contracts where proxy ended within $2 of target | 433 | 426 |
| Of those $2 close-call contracts, wrong official winner using proxy | **192 / 433 (44.3%)** | **217 / 426 (50.9%)** |
| Contracts where proxy ended within $10 of target | 2,262 | 2,074 |
| Of those $10 close-call contracts, wrong official winner using proxy | **599 / 2,262 (26.5%)** | **782 / 2,074 (37.7%)** |

These are **post-settlement fidelity diagnostics**: input features used by model still remain time-restricted Binance trade candles, and the official label always stays Kalshi's. Wrong winner is if one *substituted* the proxy-based closing price for the actual index. The highest substitution risk is close to the target—precisely the hard scenarios where we need forecasting reliability.

A more elaborate probability model cannot fix an incorrectly identified target/settlement-reference relationship. The opening-minute model used the *published official strike retroactively* to rebase the exchange price. Without timestamped published strike and actual CF BRTI tick histories, exact real-time replay remains unproved.

## 8. Near-target cases vs easy far-target contracts — held-out Sep–Oct

At 5 minutes left, with OHLC4 anchor:
- **Near target** (abs normalized target gap z < 0.5): **858 contracts**, HeadStart Brier **0.238245**, directional accuracy **58.97%**.
- **Far from target** (abs z >=1.5): **1,033 contracts**, HeadStart Brier **0.032751**, directional accuracy **96.61%**.

At 60 seconds left, same anchor:
- **Near target:** **225 contracts**, HeadStart Brier **0.244099**, directional accuracy **57.33%**.
- **Far from target:** **2,546 contracts**, HeadStart Brier **0.015951**, directional accuracy **98.35%**.

For the second proxy, the near-target 60s accuracy fell to **51.94%** on 206 contracts, while far-target accuracy remained **97.68%** on 2,582 contracts.

**Explanation:** As expiration approaches, more contracts become obvious simply because the observed BTC price is far from target relative to likely remaining volatility. This can yield overall 90%+ direction accuracy without an independently predictive leading indicator. The genuinely difficult near-target sample remains poorly understood.

Because the subgroup labels use the proxy's normalized gap, these are descriptive **post-hoc** diagnostic partitions, NOT a fitted or verified live uncertainty gate.

## 9. Time-relative best method summary

| Moment | Larger-sample research takeaway |
|---|---|
| First two minutes after opening | Direct, volatility-normalized target distance is competitive. The learned extra features do not demonstrate a robust gain; direction accuracy only about 61–62% in later historical test under these proxy assumptions. |
| 10m left | Direct HeadStart, close Schen analogue, and low-parameter logistic mapping nearly tied, about 69–70% conditional accuracy. |
| 5m left | Direct/headstart-only logistic competitors about 80–81% conditional accuracy. Removing target distance severely harms performance; extra momentum and RSI do not provide reliably incremental performance. |
| 60s left | Aggregate accuracy around 92–93% mostly due to easy far-from-target cases. Model leader changes depending on the missing BRTI opening reference approximation, and near-target contracts remain around chance. |

**A time-dependent probability transform may be sensible but has not yet demonstrated a robust Brier improvement.** Do not hard-switch whole models at five minutes based on the previous two-day leader; the broader evidence disagrees.

## 10. Engineering / source / statistical audit

Verified:
- Genuine public-source downloaded ZIP and CSV checksums (Binance 10 archives, pinned Kalshi CSV).
- Real one-minute trade OHLC instead of fabricated candle or exchange-mid-quote pseudo bars.
- Completed-minute timestamps, 61 consecutive bar lookback, no future candle within any decision; all five checkpoints required per contract.
- Exact target/contract/expiration identity; official outcomes used strictly as historical training labels and grading truth.
- Same set of contracts for every source-proxy model. Two alternative offset scenarios and 34-day cluster uncertainty.
- Separate Jan–Jun training, Jul–Aug calibration/model-choice validation, Sep–Oct descriptive later research test.
- Frozen AXIOM original functions called from read-only replay; no deployment or live probability changes.
- Plain Python fallback allows full native AXIOM regression test suite WITHOUT installing an optional numerical package into app runtime. NumPy installed only on isolated research Actions runner.
- Frozen-reference logistic gradient solver parity checked on a sufficiently sized same-checkpoint sample.

Research defects discovered and corrected:
1. Misaggregated day-bootstrap Brier values and hard-coded 2000-draw confidence indices made unit tests fail. Replaced with exact per-day total and draw-count-aware quantile indices; tested on controlled 100-draw fixtures.
2. Research NumPy import at module/test discovery broke existing full production dependency test environment. Made numerical acceleration optional, added mathematical fallback, and verified parity without the optional package.
3. Initial optimizer source-parity check used 40 examples despite the valid research model's >=100 observation floor. Replaced with a genuinely 160-example same-time sample without relaxing guard.
4. Selection fixture originally omitted one expected model; preserved real evaluator's complete-model requirements and supplied complete synthetic test input instead of weakening its check.
5. Added immutable official versus proxy winner testing and a test proving the model selected on earlier months cannot be changed using later-month labels.
6. Added permanent regression-history A20–A23, preserving the floor for the complete original suite.

**Unresolved material scientific issues:** no source-proven historical strike first-publication timestamp; no exact BRTI real-time index input or 60-second partial ticks; Binance BTCUSDT is different from the actual BTC/USD reference; historic source revisions and quotes' publication latency not fully verifiable; no contemporaneous order book asks/fill confirmation for every chosen checkpoint; Sep–Oct is an exploratory retrospective test and not independent confirmation of the model class chosen after studying later dates. These are NOT secretly fixed or certified by green CI.

**Consequence:** PASS for isolated reproducibility, official-label integrity tests, preserving the existing implemented AXIOM and historical regression functionality, with current exact-commit CI evidence. BLOCK for model promotion, trade execution, forecast accuracy guarantees, economic alpha, or advance pre-move prediction.

## 11. Required next genuinely decisive experiment

Keep the existing AXIOM model unchanged. For a new future-only paper research cohort, record **before each prediction**:
- Actual Kalshi contract ticker, published strike and its verified first-observed timestamp;
- 1-second BRTI spot index observations and partial 60-second opening/closing averaging status where authorized; independent Coinbase/Bitstamp/Kraken quotes and trade bars with receipt times;
- Actual available YES/NO bids, asks, spread, fee tiers and depth; immutable predicted probabilities on fixed checkpoints;
- Later official settled YES/NO matched by contract identity, excluding stale/unknown outcomes.

Then fit calibration only on prior official outcomes, lock weights, and report proper held-out Brier/logloss, near-target uncertainty, early call lead, same-contract calibration, and realistic execution prices. Do not promote or auto-trade unless all of AXIOM's existing strict regression, source-fidelity, no-regression, and full-system safety gates pass.

## 12. Reproduction and read-only evidence

- Isolated reproducible script: [research/monthly_cohort_replay.py](https://github.com/szmohmand/Axiom/blob/research/monthly-cohort-independent-validation-2026-11-15/research/monthly_cohort_replay.py)
- Permanent tests: [tests/test_monthly_cohort_replay.py](https://github.com/szmohmand/Axiom/blob/research/monthly-cohort-independent-validation-2026-11-15/tests/test_monthly_cohort_replay.py)
- Reproducibility workflow: [.github/workflows/axiom-monthly-cohort-replay.yml](https://github.com/szmohmand/Axiom/blob/research/monthly-cohort-independent-validation-2026-11-15/.github/workflows/axiom-monthly-cohort-replay.yml)
- First complete real-month run: https://github.com/szmohmand/Axiom/actions/runs/43782175861
- Extended settlement-basis / validation-selector / near-target scenario audit: https://github.com/szmohmand/Axiom/actions/runs/43782815193
- Final exact-head workflow, full original suite, real provider read-only smoke, and optional XGBoost results are recorded on the draft research PR once all checks are reverified.

**DO NOT merge this research branch into a live forecasting branch or claim actual Kalshi index parity.**
