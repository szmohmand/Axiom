# AXIOM verified checkpoints and recovery references

Preserve every last-known-good commit **before** a new change. Keep old SHA and recovery reference; never delete or repoint a `verified/` branch. This certifies the tested engineering checkpoint only, not trading profitability or production uptime.

| Date | Exact verified SHA | Recovery branch | Full-suite CI | Real read-only integration |
|---|---|---|---|---|
| 2026-11-15 | `981eb1e727159cb350edb59dd2872ed74443c942` | `verified/2026-11-15-981eb1e` | [Pass #43736997711](https://github.com/szmohmand/Axiom/actions/runs/43736997711), 49 tests | [Pass #43736997802](https://github.com/szmohmand/Axiom/actions/runs/43736997802), Kalshi/Coinbase and application API |

## Future workflow
1. Confirm the intended baseline SHA is fully verified and create a distinct in-repository recovery reference **before** coding.
2. Make candidate changes on an isolated branch within `szmohmand/Axiom`, not by editing the verified branch. Compare the candidate to its baseline.
3. Targeted regression tests, the **entire existing suite**, full synthetic end-to-end, data integrity/security/concurrency/recovery audit, and relevant public read-only integration/browser checks must pass before acceptance.
4. If any previous behavior breaks, **do not merge**. Repair on the isolated branch or restore the pinned checkpoint. Never stack fixes onto an unverified main.
5. Record the newly validated SHA and CI evidence here **after** passing, not when tests are merely queued. Do not move the `verified/` branch.

Git branches are mutable in GitHub; their preservation is a strict project rule, not cryptographic enforcement. The SHA is the exact recovery identity.
