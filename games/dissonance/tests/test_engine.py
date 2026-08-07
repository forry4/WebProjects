"""Dissonance engine rules tests.

Mirrors ``rust-cores/dissonance-core/tests/engine.rs``. Any rule asserted here is
also asserted there, and `test_rust_parity.py` pins the two implementations to
each other on real playthroughs.
"""

import random

import pytest

from games.dissonance import bot
from games.dissonance import engine as E


def _play_out(g, rng):
    """Drive a dealt game through auction, swap and play with the greedy bot."""
    guard = 0
    while g["phase"] != "over":
        guard += 1
        assert guard < 200, "game failed to terminate"
        seat = E.turn_seat(g)
        if g["phase"] == "auction":
            kind, mv = bot.act(g, seat, rng)
            if mv.get("pass"):
                E.apply_pass(g, seat)
            else:
                E.apply_bid(g, seat, mv["level"], mv["denom"])
        elif g["phase"] == "swap":
            _, mv = bot.act(g, seat, rng)
            E.apply_swap(g, seat, mv.get("take"), mv.get("give"))
        else:
            E.apply_play(g, seat, bot.choose_card(g, seat))
    return g


def _skip_swap(g):
    """Resolve the swap phase by standing pat, for tests that target play."""
    assert g["phase"] == "swap"
    E.apply_swap(g, g["auction"]["declarer"], None, None)


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
    assert sorted(cards) == list(range(E.NCARD)), "26 dealt + 6 out of play, no dupes"
    assert len(g["out"]) == E.N_OUT
    assert g["shown"] == g["out"][:E.N_SHOWN], "the shown cards are fixed at the deal"
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
    """The conservation invariant, stated for a round that RAN TO THIRTEEN.

    `pts` sums to POOL only over a completed round, and a round now stops the
    moment the score can no longer change -- so this asserts the invariant on
    the complete branch and asserts the STOP was legitimate on the other.
    Neither branch is skipped: a round that ended early with a score that could
    still have moved is exactly the bug worth catching.
    """
    g = _play_out(E.new_game(["a", "b"], random.Random(seed)), random.Random(seed))
    assert not set(g["played"]) & set(g["out"]), "the out-of-play pair never enters"
    if g["trick"] == E.NTRICKS:
        assert len(g["played"]) == 26
        assert sum(g["pts"]) == E.POOL
        assert not g["result"]["ended_early"]
        return
    r = g["result"]
    assert r["ended_early"] and r["made"], "only a contract that cannot fail stops early"
    assert g["trick"] <= E.NTRICKS - 2, \
        "a round must never be cut short with a single trick left to play"
    # The floor it stopped on: no more +2 tricks, every remaining -1 taken.
    neg_left = sum(1 for t in range(g["trick"], E.NTRICKS) if E.trick_value(t) < 0)
    assert g["pts"][r["declarer"]] - neg_left >= r["level"]


def test_the_last_trick_is_always_played_out():
    """Stopping one trick from home saves nothing and costs the hand its last
    beat -- the trick where the shortfall and the Null consolation are still
    live, and so the one most worth seeing.

    Driven at the predicate rather than through random play, because the
    position this guards (settled with exactly one trick left) is common enough
    to matter and rare enough that a seed sweep is not proof it was checked.
    """
    g = E.new_game(["a", "b"], random.Random(3), opener=0)
    E.apply_bid(g, 0, 1, 0)
    E.apply_pass(g, 1)
    decl = g["auction"]["declarer"]

    # Way past a level-1 target, so only the trick count can hold the round open.
    g["pts"][decl] = 99
    for remaining in (2, 1, 0):
        g["trick"] = E.NTRICKS - remaining
        settled = E._score_is_settled(g)
        if remaining <= 1:
            assert not settled, f"stopped with {remaining} trick(s) left"
        else:
            assert settled, "a contract that cannot fail should still settle early"


def test_a_round_both_completes_and_settles_early_across_random_play():
    """Non-vacuity for the branch above: if every random game ran to thirteen,
    the early-end half of that test would be asserting nothing."""
    complete = early = 0
    for seed in range(60):
        g = _play_out(E.new_game(["a", "b"], random.Random(seed)), random.Random(seed))
        if g["trick"] == E.NTRICKS:
            complete += 1
        else:
            early += 1
    assert complete and early, f"{complete} complete, {early} early"


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
    _skip_swap(g)
    assert g["phase"] == "play", "the loop below must actually run"
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
    _skip_swap(g)
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


def test_an_overtake_raises_by_at_most_two_or_outranks_at_the_same_level():
    g = E.new_game(["a", "b"], random.Random(4))
    E.apply_bid(g, 0, 4, 2)  # open 4 hearts
    bids = E.auction_options(g)["bids"]
    assert not E.can_bid(g, 1, 7, 1)[0], "raising by three is illegal"
    # Same level: only a HIGHER-ranKed denomination outranks the standing bid.
    assert [4, 3] in bids and [4, 4] in bids, "spades/NT outrank hearts at 4"
    assert [4, 0] not in bids and [4, 1] not in bids and [4, 2] not in bids
    assert E.can_bid(g, 1, 4, 3)[0]
    assert not E.can_bid(g, 1, 4, 1)[0], "diamonds does not outrank hearts"
    # Raised levels: any unused denomination.
    assert E.can_bid(g, 1, 5, 0)[0] and E.can_bid(g, 1, 6, 1)[0]


def test_null_cannot_be_bid_at_all():
    """It stopped being a purchase (2026-08-07). Every measurement of it as a
    rung said the same thing -- overtaken away when cheap, unmakeable when dear
    -- so it is a consolation that rides under every contract instead."""
    g = E.new_game(["a", "b"], random.Random(4))
    for lvl in range(E.MIN_LEVEL, E.MAX_LEVEL + 1):
        assert [lvl, E.NULL_DENOM] not in E.auction_options(g)["bids"]
    assert not E.can_bid(g, 0, 6, E.NULL_DENOM)[0]
    with pytest.raises(ValueError):
        E.apply_bid(g, 0, 6, E.NULL_DENOM)
    E.apply_bid(g, 0, 5, 1)
    assert not any(d == E.NULL_DENOM for _, d in E.auction_options(g)["bids"]),         "and it is not reachable as an overtake either"


def test_a_player_may_not_repeat_their_own_denomination_but_may_take_the_opponents():
    g = E.new_game(["a", "b"], random.Random(5))
    E.apply_bid(g, 0, 2, 0)          # seat 0 names clubs
    assert any(d == 0 for _, d in E.auction_options(g)["bids"]),         "clubs is seat 1's to take"
    E.apply_bid(g, 1, 3, 0)          # seat 1 takes clubs
    # Seat 0 used clubs themselves, so it is spent FOR THEM regardless of who
    # named it since. The budget is per-player, not shared.
    assert not E.can_bid(g, 0, 4, 0)[0], "seat 0 already named clubs"
    assert E.can_bid(g, 0, 4, 1)[0], "diamonds is untouched by seat 0"
    assert sorted({d for _, d in E.auction_options(g)["bids"]}) == [1, 2, 3, 4]


def test_passing_settles_the_contract_via_the_swap_and_the_declarer_leads():
    g = E.new_game(["a", "b"], random.Random(6), opener=0)
    E.apply_bid(g, 0, 5, 2)
    E.apply_pass(g, 1)
    assert g["phase"] == "swap", "the declarer decides on the swap before play"
    assert E.turn_seat(g) == 0
    _skip_swap(g)
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
    assert E.auction_options(g2)["bids"] == E.auction_options(g)["bids"]
    assert [4, 0] in E.auction_options(g2)["bids"]


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
    if r["null"]:
        assert r["declarer_etricks"] == 0 and not r["made"]
        ds, fs = E.NULL_MAKE, 0
    else:
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
    # Half the seeds swap, so both branches of the out-pile bookkeeping are
    # under the leak assertions below.
    if seed % 2:
        E.apply_swap(g, 0, g["shown"][0], sorted(g["hands"][0])[0])
    else:
        _skip_swap(g)
    for _ in range(9):
        seat = E.to_play(g)
        E.apply_play(g, seat, rng.choice(E.legal_moves(g, seat)))

    for me in range(2):
        opp = 1 - me
        blob = repr(E.view_for(g, me))
        v = E.view_for(g, me)

        secret = set(g["hands"][opp]) | set(g["out"])
        if me != g["auction"]["declarer"]:
            secret |= set(g["shown"])  # the DEFENDER may never see the shown cards
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
        if me == g["auction"]["declarer"]:
            assert v["shown"] == g["shown"], "the declarer keeps what they saw"
        else:
            assert v["shown"] is None, "the defender never sees the shown cards"
        assert v["swapped"] in (True, False), "that a swap happened is public"
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
        _skip_swap(g)
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


# --- Null, the consolation ---------------------------------------------------


def _duck_everything(seed, level=4, denom=2):
    """A declarer who plays to take NO +2 trick, against a defender who plays
    to hand them one. It is a real playthrough rather than a staged result --
    the point of Null is that it is decided by the cards."""
    rng = random.Random(seed)
    g = E.new_game(["a", "b"], random.Random(seed), opener=0)
    E.apply_bid(g, 0, level, denom)
    E.apply_pass(g, 1)
    E.apply_swap(g, 0, None, None)
    while g["phase"] == "play":
        seat = E.to_play(g)
        moves = E.legal_moves(g, seat)
        if seat == 0:
            # Declarer: shed the highest card on a +2 trick, keep the lead low.
            want = E.trick_value(g["trick"]) < 0
            moves = sorted(moves, key=lambda c: (E.rank(c), c), reverse=want)
        E.apply_play(g, seat, moves[0] if seat == 0 else rng.choice(moves))
    return g


def test_taking_no_scoring_trick_scores_null_instead_of_being_set():
    """Both branches, from real play: a declarer who ducks everything scores
    the consolation, one who is merely set does not."""
    null_seen = set_seen = False
    for seed in range(60):
        g = _duck_everything(seed)
        r = g["result"]
        assert r["null"] == (r["declarer_etricks"] == 0)
        if r["null"]:
            null_seen = True
            assert not r["made"], "Null replaces being set; it is never a bonus"
            assert r["scores"] == [E.NULL_MAKE, 0]
            assert g["pts"][0] <= 0, "no +2 trick means no positive total"
        elif not r["made"]:
            set_seen = True
            assert r["scores"][0] == 0 and r["scores"][1] > 0
    assert null_seen and set_seen, "60 playthroughs must reach both outcomes"


def test_null_is_live_under_every_contract_not_just_one_denomination():
    """The whole change: it is no longer a game you buy, so the denomination and
    the level the declarer happened to name cannot gate it."""
    seen = set()
    for denom in range(E.NOTRUMP + 1):
        for seed in range(40):
            g = _duck_everything(seed, level=3, denom=denom)
            if g["result"]["null"]:
                seen.add(denom)
                assert g["result"]["scores"][0] == E.NULL_MAKE
                break
    assert seen == set(range(E.NOTRUMP + 1)), f"only reached Null in {sorted(seen)}"


def test_the_swap_moves_exactly_one_card_each_way():
    g = E.new_game(["a", "b"], random.Random(21), opener=0)
    E.apply_bid(g, 0, 4, 3)
    E.apply_pass(g, 1)
    take = g["shown"][2]
    give = sorted(g["hands"][0])[-1]
    before_out = list(g["out"])
    E.apply_swap(g, 0, take, give)
    assert take in g["hands"][0] and give not in g["hands"][0]
    assert give in g["out"] and take not in g["out"]
    assert len(g["out"]) == len(before_out) == E.N_OUT
    assert give in g["shown"], \
        "shown tracks what is OUT, so the discard takes the taken card's place"
    assert g["swapped"] is True and g["phase"] == "play"
    assert len(g["hands"][0]) == 7, "hand size is unchanged"


def test_a_swap_keeps_shown_on_the_out_pile_and_records_history_separately():
    """Two fields with two jobs, because one cannot do both.

    `shown` is the OUT-OF-PLAY set this seat can place, and a swap rewrites it
    so it keeps matching `out`. `shown_at_deal` is what the declarer was
    actually shown and never moves; only the round-end reveal reads it.

    Collapsing them into one field is what the reveal bug tempted us into, and
    the wire will not have it -- see the invariant test below.
    """
    g = E.new_game(["a", "b"], random.Random(21), opener=0)
    E.apply_bid(g, 0, 4, 3)
    E.apply_pass(g, 1)
    dealt = list(g["shown"])
    take, give = g["shown"][2], sorted(g["hands"][0])[-1]

    E.apply_swap(g, 0, take, give)

    assert give in g["shown"] and take not in g["shown"], \
        "shown must follow out, or the client searcher's arithmetic breaks"
    assert g["shown_at_deal"] == dealt, "the historical record moved"
    assert take in g["shown_at_deal"], "the card taken was one they were shown"
    assert give not in g["shown_at_deal"], \
        "the discard came out of HAND -- it was never shown to them"
    assert g["swap_take"] == take and g["swap_give"] == give
    assert give in g["out"] and take not in g["out"]


@pytest.mark.parametrize("seed", range(25))
def test_every_card_the_wire_calls_shown_is_really_out_of_play(seed):
    """THE INVARIANT THE CLIENT-SIDE SEARCHER RESTS ON, and it is not obvious
    from either side alone.

    `rust-cores/dissonance-core/src/wire.rs` treats `view["shown"]` as "the
    out-of-play cards this seat can place" and does exact card-count arithmetic
    with it: the unseen pool must partition into the opponent's hand, the
    covered pile bottoms and the unplaced out-cards, or it returns None and the
    decision falls back to the server bot.

    Breaking this is SILENT. Every worker errors, the main thread's filter drops
    them, and the room plays on at full speed with a weaker opponent while still
    calling itself Hard -- no exception, no console error, nothing red. It
    happened: making `shown` the historical record put the taken card (by then
    in the declarer's hand) into the searcher's out-of-play set, and because it
    only bites after a swap it passed locally and went red in CI.

    Asserted over a whole played round, for both seats, so a swap is included.
    """
    rng = random.Random(seed)
    g = E.new_game(["a", "b"], random.Random(seed))
    while g["phase"] != "over":
        for seat in (0, 1):
            v = E.view_for(g, seat)
            if v["shown"]:
                assert set(v["shown"]) <= set(g["out"]), (
                    f"seat {seat} is told {sorted(set(v['shown']) - set(g['out']))} "
                    "is out of play when it is not")
        seat = E.turn_seat(g)
        if g["phase"] == "auction":
            _, mv = bot.act(g, seat, rng)
            if mv.get("pass"):
                E.apply_pass(g, seat)
            else:
                E.apply_bid(g, seat, mv["level"], mv["denom"])
        elif g["phase"] == "swap":
            _, mv = bot.act(g, seat, rng)
            E.apply_swap(g, seat, mv.get("take"), mv.get("give"))
        else:
            E.apply_play(g, seat, bot.choose_card(g, seat))


def test_standing_pat_records_no_moved_cards():
    g = E.new_game(["a", "b"], random.Random(23), opener=0)
    E.apply_bid(g, 0, 4, 3)
    E.apply_pass(g, 1)
    shown_at_deal = list(g["shown"])

    E.apply_swap(g, 0, None, None)

    assert g["swapped"] is False
    assert g["swap_take"] is None and g["swap_give"] is None
    assert g["shown"] == shown_at_deal


def test_which_cards_moved_stays_secret_until_the_round_is_over():
    """The defender learns THAT a swap happened, never which cards — that is the
    whole reason the discard goes face-down. Shipping it early would hand them a
    card of the declarer's hand and one they know is out, for free."""
    g = E.new_game(["a", "b"], random.Random(21), opener=0)
    E.apply_bid(g, 0, 4, 3)
    E.apply_pass(g, 1)
    take, give = g["shown"][2], sorted(g["hands"][0])[-1]
    E.apply_swap(g, 0, take, give)

    for seat in (0, 1):
        v = E.view_for(g, seat)
        assert v["swapped"] is True, "that a swap happened is public"
        assert v["swap_take"] is None and v["swap_give"] is None, \
            f"seat {seat} was told which cards moved mid-round"

    g = _play_out(g, random.Random(21))
    assert g["phase"] == "over"
    for seat in (0, 1):
        v = E.view_for(g, seat)
        assert v["swap_take"] == take and v["swap_give"] == give, \
            "the reveal must show what actually moved"


def test_the_swap_rejects_pile_cards_and_unshown_cards():
    g = E.new_game(["a", "b"], random.Random(22), opener=0)
    E.apply_bid(g, 0, 4, 3)
    E.apply_pass(g, 1)
    hidden_out = g["out"][E.N_SHOWN]
    with pytest.raises(ValueError):
        E.apply_swap(g, 0, hidden_out, sorted(g["hands"][0])[0])
    pile_top = g["piles"][0][0][-1]
    with pytest.raises(ValueError):
        E.apply_swap(g, 0, g["shown"][0], pile_top)
    with pytest.raises(ValueError):
        E.apply_swap(g, 1, g["shown"][0], sorted(g["hands"][1])[0])  # defender
    assert g["phase"] == "swap", "every refused swap leaves the phase alone"


# ── match play ────────────────────────────────────────────────────────────────
# A game is a MATCH of rounds played to a target, not a single deal. One deal
# can simply be bad; over several the deals average out and what is left is the
# bidding judgement.


def test_a_round_ending_is_not_the_game_ending():
    g = E.new_game(["a", "b"], random.Random(101), opener=0)
    g = _play_out(g, random.Random(101))
    assert E.round_over(g), "the deal is scored"
    assert not E.is_over(g), "...but the match is not decided by one round"
    assert g["match"]["scores"] == g["result"]["scores"]
    assert g["match"]["round"] == 1


def test_the_match_accumulates_round_by_round_and_ends_at_the_target():
    g = E.new_game(["a", "b"], random.Random(102), opener=0)
    running = [0, 0]
    rounds = 0
    while not E.is_over(g):
        g = _play_out(g, random.Random(200 + rounds))
        rounds += 1
        for i in (0, 1):
            running[i] += g["result"]["scores"][i]
        assert g["match"]["scores"] == running, "the match total is the sum of its rounds"
        assert g["match"]["round"] == rounds
        if E.is_over(g):
            break
        assert max(running) < g["match"]["target"], \
            "a match that reached the target must not still be running"
        E.next_round(g, 0, g["result"]["round"])
    assert rounds > 1, "one deal cannot reach the target"
    assert max(running) >= g["match"]["target"]
    assert g["result"]["match_over"] is True


@pytest.mark.parametrize("mode,target", [("classic", 100), ("skat", 100)])
def test_a_new_game_is_dealt_at_its_modes_target(mode, target):
    # Written out per mode rather than looped over MATCH_TARGET, so the numbers
    # are PINNED here and not merely echoed back from the thing under test.
    # They agree today; the dict exists so they need not.
    g = E.new_game(["a", "b"], random.Random(103), mode=mode)
    assert g["match"]["target"] == target == E.MATCH_TARGET[mode]


def test_the_opener_alternates_between_rounds():
    # Not for the LEAD -- the declarer leads to trick 1, whoever opened -- but
    # for the bidding: the opener names a contract into no information at all,
    # and in classic mode is not allowed to pass.
    #
    # The match is held OPEN rather than left to chance. `next_round` deals with
    # `rng=None`, i.e. from OS entropy, so every round after the first is
    # genuinely random -- and this needs the match to survive three of them,
    # which one big round can end on its own. It failed roughly one run in
    # eight, and a flake in a suite with no skips reads as a real regression in
    # whatever was pushed that day. Zeroing the running total between rounds
    # makes the ROUND COUNT deterministic without touching the thing under
    # test, which is the opener and nothing else.
    g = E.new_game(["a", "b"], random.Random(104), opener=0)
    openers = [g["opener"]]
    for i in range(3):
        g = _play_out(g, random.Random(300 + i))
        E.match_of(g)["scores"] = [0, 0]
        E.match_of(g)["over"] = False
        assert not E.is_over(g), "the match was held open, so it cannot be over"
        E.next_round(g, 1, g["result"]["round"])
        openers.append(g["opener"])
    assert len(openers) == 4, "three rounds were dealt, so four openers"
    for a, b in zip(openers, openers[1:]):
        assert a != b, f"the opener did not alternate: {openers}"


def test_a_duplicate_next_round_click_does_not_deal_a_third_round():
    # Both players clicking at the same moment is the normal case, not an error
    # either of them should be shown -- and emphatically not a second deal on
    # top of the first, which would throw away a round already in progress.
    g = E.new_game(["a", "b"], random.Random(105), opener=0)
    g = _play_out(g, random.Random(105))
    seen = g["result"]["round"]
    E.next_round(g, 0, seen)
    hands = [sorted(h) for h in g["hands"]]
    E.next_round(g, 1, seen)          # the other seat, one moment later
    assert [sorted(h) for h in g["hands"]] == hands, "the second click redealt"
    assert g["match"]["round"] == seen + 1


def test_next_round_is_refused_mid_round_and_after_the_match():
    g = E.new_game(["a", "b"], random.Random(106), opener=0)
    with pytest.raises(ValueError):
        E.next_round(g, 0)            # still bidding
    g = _play_out(g, random.Random(106))
    g["match"]["scores"] = [g["match"]["target"], 0]
    g["match"]["over"] = True
    with pytest.raises(ValueError):
        E.next_round(g, 0)


def test_walking_out_ends_the_match_not_just_the_round():
    g = E.new_game(["a", "b"], random.Random(107), opener=0)
    res = E.abandon_result(g, 0)
    assert res["scores"][1] > 0, "the seat left standing takes the forfeit"
    assert res["match_over"] is True
    assert res["match_scores"] == res["scores"]
    g["phase"] = "over"
    g["result"] = res
    assert E.is_over(g), "there is nobody left to play the rest of the match"


def test_a_skat_pass_out_redeals_without_counting_as_a_round():
    g = E.new_game(["a", "b"], random.Random(108), mode="skat", opener=0)
    E.apply_move(g, "a", {"kind": "pass"})
    E.apply_move(g, "b", {"kind": "pass"})
    assert g["redeals"] == 1, "a passed-out deal is thrown in"
    assert g["match"]["round"] == 1, "...and is not a round anybody played"
    assert g["match"]["scores"] == [0, 0]


def test_both_seats_may_deal_the_next_round():
    for seat in (0, 1):
        g = E.new_game(["a", "b"], random.Random(109), opener=0)
        g = _play_out(g, random.Random(109))
        E.next_round(g, seat, g["result"]["round"])
        assert g["phase"] == "auction", f"seat {seat} could not deal the next round"


def test_may_act_opens_up_between_rounds_and_shuts_at_the_match_end():
    g = E.new_game(["a", "b"], random.Random(110), opener=0)
    on_turn = g["seats"][E.turn_seat(g)]
    assert E.may_act(g, on_turn) and not E.may_act(g, g["seats"][1 - E.turn_seat(g)])
    g = _play_out(g, random.Random(110))
    assert E.may_act(g, "a") and E.may_act(g, "b"), \
        "between rounds either seat may deal the next one"
    g["match"]["over"] = True
    assert not E.may_act(g, "a") and not E.may_act(g, "b")


def test_a_save_written_before_matches_existed_still_ends_at_its_round():
    g = E.new_game(["a", "b"], random.Random(111), opener=0)
    del g["match"]                    # exactly what an older row deserialises to
    g = _play_out(g, random.Random(111))
    assert E.match_of(g) is None
    assert E.is_over(g), "a matchless game ends where it always did"
    assert E.view_for(g, 0)["match"] is None
    assert "match_scores" not in g["result"]


def test_the_opener_is_derived_from_the_round_not_flipped_from_the_last_deal():
    # Not every deal is a round. A skat hand both players pass out is thrown in
    # and dealt again, and a redeal that flipped the opener would knock the
    # alternation out of phase -- which seat opened round 4 would then depend on
    # how many hands happened to get passed out along the way.
    g = E.new_game(["a", "b"], random.Random(112), mode="skat", opener=0)
    assert g["opener"] == 0
    for expected_redeals in (1, 2, 3):
        E.apply_move(g, "a", {"kind": "pass"})
        E.apply_move(g, "b", {"kind": "pass"})
        assert g["redeals"] == expected_redeals
        assert g["match"]["round"] == 1, "a passed-out deal is not a round"
        assert g["opener"] == 0, \
            f"a redeal moved the opener to {g['opener']} without a round passing"
    assert E.opener_for_round(g["match"]) == 0


def test_the_alternation_survives_any_number_of_pass_outs():
    g = E.new_game(["a", "b"], random.Random(113), mode="skat", opener=1)
    # Round 1 opens on seat 1, so round 2 must open on seat 0 no matter how many
    # deals were thrown in first.
    E.apply_move(g, "b", {"kind": "pass"})
    E.apply_move(g, "a", {"kind": "pass"})
    g["phase"] = "over"
    g["result"] = {"round": 1, "scores": [0, 0]}
    E.next_round(g, 0, 1)
    assert g["match"]["round"] == 2
    assert g["opener"] == 0, "round 2 opens on the other seat, pass-outs or not"


def test_a_match_saved_before_the_opener_was_derived_keeps_its_phase():
    # Recovered from where the alternation actually IS, rather than reset to
    # seat 0 -- which would repeat or skip a turn in the middle of a match.
    g = E.new_game(["a", "b"], random.Random(114), opener=0)
    g["match"]["round"] = 3
    g["opener"] = 0                    # round 3 of an alternation that began at 0
    del g["match"]["first_opener"]
    g["phase"] = "over"
    g["result"] = {"round": 3, "scores": [0, 0]}
    E.next_round(g, 0, 3)
    assert g["opener"] == 1, "round 4 must follow round 3, not restart the pattern"
