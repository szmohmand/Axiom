"""Prove the strict coverage gate is not weakened by exact-path reviews.

The current gate still rejects new uncovered paths, excluded statements,
and results below the historical raw measured 99.5893% threshold.
"""
from coverage_gate import validate, REVIEWED_MISSING_ARCS


def sample(arcs=None,pct=99.7,excluded=0):
    return {"totals":{"percent_covered":pct,"excluded_lines":excluded},
            "files":{"app/nison_structures.py":{
                "missing_lines":[],"missing_branches":arcs or []}}}


def test_documented_mathematical_impossibility_accepted_but_unknown_path_rejected():
    exact=[list(arc) for arc in REVIEWED_MISSING_ARCS["app/nison_structures.py"]]
    assert validate(sample(exact))==[]
    issues=validate(sample(exact+[[999,1000]]))
    assert len(issues)==1 and "unreviewed missing branches" in issues[0]
    assert "(999, 1000)" in issues[0]


def test_zero_exclusions_and_historical_raw_threshold_still_enforced():
    assert validate(sample(pct=99.5893))==[]
    assert any("99.5893%" in x for x in validate(sample(pct=99.58)))
    assert any("exclusions" in x for x in validate(sample(excluded=1)))
    assert any("unreviewed missing statements" in x for x in
               validate({"totals":{"percent_covered":100,"excluded_lines":0},
                         "files":{"app/nison_structures.py":{
                           "missing_lines":[999],"missing_branches":[]}}}))
