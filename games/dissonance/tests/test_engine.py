"""Dissonance engine rules tests.

Mirrors ``rust-cores/dissonance-core/tests/engine.rs``. Any rule asserted here is
also asserted there, and `test_rust_parity.py` pins the two implementations to
each other on real playthroughs.
"""

import json
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
        elif g["phase"] == "double":
            E.apply_double(g, seat, bot.choose_double(g, seat))
        else:
            E.apply_play(g, seat, bot.choose_card(g, seat))
    return g


def _skip_swap(g):
    """Reach trick 1 from the swap, for tests that target play.

    Stands pat on the swap AND declines the Double -- the two decisions between
    the settled auction and the opening lead. A test that means to exercise
    either one does it explicitly.
    """
    assert g["phase"] == "swap"
    E.apply_swap(g, g["auction"]["declarer"], None, None)
    if g["phase"] == "double":
        E.apply_double(g, 1 - g["auction"]["declarer"], False)


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
    """The conservation invariant -- and, since the overtrick bonus, an
    unconditional one.

    `pts` sums to POOL only over a round that ran to thirteen tricks. That used
    to be a branch, because a contract that could not fail stopped early; now
    every trick moves the score, so every round runs to the end and the
    invariant is simply true. Asserted flat rather than behind an `if`: a round
    that ended early would be a real regression and must not read as the other
    half of a legitimate pair.
    """
    g = _play_out(E.new_game(["a", "b"], random.Random(seed)), random.Random(seed))
    assert not set(g["played"]) & set(g["out"]), "the out-of-play pair never enters"
    assert g["trick"] == E.NTRICKS, "every trick moves the score, so all 13 are played"
    assert len(g["played"]) == 26
    assert sum(g["pts"]) == E.POOL
    assert not g["result"]["ended_early"]


def test_no_round_ends_before_the_thirteenth_trick(monkeypatch):
    """Both halves of the shelf, in one place.

    WITH the bonus on (the shipped configuration) nothing settles early, at any
    point total, however far past the target -- that is the product decision.
    With it OFF the old rule is still exactly the old rule, including its
    last-trick guard, which is what makes `_score_is_settled` shelved rather
    than dead: restoring the early end is one 0 in `OVER_BONUS` and no other
    edit. Driven at the predicate rather than through random play, because the
    position it guards (settled with one trick left) is common enough to matter
    and rare enough that a seed sweep is not proof it was checked.
    """
    g = E.new_game(["a", "b"], random.Random(3), opener=0)
    E.apply_bid(g, 0, 1, 0)
    E.apply_pass(g, 1)
    decl = g["auction"]["declarer"]
    # Way past a level-1 target, so only the rules under test can end the round.
    g["pts"][decl] = 99

    for remaining in (5, 2, 1, 0):
        g["trick"] = E.NTRICKS - remaining
        assert not E._score_is_settled(g), \
            f"a round ended with {remaining} trick(s) left while overtricks pay"

    monkeypatch.setitem(E.OVER_BONUS, "classic", 0)
    for remaining in (5, 2, 1, 0):
        g["trick"] = E.NTRICKS - remaining
        settled = E._score_is_settled(g)
        if remaining <= 1:
            assert not settled, f"stopped with {remaining} trick(s) left"
        else:
            assert settled, "with the bonus off, a contract that cannot fail settles"


def test_a_round_that_would_have_stopped_early_now_plays_on_for_the_bonus(monkeypatch):
    """Non-vacuity for the test above, and the change stated as behaviour.

    Seeds that used to end short must (a) still be reachable with the bonus off,
    or the shelf is guarding nothing, and (b) run to thirteen with it on. The
    same seed both ways, so the difference is the rule and not the deal.
    """
    def played(seed):
        return _play_out(E.new_game(["a", "b"], random.Random(seed)),
                         random.Random(seed))

    monkeypatch.setitem(E.OVER_BONUS, "classic", 0)
    stopped = [s for s in range(60) if played(s)["trick"] < E.NTRICKS]
    assert stopped, "no seed settles early even with the bonus off -- shelf unguarded"

    monkeypatch.undo()
    for seed in stopped:
        g = played(seed)
        assert g["trick"] == E.NTRICKS, f"seed {seed} still stopped early"
        # ...and the extra tricks are worth something, which is the whole point.
        assert g["result"]["over"] >= 0 and g["result"]["over_bonus"] == 1


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


def test_the_opener_may_pass_when_the_mode_says_so(monkeypatch):
    """OPENER_MAY_PASS (off as shipped): with it on, nothing standing behaves
    exactly as skat's open pass -- the first hands the deal over at no price,
    the second throws the hand in and redeals the SAME opener."""
    monkeypatch.setitem(E.OPENER_MAY_PASS, "classic", True)
    g = E.new_game(["a", "b"], random.Random(3), opener=0)
    assert E.auction_options(g)["may_pass"] is True
    E.apply_pass(g, 0)
    assert g["phase"] == "auction" and g["auction"]["to_act"] == 1
    assert g["auction"]["passes"] == 1
    # The seat handed the deal may still open normally...
    assert E.can_bid(g, 1, 4, 2)[0]
    # ...or pass it out, which redeals in place, in the SAME mode.
    E.apply_pass(g, 1, random.Random(99))
    assert g["mode"] == "classic", "a redeal must not change the room's mode"
    assert g["phase"] == "auction" and g["auction"]["log"] == []
    assert g["redeals"] == 1 and g["match"]["round"] == 1, "a pass-out is not a round"
    assert g["auction"]["to_act"] == 0, "the same seat opens the replacement deal"


def test_a_redeal_is_reproducible_when_the_caller_seeds_it(monkeypatch):
    """Production draws fresh entropy for a thrown-in hand; a paired lab needs
    the two flips of one deal to draw the SAME replacement, so `apply_pass`
    takes an rng. Skat's own pass-out rides the same seam."""
    monkeypatch.setitem(E.OPENER_MAY_PASS, "classic", True)
    hands = []
    for _ in range(2):
        g = E.new_game(["a", "b"], random.Random(3), opener=0)
        E.apply_pass(g, 0)
        E.apply_pass(g, 1, random.Random(1234))
        hands.append([sorted(h) for h in g["hands"]])
    assert hands[0] == hands[1], "the same seed must deal the same replacement"


def test_an_overtake_raises_freely_or_outranks_at_the_same_level():
    """Classic dropped the raise cap (2026-08-13): any raise up to the ceiling
    is legal, and the JUMP_SET_BONUS prices big jumps instead of a rule
    forbidding them."""
    g = E.new_game(["a", "b"], random.Random(4))
    E.apply_bid(g, 0, 4, 2)  # open 4 hearts
    bids = E.auction_options(g)["bids"]
    assert E.can_bid(g, 1, 7, 1)[0], "raising by three is legal now"
    top = E.max_level_for("classic")
    assert E.can_bid(g, 1, top, 0)[0], "a jump straight to the ceiling is legal"
    assert not E.can_bid(g, 1, top + 1, 0)[0], "the ceiling still binds"
    # Same level: only a HIGHER-ranked denomination outranks the standing bid.
    assert [4, 3] in bids and [4, 4] in bids, "spades/NT outrank hearts at 4"
    assert [4, 0] not in bids and [4, 1] not in bids and [4, 2] not in bids
    assert E.can_bid(g, 1, 4, 3)[0]
    assert not E.can_bid(g, 1, 4, 1)[0], "diamonds does not outrank hearts"
    # Raised levels: any unused denomination.
    assert E.can_bid(g, 1, 5, 0)[0] and E.can_bid(g, 1, 6, 1)[0]


def test_minor_mode_keeps_the_raise_cap():
    """The cap removal is classic's alone: minor's ladder was calibrated under
    the cap and its scale carries no jump bonus."""
    g = E.new_game(["a", "b"], random.Random(4), mode="minor")
    E.apply_bid(g, 0, 2, 2)
    assert E.can_bid(g, 1, 4, 1)[0], "raising by two is still legal"
    assert not E.can_bid(g, 1, 5, 1)[0], "raising by three is still capped"
    assert E.JUMP_SET_BONUS["minor"] == 0


def test_the_final_bids_jump_is_recorded_and_pays_the_defender_on_a_set():
    """The rule that replaced the cap: +JUMP_SET_BONUS per level the FINAL bid
    raised the standing level, to the defender, iff the contract is defeated.
    THE OPENING COUNTS (v2): it is a raise over level 0, so opening at 2 and
    getting passed out carries a jump of 2. A same-level overtake is 0."""
    g = E.new_game(["a", "b"], random.Random(4))
    E.apply_bid(g, 0, 2, 2)
    assert g["auction"]["jump"] == 2, "the opening is a raise over level 0"
    E.apply_bid(g, 1, 2, 3)
    assert g["auction"]["jump"] == 0, "a same-level overtake is not a jump"
    E.apply_bid(g, 0, 6, 0)
    assert g["auction"]["jump"] == 4
    E.apply_pass(g, 1)
    terms = E.payoff_terms(g)
    plain = E._terms_for("classic", 0, 6)
    assert terms["set_base"] == plain["set_base"] + 4 * E.JUMP_SET_BONUS["classic"]
    # The bonus is a SET price: a make and the Null consolation are untouched.
    assert terms["make"] == plain["make"] and terms["null"] == plain["null"]
    # ...and the Double doubles it, like the stake it rides beside.
    doubled = E._terms_for("classic", 0, 6, doubling=2, jump=4)
    assert doubled["set_base"] == 2 * (E.SET_LEVEL_RATE["classic"] * 6
                                       + E.FLAT_SET_PENALTY["classic"]
                                       + 4 * E.JUMP_SET_BONUS["classic"])


def test_an_opening_passed_out_is_charged_its_whole_level():
    """v2's whole point: opening at 6 and getting set hands the defender 18 on
    top; opening at 1 costs 3. The only jump-free settlement is a same-level
    overtake."""
    g = E.new_game(["a", "b"], random.Random(4))
    E.apply_bid(g, 0, 6, 1)
    E.apply_pass(g, 1)
    assert (E.payoff_terms(g)["set_base"]
            == E._terms_for("classic", 1, 6)["set_base"]
            + 6 * E.JUMP_SET_BONUS["classic"])
    g = E.new_game(["a", "b"], random.Random(4))
    E.apply_bid(g, 0, 3, 1)
    E.apply_bid(g, 1, 3, 2)   # same level, higher denomination: jump 0
    E.apply_pass(g, 0)
    assert E.payoff_terms(g)["set_base"] == E._terms_for("classic", 2, 3)["set_base"]


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


def test_classic_ships_the_per_player_denomination_ban():
    """The SHIPPED rule: a seat may never re-name a denomination it has itself
    named, however the auction has moved since. The two relaxations below are
    measurement arms (`DENOM_RULE`), not classic's behaviour."""
    g = E.new_game(["a", "b"], random.Random(5))
    assert E.denom_rule_for("classic") == "used"
    E.apply_bid(g, 0, 2, 0)          # seat 0 names clubs
    assert any(d == 0 for _, d in E.auction_options(g)["bids"]), \
        "clubs is seat 1's to take"
    E.apply_bid(g, 1, 3, 0)          # seat 1 takes clubs
    assert not E.can_bid(g, 0, 4, 0)[0], "seat 0 already named clubs"
    assert E.can_bid(g, 0, 4, 1)[0], "diamonds is untouched by seat 0"


def test_the_own_denomination_arm_bars_only_your_own_previous_suit(monkeypatch):
    """MEASURED, NOT SHIPPED (2026-08-13). YOU personally never bid the same
    suit twice in a row -- a bid may not name that seat's OWN previous bid's
    denomination, and nothing else is barred. So 1C 1S 2C is illegal (the 2C
    repeats its bidder's own 1C), raising the OPPONENT's standing suit is
    legal, and a seat returns to its suit after bidding something else."""
    monkeypatch.setitem(E.DENOM_RULE, "classic", "own")
    g = E.new_game(["a", "b"], random.Random(5))
    E.apply_bid(g, 0, 1, 0)          # 1C
    E.apply_bid(g, 1, 1, 3)          # 1S
    assert not E.can_bid(g, 0, 2, 0)[0], "1C 1S 2C is illegal"
    assert E.can_bid(g, 0, 2, 3)[0], "raising the opponent's spades is legal"
    assert sorted({d for _, d in E.auction_options(g)["bids"]}) == [1, 2, 3, 4]
    E.apply_bid(g, 0, 2, 1)          # 2D
    assert not E.can_bid(g, 1, 3, 3)[0], "seat 1's own spades are barred now"
    E.apply_bid(g, 1, 3, 2)          # 3H
    assert E.can_bid(g, 0, 4, 0)[0], "clubs come back once your last bid moved off them"
    # ...so a two-suit climb can run indefinitely: 4C, 5S, 6D all legal on.
    E.apply_bid(g, 0, 4, 0)
    assert E.can_bid(g, 1, 5, 3)[0]


def test_minor_keeps_the_per_player_denomination_ban():
    """The relaxation is classic's experiment; minor (and dummy) still run the
    forever-ban the mode was calibrated under."""
    g = E.new_game(["a", "b"], random.Random(5), mode="minor")
    E.apply_bid(g, 0, 2, 0)          # seat 0 names clubs
    assert any(d == 0 for _, d in E.auction_options(g)["bids"]), \
        "clubs is seat 1's to take"
    E.apply_bid(g, 1, 3, 0)          # seat 1 takes clubs
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


# The flat stake rides on BOTH bases, so it appears on both sides of this table.
# Written against the constants like the rates, so a re-pricing lands here as one
# edit rather than ten -- which is exactly what the 2026-08-16 re-pricing was
# (`L^2 + L + 2` made, `2L + 10` set, shortfall 1), and it landed as these five
# lines plus two helpers.
_FM = E.FLAT_MAKE_BONUS["classic"]
_LM = E.LINEAR_MAKE_BONUS["classic"]
_FS = E.FLAT_SET_PENALTY["classic"]
_SL = E.SET_LEVEL_RATE["classic"]
_SH = E.CLASSIC_SHORT_PENALTY


def _mk(level):
    """What a made contract pays, jumpless."""
    return level * level + _LM * level + _FM


def _st(level, short):
    """What a set contract pays the defender, jumpless."""
    return _SL * level + _FS + _SH * short


@pytest.mark.parametrize("level,dpts,expect", [
    (5, 5, (_mk(5), 0)),
    # Past the target, at 1 a point. Exactly on it is still the bare base,
    # which is the boundary the bonus must not move.
    (5, 9, (_mk(5) + 4, 0)),
    (5, 6, (_mk(5) + 1, 0)),
    # Set pays the defender N + the stake + SHORT_PENALTY a point short. Three
    # things have moved here: the base went N-1 -> N (2026-08-07, because at
    # the floor the old base contributed nothing, so the cheapest contract paid
    # its breaker by the margin alone), the rate went 4 -> 5 (2026-08-08, to
    # price the sacrifice bidding that pricing the pass unlocked), and the
    # +-10 stake landed on both bases (2026-08-11).
    (5, 4, (0, _st(5, 1))),
    (5, 3, (0, _st(5, 2))),
    (5, 0, (0, _st(5, 5))),
    (1, 1, (_mk(1), 0)),
    (1, 0, (0, _st(1, 1))),
    (8, 8, (_mk(8), 0)),
    # The declarer's ceiling is the six +2 tricks, so this is the largest
    # overtrick bonus the game can pay.
    (1, 12, (_mk(1) + 11, 0)),
])
def test_contract_score_table(level, dpts, expect):
    assert E.contract_score(level, dpts) == expect


def test_contract_score_is_the_payoff_arithmetic_and_not_a_second_copy():
    """It used to hold its own make/set rule. The overtrick bonus is exactly the
    kind of change that lands in one copy and not the other, and this helper is
    reachable from the tests only -- so the drift would have been a test
    agreeing with itself."""
    terms = E._terms_for("classic", 0, 4)
    for dpts in range(-7, 13):
        ds, fs = E.contract_score(4, dpts)
        assert ds - fs == E.payoff(terms, dpts, True)


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
        # `contract_score` prices a jumpless contract; a set in a round whose
        # FINAL bid raised the level also pays the defender the jump bonus.
        if not r["made"]:
            fs += E.JUMP_SET_BONUS["classic"] * r.get("jump", 0)
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
        E.apply_double(g, 1, True)      # and half of THOSE are doubled
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
    E.apply_double(g, 1, False)
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
    assert g["swapped"] is True and g["phase"] == "double", \
        "the swap hands off to the defender's Double, not straight to trick 1"
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
        elif g["phase"] == "double":
            E.apply_double(g, seat, bot.choose_double(g, seat))
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


@pytest.mark.parametrize("mode,target", [("classic", 150), ("skat", 100)])
def test_a_new_game_is_dealt_at_its_modes_target(mode, target):
    # Written out per mode rather than looped over MATCH_TARGET, so the numbers
    # are PINNED here and not merely echoed back from the thing under test.
    # Classic moved 100 -> 150 with the flat stake (2026-08-11) -- the measured
    # length-preserving point; skat carries no stake and stays.
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


def test_the_forfeited_match_is_LOST_by_whoever_walked_out():
    """...at any standing, which is why the outcome is shipped rather than
    derived. Every reader compared `match_scores`, so quitting while ahead kept
    the win -- and one contract's forfeit does not close a match-sized gap."""
    g = E.new_game(["a", "b"], random.Random(107), opener=0)
    g["match"]["scores"] = [80, 10]
    res = E.abandon_result(g, 0)                 # the seat 50+ points UP walks
    assert res["match_winner"] == 1
    assert res["match_scores"][0] > res["match_scores"][1], \
        "the standing is reported as it was, not rewritten to match the outcome"
    # ...and level is not a draw when someone left.
    g = E.new_game(["a", "b"], random.Random(107), opener=0)
    g["match"]["scores"] = [40, 40]
    assert E.abandon_result(g, 1)["match_winner"] == 0


def test_a_played_out_match_names_its_winner_from_the_standing():
    """The other arm of the same field: with nobody walking out it is exactly
    the score comparison, and a level match really is a draw."""
    g = _play_out(E.new_game(["a", "b"], random.Random(109), opener=0),
                  random.Random(109))
    res = g["result"]
    a, b = res["match_scores"]
    want = -1 if a == b else (0 if a > b else 1)
    assert res["match_winner"] == want


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


def test_the_match_keeps_a_scorecard_of_every_round_it_banked():
    # The running total says who is ahead and nothing about how they got there.
    # One line per round -- the contract, the declarer's points against what
    # they promised, and who took it -- is what the side panel reads.
    g = E.new_game(["a", "b"], random.Random(115), opener=0)
    seen = []
    for i in range(3):
        g = _play_out(g, random.Random(400 + i))
        res = g["result"]
        card = g["match"]["rounds"]
        assert len(card) == i + 1, "a scored round must add exactly one line"
        row = card[-1]
        assert row["round"] == res["round"]
        # DERIVED from the result row, never re-read off the board -- the
        # scorecard and the result panel must not be able to disagree.
        assert row["scores"] == res["scores"]
        assert row["declarer"] == res["declarer"]
        assert (row["level"], row["denom"]) == (res["level"], res["denom"])
        assert row["made"] == res["made"] and row["null"] == res["null"]
        assert row["pts"] == g["pts"], "the trick points as the round ended"
        assert row["target"] == res["level"], "classic promises its level"
        seen.append(dict(row))
        E.match_of(g)["scores"] = [0, 0]     # hold the match open, as above
        E.match_of(g)["over"] = False
        E.next_round(g, 0, res["round"])
    assert g["match"]["rounds"] == seen, "an earlier round's line must never be rewritten"
    assert [r["round"] for r in seen] == [1, 2, 3]


def test_the_scorecard_totals_are_the_running_total():
    # The two are written by the same call, so this is really asking that the
    # scorecard is COMPLETE -- a round banked without a line, or a line added
    # without banking, both show up here.
    g = E.new_game(["a", "b"], random.Random(116), opener=0)
    while not E.is_over(g):
        g = _play_out(g, random.Random(500 + g["match"]["round"]))
        if not E.is_over(g):
            E.next_round(g, 0, g["result"]["round"])
    m = g["match"]
    assert len(m["rounds"]) == m["round"], "one line per round played"
    for i in (0, 1):
        assert sum(r["scores"][i] for r in m["rounds"]) == m["scores"][i]


def test_a_passed_out_skat_deal_puts_no_line_on_the_scorecard():
    """It is not a round: nothing was played and nothing was scored."""
    g = E.new_game(["a", "b"], random.Random(117), mode="skat", opener=0)
    E.apply_move(g, "a", {"kind": "pass"})
    E.apply_move(g, "b", {"kind": "pass"})
    assert g["redeals"] == 1
    assert g["match"].get("rounds", []) == []


def test_a_forfeited_round_is_on_the_scorecard_and_says_so():
    g = E.new_game(["a", "b"], random.Random(118), opener=0)
    g["result"] = E.abandon_result(g, 0)
    row = g["match"]["rounds"][-1]
    assert row["abandoned"] is True
    assert row["scores"] == g["result"]["scores"], "the forfeit is banked as the round"


def test_a_match_already_in_progress_gains_a_scorecard_without_crashing():
    # `rounds` is setdefault'ed for the same reason `match_of` exists: a save
    # written before the scorecard has no list, and banking a round must add to
    # it rather than KeyError. Its earlier rounds are simply not recoverable.
    g = E.new_game(["a", "b"], random.Random(119), opener=0)
    g["match"].pop("rounds", None)      # exactly what an older row deserialises to
    g["match"]["scores"] = [30, 20]
    g["match"]["round"] = 5
    g = _play_out(g, random.Random(119))
    assert [r["round"] for r in g["match"]["rounds"]] == [5], \
        "the round just played is on it; the four before it are gone"
    assert g["match"]["scores"] != [30, 20], "...and it still banked the score"


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


# --- the round review's deal snapshot ----------------------------------------
#
# The review is an exact double-dummy solve of the position card play started
# from, so the snapshot IS the feature: a wrong one is a review of a different
# deal, which would look perfectly plausible on screen.


def _to_trick_one(seed, level=3, denom=2):
    """Deal, settle the auction with a plain bid, stand pat, decline the Double."""
    g = E.new_game(["a", "b"], random.Random(seed))
    E.apply_bid(g, 0, level, denom)
    E.apply_pass(g, 1)
    _skip_swap(g)
    assert g["phase"] == "play"
    return g


def test_the_deal_snapshot_is_the_whole_deck_split_the_way_play_started():
    g = _to_trick_one(11)
    d = g["deal"]
    assert [len(h) for h in d["hands"]] == [7, 7]
    assert [len(p) for p in d["piles"][0]] == [2, 2, 2]
    assert [len(p) for p in d["piles"][1]] == [2, 2, 2]
    assert len(d["out"]) == 6
    # Disjoint AND complete -- the same arithmetic `deal_from_json` fails closed
    # on, asserted from the PRODUCING side so the two cannot drift apart.
    cards = [c for h in d["hands"] for c in h]
    cards += [c for q in (0, 1) for p in d["piles"][q] for c in p]
    cards += list(d["out"])
    assert len(cards) == 32
    assert len(set(cards)) == 32, "a card was claimed twice"
    assert d["trump"] == g["trump"]
    assert d["leader"] == g["leader"] == g["auction"]["declarer"]


def test_the_snapshot_is_taken_AFTER_the_talon_swap():
    """The review must price the hand that was PLAYED, not the one dealt.

    The swap moves a card between hand and the out-set, so a snapshot taken at
    the deal would review a position the round never reached.
    """
    g = E.new_game(["a", "b"], random.Random(4))
    E.apply_bid(g, 0, 3, 2)
    E.apply_pass(g, 1)
    dec = g["auction"]["declarer"]
    take, give = g["shown"][0], sorted(g["hands"][dec])[0]
    E.apply_swap(g, dec, take, give)
    if g["phase"] == "double":
        E.apply_double(g, 1 - dec, False)
    assert g["phase"] == "play"
    d = g["deal"]
    assert take in d["hands"][dec], "the swapped-IN card is missing from the reviewed hand"
    assert give not in d["hands"][dec], "the discard is still in the reviewed hand"
    assert give in d["out"], "the discard is not in the reviewed out-set"
    assert take not in d["out"]


def test_a_pile_is_snapshotted_bottom_first():
    # Orientation is the one field a wrong answer would not announce: a flipped
    # pile is still a legal position, just not this one.
    g = _to_trick_one(5)
    for q in (0, 1):
        for i in range(3):
            assert g["deal"]["piles"][q][i] == list(g["piles"][q][i])
            assert g["deal"]["piles"][q][i][-1] == E.pile_tops(g, q)[i]


def test_the_snapshot_carries_the_contract_it_must_be_priced_against():
    # A review of round 3 has to price round 3's contract, and `payoff_terms`
    # can only ever read the one the game is currently on.
    g = _to_trick_one(7)
    assert g["deal"]["terms"] == E.payoff_terms(g)


def test_a_banked_round_carries_its_deal_and_the_live_one_never_ships():
    """The redaction that makes this safe at all.

    A banked round is finished and wholly public, so its cards ride on the wire
    with the rest of the match. The round being PLAYED holds both hands, and
    `view_for` must not carry it at any phase -- shipping it would hand a seat
    the opponent's cards, which is the whole game.
    """
    g = _play_out(E.new_game(["a", "b"], random.Random(3)), random.Random(3))
    row = g["match"]["rounds"][-1]
    assert "deal" in row and len(row["deal"]["hands"]) == 2

    live = _to_trick_one(3)
    for seat in (0, 1):
        v = E.view_for(live, seat)
        assert "deal" not in v, "the live round's deal is on the wire"
        # Assert on the SERIALISED payload: the failure this repo has already
        # paid for is something that NESTS a whole-game snapshot, which defeats
        # field-by-field redaction while every field check still passes.
        blob = json.dumps(v)
        assert '"deal"' not in blob
        opp = sorted(live["hands"][1 - seat])
        assert str(opp)[1:-1] not in blob, "the opponent's hand is in the payload"


def test_a_round_abandoned_mid_play_banks_no_deal_to_review():
    g = _to_trick_one(9)
    res = E.abandon_result(g, 0)
    E._bank_round(g, res)
    row = g["match"]["rounds"][-1]
    assert row.get("abandoned") is True
    assert "deal" not in row, "there is nothing to review in a round nobody finished"


def _row_reproduces_its_score(res) -> bool:
    """Re-add the result row's own terms and see if they reach its score.

    This is the RESULT PANEL's arithmetic, written out the way the panel writes
    it: the row is the only thing the panel has, so if these terms cannot
    reconstruct the score, the panel is printing a sum that does not reach its
    own total.
    """
    decl = res["declarer"]
    if res["null"]:
        printed, winner = res["null_value"], decl
    elif res["made"]:
        # (N x N + stake) [x2] + rate x over -- the panel reads the whole
        # (doubled) base off the row's `make_value` and derives the stake from
        # it, so the spelled-out terms reach the total whatever the flat
        # stake is priced at. Mirror that read, not a recomputation of it.
        base = res.get("make_value",
                       res["level"] * res["level"] * (2 if res.get("doubled") else 1))
        if res["mode"] == "skat":
            base = res["stake"]
        printed = base + res.get("over_bonus", 0) * res["over"]
        winner = decl
    else:
        base = (res["stake"] if res["mode"] == "skat"
                else res.get("set_base",
                             res["level"] * (2 if res.get("doubled") else 1)))
        ramp, flat, s = res.get("ramp", 0), res["short_rate"], res["short"]
        tail = (sum(flat + ramp * (i + 1) for i in range(s)) if ramp
                else flat * s)
        printed, winner = base + tail, 1 - decl
    return printed == res["scores"][winner]


def _play_out_any(g, rng, force_double=False):
    """Drive ANY mode to its result. `_play_out` above speaks classic's bid
    shape only; this one goes through `bot.act` + `apply_move`, which is the
    same mapping the room server uses, so skat's number ladder and its
    declaration work unchanged."""
    guard = 0
    while g["phase"] != "over":
        guard += 1
        assert guard < 300, "game failed to terminate"
        seat = E.turn_seat(g)
        pid = g["seats"][seat]
        # The server bot never Doubles (measured), so the ramped set branch --
        # the one whose arithmetic is spelled term by term -- is unreachable
        # from self-play alone and has to be asked for.
        if force_double and g["phase"] == "double":
            E.apply_double(g, seat, True)
            continue
        kind, mv = bot.act(g, seat, rng)
        if kind == "bid":
            mv = ({"kind": "pass"} if mv.get("pass")
                  else {"kind": "bid", "level": mv["level"], "denom": mv["denom"]})
        elif kind == "play":
            mv = {"kind": "play", "card": mv}
        elif kind == "swap":
            mv = {"kind": "swap", "take": mv.get("take"), "give": mv.get("give")}
        E.apply_move(g, pid, mv)
    return g


@pytest.mark.parametrize("mode", ["classic", "minor", "skat"])
def test_the_result_row_carries_every_term_its_own_score_needs(mode):
    """THE PANEL PRINTS THE ARITHMETIC, AND THE ARITHMETIC HAS ONE OWNER.

    Twice now the result panel has hardcoded a rate that the engine later
    moved -- "+ 4 x short" survived the 4 -> 5 change in both the skat line and
    the side panel -- and each time it printed a sum that did not add up to the
    score displayed beside it. Nothing caught it, because the score itself was
    right and only the story about it was wrong.

    So every rate the panel needs must be ON the row, off the same terms
    `_finish` scored with, and this walks real played-out rounds asserting the
    row can rebuild its own number. It fails if a term is dropped from the row
    OR if the payoff arithmetic changes shape without the row following.
    """
    seen = set()
    for seed in range(60):
        for dbl in ((False, True) if mode != "skat" else (False,)):
            rng = random.Random(seed)
            g = E.new_game(["a", "b"], rng, opener=seed % 2, mode=mode)
            res = _play_out_any(g, rng, force_double=dbl)["result"]
            assert _row_reproduces_its_score(res), (
                "seed %d (doubled=%s): the row's terms do not reach its score -- %r"
                % (seed, dbl, res))
            outcome = "null" if res["null"] else "made" if res["made"] else "set"
            seen.add(outcome)
            if dbl and outcome == "set":
                seen.add("ramped set")
    # Non-vacuity: a sweep that only ever produced made contracts would pass
    # while the set branch -- the one that has broken twice -- went unchecked.
    assert {"made", "set"} <= seen, "only reached %s" % sorted(seen)
    if mode != "skat":
        assert "ramped set" in seen, "the Double's ramp branch was never reached"


@pytest.mark.parametrize("mode", ["classic", "minor", "dummy"])
def test_the_scorecard_line_says_a_round_was_doubled(mode):
    """A DOUBLED ROUND MUST BE VISIBLE IN THE MATCH BOX.

    Otherwise it sits there as an ordinary line with a surprising number
    beside it -- the one row a reader actually wants explained. The row
    carries the MULTIPLIER rather than either mode's word for the bet, so
    classic's Double and skat's Kontra/Re land in one field.
    """
    for seed in range(12):
        rng = random.Random(seed)
        g = E.new_game(["a", "b"], rng, opener=seed % 2, mode=mode)
        _play_out_any(g, rng, force_double=True)
        row = g["match"]["rounds"][-1]
        assert row["doubling"] == 2, "a doubled round must say so on its line"
        # ...and the line agrees with the result the panel prints from.
        assert row["scores"] == g["result"]["scores"]

    # The undoubled control: the field is present and reads 1, so the frontend
    # can test `> 1` rather than distinguishing absent from false.
    rng = random.Random(99)
    g = E.new_game(["a", "b"], rng, opener=0, mode=mode)
    _play_out_any(g, rng, force_double=False)
    assert g["match"]["rounds"][-1]["doubling"] == 1


def test_a_skat_kontra_shows_on_the_scorecard_as_the_multiplier_it_is():
    """Kontra doubles and Re doubles again -- the same field, so the match box
    needs no idea which auction the room ran."""
    for kontra, re_, want in ((False, False, 1), (True, False, 2), (True, True, 4)):
        g = E.new_game(["a", "b"], random.Random(5), opener=0, mode="skat")
        E.apply_skat_bid(g, 0, E.SKAT_VALUES[0])
        E.apply_pass(g, 1)
        E.apply_look(g, 0)
        E.apply_swap(g, 0, None, None)
        d = E.skat_declarable(g["auction"]["value"])[0]
        E.apply_declare(g, 0, d["denom"], d["min_level"])
        E.apply_kontra(g, 1, kontra)
        if kontra:
            E.apply_re(g, 0, re_)
        rng = random.Random(5)
        while g["phase"] == "play":
            E.apply_play(g, E.to_play(g), bot.choose_card(g, E.to_play(g)))
        assert g["match"]["rounds"][-1]["doubling"] == want, (kontra, re_)


@pytest.mark.parametrize("mode", ["classic", "minor", "dummy"])
def test_the_result_row_says_what_the_double_was_worth(mode):
    """THE PANEL REPORTS A DOUBLE AS THE DIFFERENCE IT MADE, so the row has to
    carry this same round scored with the bet taken off.

    It replaced a line that narrated the set BASE moving -- which said nothing
    about the round just played, and quoted the pre-2026-08 N-1 base at that.
    """
    for seed in range(10):
        for dbl in (False, True):
            rng = random.Random(seed)
            g = E.new_game(["a", "b"], rng, opener=seed % 2, mode=mode)
            res = _play_out_any(g, rng, force_double=dbl)["result"]
            decl = res["declarer"]
            signed = (res["scores"][decl] if res["scores"][decl]
                      else -res["scores"][1 - decl])
            want = E.payoff(E._terms_for(mode, res["denom"], res["level"],
                                         jump=res.get("jump", 0)),
                            res["declarer_pts"], not res["null"])
            assert res["undoubled"] == want, "not the undoubled re-score"
            if not dbl:
                assert res["undoubled"] == signed, (
                    "an undoubled round must price identically either way")
                continue
            # The two properties the panel's arithmetic leans on.
            assert (signed >= 0) == (res["undoubled"] >= 0), (
                "a Double must never flip WHO won the round")
            assert abs(signed) >= abs(res["undoubled"]), (
                "a Double can only raise the stake it was placed on")


# --- the server bot defends against the Null consolation --------------------


def test_the_defender_forces_a_scoring_trick_on_a_declarer_ducking_for_null():
    """REPORTED FROM REAL GAMES (2026-08-14): the bot "keeps trying to win
    positive tricks" against an opponent ducking for Null -- which is exactly
    how the Null gets handed over, since the declarer scores it by winning NO
    scoring trick. One forced trick denies it, and knowing that needs no
    lookahead: `etricks` is a fact on the board."""
    from games.dissonance import bot as B
    g = E.new_game(["a", "b"], random.Random(4), opener=0)
    E.apply_bid(g, 0, 6, 2)          # seat 0 declares a level it will not reach
    E.apply_pass(g, 1)
    _skip_swap(g)
    g["trick"] = 1                   # an EVEN trick: +2 to whoever wins it
    assert E.trick_value_in(g, g["trick"]) > 0
    # The declarer has PASSED UP two scoring tricks and taken none -- which is
    # the evidence of ducking the rule requires (see _DUCKS_BEFORE_DENYING).
    g["etricks"] = [0, 2]
    g["pts"] = [0, 3]
    # The DEFENDER must not want this trick: taking it guarantees the declarer
    # finishes with no scoring trick and collects the flat consolation.
    assert B._want_win(g, 1) is False
    # ...and the DECLARER still wants it -- one scoring trick is what they are
    # avoiding, so the rule must not leak across the table.
    assert B._want_win(g, 0) is True
    # Once the Null is already dead the defender goes back to taking tricks.
    g["etricks"] = [1, 1]
    assert B._want_win(g, 1) is True


def test_the_defender_does_not_hand_over_a_trick_that_would_make_the_contract():
    """The denial is guarded: forcing a scoring trick must not buy them the
    contract. At a level this trick would reach, taking it stays right."""
    from games.dissonance import bot as B
    g = E.new_game(["a", "b"], random.Random(4), opener=0)
    E.apply_bid(g, 0, 1, 2)          # a level-1 contract
    E.apply_pass(g, 1)
    _skip_swap(g)
    g["trick"] = 1
    g["etricks"] = [0, 2]
    g["pts"] = [0, 0]
    # +2 would put them on 2 against a target of 1 -- it MAKES the contract,
    # so the one-trick-deep tier does not give it away.
    assert B._want_win(g, 1) is True


def test_an_early_round_is_not_mistaken_for_ducking():
    """THE GUARD THAT KEEPS THIS OUT OF ORDINARY PLAY. At the start of every
    round the declarer has no scoring trick because nothing has been played;
    keying on that alone handed over the first scoring trick of every round and
    measured a 3.2-point regression in self-play (-13.00 -> -16.17). Evidence
    of ducking is scoring tricks PASSED UP, and the threshold was swept: 1 costs
    1.3 points of ordinary play for 8 more denials, 3 gives up 22 denials for
    nothing."""
    from games.dissonance import bot as B
    g = E.new_game(["a", "b"], random.Random(4), opener=0)
    E.apply_bid(g, 0, 6, 2)
    E.apply_pass(g, 1)
    _skip_swap(g)
    g["trick"] = 1
    g["pts"] = [0, 0]
    g["etricks"] = [0, 0]            # nothing has happened yet
    assert B._want_win(g, 1) is True, "an unplayed round is not a duck"
    g["etricks"] = [0, 1]            # one passed up is ordinary card play
    assert B._want_win(g, 1) is True
    g["etricks"] = [0, 2]            # two is a pattern
    assert B._want_win(g, 1) is False
    assert B._DUCKS_BEFORE_DENYING == 2


def test_null_denial_is_off_in_the_odd_tricks_nobody_wants():
    from games.dissonance import bot as B
    g = E.new_game(["a", "b"], random.Random(4), opener=0)
    E.apply_bid(g, 0, 6, 2)
    E.apply_pass(g, 1)
    _skip_swap(g)
    g["trick"] = 0                   # odd trick: -1, nobody wants it
    g["etricks"] = [0, 0]
    assert B._want_win(g, 0) is False and B._want_win(g, 1) is False
