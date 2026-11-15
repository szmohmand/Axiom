# AXIOM Phase 0 — recorded requirements and implementation gaps

**Source precedence**: current user Phase 0 instruction > AXIOM v2 README / tests > historical conversation decisions for AXIOM. Requirements from other named projects are not imported without explanation.

| Req | New bot requirement | Origin | Status in frozen AXIOM v2 |
|---|---|---|---|
| R-01 | BTC 15-minute Kalshi ABOVE/BELOW forecast with target and expiration | AXIOM v2 README | PARTIAL: model exists, statistical validation absent |
| R-02 | Independent probability calculations; Kalshi YES prices only benchmark and opportunity assessment | AXIOM v2 README | IMPLEMENTED experimental separation, uncalibrated |
| R-03 | Three experimental forecasters and consensus plus clearly separate market baseline | AXIOM v2 README | IMPLEMENTED, but overlap in underlying inputs |
| R-04 | Independent BTC LONG/SHORT/WAIT scalp guidance | AXIOM v2 README | IMPLEMENTED, indicative only; scalp P&L absent |
| R-05 | Forecast and execution/opportunity details independently visible; actionable conditions | Earlier user requirement + v2 README | PARTIAL: dashboard and entry screen, no advanced execution lifecycle |
| R-06 | Paper ledger and independent engine outcome scoring against official Kalshi results | AXIOM v2 README | IMPLEMENTED offline; not live-validated |
| R-07 | Treat CF BRTI reference distinctly from Coinbase proxy | AXIOM v2 README + earlier user direction | GAP: Coinbase used as proxy; official settlement used only for result grading |
| R-08 | No automated real orders; manual user execution and simulated trades only | AXIOM v2 README + earlier user direction | ENFORCED by current prototype scope |
| R-09 | Mobile accessible dashboard | AXIOM v2 README | IMPLEMENTED local static UI; no remote deployment |
| R-10 | Use only `szmohmand/Axiom` existing `main`; no other repositories or branch creation/deletion, services or databases | User direction | ENFORCED by remote target allowlist `szmohmand/Axiom` / `main` |
| R-11 | Run offline tests and inspect every new research method before integrating | Phase 0 instruction / earlier user direction | 21 tests now pass; further methods not migrated |
| R-12 | Reproducible clean install, audit-version mapping, explicit transfer approval | Current Phase 0 instruction | INCOMPLETE pending external evidence and clean install |

## Unresolved contradictions / scope

The earlier **BTC Intelligence Engine — Phase 0 Product Requirements & Acceptance v1.0** has a different market-integration scope and should not be treated as a revision of AXIOM's README. AXIOM remains a research prototype. No new trading capabilities are silently inferred or launched by this package.
