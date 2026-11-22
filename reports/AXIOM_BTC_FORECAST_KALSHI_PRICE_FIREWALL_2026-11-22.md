# AXIOM invariant: Kalshi quotes never affect the BTC prediction

**User-specified architecture, implemented on 2026-11-22.**

## 1. Predict Bitcoin's outcome (BTC-only)

The forecasting calculation may read:
- Real Coinbase BTC spot price and closed OHLCV candles.
- Real Binance BTC **spot trades** and signed taker-volume CVD/large-trade prints.
- BTC 30-minute, one-hour and two-hour price structure.
- Nison candlestick formation evidence.
- Fitted BTC gradient-boosted residual model.
- The **published contract BTC strike** and **expiration time**: these
  define the *question*, not anyone's opinion about its likelihood.
- Official CF Benchmarks BRTI when authentic and point-in-time available.

The forecasting calculation must **NOT** read or use:
- Kalshi YES/NO bid, ask, last price or midpoint.
- Kalshi contract trading volume, buy/sell ratios or order-book imbalance.
- Kalshi liquidity walls, cancellations or replenishment.
- Kalshi quote stickiness, price delay, inferred sentiment or contract-pricing history.
- Funding rates (removed by user's previous request).
- Any Kalshi participant quote as an extra model vote or "probability" benchmark.

`app/main.py` projects the contract into a **quote-free** dictionary before
calling `derive_signals` and `engine_pack`. `app/ensemble.py` independently
re-projects this input and **does not construct a 'kalshi_market' quote engine**.
`app/market_structure.py` uses an explicit allowlist of BTC-only features,
ignores `book` and `market` in its legacy `DepthFlowTracker.observe`
signature, and rejects any injected Kalshi-derived feature keys.

Therefore, with unchanged BTC inputs and unchanged strike/expiry,
**moving Kalshi YES from 20 cents to 90 cents cannot change AXIOM's
BTC outcome forecast or its component predictions.**

## 2. Decide whether a contract is worth buying (Kalshi pricing only)

After the independent forecast exists, Kalshi bid/ask/depth can be used
in `execution_screen`, `analyze_opportunities`,
`execution_guidance`, `execution_decision`,
`resale_screen`, and `binance_kalshi_delay` to evaluate:
- Current YES or NO entry price and available sizes.
- Comparison with AXIOM's *independent* probability.
- Fees, bid/ask spread, order-book liquidity, price impact and slippage.
- Existing-paper-position resale/exit potential.
- BTC lead versus Kalshi quote repricing **for entry timing only**.

Example: a BTC-only forecast estimates ABOVE probability of 80%.
At a YES ask of 38 cents, a hypothetical paper entry might be attractive
after costs; at 80 cents, it might not. **Both quotes leave 80% unchanged**.

## 3. Regression requirement

`tests/test_btc_forecast_kalshi_quote_firewall.py` asserts:
- Drastic changes to all Kalshi quote prices do not change any forecast engine.
- Opposite Kalshi depth/wall snapshots do not change BTC-only trade-flow features.
- Injection of legacy Kalshi features into the forecasting context is ignored.
- Kalshi asks do change execution price/value, without mutating the forecast.

Prior tests asserting a Kalshi quote benchmark appears inside the prediction
ensemble are obsolete and should be revised to enforce this stricter boundary.
Historical research results can still retain their original quote fields,
but they cannot vote on BTC outcome direction.

This change is in the Axiom GitHub repository only. It has not deployed
automatically to the Oracle VM or enabled real-money trading.
