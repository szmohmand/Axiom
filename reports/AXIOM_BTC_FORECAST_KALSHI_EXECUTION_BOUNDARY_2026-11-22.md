# AXIOM architecture: BTC predicts; Kalshi quotes price the contract

User decision: Kalshi's participant-created YES/NO quotes must never affect BTC direction, probability or the ensemble. Quotes can and should help judge whether a contract is worth buying or exiting.

## Predictive lane (allowed)
- Real BTC OHLCV, multi-timeframe trends and volatility (Coinbase)
- Real Binance spot aggressive-trade signed CVD, momentum, large-trade proxies
- Japanese candle price-action interpretation, gradient-boosted BTC forecasting
- **Contract definition only**: published Bitcoin strike, time left/expiry, market identifier
- Official BRTI/reference data when independently available and verified

## Execution and valuation lane (allowed only AFTER prediction)
- Kalshi YES and NO bid/ask contract quotes, market midpoint, spread, quantities, liquidity and order-book walls
- Price/fee comparison against AXIOM's independently calculated probability
- Contract resale/exit pricing and BTC-to-Kalshi quote repricing delays
- Book-based sizing, slippage / hypothetical fill assessment, opportunity tracking
- Market-price benchmarking in settlement grading is retrospective **comparison**, not a predictive input

## Removed from outcome prediction
- Kalshi midpoint as a prediction-engine slot (`kalshi_market`)
- Kalshi book imbalance / walls / depth replenishment as probability features
- Kalshi contract quote stickiness and stale-price differences as probability features
- Model-minus-quote-mid calculations from the **forecast** response. Quote comparison belongs to the execution/valuation lane.

## Enforced boundary
- Both `app/main.py` and `app/ensemble.py` project the market object to only `ticker`, `target`, `seconds_left`, `close_ts` before any model calculation.
- `app/market_structure.py` now strictly recognizes BTC-native feature names. Previously injected Kalshi quote or depth values are discarded.
- `BTCFlowTracker` uses actual Binance BTC signed-trade telemetry and never reads its legacy Kalshi book/market arguments.
- Added tests exercising extreme quote reversals, order-book wall changes, maliciously injected Kalshi features, and proving prices **still change execution choices** after a constant prediction.

No other repositories or branches are changed. Source merge does not deploy the Oracle instance. The existing integrated branch still has old tests that assume smaller, non-voting model counts. Tests are not rewritten or suppressed to disguise those unrelated architecture changes.
