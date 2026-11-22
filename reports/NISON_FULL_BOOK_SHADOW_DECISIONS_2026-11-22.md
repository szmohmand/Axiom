# Nison whole-book AXIOM shadow — scope, decisions and exceptions

**User directive:** Implement Steve Nison's *Japanese Candlestick Charting
Techniques*, second edition, comprehensively as a separate shadow model.
No unannounced simplifications or production-voting changes.

**Source reviewed:** user-provided 298-page PDF, *Japanese Candlestick
Charting Techniques, 2nd Edition*, copyright 2001 Steve Nison.
Source concepts summarized in original code; book passages are not copied.

## Exact meaning of 'complete'

There are two different things:
1. **Whole-book methodological coverage:** account explicitly for each
   technical chapter, every named family of patterns and complementary
   Western-convergence method, and state which can be deterministically
   measured in available data. This is implemented and documented.
2. **A mathematically exact implementation of every subjective human chart
   interpretation:** the book does not define universal numerical thresholds
   for all setups, and no code can literally reconstruct a human analyst's
   judgments. This is NOT claimed.

The live model is not silently replaced. The old 1.5–3.5% challenger
continues its pre-existing, separate first-100 live trial. The new system is
a fully separate experimental candidate, unrelated to that candidate's
probability formula.

## Chapter-by-chapter audit (book pages refer to printed pagination)

| Chapter / printed page | Coverage | Implementation status and limitations |
|---|---|---|
| 1 Introduction / 1 | Technical-analysis limitations, confirmation, capital preservation | **Policy only:** no evidence of profit, no executable orders |
| 2 Historical background / 15 | History of Japanese trading/candle methods | **Context, not a prediction rule** |
| 3 Candle construction / 23 | Genuine open/high/low/close, real body, shadows, doji, spinning top | **Automated** on strict consecutive fully closed 1m OHLCV |
| 4 Reversal patterns / 31 | Hammer, hanging man, bullish/bearish engulfing, dark cloud, piercing | **Automated**; dark cloud and piercing retain strict opening gaps; confirmations are not guaranteed |
| 5 Stars / 61 | Morning/evening stars, doji-star variation, shooting star, inverted hammer, abandoned-baby distinction | **Automated stars** with author-described intraday gap flexibility; **abandoned baby only under genuine two-sided price windows**, not redefined as a normal doji |
| 6 More reversals / 81 | Harami/cross, tweezers, belt-hold, crows, soldiers, counterattack, gap-two-crows, three mountains/rivers/Buddha, dumpling/frypan, towers | **Automated core formations**; larger tops/bottoms use explicitly labeled **geometric proxies** (human discretion is not claimed reproduced) |
| 7 Continuation / 125 | Windows, tasuki gaps, side-by-side white, gapping plays, rising/falling three methods, separating lines | **Automated** with strict real windows for gap-dependent formations |
| 8 Doji / 155 | Doji in up/down/range trend, long-legged, gravestone, dragonfly, tri-star | **Automated** descriptive formations; doji in a downtrend requires more evidence |
| 9 Putting it together / 173 | Context before formation, trend/confirmation/conflict | **Automated** caution labels and prior-trend inputs |
| 10 Candle clusters / 187 | Repeated support/resistance reactions | **Automated** as prior-20 bar touch clusters |
| 11 Trend lines / 193 | Trendline context, Wyckoff springs/upthrusts, polarity | **Automated** geometric lines, level-reclaim/rejection, retests |
| 12 Retracement levels / 213 | 38.2% / 50% / 61.8% | **Automated** contextual levels, no assumed directional trade |
| 13 Moving averages / 217 | SMA, WMA, EMA | **Automated** 9/21/50 where enough past closes exist |
| 14 Oscillators / 225 | RSI, moving-average oscillator, stochastic, MACD, divergence | **Automated** as specified deterministic approximations; not fitted to BTC or claimed to reproduce a platform indicator's exact settings |
| 15 Volume / 241 | Relative volume, volume confirmation | **Automated** where real 1m volume present; cannot infer true L2 absorption |
| 16 Measured moves / 249 | Breakouts from boxes, swing/flag/pennant projections | **Automated** bounded price geometry; projections are *conditional descriptive targets*, not predictions of fills |
| 17 Power of convergence / 263 | Combine Japanese setups with Western evidence | **Automated**; conflicting evidence is preserved, not silently suppressed |

## Implementation choices — AXIOM experiments, not Nison's rules

These have been implemented **only in the isolated development branch**, not
approved as winning formulas or deployed:

- **1-minute candle source:** Existing AXIOM's real Coinbase one-minute bars.
  It supplies ~61 completed bars. This is enough for short-term formations
  but insufficient for genuine multi-hour/multi-day context. **Do not claim
  the book's daily/multi-timeframe analyses have been validated from these.**
- **Formation thresholds:** Real-body fractions, relative-volume gate,
  local level tolerances, impulse and cluster lengths are code-level
  hypotheses. They are inspectable and require empirical validation.
- **Long formation detection:** Chapter 6 multiple-top/bottom structures
  are deterministic **proxies**. Human discretion in deciding where a
  'mountain' starts, how rounded a base is, and when a trend is mature
  cannot be reproduced exactly. Each proxy is labeled as such.
- **Gap integrity:** 'Window' requires a nonoverlap of entire consecutive
  candle high-low ranges. We never fabricate gaps in continuous BTC.
  Nison describes flexibility for *some* star-pattern body gaps on intraday
  charts, which the code treats separately.
- **Independent prediction:** `forecast_nison_independent()` does NOT take
  an AXIOM ensemble probability. It combines independently calculated
  BTC-to-strike distance with an **invented, unfitted and deliberately
  bounded** score from Nison-style evidence. Its output is an
  **uncalibrated hypothesis, NOT an objective win probability**.
- **Confidence weights:** Stored in public `_WEIGHTS`; not sourced from
  Nison and not measured hit rates. The strategy for resolving conflicting
  patterns is conservative and is an experimental choice, not book doctrine.
- **Confirmed candles only:** An observation at time T can use only candles
  with close time <= T, and never the post-contract final price or label.
  Pivot forms require two *past* completed bars to confirm. Lack of data
  is reported as unavailable, not replaced by guessed signals.
- **Kalshi reference:** BTC/USD spot is not CF Benchmarks BRTI.
  Official settlement results cannot be inferred from Coinbase last trade.
- **Capital/risk:** No real orders, no paper trades, no modified stop loss,
  no altered bankroll rules. These require a user review separately.

## Exactly what changed and what did not

Branch: `feature/axiom-nison-full-methodology-shadow-2026-11-22`,
based on the already-isolated candlestick branch.

New original code: `app/nison_methodology.py` and
`app/nison_structures.py`, independent analysis and fixed experimental
probability. New read-only study harness:
`research/nison_full_shadow_study.py`.

No change was made to `app/main.py`, the active ensemble, production SQLite,
Oracle environment, secrets, existing candlestick collector, real money
permissions or running VM. This new method has NOT been deployed or tested
on live Oracle from this conversation.

## What should be agreed before promoting this to the live test

1. Review the disclosed experimental probability formula / weights. A
   trained or calibrated probability is not supplied by Nison's book.
2. Decide whether to collect longer *point-in-time* history for 5m/15m/daily
   confirmation, and whether its source should be Coinbase or another
   provenance-verified venue. Don't fake more than 61 live bars.
3. Run a no-leakage, chronological historical comparison and a paired live
   read-only test before considering any effect on the original ensemble.
4. If the candidate does not outperform the original baseline, retain
   research diagnostics without enabling its votes. A larger model can be
   worse; completeness alone does not demonstrate predictive power.

**Policy:** Tell the user about material methodology choices, exclusions,
weights, source substitutions, any test failures and unsupported claims.
Do not quietly change strategy definitions or expand bot access.
