"""`RulesFacts` and `RulesDefs` take SHAPED items — a bare string renders blank.

Both take a list and read named fields off each entry: `RulesFacts` wants
`{k, v}` and `RulesDefs` wants `{t, d}`. Hand either one a list of plain strings
and `it.k` / `it.t` are `undefined`, so React renders the wrapper elements with
nothing inside them. The panel still lays out. The boxes are still there. They
are simply empty.

Rag Tag shipped exactly that in three sections — Setup, Health tracks and
Winning — for as long as the game has existed. Nothing could see it: the Python
suite does not render, `screens.mjs` asserts that markup exists rather than that
it says anything, and the CSS test only checks tokens. The rules panel had three
blank strips in it and looked deliberate.

So this reads the JSX as text and checks the SHAPE of what is passed. The roster
is globbed, never listed, so a new game's rules file is covered the day it is
written rather than the day someone remembers this file.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RULES = sorted(ROOT.glob("games/*/rules.jsx"))

#: component -> the fields it reads off each item
SHAPES = {"RulesFacts": ("k", "v"), "RulesDefs": ("t", "d")}


def _calls(src: str, name: str):
    """Every `<Name items={[ ... ]}` body in the file, brace-matched."""
    out = []
    for m in re.finditer(rf"<{name}\s+items=\{{", src):
        i = m.end() - 1                      # at the opening `{`
        depth = 0
        for j in range(i, len(src)):
            if src[j] in "{[":
                depth += 1
            elif src[j] in "}]":
                depth -= 1
                if depth == 0:
                    out.append(src[i + 1:j])
                    break
    return out


def test_there_are_rules_files_to_check():
    """A glob that matches nothing passes every test below over nothing."""
    assert len(RULES) >= 7, f"only found {[p.name for p in RULES]}"


@pytest.mark.parametrize("path", RULES, ids=lambda p: p.parent.name)
def test_every_rules_item_list_is_shaped_not_a_bare_string(path):
    src = path.read_text(encoding="utf-8")
    for name, fields in SHAPES.items():
        for body in _calls(src, name):
            inner = body.strip().lstrip("[").strip()
            if not inner:
                continue
            # An entry may be an object literal, or an array mapped INTO one
            # (`[[t, d], ...].map(([t, d]) => ({ t, d }))`), which is how a long
            # definition list stays readable. Both end up as objects; a bare
            # string literal does not.
            mapped = re.search(r"\]\s*\.map\(", body)
            assert inner.startswith("{") or inner.startswith("[") and mapped, (
                f"{path.parent.name}/{path.name}: <{name}> is passed bare items — "
                f"it reads {fields} off each one, so these render EMPTY. "
                f"Saw: {inner[:60]!r}")
            if mapped:
                # the .map must actually build the fields the component reads
                built = re.search(r"\.map\(\(\[[^\]]*\]\)\s*=>\s*\(\{([^}]*)\}\)", body)
                assert built, f"{path.parent.name}: <{name}> .map does not return an object"
                for f in fields:
                    assert re.search(rf"\b{f}\b", built.group(1)), (
                        f"{path.parent.name}: <{name}> items are built without "
                        f"`{f}`, which is one of the fields it renders")
