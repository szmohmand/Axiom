# AXIOM engineering resilience and coverage acceptance — 2026-11-17

**Candidate:** isolated `fix/axiom-quantum-grade-resilience-coverage-2026-11-17`, forked from `567b75f7823a960918f911da160fd7e06ccea530`. **Recovery reference:** `verified/2026-11-17-567b75f-coverage86`. Earlier `verified/**` checkpoints untouched. `main` and PR #17 unchanged. No deployment or real orders.

## Requirements and technical changes

| Requirement | Repair / verification | Evidence limitation |
|---|---|---|
| Unexercised exception paths | Independent malformed-payload, time, price, fee, position, worker, HTTP, SQLite, archive, signing, and source-fetch injection. Every original test retained. Measured coverage includes app, research, transfer and source collector; no code removed from measurement. | Coverage measures executed statements/branches, not proof of every future state. Some defensive branches may be structurally unreachable. |
| Kalshi publication gap | One **strictly bounded** retry within first 90 seconds after real 900-second boundary, now also after transient 404/429/500/502/503/504 HTTP listing errors. Original errors outside boundary preserved; second failure returns unavailable and `WAIT`. | Cannot force Kalshi to publish a new market or guarantee zero downtime. |
| Delayed official BRTI history | Read-only authenticated historical reference workflow can be retried every two hours **after separately authorized merge to default branch**. The script records pending missing seconds and checks older genuinely complete contracts; mismatches stop verification. | Provider publication lag, missing 5Hz seconds and as-of delivery timing cannot be manufactured. This is a retry/alert mechanism, not guaranteed publication. |
| Real executable returns | Existing evidence gate strictly reports zero authenticated fills and unknown real net P&L; additional tests assert it never promotes paper or order-book hypotheticals. | No bot-attributable live orders/fills, applied fee ledger or genuine exit executions supplied. It would be misleading to claim verified profits. Public repository CI must never publish private account records. |
| Historical transfer sign-off | `phase0/OWNER_DISPOSITION_PACKET.md` records exact archived hashes, new import SHA, original-history and audit ZIP gaps, and the two valid owner decision paths. | Cannot forge a missing upstream SHA or sign for the owner; formal sign-off remains pending. |

## Historical/current/foreseeable impact map

- **Feeds:** `app/feeds.py` is the only modified application source. Existing public Kalshi listing, full-depth orderbook, Coinbase spot/candles, settled-market lookup and demo provider interfaces retained. New transient HTTP rollover behavior is the sole intentional functional difference. Off-boundary errors and second failure remain fail-closed.
- **Independent forecasting and scalp:** `app/engine.py`, `app/ensemble.py`, `app/settlement_research.py` unchanged. Model never votes using participant quote prices. No calibration claims.
- **Depth/opportunity/execution:** `app/orderbook.py`, `app/depth_intelligence.py`, `app/execution_evidence.py` unchanged; all depth research read-only, book walk simulated, no individual orders, no authentic fills or net P&L claims.
- **Ledger/settlement:** `app/storage.py`, `app/settlement_reference.py`, `app/main.py` unchanged. Tests cover fail-closed official-result grading, missing index seconds, SQLite atomicity, staleness, restart, settlement queue and worker failure.
- **HTTP/UI:** no application UI change; test live HTTP/worker, manual paper token guards, mobile/desktop browser on final candidate.
- **Security/CI:** no new runtime dependencies, secrets or order endpoints; signing dependency and coverage library installed only in isolated CI. Scheduled official BRTI check only becomes active on default branch after separately authorized merge. No automatic order execution.
- **Reproducibility:** frozen ZIPs, permanent regression inventory including new A27, deterministic 2,500-book invariant test, all pytest cases and independent offline auxiliary suites.

## Release decision (pending exact-head acceptance evidence)

**No claim of mathematical perfection.** Final candidate must pass source/manifest checks, complete pytest, 2 independent auxiliary suites, full measured branch/line coverage, read-only Kalshi/Coinbase smoke, authentic BRTI reconciliation, real worker+HTTP, mobile/desktop browser, 16-minute rollover observation, and all applicable specialized source probes. An external 503 handled by `WAIT` is a correctly managed **operational interruption**, not zero downtime.

**Acceptance remains DRAFT / NOT MERGED / NOT DEPLOYED.** Record final run IDs and any warning/exception separately in the PR; a green test is not permission to assert real-money profitability or owner approval.
