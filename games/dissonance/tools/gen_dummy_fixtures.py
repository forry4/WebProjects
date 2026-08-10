"""Fixtures holding the Rust dummy reader to the Python engine's own views.

`dummy.rs` re-states the rules rather than sharing them with `state.rs` (see
that file's header for why), so NOTHING structural keeps it in step with
`engine.py` -- and a reader that drifts does not crash. It returns a legal card
computed from a slightly wrong position, or refuses every payload and lets the
room play the server bot at full speed while still saying Hard. Both are
invisible from the outside, which is the failure this repo has paid for twice.

So: play whole dummy rounds, dump `view_for` at every ply the bot would be
asked about, and record the TRUTH beside it -- the real hands and pile bottoms,
and the exact legal set the engine would accept. `tests/dummy_wire.rs` replays
the file and demands the reader agree on all of it.

    PYTHONPATH=. python -m games.dissonance.tools.gen_dummy_fixtures [rounds]
"""

from __future__ import annotations

import json
import random
import sys

from games.dissonance import bot, engine as E

OUT = "games/dissonance/tests/fixtures/dummy_views.jsonl"


def rounds(n: int, seed: int = 404):
    rng = random.Random(seed)
    rows = []
    for r in range(n):
        g = E.new_game(["a", "b"], rng, opener=r % 2, mode="dummy")
        # Vary the contract so the fixtures cover trump suits AND no-trump --
        # ruffing is a different rule and a reader that dropped it would still
        # answer every no-trump payload correctly.
        denom = r % (E.NOTRUMP + 1)
        opener = g["auction"]["to_act"]
        E.apply_bid(g, opener, 3, denom)
        E.apply_pass(g, 1 - opener)
        E.apply_double(g, 1 - opener, False)
        while g["phase"] == "play":
            seat = E.playing_seat(g)
            rows.append({
                # The payload exactly as the server would arm it.
                "view": E.view_for(g, seat),
                # ...and the truth, which the view must never have leaked and
                # the determinizer must never contradict.
                "truth": {
                    "hands": [sorted(h) for h in g["hands"]],
                    "piles": [[list(p) for p in pl] for pl in g["piles"]],
                    "out": sorted(g["out"]),
                    "legal": sorted(E.legal_moves(g, seat)),
                    "to_play": E.to_play(g),
                    "turn_seat": seat,
                },
            })
            E.apply_play(g, seat, bot.choose_card(g, seat))
    return rows


def main(n: int) -> None:
    rows = rounds(n)
    with open(OUT, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    # A fixture file is only worth what it REACHES. Print the coverage so a
    # regenerate that quietly stopped producing no-trump rounds, or mid-trick
    # positions, or dummy-to-play plies, is visible rather than silent.
    trumps = sorted({r["view"]["trump"] for r in rows})
    mid = sum(1 for r in rows if r["view"]["plays"])
    dummy_turn = sum(1 for r in rows if r["truth"]["to_play"] == E.DUMMY_POS)
    print(f"wrote {len(rows)} plies from {n} rounds -> {OUT}")
    print(f"  denominations reached: {trumps} (want 0..{E.NOTRUMP})")
    print(f"  mid-trick positions:   {mid}")
    print(f"  the dummy on turn:     {dummy_turn}")
    assert set(trumps) == set(range(E.NOTRUMP + 1)), "a denomination went uncovered"
    assert mid and dummy_turn, "the interesting positions are not in the file"


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 12)
