# AXIOM — historical/current/foreseeable impact gate

This is the **required evidence template** for every proposed functional change to AXIOM, and applies to reviews of each implemented component **and** the integrated system. Complete it in the change's pull request or in a dated report with links. This file defines the gate; it is **not** a blanket certification of future changes.

## Gate for each change

**Change identifier / PR:** _to be completed per change_  
**Verified baseline SHA and unmodified recovery reference:** _to be completed_  
**Candidate SHA and diff:** _to be completed_  
**Original behavior, change and dependency map:** _to be completed_

| Horizon | Required evidence | Status (PASS/BLOCKED/N/A with rationale) |
|---|---|---|
| Relevant historical behavior | Prior verified checkpoint, archived source identity, permanent historical regression tests, affected ledger and compatibility semantics | PENDING |
| Current components individually | Full implemented test suite, changed and unchanged components, targeted before/after tests, contract calculations, quote/fee checks, snapshots, ledger, UI/API | PENDING |
| Current system end-to-end | Complete simulated lifecycle, feed-to-decision consistency, paper controls, official outcome grading, persistence, restart, error/recovery and concurrency checks | PENDING |
| Reasonably foreseeable effects | Relevant boundary/scale, timing, API/contract changes, future data conditions, outage and restart scenarios | PENDING |
| External interfaces | Real **read-only** integration checks when relevant, and explicit external limitations | PENDING |
| Regressions and unresolved risks | No known regressions, required tests missing or material unresolved interactions | PENDING |

**Approval rule:** `PASS` requires all applicable verification to be complete, the specific purpose of the change to be proven, and **no known regression or unresolved material risk**. If a required applicable check cannot be performed or a consequential issue remains unresolved, mark `BLOCKED` and do not merge, deploy, or advance dependent work. Document unavailable but **irrelevant** history rather than treating it as an automatic stop.

**Foreseeability is bounded:** Review plausible implications of **this proposed change**. It is impossible to pre-certify every conceivable future change. Unknown future inventions or conditions are not automatic blockers; any later modification must pass the complete gate when proposed.

**Recovery decision:** Roll back to the preserved verified SHA or fix the isolated candidate and repeat the complete applicable verification.

## Policy-only adoption, November 15, 2026

This document sets the prospective gate but changes **no** forecast calculations, execution behavior, storage schemas, paper/real orders, or deployed infrastructure. The previously verified working baseline is `50d84ac9bc8cef7b8b82e0f555ed39ba37df1cab`, preserved at `verified/2026-11-15-50d84ac` inside `szmohmand/Axiom`. The adoption's GitHub CI runs and merge decision are recorded in its pull request. The tests do not certify future, as-yet-unwritten changes.
