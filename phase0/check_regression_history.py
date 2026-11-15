#!/usr/bin/env python3
"""Verify all previously discovered defects retain concrete pytest tests.

Also run the complete pytest suite. This checker checks existence/collection
naming, not the correctness of each assertion.
"""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "reports" / "REGRESSION_HISTORY.json"

def check():
    errors = []
    entries = json.loads(HISTORY.read_text(encoding="utf-8")).get("entries", [])
    if not entries:
        return ["Regression history is empty"]
    seen = set()
    parsed = {}
    for row in entries:
        ident = row.get("id")
        if not ident or ident in seen:
            errors.append(f"Duplicate or missing history ID: {ident}")
        seen.add(ident)
        if not row.get("finding") or not row.get("fixed_commit"):
            errors.append(f"{ident}: missing finding or commit")
        if not row.get("tests"):
            errors.append(f"{ident}: missing permanent test selectors")
        for selector in row.get("tests", []):
            if not isinstance(selector, str) or selector.count("::") != 1:
                errors.append(f"{ident}: malformed selector {selector!r}")
                continue
            relative, function = selector.split("::", 1)
            path = Path(relative)
            if (path.is_absolute() or ".." in path.parts or
                    path.parts[:1] != ("tests",) or path.suffix != ".py" or
                    not function.startswith("test_")):
                errors.append(f"{ident}: unsafe or invalid selector {selector}")
                continue
            filename = ROOT / path
            if not filename.is_file():
                errors.append(f"{ident}: regression test file removed: {relative}")
                continue
            if filename not in parsed:
                try:
                    parsed[filename] = {
                        node.name for node in ast.parse(
                            filename.read_text(encoding="utf-8")
                        ).body
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    }
                except (SyntaxError, UnicodeDecodeError) as error:
                    errors.append(f"Cannot parse {relative}: {error}")
                    parsed[filename] = set()
            if function not in parsed[filename]:
                errors.append(f"{ident}: regression test removed: {selector}")
    return errors

if __name__ == "__main__":
    failures = check()
    if failures:
        for failure in failures:
            print("FAIL:", failure)
        sys.exit(1)
    n = len(json.loads(HISTORY.read_text(encoding="utf-8"))["entries"])
    print(f"PASS: {n} permanent regression records retain their pytest tests")
