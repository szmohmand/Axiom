# AXIOM engineering invariant — no accepted regressions

**Scope:** This is a standing requirement for *every* AXIOM change, including code, dependencies, configuration, data schema, model logic, UI, infrastructure, and test changes. It is mandatory for human contributors and automated coding agents. Only `szmohmand/Axiom` is authorized; do not access or modify other repositories. Never place credentials or private data in source control. No real trading or deployment without separate explicit user authorization.

> A fix is successful only when the original defect is gone **and the rest of the implemented system still works correctly**. A failing or regressing candidate must not be merged or deployed.

## Mandatory change sequence

1. **Understand existing behavior first.** Inspect the actual code, inputs, outputs, dependencies, callers, stores, UI and related tests. Write down what should remain unchanged, what can break, and how failure will be detected.
2. **Preserve the last verified baseline before modifying anything.** Record its full Git commit SHA and successful CI / end-to-end evidence in `reports/VERIFIED_CHECKPOINTS.md`. Keep a recovery reference inside this Axiom repository; never delete or repoint an existing `verified/` checkpoint branch. Work in an Axiom-only change branch when possible, not by directly replacing a known-good `main`.
3. **Implement the smallest effective correction.** Do not refactor unrelated logic or silently change forecasting/trading semantics. Make any intentional behavior changes explicit.
4. **Prove the specific defect is fixed.** Create a regression test that would fail on the prior defective implementation. Test the normal case, failure, recovery, and relevant boundary/concurrency cases.
5. **Retest all existing functionality.** Run the complete existing suite, not just tests for edited files. Do not delete, skip, weaken, mark xfail, or change assertions of prior regression tests to make a candidate pass. Add each newly discovered defect to `reports/REGRESSION_HISTORY.json` with one or more permanent pytest selectors. Run `python phase0/check_regression_history.py` and `python -m pytest -q`.
6. **Run the complete implemented system end to end.** Check feeds -> engine/ensemble -> opportunities/scalping -> paper controls -> snapshots -> official-result grading -> scorecards -> storage/restart -> HTTP/UI. Exercise both healthy and degraded scenarios. Run read-only real-provider smoke tests when relevant/available; never interpret a single provider snapshot as sustained reliability or proof of accuracy.
7. **Audit unintended consequences.** Check data integrity, precise timing, price/fee calculations, stale inputs, persistence, concurrency/idempotency, errors and independent recovery, security and regressions in unchanged components. Preserve original v1/v2 source archives and their frozen checksums.
8. **Reject regressions.** If any existing behavior breaks unexpectedly, do not merge or deploy. Diagnose against the preserved baseline; repair in the isolated branch and repeat *all* gates, or revert to the verified checkpoint rather than stacking fixes on an unverified state. No green CI/partial test subset alone can waive a known failure.
9. **Advance the verified baseline only after evidence.** Record the new SHA, full CI run, end-to-end outcome, open limitations and what changed. A known defect, a skipped validation, or a testable inconsistency is not a passing release. Report limitations clearly—tests reduce risk but cannot prove all possible future conditions.

## Acceptance evidence required for every future change

- Baseline SHA and recovery pointer; source-to-destination diff and impact map.
- Named defect/requirement and targeted before/after regression test evidence.
- Green full Python tests and regression-history checker on the proposed commit.
- Complete synthetic lifecycle evidence; real read-only integration check when affected interfaces depend on external providers.
- Relevant HTTP/UI, persistence, concurrency, data correctness, timing, and recovery checks.
- No known regressions; explicit notes for independent unverified performance topics (e.g. probability calibration, BRTI basis, profitability, uptime).

No automatic real orders. The user may authorize new branches only **inside Axiom**; no other repository may be accessed.

## Mandatory historical, current, and forward-impact safety gate

**STOP RULE — applies to every individual component review and every integrated-system review.** Before any code/config/schema/model/UI/infrastructure change can be accepted, or the project moves to its next engineering phase, establish with recorded evidence that it introduces **no known harm** across all three horizons:

1. **Historical behavior:** Compare the candidate with the preserved last-verified revision, retained original archives, all reachable historical code/config revisions and the permanent regression history. Re-run tests for every previously discovered failure and trace how legacy records, migrations, decisions, timing and stored outcomes are affected. An unavailable historical source or unverified legacy behavior is an **evidence gap**, never presumed harmless.
2. **Current behavior:** Examine every implemented component individually *and* the actual connected system, whether or not edited. Run targeted before/after checks, the entire permanent regression suite, synthetic full-cycle scenarios, relevant real **read-only** integration, UI/API, database consistency, parallelism/retry/idempotency, error and recovery checks. Verify unchanged components still produce compatible, consistent results.
3. **Foreseeable future behavior:** Enumerate plausible future states and interactions caused by the change (boundary prices/time, changing contracts/data schemas/API payloads, stale or incomplete data, outages and recoveries, backlog growth, restarts, concurrency, retention and version compatibility). Use boundary/stress/property/scenario tests where practical. Document assumptions, unsupported conditions and each remaining risk; do **not** claim a test proves that every imaginable future change or event is harmless. New future changes require their own complete review at the time they are proposed.

**Decision gate:** Each review must contain a traceable evidence matrix for historical/current/foreseeable-future effects, per-component and whole-system coverage, test artifacts, unresolved questions and a binary `PASS` or `BLOCKED` decision. If any material interaction, regression, uncertainty or required test is unresolved, the decision is **BLOCKED**. Do not move to the next phase, merge a functional change, deploy, or label the code safe. Preserve and return to the last verified checkpoint; repair the isolated candidate and rerun every applicable gate. No vague "should be fine," selective passing tests, silent risk waiver, or proof-by-absence is acceptable.

**Proof limit:** A universal guarantee about all undefined future changes is logically impossible. Our enforceable standard is exhaustive assessment of **available history**, every **implemented current component**, and **identified reasonably foreseeable future interactions**, with explicit uncovered evidence keeping the gate blocked. Do not substitute a green CI run for this human and automated impact audit.

The current project-wide readiness state is recorded in `reports/CHANGE_SAFETY_GATE.md`. This safeguard policy may be merged without releasing new functionality; it does not by itself turn a `BLOCKED` readiness state into `PASS`.
