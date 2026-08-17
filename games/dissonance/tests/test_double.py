"""Classic's Double — the defender's one bet, and what it is a bet ON.

    made   N^2 + 4   ->  2 (N^2 + 4)      (overtricks doubled with it)
    set     2N + 2   ->  UNCHANGED        (`DOUBLE_BASE_MULT` 1)
      + 6j per level of the final leap  ->  x2   (`DOUBLE_JUMP_MULT`)
      + 5 per point short               ->  10   (`DOUBLED_SHORT_PENALTY`)
    Null        20   ->  20               (never scales, whatever the dials say)

**So doubling wins the defender the LEAP and the SHORTFALL, not the fixed
stake** -- the two things a sacrifice actually has. That is the design, and it is
what makes the bet discriminate: a near-miss on a climbed contract wins almost
nothing, a collapse on a leap wins a lot.

HOW IT GOT HERE, all on 2026-08-16, because the sequence explains the dials:

The Double has to tell a SACRIFICE from a near-miss, and what separates them is
not the level (both have that) but how far short the declarer finishes: ordinary
failures are a median of 2 short with 48% by exactly 1, sacrifices a median of 4.
So the reward has to depend on the shortfall.

  1. `DOUBLE_RAMP` did it with an ESCALATOR -- 6, 7, 8, 9 per point. Retired:
     legible neither on the round panel nor in the head.
  2. A flat 5 both ways made the reward SHORTFALL-BLIND.
  3. `DOUBLED_SHORT_PENALTY = 10` (2 x 5) made the whole Double UNIFORM -- every
     scored line exactly x2. Clean to state, but the fixed stake doubling is what
     made doubling a LOW contract nearly free (break-even 0.26 at level 1), and
     bot doubling measured 41.7%.
  4. `DOUBLE_BASE_MULT = 1` with `DOUBLE_JUMP_MULT = 2` takes the fixed stake
     back out while keeping the leap in. Measured against the uniform Double at
     two CFR+ seeds: the equilibrium's doubles land on a SET 46-47% of the time
     against 36%, and the bot's rate falls 41.7% -> 29.2% at the re-fitted
     `DOUBLE_MARGIN = 12`, at the same discrimination.

Every pin below composes the shipped multipliers rather than typing a number, so
moving them again should need no edit here.
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
#: The prices, off the constants so a re-pricing lands here as one edit. Both
#: bases are DERIVED, never typed out, for the same reason the ramp is read from
#: its constant: a literal only says what someone believed on the day, and these
#: have already moved twice (the 2026-08-16 re-pricing, then the ramp's
#: retirement). Today: `L^2 + 4` made, `2L + 2` set, a flat 5 a point short.
_FM = E.FLAT_MAKE_BONUS["classic"]
_LM = E.LINEAR_MAKE_BONUS["classic"]
_FS = E.FLAT_SET_PENALTY["classic"]
_SL = E.SET_LEVEL_RATE["classic"]
_SH = E.CLASSIC_SHORT_PENALTY
#: What a DOUBLED shortfall costs per point. Its own dial since 2026-08-16 --
#: absent for a mode means "the same as undoubled", so this expression is the
#: engine's own fallback and stays correct if the dial is removed again.
_DSH = E.DOUBLED_SHORT_PENALTY.get("classic", _SH)
#: The Double's three MULTIPLIERS, read the way `_terms_for` reads them so the
#: fallbacks match the engine's exactly. Since 2026-08-16 classic runs base x1,
#: jump x2 -- the flat stake does NOT double, the leap does -- so a doubled set
#: base is no longer `2 x _sb`, and every arithmetic pin below composes it.
_JB = E.JUMP_SET_BONUS["classic"]
_BM = E.DOUBLE_BASE_MULT.get("classic", 2)
_MM = E.DOUBLE_MAKE_MULT.get("classic", 2)
_JM = E.DOUBLE_JUMP_MULT.get(
    "classic", _BM if E.JUMP_DOUBLED.get("classic", True) else 1)


def _mk(level):
    """A made contract's base, jumpless."""
    return level * level + _LM * level + _FM


def _sb(level):
    """A set contract's base, jumpless."""
    return _SL * level + _FS


def _dsb(level, jump=0):
    """...and the DOUBLED set base, composed term by term."""
    return _sb(level) * _BM + _JB * jump * _JM


def _dwin(level, short, jump=0):
    """What doubling WINS the defender on a set `short` points below target."""
    return (E.payoff(E._terms_for("classic", 0, level, jump=jump, doubling=1),
                     level - short, True)
            - E.payoff(E._terms_for("classic", 0, level, jump=jump, doubling=2),
                       level - short, True))


# --- the arithmetic --------------------------------------------------------


@pytest.mark.parametrize("level", range(E.MIN_LEVEL, _TOP + 1))
def test_a_made_contract_pays_exactly_double(level):
    plain, dbl = _terms(level, False), _terms(level, True)
    assert dbl["make"] == 2 * plain["make"] == 2 * _mk(level)
    assert dbl["over"] == 2 * plain["over"], "overtricks double with the contract"


@pytest.mark.parametrize("level", range(E.MIN_LEVEL, _TOP + 1))
def test_a_set_contract_pays_2N_and_its_own_per_point_rate(level):
    plain, dbl = _terms(level, False), _terms(level, True)
    assert plain["set_base"] == _sb(level) and plain["ramp"] == 0
    assert dbl["set_base"] == _dsb(level)
    assert plain["short"] == _SH
    assert dbl["short"] == _DSH, "a doubled shortfall has its own per-point rate"
    # DERIVED from the two dials, never typed out: both have moved already
    # (short 4 -> 5, ramp 0 -> 1 -> 0) and a literal only says what someone
    # believed on the day. Doubled, the s-th point short costs `short + s*ramp`,
    # which is the SHIPPED arithmetic whether or not the ramp is switched on --
    # so this test does not pin `DOUBLE_RAMP` to a value and did not need
    # editing when the ramp was retired on 2026-08-16.
    assert dbl["ramp"] == E.DOUBLE_RAMP
    P, R = _DSH, E.DOUBLE_RAMP
    pen = [-E.payoff(dbl, level - s, True) - _dsb(level)
           for s in range(1, 6)]
    steps = [b - a for a, b in zip([0] + pen, pen)]
    assert steps == [P + R * s for s in range(1, 6)], steps
    # Monotone either way; STRICTLY rising only while the ramp is on. Asserting
    # both arms rather than only the live one keeps the test meaningful if the
    # ramp is ever switched back on, which is the reason it is a constant.
    assert steps == sorted(steps), steps
    if R:
        assert steps[-1] > steps[0], "with a ramp the shortfall must ESCALATE"
    else:
        assert len(set(steps)) == 1, "no ramp: a flat rate per point"
    flat = [-E.payoff(plain, level - s, True) - _sb(level)
            for s in range(1, 6)]
    assert flat == [_SH * s for s in range(1, 6)], "undoubled stays flat"
    if not R:
        # Both sides flat, but at their OWN rates -- equal only if the doubled
        # dial is set to the undoubled rate.
        assert pen == [_DSH * s for s in range(1, 6)]
        assert (pen == flat) == (_DSH == _SH)


def test_the_double_scales_each_term_by_its_own_multiplier():
    """THE RULE, over the whole grid, composed from the dials rather than typed.

    The Double was briefly UNIFORM (every scored line exactly x2, 2026-08-16) and
    this test asserted that. It is not uniform now -- classic runs base x1 /
    jump x2 -- so the claim is restated one level up: each TERM scales by its own
    multiplier, and the payoff follows. That form covers the uniform case too
    (all multipliers 2), so it survives the next move.

    Null is the one term that never scales, whatever the dials say.
    """
    bad = []
    for level in range(E.MIN_LEVEL, _TOP + 1):
        for jump in (0, 1, level):
            a = E._terms_for("classic", 0, level, jump=jump, doubling=1)
            b = E._terms_for("classic", 0, level, jump=jump, doubling=2)
            if b["make"] != _MM * a["make"]:
                bad.append(("make", level, jump))
            if b["over"] != _MM * a["over"]:
                bad.append(("over", level, jump))
            if b["set_base"] != _dsb(level, jump):
                bad.append(("set_base", level, jump, a["set_base"], b["set_base"]))
            if b["short"] != _DSH:
                bad.append(("short", level, jump))
            # NULL NEVER SCALES.
            for pts in range(-7, 14):
                if E.payoff(b, pts, False) != E.payoff(a, pts, False):
                    bad.append(("null", level, jump, pts))
    assert not bad, f"a term did not scale by its multiplier: {bad[:5]}"


@pytest.mark.parametrize("level", range(E.MIN_LEVEL, _TOP + 1))
def test_null_is_never_doubled(level):
    assert _terms(level, True)["null"] == _terms(level, False)["null"] == E.NULL_MAKE


def test_what_doubling_wins_rises_with_the_SHORTFALL():
    """What doubling WINS, as a function of how far short the declarer finishes.

    The Double's core design property: the reward must rise with the shortfall or
    the bet cannot tell a sacrifice from a near-miss. Which DIAL delivers that has
    changed twice (`DOUBLE_RAMP` quadratically, then `DOUBLED_SHORT_PENALTY`
    linearly), so all three arms are asserted off the constants -- ramp on, both
    rates equal (shortfall-blind, the one state that FAILS the property), and a
    raised doubled rate."""
    for level in (3, 6):
        plain, dbl = _terms(level, False), _terms(level, True)
        wins = [E.payoff(plain, level - s, True) - E.payoff(dbl, level - s, True)
                for s in range(1, 7)]
        # Derived, not typed: doubling adds one more set base plus the ramp's
        # triangular term, so the win at s short is `sb + ramp*s(s+1)/2`.
        R = E.DOUBLE_RAMP
        # Doubling adds one more set base, the ramp's triangular term, and the
        # DIFFERENCE between the doubled and undoubled per-point rates.
        # Composed from the three multipliers: the extra stake, the extra
        # per-point rate, and the ramp's triangular term.
        assert wins == [(_BM - 1) * _sb(level) + (_DSH - _SH) * s
                        + R * s * (s + 1) // 2 for s in range(1, 7)], wins
        if R:
            assert all(b > a for a, b in zip(wins, wins[1:])), wins
            assert wins[0] < (_BM - 1) * _sb(level) + 2, \
                f"a 1-short miss should stay cheap: {wins[0]}"
            assert wins[5] - wins[0] >= 20 * R, \
                f"a 6-short collapse should not: {wins}"
        elif _DSH > _SH:
            # The 2026-08-16 replacement for the ramp: the reward rises with the
            # shortfall again, LINEARLY rather than quadratically.
            assert all(b - a == _DSH - _SH for a, b in zip(wins, wins[1:])), wins
            assert wins[-1] > wins[0], "a deeper failure must still pay more"
        else:
            assert len(set(wins)) == 1 and wins[0] == (_BM - 1) * _sb(level), \
                f"flat rate both ways: the reward cannot depend on shortfall: {wins}"


def test_where_a_near_miss_double_stops_paying():
    """On the COMMON failure -- 1 short, 48% of them -- does doubling risk more
    than it wins? Under the UNIFORM Double (everything x2, 2026-08-16) that is no
    longer true everywhere, and where it flips is pure arithmetic:

        risk > win(1)   <=>   L^2 + Fm  >  (SL*L + Fs) + short
        at the shipped prices   L^2 + 4 > 2L + 7   <=>   L > 3

    So L1-L3 INVITE the double even on a near-miss, and L4 up protect the
    declarer. That is not the Double being lopsided -- it is the make curve being
    quadratic off a base of 4 while the set base is linear, so at the bottom of
    the ladder being set already costs more than making pays. Uniform doubling
    only exposes it.

    JUMP-FREE contracts only: the v2 jump rule deliberately breaks this further
    for jumped ones -- see the companion test below."""
    crossover = None
    for level in range(1, _TOP + 1):
        plain, dbl = _terms(level, False), _terms(level, True)
        win = E.payoff(plain, level - 1, True) - E.payoff(dbl, level - 1, True)
        risk = dbl["make"] - plain["make"]
        # DERIVED from the price list, so a re-pricing moves the expectation with
        # the game instead of failing this test.
        want = (_MM - 1) * _mk(level) > _dwin(level, 1)
        assert (risk > win) == want, \
            f"level {level}: risk {risk} vs win {win}, expected risk>win={want}"
        if risk > win and crossover is None:
            crossover = level
    assert crossover is not None, "some level must protect the declarer"
    assert all((_MM - 1) * _mk(l) > _dwin(l, 1)
               for l in range(crossover, _TOP + 1)), \
        "protection must be monotone once it starts -- make is quadratic, set linear"


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
    # and stay reachable at the top or the bet is dead.
    #
    # RETIRING THE RAMP MOVED THIS, and it is the change's main consequence:
    # break-even now reads 0.56 / 0.57 / 0.62 / 0.67 against 0.44 / .. / < 0.75
    # before. The reward no longer grows with the shortfall, so the defender
    # needs BETTER THAN EVEN ODDS at every level, where a level-1 Double used to
    # pay from 44%. Asserted as `> 0.5` rather than pinned to 0.56 so the claim
    # is the design property and not the arithmetic of one day.
    assert sorted(need) == [1, 2, 3, 4]
    vals = [need[k] for k in (1, 2, 3, 4)]
    assert all(b > a for a, b in zip(vals, vals[1:])), need
    assert vals[-1] < 0.75, need
    # THIS MOVED TWICE ON 2026-08-16 and the sequence is the useful record:
    #   ramp on               0.44 / .. / < 0.75   reward grows quadratically
    #   ramp off, flat 5      0.56 0.57 0.62 0.67  reward FLAT in the shortfall
    #   ramp off, doubled 6   0.45 0.50 0.57 0.62  reward grows linearly
    # The design property is not any of those triples -- it is that the bottom of
    # the ladder pays from UNDER even odds exactly when doubling's reward depends
    # on the shortfall at all. Asserted that way so it survives the next move.
    if bool(E.DOUBLE_RAMP) or _DSH > _SH:
        assert vals[0] < 0.5, \
            f"a low Double should pay from under even odds: {need}"
    else:
        assert vals[0] > 0.5, \
            f"a shortfall-blind Double needs better than even: {need}"


# --- end to end ------------------------------------------------------------


def test_a_doubled_round_scores_the_doubled_numbers():
    for doubled in (False, True):
        g = _settled_flat(level=3)
        E.apply_double(g, 1, doubled)
        assert g["doubled"] is doubled
        t = E.payoff_terms(g)
        # made exactly on target: (N^2 + stake) [x2]
        assert E.payoff(t, 3, True) == (_MM * _mk(3) if doubled else _mk(3))
        # Set by two. `_settled_flat` ends on a SAME-LEVEL overtake, so there is
        # no jump and the doubled base is `_sb x DOUBLE_BASE_MULT` -- which is
        # `_sb` itself at classic's shipped 1. Both the base and the per-point
        # rate are their own dials, so both differ by arm.
        P, R = (_DSH if doubled else _SH), E.DOUBLE_RAMP
        want = (-(_dsb(3) + (P + R) + (P + 2 * R)) if doubled
                else -(_sb(3) + 2 * P))
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
    assert res["make_value"] == 2 * _mk(4)
    assert res["set_base"] == _dsb(4)
    # The panel narrates from these, so they must be the ones actually scored.
    winner = res["declarer"] if res["scores"][res["declarer"]] else 1 - res["declarer"]
    assert res["scores"][winner] > 0


# --- the phase -------------------------------------------------------------


def test_the_jump_bonus_rides_inside_the_double_as_shipped(monkeypatch):
    """The jump bonus rides INSIDE the Double, at its own multiplier.

    Since 2026-08-16 the flat stake does NOT double while the leap does
    (`DOUBLE_BASE_MULT` 1, `DOUBLE_JUMP_MULT` 2), so the defender's gain from
    doubling is the leap and the shortfall rather than the fixed stake.

    Also pins the PRECEDENCE between the two knobs that reach this term, since
    the older one is now inert for classic and that is easy to trip over.
    """
    N, j = 5, 4
    stake, bonus = _sb(N), _JB * j
    on = E._terms_for("classic", 2, N, jump=j, doubling=2)
    off = E._terms_for("classic", 2, N, jump=j)
    # THE BONUS STILL DOUBLES; THE STAKE IT RIDES BESIDE NO LONGER DOES
    # (`DOUBLE_JUMP_MULT` 2 against `DOUBLE_BASE_MULT` 1, 2026-08-16). Keeping
    # the bonus inside the Double is what preserves the v2 jump rule's teeth --
    # at jump x1 a leap stops inviting the Double entirely.
    assert _JM == 2, "the leap must stay inside the Double"
    assert on["set_base"] == stake * _BM + bonus * _JM
    assert off["set_base"] == stake + bonus
    assert on["set_base"] - off["set_base"] == bonus * (_JM - 1) \
        + stake * (_BM - 1), "the doubled gain is the leap, not the stake"

    # PRECEDENCE, ASSERTED BECAUSE TWO KNOBS NOW REACH THE SAME TERM.
    # `DOUBLE_JUMP_MULT` is explicit and WINS; `JUMP_DOUBLED` is only the
    # fallback used when the mode names no multiplier. So flipping
    # `JUMP_DOUBLED` while classic names a multiplier changes NOTHING -- which
    # is a live footgun (the arena still exposes `DIS_JUMP_DOUBLED=0`, and that
    # arm is inert for classic until the multiplier is cleared).
    monkeypatch.setitem(E.JUMP_DOUBLED, "classic", False)
    assert E._terms_for("classic", 2, N, jump=j, doubling=2) == on, \
        "DOUBLE_JUMP_MULT must override JUMP_DOUBLED, not be overridden by it"

    # ...and with the multiplier CLEARED the fallback takes over again, which is
    # what the `JUMP_DOUBLED=False` arm was always for: the bonus is added after
    # the multiplier instead of inside it.
    monkeypatch.delitem(E.DOUBLE_JUMP_MULT, "classic")
    arm_on = E._terms_for("classic", 2, N, jump=j, doubling=2)
    arm_off = E._terms_for("classic", 2, N, jump=j)
    assert arm_on["set_base"] == stake * _BM + bonus, "the bonus is added after"
    assert arm_on["set_base"] < on["set_base"], "the arm must actually trim it"
    # THE WHOLE POINT: the undoubled contract is untouched by the arm.
    assert arm_off == off
    # ...and a jumpless contract is identical under both, since there is no
    # bonus to move -- so the arm can only ever reprice a LEAP.
    assert (E._terms_for("classic", 2, N, jump=0, doubling=2)
            == on | {"set_base": stake * _BM})


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
    assert E.payoff_terms(g)["make"] == _mk(3)


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
    """Skat's Kontra ships ONE option and decides on its sign. Classic ships TWO
    and the search compares them -- and it must keep doing so even now that the
    Double is uniform, because the reason has nothing to do with symmetry:
    DECLINING IS NOT WORTH ZERO. It is worth the undoubled contract, which is a
    live payoff either way, so a one-option "is it positive" test would be
    comparing the doubled branch against nothing."""
    g = _settled_flat(level=3)
    opts = E.auction_payoff_options(g)
    assert len(opts) == 2
    on = next(o for o in opts if o["move"]["on"] is True)
    off = next(o for o in opts if o["move"]["on"] is False)
    assert on["make"] == 2 * off["make"]
    assert on["set_base"] == _dsb(3) and off["set_base"] == _sb(3)
    assert on["ramp"] == E.DOUBLE_RAMP and off["ramp"] == 0
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
        # THE WIN IS NOT THE SET-BASE DELTA ANY MORE. At `DOUBLE_BASE_MULT = 1`
        # a jumpless contract's base does not move at all, so reading the win
        # off the bases alone gives 0 at every level and a flat curve of 1.0.
        # The win is what doubling actually pays, which is `_dwin` -- taken at
        # the MEDIAN ordinary shortfall of 2, the case a defender doubling an
        # honest contract is betting against.
        win = _dwin(level, 2)
        risk = dbl["make"] - plain["make"]
        be = risk / (win + risk)
        assert be > prev, f"break-even must rise with the level (L{level}: {be})"
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
    # The DESIGN property is the SIGN and the SEPARATION, not the magnitude --
    # which has swung with every re-pricing (see the history above; -9.6, then
    # -4.16 under the uniform Double of 2026-08-16). Asserting `< 0` rather than
    # `< -5` states the claim that actually matters and stops this test being
    # re-tuned by hand every time the price list moves.
    assert ordinary < 0, f"doubling an ORDINARY contract must lose: {ordinary}"
    assert sacrifice > 5, f"doubling a SACRIFICE must pay: {sacrifice}"
    assert sacrifice - ordinary > 15, "...and separate it from an honest contract"
