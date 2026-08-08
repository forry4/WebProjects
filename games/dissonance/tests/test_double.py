"""Classic's Double — the defender's one bet, and its deliberately lopsided odds.

Skat doubles with Kontra, symmetrically: everything ×2 whichever way it falls.
Classic's Double is NOT that, and the asymmetry is the design:

    made   N^2  ->  2 N^2      (overtricks doubled with it)
    set      N  ->  2N
    Null    12  ->  12         (untouched)

so it wins you N when it lands and costs N^2 when it does not -- reward linear
in the level, risk quadratic. Every test here is about one of those three
lines, or about the consequence of that asymmetry.
"""

import random

import pytest

from games.dissonance import bot
from games.dissonance import engine as E


def _settled(level=3, denom=2, seed=3, opener=0):
    """A classic game with the auction won by the opener, ready for the swap."""
    g = E.new_game(["a", "b"], random.Random(seed), opener=opener)
    E.apply_bid(g, opener, level, denom)
    E.apply_pass(g, 1 - opener)
    E.apply_swap(g, opener, None, None)
    return g


def _terms(level, doubled):
    g = _settled(level=level)
    E.apply_double(g, 1, doubled)
    return E.payoff_terms(g)


# --- the arithmetic --------------------------------------------------------


@pytest.mark.parametrize("level", range(1, 13))
def test_a_made_contract_pays_exactly_double(level):
    plain, dbl = _terms(level, False), _terms(level, True)
    assert dbl["make"] == 2 * plain["make"] == 2 * level * level
    assert dbl["over"] == 2 * plain["over"], "overtricks double with the contract"


@pytest.mark.parametrize("level", range(1, 13))
def test_a_set_contract_pays_2N_and_the_per_point_term_is_untouched(level):
    plain, dbl = _terms(level, False), _terms(level, True)
    assert plain["set_base"] == level
    assert dbl["set_base"] == 2 * level
    assert dbl["set_base"] - plain["set_base"] == level, "the reward is LINEAR in N"
    assert dbl["short"] == plain["short"], "the per-point term is NOT doubled"


@pytest.mark.parametrize("level", range(1, 13))
def test_null_is_never_doubled(level):
    assert _terms(level, True)["null"] == _terms(level, False)["null"] == E.NULL_MAKE


def test_the_bet_is_high_risk_for_low_reward_at_every_level():
    """The property the whole mechanic exists to have, asserted rather than
    asserted-in-prose: doubling risks more than it wins, by more at every step
    up. If a future re-pricing makes doubling a free roll, this fails."""
    ratios = []
    for level in range(1, 13):
        plain, dbl = _terms(level, False), _terms(level, True)
        win = dbl["set_base"] - plain["set_base"]          # if it goes down
        risk = dbl["make"] - plain["make"]                 # if it does not
        assert win == level and risk == level * level
        ratios.append(risk / win)
    assert ratios[0] == 1, "at level 1 the bet is even money"
    assert all(b > a for a, b in zip(ratios, ratios[1:])), \
        f"the risk:reward ratio must worsen with every level: {ratios}"


def test_the_break_even_odds_are_what_the_bot_policy_rests_on():
    """The server tier declines every Double because of these numbers, so pin
    them: a level-N Double needs the declarer to fail this often to break even.
    Measured failure rates over 1500 rounds were 0% / 6% / 18% / 27%."""
    need = {}
    for level in (1, 2, 3, 4):
        plain, dbl = _terms(level, False), _terms(level, True)
        win = dbl["set_base"] - plain["set_base"]
        risk = dbl["make"] - plain["make"]
        need[level] = round(risk / (win + risk), 2)
    assert need == {1: 0.5, 2: 0.67, 3: 0.75, 4: 0.8}


# --- end to end ------------------------------------------------------------


def test_a_doubled_round_scores_the_doubled_numbers():
    for doubled in (False, True):
        g = _settled(level=3)
        E.apply_double(g, 1, doubled)
        assert g["doubled"] is doubled
        t = E.payoff_terms(g)
        # made exactly on target
        assert E.payoff(t, 3, True) == (18 if doubled else 9)
        # set by two
        assert E.payoff(t, 1, True) == -((6 if doubled else 3) + 4 * 2)
        # no +2 trick at all
        assert E.payoff(t, -2, False) == E.NULL_MAKE


def test_the_result_row_carries_the_double_and_the_numbers_it_used():
    g = _settled(level=4)
    E.apply_double(g, 1, True)
    rng = random.Random(11)
    while g["phase"] == "play":
        s = E.to_play(g)
        E.apply_play(g, s, bot.choose_card(g, s))
    res = g["result"]
    assert res["doubled"] is True
    assert res["make_value"] == 2 * 4 * 4
    assert res["set_base"] == 2 * 4
    # The panel narrates from these, so they must be the ones actually scored.
    winner = res["declarer"] if res["scores"][res["declarer"]] else 1 - res["declarer"]
    assert res["scores"][winner] > 0


# --- the phase -------------------------------------------------------------


def test_the_swap_hands_off_to_the_defenders_double():
    g = _settled()
    assert g["phase"] == "double"
    assert E.turn_seat(g) == 1, "the DEFENDER decides"


def test_only_the_defender_may_double_and_only_in_its_phase():
    g = _settled()
    with pytest.raises(ValueError):
        E.apply_double(g, 0, True)              # the declarer
    E.apply_double(g, 1, False)
    assert g["phase"] == "play"
    with pytest.raises(ValueError):
        E.apply_double(g, 1, True)              # too late


def test_skat_mode_has_no_double_phase_and_refuses_the_move():
    """Skat doubles with Kontra. Two mechanics for one decision in one mode
    would be a second copy of the same rule."""
    g = E.new_game(["a", "b"], random.Random(4), opener=0, mode="skat")
    E.apply_skat_bid(g, 0, 12)
    E.apply_pass(g, 1)
    E.apply_hand(g, 0)
    E.apply_declare(g, 0, 2, 6)
    assert g["phase"] == "kontra", "skat goes to Kontra, never to double"
    with pytest.raises(ValueError):
        E.apply_double(g, 1, True)


def test_declining_the_double_leaves_the_round_exactly_as_it_was():
    a, b = _settled(level=5), _settled(level=5)
    E.apply_double(a, 1, False)
    assert a["doubled"] is False
    assert E.payoff_terms(a) == E.payoff_terms(b) | {"declarer": 0}


def test_a_classic_save_written_before_Double_existed_is_not_doubled():
    g = _settled(level=3)
    E.apply_double(g, 1, False)
    del g["doubled"]                            # what an older row deserialises to
    assert E.classic_doubling(g) == 1
    assert E.payoff_terms(g)["make"] == 9


# --- what both seats are told ----------------------------------------------


def test_the_double_is_public_to_both_seats():
    """It is a bet announced at the table: both players have to know what the
    round is now worth. Nothing about it is secret."""
    g = _settled(level=3)
    E.apply_double(g, 1, True)
    for seat in (0, 1):
        assert E.view_for(g, seat)["doubled"] is True
    g2 = E.new_game(["a", "b"], random.Random(9), opener=0, mode="skat")
    assert E.view_for(g2, 0)["doubled"] is None, "skat carries no classic Double"


def test_the_declarer_keeps_sight_of_the_talon_through_the_double_phase():
    """Inserting a phase between the swap and trick 1 must not take back
    information the declarer already holds -- and must not hand the Hard tier a
    different out-of-play set for the Double than for the opening lead."""
    g = _settled(level=3)
    assert g["phase"] == "double"
    assert E.view_for(g, 0)["shown"] is not None, "the declarer was shown these"
    assert E.view_for(g, 1)["shown"] is None, "the defender was not"
    E.apply_double(g, 1, False)
    assert E.view_for(g, 0)["shown"] is not None, "...and still holds them at trick 1"


# --- the search sees both branches ------------------------------------------


def test_the_hard_tier_is_offered_both_branches_priced():
    """Skat's Kontra ships ONE option and decides on its sign, which works only
    because Kontra is symmetric. Classic's Double is lopsided, so declining is
    not worth zero -- it is worth the undoubled contract -- and the search has
    to be able to compare the two."""
    g = _settled(level=3)
    opts = E.auction_payoff_options(g)
    assert len(opts) == 2
    on = next(o for o in opts if o["move"]["on"] is True)
    off = next(o for o in opts if o["move"]["on"] is False)
    assert on["make"] == 2 * off["make"]
    assert on["set_base"] == 6 and off["set_base"] == 3
    assert all("decline" not in o for o in opts), \
        "both branches carry their own move; neither is an implicit zero"


def test_the_server_tier_never_doubles_and_the_numbers_say_why():
    """Not a gap -- a measured decision, pinned with the arithmetic behind it.

    Doubling needs the declarer to fail 33% / 57% / 69% / 76% / 81% / 84% of the
    time at levels 1-6 to break even, and 1500 rounds of self-play put the real
    failure rate at 0% / 6% / 18% / 27% / 39% / 55%. The reward grows linearly
    and the risk quadratically, so the curves never cross.

    If someone re-prices Double so that they DO cross, this test is what says to
    revisit the policy rather than leaving a permanently-declining bot behind a
    mechanic that has become worth using.
    """
    seen = 0
    for seed in range(150):
        g = E.new_game(["a", "b"], random.Random(400 + seed), opener=seed % 2)
        rng = random.Random(seed)
        while g["phase"] not in ("double", "over"):
            seat = E.turn_seat(g)
            kind, mv = bot.act(g, seat, rng)
            if kind == "bid":
                mv = ({"kind": "pass"} if mv.get("pass")
                      else {"kind": "bid", "level": mv["level"], "denom": mv["denom"]})
            elif kind == "swap":
                mv = {"kind": "swap", "take": mv["take"], "give": mv["give"]}
            E.apply_move(g, g["seats"][seat], mv)
        if g["phase"] != "double":
            continue
        seen += 1
        defender = 1 - g["auction"]["declarer"]
        assert bot.choose_double(g, defender) is False
        # ...and it answers through `act`, not only through the helper.
        kind, mv = bot.act(g, defender, rng)
        assert (kind, mv) == ("move", {"kind": "double", "on": False})
    assert seen > 100, f"only {seen} rounds reached the Double"


def test_the_break_even_curve_never_meets_the_failure_curve():
    """The claim above as arithmetic, independent of any self-play run: the
    reward is linear in N and the risk quadratic, so break-even rises without
    bound while a failure rate cannot pass 100%."""
    prev = 0.0
    for level in range(1, 13):
        plain, dbl = _terms(level, False), _terms(level, True)
        win = dbl["set_base"] - plain["set_base"]
        risk = dbl["make"] - plain["make"]
        be = risk / (win + risk)
        assert be > prev, "break-even must rise with the level"
        prev = be
    assert prev > 0.9, "and reach a rate no defender could sustain"


def test_the_priced_branches_pick_the_double_exactly_when_the_contract_is_dead():
    """The Hard tier's decision rule, as arithmetic.

    It gets both branches priced from the DECLARER's side and takes the one
    worst for them. So the doubled branch must win precisely when the declarer
    cannot reach the target -- which is what makes the search able to spot a
    sacrifice that a rank-sum heuristic cannot: "can this contract be reached"
    is a solve, not a hand count.
    """
    g = _settled(level=6, denom=0)
    on, off = (next(o for o in E.auction_payoff_options(g)
                    if o["move"]["on"] is want) for want in (True, False))

    def better_for_defender(pts, can_duck):
        # The client negates the declarer-signed value and takes the max.
        a = -E.payoff(on, pts, not can_duck)
        b = -E.payoff(off, pts, not can_duck)
        return "double" if a > b else "decline"

    # A sacrifice: bid 6, cannot get near it. Double.
    assert better_for_defender(0, False) == "double"
    assert better_for_defender(2, False) == "double"
    # A contract that makes. Declining is worth more than doubling it.
    assert better_for_defender(6, False) == "decline"
    assert better_for_defender(9, False) == "decline"
    # ...and a declarer who can still duck to Null is worth nothing either way,
    # because Double does not touch Null -- so the search is indifferent.
    assert -E.payoff(on, 0, False) == -E.payoff(off, 0, False) == -E.NULL_MAKE


def test_a_sacrifice_is_the_case_the_double_is_priced_for():
    """Measured, and recorded because it is both the reason the mechanic exists
    AND the reason it currently sits on a knife edge.

    Ordinary level-6 contracts fail 56% against a break-even of 86%, so doubling
    them loses 12.6 a go. A SACRIFICE -- a hopeless hand overtaking at 6 to deny
    a made contract -- fails 78% with a further 9% ducking to Null, which is
    EV -0.13: break-even, not profit.

    It was +0.97 until the classic set base moved from N-1 to N on 2026-08-07.
    That change made the doubled base a literal doubling (N -> 2N) but cut the
    reward for doubling from N+1 to N, and at level 6 that one point is the
    whole margin. If Double should actually pay against a sacrifice, the reward
    is the lever: a doubled base of 3N puts the same case at about +4.7.
    """
    plain, dbl = _terms(6, False), _terms(6, True)
    win = dbl["set_base"] - plain["set_base"]
    risk = dbl["make"] - plain["make"]
    assert win == 6 and risk == 36
    ordinary = 0.56 * win - 0.44 * risk        # measured, self-play
    sacrifice = 0.78 * win - 0.13 * risk       # measured, forced sacrifice
    assert ordinary < -10, ordinary
    assert -1 < sacrifice < 1, f"the sacrifice case is break-even, not profit: {sacrifice}"
    assert sacrifice - ordinary > 10, "...but it is the case the mechanic is for"
