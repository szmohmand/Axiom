# AXIOM Batch 1 — 100 checks, actual historical evidence, full-system safety

**Date:** November 15, 2026  
**Scope:** read-only isolated research child branch, NOT the live model  
**Source branch:** `research/isolated-btc-challengers-2026-11-15` at `e331cfee9c8f823c748e40d9d41da2ad5fa8f84b`  
**Immutable source baseline identity:** `b12be3758049b6766dda8fefad06611bf41ada2e`  
**Preserved recovery:** `verified/2026-11-15-b12be37` (unchanged)  
**Original verified runtime identity:** `902f7d7dfd7a4a952b4afc2019f01a599af43355`

## Status and the important qualification

- **100/100 numbered deterministic research-safety checks passed.** One additional case-inventory integrity test passed; 101 total in the dedicated suite.
- AXIOM's full historical regression and end-to-end CI, authentic real-source read-only smoke test, and separately isolated optional XGBoost synthetic test were green on this research child branch. The final exact-commit checks must be verified again after the report-only commit.
- **An additional public historical data experiment actually ran on 25,370 Kalshi BTC15m windows and 11,360 independently source-matched official-only alerts.** This does NOT score AXIOM's challengers; that requires actual as-of BTC features unavailable in the used source tables.
- **No deployment, order placement, model promotion, live application edit, main merge, runtime dependency upgrade, or automated continuing collection.**
- The 100 cases are code/methodology/failure-mode tests on clearly synthetic inputs. They are NOT 100 independent financial experiments and are NOT proof of profitable early forecasting. The distinct public historical dataset audit provides the real empirical measurements below.

## Authentic historical evidence: exactly what was analyzed

Public source: [DegenHedge/kalshi-btc-15m](https://huggingface.co/datasets/DegenHedge/kalshi-btc-15m), v2026.10.1 public CSV release. Data dictionary explains official settlement/proxy tags and published signal selection. Dates span January 10–October 4, 2026; subset of logged alerts from March–October 2026.

**SHA256 of files actually fetched:**

- `windows.csv`: `9fd4f92f7b85038c825c7468e4e982ca17f7f4c4bb4cba75f1760f51262078d7`
- `signals.csv`: `34ec73ba13188daf99f42eb1b674ef14f1c207ec7c24a36f05b8395f68987fca`

| Real source metric | Verified value |
|---|---:|
| Published KXBTC15M window rows | 25,370 |
| Distinct usable KXBTC15M window identities | 25,370 |
| Rows with yes/no result | 25,370 |
| Windows with a reported usable official strike | 25,302 |
| Publisher-selected alert rows | 11,541 |
| Excluded: graded via publisher's own spot fallback | 167 |
| Excluded: logged timing differs from window close by more than 2 seconds | 14 |
| Publisher-selected, strictly official-graded and timing-consistent alerts retained | **11,360** |
| Unique UTC days with retained alerts | 194 |
| Correct direction for these *selected third-party* alerts | **91.25%** |
| Average stated model confidence for selected direction | **91.9553%** |
| Binary YES-target Brier score (same side converted to YES probability) | **0.076915** |
| Binary log loss | **0.277891** |
| Illustrative purchased-at-logged-ask gross contract return | **−$0.005162** |
| Illustrative taker fee at 7% × p × (1−p), rounded up to cents per contract | **$0.011502** |
| Illustrative purchased-at-logged-ask after-fee return | **−$0.016664** |

**Bootstrap:** 1,000 resamples of whole UTC days with deterministic seed 20261115; intervals describe this **selected alert sample**, NOT executable trading or out-of-sample AXIOM performance.

| Statistic | Approximate day-block bootstrap 95% interval |
|---|---|
| Selected-alert directional win rate | **90.58%–91.82%** |
| Selected-alert Brier score | **0.072617–0.081939** |
| Illustrative after-fee contract return | **−$0.021763 to −$0.011997** |

**Monthly variation** (retained strictly official alerts only): March 260 alerts, 81.92% win, −3.32¢ illustrative after fees; April 1,669, 91.13%, −1.42¢; May 1,705, 92.26%, −1.35¢; June 1,915, 91.17%, −1.63¢; July 1,751, 92.86%, −0.70¢; August 1,810, 91.60%, −2.10¢; September 2,017, 89.74%, −2.58¢; October 233, 93.99%, −0.13¢.

**Lead-time coverage:** 11,359 of 11,360 retained historical signals were logged from **2 to 5 minutes before expiry**; one was 1–2 minutes before expiry. None was 5–10 minutes before expiry or 10+ minutes before expiry. Expiry timing is NOT the time before an actual BTC price move starts. This dataset cannot demonstrate advance prediction of an imminent move, nor test accuracy at AXIOM's 14m or 10m checkpoints.

### Why the 91.25% result does NOT prove an edge

The source publishes a **selection of alerted signals** with quoted ask between 1¢ and 99¢, not every candidate or every time; selection and timing raise win rate, and most selected contracts were relatively expensive. The paid ask can exceed the empirical win probability, before fees. The ask was reconstructed from opposing bids; no guaranteed fill/size, liquidity, queue position, real trading P&L, slippage, or latency is established. Actual market-specific fee exceptions were not audited. Historical publisher model training provenance is not audited. Consequently the illustrative P&L is a sanity check, **not a backtest of actual executable trading**.

The CSV does **not** publish the proprietary model's contemporaneous BTC features or spot observations, and its official results are generated after the call. It cannot legitimately produce same-input challenger Brier or an AXIOM calibration score. We must not silently substitute after-the-fact prices and claim point-in-time evidence.

## Existing and foreseeable AXIOM-system safety

1. Only added isolated `tests/test_batch1_100.py`, `research/public_dataset_audit.py`, the standalone read-only experimental GitHub Action, and this dated report on the child branch. No app source or operational data was mutated.
2. Test functions exercise malformed timestamps, future values, gapped/minute-invalid bars, improperly sourced outcomes, same-observation Kalshi-odds independence, proper scoring, unavailable training history, and official-only logging.
3. All prior permanent regressions remain protected; the project's full original suite includes historical source archives, feed quality, official grading, storage/rollback, concurrency/recovery, UI, security and synthetic end-to-end. A PASS applies to **implemented** and **tested** behavior, not unknowable future changes.
4. Exact action run for 101/101 case file + public source re-audit + 20 historical regression checks: https://github.com/szmohmand/Axiom/actions/runs/43771886327
5. Exact corresponding full-suite regression run: https://github.com/szmohmand/Axiom/actions/runs/43771886351
6. Exact corresponding unchanged real-provider read-only smoke: https://github.com/szmohmand/Axiom/actions/runs/43771886391
7. Exact corresponding optional real XGBoost code trained on clearly synthetic fixtures in an ephemeral runner: https://github.com/szmohmand/Axiom/actions/runs/43771886322
8. No original external-trained bot or its full feature, training and calibration code is reproduced. No claim of model parity or improvement.

## What data has actually become available for the NEXT 100 scientific tests

- DegenHedge provides many published **official BTC15m outcome labels and targets** but deliberately omits exchange spot feature histories; suitable for outcome-universe/statistical checks, **not** actual full independent-model replays.
- [Kalshi Eye's public historical sample](https://huggingface.co/datasets/KalshiEye/kalshi-order-book-sample) contains 15-minute BTC spot, book and settlement recordings on October 13 and October 25, 2026. The source reports 96 BTC windows each day and exchange spot streams. The sample is CC BY-NC 4.0 for noncommercial research. We have **discovered and inspected the documentation**, not yet ingested or replayed those files. Its 91.5% Oct 13 and 99.8% Oct 25 recording coverage, gaps and receipt-vs-exchange timestamps require explicit treatment.
- Prior local Library historical outcomes dated December 2025 are quarantined for missing numeric targets and belong to an earlier ruleset. They were not mixed into the January–October 2026 experiment.
- The full experiment needs genuine as-of BTC/market feeds, known timestamps, independent Kalshi price benchmarks, official BRTI-resolved labels, valid buyable asks/bids and chronological training without future labels. A model winner can only be named after matched-contract holdout comparisons and quantified uncertainty.

## Batch 1: individually numbered execution ledger

The descriptions below are concise literal inputs/conditions from source. **PASS** denotes a collected and passing pytest parameterized test in the 101-test GitHub CI; all synthetic, all independently numbered. See `tests/test_batch1_100.py` for complete assertions and fixtures.

| Case | Test domain | Input/condition | Result |
|---|---|---|---|
| G001 | Contract identity and timing | `"ticker",""` | PASS |
| G002 | Contract identity and timing | `"ticker","KXETH15M-WRONG"` | PASS |
| G003 | Contract identity and timing | `"ticker",123` | PASS |
| G004 | Contract identity and timing | `"ticker",MISSING` | PASS |
| G005 | Contract identity and timing | `"ts",lambda r:r["open_ts"]-1` | PASS |
| G006 | Contract identity and timing | `"ts",lambda r:r["expires_ts"]` | PASS |
| G007 | Contract identity and timing | `"expires_ts",lambda r:r["open_ts"]-1` | PASS |
| G008 | Contract identity and timing | `"open_ts",lambda r:r["ts"]+1` | PASS |
| G009 | Contract identity and timing | `"target_ts",lambda r:r["ts"]+1` | PASS |
| G010 | Contract identity and timing | `"target",0` | PASS |
| G011 | Spot validity and freshness | `"spot_ts",lambda r:r["ts"]+1` | PASS |
| G012 | Spot validity and freshness | `"spot_ts",lambda r:r["ts"]-31` | PASS |
| G013 | Spot validity and freshness | `"spot_ts",None` | PASS |
| G014 | Spot validity and freshness | `"spot_ts",True` | PASS |
| G015 | Spot validity and freshness | `"spot",0` | PASS |
| G016 | Spot validity and freshness | `"spot",-1` | PASS |
| G017 | Spot validity and freshness | `"spot",float("inf")` | PASS |
| G018 | Spot validity and freshness | `"spot",float("nan")` | PASS |
| G019 | Spot validity and freshness | `"spot",True` | PASS |
| G020 | Spot validity and freshness | `"spot","not-a-price"` | PASS |
| G021 | Authentic completed minute bars | `lambda c:None` | PASS |
| G022 | Authentic completed minute bars | `lambda c:c[:30]` | PASS |
| G023 | Authentic completed minute bars | `lambda c:[*c[:-1],"malformed"]` | PASS |
| G024 | Authentic completed minute bars | `lambda c:[*c[:-1],dict(c[-1],t=c[-1]["t"]+.5)]` | PASS |
| G025 | Authentic completed minute bars | `lambda c:[*c[:-1],dict(c[-1],t=c[-1]["t"]+60)]` | PASS |
| G026 | Authentic completed minute bars | `lambda c:[*c[:-1],dict(c[-1],t=c[-1]["t"]-60)]` | PASS |
| G027 | Authentic completed minute bars | `lambda c:[*c[:-1],dict(c[-1],t=c[-1]["t"]+120)]` | PASS |
| G028 | Authentic completed minute bars | `lambda c:[*c[:-1],dict(c[-1],high=c[-1]["close"]-1)]` | PASS |
| G029 | Authentic completed minute bars | `lambda c:[*c[:-1],dict(c[-1],low=-2)]` | PASS |
| G030 | Authentic completed minute bars | `lambda c:[*c[:-1],dict(c[-1],volume=-1)]` | PASS |
| G031 | Kalshi benchmark quote integrity | `"market_mid",-.001` | PASS |
| G032 | Kalshi benchmark quote integrity | `"market_mid",0` | PASS |
| G033 | Kalshi benchmark quote integrity | `"market_mid",1` | PASS |
| G034 | Kalshi benchmark quote integrity | `"market_mid",1.1` | PASS |
| G035 | Kalshi benchmark quote integrity | `"market_mid",float("nan")` | PASS |
| G036 | Kalshi benchmark quote integrity | `"market_mid","not-a-probability"` | PASS |
| G037 | Kalshi benchmark quote integrity | `"market_mid_ts",MISSING` | PASS |
| G038 | Kalshi benchmark quote integrity | `"market_mid_ts",lambda r:r["ts"]+1` | PASS |
| G039 | Kalshi benchmark quote integrity | `"market_mid_ts",lambda r:r["ts"]-31` | PASS |
| G040 | Kalshi benchmark quote integrity | `"market_mid",True` | PASS |
| G041 | Official settlement labels | `"ticker",""` | PASS |
| G042 | Official settlement labels | `"ticker","KXETH15M-WRONG"` | PASS |
| G043 | Official settlement labels | `"result","unresolved"` | PASS |
| G044 | Official settlement labels | `"result",0` | PASS |
| G045 | Official settlement labels | `"source","unknown"` | PASS |
| G046 | Official settlement labels | `"source","synthetic_fixture"` | PASS |
| G047 | Official settlement labels | `"settled_at",lambda r:r["expires_ts"]-1` | PASS |
| G048 | Official settlement labels | `"expires_ts",None` | PASS |
| G049 | Official settlement labels | `"settled_at",float("nan")` | PASS |
| G050 | Official settlement labels | `"result",None` | PASS |
| G051 | Fixed checkpoint classification | `840,"14m"` | PASS |
| G052 | Fixed checkpoint classification | `869,"14m"` | PASS |
| G053 | Fixed checkpoint classification | `810,"14m"` | PASS |
| G054 | Fixed checkpoint classification | `720,"12m"` | PASS |
| G055 | Fixed checkpoint classification | `600,"10m"` | PASS |
| G056 | Fixed checkpoint classification | `300,"5m"` | PASS |
| G057 | Fixed checkpoint classification | `60,"1m"` | PASS |
| G058 | Fixed checkpoint classification | `29,None` | PASS |
| G059 | Fixed checkpoint classification | `180,None` | PASS |
| G060 | Fixed checkpoint classification | `901,None` | PASS |
| G061 | Kalshi-odds independence | `.01,.99` | PASS |
| G062 | Kalshi-odds independence | `.02,.98` | PASS |
| G063 | Kalshi-odds independence | `.07,.93` | PASS |
| G064 | Kalshi-odds independence | `.15,.85` | PASS |
| G065 | Kalshi-odds independence | `.25,.75` | PASS |
| G066 | Kalshi-odds independence | `.30,.70` | PASS |
| G067 | Kalshi-odds independence | `.40,.60` | PASS |
| G068 | Kalshi-odds independence | `.45,.55` | PASS |
| G069 | Kalshi-odds independence | `.49,.51` | PASS |
| G070 | Kalshi-odds independence | `.05,.95` | PASS |
| G071 | Brier/log-loss and calibration arithmetic | `.01,0` | PASS |
| G072 | Brier/log-loss and calibration arithmetic | `.10,0` | PASS |
| G073 | Brier/log-loss and calibration arithmetic | `.20,0` | PASS |
| G074 | Brier/log-loss and calibration arithmetic | `.33,0` | PASS |
| G075 | Brier/log-loss and calibration arithmetic | `.49,0` | PASS |
| G076 | Brier/log-loss and calibration arithmetic | `.50,1` | PASS |
| G077 | Brier/log-loss and calibration arithmetic | `.51,1` | PASS |
| G078 | Brier/log-loss and calibration arithmetic | `.73,1` | PASS |
| G079 | Brier/log-loss and calibration arithmetic | `.90,1` | PASS |
| G080 | Brier/log-loss and calibration arithmetic | `.99,1` | PASS |
| G081 | Chronological train/test leakage guards | `"insufficient_nine"` | PASS |
| G082 | Chronological train/test leakage guards | `"one_sided_outcome"` | PASS |
| G083 | Chronological train/test leakage guards | `"labels_future"` | PASS |
| G084 | Chronological train/test leakage guards | `"only_nine_available"` | PASS |
| G085 | Chronological train/test leakage guards | `"minimum_ten"` | PASS |
| G086 | Chronological train/test leakage guards | `"row_order_permutation"` | PASS |
| G087 | Chronological train/test leakage guards | `"market_odds_perturbation"` | PASS |
| G088 | Chronological train/test leakage guards | `"future_added_label"` | PASS |
| G089 | Chronological train/test leakage guards | `"boundary_settlement_time"` | PASS |
| G090 | Chronological train/test leakage guards | `"bounded_outlier_probability"` | PASS |
| G091 | Read-only collector and grading lifecycle | `"missing_market"` | PASS |
| G092 | Read-only collector and grading lifecycle | `"missing_target"` | PASS |
| G093 | Read-only collector and grading lifecycle | `"missing_close"` | PASS |
| G094 | Read-only collector and grading lifecycle | `"insufficient_candles"` | PASS |
| G095 | Read-only collector and grading lifecycle | `"stale_candles"` | PASS |
| G096 | Read-only collector and grading lifecycle | `"first_record"` | PASS |
| G097 | Read-only collector and grading lifecycle | `"duplicate_record"` | PASS |
| G098 | Read-only collector and grading lifecycle | `"no_grading_before_expiration"` | PASS |
| G099 | Read-only collector and grading lifecycle | `"official_grading_only"` | PASS |
| G100 | Read-only collector and grading lifecycle | `"idempotent_grading"` | PASS |

**Batch 1 conclusion:** 100/100 research-safety checks PASS; standalone public-data analysis PASS; unchanged AXIOM system full suite/read-only integration PASS. Claiming actual accuracy, independent-model superiority or early-move prediction is **BLOCKED for lack of identical genuine point-in-time model inputs**. Do not merge into active forecasting, deploy, or trade.
