"""Dummy mode — the fourth mode, and the first with a THIRD HAND.

Three seats of ten (4 in hand + three 2-card piles), two cards out, ten tricks
of three cards, card scoring, classic's auction. The dummy plays SECOND in
every trick and never leads, and WHOEVER LEADS THE TRICK PLAYS IT -- so
command changes hands with the lead (`DUMMY_COMMAND`).

The Rust core is two-seat, so NONE of this is covered by the parity fixtures --
these tests are the only thing standing behind the mode's card play.
"""

from __future__ import annotations

import json
import random

from games.dissonance import bot as B
from games.dissonance import engine as E


def _dummy(seed: int = 1, opener: int = 0) -> dict:
    return E.new_game(["alice", "bob"], random.Random(seed), opener, mode="dummy")


def _to_play(seed: int = 1, level: int = 3, denom: int = 2) -> dict:
    g = _dummy(seed)
    E.apply_bid(g, 0, level, denom)
    E.apply_pass(g, 1)
    E.apply_double(g, 1, False)
    return g


def test_the_deal_is_three_hands_of_ten_with_two_out():
    g = _dummy()
    assert E.n_hands(g) == 3
    assert [len(h) for h in g["hands"]] == [4, 4, 4]
    assert all(len(p) == 3 and all(len(x) == 2 for x in p) for p in g["piles"])
    assert len(g["out"]) == 2
    assert E.ntricks_in(g) == 10
    # Every card exactly once, and nothing dealt twice.
    seen = list(g["out"])
    for q in range(3):
        seen += g["hands"][q] + [c for p in g["piles"][q] for c in p]
    assert sorted(seen) == list(range(E.NCARD))
    assert all(len(g["hands"][q]) + sum(len(p) for p in g["piles"][q]) == 10
               for q in range(3))


def test_there_is_no_talon_and_the_auction_runs_straight_into_the_double():
    g = _dummy()
    assert g["shown"] == [] and g["shown_at_deal"] == []
    E.apply_bid(g, 0, 2, 1)
    E.apply_pass(g, 1)
    assert g["phase"] == "double", "no swap phase: the prize is the dummy"
    E.apply_double(g, 1, False)
    assert g["phase"] == "play"


def test_the_dummy_plays_second_every_trick_and_never_leads():
    """The order rule, over whole rounds: leader, dummy, then the real player
    who did not lead -- so the last word is always a human's, whoever led."""
    for seed in range(15):
        g = _to_play(seed)
        while g["phase"] == "play":
            order = E.trick_order(g)
            assert order[1] == E.DUMMY_POS, "the dummy is always second"
            assert order[0] != E.DUMMY_POS, "the dummy never leads"
            assert sorted(order) == [0, 1, 2], "every hand plays once a trick"
            for _ in range(3):
                seat = E.playing_seat(g)
                E.apply_play(g, seat, E.legal_moves(g, seat)[0])
        assert g["trick"] == 10


def test_the_leader_acts_for_the_dummy_and_nobody_else_can():
    """`DUMMY_COMMAND = "leader"`: the third hand belongs to whoever leads the
    trick, so it changes hands with the lead. Measured reason -- under the
    first rule (always the declarer) the declarer banked 69% of the pool
    before deciding anything; contesting it drops that to 57%."""
    both = set()
    for seed in (4, 5, 6):
        g = _to_play(seed)
        saw = 0
        while g["phase"] == "play":
            pos, seat = E.to_play(g), E.playing_seat(g)
            if pos == E.DUMMY_POS:
                saw += 1
                lead = g["leader"]
                assert seat == lead, "the dummy's turn belongs to the leader"
                assert E.legal_moves(g, 1 - lead) == [], "nobody else may play it"
                assert E.turn_pid(g) == g["seats"][lead]
                both.add(lead)
            E.apply_play(g, seat, E.legal_moves(g, seat)[0])
        assert saw == 10, "the dummy plays once a trick"
    assert both == {0, 1}, "command never actually changed hands"


def test_a_trick_the_dummy_takes_scores_for_whoever_commanded_it():
    """A dummy trick pays the seat that played it -- the trick's LEADER -- and
    leaves the lead with them, so command persists until someone takes it."""
    took = 0
    for seed in range(25):
        g = _to_play(seed)
        while g["phase"] == "play":
            lead = g["leader"]
            before = list(g["pts"])
            plays = []
            for _ in range(3):
                seat = E.playing_seat(g)
                c = E.legal_moves(g, seat)[-1]
                plays.append([E.to_play(g), c])
                E.apply_play(g, seat, c)
            win = plays[0]
            for p in plays[1:]:
                if E.beats(win[1], p[1], g["trump"]):
                    win = p
            v = sum(E.card_points(c) for _, c in plays)
            side = lead if win[0] == E.DUMMY_POS else win[0]
            assert g["pts"][side] - before[side] == v, "the trick paid its cards"
            assert sum(g["pts"]) - sum(before) == v, "nobody else was paid"
            if g["phase"] == "play":
                assert g["leader"] != E.DUMMY_POS
                if win[0] == E.DUMMY_POS:
                    took += 1
                    assert g["leader"] == lead, \
                        "a dummy trick leaves the lead where it was"
                else:
                    assert g["leader"] == win[0]
    assert took > 0, "the dummy never won a trick -- the rule is untested"


def test_a_completed_round_conserves_the_deal_pool():
    for seed in range(20):
        g = _to_play(seed)
        while g["phase"] == "play":
            seat = E.playing_seat(g)
            E.apply_play(g, seat, E.legal_moves(g, seat)[0])
        assert g["trick"] == 10
        assert len(g["played"]) == 30, "thirty cards are dealt in and all played"
        assert sum(g["pts"]) == E.played_pool(g)
        assert not set(g["played"]) & set(g["out"])


def test_follow_suit_still_binds_all_three_hands():
    for seed in range(12):
        g = _to_play(seed)
        while g["phase"] == "play":
            seat, pos = E.playing_seat(g), E.to_play(g)
            legal = E.legal_moves(g, seat)
            if g["led"] is not None:
                ls = E.esuit(g["led"], g["trump"])
                follow = [c for c in E.playable(g, pos)
                          if E.esuit(c, g["trump"]) == ls]
                assert set(legal) == set(follow or E.playable(g, pos))
            else:
                assert set(legal) == set(E.playable(g, pos))
            E.apply_play(g, seat, legal[0])


def test_the_view_opens_the_dummys_hand_but_not_its_outer_piles():
    """The dummy is OPEN, not solved: both players read its hand, and its
    outer pile bottoms are hidden from everyone including the declarer."""
    g = _to_play(6)
    for seat in (0, 1):
        v = E.view_for(g, seat)
        assert v["dummy"] == sorted(g["hands"][E.DUMMY_POS]), \
            "both players see the dummy's hand"
        assert v["dummy_seat"] == E.side_of(g, E.DUMMY_POS), \
            "the view names whoever commands the dummy right now"
        assert len(v["piles"]) == 3
        row = v["piles"][E.DUMMY_POS]
        assert row[0]["under"] is None and row[2]["under"] is None, \
            "the dummy's outer bottoms are hidden from everyone"
        assert row[1]["under"] == g["piles"][E.DUMMY_POS][1][0], \
            "...and its middle bottom is face up, like anyone's"


def test_the_view_still_hides_the_opponents_hand():
    """A third OPEN hand must not have opened the other two. Asserted against
    the SERIALISED payload, per the nested-snapshot lesson."""
    g = _to_play(7)
    v = E.view_for(g, 0)
    assert v["opp_hand"] is None
    assert v["hand"] == sorted(g["hands"][0])
    assert v["opp_hand_n"] == len(g["hands"][1])
    assert v["out"] is None, "the out-cards stay secret until the end"
    # The opponent's hand must not reach the wire by any other route.
    blob = json.loads(json.dumps(v))
    assert blob["dummy"] == sorted(g["hands"][E.DUMMY_POS])
    assert sorted(g["hands"][1]) != blob["dummy"], "seat 1 is not the dummy"


def test_the_view_names_the_position_and_the_player_separately():
    g = _to_play(8)
    decl = g["auction"]["declarer"]
    seat = E.playing_seat(g)
    E.apply_play(g, seat, E.legal_moves(g, seat)[0])
    assert E.to_play(g) == E.DUMMY_POS
    v = E.view_for(g, decl)
    assert v["to_play"] == E.DUMMY_POS, "the POSITION on turn"
    assert v["turn_seat"] == decl, "...and the PLAYER who acts for it"
    assert len(v["plays"]) == 1 and v["plays"][0][0] != E.DUMMY_POS
    assert v["tricks"] == 10


def test_the_bot_plays_every_hand_and_finishes_a_round():
    rng = random.Random(5)
    for seed in range(10):
        g = _dummy(seed)
        guard = 0
        while g["phase"] != "over":
            seat = E.turn_seat(g)
            kind, mv = B.act(g, seat, rng)
            if kind == "play":
                move = {"kind": "play", "card": mv}
            elif kind == "bid":
                move = {"kind": "pass"} if mv.get("pass") else {"kind": "bid", **mv}
            else:
                move = mv
            E.apply_move(g, g["seats"][seat], move)
            guard += 1
            assert guard < 200
        assert g["result"] is not None and g["trick"] == 10


def test_the_bot_does_not_overtake_its_own_dummy():
    """The mechanic's first trap: with the declarer's own card already
    winning, beating it with the dummy wins nothing and spends a better
    card. It MAY overtake to add value -- what it must not do is overtake
    with a card worth less than the duck it had."""
    checked = 0
    for seed in range(30):
        g = _to_play(seed, level=3, denom=E.NOTRUMP)
        while g["phase"] == "play":
            pos, seat = E.to_play(g), E.playing_seat(g)
            if pos == E.DUMMY_POS and g["plays"] and g["plays"][0][0] == g["leader"]:
                led = g["plays"][0][1]
                legal = E.legal_moves(g, seat)
                wins = [c for c in legal if E.beats(led, c, g["trump"])]
                ducks = [c for c in legal if not E.beats(led, c, g["trump"])]
                if wins and ducks:
                    pick = B.choose_card(g, seat)
                    if pick in wins:
                        assert E.card_points(pick) >= max(
                            E.card_points(d) for d in ducks), \
                            "overtook its own winner with a worse card"
                    checked += 1
            E.apply_play(g, seat, B.choose_card(g, seat))
    assert checked > 0, "the position never arose -- the test proves nothing"


def test_dummy_mode_is_card_scored_and_not_client_searchable():
    assert E.uses_card_points("dummy") is True
    assert E.pool_for("dummy") is None
    assert E.has_dummy("dummy") and not E.has_dummy("skat")
    # The Rust core is two-seat, so the browser must never be armed here.
    assert E.client_searchable("dummy") is False
    for m in ("classic", "skat", "minor"):
        assert E.client_searchable(m) is True
        assert E.has_dummy(m) is False
        assert E.layout_for(m)[0] == 2


def test_no_round_review_is_stored_for_a_dummy_round():
    """The DD column is an exact solve and the solver cannot see three hands,
    so a dummy round banks no deal rather than a snapshot nothing can price."""
    g = _to_play(9)
    assert "deal" not in g
    while g["phase"] == "play":
        seat = E.playing_seat(g)
        E.apply_play(g, seat, E.legal_moves(g, seat)[0])
    row = g["match"]["rounds"][-1]
    assert "deal" not in row


def test_a_dummy_round_survives_the_persistence_round_trip():
    """History records POSITIONS (0, 1, or the dummy's 2), which does not fit
    the one seat bit the packer has -- so a 3-seat history stays verbose and
    `expand_state` discriminates on shape."""
    from games.dissonance import persist
    g = _to_play(11)
    for _ in range(9):
        seat = E.playing_seat(g)
        E.apply_play(g, seat, E.legal_moves(g, seat)[0])
    assert any(h[0] == E.DUMMY_POS for h in g["history"]), "the dummy played"
    packed = persist.compact_state({"game": g, "status": "playing"})
    assert isinstance(packed["game"]["history"][0], list), "left verbose"
    back = persist.expand_state(packed)
    assert back["game"]["history"] == g["history"]
    assert back["game"]["played"] == g["played"]
    assert back["game"]["plays"] == g["plays"]


def test_a_two_seat_history_is_still_packed():
    """...and the two-seat modes must not have lost their packing to it."""
    from games.dissonance import persist
    g = E.new_game(["a", "b"], random.Random(2), 0, mode="classic")
    E.apply_bid(g, 0, 1, 0)
    E.apply_pass(g, 1)
    E.apply_swap(g, 0, None, None)
    E.apply_double(g, 1, False)
    for _ in range(6):
        seat = E.to_play(g)
        E.apply_play(g, seat, E.legal_moves(g, seat)[0])
    packed = persist.compact_state({"game": g})
    assert isinstance(packed["game"]["history"][0], int), "still packed"
    assert persist.expand_state(packed)["game"]["history"] == g["history"]
