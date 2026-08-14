"""Classic's Double — the defender's one bet, and its deliberately lopsided odds.

Skat doubles with Kontra, symmetrically: everything ×2 whichever way it falls.
Classic's Double is NOT that, and the asymmetry is the design (the flat ±10
stake of 2026-08-11 rides INSIDE both bases, so it doubles with them):

    made   N^2 + 10  ->  2 (N^2 + 10)     (overtricks doubled with it)
    set      N + 10  ->  2 (N + 10), and the shortfall RAMPS: 6, 7, 8 a point
                         instead of a flat 5
    Null         12  ->  12               (untouched)

The ramp is the part that makes the mechanic work. Doubling has to tell a
SACRIFICE from a near-miss, and what separates them is not the level -- both
have that -- but how far short the declarer finishes: ordinary failures are a
median of 2 short with 48% by exactly 1, sacrifices a median of 4. Scaling by
the level taxes what they share; ramping taxes what only a sacrifice has.
"""

import random

import pytest

from games.dissonance import bot
from games.dissonance import engine as E


def _settled(level=3, denom=2, seed=3, opener=0):
    """A classic game with the auction won by the opener, ready for the swap.

    NOTE (v2 jump rule, 2026-08-13): an opening bid counts as a raise over
    level 0, so this contract carries a JUMP of `level` and its set base is
    `level + stake + JUMP_SET_BONUS x level`. The arithmetic pins below use
    `_settled_flat` instead, so they state the Double's own numbers without
    the jump term riding along."""
    g = E.new_game(["a", "b"], random.Random(seed), opener=opener)
    E.apply_bid(g, opener, level, denom)
    E.apply_pass(g, 1 - opener)
    E.apply_swap(g, opener, None, None)
    return g


def _settled_flat(level=3, denom=2, seed=3, opener=0):
    """Like `_settled`, but the auction ends on a SAME-LEVEL overtake, so the
    settled contract carries NO jump: the opener climbs 0 -> 1 -> `denom` at
    one level and the defender passes. Needs `denom >= 2`."""
    g = E.new_game(["a", "b"], random.Random(seed), opener=opener)
    E.apply_bid(g, opener, level, 0)
    E.apply_bid(g, 1 - opener, level, 1)
    E.apply_bid(g, opener, level, denom)
    E.apply_pass(g, 1 - opener)
    E.apply_swap(g, opener, None, None)
    return g


def _terms(level, doubled):
    g = _settled_flat(level=level)
    E.apply_double(g, 1, doubled)
    return E.payoff_terms(g)


#: Classic's bid ladder top. Was a literal 13-exclusive range, which quietly
#: became "two rungs past what anyone can bid" when the ladder capped at 10 --
#: and a parametrize over unbiddable levels fails as an illegal-bid ValueError
#: rather than as the arithmetic claim it means to make.
_TOP = E.max_level_for("classic")
#: The flat stake, off the constants so a re-pricing lands here as one edit.
_FM = E.FLAT_MAKE_BONUS["classic"]
_FS = E.FLAT_SET_PENALTY["classic"]


# --- the arithmetic --------------------------------------------------------


@pytest.mark.parametrize("level", range(E.MIN_LEVEL, _TOP + 1))
def test_a_made_contract_pays_exactly_double(level):
    plain, dbl = _terms(level, False), _terms(level, True)
    assert dbl["make"] == 2 * plain["make"] == 2 * (level * level + _FM)
    assert dbl["over"] == 2 * plain["over"], "overtricks double with the contract"


@pytest.mark.parametrize("level", range(E.MIN_LEVEL, _TOP + 1))
def test_a_set_contract_pays_2N_and_a_RAMPED_shortfall(level):
    plain, dbl = _terms(level, False), _terms(level, True)
    assert plain["set_base"] == level + _FS and plain["ramp"] == 0
    assert dbl["set_base"] == 2 * (level + _FS)
    assert dbl["short"] == plain["short"], "the flat per-point term is unchanged"
    assert dbl["ramp"] == E.DOUBLE_RAMP == 1
    # DERIVED from the two dials, never typed out: both have moved once already
    # (short 4 -> 5, ramp 0 -> 1) and a literal only says what someone believed
    # on the day. Doubled, the s-th point short costs `short + s*ramp`.
    P, R = E.SHORT_PENALTY, E.DOUBLE_RAMP
    pen = [-E.payoff(dbl, level - s, True) - 2 * (level + _FS)
           for s in range(1, 6)]
    steps = [b - a for a, b in zip([0] + pen, pen)]
    assert steps == [P + R * s for s in range(1, 6)], steps
    assert steps == sorted(steps) and steps[0] > steps[0] - 1, "it must RISE"
    flat = [-E.payoff(plain, level - s, True) - (level + _FS)
            for s in range(1, 6)]
    assert flat == [P * s for s in range(1, 6)], "undoubled stays flat"


@pytest.mark.parametrize("level", range(E.MIN_LEVEL, _TOP + 1))
def test_null_is_never_doubled(level):
    assert _terms(level, True)["null"] == _terms(level, False)["null"] == E.NULL_MAKE


def test_the_reward_grows_with_the_SHORTFALL_not_just_the_level():
    """The design property, asserted rather than left in prose: what doubling
    wins you must rise with how far short the declarer finishes, or it cannot
    distinguish a sacrifice from a near-miss."""
    for level in (3, 6):
        plain, dbl = _terms(level, False), _terms(level, True)
        wins = [E.payoff(plain, level - s, True) - E.payoff(dbl, level - s, True)
                for s in range(1, 7)]
        assert all(b > a for a, b in zip(wins, wins[1:])), wins
        # A near-miss is barely taxed beyond the doubled stake; a deep failure
        # pays the whole ramp on top (s(s+1)/2 x ramp, 20 more by 6 short).
        assert wins[0] < level + _FS + 2, \
            f"a 1-short miss should stay cheap: {wins[0]}"
        assert wins[5] - wins[0] >= 20 * E.DOUBLE_RAMP, \
            f"a 6-short collapse should not: {wins}"


def test_doubling_still_risks_more_than_it_wins_on_a_near_miss():
    """It must stay a real bet. On the COMMON failure -- 1 short, 48% of them --
    the risk of a made contract still dwarfs the reward.

    JUMP-FREE contracts only: the v2 jump rule deliberately breaks this for
    jumped ones -- see the companion test below."""
    for level in range(2, _TOP + 1):
        plain, dbl = _terms(level, False), _terms(level, True)
        win = E.payoff(plain, level - 1, True) - E.payoff(dbl, level - 1, True)
        risk = dbl["make"] - plain["make"]
        assert risk > win, f"level {level}: risk {risk} <= reward {win}"


def test_a_jumped_contracts_double_out_wins_its_risk_at_low_levels():
    """v2's teeth, pinned as a DESIGN property rather than left to be
    rediscovered as a surprise: an open-and-pass contract carries its whole
    level as a jump, the Double doubles the jump bonus with the base, and at
    levels 2-4 that makes the near-miss reward EXCEED the made-contract risk.
    A leap is not just fatter when set -- it invites the Double."""
    flipped = 0
    for level in (2, 3, 4):
        g = _settled(level=level)          # open-and-pass: jump == level
        plain = E.payoff_terms(g)
        E.apply_double(g, 1, True)
        dbl = E.payoff_terms(g)
        win = E.payoff(plain, level - 1, True) - E.payoff(dbl, level - 1, True)
        risk = dbl["make"] - plain["make"]
        if win > risk:
            flipped += 1
    assert flipped == 3, "the jump bonus should flip the near-miss bet at 2-4"


def test_the_break_even_odds_are_what_the_bot_policy_rests_on():
    """The server tier declines every Double because of these numbers, so pin
    them: a level-N Double needs the declarer to fail this often to break even.
    Measured failure rates over 1500 rounds were 0% / 6% / 18% / 27%."""
    need = {}
    for level in (1, 2, 3, 4):
        plain, dbl = _terms(level, False), _terms(level, True)
        # ...at the MEDIAN ordinary shortfall of 2, which is the case a
        # defender doubling a genuine contract is actually betting against.
        win = E.payoff(plain, level - 2, True) - E.payoff(dbl, level - 2, True)
        risk = dbl["make"] - plain["make"]
        need[level] = round(risk / (win + risk), 2)
    # Derived, and asserted as a SHAPE: break-even must rise with the level,
    # and stay reachable at the bottom where a sacrifice is cheapest to punish.
    # The +-10 stake lifted the floor (level-1 break-even 0.31 -> 0.44: the
    # risk grew by the whole stake, the reward only by its doubled half) but
    # flattened the top -- see the curve test below.
    assert sorted(need) == [1, 2, 3, 4]
    vals = [need[k] for k in (1, 2, 3, 4)]
    assert all(b > a for a, b in zip(vals, vals[1:])), need
    assert vals[0] < 0.5 and vals[-1] < 0.75, need


# --- end to end ------------------------------------------------------------


def test_a_doubled_round_scores_the_doubled_numbers():
    for doubled in (False, True):
        g = _settled_flat(level=3)
        E.apply_double(g, 1, doubled)
        assert g["doubled"] is doubled
        t = E.payoff_terms(g)
        # made exactly on target: (N^2 + stake) [x2]
        assert E.payoff(t, 3, True) == (2 * (9 + _FM) if doubled else 9 + _FM)
        # set by two. Doubled: base 2(N + stake) + (short+ramp) + (short+2 ramp).
        # Undoubled: base (N + stake) + 2 short.
        P, R = E.SHORT_PENALTY, E.DOUBLE_RAMP
        want = (-(2 * (3 + _FS) + (P + R) + (P + 2 * R)) if doubled
                else -((3 + _FS) + 2 * P))
        assert E.payoff(t, 1, True) == want
        # no +2 trick at all
        assert E.payoff(t, -2, False) == E.NULL_MAKE


def test_the_result_row_carries_the_double_and_the_numbers_it_used():
    g = _settled_flat(level=4)
    E.apply_double(g, 1, True)
    rng = random.Random(11)
    while g["phase"] == "play":
        s = E.to_play(g)
        E.apply_play(g, s, bot.choose_card(g, s))
    res = g["result"]
    assert res["doubled"] is True
    assert res["make_value"] == 2 * (4 * 4 + _FM)
    assert res["set_base"] == 2 * (4 + _FS)
    # The panel narrates from these, so they must be the ones actually scored.
    winner = res["declarer"] if res["scores"][res["declarer"]] else 1 - res["declarer"]
    assert res["scores"][winner] > 0


# --- the phase -------------------------------------------------------------


def test_the_jump_bonus_rides_inside_the_double_as_shipped(monkeypatch):
    """`JUMP_DOUBLED` is an experiment arm and it is ON, which is the shipped
    rule: the Double multiplies the jump bonus with the rest of the set base.

    Off, the bonus is added AFTER the doubling. The property that makes it the
    surgical candidate is that the UNDOUBLED game cannot move either way -- so
    it can be measured without relitigating the jump-rate calibration -- and
    that is asserted here rather than argued.
    """
    assert E.JUMP_DOUBLED["classic"] is True, "the shipped rule doubles it"
    N, j = 5, 4
    stake, bonus = N + E.FLAT_SET_PENALTY["classic"], E.JUMP_SET_BONUS["classic"] * j
    on = E._terms_for("classic", 2, N, jump=j, doubling=2)
    off = E._terms_for("classic", 2, N, jump=j)
    assert on["set_base"] == (stake + bonus) * 2
    assert off["set_base"] == stake + bonus

    monkeypatch.setitem(E.JUMP_DOUBLED, "classic", False)
    arm_on = E._terms_for("classic", 2, N, jump=j, doubling=2)
    arm_off = E._terms_for("classic", 2, N, jump=j)
    assert arm_on["set_base"] == stake * 2 + bonus, "the bonus is added after the x2"
    assert arm_on["set_base"] < on["set_base"], "the arm must actually trim it"
    # THE WHOLE POINT: the undoubled contract is untouched by the arm.
    assert arm_off == off
    # ...and a jumpless contract is identical under both, since there is no
    # bonus to move -- so the arm can only ever reprice a LEAP.
    assert (E._terms_for("classic", 2, N, jump=0, doubling=2)
            == on | {"set_base": stake * 2})


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
    assert E.payoff_terms(g)["make"] == 9 + _FM


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
    g = _settled_flat(level=3)
    opts = E.auction_payoff_options(g)
    assert len(opts) == 2
    on = next(o for o in opts if o["move"]["on"] is True)
    off = next(o for o in opts if o["move"]["on"] is False)
    assert on["make"] == 2 * off["make"]
    assert on["set_base"] == 2 * (3 + _FS) and off["set_base"] == 3 + _FS
    assert on["ramp"] == 1 and off["ramp"] == 0
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
    for level in range(E.MIN_LEVEL, _TOP + 1):
        plain, dbl = _terms(level, False), _terms(level, True)
        win = dbl["set_base"] - plain["set_base"]
        risk = dbl["make"] - plain["make"]
        be = risk / (win + risk)
        assert be > prev, "break-even must rise with the level"
        prev = be
    # The +-10 stake compressed the top of the curve (0.93 -> 0.85: the win
    # side gained the doubled stake, which matters more where N is the whole
    # win) -- still past any sustainable failure rate, sacrifices included
    # (they fail ~78%).
    assert prev > 0.8, "and reach a rate no defender could sustain"


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
    """Measured, and recorded because it is the reason the mechanic exists.

    Ordinary level-6 contracts fail 56% against their break-even, so doubling
    them still loses (~9.6 a go under the stake). A SACRIFICE -- a hopeless
    hand overtaking at 6 to deny a made contract -- fails 78% with a further
    9% ducking to Null.

    HISTORY, because this number has swung with every re-pricing: +0.97 on the
    N-1 base, -0.13 (knife-edge) after the base moved to N on 2026-08-07, and
    +14.3 under the 2026-08-11 +-10 stake -- the doubled stake pays the
    defender 20 more on a set while the risk only grew 10, so doubling a
    sacrifice now genuinely PAYS instead of breaking even. That is by design:
    the stake is what a sacrificer is gambling with, and Double is how the
    other seat collects it.
    """
    plain, dbl = _terms(6, False), _terms(6, True)
    risk = dbl["make"] - plain["make"]
    def win(short):
        return E.payoff(plain, 6 - short, True) - E.payoff(dbl, 6 - short, True)
    # Measured shortfall medians: ordinary failures 2, sacrifices 4.
    ordinary = 0.56 * win(2) - 0.44 * risk
    sacrifice = 0.78 * win(4) - 0.13 * risk
    assert ordinary < -5, ordinary
    assert sacrifice > 5, f"the ramp must make the sacrifice case pay: {sacrifice}"
    assert sacrifice - ordinary > 15, "...and separate it from an honest contract"
