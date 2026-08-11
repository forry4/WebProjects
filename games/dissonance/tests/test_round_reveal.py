"""The scorecard's reveal: a banked round carries its own story.

The round-review modal (2026-08-11) lays a finished round out face up — both
hands, the talon, which of it the declarer was shown, and the bidding that
produced the contract. All of that is public at the round's own end, but the
over-phase view dies with the next deal; the scorecard line is what outlives
it, so the line has to carry the story itself.

The redaction half matters more than the display half: the reveal rides the
match onto the wire, and the match is shipped MID-ROUND too — so these tests
pin that only BANKED rounds carry hands, and the round being played never
does.
"""

import json
import random

import pytest

from games.dissonance import bot
from games.dissonance import engine as E


def _step(g, rng):
    """One server-shaped bot action through the single move entry point."""
    seat = E.turn_seat(g)
    assert seat is not None, "no seat on turn"
    pid = g["seats"][seat]
    kind, mv = bot.act(g, seat, rng)
    if kind == "bid":
        mv = ({"kind": "pass"} if mv.get("pass")
              else {"kind": "bid", "level": mv["level"], "denom": mv["denom"]})
    elif kind == "play":
        mv = {"kind": "play", "card": mv}
    elif kind == "swap":
        mv = {"kind": "swap", "take": mv.get("take"), "give": mv.get("give")}
    E.apply_move(g, pid, mv)


def _play_round_out(g, rng):
    guard = 0
    while g["phase"] != "over":
        guard += 1
        assert guard < 400, "round failed to finish"
        _step(g, rng)
    return g


def _to_play_phase(g, rng):
    guard = 0
    while g["phase"] != "play":
        guard += 1
        assert guard < 80, "never reached play"
        _step(g, rng)
    return g


@pytest.mark.parametrize("mode", ["classic", "minor", "skat", "dummy"])
def test_a_banked_round_carries_its_reveal_in_every_mode(mode):
    rng = random.Random(3)
    g = E.new_game(["a", "b"], random.Random(3), mode=mode)
    _play_round_out(g, rng)
    row = g["match"]["rounds"][-1]

    r = row["reveal"]
    assert isinstance(r["auction"], list) and r["auction"], \
        "the bidding that produced the contract is on the line"
    for e in r["auction"]:
        assert "seat" in e
    # The layout is on the line too, whole.
    deal = row["deal"]
    assert len(deal["hands"]) == (3 if mode == "dummy" else 2)
    seen = sorted(sum(deal["hands"], [])
                  + [c for sp in deal["piles"] for p in sp for c in p]
                  + deal["out"])
    assert seen == sorted(range(E.deck_size(mode))), "the layout is the deck"

    if mode == "dummy":
        assert r["shown"] == [] and r["swap"] == [None, None]
    elif mode == "skat" and not r["looked"]:
        pass  # a Hand game: the declarer never saw the talon
    else:
        assert len(r["shown"]) == E.N_SHOWN
    if mode == "skat":
        assert set(r["announce"]) == {"hand", "sharp", "open"}
    else:
        assert r["announce"] == {}
        assert r["looked"] is True, "classic's declarer always sees the talon"


def test_the_reveal_swap_matches_the_deal_it_sits_beside():
    """When a swap happened, the banked hands are the post-swap hands: the
    taken card sits in the declarer's banked hand, the discard in the banked
    out — so the modal can annotate the exchange without re-deriving it."""
    seen_swap = False
    for seed in range(40):
        rng = random.Random(seed)
        g = E.new_game(["a", "b"], random.Random(seed), mode="classic")
        _play_round_out(g, rng)
        row = g["match"]["rounds"][-1]
        take, give = row["reveal"]["swap"]
        if take is None:
            continue
        seen_swap = True
        decl = row["declarer"]
        assert take in row["deal"]["hands"][decl]
        assert give in row["deal"]["out"]
        assert take in row["reveal"]["shown"], "only a shown card can be taken"
        assert give not in row["deal"]["hands"][decl]
    assert seen_swap, "40 seeds must produce at least one swap (the bot swaps often)"


def test_the_mid_round_wire_never_carries_the_current_rounds_hands():
    """The match rides on every broadcast, banked reveals included. The round
    BEING PLAYED must contribute nothing to it: its snapshot lives in
    g['deal'], which view_for does not ship. Asserted against the whole
    serialized view of a real mid-round position, per the redaction doctrine."""
    rng = random.Random(5)
    g = E.new_game(["a", "b"], random.Random(5), mode="classic")
    # Bank round 1 so the match has a public reveal in it.
    _play_round_out(g, rng)
    E.next_round(g, 0, g["match"]["round"])
    # Drive round 2 to mid-play.
    _to_play_phase(g, rng)
    for _ in range(5):
        seat = E.playing_seat(g)
        E.apply_play(g, seat, E.legal_moves(g, seat)[0])

    for me in range(2):
        opp = 1 - me
        v = E.view_for(g, me)
        blob = json.dumps(v)
        assert blob, "the view must serialize"
        # Every banked line predates this round; none may name this round.
        for line in v["match"]["rounds"]:
            assert line["round"] < g["match"]["round"]
        assert "deal" not in v, "the live snapshot must never be on the wire"
        # The opponent's current hand appears in no field of the view. Card
        # ids are small ints that legitimately appear elsewhere, so assert on
        # structure: no int-list field equals the opponent's exact holding.
        opp_hand = set(g["hands"][opp])

        def walk(x):
            if isinstance(x, list) and x and all(isinstance(c, int) for c in x):
                yield set(x)
            elif isinstance(x, list):
                for y in x:
                    yield from walk(y)
            elif isinstance(x, dict):
                for y in x.values():
                    yield from walk(y)
        assert not any(s == opp_hand for s in walk(v)), \
            "some field of the mid-round view is the opponent's exact hand"


def test_a_forfeited_round_banks_neither_deal_nor_reveal():
    """An abandoned round is banked MID-PLAY — its snapshot contains live
    hands and its story never finished. Nothing of either belongs on the
    wire, which is also the pre-existing rule for `deal`."""
    rng = random.Random(7)
    g = E.new_game(["a", "b"], random.Random(7), mode="classic")
    _to_play_phase(g, rng)
    E.abandon_result(g, 0)
    row = g["match"]["rounds"][-1]
    assert row["abandoned"] is True
    assert "deal" not in row
    assert "reveal" not in row
