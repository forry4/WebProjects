"""The PLAIN classic terms the shipped game charges, per level, as a fixture.

WHY THIS EXISTS. `payoff.jsonl` pins the arithmetic that turns TERMS INTO A
NUMBER -- the one thing genuinely written twice, since the terms themselves are
shipped to the browser rather than reimplemented. What nothing pinned was WHICH
TERMS the game charges, and offline harnesses that build their own `Contract`
are therefore unguarded by construction.

Three of them had gone stale on the 2026-08-16 re-price and none was loud about
it (found 2026-08-19): `cmatch.rs` and `nullbot.rs` carried `N^2 + 10` against a
set base of `N + 10`, and `abench.rs` the same for level 3, while the engine
ships `N^2 + 4` against `2N + 2` -- and `cmatch` had `over: 0` besides, so every
number it ever reported was measured on flat payouts. Each was internally
consistent, which is why each stayed wrong.

    PYTHONPATH=<repo root> python -m games.dissonance.tools.gen_shipped_terms \\
        > games/dissonance/tests/fixtures/shipped_terms.jsonl

Committed, like the other fixtures -- CI runs cargo with no Python available.
"""

from __future__ import annotations

import json
import sys

from games.dissonance import engine as E


def main() -> None:
    for level in range(E.MIN_LEVEL, E.max_level_for("classic") + 1):
        for jump in (0, 1, 3):
            t = E._terms_for("classic", 0, level, jump=jump)
            print(json.dumps({
                "level": level,
                "jump": jump,
                # Only the fields a `dd::Contract` is built from; anything else
                # would be pinning the generator rather than the price list.
                "make": t["make"],
                "set_base": t["set_base"],
                "over": t["over"],
                "short": t["short"],
                "null": t["null"],
            }))


if __name__ == "__main__":
    sys.exit(main())
