## AXIOM change acceptance — complete before merge

**A change is successful only when the target defect is fixed AND the rest of the implemented system still works.**

- [ ] Only `szmohmand/Axiom` was accessed; no unrelated repositories, deployments, real orders, or original source ZIPs were changed
- [ ] Recorded last fully verified baseline SHA and its unmodified `verified/` recovery branch: `________________`
- [ ] Documented the existing behavior, impacted callers, dependent data/HTTP/UI paths, expected unchanged behavior and risks
- [ ] Kept the change targeted; listed any intentional changes to semantics
- [ ] Added permanent tests to `reports/REGRESSION_HISTORY.json` for newly found bugs; verified the tests fail against the previous defective behavior
- [ ] Ran source/archive/secret checks, `phase0/check_regression_history.py`, and **all** existing tests on the proposed commit
- [ ] Exercised synthetic end-to-end workflow: feeds → forecast/scalp/opportunity → manual/automatic paper guards → snapshots → settlement → scoring → persistence/restart → API/UI
- [ ] Verified failure and recovery states, timing, math, data integrity, concurrency/idempotency, and impact on previously working components
- [ ] Completed live **read-only** provider/application integration checks (or clearly documented a genuine external limitation; **do not declare fully validated** if an applicable check is unavailable)
- [ ] Compared the code and results against the preserved baseline; **no known regressions**
- [ ] Attached exact CI URLs, test results, and audit evidence; updated `reports/VERIFIED_CHECKPOINTS.md` only when the new code truly qualifies

**Known unverified areas / limitations:**

**Rollback plan:** If a regression appears, stop promotion, return to the preserved verified commit, or repair on the isolated Axiom branch and repeat all checks. Never stack new unverified fixes.

**Release decision:** `PENDING` until all applicable checks pass and no regression is known.
