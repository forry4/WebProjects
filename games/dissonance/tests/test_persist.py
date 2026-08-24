"""At-rest compaction for Dissonance.

The round-review snapshot is the one thing in this blob that grows with the
MATCH rather than with the round, so it is packed at rest -- and packing is only
safe if it is exactly reversible on a real played-out match, which is what this
asserts. Dissonance's other persistence coverage lives in ``test_skat.py``
(the ``state_json`` round-trip of a skat game).
"""

import copy
import random

from games.dissonance import bot
from games.dissonance import engine as E
from games.dissonance import persist

def test_a_reviewable_match_round_trips_through_compaction():
    """The review snapshots are packed at rest and must come back identical.

    Both the live round's and every banked round's, which is why `_map_deals`
    reaches both: the live one is a single round, the banked ones are the part
    that accumulates, and a packer that reached only one would leave the growth
    exactly where it was.
    """

    rng = random.Random(5)
    g = E.new_game(["a", "b"], random.Random(5))
    rounds = 0
    while rounds < 3 and not E.is_over(g):
        guard = 0
        while g["phase"] != "over":
            guard += 1
            assert guard < 300
            seat = E.turn_seat(g)
            ph = g["phase"]
            if ph == "auction":
                _, mv = bot.act(g, seat, rng)
                if mv.get("pass"):
                    E.apply_pass(g, seat)
                else:
                    E.apply_bid(g, seat, mv["level"], mv["denom"])
            elif ph == "swap":
                _, mv = bot.act(g, seat, rng)
                E.apply_swap(g, seat, mv.get("take"), mv.get("give"))
            elif ph == "double":
                E.apply_double(g, seat, bot.choose_double(g, seat))
            else:
                E.apply_play(g, seat, bot.choose_card(g, seat))
        rounds += 1
        if E.is_over(g):
            break
        E.next_round(g, 0, g["match"]["round"])

    banked = [r for r in g["match"]["rounds"] if "deal" in r]
    assert banked, "no round banked a deal -- the test exercised nothing"

    before = copy.deepcopy(g)
    packed = persist.compact_state({"game": copy.deepcopy(g)})
    # It really is packed, not merely passed through.
    assert "c" in packed["game"]["match"]["rounds"][0]["deal"]
    assert "hands" not in packed["game"]["match"]["rounds"][0]["deal"]

    after = persist.expand_state(packed)["game"]
    after.pop("played", None)
    before.pop("played", None)
    assert after == before


def test_a_blob_packed_before_the_string_encoding_still_expands():
    """Rows already at rest carry `c` as an int list and `terms` verbatim.

    The unpacker discriminates on shape rather than on a version bump, so those
    rows must keep loading forever -- there is no migration pass to fix them.
    """
    old_style = {
        "c": list(range(32)),
        "trump": 2,
        "leader": 1,
        "terms": {"declarer": 1, "target": 3, "make": 9},
    }
    d = persist._unpack_deal(dict(old_style))
    assert d["hands"] == [list(range(7)), list(range(7, 14))]
    assert d["piles"][0][0] == [14, 15]
    assert d["out"] == list(range(26, 32))
    assert d["terms"] == old_style["terms"], "verbatim terms must survive"
    assert d["trump"] == 2 and d["leader"] == 1


def test_an_unrecognised_deck_width_is_left_verbose_not_corrupted():
    # Fail OPEN: a deal this encoding does not recognise must come through
    # unshrunk rather than mangled -- an unreadable save is the worse failure.
    weird = {"hands": [[40], [1]], "piles": [[[2, 3]] * 3] * 2, "out": [9],
             "trump": 0, "leader": 0, "terms": {"target": 1}}
    packed = persist._pack_deal(dict(weird))
    assert packed == weird, "an unencodable deal must pass through untouched"
