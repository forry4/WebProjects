"""Board-read tests.

`bot_plan` produces the CANDIDATE plans the champion's tournament plays off
against each other. That framing matters for what these tests assert: a plan
being wrong on some board is not a bug (the tournament rejects it), but a plan
being unbuildable — naming a card that is not on the board, or an engine with
no draw in it — is.
"""

from games.dontminion import bot_plan, engine
from games.dontminion.cards import KINGDOM

ENGINE_BOARD = ["Village", "Smithy", "Market", "Chapel", "Festival",
                "Laboratory", "Moat", "Cellar", "Workshop", "Gardens"]
MONEY_BOARD = ["Moat", "Chapel", "Cellar", "Harbinger", "Merchant",
               "Vassal", "Workshop", "Moneylender", "Poacher", "Smithy"]
GARDENS_RUSH = ["Gardens", "Workshop", "Market", "Cellar", "Moat",
                "Village", "Harbinger", "Merchant", "Vassal", "Chapel"]


def plan(kingdom, **kw):
    return bot_plan.plan_for(tuple(kingdom), **kw)


def test_an_engine_board_reads_as_an_engine():
    assert plan(ENGINE_BOARD).archetype == "engine"


def test_a_board_without_the_ingredients_falls_back_to_money():
    """All four ingredients or it is not an engine — that is how the named
    losing archetypes ("Durdle", "Village Idiot") happen."""
    assert plan(MONEY_BOARD).archetype == "money"


def test_minion_picks_itself():
    board = ["Minion", "Village", "Smithy", "Market", "Chapel", "Moat",
             "Cellar", "Workshop", "Gardens", "Festival"]
    assert plan(board).archetype == "minion"


def test_a_rush_needs_a_real_pile_gainer_not_just_any_gainer():
    """Bureaucrat "gains a Silver" and Bandit "gains a Gold" — neither can
    empty a pile. Counting them offered a Gardens rush on boards with no rush,
    and forcing that plan measured 0.165 against Big Money+.

    Asserted over CANDIDATES rather than the selector's single pick: the
    champion tournaments the candidate list, so "is the rush on the menu at
    all" is the decision this rule actually controls. (The selector itself
    checks engines first, and the rush board below is also a fine engine
    board — which is exactly the ambiguity the tournament exists to settle.)
    """
    offered = [p.archetype for p in bot_plan.candidates(tuple(GARDENS_RUSH))]
    assert "rush:Gardens" in offered

    fake = ["Gardens", "Bureaucrat", "Market", "Cellar", "Moat", "Village",
            "Harbinger", "Merchant", "Vassal", "Chapel"]
    offered = [p.archetype for p in bot_plan.candidates(tuple(fake))]
    assert not any(a.startswith("rush") for a in offered)


def test_every_plan_only_names_cards_that_are_on_the_board():
    """A menu entry for a card outside the kingdom is unbuyable, so the plan
    silently degrades to the money ladder underneath it."""
    basics = {"Gold", "Silver", "Copper", "Estate", "Duchy", "Province",
              "Platinum", "Colony"}
    for board in (ENGINE_BOARD, MONEY_BOARD, GARDENS_RUSH):
        for p in bot_plan.candidates(tuple(board)):
            for e in p.menu:
                assert e["card"] in board or e["card"] in basics, \
                    f"{p.archetype} wants {e['card']}, not on the board"
                for pre in e["after"]:
                    assert pre in board or pre in basics


def test_an_engine_plan_always_contains_draw_and_a_village():
    p = plan(ENGINE_BOARD)
    cards = [e["card"] for e in p.menu]
    from games.dontminion.bot_traits import traits
    assert any(traits(c)["draw"] or traits(c)["draw_to_x"] for c in cards)
    assert any(traits(c)["village"] for c in cards)
    assert "Gold" in cards, "an engine with no economy cannot buy Provinces"


def test_library_class_draw_is_not_invisible():
    """"Draw until you have 7" prints no "+N Cards", so a purely text-derived
    classifier misses Library entirely — it was absent from the engine plan's
    draw pool for exactly that reason."""
    from games.dontminion.bot_traits import traits
    assert traits("Library")["draw_to_x"]
    assert not traits("Library")["draw"]        # genuinely prints no +N Cards
    board = ["Library", "Village", "Chapel", "Market", "Festival", "Moat",
             "Cellar", "Workshop", "Gardens", "Merchant"]
    f = bot_plan.features(board)
    assert "Library" in f["draw"]


def test_candidates_always_include_money_and_are_unique():
    for board in (ENGINE_BOARD, MONEY_BOARD, GARDENS_RUSH):
        cands = bot_plan.candidates(tuple(board))
        arch = [p.archetype for p in cands]
        assert "money" in arch, "the fallback that always works must be offered"
        assert len(arch) == len(set(arch))


def test_force_selects_a_named_archetype():
    assert plan(ENGINE_BOARD, force="engine").archetype == "engine"
    assert plan(ENGINE_BOARD, force="money").archetype == "money"
    # an archetype this board cannot support degrades to money, never crashes
    assert plan(MONEY_BOARD, force="minion").archetype == "money"


def test_every_dealt_board_produces_a_usable_plan():
    """Soak: the selector must answer for any kingdom the dealer can produce,
    across every expansion."""
    exps = ["base", "intrigue", "seaside", "prosperity", "hinterlands"]
    for seed in range(40):
        g = engine.new_game(["a", "b"], exps, seed=seed)
        cands = bot_plan.candidates(tuple(g["kingdom"]), bool(g.get("colony")))
        assert cands, f"seed {seed} produced no candidate plans"
        p = bot_plan.plan_for(tuple(g["kingdom"]), bool(g.get("colony")))
        assert p.archetype
