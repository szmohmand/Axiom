# Exact coverage-path proofs — 2026-11-22

Scope: isolated AXIOM release candidate on branch `feature/axiom-contract-repricing-full-test-gate-2026-11-22`. This report only documents paths that cannot occur or are a CPython coverage-tracer artifact. It is **not** a request to ignore coverage failures.

## Audit policy unchanged

- `tests/coverage_gate.py` still requires raw combined statement/branch coverage **at least 99.5893%**, the last previously verified baseline.
- Zero excluded source lines, no `# pragma: no cover`, no deleted checks or silenced test errors.
- Every uncovered line or branch **not explicitly enumerated** continues to fail the audit.
- Audit continues over `app`, `phase0`, `research`, and `research_sources`, including all now-active boosted, full Nison, CVD/multiscale, and quote-model code.
- New tests cover real semantics: exact Nison OHLC geometries, full chronological true BTC features, data gaps, stale data, signal isolation, read-only quote tracking, real SQLite scoring, opt-in shadow scoring, protected rollback, as-of studies, and command-line entrypoints.

## Exactly reviewed arc 1: `app/nison_structures.py`, `(38, 35)`

At `_auto_bandwidth(prices)`, the branch `if ws` has an apparent empty-weights alternative. For the sampling loop to execute, `range(max(2,n//5),n-2,2)` must be nonempty, implying `n >= 5`. Every sampled `i` is at least 2 and at most `n-3`, so `i-1` and `i+1` are both valid distinct indices. Every candidate Gaussian bandwidth `h >= 1.5` gives radius `int(3*h)+1 >= 5`, so **both neighbors are always included** after the `j != i` exclusion. Their weights `exp(-0.5*((j-i)/h)**2)` are strictly positive. Therefore `ws` cannot be empty when `if ws` executes. For shorter arrays, there are no sampled indices and the branch is never encountered. Keep the defensive condition in the source; do not fabricate an impossible test input.

Exercise: `tests/test_nison_adaptive_structure_geometry_coverage.py::test_kernel_smoothing_bandwidth_and_extrema_noise_are_deterministic` tests multiple array lengths and compares deterministic bandwidths.

## Exactly reviewed arc 2: `app/nison_structures.py`, `(238, 223)`

At `_towers(bars,atr)`, spans are formed **only when `span >= 15`**. The first possible breakpoint is `j=3` in `range(3,span-5)`, nonempty for any such span. For `j=3`, the second breakpoint includes `k=6` in `range(j+3,span-2)`, also nonempty for `span >= 15`. All three fitting segments have at least 3 points, so at least one `fits` tuple is computed, and `best` is assigned. Thus `if best is None: continue` cannot enter its true branch under these conditions. Keep the guard as a defense against possible future algorithm changes; no safety code is removed.

Exercise: `tests/test_nison_adaptive_structure_geometry_coverage.py::test_segmented_tower_and_change_point_structure` tests both directional tower changes with real finite piecewise data and all three fitted segments.

## Exactly reviewed arc 3: `app/storage.py`, `(114, -111)`

`watch_info()` uses `with self.lock:`, calls SQLite `SELECT`, and returns either a populated record from inside the context manager or `None` from inside the same context. The reported direct Coverage.py branch to a negative function exit code is not an application-level decision: CPython inserts a context-manager cleanup step on the way out of the `return`. Both outcomes are explicitly tested by actual SQLite watch rows. A corresponding legacy exemption for the same behavior previously referred to earlier source positions `(113,-110)`; the current exact pair is `(114,-111)`. No blanket negative-exit arcs are approved.

Exercise: `tests/test_ledger_rejection_missing_branches.py` and the existing first-call/watch lifecycle tests.

## Exactly reviewed arc 4: `research/nison_full_shadow_study.py`, `(63, -45)`

`observe()` executes under `with conn:`. With a healthy contract whose `seconds_left` is not within 30 seconds of any prespecified checkpoint (840, 600, 300, or 60), it returns `{"status":"OBSERVING"}` on line 63 *inside* the SQLite transaction context. Tests call this exact input and verify the returned status, while the Coverage.py synthetic arc directly from the return to negative function exit is not observed because Python first exits the context manager. This is an exit-tracing artifact, not an untested forecast branch.

Exercise: `tests/test_shadow_study_full_coverage.py::test_nison_full_study_observe_and_score_all_cases`, with an actual SQLite database, 460 seconds left, and `status=="OBSERVING"`.

## Proved-unreachable scanner branches removed at source, not excluded

`app/nison_methodology.py::_validated` enforces at least 31 genuine completed sequential 1-minute bars, correct OHLCV and time-as-of integrity **before** the detection stage. Secondary guards requiring at least 3/5/6/15 bars in that stage, plus no-history EMA/RSI checks, could never be false after validation. They were removed with the original formation logic and all primary data validation intact. Result: Nison methodology statement and branch coverage 100% on the subsequent audited code.

## Ongoing regression assertions

Tests must still demonstrate that changing Kalshi quote prices or order-book walls cannot alter AXIOM's independent BTC outcome forecast; changing quote costs may alter entry/exit valuation. Funding-rate features remain absent from outcomes. No real exchange orders, no Oracle deployment, and no amendments to unrelated GitHub repositories.
