# AXIOM verified checkpoints and recovery references

Preserve every last-known-good commit **before** a new change. Keep old SHA and recovery reference; never delete or repoint a `verified/` branch. This certifies the tested engineering checkpoint only, not trading profitability or production uptime.

| Date | Exact verified SHA | Recovery branch | Full-suite CI | Real read-only integration |
|---|---|---|---|---|
| 2026-11-15 | `981eb1e727159cb350edb59dd2872ed74443c942` | `verified/2026-11-15-981eb1e` | [Pass #43736997711](https://github.com/szmohmand/Axiom/actions/runs/43736997711), 49 tests | [Pass #43736997802](https://github.com/szmohmand/Axiom/actions/runs/43736997802), Kalshi/Coinbase and application API |
| 2026-11-15 | `50d84ac9bc8cef7b8b82e0f555ed39ba37df1cab` | `verified/2026-11-15-50d84ac` | [Pass #43739391137](https://github.com/szmohmand/Axiom/actions/runs/43739391137), regression policy CI | [Pass #43739391130](https://github.com/szmohmand/Axiom/actions/runs/43739391130), public read-only sources |
| 2026-11-15 | `88957587e1b4e5a94acc78956821ef3e8ebfdf44` | `verified/2026-11-15-8895758` | [Pass #43741212964](https://github.com/szmohmand/Axiom/actions/runs/43741212964), full suite | [Pass #43741212473](https://github.com/szmohmand/Axiom/actions/runs/43741212473), public read-only sources |
| 2026-11-15 | `2694dd0faf01479dea396e81535605dbf6e2111f` | `verified/2026-11-15-2694dd0` | [Pass #43753123878](https://github.com/szmohmand/Axiom/actions/runs/43753123878), 62 baseline tests | [Pass #43753123862](https://github.com/szmohmand/Axiom/actions/runs/43753123862), snapshot-only; later source candle gaps exposed limitation |
| 2026-11-15 | `902f7d7dfd7a4a952b4afc2019f01a599af43355` | `verified/2026-11-15-902f7d7` | [Pass #43759621808](https://github.com/szmohmand/Axiom/actions/runs/43759621808), 72 tests, 19 permanent regressions, archive checks | [Pass #43759621781](https://github.com/szmohmand/Axiom/actions/runs/43759621781), public read-only app; [16-min post-merge PASS #43759096906](https://github.com/szmohmand/Axiom/actions/runs/43759096906) on byte-identical runtime `c01968c` across 2 live contracts (32/32 samples); [real worker PASS #43759096797](https://github.com/szmohmand/Axiom/actions/runs/43759096797) |

| 2026-11-17 | `8f3c16d60f1f29f177bcb9aaa7685d1c037b9ebe` | `verified/2026-11-17-8f3c16d-pre-node24` | [Pass #44167929003](https://github.com/szmohmand/Axiom/actions/runs/44167929003), full historical + synthetic suite; [worker #44167928957](https://github.com/szmohmand/Axiom/actions/runs/44167928957), two real live polls; [browser #44167928969](https://github.com/szmohmand/Axiom/actions/runs/44167928969), mobile/desktop Chromium | [Pass #44167929016](https://github.com/szmohmand/Axiom/actions/runs/44167929016), read-only real-provider snapshot; development test-only baseline, **not** a production/rollover certification |

| 2026-11-17 | `ce71c66c087c75a9883f010757b67804c31578a1` | `verified/2026-11-17-ce71c66-node24` | [Pass #44192967169](https://github.com/szmohmand/Axiom/actions/runs/44192967169), 20 permanent regressions and full synthetic suite; [browser #44192967384](https://github.com/szmohmand/Axiom/actions/runs/44192967384), mobile + desktop; [read-only worker #44192967202](https://github.com/szmohmand/Axiom/actions/runs/44192967202), 2 real polls | [Pass #44192967074](https://github.com/szmohmand/Axiom/actions/runs/44192967074), official Kalshi public endpoints and Coinbase; [16-minute rollover #44192967168](https://github.com/szmohmand/Axiom/actions/runs/44192967168), 32 samples, 2 safe brief contract-publication gaps |

| 2026-11-17 | `54fe1a288333e24d90b4c730c4b7c783dbec20d2` | `verified/2026-11-17-54fe1a2-pre-numeric-hardening` | [Full pytest + archive and 23 permanent regressions #44234033750](https://github.com/szmohmand/Axiom/actions/runs/44234033750); [measured coverage #44234033687](https://github.com/szmohmand/Axiom/actions/runs/44234033687): 98.64% at exact audit SHA, before new numeric regressions | [Read-only provider #44234033836](https://github.com/szmohmand/Axiom/actions/runs/44234033836); sandbox-only audit source and no real orders |

## Future workflow
1. Confirm the intended baseline SHA is fully verified and create a distinct in-repository recovery reference **before** coding.
2. Make candidate changes on an isolated branch within `szmohmand/Axiom`, not by editing the verified branch. Compare the candidate to its baseline.
3. Targeted regression tests, the **entire existing suite**, full synthetic end-to-end, data integrity/security/concurrency/recovery audit, and relevant public read-only integration/browser checks must pass before acceptance.
4. If any previous behavior breaks, **do not merge**. Repair on the isolated branch or restore the pinned checkpoint. Never stack fixes onto an unverified main.
5. Record the newly validated SHA and CI evidence here **after** passing, not when tests are merely queued. Do not move the `verified/` branch.

Git branches are mutable in GitHub; their preservation is a strict project rule, not cryptographic enforcement. The SHA is the exact recovery identity.
