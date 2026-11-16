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

## August completion and extension checkpoint

August BRTI job succeeded and its artifact contains 3,041,325 5Hz observations and 608,270 first-tick seconds (including August 5 warmup hour). The manifest flags eight incomplete hours, with 675 missing 200ms slots and 130 missing seconds relative to theoretical coverage. These gaps must remain visible. Independent reconciliation is in progress; do not describe the August series as gap-free.

August Kalshi minute collection completed locally: 10,608 candles including 9,945 within-contract candles; all 663 contracts have 15 in-window bars, no crossed quotes reported. The raw historical listing preserved 26,021 unique terms across December 10–September 15. No August transaction ticks or depth have yet been collected.

A separate sequential two-batch workflow extends BRTI from August 18 through October 16, excluding previously collected complete-day ranges. Combined with October 17–November 15 this targets 90 consecutive days; this is a target, not a completeness claim. Boundary warmup hours intentionally overlap for reconstruction. Raw JSON response preservation and retrieval timestamps remain enabled. Existing Kalshi run is not restarted.

## Independent August settlement audit

Source-file hashes and original JSON uncompressed-byte fingerprints were checked. All 608,270 exported first-tick samples matched independent selection from the exported 5Hz rows. The 663 unique contract terms and 10,608 unique candle identities were checked, with 9,945 within-window candles and no crossed closing bid/ask.

659 opening and 661 closing references have both a full 60-second sample population and published numeric official references. Every such reconstructed reference is within $0.005 of the published value. 657 contracts support both boundaries; all 657 candidate winners match official YES/NO results, zero disagreements. 655 contracts have all 900 in-window seconds; 651 have full windows plus both verified boundary comparisons. These are research-ready index/contract/minute-candle windows, not verified tradable fills. No historical transaction/depth evidence is included in this August package. August contract presence is 663/672=98.66%; full window plus boundary coverage is 651/672=96.875%. Native raw source JSON and source retrieval metadata are preserved separately. No missing records were filled.

30-day independently packaged BRTI: https://github.com/szmohmand/Axiom/actions/runs/43805072835/artifacts/14198031781 ; 149787705 bytes, SHA256 b4112c64b53b6b7b718ca86f7f4a00a5033f4a854b0d2a1a46b71d85291c5af7 . Includes original gzip export, independent audit, verification script, handoff and MASTER_INDEX.json. This package reuses the original collection.

## Independent 30-day contract/index reconciliation

While the original Kalshi candle/trade job remained active, a bounded three-page official contract-metadata read obtained 2,848 unique finalized contracts for October 17–November 15 (1,368 YES, 1,480 NO). No candle or transaction collection was duplicated. All 2,848 opening targets and 2,848 closing references were compared against full 60-second first-tick BRTI averages: every comparison is within half a cent; all 2,848 candidate winners match the official result. No disagreement found. Contract presence: 2,848/2,880 = 98.8889% of theoretical windows. Missing windows are October 22 and 29 07:00–08:45 UTC, and November 5 and 12 08:00–09:45 UTC, eight opening windows on each date. No inference about the cause is made without source evidence.

Fee evidence read: current official /series/KXBTC15M reports fee_type quadratic and fee_multiplier 1, with https://assets.kalshi.com/contract_terms/CRYPTO.pdf . Current https://kalshi.com/fee-schedule was retrievable. Neither proves which schedule applied on each historical date. Historical maker/taker schedules and fee rounding remain UNVERIFIED; no past profitability calculation uses the current fee page.
