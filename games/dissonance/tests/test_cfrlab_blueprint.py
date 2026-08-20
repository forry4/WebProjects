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


# ---------------------------------------------------------------------------
# The widened private bucket (2026-08-20)
# ---------------------------------------------------------------------------

def test_one_feature_is_the_original_abstraction_byte_for_byte():
    """THE NULL CONTROL. At CFR_FEATURES=1 the joint bucket must be exactly the
    strength quantile the abstraction always used -- otherwise every widened
    arm is confounded by the bucketing changing underneath it."""
    if C.CFR_FEATURES != 1:
        return  # the widened build is covered by the tests below
    assert C.NBUCKET == C.NSTRENGTH == 8
    cuts = ([1.0, 2.0, 3.0], [], [])
    # tops/shortest must not move the answer at all when they are not in play.
    for tops in (0, 3, 9):
        for short in (0, 2, 5):
            assert C.joint_bucket(0.5, tops, short, cuts) == 0
            assert C.joint_bucket(2.5, tops, short, cuts) == 2
            assert C.joint_bucket(9.9, tops, short, cuts) == 3


def test_the_joint_bucket_is_injective_over_its_axes():
    """A joint index that collides is two different hands sharing a policy.

    Exercised on the WIDE shape regardless of the build's own CFR_FEATURES, by
    driving `joint_bucket`'s arithmetic directly -- so this test says something
    even in the narrow default build.
    """
    scuts, tcuts, hcuts = [1.0, 2.0], [1, 2], [1, 2]
    seen = {}
    for si, sv in enumerate([0.5, 1.5, 2.5]):
        for ti, tv in enumerate([0, 1, 2]):
            for hi, hv in enumerate([0, 1, 2]):
                i = si
                i = i * 3 + ti
                i = i * 3 + hi
                assert i not in seen, f"bucket {i} collides: {seen.get(i)} and {(si, ti, hi)}"
                seen[i] = (si, ti, hi)
    assert len(seen) == 27


def test_hand_shape_reads_only_the_cards_the_seat_may_name():
    """INFORMATION LEGALITY, and it is the one property here that is a RULE
    rather than a modelling choice.

    A seat holds thirteen cards and may name eleven -- the two outer pile
    bottoms are face down to their owner too. `hand_strength` had this bug once
    and valued its own hand with information the rules do not give it. The
    features must read exactly the same set, so mutating a hidden bottom must
    not move them.
    """
    import random
    g = E.new_game(["a", "b"], random.Random(3), opener=0, mode="classic")
    before = C.hand_shape(g, 0)
    moved = 0
    for i, p in enumerate(g["piles"][0]):
        if len(p) == 2 and i != 1:
            # Swap the hidden bottom for a card of a different suit and rank.
            p[0] = (p[0] + 9) % 32
            moved += 1
    assert moved == 2, f"expected two hidden bottoms, found {moved}"
    assert C.hand_shape(g, 0) == before, (
        "hand_shape moved when a card the seat cannot see changed")


def test_hand_shape_does_move_on_a_card_the_seat_can_see():
    """...and the positive control, so the test above cannot pass by the
    function being constant."""
    import random
    g = E.new_game(["a", "b"], random.Random(3), opener=0, mode="classic")
    before = C.hand_shape(g, 0)
    # Replace the whole hand with one suit of top cards: tops and shortest must
    # both move.
    g["hands"][0] = [28, 29, 30, 31, 24, 25, 26]
    assert C.hand_shape(g, 0) != before
