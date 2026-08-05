"""THE DEBT VECTOR (phase 7H) — the cost dimension no shipped card uses yet.

7H is hardening, in the 3H/5H/6H mold: it changes no card and no game we can
play today. No card in `CARDS` and no Event in `LANDSCAPES` has a `debt` key, so
nothing on any board can hand you a token — which means "the existing suite
still passes" proves only that the refactor changed nothing. The other half of
the job is that the thing it was built for works, and that is what this file is.

Every test injects a SYNTHETIC Debt-costed card or Event into `CARDS` /
`LANDSCAPES` for its duration (the 6H fixture pattern), so all of it runs
against the real kernel with zero real consumers. The day Empires lands, these
paths are already exercised rather than merely existing.

The rules pinned here are DEBT § IV (p30), quoted in the docstrings:

  * a cost is the vector {coins, potions, debt}, compared component-wise;
  * buying a Debt-costed thing PAYS the coins and TAKES the Debt;
  * "when you have Debt tokens, you can't buy anything (cards, Events or
    Projects). This is the only effect of having Debt";
  * "you may pay off Debt by paying $1 per token ... at any time during your
    turn", using up no Buy — the 2024 change, which card-list sites and the
    2016 rulebook still describe the old way;
  * "gaining a Debt-cost card without buying it doesn't give you Debt";
  * "you can't overpay with Debt (since you don't pay with Debt)".
"""

import copy
import json
import random
from collections import Counter

import pytest

from games.dontminion import bot, cards, effects, engine

A, B = "alice", "bob"
K10 = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room",
       "Gardens", "Market", "Cellar", "Festival"]

# The synthetic Debt-costed cards. Real card shapes, invented names — nothing in
# cards.py changes, and each one exists only for the test that asks for it.
DEBT_CARDS = {
    # {$2, 4D}: the mixed cost the compendium's own example uses
    "Tollgate": {"cost": 2, "debt": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+2 Cards.", "expansion": "base", "kingdom": True},
    # a PURE Debt cost — {$0, 8D}, buyable with no money at all
    "Obligation": {"cost": 0, "debt": 8, "types": ["action"], "coins": 0, "vp": 0,
                   "text": "+1 Card. +1 Action.", "expansion": "base", "kingdom": True},
    # {$4, 0D} and {$4, 4D}: the pair the vector rules are stated against
    "Plainfour": {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                  "text": "+1 Card.", "expansion": "base", "kingdom": True},
    "Fourfour": {"cost": 4, "debt": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Card.", "expansion": "base", "kingdom": True},
    "Plainfive": {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                  "text": "+1 Card.", "expansion": "base", "kingdom": True},
    # {$3, 2D} + the two cards a "up to $2 more than it" window should admit
    "Threetwo": {"cost": 3, "debt": 2, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Card.", "expansion": "base", "kingdom": True},
    "Fivetwo": {"cost": 5, "debt": 2, "types": ["action"], "coins": 0, "vp": 0,
                "text": "+1 Card.", "expansion": "base", "kingdom": True},
    "Fivethree": {"cost": 5, "debt": 3, "types": ["action"], "coins": 0, "vp": 0,
                  "text": "+1 Card.", "expansion": "base", "kingdom": True},
    # an OVERPAY card that also costs Debt — "you can't overpay with Debt"
    "Tollbooth": {"cost": 2, "debt": 3, "overpay": True, "types": ["action"],
                  "coins": 0, "vp": 0, "text": "+1 Card. Overpay: nothing.",
                  "expansion": "base", "kingdom": True},
}

# A synthetic Debt-costed EVENT and a plain one (Empires has Triumph, Annex,
# Ritual). Same shape as the 6H landscape fixtures.
DEBT_LANDSCAPES = {
    "Levy": {"kind": "event", "cost": 0, "debt": 5, "expansion": "base",
             "text": "+1 Buy."},
    "Tithe": {"kind": "event", "cost": 3, "debt": 2, "expansion": "base",
              "text": "+$1."},
    "Errand": {"kind": "event", "cost": 2, "expansion": "base", "text": "+1 Buy."},
}


@pytest.fixture
def reg():
    """Temporary CARDS / LANDSCAPES / registry entries, restored afterwards.
    These are module-level dicts the engine reads BY REFERENCE, so tests mutate
    them in place — a rebind would leave engine.py's own `from .cards import
    LANDSCAPES` pointing at the original object."""
    saved = (dict(cards.CARDS), dict(cards.LANDSCAPES), dict(effects.EFFECTS),
             dict(effects.LANDSCAPE_FX), dict(effects.LANDSCAPE_SCORING),
             dict(effects.LANDSCAPE_SETUP),
             {k: list(v) for k, v in effects.TRIGGERS.items()},
             dict(effects.STAGES))
    cards.CARDS.update(copy.deepcopy(DEBT_CARDS))
    cards.LANDSCAPES.update(copy.deepcopy(DEBT_LANDSCAPES))
    # every synthetic is an Action, so each needs a play ability or the kernel
    # KeyErrors the moment a random game buys one and plays it
    for name in DEBT_CARDS:
        effects.EFFECTS.setdefault(name, lambda game, pid: engine.draw(game, pid, 1))
    yield effects
    for store, old in ((cards.CARDS, saved[0]), (cards.LANDSCAPES, saved[1]),
                       (effects.EFFECTS, saved[2]),
                       (effects.LANDSCAPE_FX, saved[3]),
                       (effects.LANDSCAPE_SCORING, saved[4]),
                       (effects.LANDSCAPE_SETUP, saved[5]),
                       (effects.TRIGGERS, saved[6]), (effects.STAGES, saved[7])):
        store.clear()
        store.update(old)


def fresh(kingdom=tuple(K10), landscapes=None, players=(A, B), seed=42):
    return engine.new_game(list(players), ["base"], seed=seed,
                           kingdom=list(kingdom), landscapes=landscapes)


def buy_phase(g, pid=A, coins=20, buys=1):
    g["turn"] = pid
    g["phase"] = "buy"
    g["coins"] = coins
    g["buys"] = buys
    g["pending"] = []
    engine._sync_pending(g)


def events(g, name):
    return [e for e in g["log"] if e.get("event") == name]


# ── the cost VECTOR, verbatim from DEBT § IV p30 ──────────────────────────────

def test_debt_is_the_printed_cost_and_no_reduction_ever_touches_it(reg):
    """"Debt functions like another kind of cost, just like Potion" and "cards
    that reduce $ costs (like Bridge) don't affect Debt costs"."""
    g = fresh(kingdom=["Tollgate", "Bridge", "Quarry"] + K10[:7])
    assert engine.debt_cost(g, "Tollgate") == 4
    assert engine.cost(g, "Tollgate") == 2
    g["turn_ctx"]["bridges"] = 2                 # two Bridges played
    g["turn_ctx"]["quarries"] = 1                # ...and a Quarry on the table
    assert engine.cost(g, "Tollgate") == 0       # coins floor at 0
    assert engine.debt_cost(g, "Tollgate") == 4, "a reduction reached the Debt"
    # ...and the Adventures -$2 pile token doesn't reach it either
    g["turn_ctx"]["bridges"] = 0
    g["turn_ctx"]["quarries"] = 0
    engine.move_token(g, A, "-cost", "Tollgate")
    assert engine.cost(g, "Tollgate") == 0
    assert engine.debt_cost(g, "Tollgate") == 4


def test_a_card_with_no_debt_key_costs_zero_debt(reg):
    g = fresh()
    for c in ("Copper", "Province", "Village", "Curse"):
        assert engine.debt_cost(g, c) == 0


def test_both_four_and_fourdebt_are_lower_than_four_and_fourdebt(reg):
    """"Both {$4} and {4D} are lower than {$4, 4D}." — the compendium's own
    worked comparison, played straight."""
    g = fresh(kingdom=["Plainfour", "Fourfour", "Obligation"] + K10[:7])
    assert engine.cost_lt_card(g, "Plainfour", "Fourfour")   # {$4} < {$4,4D}
    assert engine.cost_lt_card(g, "Obligation", "Fourfour") is False, \
        "{$0,8D} is not lower than {$4,4D} — its Debt component is HIGHER"
    # the {4D} half of the quote, with a synthetic that really is {$0,4D}
    cards.CARDS["Fourdebt"] = {"cost": 0, "debt": 4, "types": ["action"],
                               "coins": 0, "vp": 0, "text": "", "expansion": "base",
                               "kingdom": True}
    assert engine.cost_lt_card(g, "Fourdebt", "Fourfour")


def test_five_and_fourdebt_are_incomparable_in_both_directions(reg):
    """"However, {$5} is not lower than {$4, 4D} (nor vice versa)." A vector is
    lower only if NO component is higher and at least one is lower."""
    g = fresh(kingdom=["Plainfive", "Fourfour"] + K10[:8])
    assert engine.cost_lt_card(g, "Plainfive", "Fourfour") is False
    assert engine.cost_lt_card(g, "Fourfour", "Plainfive") is False


def test_up_to_a_number_excludes_every_debt_cost(reg):
    """"Up to $N" is an UPPER bound on the whole vector, so a Debt component
    puts a card out of reach of every plain "costing up to $N" — the same rule
    that makes Workshop miss a Familiar."""
    g = fresh(kingdom=["Tollgate", "Obligation", "Plainfour"] + K10[:7])
    assert engine.cost_le(g, "Plainfour", 4)
    assert engine.cost_le(g, "Tollgate", 4) is False, "$2 + 4D is not 'up to $4'"
    assert engine.cost_le(g, "Tollgate", 99) is False
    assert engine.cost_le(g, "Obligation", 8) is False
    # ...and so do the other two number forms
    assert engine.cost_eq(g, "Tollgate", 2) is False
    assert engine.cost_lt(g, "Tollgate", 5) is False
    assert engine.cost_eq(g, "Plainfour", 4) and engine.cost_lt(g, "Plainfour", 5)


def test_cost_ge_reads_the_coin_component_alone(reg):
    """A5, which Debt inherits from Potion unchanged: the compendium states the
    exclusion rule for UPPER bounds only, so "costing $2 or more" finds a
    {$2,4D} card. A range (Knights' "$3 to $6") still excludes it, because its
    cost_le half does."""
    g = fresh(kingdom=["Tollgate", "Obligation"] + K10[:8])
    assert engine.cost_ge(g, "Tollgate", 2)
    assert engine.cost_ge(g, "Tollgate", 3) is False
    assert engine.cost_ge(g, "Obligation", 0)
    # the range form still keeps it out
    assert not (engine.cost_ge(g, "Tollgate", 2) and engine.cost_le(g, "Tollgate", 6))


def test_exactly_more_than_a_card_requires_MATCHING_debt(reg):
    """"Costing exactly $1 more" means "having the same cost plus $1", so the
    Debt component must MATCH — the Potion rule, one dimension over."""
    g = fresh(kingdom=["Threetwo", "Fivetwo", "Plainfive", "Fivethree"] + K10[:6])
    assert engine.cost_eq_card(g, "Fivetwo", "Threetwo", 2)      # {$5,2D} = {$3,2D}+$2
    assert engine.cost_eq_card(g, "Plainfive", "Threetwo", 2) is False
    assert engine.cost_eq_card(g, "Fivethree", "Threetwo", 2) is False
    assert engine.cost_eq_card(g, "Fivetwo", "Plainfive", 0) is False


def test_up_to_more_than_a_card_caps_the_debt_at_the_references(reg):
    """"Up to $2 more than {$3,2D}" means "up to {$5,2D}": the Debt component
    may not be HIGHER than the reference's, but it may be lower."""
    g = fresh(kingdom=["Threetwo", "Fivetwo", "Plainfive", "Fivethree"] + K10[:6])
    assert engine.cost_le_card(g, "Fivetwo", "Threetwo", 2)      # exactly {$5,2D}
    assert engine.cost_le_card(g, "Plainfive", "Threetwo", 2)    # {$5,0D}: lower Debt
    assert engine.cost_le_card(g, "Fivethree", "Threetwo", 2) is False, \
        "{$5,3D} is not 'up to $2 more than {$3,2D}'"


# ── buying: pay the coins, take the Debt ──────────────────────────────────────

def test_buying_a_debt_costed_card_pays_the_coins_and_takes_the_tokens(reg):
    """"You don't pay anything to cover the Debt cost. Instead you take that
    many Debt tokens. (If the cost also includes $, you have to pay that.)"""
    g = fresh(kingdom=["Tollgate"] + K10[:9])
    buy_phase(g, A, coins=5, buys=2)
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": "Tollgate"})
    assert ok, err
    assert g["coins"] == 3, "only the COIN component is paid"
    assert g["debt"][A] == 4
    assert g["buys"] == 1, "a Debt-costed buy still uses up a Buy"
    assert g["turn_ctx"]["bought"] is True
    assert "Tollgate" in g["seats"][A]["discard"], "the card was still gained"
    assert events(g, "debt")[-1]["count"] == 4


def test_a_pure_debt_card_is_buyable_with_no_money_at_all(reg):
    g = fresh(kingdom=["Obligation"] + K10[:9])
    buy_phase(g, A, coins=0, buys=1)
    assert {"type": "buy", "card": "Obligation"} in engine.legal_moves(g, A)
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": "Obligation"})
    assert ok, err
    assert g["coins"] == 0 and g["debt"][A] == 8


def test_buying_a_debt_costed_event_takes_the_debt_too(reg):
    """Empires' Debt-costed Events (Triumph, Annex, Ritual). A landscape's
    price is the PRINTED one in BOTH components."""
    reg.LANDSCAPE_FX["Tithe"] = lambda game, pid: engine.add_coins(game, 1)
    g = fresh(landscapes=["Tithe"])
    buy_phase(g, A, coins=5, buys=1)
    ok, err = engine.apply_move(g, A, {"type": "buy_landscape", "name": "Tithe"})
    assert ok, err
    assert g["coins"] == 3          # 5 - $3 paid, + $1 from the ability
    assert g["debt"][A] == 2
    assert g["buys"] == 0


def test_a_free_but_debt_costed_event_is_buyable_with_no_money(reg):
    g = fresh(landscapes=["Levy"])
    buy_phase(g, A, coins=0, buys=1)
    assert {"type": "buy_landscape", "name": "Levy"} in engine.legal_moves(g, A)
    ok, err = engine.apply_move(g, A, {"type": "buy_landscape", "name": "Levy"})
    assert ok, err
    assert g["debt"][A] == 5


def test_a_bridge_never_discounts_a_landscapes_debt(reg):
    """A landscape's cost "cannot be changed by cards like Bridge" — which now
    has to hold for its Debt half too."""
    g = fresh(landscapes=["Tithe"])
    buy_phase(g, A, coins=9, buys=1)
    g["turn_ctx"]["bridges"] = 3
    engine.apply_move(g, A, {"type": "buy_landscape", "name": "Tithe"})
    assert g["coins"] == 6 and g["debt"][A] == 2


# ── the gate: "you can't buy ANYTHING" ────────────────────────────────────────

def test_one_debt_token_blocks_every_card_and_every_event(reg):
    """"When you have Debt tokens, you can't buy anything (cards, Events or
    Projects). This is the only effect of having Debt." One token is enough,
    and it binds BOTH handlers — which is also how ph. 9's Projects are covered,
    since they buy through the landscape handler."""
    g = fresh(landscapes=["Errand"])
    reg.LANDSCAPE_FX["Errand"] = lambda game, pid: engine.add_buys(game, 1)
    buy_phase(g, A, coins=20, buys=5)
    engine.add_debt(g, A, 1)
    moves = engine.legal_moves(g, A)
    assert not [m for m in moves if m["type"] in ("buy", "buy_landscape")], \
        "the enumerator offered a buy the handler will refuse"
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": "Copper"})
    assert not ok and err == "pay off your Debt first"
    ok, err = engine.apply_move(g, A, {"type": "buy_landscape", "name": "Errand"})
    assert not ok and err == "pay off your Debt first"


def test_debt_blocks_buying_but_nothing_else(reg):
    """"This is the ONLY effect of having Debt" — you still play, draw, gain and
    end your turn normally, and you still keep your Buys."""
    g = fresh()
    g["turn"] = A
    g["phase"] = "action"
    g["actions"] = 1
    g["seats"][A]["hand"] = ["Village", "Copper"]
    engine.add_debt(g, A, 3)
    ok, err = engine.apply_move(g, A, {"type": "play_action", "card": "Village"})
    assert ok, err
    assert g["actions"] == 2
    assert g["phase"] == "buy"          # auto-advanced: no Action left in hand
    ok, err = engine.apply_move(g, A, {"type": "play_treasure", "card": "Copper"})
    assert ok, err
    assert g["coins"] == 1
    assert g["buys"] == 1, "Debt costs you no Buys, it only forbids using them"
    ok, err = engine.apply_move(g, A, {"type": "end_phase"})
    assert ok, err
    assert g["debt"][A] == 3, "unpaid Debt carries across the turn"


def test_gaining_a_debt_costed_card_gives_no_debt(reg):
    """"Gaining a Debt-cost card without buying it doesn't give you Debt." It
    falls out of gain() simply not knowing about Debt — pinned anyway, because
    "we didn't write the code" is not a rule."""
    g = fresh(kingdom=["Tollgate", "Workshop"] + K10[:8])
    engine.gain(g, A, "Tollgate")
    assert g["debt"][A] == 0
    engine.gain_from(g, A, "Tollgate", dest="hand")
    assert g["debt"][A] == 0
    # ...and a when-gain gain (Workshop's own) is the same
    g["turn"] = A
    g["phase"] = "action"
    g["actions"] = 1
    g["seats"][A]["hand"] = ["Workshop"]
    engine.apply_move(g, A, {"type": "play_action", "card": "Workshop"})
    assert "Tollgate" not in (g["pending"][-1]["constraint"].get("piles") or []), \
        "Workshop's 'up to $4' must not even offer a Debt-costed pile"


def test_after_paying_the_debt_off_the_same_buy_succeeds(reg):
    g = fresh(kingdom=["Tollgate"] + K10[:9])
    buy_phase(g, A, coins=6, buys=2)
    engine.apply_move(g, A, {"type": "buy", "card": "Tollgate"})
    assert g["debt"][A] == 4 and g["coins"] == 4
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": "Copper"})
    assert not ok and err == "pay off your Debt first"
    ok, err = engine.apply_move(g, A, {"type": "spend", "what": "debt", "n": 4})
    assert ok, err
    assert g["debt"][A] == 0 and g["coins"] == 0
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": "Copper"})
    assert ok, err


# ── the payoff MOVE ───────────────────────────────────────────────────────────

def test_the_payoff_is_partial_and_capped_by_your_money(reg):
    """"You may pay off Debt by paying $1 per token" — any amount, and never
    more than you can afford."""
    g = fresh()
    buy_phase(g, A, coins=3, buys=1)
    engine.add_debt(g, A, 5)
    assert engine.spendable(g, A) == {"debt": 3}, "capped by the money pool"
    ok, err = engine.apply_move(g, A, {"type": "spend", "what": "debt", "n": 2})
    assert ok, err
    assert g["debt"][A] == 3 and g["coins"] == 1
    ok, err = engine.apply_move(g, A, {"type": "spend", "what": "debt", "n": 2})
    assert not ok and err == "you don't have 2 debt"
    assert g["debt"][A] == 3 and g["coins"] == 1


def test_paying_off_debt_uses_no_buy_and_is_not_buying(reg):
    """"Paying off Debt doesn't use up a Buy" — and it is not a buy at all, so
    it must not end the part of the Buy phase where you may still play
    Treasures (turn_ctx["bought"])."""
    g = fresh()
    buy_phase(g, A, coins=4, buys=1)
    engine.add_debt(g, A, 2)
    g["seats"][A]["hand"] = ["Copper", "Silver"]
    engine.apply_move(g, A, {"type": "spend", "what": "debt", "n": 2})
    assert g["buys"] == 1, "the payoff spent a Buy"
    assert g["turn_ctx"]["bought"] is False
    ok, err = engine.apply_move(g, A, {"type": "play_treasure", "card": "Silver"})
    assert ok, f"Treasures must still be playable after paying Debt off: {err}"


def test_the_payoff_is_legal_in_the_action_phase(reg):
    """"At any time during your turn" — not only in the Buy phase, which is
    where the pre-2024 rule confined it."""
    g = fresh()
    g["turn"] = A
    g["phase"] = "action"
    g["coins"] = 2                # a Storyteller-ish position: money in hand early
    engine.add_debt(g, A, 2)
    assert {"type": "spend", "what": "debt", "n": 2} in engine.legal_moves(g, A)
    ok, err = engine.apply_move(g, A, {"type": "spend", "what": "debt", "n": 2})
    assert ok, err
    assert g["debt"][A] == 0


def test_the_payoff_is_legal_in_the_middle_of_resolving_an_ability(reg):
    """"You can even pay off Debt in the middle of resolving an ability" — the
    Storyteller shape ph. 7 opened for Coffers, one counter over. The offer goes
    to the PENDING player, or apply_move's own pending gate would refuse the
    move it had just enumerated."""
    g = fresh()
    g["turn"] = A
    g["phase"] = "action"
    g["coins"] = 3
    engine.add_debt(g, A, 3)
    engine.push_choose_cards(g, A, "Cellar", "discard",
                             ["Copper", "Estate"], 0, 2, "discard")
    assert g["pending_pid"] == A
    assert {"type": "spend", "what": "debt", "n": 3} in engine.legal_moves(g, A)
    ok, err = engine.apply_move(g, A, {"type": "spend", "what": "debt", "n": 3})
    assert ok, err
    assert g["debt"][A] == 0 and g["coins"] == 0
    assert g["pending_pid"] == A, "the open decision is still open"


def test_you_cannot_pay_off_debt_off_turn_or_while_an_opponent_decides(reg):
    g = fresh()
    g["turn"] = A
    g["phase"] = "buy"
    g["coins"] = 5
    engine.add_debt(g, B, 3)
    assert engine.spendable(g, B) == {}, "B has no money pool on A's turn"
    ok, err = engine.apply_move(g, B, {"type": "spend", "what": "debt", "n": 1})
    assert not ok
    # ...and with an OPPONENT deciding, the turn player cannot act either
    engine.add_debt(g, A, 2)
    engine.push_choose_cards(g, B, "Militia", "discard",
                             ["Copper", "Estate"], 2, 2, "discard")
    assert engine.spendable(g, A) == {}
    ok, err = engine.apply_move(g, A, {"type": "spend", "what": "debt", "n": 1})
    assert not ok


def test_no_money_enumerates_no_payoff_move_at_all(reg):
    """THE LIVELOCK GUARD. `_spend_moves` enumerates per amount from
    `spendable`, so a $0 player with Debt must be offered nothing — otherwise a
    random-legal bot can pick a move that changes nothing, forever."""
    g = fresh()
    buy_phase(g, A, coins=0, buys=1)
    engine.add_debt(g, A, 6)
    assert engine.spendable(g, A) == {}
    assert not [m for m in engine.legal_moves(g, A) if m["type"] == "spend"]


def test_the_spend_registry_still_serves_coffers_unchanged(reg):
    """The registry is a generalization, not a rewrite: Coffers behave exactly
    as they did, and the two kinds coexist and are offered together."""
    g = fresh()
    buy_phase(g, A, coins=2, buys=1)
    engine.add_coffers(g, 3, A)
    engine.add_debt(g, A, 4)
    assert engine.spendable(g, A) == {"coffers": 3, "debt": 2}
    ok, err = engine.apply_move(g, A, {"type": "spend", "what": "coffers", "n": 3})
    assert ok, err
    assert g["coffers"][A] == 0 and g["coins"] == 5
    assert engine.spendable(g, A) == {"debt": 4}
    engine.apply_move(g, A, {"type": "spend", "what": "debt", "n": 4})
    assert g["debt"][A] == 0 and g["coins"] == 1


def test_the_spend_handler_refuses_an_unknown_kind_and_a_bad_amount(reg):
    g = fresh()
    buy_phase(g, A, coins=3, buys=1)
    engine.add_debt(g, A, 3)
    for move in ({"type": "spend", "what": "villagers", "n": 1},
                 {"type": "spend", "what": "debt", "n": 0},
                 {"type": "spend", "what": "debt", "n": -2},
                 {"type": "spend", "what": "debt", "n": "lots"}):
        ok, _ = engine.apply_move(g, A, move)
        assert not ok, move
    assert g["debt"][A] == 3 and g["coins"] == 3


# ── overpay ───────────────────────────────────────────────────────────────────

def test_you_cannot_overpay_with_debt(reg):
    """"You can't overpay with Debt (since you don't pay with Debt)" —
    Stonemason's overpay is coins (+Potion) only. The prompt is built from the
    money pool, so this is a claim about what the offer contains."""
    g = fresh(kingdom=["Tollbooth"] + K10[:9])
    buy_phase(g, A, coins=5, buys=1)
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": "Tollbooth"})
    assert ok, err
    assert g["debt"][A] == 3, "the Debt half is taken, not overpaid"
    frame = g["pending"][-1]
    assert frame["stage"] == "__overpay"
    labels = [o["label"] for o in frame["constraint"]["options"]]
    assert not any("Debt" in lab for lab in labels), labels
    # $5 - $2 = $3 left, so the offer is overpay $0..$3 — coins alone
    assert len(labels) == 4


# ── the wire + the save shape ─────────────────────────────────────────────────

def test_debt_is_public_on_the_wire_for_every_viewer(reg):
    """Debt sits in front of you where everyone can count it, and everyone must:
    it is why that player is not buying anything."""
    g = fresh()
    engine.add_debt(g, A, 4)
    for viewer in (A, B, None):
        view = engine.player_view(g, viewer)
        assert view["debt"] == {A: 4, B: 0}
        json.dumps(view)


def test_the_debt_counter_survives_json_and_migrate(reg):
    g = fresh(kingdom=["Tollgate"] + K10[:9])
    buy_phase(g, A, coins=4, buys=1)
    engine.apply_move(g, A, {"type": "buy", "card": "Tollgate"})
    blob = json.loads(json.dumps(g))
    engine.migrate(blob)
    assert blob["debt"][A] == 4
    assert blob == json.loads(json.dumps(g)), "migrate mutated a current save"


def test_a_debt_position_is_undoable(reg):
    """Undo restores a whole game dict, so the counter comes back with it — the
    check that matters is that the buy is genuinely reversible while unrevealed."""
    g = fresh(kingdom=["Tollgate"] + K10[:9])
    buy_phase(g, A, coins=4, buys=2)
    engine.apply_move(g, A, {"type": "buy", "card": "Tollgate"})
    assert g["debt"][A] == 4
    ok, err = engine.apply_move(g, A, {"type": "undo_turn"})
    assert ok, err
    assert g["debt"][A] == 0 and g["coins"] == 4
    assert "Tollgate" not in g["seats"][A]["discard"]


# ── a full random game on a synthetic Debt board ──────────────────────────────

def test_a_random_game_on_a_debt_board_terminates_and_conserves_cards(reg):
    """The 6H synthetic-landscape fuzz pattern, with Debt. Random-legal bots buy
    Debt-costed cards and Events, get stuck, and have to pay their way out —
    which is the only way to prove the gate and the payoff cannot deadlock a
    game (a player who can neither buy nor pay must still be able to end the
    turn) and that the payoff move can't livelock at $0."""
    reg.LANDSCAPE_FX["Levy"] = lambda game, pid: engine.add_buys(game, 1)
    reg.LANDSCAPE_FX["Tithe"] = lambda game, pid: engine.add_coins(game, 1)

    def census(game):
        total = Counter(engine.pile_cards(game))
        total.update(game["trash"])
        for p in game["players"]:
            total.update(engine.owned_cards(game, p))
        return total

    paid_off = took_debt = blocked = 0
    for seed in range(12):
        g = fresh(kingdom=["Tollgate", "Obligation", "Tollbooth"] + K10[:7],
                  landscapes=["Levy", "Tithe"], seed=seed)
        baseline = census(g)
        rng = random.Random(seed)
        for _ in range(4000):
            if g["over"]:
                break
            pid = g["pending_pid"] or g["turn"]
            moves = engine.legal_moves(g, pid)
            assert moves, "the actor was left with no legal move"
            mv = rng.choice(moves)
            if mv["type"] == "spend" and mv["what"] == "debt":
                paid_off += 1
            ok, err = engine.apply_move(g, pid, mv)
            assert ok, err
            if g["debt"][pid]:
                took_debt += 1
                if g["phase"] == "buy" and not g["pending_pid"] and pid == g["turn"]:
                    assert not [m for m in engine.legal_moves(g, pid)
                                if m["type"] in ("buy", "buy_landscape")]
                    blocked += 1
            assert census(g) == baseline, "card conservation broken"
        assert g["over"], "a Debt board failed to finish"
    assert took_debt and paid_off and blocked, \
        (took_debt, paid_off, blocked)


def test_both_bot_tiers_cope_with_a_debt_board(reg):
    """No shipped card grants Debt, so neither bot has a decision to make here.
    The obligation is only that a synthetic one cannot wedge them."""
    reg.LANDSCAPE_FX["Levy"] = lambda game, pid: engine.add_buys(game, 1)
    for tier in ("easy", "bmplus"):
        g = fresh(kingdom=["Tollgate", "Obligation"] + K10[:8],
                  landscapes=["Levy"], seed=7)
        rng = random.Random(3)
        for _ in range(3000):
            if g["over"]:
                break
            pid = g["pending_pid"] or g["turn"]
            mv = bot.choose(g, pid, rng, tier)
            ok, err = engine.apply_move(g, pid, mv)
            assert ok, f"{tier}: {err} for {mv}"
        assert g["over"], f"{tier} failed to finish a Debt board"
