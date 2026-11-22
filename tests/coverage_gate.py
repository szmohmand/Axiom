#!/usr/bin/env python3
"""Verify that coverage's remaining raw gaps are all explicitly reviewed.

This does NOT exclude lines, alter source, waive warnings or inflate the
Coverage.py percentage. A new unreviewed missing line/branch fails CI.
Exactly reviewed exceptions are documented in the companion evidence report.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys

# Missing statements are proved unreachable by current source invariants.
REVIEWED_MISSING_STATEMENTS = {
    "app/orderbook.py": {100, 158},
    # 37 five-second buckets either fail early on missing genuine BRTI data
    # or produce exactly 36 adjacent returns. Keep the defensive check.
    # Exercised with complete and incomplete input in
    # test_five_second_rolling_sigma_reconnect_and_source_gaps.
    "app/brti_live.py": {123},
    "app/settlement_research.py": {88},
    # 31+ strictly valid continuous bars always produce 30+ log returns;
    # this defensive check is logically unreachable without altering inputs
    # between validation and arithmetic. Keep the safety guard in source.
    "app/decision_signals.py": {73},
    "research/verify_official_brti_live.py": {110},
}
# Exact, individually proven unreachable branches / Python tracer artifacts.
# Each added arc has a line-by-line invariant proof, an exercised observable
# outcome, and a specific test in
# reports/AXIOM_COVERAGE_UNREACHABLE_PROOFS_2026-11-22.md.
# Not a generic waiver: all other new arcs STILL fail this gate.
REVIEWED_MISSING_ARCS = {
    "app/engine.py": {(129, -104)},
    # _book guards both sides nonempty and strictly uncrossed before
    # _near_depth, so it cannot return a missing midpoint at line 173.
    # ingest rejects every venue except Coinbase/Kraken/Bitstamp before
    # the if/elif dispatch, making the final Bitstamp-false arc impossible.
    # Both malformed-book reset and all three venue dispatches are tested.
    # Diagnostic-only methods shifted these existing, proven-unreachable
    # source guards; no new exception is introduced by this update.
    "app/axiom_brain.py": {(240, -202), (353, -266)},
    # The source-second loop always contains 37 five-second windows; all
    # accepted iterations append once, yielding 36 returns exactly.
    "app/brti_live.py": {(122, 123)},
    "app/decision_signals.py": {(72, 73)},
    "app/orderbook.py": {(99, 100), (157, 158)},
    "app/settlement_research.py": {(87, 88)},
    # Return from 'with self.lock' has a compiler-inserted context-manager
    # exit. Real populated and empty watch returns are both exercised.
    "app/storage.py": {(114, -111), (127, -124)},
    # watch_info's populated-return branch exits a 'with self.lock' block;
    # CPython reports the impossible direct return-to-function arc.
    # Both populated and empty results are exercised in the ledger tests.
    # All sampled i have >=2 available neighbors within Gaussian radius.
    # Every candidate tower segment length >=15 has valid j,k partitions.
    "app/nison_structures.py": {(38, 35), (238, 223)},
    # observe() returned OBSERVING from within 'with conn:' in tests;
    # the direct synthetic function-exit arc misses context-manager exit.
    "research/nison_full_shadow_study.py": {(63, -45)},
    "research/verify_official_brti_live.py": {(109, 110)},
}


def validate(result: dict) -> list[str]:
    problems = []
    totals = result.get("totals", {})
    if totals.get("excluded_lines", 0) != 0:
        problems.append("Source code exclusions are not permitted in this audit")
    files = result.get("files")
    if not isinstance(files, dict) or not files:
        return problems + ["Coverage JSON lacks measured source files"]
    for name, details in sorted(files.items()):
        missing_lines = set(details.get("missing_lines", []))
        missing_arcs = {tuple(x) for x in details.get("missing_branches", [])}
        unexpected_lines = missing_lines - REVIEWED_MISSING_STATEMENTS.get(name, set())
        unexpected_arcs = missing_arcs - REVIEWED_MISSING_ARCS.get(name, set())
        if unexpected_lines:
            problems.append(f"{name}: new unreviewed missing statements {sorted(unexpected_lines)}")
        if unexpected_arcs:
            problems.append(f"{name}: new unreviewed missing branches {sorted(unexpected_arcs)}")
    if totals.get("percent_covered", 0) < 99.5893:
        problems.append("Coverage fell below the last verified 99.5893% baseline")
    return problems


def main(path: str) -> int:
    evidence = json.loads(Path(path).read_text())
    issues = validate(evidence)
    if issues:
        print("FAIL: coverage review gate rejected uncovered execution paths:")
        for issue in issues:
            print("  " + issue)
        return 1
    totals = evidence["totals"]
    print(
        "PASS: no new unreviewed missing paths, no exclusions, "
        f"raw Coverage.py {totals['percent_covered']:.4f}% / "
        f"{totals['missing_lines']} missing statements / "
        f"{totals['missing_branches']} missing branches; "
        "all remaining arcs explicitly documented"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "full-code-coverage.json"))
