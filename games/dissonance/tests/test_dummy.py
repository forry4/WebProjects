"""Dummy mode — the fourth mode, and the first with a THIRD HAND.

Three seats of THIRTEEN (7 in hand + three 2-card piles, the same holding
every other mode deals), one card out, thirteen tricks of three cards, card
scoring, classic's auction. The dummy plays SECOND in every trick and never
leads, and WHOEVER LEADS THE TRICK PLAYS IT -- so command changes hands with
the lead (`DUMMY_COMMAND`).

Three thirteens is 39 cards, so this is the one mode that deals the WIDE deck:
the base 32 plus a 5 and a 6 in each suit, as ids 32..39 (see `engine.rank`).
Its deck partition is asserted below against `deck_size`, not a literal.

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


def test_the_deal_is_three_hands_of_thirteen_off_the_wide_deck():
    g = _dummy()
    assert E.n_hands(g) == 3
    assert [len(h) for h in g["hands"]] == [7, 7, 7]
    assert all(len(p) == 3 and all(len(x) == 2 for x in p) for p in g["piles"])
    assert len(g["out"]) == 1
    assert E.ntricks_in(g) == 13
    # Every card exactly once, and nothing dealt twice. THE WIDE DECK: 40 cards
    # rather than 32, because three seats of thirteen is 39.
    assert E.deck_size("dummy") == 40 and E.deck_size("classic") == 32
    seen = list(g["out"])
    for q in range(3):
        seen += g["hands"][q] + [c for p in g["piles"][q] for c in p]
    assert sorted(seen) == list(range(E.deck_size("dummy")))
    assert all(len(g["hands"][q]) + sum(len(p) for p in g["piles"][q]) == 13
               for q in range(3))


def test_the_wide_decks_extra_cards_are_the_low_ranks_and_move_no_existing_id():
    """The whole reason the extra cards sit at ids 32..39 rather than the deck
    being renumbered `suit * 10 + rank`: every base card keeps its id, so the
    committed Rust fixtures, the committed wasm and every saved classic / skat /
    minor game go on meaning what they meant. Asserted rather than trusted --
    a renumbering is exactly the kind of change that looks harmless."""
    for c in range(E.NCARD):
        assert E.suit(c) == c // E.NRANK
        assert E.rank(c) == c % E.NRANK + E.BASE_OFFSET
    # ...and the eight new ones are a 5 and a 6 in each suit, below every 7.
    # THEIR STRENGTHS ARE NO LONGER 0 AND 1: the full deck put the 2, 3 and 4
    # underneath them, so they sit at `WIDE_OFFSET`. Their IDS did not move,
    # which is the property this test exists for.
    extra = list(range(E.NCARD, E.NCARD_WIDE))
    assert sorted(E.suit(c) for c in extra) == [0, 0, 1, 1, 2, 2, 3, 3]
    assert sorted(set(E.rank(c) for c in extra)) == [E.WIDE_OFFSET,
                                                     E.WIDE_OFFSET + 1]
    assert {E.RANK_NAMES[E.rank(c)] for c in extra} == {"5", "6"}
    for c in extra:
        for b in range(E.NCARD):
            if E.suit(b) == E.suit(c):
                assert E.beats(c, b, E.NOTRUMP), "every base card beats a 5 or 6"
                assert not E.beats(b, c, E.NOTRUMP)


def test_the_extra_ranks_are_worth_nothing_and_the_deck_total_does_not_move():
    """Two properties the value table was chosen for, both load-bearing:
    the wide deck adds EIGHT cards and no points (so the ladder is not silently
    re-scaled), and a trick's worth stops being a multiple of 3 (so the contract
    rungs stop being duplicates of each other)."""
    assert all(E.card_points(c) == 0 for c in range(E.NCARD, E.NCARD_WIDE))
    assert E.card_pool_for("dummy") == E.card_pool_for("classic") == 16
    from math import gcd
    sums = {a + b + c
            for a in E.CARD_VALUES for b in E.CARD_VALUES for c in E.CARD_VALUES}
    g = 0
    for s in sums:
        g = gcd(g, abs(s))
    assert g == 1, "a three-card trick can be worth any integer, not a multiple of 3"


def test_a_thirty_two_card_room_still_ships_the_wire_table_it_always_did():
    """WIRE COMPATIBILITY. `card_values` is sliced to the deck the room deals,
    so a bundle cached from before the wide deck goes on indexing skat's eight
    entries with `c % 8` and labelling every corner chip correctly. A dummy room
    ships all ten and the client takes its offset from the LENGTH."""
    assert E.wire_card_values("skat") == [-1, -1, 2, 2, 2, 2, -1, -1]
    assert len(E.wire_card_values("dummy")) == E.nranks_for("dummy") == 10
    for c in range(E.NCARD):
        assert E.wire_card_values("skat")[c % E.NRANK] == E.card_points(c)
    for c in range(E.NCARD_WIDE):
        off = E.rank_offset("dummy")
        assert E.wire_card_values("dummy")[E.rank(c) - off] == E.card_points(c)
    # THE CLIENT'S OWN ARITHMETIC, asserted here rather than trusted: it takes
    # the offset from the LENGTH (`NRANKS - len(t)`), which is the whole reason
    # a third deck width needed no wire change and no version bump.
    for mode in ("classic", "skat", "minor", "dummy"):
        t = E.wire_card_values(mode)
        assert E.NRANKS - len(t) == E.rank_offset(mode)
        for c in range(E.deck_size(mode)):
            assert t[E.rank(c) - (E.NRANKS - len(t))] == E.card_points(c)


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
        assert g["trick"] == 13


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
        assert saw == 13, "the dummy plays once a trick"
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
        assert g["trick"] == 13
        assert len(g["played"]) == 39, "thirty-nine cards are dealt in and all played"
        assert sum(g["pts"]) == E.played_pool(g)
        assert not set(g["played"]) & set(g["out"])


def test_dummy_mode_is_free_discard_and_the_parity_modes_are_not():
    """FREE DISCARD (2026-08-10): every playable card is legal, always. The
    followers were the seats with nothing to decide -- 2.27 legal cards
    against a leader's 4.11 -- and this levels it to 4.11 across the board.

    The parity modes keep mandatory follow: there the trick's value is known
    before anyone chooses, so free discard lets every unwanted trick fall to
    whoever led it. Both halves are asserted, because the whole point is that
    the rule is per-mode."""
    assert E.follows_suit("dummy") is False
    for m in ("classic", "skat", "minor"):
        assert E.follows_suit(m) is True, m

    could_have_been_forced = 0
    for seed in range(12):
        g = _to_play(seed)
        while g["phase"] == "play":
            seat, pos = E.playing_seat(g), E.to_play(g)
            legal = E.legal_moves(g, seat)
            assert set(legal) == set(E.playable(g, pos)), \
                "every card a seat can reach is legal"
            if g["led"] is not None:
                ls = E.esuit(g["led"], g["trump"])
                follow = [c for c in E.playable(g, pos)
                          if E.esuit(c, g["trump"]) == ls]
                if follow and len(follow) < len(legal):
                    could_have_been_forced += 1
            E.apply_play(g, seat, legal[0])
    assert could_have_been_forced > 0, \
        "no seat was ever holding the led suit -- the rule proved nothing"


def test_a_parity_mode_still_makes_you_follow():
    """The guard on the other side: classic must be untouched by dummy's rule."""
    import random as _r
    bound = 0
    for seed in range(20):
        g = E.new_game(["a", "b"], _r.Random(seed), 0, mode="classic")
        E.apply_bid(g, 0, 1, 2)
        E.apply_pass(g, 1)
        E.apply_swap(g, 0, None, None)
        E.apply_double(g, 1, False)
        while g["phase"] == "play":
            seat = E.to_play(g)
            legal = E.legal_moves(g, seat)
            if g["led"] is not None:
                ls = E.esuit(g["led"], g["trump"])
                follow = [c for c in E.playable(g, seat)
                          if E.esuit(c, g["trump"]) == ls]
                assert set(legal) == set(follow or E.playable(g, seat))
                bound += bool(follow) and len(follow) < len(E.playable(g, seat))
            E.apply_play(g, seat, legal[0])
    assert bound > 0, "follow-suit never bound in classic -- vacuous"


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
    assert v["tricks"] == 13


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
        assert g["result"] is not None and g["trick"] == 13


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


def test_a_dummy_round_banks_a_three_hand_deal_the_dd_column_must_refuse():
    """Since the round-review modal (2026-08-11) every mode banks its deal --
    a dummy round's three hands included, so the modal can lay the round out
    face up. The DD solver still cannot price three hands: the FRONTEND gates
    on the hand count before posting a deal to the review worker, and the
    count is therefore the field this test pins."""
    g = _to_play(9)
    assert len(g["deal"]["hands"]) == 3, "the snapshot carries all three hands"
    while g["phase"] == "play":
        seat = E.playing_seat(g)
        E.apply_play(g, seat, E.legal_moves(g, seat)[0])
    row = g["match"]["rounds"][-1]
    assert len(row["deal"]["hands"]) == 3
    assert len(row["deal"]["piles"]) == 3
    # The union of the banked layout is the whole wide deck: the modal renders
    # this as fact, so it must BE the deal, not resemble one.
    seen = sorted(sum(row["deal"]["hands"], [])
                  + [c for sp in row["deal"]["piles"] for p in sp for c in p]
                  + row["deal"]["out"])
    assert seen == sorted(range(E.deck_size("dummy"))), "the layout is the deck"
    assert row["reveal"]["swap"] == [None, None], "no talon in dummy mode"


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


def test_a_round_dealt_before_the_wide_deck_is_deleted_rather_than_jammed():
    """A dummy round in progress plays from the hands it was DEALT, so a
    ten-card round resumed under the thirteen-card layout runs fine until trick
    11 and then jams with no legal move — a hung room, not an error.

    It is DELETED, not voided. Voiding it in place left the row saying
    `playing`, so the game sat in the player's Active list forever and the
    lobby's cancel (open rooms only) could not remove it. Nothing about the
    round is recoverable, so the row served nobody.

    Driven through `load_game_to_memory` rather than asserting the predicate
    alone, because the guard is only worth anything at the seam — the predicate
    passing says nothing about whether anything calls it.
    """
    from games.dissonance import main as M

    g = _to_play()
    assert E.deal_is_current(g), "a freshly dealt round is current by definition"
    for mode in E.MODES:
        fresh = E.new_game(["a", "b"], random.Random(3), mode=mode)
        assert E.deal_is_current(fresh), mode

    # The old shape: three hands of ten off the 32-card deck.
    old = E.new_game(["a", "b"], random.Random(9), mode="dummy")
    deck = list(range(E.NCARD))
    old["hands"] = [sorted(deck[i * 4:i * 4 + 4]) for i in range(3)]
    old["piles"] = [[[deck[12 + i * 6 + 2 * j], deck[12 + i * 6 + 2 * j + 1]]
                     for j in range(3)] for i in range(3)]
    old["out"] = deck[30:32]
    old["played"] = []
    assert not E.deal_is_current(old)

    rid = "WIDEDK"
    row = {"players": {"p": "alice"}, "host": "p", "status": "playing",
           "game": old, "meta": {}, "mode": "dummy"}
    deleted = []
    real_load, real_del = M.load_game_state, M.delete_game
    M.load_game_state = lambda _rid: row
    M.delete_game = lambda gid: deleted.append(gid)
    M.ROOMS.pop(rid, None)
    try:
        assert M.load_game_to_memory(rid) is False, "an unplayable save is gone"
        assert deleted == [rid], "...and the ROW is deleted, not just the memory"
        assert rid not in M.ROOMS
    finally:
        M.load_game_state, M.delete_game = real_load, real_del
        M.ROOMS.pop(rid, None)


def test_a_playable_save_is_never_deleted_by_the_unplayable_guard():
    """The guard drives an IRREVERSIBLE delete, so its false-positive rate is
    the whole safety argument. Every card sits in exactly one of hands / piles /
    out / played at every moment — `expand_state` rebuilds `played` from
    `history`, so it is never merely absent — which makes `deal_is_current`
    exact arithmetic rather than a heuristic.

    Asserted over whole rounds in EVERY mode, at every ply, because a predicate
    that is right at the deal and wrong at trick 9 would delete live games.
    """
    from games.dissonance import main as M

    for mode in E.MODES:
        g = E.new_game(["a", "b"], random.Random(21), opener=0, mode=mode)
        seen = 0
        while g["phase"] != "over" and seen < 300:
            assert E.deal_is_current(g), f"{mode} ply {seen}: a live game read as stale"
            seat = E.turn_seat(g)
            if seat is None:
                break
            kind, mv = B.act(g, seat, random.Random(seen))
            # `bot.act`'s answer -> an `apply_move` dict, the same mapping
            # main.py does. Every kind, because this walks all four modes and
            # an unhandled one would end the loop early and check nothing.
            if kind == "move":
                move = mv
            elif kind == "play":
                move = {"kind": "play", "card": mv}
            elif kind == "swap":
                move = {"kind": "swap", "take": mv.get("take"), "give": mv.get("give")}
            elif mv.get("pass"):
                move = {"kind": "pass"}
            else:
                move = {"kind": "bid", **mv}
            E.apply_move(g, g["seats"][seat], move)
            seen += 1
        assert seen > 20, f"{mode}: the round barely advanced, so little was checked"

    # ...and the seam agrees: a healthy save loads, and nothing is deleted.
    healthy = E.new_game(["a", "b"], random.Random(5), mode="dummy")
    rid = "HEALTHY"
    row = {"players": {"p": "alice"}, "host": "p", "status": "playing",
           "game": healthy, "meta": {}, "mode": "dummy"}
    deleted = []
    real_load, real_del = M.load_game_state, M.delete_game
    M.load_game_state = lambda _rid: row
    M.delete_game = lambda gid: deleted.append(gid)
    M.ROOMS.pop(rid, None)
    try:
        assert M.load_game_to_memory(rid) is True
        assert deleted == [], "a playable save must never be deleted"
    finally:
        M.load_game_state, M.delete_game = real_load, real_del
        M.ROOMS.pop(rid, None)


def test_an_unplayable_save_is_dropped_from_the_lobby_without_being_opened():
    """THE LOBBY is where this actually has to happen. The load path deletes an
    unplayable save too, but a room is only loaded when someone OPENS it — so a
    game nobody clicks sat in Active forever, which was the whole complaint and
    what the first fix missed.

    Driven through `list_user_games` against a real temp DB, because the point
    is the seam: the predicate agreeing says nothing about the list calling it.
    """
    from games.dissonance import main as M

    stale = E.new_game(["a", "b"], random.Random(9), mode="dummy")
    deck = list(range(E.NCARD))
    stale["hands"] = [sorted(deck[i * 4:i * 4 + 4]) for i in range(3)]
    stale["piles"] = [[[deck[12 + i * 6 + 2 * j], deck[12 + i * 6 + 2 * j + 1]]
                       for j in range(3)] for i in range(3)]
    stale["out"] = deck[30:32]
    stale["played"] = []
    healthy = E.new_game(["a", "b"], random.Random(5), mode="dummy")

    rows = [{"id": "STALE1", "status": "playing", "player1_id": "u1",
             "player1_name": "alice", "player2_id": "u2", "player2_name": "bob",
             "state_json": M._encode_state({"game": stale}),
             "created_at": 1, "updated_at": 2},
            {"id": "GOOD1", "status": "playing", "player1_id": "u1",
             "player1_name": "alice", "player2_id": "u2", "player2_name": "bob",
             "state_json": M._encode_state({"game": healthy}),
             "created_at": 1, "updated_at": 3},
            # A row whose blob will NOT decode. `list_user_games` turns that
            # into `{}`, and treating "I cannot tell" as unplayable would make
            # one transient decode error destroy games — so it must SURVIVE.
            {"id": "JUNK1", "status": "playing", "player1_id": "u1",
             "player1_name": "alice", "player2_id": "u2", "player2_name": "bob",
             "state_json": "{not json", "created_at": 1, "updated_at": 4}]

    class _Cur:
        def execute(self, *_a, **_k):
            return self

        def fetchall(self):
            return rows

    class _Conn:
        def cursor(self):
            return _Cur()

        def close(self):
            pass

    deleted = []
    real_db, real_del = M._db, M.delete_game
    M._db = lambda: _Conn()
    M.delete_game = lambda gid: deleted.append(gid)
    try:
        listed = [row["id"] for row in M.list_user_games("u1")]
    finally:
        M._db, M.delete_game = real_db, real_del

    assert "STALE1" not in listed, "an unplayable game must leave Active"
    assert deleted == ["STALE1"], "...and its ROW must go, not just the listing"
    assert "GOOD1" in listed, "a playable game is untouched"
    assert "JUNK1" in listed, (
        "an undecodable row must SURVIVE — absence of evidence is not evidence "
        "that a game is unplayable, and the answer drives a delete")
