# Historical data handoff

Collection only; no models or trading. Main and recovery remain b12be3758049b6766dda8fefad06611bf41ada2e. Research starts from 381bb6571a127440b1a5476dcb264989d45abbb3 on research/historical-data-completion-2026-11-16. No production checkpoint advanced.

## Verified source export

https://github.com/szmohmand/Axiom/actions/runs/43802326178/artifacts/14197885366

Original ZIP: 149768280 bytes. SHA256: 227295a0a31f1a9fd33f6f4c227f9174c0d280534f82b91d995f7734af52c305

Official CF Benchmarks BRTI via authenticated Kalshi /trade-api/v2/cfbenchmarks/history/values. October 17–November 15 UTC: 12,960,000 observations, plus 18,000 warmup observations on October 16 23:00–24:00 UTC. Total 12,978,000 5Hz observations and 2,595,600 derived first-tick seconds. All 721 requested hours contain 18,000 rows. Full independent audit: all 32 data-file hashes and sizes match; all adjacent native timestamps advance 200ms; UTC matches native time; finite positive values; all derived seconds match independent selection. No gaps or duplicates found.

VERIFIED SOURCE DATA means the existing normalized export, not original JSON bytes. That collector converted prices to float and eight decimal places; original precision beyond this is unverified. Original response envelopes, per-request retrieval times and revisions were not retained. Event time is not delivery time.

VERIFIED DERIVED DATA: first BRTI observation each second. This is a research policy, not a documented universal settlement guarantee. Reproduce after extracting: `python verify_brti_archive.py 01_OFFICIAL_BRTI`. Standard library only; audit writes INDEPENDENT_AUDIT.json.

## Pending collections

Kalshi: https://github.com/szmohmand/Axiom/actions/runs/43802346611 . Still active at initial audit. Its code collects 30 days of terms/candles but individual trades only November 13–14. Do not claim 30-day transaction coverage.

August BRTI: https://github.com/szmohmand/Axiom/actions/runs/43804623416 . Separate research wrapper preserves original response bytes and retrieval times without headers; counts remain pending artifact verification.

August Kalshi source exploration: /markets returned no contracts. Official https://docs.kalshi.com/openapi.yaml documents /historical/markets and /historical/markets/{ticker}/candlesticks. /historical/cutoff reported settlement cutoff 2026-09-16. Historical listing has no documented close-time filter, so filter locally. Local preserved responses contain 26,021 unique archived terms, opening dates 2025-12-10 through 2026-09-15. August 6–12 contains 663 15-minute contracts versus 672 theoretical (87 on August 6; 96 on each remaining day); nine windows are missing, not synthesized. Minute-candle collection is in progress at this checkpoint.

## Missing data and assumptions

PARTIALLY VERIFIED: native source precision in older BRTI export, historical retrieval/revision metadata.

UNAVAILABLE/UNVERIFIED: original strike publication time, receipt latency, historical fee effectiveness, full historical depth updates, account fills and actual fill probability. No account data accessed. Minute candles are not exact executable quotes; NO complements are derived. Settlement reconciliation and matched usable-window count await verified Kalshi output. No 90/180-day aligned completeness claim.

The three existing ZIPs in /BTC Historical Research/ are user-confirmed; no Library listing or upload tool is available here. No new Library upload claimed. Status PENDING. Repository visibility is PUBLIC: Actions downloads requiring GitHub authentication are not owner-private storage. Provider licenses still apply; no licensed raw data committed to Git.

## Tests

77 local tests passed across tests/ and research/ in isolated workspace dependencies; 19 permanent regression records and frozen-source checks passed. Python 3.13 CI: https://github.com/szmohmand/Axiom/actions/runs/43804623288 (success). Live read-only smoke: https://github.com/szmohmand/Axiom/actions/runs/43804623405 (success). No orders, production changes, deployment or other repositories.
