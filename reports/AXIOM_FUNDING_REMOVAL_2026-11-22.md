# AXIOM funding-rate removal — 2026-11-22

User decision: Remove perpetual funding rates from AXIOM because they should not influence Bitcoin predictions.

Changes now included:
- Removed Binance USD-M `premiumIndex` REST funding sampler, thread, funding-rate parsing and public funding fields.
- Removed `btc_perpetual_funding_pressure` from all prediction components and the ensemble's provenance.
- Removed `btc_perpetual_basis_pressure` as well: it was read from the *same futures funding endpoint*. This change does **not** remove Coinbase BTC-USD prices or independently observed Binance BTCUSDT spot prices.
- Removed funding metadata from the Binance/Kalshi lag observer, intracontract API and mobile dashboard.
- Preserved the new gradient-boosted BTC model, Nison candlesticks, 30m/1h/2h price structure, genuine Binance aggressive-trade CVD and large prints, Kalshi liquidity walls, order-book imbalance, and Bitcoin-to-Kalshi quote-delay analysis.
- Added regression assertions that injected funding-rate fields cannot affect the market-structure forecast.
- Updated the Oracle service documentation to start **one** Binance spot-stream worker, not an additional funding worker.

This is a source-code removal in the `szmohmand/Axiom` repository. There is no associated Oracle VM deployment in this change; live processes need redeployment for the change to take effect on the server.

Historical integration research reports describing earlier model versions are preserved as historical records, not re-written to imply the funding signal was never tried.
