"""The no-conditional-skips rule, enforced instead of merely written down.

The rule (root CLAUDE.md, Testing): a test that can't reach the state it means
to exercise must FAIL, not opt out — a skip is a green tick over a test that
proved nothing, and the failure it hides looks exactly like a pass in CI. Three
real holes were found and fixed that way.

**This guard exists because the rule DRIFTED, which is the argument for it.**
CLAUDE.md claimed "ZERO conditional skips, repo-wide" while two `importorskip`
calls sat in the tree — one vacuous (`numpy`, a hard requirement, so it could
never fire) and one deliberate (`torch`). Nothing noticed, because a rule whose
only enforcement is prose is enforced only by whoever happens to re-read it.
And the failure is self-concealing: the drift is a SKIP, so the suite stays
green and the summary line, which is where anyone would look, says "passed".

Two design choices, both learned here the expensive way:

* **AST, not regex.** `test_every_find_card_zone_guard_logs_lost_track` shipped
  as a regex over a 6-line window and comments pushed two real sites out of it,
  so it passed while checking 5 of 7. It is also load-bearing in the other
  direction here: two test modules DISCUSS `pytest.skip()` in prose comments
  explaining why a skip was removed, and a text search would flag both. The AST
  sees code, so those are correctly invisible.
* **The roster is DERIVED from `pytest.ini`**, never a hand-written list. A
  hardcoded roster only guards the tree SHRINKING — a new test package would
  join the suite unguarded, silently, which is the exact shape of the
  `range(13)` soak bug the rule itself cites.

This lives in core/tests for the same reason `test_history_limit.py` does, and
with the same constraint: it reads source as TEXT and imports no feature, since
`core/` may not depend on one and that holds for its tests.
"""
import ast
import configparser
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The skip surface. `pytest.skip` / `importorskip` / `xfail` as CALLS, and the
# three marks as DECORATORS — a rule that covered only one form would be a
# doorway rather than a gate.
_SKIP_CALLS = {"skip", "importorskip", "xfail"}
_SKIP_MARKS = {"skip", "skipif", "xfail"}

# ── THE SANCTIONED CARVE-OUTS ────────────────────────────────────────────────
# (path relative to the repo root, the skip form) -> why it is allowed.
# Adding a row here is a DELIBERATE act and owes a matching entry in the
# CLAUDE.md rule; anything not listed is drift by definition.
SANCTIONED = {
    ("games/spender/tests/test_az_actions.py", "importorskip"): (
        "OPTIONAL DEPENDENCY over code that does not ship. Covers SpenderNet in "
        "ai/offline/net.py — the AZ/variant-Z TRAINING stack, imported only by "
        "train_az/arena/az_vs_h2/bootstrap_train. Variant Z is retired and the path "
        "that still serves it to old saves is numpy (infer_np + az_model.npz), never "
        "torch; ai/offline/ is never imported by the server and sits outside the "
        "deploy path filter. Verified 2026-08-07 by installing torch and RUNNING it: "
        "it passes, so it hides no regression. Running it in CI costs a torch install "
        "(4.6GB from PyPI's CUDA build) against a ~50s suite — and it must never enter "
        "games/spender/requirements.txt, which is installed into the prod image."
    ),
}


def _test_files():
    """Every test module the suite actually collects, derived from pytest.ini."""
    cfg = configparser.ConfigParser()
    cfg.read(REPO / "pytest.ini")
    paths = cfg["pytest"]["testpaths"].split()
    assert paths, "pytest.ini declares no testpaths — this guard has rotted"
    files = []
    for p in paths:
        d = REPO / p
        assert d.is_dir(), f"testpaths names {p}, which does not exist"
        files.extend(sorted(d.rglob("test_*.py")))
    return files


def _skips_in(path: Path):
    """(form, lineno) for every skip in the file — code only, never comments."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        # pytest.skip(...) / pytest.importorskip(...) / pytest.xfail(...)
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in _SKIP_CALLS:
                found.append((f.attr, node.lineno))
        # @pytest.mark.skip / .skipif / .xfail — bare or called
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                d = dec.func if isinstance(dec, ast.Call) else dec
                if (isinstance(d, ast.Attribute) and d.attr in _SKIP_MARKS
                        and isinstance(d.value, ast.Attribute) and d.value.attr == "mark"):
                    found.append((d.attr, dec.lineno))
    return found


def _all_skips():
    out = []
    for f in _test_files():
        rel = f.relative_to(REPO).as_posix()
        out.extend((rel, form, line) for form, line in _skips_in(f))
    return out


def test_every_skip_in_the_suite_is_a_sanctioned_one():
    unsanctioned = [(rel, form, line) for rel, form, line in _all_skips()
                    if (rel, form) not in SANCTIONED]
    assert not unsanctioned, (
        "Unsanctioned conditional skip(s):\n"
        + "\n".join(f"  {rel}:{line}  pytest.{form}" for rel, form, line in unsanctioned)
        + "\n\nA test that cannot reach the state it means to exercise must FAIL, not "
          "opt out (root CLAUDE.md, Testing). If this really is an optional-dependency "
          "guard over code that does NOT ship, add it to SANCTIONED here AND to the rule "
          "in CLAUDE.md — the two are meant to be read together."
    )


def test_the_guard_can_actually_see_a_skip():
    """Anti-vacuity, and the thing that makes the roster self-maintaining.

    Without this the whole module passes just as happily when the AST walk is
    broken, when `testpaths` stops resolving, or when someone deletes the torch
    test and leaves a stale allowlist row — every one of which is a guard that
    checks nothing while reporting green, i.e. precisely the failure the rule
    exists to prevent.
    """
    seen = {(rel, form) for rel, form, _ in _all_skips()}
    missing = set(SANCTIONED) - seen
    assert not missing, (
        f"SANCTIONED lists {sorted(missing)}, which the walk no longer finds. Either the "
        "detector broke, or that skip is gone — if it is gone, delete the row (and its "
        "paragraph in CLAUDE.md) rather than leaving a carve-out for nothing."
    )
