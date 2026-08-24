"""QUARTET -- four hands, two players, and the three cards nobody plays.

The mode's coverage is Python-only and that is the whole risk: `client_
searchable("quartet")` is False, so there is no Rust core and no parity
fixture standing behind any of this. What is here is what is checked.
"""

import json
import random

import pytest

from games.dissonance import bot as B, engine as E

MODE = "quartet"


def _deal(seed=3):
    return E.new_game(["p0", "p1"], random.Random(seed), opener=0, mode=MODE)


def _to_play(g, seed=3):
    """Deal, bid, commit and double through to trick 1."""
    rng = random.Random(seed)
    E.apply_bid(g, 0, 4, E.backed_denoms(g, 0)[0])
    E.apply_pass(g, 1)
    E.apply_commit(g, 0, g["auction"]["declarer"])
    E.apply_double(g, 1, False)
    return rng


def _play_out(g, rng, policy=None):
    while g["phase"] == "play":
        seat = E.playing_seat(g)
        moves = E.legal_moves(g, seat)
        assert moves, f"no legal move at trick {g['trick']} pos {E.to_play(g)}"
        E.apply_play(g, seat, policy(g, seat) if policy else rng.choice(moves))


# --- the deal --------------------------------------------------------------


def test_the_deal_is_four_hands_of_twelve_with_four_out():
    g = _deal()
    nhands, in_hand, n_out, ntricks, npiles = E.layout_for(MODE)
    assert (nhands, in_hand, n_out, ntricks, npiles) == (4, 12, 4, 9, 0)
    assert [len(h) for h in g["hands"]] == [12] * 4
    assert len(g["out"]) == 4
    assert all(p == [] for p in g["piles"]), "quartet deals no piles"
    # Asserted against `deck_size`, never a literal: the partition IS the deck.
    cards = [c for h in g["hands"] for c in h] + list(g["out"])
    assert sorted(cards) == list(range(E.deck_size(MODE))) == list(range(52))


def test_there_is_no_talon_and_nothing_is_ever_shown():
    """The four out-cards are pure SECRECY -- they are what stops the two
    players partitioning the deck between them, and no declarer ever sees
    them. The prize for the auction is the commit-phase swap instead."""
    g = _deal()
    assert g["shown"] == [] and g["shown_at_deal"] == []


def test_nine_tricks_leave_three_in_every_hand():
    g = _deal()
    rng = _to_play(g)
    _play_out(g, rng)
    assert g["trick"] == 9
    assert [len(h) for h in g["hands"]] == [3] * 4
    assert len(g["played"]) == 36 == 9 * 4


# --- positions, seats and the order round the table ------------------------


def test_a_player_commands_the_hand_opposite_them():
    g = _deal()
    for pos in range(4):
        assert E.side_of(g, pos) == pos % 2
    assert E.side_of(g, 0) == E.side_of(g, 2) == 0
    assert E.side_of(g, 1) == E.side_of(g, 3) == 1


def test_play_goes_round_the_table_and_alternates_between_the_players():
    g = _deal()
    rng = _to_play(g)
    while g["phase"] == "play":
        order = E.trick_order(g)
        assert len(order) == 4 and sorted(order) == [0, 1, 2, 3]
        assert order[0] == g["leader"]
        # A,B,A,B -- the alternation is the mode's central tension, since the
        # side that does NOT lead places the last card of the trick.
        sides = [E.side_of(g, p) for p in order]
        assert sides == [sides[0], 1 - sides[0], sides[0], 1 - sides[0]]
        for step, pos in enumerate(order):
            assert E.to_play(g) == pos, (g["trick"], step)
            seat = E.playing_seat(g)
            assert seat == pos % 2
            E.apply_play(g, seat, rng.choice(E.legal_moves(g, seat)))


def test_the_defender_can_never_play_a_card_from_the_declarers_hands():
    g = _deal()
    rng = _to_play(g)
    while g["phase"] == "play":
        pos = E.to_play(g)
        wrong = 1 - (pos % 2)
        assert E.legal_moves(g, wrong) == [], "a seat moved out of turn"
        seat = E.playing_seat(g)
        E.apply_play(g, seat, rng.choice(E.legal_moves(g, seat)))


def test_whoever_wins_a_trick_leads_the_next_one():
    g = _deal()
    rng = _to_play(g)
    while g["phase"] == "play":
        before = g["trick"]
        plays = []
        while g["trick"] == before and g["phase"] == "play":
            pos = E.to_play(g)
            seat = E.playing_seat(g)
            c = rng.choice(E.legal_moves(g, seat))
            plays.append((pos, c))
            E.apply_play(g, seat, c)
        win_pos, win_card = plays[0]
        for p, c in plays[1:]:
            if E.beats(win_card, c, g["trump"]):
                win_pos, win_card = p, c
        if g["phase"] == "play":
            assert g["leader"] == win_pos


# --- the auction: backed bids ---------------------------------------------


def test_a_bid_must_be_backed_by_six_cards_in_the_suit():
    g = _deal()
    for seat in (0, 1):
        held = [0] * 4
        for pos in (seat, seat + E.QUARTET_HANDS):
            for c in g["hands"][pos]:
                held[E.suit(c)] += 1
        want = [d for d in range(4) if held[d] >= E.QUARTET_BACKING]
        assert E.backed_denoms(g, seat) == want + [E.NOTRUMP]


def test_no_trump_is_always_legal_so_no_hand_is_unbiddable():
    for seed in range(60):
        g = _deal(seed)
        for seat in (0, 1):
            assert E.NOTRUMP in E.backed_denoms(g, seat)


def test_the_auction_never_offers_a_denomination_the_bidder_cannot_back():
    for seed in range(40):
        g = _deal(seed)
        backed = set(E.backed_denoms(g, 0))
        for _lvl, d in E.auction_options(g)["bids"]:
            assert d in backed


def test_an_unbacked_bid_is_refused_by_the_engine_not_only_hidden_by_the_ui():
    g = _deal()
    unbacked = [d for d in range(4) if d not in E.backed_denoms(g, 0)]
    if not unbacked:                      # this deal happens to back all four
        pytest.fail("pick a seed where a suit is unbacked")
    ok, why = E.can_bid(g, 0, 3, unbacked[0])
    assert not ok and why


def test_backing_is_counted_across_both_of_a_players_hands():
    """The gate reads 24 cards, not 12 -- which is what makes six a meaningful
    threshold (it is exactly the mean length across a player's side)."""
    g = _deal()
    seat = 0
    own = sum(1 for c in g["hands"][seat] if E.suit(c) == 0)
    other = sum(1 for c in g["hands"][seat + 2] if E.suit(c) == 0)
    assert (0 in E.backed_denoms(g, seat)) == (own + other >= E.QUARTET_BACKING)


# --- the commit phase ------------------------------------------------------


def test_the_auction_hands_over_to_the_commit_phase():
    g = _deal()
    E.apply_bid(g, 0, 4, E.backed_denoms(g, 0)[0])
    E.apply_pass(g, 1)
    assert g["phase"] == "commit"
    assert E.turn_seat(g) == g["auction"]["declarer"]


def test_the_declarer_names_which_of_their_two_hands_leads():
    for lead_choice in (0, 1):
        g = _deal()
        E.apply_bid(g, 0, 4, E.backed_denoms(g, 0)[0])
        E.apply_pass(g, 1)
        decl = g["auction"]["declarer"]
        lead = [decl, decl + E.QUARTET_HANDS][lead_choice]
        assert lead in E.commit_options(g)["leads"]
        E.apply_commit(g, decl, lead)
        E.apply_double(g, 1 - decl, False)
        assert g["leader"] == lead
        assert E.trick_order(g)[0] == lead


def test_a_player_cannot_lead_from_a_hand_they_do_not_command():
    g = _deal()
    E.apply_bid(g, 0, 4, E.backed_denoms(g, 0)[0])
    E.apply_pass(g, 1)
    decl = g["auction"]["declarer"]
    with pytest.raises(ValueError):
        E.apply_commit(g, decl, 1 - decl)
    with pytest.raises(ValueError):
        E.apply_commit(g, 1 - decl, decl)


def test_the_commit_swap_moves_one_card_each_way_between_your_own_hands():
    g = _deal()
    E.apply_bid(g, 0, 4, E.backed_denoms(g, 0)[0])
    E.apply_pass(g, 1)
    decl = g["auction"]["declarer"]
    dummy = decl + E.QUARTET_HANDS
    take, give = g["hands"][dummy][0], g["hands"][decl][0]
    E.apply_commit(g, decl, decl, take, give)
    assert take in g["hands"][decl] and take not in g["hands"][dummy]
    assert give in g["hands"][dummy] and give not in g["hands"][decl]
    assert [len(h) for h in g["hands"]] == [12] * 4, "a swap moves, never adds"
    assert g["swapped"] is True


def test_half_a_swap_is_refused_rather_than_silently_ignored():
    g = _deal()
    E.apply_bid(g, 0, 4, E.backed_denoms(g, 0)[0])
    E.apply_pass(g, 1)
    decl = g["auction"]["declarer"]
    with pytest.raises(ValueError):
        E.apply_commit(g, decl, decl, g["hands"][decl + 2][0], None)


def test_declining_the_swap_is_recorded_as_declining_it():
    g = _deal()
    E.apply_bid(g, 0, 4, E.backed_denoms(g, 0)[0])
    E.apply_pass(g, 1)
    decl = g["auction"]["declarer"]
    E.apply_commit(g, decl, decl)
    assert g["swapped"] is False


# --- scoring: the keeps ----------------------------------------------------


def test_only_an_own_hands_three_kept_cards_score():
    g = _deal()
    rng = _to_play(g)
    _play_out(g, rng)
    keeps = E.keeps_for(g)
    assert keeps == [sum(E.card_points(c) for c in g["hands"][p])
                     for p in (0, 1)]
    # ...and the dummies' three are dead, however good they are.
    assert len(keeps) == 2


def test_the_declarers_total_is_tricks_plus_their_own_keeps():
    g = _deal()
    rng = _to_play(g)
    _play_out(g, rng)
    r = g["result"]
    d = r["declarer"]
    assert r["declarer_pts"] == r["trick_pts"][d] + r["keeps"][d]
    assert r["trick_pts"] == g["pts"]


def test_the_trick_pool_is_conserved_and_the_keeps_stay_out_of_it():
    """Nine tricks: four evens at +2 against five odds at -1, so +3. `pts` is
    the TRICK total in every mode -- the keeps are added once, in `_finish`."""
    assert E.pool_for(MODE) == 3
    for seed in range(12):
        g = _deal(seed)
        rng = _to_play(g, seed)
        _play_out(g, rng)
        assert sum(g["pts"]) == E.pool_for(MODE) == 3


def test_the_nine_trick_pool_is_derived_and_not_a_thirteen_trick_constant():
    """Guards the generalisation directly: a hardcoded `6 * even - 7` returns
    classic's +5 here, and every pool assertion above would fail pointing at
    the card play instead of at this."""
    assert E.pool_for("classic") == 5
    assert E.pool_for("minor") == -1
    assert E.pool_for(MODE) == 3


# --- redaction -------------------------------------------------------------

#: Every view field that can carry a card id. Checked as a WHITELIST rather
#: than by walking the payload for small integers, because card ids run 0..51
#: and collide with levels, seats, counts and phases -- a walk that cannot tell
#: them apart has to discard its own findings to avoid false alarms, which
#: makes it no gate at all.
_CARD_FIELDS = ("hand", "mine", "out", "hands_open", "shown", "led", "played",
                "legal", "swap_take", "swap_give", "opp_hand")


def _cards_in(v):
    """Every card id reachable in a view, from the fields that hold them."""
    found = set()

    def eat(x):
        if isinstance(x, int):
            found.add(x)
        elif isinstance(x, (list, tuple)):
            for y in x:
                eat(y)
        elif isinstance(x, dict):
            for y in x.values():
                eat(y)

    for k in _CARD_FIELDS:
        eat(v.get(k))
    # the trick on the table, and the whole history, are [position, card]
    for entry in (v.get("plays") or []):
        found.add(entry[1])
    for entry in (v.get("history") or []):
        found.add(entry[1])
    for entry in (v.get("last_trick") or []):
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            found.add(entry[1])
    return found


def test_a_player_sees_their_own_two_hands_and_neither_of_the_opponents():
    """THE MODE'S CENTRAL INFORMATION DECISION. A finesse is a guess about
    WHICH of two hidden hands holds a card, so a player must face two hidden
    hands -- publishing either dummy would leave one and delete the finesse.

    Asserted against the whole serialized payload of a REAL in-progress game,
    mid-round, because the repo has paid three times for a redaction test built
    on a synthetic dict that missed a nested copy.
    """
    for seed in range(8):
        g = _deal(seed)
        rng = _to_play(g, seed)
        for _ in range(14):               # stop mid-round, cards still down
            seat = E.playing_seat(g)
            E.apply_play(g, seat, rng.choice(E.legal_moves(g, seat)))
        for me in (0, 1):
            v = E.view_for(g, me)
            json.dumps(v)          # must serialize: the wire carries this
            mine = set(g["hands"][me]) | set(g["hands"][me + 2])
            theirs = set(g["hands"][1 - me]) | set(g["hands"][(1 - me) + 2])
            secret = theirs | set(g["out"])
            entitled = mine | set(g["played"])
            seen = _cards_in(v)
            assert not (seen & secret), (
                f"seed {seed} seat {me}: leaked {sorted(seen & secret)}")
            assert seen <= entitled
            assert set(v["hand"]) == set(g["hands"][me])
            assert set(v["mine"]) == set(g["hands"][me + 2])
            assert v["out"] is None
            assert v["hands_open"] is None


def test_the_bid_pad_never_reaches_the_seat_that_is_not_bidding():
    """A BACKED bid makes the legal-bid list private, and this is the leak that
    change introduced. `auction_options` is built for whoever is to act, so
    shipping it to both seats was harmless while legality depended only on
    public state -- the standing bid and the spent denominations. Under quartet
    it depends on the bidder's 24 private cards, so the defender could read
    straight off their own pad which suits their opponent holds six of, which
    is exactly what a bid is supposed to cost something to reveal.

    Caught by reading a real `created` payload, not by a test -- which is why
    there is now a test.
    """
    for seed in range(25):
        g = _deal(seed)
        to_act = g["auction"]["to_act"]
        assert E.view_for(g, to_act)["options"] is not None
        other = E.view_for(g, 1 - to_act)
        assert other["options"] is None, "the pad leaked to the wrong seat"
        # ...and the leak it would have been is real on this deal: the two
        # seats do not back the same denominations.
        blob = json.dumps(other)
        mine = set(E.backed_denoms(g, to_act))
        theirs = set(E.backed_denoms(g, 1 - to_act))
        if mine != theirs:
            assert "bids" not in blob


def test_the_card_counts_of_every_hand_are_public():
    g = _deal()
    rng = _to_play(g)
    for _ in range(9):
        seat = E.playing_seat(g)
        E.apply_play(g, seat, rng.choice(E.legal_moves(g, seat)))
    for me in (0, 1):
        assert E.view_for(g, me)["hand_n"] == [len(h) for h in g["hands"]]


def test_everything_opens_up_once_the_round_is_over():
    g = _deal()
    rng = _to_play(g)
    _play_out(g, rng)
    for me in (0, 1):
        v = E.view_for(g, me)
        assert set(v["out"]) == set(g["out"])
        assert [sorted(h) for h in g["hands"]] == v["hands_open"]
        assert v["keeps"] == E.keeps_for(g)


def test_the_redaction_test_would_notice_a_leak():
    """Non-vacuous: a view that shipped the opponent's hands must FAIL it."""
    g = _deal()
    rng = _to_play(g)
    for _ in range(8):
        seat = E.playing_seat(g)
        E.apply_play(g, seat, rng.choice(E.legal_moves(g, seat)))
    v = E.view_for(g, 0)
    assert not (_cards_in(v) & set(g["hands"][1]))
    v["mine"] = sorted(g["hands"][1])          # the leak this guards against
    assert _cards_in(v) & set(g["hands"][1])


# --- the bot ---------------------------------------------------------------


def test_the_bot_plays_a_whole_quartet_game_in_every_phase():
    rng = random.Random(19)
    g = _deal(19)
    seen = set()
    while g["phase"] != "over":
        seat = E.turn_seat(g)
        assert seat is not None
        seen.add(g["phase"])
        kind, mv = B.act(g, seat, rng)
        assert kind is not None, f"the bot has no answer in phase {g['phase']}"
        if kind == "play":
            move = {"kind": "play", "card": mv}
        elif kind == "bid":
            move = {"kind": "pass"} if mv.get("pass") else {"kind": "bid", **mv}
        else:
            move = mv
        E.apply_move(g, g["seats"][seat], move, rng)
    assert {"auction", "commit", "double", "play"} <= seen
    assert g["result"]["mode"] == MODE


def test_the_bot_never_overtakes_its_own_side():
    """Beating a card your own other hand is already winning with spends a
    better card for nothing -- the trap dummy mode paid for first."""
    rng = random.Random(23)
    g = _deal(23)
    _to_play(g, 23)
    overtakes = 0
    while g["phase"] == "play":
        seat = E.playing_seat(g)
        pos = E.to_play(g)
        plays = g.get("plays") or []
        c = B.choose_card(g, seat)
        if plays:
            best_pos, best_card = plays[0]
            for p, card in plays[1:]:
                if E.beats(best_card, card, g["trump"]):
                    best_pos, best_card = p, card
            if (E.side_of(g, best_pos) == E.side_of(g, pos)
                    and E.beats(best_card, c, g["trump"])):
                alt = [x for x in E.legal_moves(g, seat)
                       if not E.beats(best_card, x, g["trump"])]
                if alt:
                    overtakes += 1
        E.apply_play(g, seat, c)
    assert overtakes == 0, f"{overtakes} needless overtakes of its own side"


def test_the_bot_protects_its_keeps_far_better_than_random_play():
    """The keeps are worth ~3.5 points a round and a policy blind to them
    throws that away -- measured in `tools/quartet_keeps.py` as +0.91 random
    against +4.41 protecting."""
    def run(policy):
        got = []
        for seed in range(40):
            g = _deal(500 + seed)
            rng = _to_play(g, 500 + seed)
            _play_out(g, rng, policy)
            got += E.keeps_for(g)
        return sum(got) / len(got)

    rand = run(lambda g, s: random.Random(g["trick"] * 7 + s).choice(
        E.legal_moves(g, s)))
    smart = run(lambda g, s: B.choose_card(g, s))
    assert smart > rand + 1.5, (smart, rand)


# --- persistence -----------------------------------------------------------


def test_a_quartet_round_survives_the_state_json_codec():
    from games.dissonance import main as M
    g = _deal(31)
    rng = _to_play(g, 31)
    for _ in range(11):
        seat = E.playing_seat(g)
        E.apply_play(g, seat, rng.choice(E.legal_moves(g, seat)))
    back = M._decode_state(M._encode_state(g))
    assert back == g


def test_a_quartet_deal_reads_as_current():
    g = _deal()
    assert E.deal_is_current(g)
    rng = _to_play(g)
    while g["phase"] == "play":
        assert E.deal_is_current(g)
        seat = E.playing_seat(g)
        E.apply_play(g, seat, rng.choice(E.legal_moves(g, seat)))
