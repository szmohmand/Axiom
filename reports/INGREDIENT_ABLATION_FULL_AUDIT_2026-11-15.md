# AXIOM model ingredients: controlled ablation, mechanism analysis, and final verification

Research prepared November 15, 2026. **Evidence status: exploratory historical research; not production validation.**

## 1. Direct answer

**The models are not winning at different times because they discovered completely separate predictive forces.** The most important shared feature is **distance between BTC and the contract target, divided by contemporaneous volatility and a remaining-time factor**. The "Schen M0" and AXIOM HeadStart scores were essentially identical because their risk-normalized distance formulas are nearly identical. The later trained logistic model mostly rescales this *same feature* and adjusts the probability slope/intercept rather than discovering a new movement.

The evidence points toward **one shared time-aware distance/volatility backbone plus carefully verified, time-specific probability calibration** as a research direction. Momentum and RSI have NOT demonstrated stable incremental value. No automated model switching or production replacement is justified by the evidence here.

Source: KalshiEye public historical sample, CC BY-NC 4.0 (noncommercial use), October 13, 2026 as training data; October 25 as previously explored and therefore **exploratory**, not a fresh untouched holdout. There are 44 source-qualified training contracts (522 model snapshots) and 87 October 25 contracts (1,027 model snapshots at 12 times).

Original research branch: research/window-specific-model-rerun-2026-11-15  
Current independent audit branch: research/feature-ablation-and-audit-2026-11-15  
Protected AXIOM main/recovery before and after: b12be3758049b6766dda8fefad06611bf41ada2e

## 2. Why Schen M0 and HeadStart appear to win early

Let S be observed BTC spot, K the contract target, sigma the standard deviation of one-minute BTC log returns, and t the seconds remaining, with t >= 60.

AXIOM's adapted HeadStart can be written approximately:

    z_H = [(S-K)/S] / [sigma * sqrt((t-40)/60)]
    p_H = NormalCDF(z_H), with probability cap 0.005 to 0.995

The research-only Schen M0 (using *minute* sigma in place of source's original per-second EWMA) uses:

    z_M = [ln(S/K) - 0.5 * (sigma^2/60) * (t-30)]
          / [sigma * sqrt((t-40)/60)]
    p_M = NormalCDF(z_M), with probability cap 0.000001 to 0.999999

When price is close to target, ln(S/K) is approximately (S-K)/S; both have **exactly the same time/uncertainty denominator**. Schen adds only a small log-price and stochastic-drift refinement. The HeadStart volatility floor of 0.00005 was **not active in any held-out row for the compared early checkpoints**.

This is strong **mathematical/source-level explanatory evidence**, not a new hidden market signal. Actual original-model mirror tests exactly matched the frozen AXIOM equation outputs at all 12 audited timepoints: maximum reproduced-source difference **zero** at stored output precision.

At each of the first five opening checkpoints the mean absolute Schen-versus-HeadStart difference in predicted probability was about 0.00015 to 0.00019; the models **never disagreed on ABOVE/BELOW direction**. At 10m left their mean absolute probability difference was 0.000155; at 5m left, 0.000523. By 60s left the probability-cap difference produced mean absolute separation about 0.00317, but still **zero direction differences**.

We audited and fixed an important previous source-parity error: comparing Schen's epsilon cap directly to AXIOM's 0.005 cap falsely failed the formula audit. The correct implementation respects each source's existing cap and additionally runs equal-cap counterfactuals. The two variants' small Brier differences must not be presented as two independent confirmations of forecast skill.

## 3. Why trained logistic looks stronger toward expiry

The trained logistic model has these actual inputs:

    probability = sigmoid(intercept + a * HeadStart_z
                                     + b * normalized 5-minute momentum
                                     + c * RSI)

Each checkpoint has its own small-sample coefficients learned ONLY on October 13 official outcomes. The full trained model was reimplemented independently and its fitted coefficients were confirmed identical to the research baseline.

Examples of October 13 fitted weights:

| Checkpoint | Intercept | HeadStart coefficient | Momentum coefficient | RSI coefficient |
|---|---:|---:|---:|---:|
| +15s after open | +0.052 | +1.778 | -0.410 | -0.090 |
| 10m remaining | +0.283 | +1.903 | +0.118 | -0.112 |
| 5m remaining | -0.131 | +2.115 | -0.388 | +0.240 |
| 60s remaining | +0.158 | +1.984 | -0.082 | +0.021 |
| 15s remaining | +0.241 | +1.891 | -0.098 | +0.039 |

HeadStart retains the largest interpretable coefficient in this small-sample model. Moreover, sigmoid(1.7*z) is a close mathematical approximation to NormalCDF(z); across z in [-4,+4], the maximum theoretical difference is about 0.00956 in probability. Thus the fixed logistic *prior* on HeadStart and the direct HeadStart-CDF model are near relatives, not independent market intelligence.

## 4. Controlled component-removal experiments

Ablation means rerun the same held-out contract/timestamp outcomes while removing one term and, for logistic, RE-FITTING the remaining terms on the earlier October 13 data. Delta is the Brier score of the version with the ingredient removed MINUS the original model; **positive is worse, negative is better**.

| Removal / change | First 2m Brier change | 10m left | 5m left | Final minute |
|---|---:|---:|---:|---:|
| Retrain logistic WITHOUT HeadStart | **+0.024595** | +0.010578 | **+0.052114** | **+0.078687** |
| Retrain logistic WITHOUT five-minute momentum | -0.001439 | -0.000602 | +0.002660 | -0.000087 |
| Retrain logistic WITHOUT RSI | -0.000581 | -0.000176 | -0.001504 | +0.000035 |
| Remove drift/momentum from Aaryann | -0.013749 | -0.001525 | -0.021553 | +0.000306 |
| HeadStart: replace dynamic volatility with October 13 median | +0.007492 | +0.008350 | +0.009182 | +0.005458 |
| HeadStart: remove 60-second averaging time adjustment | +0.000217 | +0.000323 | -0.000084 | +0.001486 |

Interpretation:
- **HeadStart normalized target distance is the dominant useful logistic ingredient**. After fully refitting without it, the remaining RSI and momentum were substantially inferior, especially at five minutes and the end.
- **Momentum is not a demonstrated stable enhancement.** In particular, Aaryann's drift term harmed the five-minute Brier on October 25; removing it improved by about 0.02155, with a nominal 95% bootstrap interval excluding zero. However, once all 83 experimental comparisons are accounted for, that *particular finding does not meet the Holm 5% family-wise threshold*. It is a hypothesis for genuinely fresh data, NOT an established repair.
- **RSI's marginal benefit was not established.** Eliminating RSI in the five-minute logistic lowered Brier by 0.00150 without changing a single directional call. That is a small calibration effect on one previously examined day, not proof that RSI should permanently be removed.
- **Using contemporaneous volatility rather than a constant training-day volatility appears useful, particularly late.** The static alternative had worse Brier at all four periods, but these time-specific effects did not survive the multiple-testing correction.
- The 60-second time normalization and Schen Ito/log-vs-linear-distance tweaks produce comparatively small changes here. Time still matters strongly *inside the shared z-score*, and outright removing time was not the experiment.

Technical note: Removing the only target-distance input from plain HeadStart *must* produce 0.5 by construction and a constant Brier of 0.25. That knockout verifies the dependency but is **not an independent scientific discovery** about BTC. The more informative experiment is retraining logistic WITHOUT HeadStart and measuring what the other features can recover.

## 5. Better Brier is not necessarily better direction

The model-selection lesson is clearest when comparing the trained logistic with direct HeadStart:

| Period | Fraction of matched calls with different ABOVE/BELOW direction | Calls corrected by logistic | Calls made wrong by logistic |
|---|---:|---:|---:|
| First 2 minutes | 20.75% | 7.36% | 13.39% |
| 10m left | 10.34% | 3.45% | 6.90% |
| 5m left | **1.19%** | 1.19% | 0% |
| Final minute | **1.61%** | 1.15% | 0.46% |

These are equal-contract-weighted snapshot fractions. The first two periods show that the trained logistic frequently changed the direction and **more often hurt than helped**. By the last minute it nearly never changed the direction at all; the difference in Brier score largely reflects **recalibration of confidence in the same direction**, not detecting a new move.

Deleting RSI from the logistic at **5m, 10m, and the final minute** changed no ABOVE/BELOW calls on this dataset. Deleting momentum from the logistic in the entire last minute also changed no calls, while altering the reported probabilities slightly.

## 6. Does the ingredient benefit depend on conditions?

Yes, but the available sample is too small for stable regime rules.

At five minutes remaining:
- For the **32 far-from-strike contracts** (absolute HeadStart z-score >=1.5), all leading models selected the correct outcome in this subset; logistic Brier was 0.000376. That is an easier category where the price gap already points strongly toward one outcome.
- For the **17 near-strike contracts** (absolute z-score <0.5), logistic Brier was **0.263210**, worse than HeadStart's **0.248708**. Directional correctness was 58.82% versus 52.94%; neither is compelling. The hardest close-call scenarios remain hard.
- In the **60 momentum-aligned** contracts, logistic Brier was 0.093226, and without momentum it was 0.100210. In the **24 momentum-opposed** contracts, logistic Brier was 0.176029, whereas without momentum it was 0.167879. This is a plausible context-dependent hypothesis, but these post-hoc partitions cannot justify a momentum gate without a new confirmation set.
- Only **five** five-minute contracts had volatility above the October 13 training median. The high-volatility subgroup is far too small for reliable conclusions.

The result suggests the observed later "accuracy" may be driven strongly by situations where BTC is already far ahead of its target. That estimates the eventual contract winner; it is **not** evidence of detecting a price movement one or two minutes before its onset.

## 7. Adaptive mixing and calibration candidates

Predefined simple 50/50 combinations of HeadStart with logistic, the current AXIOM ensemble with logistic, and HeadStart with the ensemble were also evaluated on matched historical inputs. Some mixtures nudged Brier downward in one period, but no clear multi-regime advantage was established against the correct frozen parents.

At the first two minutes, fixed sigmoid(1.7*HeadStart_z) scored 0.221479 versus direct HeadStart 0.222004; at ten minutes it scored 0.180948 versus 0.181576. Those are small *probability mapping* differences, not new information.

A plausible future design for an **independent, time-adaptive forecast** is:

    shared_z(t) = [(BTC_spot - published_target)/BTC_spot] /
                  [local_volatility * sqrt(adjusted_seconds_to_close/60)]

    p_yes(t) = sigmoid( intercept(t) + slope(t)*shared_z(t)
                      + momentum_weight(t)*momentum
                      + RSI_weight(t)*RSI )

The continuous time-dependent parameters must be fitted/calibrated on enough **strictly past officially settled contracts**, with a stable, independent walk-forward calibration evaluation. Adding momentum or RSI should require *measurable additional out-of-sample skill*, not just apparent feature complexity. At less than 60 seconds, settlement-average conditioning must use genuine past CF BRTI ticks or be explicitly unavailable.

**This formula is a research proposal, not a proven production model.** An automatic model switch chosen after seeing October 25 results would be data snooping, not a valid winning strategy.

## 8. Formal uncertainty / multiple testing audit

We performed **83 separately reported model ingredient comparisons** across the requested time periods: 22 early, 22 at 10m, 22 at 5m, and 17 over the full last minute. Each uses the same available contract/timestamp rows and a 1,000-draw contract-level bootstrap interval. Comparisons with only partial time coverage (such as Schen at -60s but not -45s/-30s/-15s/-5s) were explicitly excluded from the whole-last-minute family.

We also ran >=5,000 sign-flip draws per comparison and a **family-wise Holm-Bonferroni adjustment across the entire 83-comparison set**. These p values are *approximate*, because neighboring contracts may not be fully independent and all the October 25 observations had already been examined in previous research.

Key corrected findings after this stringent correction:
- **Retraining without HeadStart** still materially worsened logistic in the final minute (adjusted p approximately 0.0166); the five-minute reduction was large but **did not pass** the full 83-test Holm threshold.
- Remove-target constant-0.5 controls trivially performed much worse, as their construction guarantees.
- Some identical-direction probability-cap changes achieved tiny numerical significance at five minutes, but their Brier changes were about **0.000003**, far too small to infer a practical edge.
- The five-minute Aaryann momentum benefit, the five-minute RSI knockout, the fixed-volatility counterfactual, and the model blends did **not** provide family-wise-confirmed improvements.
- The eight or more candidate models and their ablations are **not independent hypotheses**; the multiple-model search can still bias reported winners.

A nominal 95% interval for an individual test is NOT permission to deploy that feature.

## 9. Extra internal validation and historical timing audit

We added two genuine chronological within-October-13 probes (first 28 contracts then 8, first 36 contracts then 8), taking only training outcomes with **both** a recorded settlement timestamp and settlement-receipt timestamp strictly earlier than the validation window.

- Fold 1: 28 candidate prior contracts, only **25 verified as-received outcomes** available before the validation timestamp, 8 validation contracts and 96 recorded checkpoint observations.
- Fold 2: 36 candidate prior contracts, only **26 verified as-received outcomes** available before the validation timestamp, 8 validation contracts and 96 observations.
- This new guard catches genuine delayed-outcome hindsight that merely ordering contract opening times would miss.
- On these 16 within-day validation contracts, the close-tie Schen/HeadStart early structure reappeared. A five-minute logistic without momentum beat the full model on Brier (0.109361 versus 0.113134). On October 25, by contrast, the full model slightly beat the no-momentum variant at 5m (0.116884 versus 0.119544). That **directional instability across tiny validation samples** is a strong reason not to hard-code a momentum rule.

These within-day tests are tiny and share one market date with the training sample; do not treat them as separate broad market validation.

## 10. Source, code and integration audit log

**Audit defects identified and addressed within the research branch:**
1. **Probability-cap mismatch:** Schen epsilon-capping was incorrectly checked against AXIOM's 0.005 CDF cap. Fixed the parity audit to reproduce original source policy and added exact matched-cap alternatives. Original research model source was not altered to disguise the difference.
2. **Hindsight labels:** additional same-day rolling fit previously ordered contracts without checking label receipt. Fixed to require recorded settlement and receipt timestamps before each validation decision; added tests for both blocked and correctly available labels.
3. **Partial last-minute comparison:** initial ablation family could include a Schen result that existed only at T-60s under the heading "last minute". Fixed by requiring the comparison to cover every requested instant in the named period.
4. **Direction-diagnostic test failure:** a research-only field-name typo stopped CI. Fixed the diagnostic and reran the full original regression and new methodology tests without weakening any existing assertion.
5. **Multiple testing:** added family-wise Holm correction and explicitly retained the distinction between numerical significance, useful magnitude, and genuinely replicable improvement.
6. **Source-equation parity:** all three frozen AXIOM engine equations were independently mirrored and checked; observed maximum stored-precision discrepancy **zero** over all replayed checkpoints.

**Checks that do pass** (verified on the isolated research commit before the report-only commit):
- Full original AXIOM historical regression, code/data preservation and end-to-end integration workflow.
- Real Kalshi/Coinbase read-only application smoke tests.
- Optional XGBoost challenger tests on a separate ephemeral research runner (never installed into the production lockfile).
- Real October historical ingredient ablation workflow, source-equation tests, finite probability checks, timing guards, model input separation, same-contract scoring and as-of settlement-cutoff regression tests.

**Unresolved data limitations blocking full scientific certification:**
- The downloaded KalshiEye historical contract target comes from a day-end market catalog and lacks a verified publication-as-of timestamp. This is a **material research validity limitation**, not a software test failure. It prevents a fully proved causal replay, even though BTC spot/book features are timestamped.
- The sample's Coinbase MID-QUOTE-derived candle history is **not actual Coinbase trade OHLCV** and is **not CF Benchmarks BRTI**; the true final-minute partial-average inputs are unavailable.
- Only two nonconsecutive historical dates, with only 44 and 87 eligible contracts. The October 25 test set had already been inspected in prior rounds, so new variants fitted/selected after examining its outcomes are exploratory only, not untouched external confirmation.
- No independent economic execution or signal lead-time benefit established: contract eventual winner does not prove advance detection of an imminent BTC move; simulated ask prices do not prove fills.

**Decision:** PASS for isolated research implementation, its dedicated tests and AXIOM's verified operational non-regression in the implemented test scope; **BLOCKED** for claims of fully proven original bot parity, a new statistically defensible market edge, deployment, promotion, auto trading, or a dynamically switched production forecast. All live AXIOM modules and existing verified branches remain unchanged.

## 11. What should AXIOM take from this research?

The strongest evidence-backed ingredient is **normalized target distance**, with genuine realized volatility and remaining time integral to that variable. A **trained probability mapping** may improve calibration late, but cannot yet be credited with new independent price-movement foresight. Add momentum and RSI only when independently validated on sufficiently large new as-of market histories. Avoid treating Schen and HeadStart as two statistically independent opinions in a consensus vote.

The next genuinely decisive scientific experiment is a **registered, forward-only, point-in-time shadow comparison** over substantially more days with published-strike timestamps, true BRTI partial averages, independent BTC trade/quote feeds, optional original source model parity, and no trading execution. The current isolated branch can inform such a protocol, but this batch does **not** authorize a live deployment.

## 12. Reproduction

Source code is under research/ingredient_ablation.py and its permanent methodology tests under tests/test_ingredient_ablation.py. The isolated workflow is .github/workflows/axiom-ingredient-ablation.yml.

Research CI results before this report commit: https://github.com/szmohmand/Axiom/actions/runs/43778648416  
AXIOM full regression results: https://github.com/szmohmand/Axiom/actions/runs/43778648424  
Live read-only smoke: https://github.com/szmohmand/Axiom/actions/runs/43778648443  
Optional XGBoost test: https://github.com/szmohmand/Axiom/actions/runs/43778648449

The report's final commit must pass applicable AXIOM checks again before its safety decision is considered final.
