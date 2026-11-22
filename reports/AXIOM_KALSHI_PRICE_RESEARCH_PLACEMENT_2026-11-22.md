# Kalshi price research: correct feature placement in AXIOM

2026-11-22. Objective: interpret existing research, apply what is useful
in the appropriate lane, and **never allow Kalshi contract quote prices or
order-book pressure to change AXIOM's independent BTC prediction**.

## Papers actually checked

1. Constantin Bürgi, Wanying Deng, Karl Whelan, *Makers and Takers: The
Economics of the Kalshi Prediction Market*. The authors examined over
300,000 contracts across categories. Prices carried outcome information,
especially close to expiry, but cheap held-to-settlement contracts often
lost money; maker/taker results also differed. Author summary:
https://cepr.org/voxeu/columns/economics-kalshi-prediction-market

2. Tanay Subramanian, *Prediction market efficiency: evidence from Kalshi
on pricing accuracy, forecasting, and risk*, 2026. 103,003 resolved
markets across 16 categories as of 2025, published October 14, 2026.
The abstract reports that models taking price *as a feature* beat quote-only
prediction for the broader event dataset. **This does not establish
out-of-sample BTC 15-minute Kalshi profit or intracontract resale edge.**
https://www.inderscience.com/info/inarticle.php?artid=157002

3. Kalshi Research, *Calibration in Prediction Markets* (2026).
Aggregate contract-price calibration often improves as events resolve and
with market participation, with significant differences between categories.
This is **cross-category evidence** and is not a rule that a BTC 15-minute
quote determines independent Bitcoin direction.
https://kalshi.com/research/publications/calibration

## Code placement (required)

**Forecast lane:** Actual BTC spot/BRTI reference, completed Coinbase
OHLCV/price structures, Binance signed taker CVD and large aggressive
prints, Nison interpretation, gradient-boosted BTC and contract's
published strike/expiry only. Kalshi contract quotes, spreads and book
walls MUST NOT vote, adjust confidence, select BTC direction, or generate
feature inputs to a prediction engine.

**Valuation/execution lane:** Real Kalshi YES/NO bids and asks, size-aware
sweep of executable ask/bid depth, taker fees, spread, price-vs-model
discrepancy, liquidity, hypothetical fill or resale. Retain original
low-cost opportunities; cheap contracts are NOT automatically excluded.

**Added to app/depth_intelligence.py:**
- Informational `cheap_contract_settlement_bias_warning` for
  <10-cent size-weighted entry prices. The price band is drawn from
  the published research. Crucially, this is NOT a hard entry rule, an
  adjustment of BTC probability, or a claim of a proven 15-minute bias.
- `passive_maker_buy_reference` (current resting bid), versus
  `taker_size_adjusted_ask` (quoted, size-sensitive buy).
- `potential_price_saving_before_fees` as a simple quote difference.
  This is NOT free expected profit. A resting maker order may never fill
  and the maker fee may differ.
- Explicit flags that the settlement study does not prove
  pre-expiration resale outcomes, and that neither a specific Kalshi
  quote nor an outside-market category proves BTC-specific calibration.

**Already kept after BTC prediction:** Kalshi quote lag/repricing tracker,
depth/fees, intracontract quote movement and hypothetical exit-bid
resale screening.

## Deliberately NOT added
- Automatic BTC direction or probability changes from YES/NO quotes.
- Turning the 2026 paper's ~30% broad-category Brier improvement into a
  claimed 30% BTC15M improvement.
- Assuming cheap contracts are all losing trades or high-price favorites
  are always better; this would miss profitable pre-expiration repricing.
- Hard-coded universal probabilities from population-level calibration
  charts, or untrained price-to-win-correction model.
- Automatic order placement or invented maker fills/fees.
- Using Kalshi participant book imbalance as proof of BTC exchange
  liquidity absorption.

This is a targeted valuation enhancement, not an expansion of the
independent forecast.
