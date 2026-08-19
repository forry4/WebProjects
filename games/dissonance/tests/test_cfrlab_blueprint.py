"""The blueprint bidder's live-game <-> abstraction mapping.

`cfrlab` already knows how to drive a REAL auction to an abstract state
(`_path_to` + `_drive_to`, which the off-policy probes use). The blueprint
bidder needs the INVERSE -- read `(level, prev, holds)` off an auction in
progress -- and a second derivation of the same fact is exactly the shape of
bug this package keeps recording. So the two are held together by a round trip
rather than by inspection.
"""
import random

import pytest

from games.dissonance import engine as E
from games.dissonance.tools import cfrlab as C


def _fresh():
    return E.new_game(["a", "b"], random.Random(11), opener=0, mode="classic")


def test_a_fresh_auction_reads_as_the_forced_opening():
    assert C._live_abstract_state(_fresh()) == (0, 0, 0)


@pytest.mark.parametrize(
    "state",
    [(level, prev, holds, actor)
     for (level, prev, holds, actor) in C.states()
     if level <= C.MAXL],
)
def test_driving_to_a_state_reads_back_as_that_state(state):
    """THE ROUND TRIP. Every state the abstraction enumerates, driven to with
    real bids, must read back as itself.

    Skipping unreachable paths is NOT allowed here (this package forbids
    state-reachability skips): `_path_to` returns None for states with no path
    and `_drive_to` returns False when the denomination forever-ban blocks the
    path on this particular deal. Both are real facts about the game rather
    than gaps in the test, so they are counted and asserted on in aggregate by
    the test below.
    """
    level, prev, holds, actor = state
    path = C._path_to(level, prev, holds, actor)
    if path is None:
        return
    g = _fresh()
    if not C._drive_to(g, path):
        return
    assert C._live_abstract_state(g) == (level, prev, holds)


def test_the_round_trip_actually_reaches_most_of_the_abstraction():
    """...and the aggregate check, so the parametrised test above cannot pass
    by never driving anywhere.

    A guard that only ever hit unreachable paths would be a green tick over
    nothing -- the exact defect this package's "zero state-reachability skips"
    rule exists to prevent.
    """
    reached = total = 0
    for level, prev, holds, actor in C.states():
        if level > C.MAXL:
            continue
        total += 1
        path = C._path_to(level, prev, holds, actor)
        if path is None:
            continue
        g = _fresh()
        if not C._drive_to(g, path):
            continue
        reached += 1
        assert C._live_abstract_state(g) == (level, prev, holds)
    assert total > 50, f"the abstraction only enumerated {total} states"
    assert reached > total // 3, (
        f"only {reached} of {total} states were reachable on this deal -- "
        "the round trip is not covering the abstraction")


def test_holds_count_the_trailing_run_and_prev_is_the_level_under_it():
    """The two fields that are easy to get subtly wrong, on an explicit
    sequence rather than through the path builder."""
    g = _fresh()
    seen = []
    for want in (2, 4, 4):
        opts = E.auction_options(g)
        pick = next(((l, d) for l, d in opts["bids"] if l == want), None)
        if pick is None:
            break
        E.apply_move(g, g["seats"][g["auction"]["to_act"]],
                     {"kind": "bid", "level": pick[0], "denom": pick[1]})
        seen.append(C._live_abstract_state(g))
    assert seen == [(2, 0, 0), (4, 2, 0), (4, 2, 1)], seen


def test_a_pass_entry_in_the_log_is_not_read_as_a_bid():
    """The log's vocabulary is not the MOVE's vocabulary.

    A bid logs `{seat, level, denom}` and a pass logs `{seat, pass: True}` --
    there is no `kind` field, and the first cut of `_live_abstract_state`
    filtered on `kind == "bid"`, matched nothing, and reported the opening state
    at every node. That is a blueprint that always thinks it is opening, and
    nothing about it is loud.
    """
    g = _fresh()
    opts = E.auction_options(g)
    lvl, den = next((l, d) for l, d in opts["bids"] if l == 3)
    E.apply_move(g, g["seats"][g["auction"]["to_act"]],
                 {"kind": "bid", "level": lvl, "denom": den})
    assert C._live_abstract_state(g) == (3, 0, 0)
    E.apply_move(g, g["seats"][g["auction"]["to_act"]], {"kind": "pass"})
    log = g["auction"]["log"]
    assert any("pass" in m for m in log), "expected a pass entry in the log"
    assert all("level" in m or "pass" in m for m in log)
    # The pass settled the auction; the bid history still reads as it did.
    assert C._live_abstract_state(g) == (3, 0, 0)
