# AXIOM — evidence-backed research integration checkpoint (2026-11-17)

## Scope and preservation
Only szmohmand/Axiom. Baseline main commit b12be3758049b6766dda8fefad06611bf41ada2e is unchanged. Implementation exists only on branch research/evidence-backed-shadow-forecast-2026-11-17. No deployment, live orders, or external account changes.

## Actual sources reviewed
- ChatGPT Library: FINAL_OFFICIAL_BRTI_KALSHI_EVIDENCE_REPORT.html, UPDATED_ALL_42_HYPOTHESIS_REGISTER_OFFICIAL_BRTI.csv, and BTC_180Day_Independent_CrossSource_Validated_Research_PartialRawTransfer_2026-11-16.zip.
- Kalshi Help Center, Crypto Markets: https://help.kalshi.com/en/articles/13823838-crypto-markets
- CF Benchmarks BRTI: https://www.cfbenchmarks.com/data/indices/BRTI
- Existing AXIOM main-branch application, provider, ensemble, storage and regression code.

## Research verdicts
1. Strongest forecast ingredient for an initial challenger: log distance to the Kalshi target, divided by recent realized one-minute volatility times sqrt(minutes remaining). Retrospective official-outcome evaluation supports it as a useful structure, not a proven profitable trading edge.
2. Actual Kalshi quote midpoints beat the standalone BRTI normalized-distance model in 11 of 12 matched historical period/stage cells in the earlier official-source study. Historic quote receipt times and strike first-publication are unverified, so this is not an as-of executable advantage.
3. Longer volatility memory helped movement magnitude/first-passage tasks, but not reliably incremental signed 15-minute settlement prediction.
4. Taker flow, book erosion, breakout variants, model-revision topology and complex independent stage experts have not demonstrated robust incremental expiry-direction benefits in the reviewed experiments. Do not promote them as validated signals.
5. The new 180-day BRTI descriptive pass evaluated 17,043 Kalshi contracts with 15/30/60/120-minute volatility memories and 13/10/5/2-minute remaining checkpoints. For the 60-minute setting: 13m n=16,302 accuracy=.629248 Brier=.226683; 10m n=16,324 accuracy=.707792 Brier=.192882; 5m n=16,313 accuracy=.815362 Brier=.128237; 2m n=16,309 accuracy=.894414 Brier=.076999. These are retrospective and not evidence of live prediction or attainable trading returns.
6. In the unpaired descriptive summaries, 60-minute volatility memory is not universally the lowest Brier. Historical strikes were not proven published at the scoring time. Avoid selection by unpaired sample means.

## Implemented only in isolated branch
- app/settlement_research.py: as-of, complete-bar volatility/strike-time experimental forecast. Uses Coinbase as an EXPLICIT SPOT PROXY, not BRTI. Abstains near target or when data incomplete; does not invent bars.
- app/main.py: exposes a separate optional research_shadow field in the existing state API. Never votes in ensemble, never changes execution decisions, never triggers paper or live orders. Errors in this optional feature are isolated, and stale outputs are suppressed.
- tests/test_settlement_research.py: candidate input, timing, no-lookahead, failure, non-voting and unchanged-original-model regression tests.

## Validation
Full GitHub clean-install regression and synthetic end-to-end workflow: https://github.com/szmohmand/Axiom/actions/runs/44056254541 (success).
Real provider GET-only smoke workflow: https://github.com/szmohmand/Axiom/actions/runs/44056254629 (success).
Neither success establishes statistically validated alpha, real-life fill assumptions or uptime. No release to main.

## Next evidence gates before promotion
- Capture authenticated official BRTI live as-of observations and the 60-second opening and closing averages.
- Verify first publication of strike, actual as-of quote receipt time and model feature timestamps. No retrospectively observed post-decision data.
- Compare exact matched contracts/stages against Kalshi midpoint and simple models; report Brier/log loss, temporal holdouts, calibration and day-block confidence intervals.
- Preserve separate tasks: final-winner probability, short-horizon direction, movement magnitude, and achievable contract entry/exit.
- Verify historic date-specific fees, bid/ask, available depth and slippage before any profit claims.
- Shadow signals cannot vote or drive trades without a separate evidence-based change and complete regression verification.

This is a first incremental research integration, not an assertion of a completed or profitable bot, or exhaustive review of every research archive.


## Additional exact-paired 180-day volatility study (2026-11-17)

The earlier 16-setting summaries had *different* sample coverage for each volatility horizon. A follow-up read-only comparison used the archived minute-end BRTI records and separately archived Kalshi official settlement labels, counting each contract once per stage and comparing candidate histories on EXACT same contracts. Each estimate used fully observed completed minute returns before the target time. The stage remaining times were 13, 10, 5 and 2 minutes. Day-block bootstrap: 1,000 resamples, UTC calendar-day blocks; these results still do not certify actual strike first-publication or real-time index delivery.

Paired Brier gain for the 60-minute memory relative to the 15-minute version:
- 13m: n=16,305; +0.000164, 95% day-block CI [-0.000427,+0.000775], not established.
- 10m: n=16,331; +0.001498, 95% CI [+0.000728,+0.002186], favorable in this retrospective experiment.
- 5m: n=16,318; +0.000917, 95% CI [+0.000184,+0.001640], favorable in this retrospective experiment.
- 2m: n=16,314; +0.000118, 95% CI [-0.000384,+0.000618], not established.

Comparisons of 60 versus 30 minutes had intervals overlapping zero at all four stages, so no claim of superiority to the 30-minute option is justified. These are 16 paired config comparisons on reused outcome periods; multiple comparisons and target/publication timing remain limitations. The serialized reproducible numerical results are in companion local artifact AXIOM_Paired_180Day_Volatility_Memory_2026-11-17.json. No candidate has been promoted into voting or trading.

