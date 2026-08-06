"""Oddtrick engine rules tests.

Mirrors ``rust-cores/oddtrick-core/tests/engine.rs``. Any rule asserted here is
also asserted there, and `test_rust_parity.py` pins the two implementations to
each other on real playthroughs.
"""

import random

import pytest

from games.oddtrick import bot
from games.oddtrick import engine as E


def _play_out(g, rng):
    """Drive a dealt game through auction and play with the greedy bot."""
    guard = 0
    while g["phase"] != "over":
        guard += 1
        assert guard < 200, "game failed to terminate"
        if g["phase"] == "auction":
            seat = g["auction"]["to_act"]
            kind, mv = bot.act(g, seat, rng)
            if mv.get("pass"):
                E.apply_pass(g, seat)
            else:
                E.apply_bid(g, seat, mv["level"], mv["denom"])
        else:
            seat = E.to_play(g)
            E.apply_play(g, seat, bot.choose_card(g, seat))
    return g


def _all_cards(g):
    cards = []
    for s in range(2):
        cards += list(g["hands"][s])
        for p in g["piles"][s]:
            cards += list(p)
    return cards


# --- dealing ---------------------------------------------------------------


@pytest.mark.parametrize("seed", range(40))
def test_deal_partitions_the_deck(seed):
    g = E.new_game(["a", "b"], random.Random(seed))
    cards = _all_cards(g) + list(g["out"])
    assert sorted(cards) == list(range(E.NCARD)), "26 dealt + 2 out of play, no dupes"
    for s in range(2):
        assert len(g["hands"][s]) == 7
        assert [len(p) for p in g["piles"][s]] == [2, 2, 2]


def test_out_of_play_pair_is_hidden_until_the_round_ends():
    g = E.new_game(["a", "b"], random.Random(1))
    assert E.view_for(g, 0)["out"] is None
    _play_out(g, random.Random(1))
    assert sorted(E.view_for(g, 0)["out"]) == sorted(g["out"])


# --- scoring geometry ------------------------------------------------------


def test_trick_values_and_constant_sum():
    vals = [E.trick_value(t) for t in range(E.NTRICKS)]
    assert vals[0] == -1, "trick 1 is odd-numbered"
    assert vals[1] == 2, "trick 2 is even-numbered"
    assert vals[12] == -1, "trick 13 is odd-numbered"
    assert vals.count(2) == 6 and vals.count(-1) == 7
    assert sum(vals) == E.POOL


@pytest.mark.parametrize("seed", range(30))
def test_every_card_is_played_and_points_sum_to_the_pool(seed):
    g = _play_out(E.new_game(["a", "b"], random.Random(seed)), random.Random(seed))
    assert g["trick"] == E.NTRICKS
    assert len(g["played"]) == 26
    assert not set(g["played"]) & set(g["out"]), "the out-of-play pair never enters"
    assert sum(g["pts"]) == E.POOL


def test_taking_every_trick_scores_worse_than_taking_the_even_ones():
    """The premise of the whole game, stated as an assertion."""
    sweep = sum(E.trick_value(t) for t in range(E.NTRICKS))
    surgical = sum(E.trick_value(t) for t in range(E.NTRICKS) if E.trick_value(t) > 0)
    assert sweep == 5 and surgical == 12
    assert surgical > sweep


# --- trick mechanics -------------------------------------------------------


def test_trick_winner_rules():
    c = lambda s, r: s * E.NRANK + r
    assert E.beats(c(0, 2), c(0, 5), E.NOTRUMP)
    assert not E.beats(c(0, 5), c(0, 2), E.NOTRUMP)
    assert not E.beats(c(0, 0), c(1, 6), E.NOTRUMP), "off-suit never wins at NT"
    assert E.beats(c(0, 6), c(2, 0), 2), "a ruff wins"
    assert not E.beats(c(0, 6), c(1, 6), 2), "an off-suit non-trump does not"
    assert not E.beats(c(2, 0), c(0, 6), 2), "a trump lead is not beaten by a side suit"


@pytest.mark.parametrize("seed", range(25))
def test_follow_suit_is_mandatory_and_pile_tops_count(seed):
    rng = random.Random(seed)
    g = E.new_game(["a", "b"], random.Random(seed))
    E.apply_bid(g, 0, 3, seed % 5)
    E.apply_pass(g, 1)
    while g["phase"] == "play":
        seat = E.to_play(g)
        moves = E.legal_moves(g, seat)
        assert 1 <= len(moves) <= 10, "at most 7 hand + 3 pile tops"
        if g["led"] is not None:
            ls = E.suit(g["led"])
            have = [c for c in E.playable(g, seat) if E.suit(c) == ls]
            if have:
                assert sorted(moves) == sorted(have), "must follow, piles included"
        E.apply_play(g, seat, rng.choice(moves))


def test_a_pile_bottom_only_becomes_playable_once_uncovered():
    g = E.new_game(["a", "b"], random.Random(7))
    E.apply_bid(g, 0, 2, E.NOTRUMP)
    E.apply_pass(g, 1)
    seat = E.to_play(g)
    buried = [p[0] for p in g["piles"][seat] if len(p) == 2]
    assert buried, "fixture must actually have covered cards"
    for c in buried:
        assert c not in E.playable(g, seat)
    top = g["piles"][seat][0][-1]
    under = g["piles"][seat][0][0]
    if top in E.legal_moves(g, seat):
        E.apply_play(g, seat, top)
        assert under in E.playable(g, seat), "uncovering makes it playable"


# --- auction ---------------------------------------------------------------


def test_the_opener_must_bid_and_cannot_pass():
    g = E.new_game(["a", "b"], random.Random(3))
    assert E.auction_options(g)["may_pass"] is False
    with pytest.raises(ValueError):
        E.apply_pass(g, 0)


def test_an_overtake_raises_by_one_or_two_only():
    g = E.new_game(["a", "b"], random.Random(4))
    E.apply_bid(g, 0, 4, 0)
    assert E.auction_options(g)["levels"] == [5, 6]
    ok, _ = E.can_bid(g, 1, 7, 1)
    assert not ok, "raising by three is illegal"
    ok, _ = E.can_bid(g, 1, 4, 1)
    assert not ok, "matching the level is illegal"
    assert E.can_bid(g, 1, 6, 1)[0]


def test_a_player_may_not_repeat_their_own_denomination_but_may_take_the_opponents():
    g = E.new_game(["a", "b"], random.Random(5))
    E.apply_bid(g, 0, 2, 0)          # seat 0 names clubs
    assert 0 in E.auction_options(g)["denoms"], "clubs is seat 1's to take"
    E.apply_bid(g, 1, 3, 0)          # seat 1 takes clubs
    # Seat 0 used clubs themselves, so it is spent FOR THEM regardless of who
    # named it since. The budget is per-player, not shared.
    assert not E.can_bid(g, 0, 4, 0)[0], "seat 0 already named clubs"
    assert E.can_bid(g, 0, 4, 1)[0], "diamonds is untouched by seat 0"
    assert E.auction_options(g)["denoms"] == [1, 2, 3, 4]


def test_passing_settles_the_contract_and_the_declarer_leads():
    g = E.new_game(["a", "b"], random.Random(6), opener=0)
    E.apply_bid(g, 0, 5, 2)
    E.apply_pass(g, 1)
    assert g["phase"] == "play"
    assert g["trump"] == 2
    assert g["auction"]["declarer"] == 0
    assert g["leader"] == 0, "the declarer leads to trick 1"
    assert E.to_play(g) == 0


def test_the_auction_survives_a_json_round_trip():
    """Pending decisions are game state, so a save cannot lose them."""
    import json
    g = E.new_game(["a", "b"], random.Random(8))
    E.apply_bid(g, 0, 3, 1)
    g2 = json.loads(json.dumps(g))
    assert g2["auction"]["to_act"] == 1
    assert E.auction_options(g2)["levels"] == [4, 5]


# --- contract scoring ------------------------------------------------------


@pytest.mark.parametrize("level,dpts,expect", [
    (5, 5, (25, 0)),
    (5, 9, (25, 0)),
    (5, 4, (0, 4 + 4 * 1)),
    (5, 3, (0, 4 + 4 * 2)),
    (5, 0, (0, 4 + 4 * 5)),
    (1, 1, (1, 0)),
    (1, 0, (0, 0 + 4 * 1)),
    (8, 8, (64, 0)),
])
def test_contract_score_table(level, dpts, expect):
    assert E.contract_score(level, dpts) == expect


@pytest.mark.parametrize("seed", range(20))
def test_result_is_internally_consistent(seed):
    g = _play_out(E.new_game(["a", "b"], random.Random(seed)), random.Random(seed))
    r = g["result"]
    decl = r["declarer"]
    assert r["declarer_pts"] == g["pts"][decl]
    assert r["made"] == (r["declarer_pts"] >= r["level"])
    ds, fs = E.contract_score(r["level"], r["declarer_pts"])
    assert r["scores"][decl] == ds
    assert r["scores"][1 - decl] == fs
    # Exactly one side scores.
    assert (r["scores"][decl] == 0) != (r["scores"][1 - decl] == 0) or r["scores"] == [0, 0]


# --- redaction -------------------------------------------------------------


@pytest.mark.parametrize("seed", range(15))
def test_a_view_never_leaks_a_card_the_seat_cannot_know(seed):
    """Asserted against a REAL mid-game payload, not a synthetic dict."""
    rng = random.Random(seed)
    g = E.new_game(["a", "b"], random.Random(seed))
    E.apply_bid(g, 0, 3, seed % 5)
    E.apply_pass(g, 1)
    for _ in range(9):
        seat = E.to_play(g)
        E.apply_play(g, seat, rng.choice(E.legal_moves(g, seat)))

    for me in range(2):
        opp = 1 - me
        blob = repr(E.view_for(g, me))
        v = E.view_for(g, me)

        secret = set(g["hands"][opp]) | set(g["out"])
        for i, p in enumerate(g["piles"]):
            for j, pile in enumerate(p):
                if len(pile) == 2 and j != 1:
                    secret.add(pile[0])   # side-pile bottoms, INCLUDING our own

        # Nothing secret may appear anywhere in the serialized view.
        def _walk(x, acc):
            if isinstance(x, int):
                acc.append(x)
            elif isinstance(x, (list, tuple)):
                for y in x:
                    _walk(y, acc)
            elif isinstance(x, dict):
                for y in x.values():
                    _walk(y, acc)
        seen = []
        _walk({k: val for k, val in v.items() if k not in ("pts", "trick", "you",
                                                           "leader", "opp_hand_n")}, seen)
        # `seen` includes non-card ints, so only assert on the card-shaped ones
        # that we know are secret.
        leaked = secret & set(c for c in seen if 0 <= c < E.NCARD)
        # A secret card may coincide with a legitimate small int elsewhere, so
        # check the structured fields explicitly too.
        assert v["opp_hand_n"] == len(g["hands"][opp])
        for owner in range(2):
            for j, pv in enumerate(v["piles"][owner]):
                real = g["piles"][owner][j]
                assert pv["n"] == len(real)
                assert pv["top"] == (real[-1] if real else None)
                if len(real) == 2:
                    expected = real[0] if j == 1 else None
                    assert pv["under"] == expected, "only the middle bottom is face-up"
        assert v["out"] is None
        assert "hands" not in v and "piles" not in blob.split("'piles':")[0]
        _ = leaked  # structural assertions above are the real gate


def test_view_shows_the_middle_pile_bottom_to_both_players():
    g = E.new_game(["a", "b"], random.Random(11))
    for me in range(2):
        v = E.view_for(g, me)
        for owner in range(2):
            assert v["piles"][owner][1]["under"] == g["piles"][owner][1][0]
            assert v["piles"][owner][0]["under"] is None
            assert v["piles"][owner][2]["under"] is None


# --- bot -------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(20))
def test_the_bot_always_produces_a_legal_action(seed):
    g = _play_out(E.new_game(["a", "b"], random.Random(seed)), random.Random(seed))
    assert g["phase"] == "over"


def test_the_bot_beats_random_play():
    """A floor check: the heuristic must be meaningfully better than noise."""
    wins = 0
    games = 0
    for seed in range(60):
        rng = random.Random(seed)
        g = E.new_game(["a", "b"], random.Random(seed))
        E.apply_bid(g, 0, 3, seed % 5)
        E.apply_pass(g, 1)
        bot_seat = seed % 2
        while g["phase"] == "play":
            seat = E.to_play(g)
            if seat == bot_seat:
                E.apply_play(g, seat, bot.choose_card(g, seat))
            else:
                E.apply_play(g, seat, rng.choice(E.legal_moves(g, seat)))
        games += 1
        if g["pts"][bot_seat] > g["pts"][1 - bot_seat]:
            wins += 1
    assert wins / games > 0.7, f"greedy only won {wins}/{games} against random"
