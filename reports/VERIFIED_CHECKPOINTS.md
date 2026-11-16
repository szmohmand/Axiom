# AXIOM verified checkpoints and recovery references

Preserve every last-known-good commit **before** a new change. Keep old SHA and recovery reference; never delete or repoint a `verified/` branch. This certifies the tested engineering checkpoint only, not trading profitability or production uptime.

| Date | Exact verified SHA | Recovery branch | Full-suite CI | Real read-only integration |
|---|---|---|---|---|
| 2026-11-15 | `981eb1e727159cb350edb59dd2872ed74443c942` | `verified/2026-11-15-981eb1e` | [Pass #43736997711](https://github.com/szmohmand/Axiom/actions/runs/43736997711), 49 tests | [Pass #43736997802](https://github.com/szmohmand/Axiom/actions/runs/43736997802), Kalshi/Coinbase and application API |
| 2026-11-15 | `50d84ac9bc8cef7b8b82e0f555ed39ba37df1cab` | `verified/2026-11-15-50d84ac` | [Pass #43739391137](https://github.com/szmohmand/Axiom/actions/runs/43739391137), regression policy CI | [Pass #43739391130](https://github.com/szmohmand/Axiom/actions/runs/43739391130), public read-only sources |
| 2026-11-15 | `88957587e1b4e5a94acc78956821ef3e8ebfdf44` | `verified/2026-11-15-8895758` | [Pass #43741212964](https://github.com/szmohmand/Axiom/actions/runs/43741212964), full suite | [Pass #43741212473](https://github.com/szmohmand/Axiom/actions/runs/43741212473), public read-only sources |
| 2026-11-15 | `2694dd0faf01479dea396e81535605dbf6e2111f` | `verified/2026-11-15-2694dd0` | [Pass #43753123878](https://github.com/szmohmand/Axiom/actions/runs/43753123878), 62 baseline tests | [Pass #43753123862](https://github.com/szmohmand/Axiom/actions/runs/43753123862), snapshot-only; later source candle gaps exposed limitation |
| 2026-11-15 | `902f7d7dfd7a4a952b4afc2019f01a599af43355` | `verified/2026-11-15-902f7d7` | [Pass #43759621808](https://github.com/szmohmand/Axiom/actions/runs/43759621808), 72 tests, 19 permanent regressions, archive checks | [Pass #43759621781](https://github.com/szmohmand/Axiom/actions/runs/43759621781), public read-only app; [16-min post-merge PASS #43759096906](https://github.com/szmohmand/Axiom/actions/runs/43759096906) on byte-identical runtime `c01968c` across 2 live contracts (32/32 samples); [real worker PASS #43759096797](https://github.com/szmohmand/Axiom/actions/runs/43759096797) |

## Future workflow
1. Confirm the intended baseline SHA is fully verified and create a distinct in-repository recovery reference **before** coding.
2. Make candidate changes on an isolated branch within `szmohmand/Axiom`, not by editing the verified branch. Compare the candidate to its baseline.
3. Targeted regression tests, the **entire existing suite**, full synthetic end-to-end, data integrity/security/concurrency/recovery audit, and relevant public read-only integration/browser checks must pass before acceptance.
4. If any previous behavior breaks, **do not merge**. Repair on the isolated branch or restore the pinned checkpoint. Never stack fixes onto an unverified main.
5. Record the newly validated SHA and CI evidence here **after** passing, not when tests are merely queued. Do not move the `verified/` branch.

Git branches are mutable in GitHub; their preservation is a strict project rule, not cryptographic enforcement. The SHA is the exact recovery identity.

## Historical data collection isolation, 2026-11-16

Production baseline remains `b12be3758049b6766dda8fefad06611bf41ada2e`, with existing recovery branch `verified/2026-11-15-b12be37`; both verified by remote read before this work. Existing checkpoint references are preserved. This records identity, not new production certification.

Source research head inspected: `381bb6571a127440b1a5476dcb264989d45abbb3` on `research/extended-historical-data-export-2026-11-16`. New work is isolated on `research/historical-data-completion-2026-11-16`.

The existing BRTI run 43802326178 succeeded. Artifact 14197885366 SHA256: `227295a0a31f1a9fd33f6f4c227f9174c0d280534f82b91d995f7734af52c305`. Independent full-file audit passed 12,978,000 5Hz rows and 2,595,600 first-tick samples, including a one-hour warmup. All 32 data-file hashes and sizes matched. Every adjacent tick advanced 200ms; native/UTC timestamps agreed; every derived second matched independent selection. Original JSON and per-request retrieval times were not retained in that older export.

Kalshi run 43802346611 was still in progress at inspection. No duplicate launched. Its collector explicitly limits transactions to November 13–14; 30 days of transactions must not be claimed.

New requirement: collect August 6–12 using existing BRTI collector, retaining original response bytes, native precision and retrieval metadata without headers. Impact: research wrapper, isolated GET-only Actions workflow and offline tests only. No runtime, dependency configuration or trading code changed. Historical/current/foreseeable review: existing collector is unchanged; wrapper validates positive <=31-day bounds and restores its patched GET helper on error; tests verify hour boundaries, raw precision and exclusion of headers. Local Python 3.12 validation: 77 tests passed across tests/ and research/; 19 permanent regression records and frozen-source transfer checks passed. Python 3.13 CI remains required. No production baseline advanced; no merge/deploy authorized.

Library access: no available Library listing/upload tool in this session. The three preexisting ZIPs are user-confirmed, not independently inspected here. New Library transfer remains PENDING.
