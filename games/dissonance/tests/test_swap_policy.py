"""The classic talon swap -- the FITTED policy that replaced take-high/give-low.

The old rule measured -0.477 +- 0.226 score/round against standing pat over
3000 paired deals; the fitted one measures +1.500 +- 0.208 against pat and
+1.976 +- 0.194 against the old rule (same harness, same deals). These tests
pin the properties the fit found, so a refactor that quietly restored
rank-maximisation -- which LOOKS sensible and is exactly backwards in a game
where 7 of 13 tricks are penalties -- fails loudly instead of costing two
points a round in silence.

`choose_swap`'s classic branch is a pure function of the denomination, the
hand and `shown`, so most tests build the minimal dict directly; the game-
shaped tests drive real deals.
"""

import random

import pytest

from games.dissonance import bot as B
from games.dissonance import engine as E


def _pos(denom, level, hand, shown):
    return {"auction": {"denom": denom, "level": level},
            "hands": [sorted(hand), []], "shown": list(shown)}


def _card(suit, rank):
    return suit * E.NRANK + rank


# --- the fitted shape ------------------------------------------------------


def test_a_low_card_is_worth_taking_and_a_middle_card_is_not():
    """The oracle's take-histogram is U-SHAPED -- it takes 7s almost as often
    as Aces -- and the old policy could not represent that at all: its worth
    curve was strictly increasing in rank."""
    # Shown: a 7, a 10 and a Jack, all off-trump, same suit. The 7 wins.
    hand = [_card(2, r) for r in range(1, 7)] + [_card(3, 6)]
    sw = B.choose_swap(_pos(0, 3, hand, [_card(1, 0), _card(1, 3), _card(1, 4)]), 0)
    assert sw["take"] == _card(1, 0), f"took {sw['take']}, not the 7"


def test_an_ace_still_outranks_a_seven():
    hand = [_card(2, r) for r in range(1, 7)] + [_card(3, 6)]
    sw = B.choose_swap(_pos(0, 3, hand, [_card(1, 0), _card(1, 7), _card(1, 3)]), 0)
    assert sw["take"] == _card(1, 7)


def test_it_stands_pat_when_no_exchange_clears_the_bar():
    """The oracle stands pat in 35% of decisions; the old policy did in 4%.
    Middle-rank talon against a hand of honours is the textbook pat."""
    hand = [_card(s, r) for s, r in ((0, 6), (0, 7), (1, 6), (1, 7), (2, 6), (2, 7), (3, 7))]
    sw = B.choose_swap(_pos(3, 4, hand, [_card(2, 2), _card(2, 3), _card(1, 2)]), 0)
    assert sw == {"take": None, "give": None}


def test_discarding_a_suits_last_card_beats_an_equal_discard_that_is_not():
    """Shape is value the old rank-only rule could not see: a void lets the
    hand ruff, and the fit priced it at +1.47."""
    # Two candidate discards of the SAME rank: one a singleton, one from a
    # three-card suit. Taking is fixed (one shown card gains).
    hand = [_card(1, 1), _card(2, 1), _card(2, 3), _card(2, 5),
            _card(3, 4), _card(3, 5), _card(3, 6)]
    sw = B.choose_swap(_pos(0, 3, hand, [_card(0, 7), _card(1, 3), _card(1, 4)]), 0)
    assert sw["take"] == _card(0, 7)
    assert sw["give"] == _card(1, 1), "the singleton discard makes a void"


def test_a_trump_is_never_discarded_in_favour_of_an_equal_off_suit_card():
    hand = [_card(0, 1), _card(1, 1), _card(2, 3), _card(2, 5),
            _card(3, 4), _card(3, 5), _card(3, 6)]
    sw = B.choose_swap(_pos(0, 3, hand, [_card(2, 7), _card(1, 3), _card(1, 4)]), 0)
    assert sw["give"] != _card(0, 1), "gave the trump away"


# --- the skat branch is deliberately the OLD rule --------------------------


def test_the_skat_talon_runs_its_own_weights_and_not_classics(monkeypatch):
    """Skat's talon resolves BEFORE the game is named, so it was never allowed
    the classic weights on faith -- it got its own swaplab run and its own fit
    (2026-08-21). This is the marker: if someone unifies the branches, the two
    policies have to be measured to agree first, because they were fitted
    against different information and different card play."""
    monkeypatch.delenv("DIS_SKAT_SWAP_OLD", raising=False)
    assert B._SK_TAKE_W != B._SWAP_TAKE_W
    assert B._SK_GIVE_W != B._SWAP_GIVE_W
    g = {"auction": {"denom": -1, "level": 0, "value": 12},
         "hands": [sorted([_card(2, r) for r in range(7)]), []],
         "shown": [_card(1, 0), _card(1, 7), _card(1, 3)],
         "piles": [[[], [], []], [[], [], []]], "out": []}
    assert B.choose_swap(g, 0, denom=1) != _old_skat_pick(g)


def _old_skat_pick(g, monkey=None):
    """What the separable rank rule would have done: take the highest card
    shown, throw the lowest card held. It cannot express anything else."""
    return {"take": _card(1, 7), "give": _card(2, 0)}


def test_the_old_skat_rule_is_still_reachable_for_the_arena(monkeypatch):
    """`swaparena.py` puts the incumbent in one arm through this flag rather
    than through a copy of the rule in the harness -- a copy measures the copy.
    So the flag has to keep working, and it has to keep meaning what it says."""
    monkeypatch.setenv("DIS_SKAT_SWAP_OLD", "1")
    assert B.skat_swap_old()
    g = {"auction": {"denom": -1, "level": 0, "value": 12},
         "hands": [sorted([_card(2, r) for r in range(7)]), []],
         "shown": [_card(1, 0), _card(1, 7), _card(1, 3)],
         "piles": [[[], [], []], [[], [], []]], "out": []}
    assert B.choose_swap(g, 0, denom=1) == _old_skat_pick(g)


# --- against the real engine ----------------------------------------------


@pytest.mark.parametrize("seed", range(8))
def test_the_chosen_swap_is_always_legal_on_a_real_deal(seed):
    g = E.new_game(["a", "b"], random.Random(9100 + seed), opener=seed % 2)
    rng = random.Random(seed)
    guard = 0
    while g["phase"] not in ("swap", "play", "over") and guard < 40:
        guard += 1
        s = E.turn_seat(g)
        kind, p = B.act(g, s, rng)
        mv = ({"kind": "pass"} if p.get("pass")
              else {"kind": "bid", **{a: b for a, b in p.items() if a != "pass"}}) \
            if kind == "bid" else (p if kind == "move"
                                   else ({"kind": "swap", **p} if kind == "swap" else p))
        E.apply_move(g, g["seats"][s], mv)
    if g["phase"] != "swap":
        return  # this deal's auction path never reached a swap; others do
    decl = g["auction"]["declarer"]
    sw = B.choose_swap(g, decl)
    if sw["take"] is not None:
        assert sw["take"] in g["shown"]
        assert sw["give"] in g["hands"][decl]
    E.apply_swap(g, decl, sw["take"], sw["give"])   # must not raise


# --- skat's FITTED talon, behind its flag ----------------------------------


def test_the_skat_weight_tables_span_every_rank():
    """`E.rank` returns a card's strength on the WIDE deck's scale (0..9), not
    an index into the base deck's 8 ranks, so every rank-indexed table has to be
    `NRANKS` long.

    The first cut of the fitted skat policy sized both tables -- and the fit's
    own feature vector with them -- by `NRANK`, which overlapped the give block
    onto the trump features (one weight meaning both "give a king" and "the take
    is trump") and made the policy raise IndexError the first time it was handed
    an ace. It never reached a test because nothing indexed the tables in the
    suite: the flag was off. This asserts the shape directly."""
    for table in (B._SWAP_TAKE_W, B._SWAP_GIVE_W, B._SK_TAKE_W, B._SK_GIVE_W):
        assert len(table) == E.NRANKS, (len(table), E.NRANKS)
    # ...and the two unreachable wide-deck ranks are the LEADING pair, so a
    # 32-card mode never reads a fitted weight for a card it cannot hold.
    assert E.rank(_card(0, 0)) == E.NEXTRA


def test_the_fitted_skat_talon_is_legal_on_every_real_deal_that_reaches_it(
        monkeypatch):
    """The fitted policy across enough real skat deals to hand it every rank,
    including the ace the first cut of it crashed on -- it was sized by `NRANK`
    and indexed by `E.rank`, and no test caught it because the policy was still
    behind a flag nothing turned on.

    ONE TEST OVER MANY SEEDS RATHER THAN A PARAMETRIZE, because not every
    auction reaches the talon and a per-seed test would have to return early on
    the ones that do not -- a state-reachability skip wearing a pass. Counting
    instead makes the reachability itself an assertion.
    """
    monkeypatch.delenv("DIS_SKAT_SWAP_OLD", raising=False)
    reached, ranks = 0, set()
    for seed in range(40):
        g = E.new_game(["a", "b"], random.Random(9600 + seed), opener=seed % 2,
                       mode="skat")
        rng = random.Random(seed)
        guard = 0
        while g["phase"] not in ("talon", "play", "over") and guard < 40:
            guard += 1
            s = E.turn_seat(g)
            kind, p = B.act(g, s, rng)
            mv = ({"kind": "pass"} if p.get("pass")
                  else {"kind": "bid",
                        **{a: b for a, b in p.items() if a != "pass"}}) \
                if kind == "bid" else (p if kind == "move"
                                       else ({"kind": "swap", **p}
                                             if kind == "swap" else p))
            E.apply_move(g, g["seats"][s], mv)
        if g["phase"] != "talon":
            continue
        reached += 1
        decl = g["auction"]["declarer"]
        if not g.get("looked"):
            E.apply_move(g, g["seats"][decl], {"kind": "look"})
        ranks |= {E.rank(c) for c in g["shown"]} | {E.rank(c)
                                                    for c in g["hands"][decl]}
        sw = B.choose_swap(g, decl)
        if sw["take"] is not None:
            assert sw["take"] in g["shown"]
            assert sw["give"] in g["hands"][decl]
        E.apply_swap(g, decl, sw["take"], sw["give"])   # must not raise
    assert reached >= 20, reached
    # EVERY RANK A 32-CARD DECK HOLDS was scored at least once. Without this the
    # test could pass having never handed the tables their top index, which is
    # precisely the read that used to raise.
    assert ranks == set(range(E.NEXTRA, E.NRANKS)), sorted(ranks)


def test_the_flag_is_what_decides_which_skat_policy_runs(monkeypatch):
    """A flag that changes nothing is a flag nobody can trust. This pins that
    the two branches actually disagree on a hand where they should: the old rule
    throws the lowest card held, and the fitted one will not throw a 7 -- a 7 is
    a -1 card, and the whole point of the talon is that a discard leaves play,
    so a liability is what belongs in it."""
    hand = sorted([_card(2, r) for r in range(6)] + [_card(3, 7)])
    g = {"auction": {"denom": -1, "level": 0, "value": 12, "declarer": 0},
         "hands": [hand, []],
         "shown": [_card(1, 0), _card(1, 7), _card(1, 3)],
         "piles": [[[], [], []], [[], [], []]], "out": []}
    monkeypatch.delenv("DIS_SKAT_SWAP_OLD", raising=False)
    assert not B.skat_swap_old()
    fit = B.choose_swap(dict(g), 0, denom=1)
    monkeypatch.setenv("DIS_SKAT_SWAP_OLD", "1")
    assert B.skat_swap_old()
    old = B.choose_swap(dict(g), 0, denom=1)
    assert old != fit
    assert E.rank(old["give"]) == E.rank(_card(0, 0))     # the lowest held
    assert E.rank(fit["give"]) != E.rank(_card(0, 0))
