"""Real `view_for` payloads, for the Rust wire reader to replay.

The Hard tier searches the SERVER'S OWN per-seat view — `engine.view_for`, the
same builder that feeds a human — read back into `dissonance-core`'s `View` by
`src/wire.rs`. That crossing is a second parity surface alongside the card-play
one, and it fails in a way nothing else notices: a reader that mis-sizes the
hidden pool or drops a void still returns a legal card, just a worse one. A bot
that quietly plays at Normal strength while the room says Hard is exactly the
class of bug the play fixtures exist to prevent, so it gets fixtures too.

Every position of several complete games, both seats, both auction modes:

    PYTHONPATH=<repo root> python -m games.dissonance.tools.gen_view_fixtures \\
        > games/dissonance/tests/fixtures/views.jsonl

then `cargo test --features bridge` in `rust-cores/dissonance-core`. The file is
COMMITTED, like `play.jsonl` — CI runs the Rust tests without a Python step.
Regenerate whenever `view_for` changes shape.
"""

from __future__ import annotations

import json
import random
import sys

from games.dissonance import bot as B
from games.dissonance import engine as E

GAMES = 4


def _settle(g: dict, rng: random.Random) -> None:
    """Drive every pre-play phase with the heuristic bot, both seats."""
    for _ in range(80):
        if g["phase"] in ("play", "over"):
            return
        seat = E.turn_seat(g)
        kind, mv = B.act(g, seat, rng)
        pid = g["seats"][seat]
        if kind == "bid":
            E.apply_move(g, pid, {"kind": "pass"} if mv.get("pass")
                         else {"kind": "bid", **mv})
        elif kind == "swap":
            E.apply_move(g, pid, {"kind": "swap", **mv})
        elif kind == "play":
            E.apply_move(g, pid, {"kind": "play", "card": mv})
        else:
            E.apply_move(g, pid, mv)


def main() -> None:
    out = []
    for i in range(GAMES):
        rng = random.Random(1000 + i)
        mode = "skat" if i % 2 else "classic"
        g = E.new_game(["a", "b"], rng, opener=i % 2, mode=mode)
        _settle(g, rng)
        while g["phase"] == "play":
            seat = E.to_play(g)
            # BOTH seats every ply, not just the mover: the defender's view is
            # the one with all six out-cards still hidden, and it is a different
            # pool arithmetic from the declarer's.
            for s in (0, 1):
                v = E.view_for(g, s)
                v["_mover"] = seat
                out.append(json.dumps(v, separators=(",", ":")))
            E.apply_move(g, g["seats"][seat],
                         {"kind": "play", "card": B.choose_card(g, seat)})
    sys.stdout.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
