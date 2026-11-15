# AXIOM isolated BTC15m challenger laboratory

This is an **opt-in, read-only, separate research path**. It is NOT loaded by
AXIOM's FastAPI application, prediction worker, ensemble, scalping,
opportunity screen, paper ledger or dashboard. No orders, deployment,
background scheduling or secrets are created here. Preserve main.

## Preserved system

- Last documented verified main: b12be3758049b6766dda8fefad06611bf41ada2e
- Existing recovery ref: verified/2026-11-15-b12be37
- Underlying runtime verified: 902f7d7dfd7a4a952b4afc2019f01a599af43355
- This experiment exists only on a research branch until every applicable
  AXIOM historical/current/foreseeable review gate is satisfied.

## How the experiment works

Each candidate uses the **same read-only checkpoint observation** at 14, 12,
10, 5 or 1 minutes to expiration (within ±30 seconds), containing:
actual completed contiguous 1m Coinbase BTC candles, observed Coinbase spot
and timestamps, Kalshi's published target and expiration. Kalshi YES midpoint
is captured with its own observation timestamp but is allowed **only** as an
external benchmark. No outcome exists anywhere in a prediction observation.

Separate settled yes/no outcomes must come from Kalshi's official settled
market endpoint. Coinbase is a **BRTI proxy** and is never converted into an
official settlement label. A source of synthetic_fixture is accepted only
by the explicit --allow-synthetic CLI flag, and such reports are always
marked non-real. Every contract and checkpoint is deduplicated; all training
uses only labels available *before* each chronological test batch, with entire
contracts held out rather than individual rows.

The scorecard reports: Brier, log loss, five-bin calibration/ECE, directional
accuracy, same-row paired Brier against AXIOM's volatility model, model
coverage and first confident call lead time. Accuracy when waiting later is
not an imminent-move early-warning measurement. A confidence threshold is
not evidence of profitable execution.

## Candidate identity and critical limits

| Challenger | Research code status | What is not established |
|---|---|---|
| AXIOM volatility / Aaryann fair / HeadStart / existing ensemble | Reuses current formulas, evaluated offline only | Baselines are not calibrated |
| settlement_zero_drift | Implements settlement-average M0 lognormal formula (variance horizon tau minus 40s); substitutes 1m-return volatility divided by sqrt(60) for original per-second EWMA | NOT the original full Schen live engine or its calibration; below 60s deliberately refuses missing partial-settlement ticks |
| kalshibot_independent_logistic | Research reimplementation of independent non-market-anchored regularized logistic forecasting from visible candle-based features; trained on prior contracts only | NOT the full Swift trainer, tick inputs, original learned coefficients, feature promotion pipeline or its reported accuracy |
| siddha_spot_xgboost | Optional research XGBoost classifier retrained from scratch on causal BTC-only features, no Kalshi midpoint/spread or other contract price fields | NOT the original full SiddhaBasu feature parity or model artifact; optional XGBoost and adequate historical input required |
| kalshi_market_mid | Contemporaneous YES midpoint; benchmark only | NEVER an input to an independent model or ensemble |

Source-reading reference implementations, not vendored or executed:
- https://github.com/schen9999/btc-15m-engine/blob/main/backend/app/core/math_engine.py
- https://github.com/jaldrich2023/KalshiBot/blob/main/KalshiBot/Engine/Predictor.swift
- https://github.com/jaldrich2023/KalshiBot/blob/main/KalshiBot/Engine/ModelTrainer.swift
- https://github.com/SiddhaBasu/kalshi-bot/blob/main/backend/core/btc_model_training.py

The preliminary lab does NOT imply full original implementations were
imported. Missing per-second features, original trained calibration, XGB
dependencies, data-quality parity, and sufficient input history are
explicit research dependencies. Neither source-reported results nor synthetic
results may be attributed to AXIOM.

## One-shot public data capture, with no live integration

This is not a scheduled recorder. It runs only where the user intentionally
invokes it in a Python environment with the existing pinned dependencies:

    python -m research.record_live --mode observe
    python -m research.record_live --mode grade

Capture should run at the stated checkpoints; grade separately resolves
expired recorded tickers using public Kalshi settled outcomes. Both commands
store only in git-ignored data/challenger_lab/*.jsonl, not AXIOM SQLite.
No observing or grading has been initiated by adding these files. The
recorder measures client receipt times, not the true age of exchange quotes;
unknown exchange-side delay remains a validity limitation.

After sufficient real, causally complete observations and official results:

    python -m research.challenger_lab \
        --observations data/challenger_lab/observations.jsonl \
        --settlements data/challenger_lab/settlements.jsonl \
        --output data/challenger_lab/scorecard.json

The optional XGBoost dependency is deliberately NOT installed in AXIOM's
locked production environment; in its absence, XGBoost is reported
unavailable, never silently replaced. --skip-xgboost runs other models.

Existing AXIOM engine_snapshots retain prediction summaries and official
outcomes, but not all historical BTC inputs and timestamps needed for parity
replay. You cannot legitimately reconstruct missing genuine point-in-time
inputs from post-hoc prices and call that a real walk-forward test.

## Rules for any promotion

1. Show enough real out-of-sample **same-observation** comparisons, Brier and
   calibration with uncertainty intervals and multiple regimes.
2. Show benefit **at the early checkpoint**, not simply accuracy from a late
   high-confidence or near-settled call.
3. Verify actual BRTI-vs-Coinbase proxy differences and averaging near strike.
4. Re-run all AXIOM historical regressions, full existing tests, synthetic
   end-to-end lifecycle, live read-only smoke, UI, ledger, outage, recovery,
   security and timing checks. Real order path remains disabled.
5. Never blend market-price-anchored models into an independent probability.
   If challenger value is unproven, keep AXIOM unchanged.

See reports/CHALLENGER_GATE_2026-11-15.md for acceptance status.
