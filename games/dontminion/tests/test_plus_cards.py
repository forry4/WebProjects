"""+CARDS vs "draw" — the Way of the Chameleon boundary, and the guard that
holds it.

Way of the Chameleon (Menagerie, ph. 10): "all +Cards you get this turn are +$
instead, and vice versa (keeping their values). … Only card drawing denoted
with '+' is changed to +$. For instance 'draw 2 cards' is unchanged."

So the engine has TWO calls for what used to be one: `E.add_cards(game, n, pid)`
is the printed "+N Cards" bonus (the twin of `add_coins`, and the only one the
Chameleon swap can see), and `E.draw(game, pid, n)` is everything else — a
printed "draw N cards", a draw-to-X, an opponent's draw, a draw that is part of
a larger instruction. Card code cannot tell them apart at runtime and NEITHER
CAN A TEST OF BEHAVIOUR: with no Chameleon on the table the two are identical,
so a card that picks the wrong one is silent until someone plays a Way at it,
and then it is silent in the other direction (nothing raises — a Smithy just
quietly stops swapping).

That is why the classification lives here as SOURCE-LEVEL data. `DRAW_NOT_PLUS`
is a record of a HUMAN reading each card's printed text, not a derivation from
the code it checks (the `bot_traits.REVIEWED` lesson, ph. 7) — a guard whose
allowlist was computed from the call sites would agree with any mistake in
them. Each entry carries the printed wording that justifies it, and the CALL
COUNT, so that adding a second `E.draw` to an allowlisted function (the shape
Council Room already has: its own "+4 Cards" beside the opponents' "draws a
card") re-opens the question instead of inheriting the exemption.
"""

import ast
import pathlib

from games.dontminion import engine

A, B = "alice", "bob"


# --- the classification ------------------------------------------------------
# (module, enclosing function) -> (how many E.draw calls, why they are NOT a
# printed "+N Cards"). Everything else in effects_*.py must use E.add_cards.

DRAW_NOT_PLUS = {
    ("effects_adventures.py", "_guide_call"):
        (1, 'Guide, called: "discard your hand and draw 5 cards" — no plus.'),
    ("effects_adventures.py", "_lost_city_draw"):
        (1, 'Lost City on-gain: "each other player draws a card" — theirs, no plus.'),
    ("effects_adventures.py", "_storyteller_pay"):
        (1, 'Storyteller: "draw a card per $1 you paid" — no plus.'),
    ("effects_base.py", "_cellar_discard"):
        (1, 'Cellar (Base 2E): "Discard any number of cards, THEN DRAW THAT '
            'MANY" — no plus. The 1E card was "+1 Card per card discarded" and '
            "we shipped that wording until ph. 10; the compendium names Cellar "
            "as one of the cards whose EDITION is observable under Way of the "
            "Chameleon, which is what caught it."),
    ("effects_base.py", "_council_room"):
        (1, 'Council Room: "Each other player draws a card" — theirs, no plus. '
            "(The card's own +4 Cards in the same function IS add_cards.)"),
    ("effects_cornucopia.py", "_soothsayer_hit"):
        (1, 'Soothsayer: the victim "draws a card" — theirs, no plus.'),
    ("effects_darkages.py", "_storeroom_refill"):
        (1, 'Storeroom: "Discard any number of cards, then draw that many" — no plus.'),
    ("effects_empires.py", "_chariot_race"):
        (1, 'Chariot Race: "Draw a card, revealing it" — no plus (and the drawn '
            "card is read back, which a swapped grant would not return)."),
    ("effects_empires.py", "_legionary_hit"):
        (1, 'Legionary: the victim "then draws a card" — theirs, no plus.'),
    ("effects_empires.py", "_legionary_draw"):
        (1, "Legionary, same victim draw after the discard frame."),
    ("effects_empires.py", "_ev_donate_draw"):
        (1, 'Donate (Event): "shuffle your hand into your deck and draw 5 cards".'),
    ("effects_hinterlands.py", "_margrave_hit"):
        (1, 'Margrave: "Each other player draws a card" — theirs, no plus.'),
    ("effects_hinterlands.py", "_jack_draw"):
        (1, 'Jack of All Trades: "Draw until you have 5 cards in hand" — draw-to-X.'),
    ("effects_intrigue.py", "_minion_hit"):
        (1, 'Minion: the victim "discards their hand and draws 4 cards" — theirs.'),
    ("effects_intrigue.py", "_diplomat_react"):
        (1, 'Diplomat (Reaction): "to draw 2 cards then discard 3" — no plus.'),
    ("effects_prosperity.py", "_vault_opp_discard"):
        (1, 'Vault: "Each other player may discard 2 cards, to draw a card" — theirs.'),
    ("effects_prosperity.py", "_watchtower"):
        (1, 'Watchtower: "Draw until you have 6 cards in hand" — draw-to-X.'),
}

# `E.final_draw` (the Star-Chart-aware draw, ph. 9) is a THIRD call and the same
# question applies to it. It is ledgered rather than migrated because
# `add_cards` has no final form — it ends in `draw()`, so routing a final draw
# through it would drop the Star Chart pick. Entries marked KNOWN GAP are
# printed +Cards that the Chameleon therefore cannot see yet; the fix is an
# engine one (`add_cards(..., final=True)`), not a card-code one, so this table
# is the record until it lands.
FINAL_DRAW_LEDGER = {
    # The six printed plusses this ledger recorded as KNOWN GAPS were CLOSED
    # the day it was written: `add_cards` grew a `final=` argument, so a
    # printed plus that also ends its ability gets BOTH seams. The order is
    # what makes them compose — a SWAPPED +Cards draws nothing at all, so it
    # can cause no shuffle and needs no Star Chart pick. Only a genuine
    # non-plus final draw belongs here now.
    ("effects_renaissance.py", "_silos_draw"):
        (1, 'Silos: "discard any number of Coppers … and draw that many cards" — '
            "no plus, correct as a plain draw."),
    ("effects_menagerie.py", "_w_owl"):
        (1, 'Way of the Owl: "Draw until you have 6 cards in hand" — draw-to-X, '
            "no plus, so Way of the Chameleon must NOT change it (ch. VII Way "
            "of the Chameleon 4). Watchtower is the same wording, and it is a "
            "pleasing proof that the distinction is real: the Chameleon and "
            "the Owl can sit on the same board."),
}

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _call_sites(name):
    """(module, enclosing function) -> count, for every `E.<name>(...)` call in
    the effects modules. Innermost function wins (Empires builds Settlers and
    Bustling Village from a nested factory)."""
    found = {}
    for path in sorted(_ROOT.glob("effects_*.py")):
        tree = ast.parse(path.read_bytes())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", None) == name
                    and getattr(getattr(node.func, "value", None), "id", None) == "E"):
                continue
            owner = "?"
            best = -1
            for fn in ast.walk(tree):
                if isinstance(fn, ast.FunctionDef) \
                        and fn.lineno <= node.lineno <= (fn.end_lineno or fn.lineno) \
                        and fn.lineno > best:
                    owner, best = fn.name, fn.lineno
            key = (path.name, owner)
            found[key] = found.get(key, 0) + 1
    return found


def test_every_plus_cards_grant_uses_add_cards():
    """A printed "+N Cards" must be granted with E.add_cards, so Way of the
    Chameleon can swap it; every other draw stays E.draw. Source-level because
    there is NO runtime signal — without a Chameleon in play the two calls are
    the same function, and the misclassification only shows up as a card
    silently not swapping (or silently swapping something it shouldn't).

    Fails on any E.draw call site that is not in DRAW_NOT_PLUS, and on any
    allowlisted function whose call COUNT has moved — an exemption is granted
    to a reading of one printed clause, not to a function forever.
    """
    draws = _call_sites("draw")
    grants = _call_sites("add_cards")

    unlisted = sorted(k for k in draws if k not in DRAW_NOT_PLUS)
    assert not unlisted, (
        "E.draw call site(s) not classified — if this is a printed '+N Cards', "
        "grant it with E.add_cards(game, n, pid) so Way of the Chameleon can "
        "swap it; if it is not, add it to DRAW_NOT_PLUS with the printed "
        "wording: " + ", ".join(f"{m}:{f}" for m, f in unlisted))

    moved = sorted(k for k, (n, _) in DRAW_NOT_PLUS.items() if draws.get(k, 0) != n)
    assert not moved, (
        "allowlisted function(s) whose E.draw count changed — re-read the "
        "printed text for the new call instead of inheriting the exemption: "
        + ", ".join(f"{m}:{f} ({draws.get((m, f), 0)} calls, "
                    f"allowlist says {DRAW_NOT_PLUS[(m, f)][0]})" for m, f in moved))

    # non-vacuity: the scan really is finding both halves of the split
    assert sum(draws.values()) == sum(n for n, _ in DRAW_NOT_PLUS.values())
    assert sum(grants.values()) > 100, (
        f"only {sum(grants.values())} E.add_cards sites — the scan (or the "
        "engine's API name) has moved and this guard is checking nothing")


def test_every_final_draw_is_classified():
    """E.final_draw is the Star-Chart-aware draw, and the same +Cards question
    applies to it — but `add_cards` ends in `draw()`, so migrating a final draw
    would trade the Chameleon swap for the Star Chart pick. This is the ledger
    of that trade: every site classified, the printed-plus ones marked KNOWN
    GAP. A new set adding a final draw lands here and has to be read.
    """
    finals = _call_sites("final_draw")
    unlisted = sorted(k for k in finals if k not in FINAL_DRAW_LEDGER)
    assert not unlisted, (
        "E.final_draw site(s) not in FINAL_DRAW_LEDGER — classify against the "
        "printed text: " + ", ".join(f"{m}:{f}" for m, f in unlisted))
    moved = sorted(k for k, (n, _) in FINAL_DRAW_LEDGER.items() if finals.get(k, 0) != n)
    assert not moved, "final_draw count changed: " + ", ".join(
        f"{m}:{f}" for m, f in moved)
    assert sum(finals.values()) == sum(n for n, _ in FINAL_DRAW_LEDGER.values())


# --- behaviour ---------------------------------------------------------------

def fresh(sets, kingdom, seed=7):
    return engine.new_game([A, B], list(sets), seed=seed, kingdom=list(kingdom))


def give_hand(g, pid, cards):
    """Force a hand to exactly `cards` (conservation not preserved)."""
    g["seats"][pid]["hand"] = list(cards)


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def end_turn(g, pid):
    guard = 0
    while g["turn"] == pid and not g["over"]:
        ok, err = mv(g, pid, {"type": "end_phase"})
        assert ok, err
        guard += 1
        assert guard < 4, "end_turn did not terminate"


KB = ["Smithy", "Library", "Market", "Militia", "Council Room", "Village",
      "Moat", "Witch", "Laboratory", "Festival"]


def test_a_printed_plus_cards_becomes_coins():
    """Smithy under the Chameleon: "+3 Cards" is +$3, and NOTHING is drawn."""
    g = fresh(["base"], KB)
    give_hand(g, A, ["Smithy"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 10
    g["turn_ctx"]["chameleon"] = True
    assert mv(g, A, {"type": "play_action", "card": "Smithy"})[0]
    assert g["coins"] == 3
    assert s["hand"] == [] and len(s["deck"]) == 10


def test_the_same_smithy_draws_with_the_flag_off():
    """The control: add_cards IS draw when no Way is in play. Without this the
    test above would pass against an engine that simply never draws."""
    g = fresh(["base"], KB)
    give_hand(g, A, ["Smithy"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 10
    assert mv(g, A, {"type": "play_action", "card": "Smithy"})[0]
    assert g["coins"] == 0 and len(s["hand"]) == 3 and len(s["deck"]) == 7


def test_a_printed_plus_coins_becomes_cards():
    """"And vice versa" — Market prints both, so one play proves both
    directions: its +1 Card pays $1 and its +$1 draws a card."""
    g = fresh(["base"], KB)
    give_hand(g, A, ["Market"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 10
    g["turn_ctx"]["chameleon"] = True
    assert mv(g, A, {"type": "play_action", "card": "Market"})[0]
    assert g["coins"] == 1                       # from the +1 Card
    assert s["hand"] == ["Copper"]               # from the +$1
    assert g["buys"] == 2 and g["actions"] == 1  # untouched by the Way


def test_a_draw_that_is_not_a_printed_plus_is_untouched():
    """Library "Draw until you have 7 cards in hand" — no plus, so the Way does
    not see it (and it is not even a draw() call: it looks and takes)."""
    g = fresh(["base"], KB)
    give_hand(g, A, ["Library", "Copper", "Copper"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 10
    g["turn_ctx"]["chameleon"] = True
    assert mv(g, A, {"type": "play_action", "card": "Library"})[0]
    assert g["pending_pid"] is None
    assert len(s["hand"]) == 7 and g["coins"] == 0


def test_an_opponents_printed_draw_is_not_the_chameleon_players():
    """"Only +Cards and +$ THAT YOU GET are changed." Council Room swaps its own
    "+4 Cards" to +$4 and the opponents still DRAW their card."""
    g = fresh(["base"], KB)
    give_hand(g, A, ["Council Room"])
    g["seats"][A]["deck"] = ["Copper"] * 10
    g["seats"][B]["deck"] = ["Estate"] * 5
    g["seats"][B]["hand"] = []
    g["turn_ctx"]["chameleon"] = True
    assert mv(g, A, {"type": "play_action", "card": "Council Room"})[0]
    assert g["coins"] == 4 and g["seats"][A]["hand"] == []
    assert g["seats"][B]["hand"] == ["Estate"]


def test_a_durations_next_turn_plus_is_scoped_to_the_turn_it_fires_in():
    """"If you play Merchant Ship, you get +2 Cards this turn, but +$ next turn
    as normal" — read for Wharf, whose +2 Cards is on BOTH halves. The delayed
    half is add_cards too; the turn-scoping is the kernel's (`turn_ctx` does not
    survive the turn), not the card's."""
    g = fresh(["seaside"], ["Wharf", "Bazaar", "Caravan", "Haven", "Lookout",
                            "Salvager", "Sea Chart", "Tide Pools", "Warehouse",
                            "Lighthouse"])
    give_hand(g, A, ["Wharf"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 20
    g["turn_ctx"]["chameleon"] = True
    assert mv(g, A, {"type": "play_action", "card": "Wharf"})[0]
    assert g["coins"] == 2 and s["hand"] == []      # this turn: swapped
    end_turn(g, A)
    end_turn(g, B)
    assert g["turn"] == A and not g["turn_ctx"]["chameleon"]
    assert len(s["hand"]) == 7                      # next turn: 5 + a real +2 Cards


def test_minus_coins_is_not_swapped():
    """"-$, as on Poor House or Souk, is not changed by this Way." Poor House's
    +$4 becomes +4 Cards; its -$1 per Treasure still comes off the money pool."""
    g = fresh(["base", "darkages"], KB + ["Poor House"])
    give_hand(g, A, ["Poor House", "Copper", "Copper"])
    s = g["seats"][A]
    s["deck"] = ["Estate"] * 10
    g["coins"] = 5                                  # as if Treasures were played
    g["turn_ctx"]["chameleon"] = True
    assert mv(g, A, {"type": "play_action", "card": "Poor House"})[0]
    # +$4 -> 4 Estates drawn; the two Coppers still deduct $2 from the pool
    assert sorted(s["hand"]) == ["Copper", "Copper"] + ["Estate"] * 4
    assert g["coins"] == 3


def test_the_minus_coin_token_applies_to_the_swapped_result():
    """"A Militia gives +2 Cards and will trigger your -1 Card token but not
    your -$ token" — read the other way: a SWAPPED "+3 Cards" is now $, so it is
    the -$1 token that eats it and the -1 Card token that is left alone."""
    g = fresh(["base"], KB)
    give_hand(g, A, ["Smithy"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 10
    s["tokens"]["-coin"] = True
    s["tokens"]["-card"] = True
    g["turn_ctx"]["chameleon"] = True
    assert mv(g, A, {"type": "play_action", "card": "Smithy"})[0]
    assert g["coins"] == 2                          # $3 less the -$1 token
    assert "-coin" not in s["tokens"]
    assert s["tokens"].get("-card") is True         # untouched: nothing was drawn


def test_the_minus_card_token_applies_to_the_swapped_result():
    """The mirror: Militia's printed +$2 becomes +2 Cards, so now it is the
    -1 Card token that bites and the -$1 token that is left alone."""
    g = fresh(["base"], KB)
    give_hand(g, A, ["Militia"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 10
    s["tokens"]["-coin"] = True
    s["tokens"]["-card"] = True
    g["turn_ctx"]["chameleon"] = True
    assert mv(g, A, {"type": "play_action", "card": "Militia"})[0]
    assert g["coins"] == 0
    assert s["hand"] == ["Copper"]                  # 2 cards less the -1 Card token
    assert "-card" not in s["tokens"]
    assert s["tokens"].get("-coin") is True
