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
    "app/settlement_research.py": {88},
    # 31+ strictly valid continuous bars always produce 30+ log returns;
    # this defensive check is logically unreachable without altering inputs
    # between validation and arithmetic. Keep the safety guard in source.
    "app/decision_signals.py": {73},
    "research/verify_official_brti_live.py": {110},
}
# Exact coverage.py branch arcs. app/storage.py 113->-110 is a CPython
# return-from-with tracer artifact; tests exercise both return outcomes.
REVIEWED_MISSING_ARCS = {
    "app/engine.py": {(129, -104)},
    "app/decision_signals.py": {(72, 73)},
    "app/orderbook.py": {(99, 100), (157, 158)},
    "app/settlement_research.py": {(87, 88)},
    "app/storage.py": {(113, -110)},
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
