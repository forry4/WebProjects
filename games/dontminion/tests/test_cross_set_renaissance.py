"""Cross-set tests for phase 9 (RENAISSANCE) — the combos where the new
mechanics meet the nine already-shipped sets.

Step 6 of the per-phase playbook, and it is not optional: a card batch can only
ever be as correct as the precedent it copies, so per-set tests structurally
cannot find the class of bug where a NEW rule meets an OLD card. Everything
here therefore builds a board that mixes Renaissance with at least one shipped
expansion and drives real moves.

Every test names the rule it encodes and the compendium ruling it comes from
(Knutsen v11.1; page numbers are the PDF's printed page, one higher than the
0-based index).

HEADLINE FINDINGS (see the docstrings, each marked FOUND BUG):

  * **Improve x Peddler** — "cost reductions for this turn, or from cards in
    play, still apply in Clean-up (EXCEPT Peddler's cost reduction)" (Improve,
    p. 108). `game["phase"]` never leaves `"buy"` during Clean-up, so
    Peddler's `DYN_COSTS` discount is still live when Improve reads costs and
    Improve can "remodel" a $3 into a Peddler.
"""

import copy
import json
import random

from games.dontminion import cards, effects, engine

A, B, C = "alice", "bob", "carol"


# --- fixtures ----------------------------------------------------------------

def fresh(kingdom, expansions, landscapes=(), players=(A, B), seed=7):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom), landscapes=list(landscapes))


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def decide(g, pid, **payload):
    return engine.apply_move(g, pid, {"type": "decision", **payload})


def frame(g):
    return g["pending"][-1] if g["pending"] else None


def opt_ids(g):
    return [o["id"] for o in frame(g)["constraint"]["options"]]


def give_hand(g, pid, cards_):
    g["seats"][pid]["hand"] = list(cards_)


def give_deck(g, pid, cards_):
    g["seats"][pid]["deck"] = list(cards_)


def give_cube(g, name, pid):
    """Buy a Project without paying for it — the cube IS `bought_by`."""
    g["landscapes"][name]["bought_by"].append(pid)


def events(g, name):
    return [e for e in g["log"] if e.get("event") == name]


def play(g, pid, card):
    ok, err = mv(g, pid, {"type": "play_action", "card": card})
    assert ok, err


def to_buy(g, pid):
    if g["phase"] == "action" and not g["pending"]:
        ok, err = mv(g, pid, {"type": "end_phase"})
        assert ok, err


def end_turn(g, pid):
    to_buy(g, pid)
    if g["over"] or g["pending"]:
        return
    ok, err = mv(g, pid, {"type": "end_phase"})
    assert ok, err


def drain(g, rng=None, cap=200):
    """Answer every open decision with a uniform valid payload."""
    rng = rng or random.Random(3)
    for _ in range(cap):
        pid = g["pending_pid"]
        if pid is None:
            return
        ok, err = decide(g, pid, **engine.sample_decision(g, pid, rng))
        assert ok, err
    raise AssertionError("decisions never drained")


def gain(g, pid, pile, **kw):
    out = engine.gain(g, pid, pile, **kw)
    engine._drive(g)
    return out


def pass_turn_to(g, pid):
    """End turns (answering nothing but auto frames) until it is pid's turn."""
    for _ in range(12):
        if g["turn"] == pid and g["phase"] == "action":
            return
        cur = g["turn"]
        end_turn(g, cur)
        drain(g)
    raise AssertionError("never reached %s" % pid)


# =============================================================================
# CAPITALISM x THE NINE SHIPPED SETS
# Capitalism has the widest blast radius in the set: it is a `types_of`
# injection, so it reaches every card in the game at once.
# =============================================================================

CAP_KINGDOM = ["Improve", "Patron", "Seer", "Village", "Smithy", "Market",
               "Laboratory", "Bishop", "Moat"]


def test_capitalism_does_not_change_types_when_you_score_for_keep():
    """Keep (an EMPIRES landmark) scores "5 VP per differently named Treasure
    you have, that you have more copies of than each other player". Capitalism:
    "Cards are not changed by Capitalism when you score for Keep, as it's not
    your turn at the end of the game" (compendium p. 68). The `not game["over"]`
    gate in `types_of` is what buys this; the mid-game half of the assertion is
    what makes the test non-vacuous."""
    g = fresh(["Festival"] + CAP_KINGDOM, ["base", "empires", "renaissance"],
              landscapes=["Capitalism", "Keep"])
    give_cube(g, "Capitalism", A)
    g["seats"][A]["discard"] += ["Festival", "Festival"]
    keep = effects.LANDSCAPE_SCORING["Keep"]
    # DURING A's turn the Festivals really are Treasures, so Keep pays for them
    assert g["turn"] == A and not g["over"]
    assert keep(g, A) == 10, "Copper + Festival while Capitalism is live"
    # ...and at game over it is nobody's turn, so they are Actions again
    g["supply"]["Province"] = 0
    end_turn(g, A)
    drain(g)
    assert g["over"]
    assert engine.types_of(g, "Festival") == ["action"]
    assert keep(g, A) == 5, "only Copper: Capitalism is off at scoring"
    assert g["scores"][A]["vp"] == 3 + 5


def test_a_capitalism_treasure_played_in_the_buy_phase_is_enchanted():
    """Enchantress (EMPIRES) replaces what the first Action card each opponent
    plays on their turn does. A Capitalism-changed Action played in the Buy
    phase IS an Action play ("this doesn't use an Action from your Action pool"
    is the only thing that changes), so the would_resolve window catches it:
    +1 Card +1 Action instead of Festival's +2 Actions/+1 Buy/+$2."""
    g = fresh(["Enchantress", "Festival"] + CAP_KINGDOM[:8],
              ["base", "empires", "renaissance"], landscapes=["Capitalism"])
    give_cube(g, "Capitalism", A)
    give_hand(g, B, ["Enchantress"])
    end_turn(g, A)
    drain(g)
    play(g, B, "Enchantress")
    end_turn(g, B)
    drain(g)
    assert g["turn"] == A and g["phase"] == "buy"
    give_hand(g, A, ["Festival", "Copper"])
    hand0 = len(g["seats"][A]["hand"])
    assert mv(g, A, {"type": "play_treasure", "card": "Festival"})[0]
    assert [e for e in g["log"] if e.get("event") == "enchanted"], "not Enchanted"
    assert g["coins"] == 0 and g["buys"] == 1, "Festival's own text was replaced"
    assert g["actions"] == 2, "+1 Action from the Enchantment"
    assert len(g["seats"][A]["hand"]) == hand0 - 1 + 1, "+1 Card from the Enchantment"


def test_a_capitalism_attack_played_in_the_buy_phase_still_opens_the_reaction_window():
    """"A card changed by Capitalism always counts as both an Action and a
    Treasure" (p. 68) — so a Militia played as a Treasure is still an ATTACK
    being played, and Moat's reaction window must open. `_play_one_treasure`
    delegates to `play_action_card`, which is what wraps the play."""
    g = fresh(["Militia", "Festival"] + CAP_KINGDOM[:8], ["base", "renaissance"],
              landscapes=["Capitalism"])
    give_cube(g, "Capitalism", A)
    give_hand(g, A, ["Militia", "Copper"])
    give_hand(g, B, ["Moat", "Copper", "Copper", "Copper", "Copper"])
    to_buy(g, A)
    assert engine.types_of(g, "Militia") == ["action", "attack", "treasure"]
    assert mv(g, A, {"type": "play_treasure", "card": "Militia"})[0]
    assert g["pending_pid"] == B and frame(g)["kind"] == "choose_option", \
        "no reaction window for a Capitalism-changed Attack"
    assert g["turn_ctx"]["actions_played"] == 1, "it counts as an Action played"
    assert g["actions"] == 1, "...but spends no Action from the pool"


def test_crown_in_the_buy_phase_plays_a_capitalism_changed_action_twice():
    """Crown (EMPIRES) plays an Action twice in the Action phase and a Treasure
    twice in the Buy phase; Capitalism's entry points at Crown for what a
    changed card is ("always counts as both an Action and a Treasure, just like
    Crown"). So in the Buy phase Crown may pick a changed Action, and it
    resolves twice."""
    g = fresh(["Crown", "Festival"] + CAP_KINGDOM[:8],
              ["base", "empires", "renaissance"], landscapes=["Capitalism"])
    give_cube(g, "Capitalism", A)
    give_hand(g, A, ["Crown", "Festival"])
    to_buy(g, A)
    assert mv(g, A, {"type": "play_treasure", "card": "Crown"})[0]
    assert frame(g)["constraint"]["cards"] == ["Festival"], \
        "the changed Action is not offered as Crown's Treasure"
    assert decide(g, A, cards=["Festival"])[0]
    drain(g)
    assert g["coins"] == 4 and g["buys"] == 3 and g["actions"] == 5
    assert g["seats"][A]["in_play"] == ["Crown", "Festival"]


def test_play_all_treasures_never_fires_a_capitalism_changed_action():
    """`autoplay_treasures` is THE reader for the handler, `legal_moves` and
    `player_view`. A changed Militia draws, attacks or prompts like the Action
    it is, so the button must skip it — and a hand of NOTHING but changed
    Actions and manual Treasures must not offer the move at all (the no-op
    livelock rule)."""
    g = fresh(["Militia", "Scepter"] + CAP_KINGDOM[:8], ["base", "renaissance"],
              landscapes=["Capitalism"])
    give_cube(g, "Capitalism", A)
    give_hand(g, A, ["Militia", "Copper", "Silver", "Scepter"])
    to_buy(g, A)
    assert engine.autoplay_treasures(g, A) == ["Copper", "Silver"], \
        "Militia (changed) and Scepter (manual) must both be skipped"
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert sorted(g["seats"][A]["in_play"]) == ["Copper", "Silver"]
    assert sorted(g["seats"][A]["hand"]) == ["Militia", "Scepter"]
    # ...and now the button is a no-op, so neither the enumerator nor the
    # handler may accept it
    assert engine.autoplay_treasures(g, A) == []
    assert not any(m["type"] == "play_all_treasures"
                   for m in engine.legal_moves(g, A))
    assert mv(g, A, {"type": "play_all_treasures"}) == (False, "no treasures to autoplay")


def test_the_bulk_treasure_play_stays_undoable_with_capitalism_on_the_board():
    """`test_every_autoplayed_treasure_leaves_the_bulk_play_undoable` enumerates
    the autoplay bucket from the REGISTRIES, which a state-dependent exclusion
    is invisible to. Capitalism only ever REMOVES cards from the bucket, so the
    one move must still be undoable — pinned here because that removal is what
    keeps a drawing/revealing Action out of it."""
    g = fresh(["Militia", "Seer"] + CAP_KINGDOM[:8], ["base", "renaissance"],
              landscapes=["Capitalism"])
    give_cube(g, "Capitalism", A)
    give_hand(g, A, ["Militia", "Copper", "Silver", "Seer"])
    to_buy(g, A)
    before = copy.deepcopy({k: v for k, v in g.items()
                            if k not in ("undo_stack", "log")})
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert not g["turn_revealed"], "nothing in the bulk play revealed anything"
    assert g["undo_stack"], "the bulk play was not undoable"
    assert mv(g, A, {"type": "undo_turn"})[0]
    after = {k: v for k, v in g.items() if k not in ("undo_stack", "log")}
    assert after == before


def test_charlatan_and_capitalism_are_two_independent_type_injections():
    """Charlatan (PROSPERITY) makes Curse a Treasure for the whole game;
    Capitalism makes Charlatan itself a Treasure for its owner's turns. Both
    land, and the button autoplays the Curse (an ordinary Treasure) while
    skipping the changed Attack."""
    g = fresh(["Charlatan", "Festival"] + CAP_KINGDOM[:8],
              ["base", "prosperity", "renaissance"], landscapes=["Capitalism"])
    give_cube(g, "Capitalism", A)
    assert g["curse_is_treasure"]
    assert engine.types_of(g, "Curse") == ["curse", "treasure"]
    assert engine.types_of(g, "Charlatan") == ["action", "attack", "treasure"]
    give_hand(g, A, ["Curse", "Charlatan", "Copper"])
    to_buy(g, A)
    assert engine.autoplay_treasures(g, A) == ["Curse", "Copper"]


def test_an_inherited_estate_is_a_treasure_when_capitalism_changes_its_card():
    """FOUND BUG (Adventures x Renaissance).

    Inheritance puts your Estate token on an Action card, and every Estate in
    the game then has that card's types and text. The compendium's "Your Estate
    token" entry (p. 179): "If you have your Estate token on an Action card
    which Capitalism changes into a Treasure, ALL YOUR ESTATES ARE ALSO
    TREASURES."

    We inject `action`+`command` onto Estate for Inheritance and then ask
    Capitalism about the literal name "Estate", which is not in
    `CAPITALISM_CARDS` — so the second injection never sees the first. The
    inherited Estate cannot be played in the Buy phase and is invisible to
    Keep, Mint, Bank and Investment."""
    g = fresh(["Festival"] + CAP_KINGDOM, ["base", "adventures", "renaissance"],
              landscapes=["Capitalism", "Inheritance"])
    give_cube(g, "Capitalism", A)
    engine.set_seat_token(g, A, "estate", "Festival")
    assert engine.estate_token_card(g) == "Festival"
    assert engine.has_type(g, "Festival", "treasure"), "control: Festival is changed"
    assert engine.has_type(g, "Estate", "treasure"), \
        "an Estate inheriting a Capitalism-changed Action is also a Treasure"
    give_hand(g, A, ["Estate", "Copper"])
    to_buy(g, A)
    assert mv(g, A, {"type": "play_treasure", "card": "Estate"})[0]


def test_herbalist_may_topdeck_a_capitalism_changed_action_including_itself():
    """Herbalist (ALCHEMY, 2022 version) — "Once this turn, when you discard a
    Treasure from play, you may put it onto your deck". Compendium Herbalist 2
    (p. 104): "With Capitalism, you may choose the Herbalist itself." Herbalist
    has "+$1" in its text, so it is one of the changed cards."""
    g = fresh(["Herbalist", "Festival"] + CAP_KINGDOM[:8],
              ["base", "alchemy", "renaissance"], landscapes=["Capitalism"])
    give_cube(g, "Capitalism", A)
    give_hand(g, A, ["Herbalist", "Festival", "Copper"])
    play(g, A, "Herbalist")
    assert g["phase"] == "buy", "Herbalist gives no +Action"
    assert mv(g, A, {"type": "play_treasure", "card": "Festival"})[0]
    assert mv(g, A, {"type": "play_treasure", "card": "Copper"})[0]
    end_turn(g, A)
    assert frame(g)["card"] == "Herbalist"
    assert frame(g)["constraint"]["cards"] == ["Copper", "Festival", "Herbalist"], \
        "both changed Actions in play are Treasures being discarded"
    assert decide(g, A, cards=["Herbalist"])[0]
    drain(g)
    # topdecked, so it is the first card of the next hand rather than discarded
    assert [e for e in g["log"]
            if e.get("event") == "topdeck" and e.get("card") == "Herbalist"]
    assert g["seats"][A]["hand"][0] == "Herbalist"
    assert "Herbalist" not in g["seats"][A]["discard"]


# =============================================================================
# SCEPTER — a Command Treasure that replays an Action still in play
# =============================================================================

def test_scepter_may_replay_a_throne_room_but_never_a_command():
    """2024: Scepter "now only lets you replay non-Command cards, and is itself
    a Command card … to prevent you from using Scepter to replay itself". The
    Command type belongs to Band of Misfits, Overlord (and Scepter) — a Throne
    Room is NOT a Command and is a perfectly legal target."""
    g = fresh(["Scepter", "Overlord", "Throne Room", "Village", "Smithy",
               "Market", "Laboratory", "Festival", "Bishop", "Improve"],
              ["renaissance", "base", "empires"])
    assert "command" in cards.CARDS["Overlord"]["types"]
    assert "command" not in cards.CARDS["Throne Room"]["types"]
    give_hand(g, A, ["Throne Room", "Village", "Scepter", "Overlord"])
    play(g, A, "Throne Room")
    assert decide(g, A, cards=["Village"])[0]
    drain(g)
    play(g, A, "Overlord")
    drain(g)
    assert {"Throne Room", "Overlord"} <= set(g["seats"][A]["in_play"])
    to_buy(g, A)
    assert mv(g, A, {"type": "play_treasure", "card": "Scepter"})[0]
    assert decide(g, A, ids=["replay"])[0]
    assert frame(g)["constraint"]["cards"] == ["Throne Room", "Village"], \
        "Overlord is a Command and Scepter itself is not an Action"


def test_scepter_replaying_a_duration_piles_onto_the_one_physical_card():
    """A Duration played this turn is "still in play", so Scepter may replay it
    — and the second resolution must land on the SAME `dur_setup` entry
    (Kernel v9's `duration_handle` / the ph.-7H `_restore_cur_dur` rule).
    Minting a second entry would discard one physical card twice."""
    g = fresh(["Scepter", "Caravan", "Village", "Smithy", "Market",
               "Laboratory", "Festival", "Bishop", "Improve", "Patron"],
              ["renaissance", "seaside", "base"])
    give_hand(g, A, ["Caravan", "Scepter"])
    give_deck(g, A, ["Copper"] * 12)
    g["seats"][A]["discard"] = []
    play(g, A, "Caravan")
    to_buy(g, A)
    assert mv(g, A, {"type": "play_treasure", "card": "Scepter"})[0]
    assert decide(g, A, ids=["replay"])[0]
    assert frame(g)["constraint"]["cards"] == ["Caravan"]
    assert decide(g, A, cards=["Caravan"])[0]
    drain(g)
    setups = g["seats"][A]["dur_setup"]
    assert len(setups) == 1 and len(setups[0]["fx"]) == 2, \
        "one physical Caravan, two next-turn draws"
    end_turn(g, A)
    drain(g)
    end_turn(g, B)
    drain(g)
    assert g["turn"] == A
    assert len(g["seats"][A]["hand"]) == 7, "5 + Caravan's two +1 Cards"
    assert g["seats"][A]["duration"] == [
        {"card": "Caravan", "fx": [], "watchers": 0, "riders": [], "done": True}]


def test_scepter_may_not_replay_a_card_that_left_play_and_came_back():
    """FOUND BUG (Adventures x Renaissance) — deviation B5 becoming REACHABLE.

    Scepter 5 (compendium p. 141): "'Still in play' means the Action card can't
    have left play after you played it, EVEN IF IT HAS ENTERED PLAY AGAIN as
    with certain Reserve cards. So if you play a Duplicate or Royal Carriage
    and call it the same turn, you still can't replay it with Scepter."

    Playing Royal Carriage moves it to the Tavern mat (it LEAVES play); calling
    it puts it back into `in_play`. `_scepter_targets` intersects
    `turn_ctx["played_actions"]` with `in_play`, which is PRESENCE-based and
    cannot tell "still there" from "left and returned" — the standing-list row
    B5 predicted exactly this and said to revisit "when a set ships a card that
    can round-trip a zone mid-window". Scepter is that card."""
    g = fresh(["Scepter", "Royal Carriage", "Village", "Smithy", "Market",
               "Laboratory", "Festival", "Bishop", "Improve", "Patron"],
              ["renaissance", "adventures", "base"])
    give_hand(g, A, ["Royal Carriage", "Village", "Scepter"])
    play(g, A, "Royal Carriage")
    assert g["seats"][A]["tavern"] == ["Royal Carriage"]
    assert g["seats"][A]["in_play"] == [], "Royal Carriage left play"
    play(g, A, "Village")
    assert frame(g)["card"] == "Royal Carriage"          # the call offer
    assert opt_ids(g) == ["play", "decline"]
    assert decide(g, A, ids=["play"])[0]
    drain(g)
    assert "Royal Carriage" in g["seats"][A]["in_play"], "called back into play"
    to_buy(g, A)
    assert mv(g, A, {"type": "play_treasure", "card": "Scepter"})[0]
    assert decide(g, A, ids=["replay"])[0]
    assert "Royal Carriage" not in frame(g)["constraint"]["cards"], \
        "a called Royal Carriage left play, so Scepter may not replay it"
    assert frame(g)["constraint"]["cards"] == ["Village"]


# =============================================================================
# IMPROVE — trashes an Action LEAVING PLAY at Clean-up for one costing $1 more
# =============================================================================

IMP_K = ["Improve", "Cargo Ship", "Village", "Smithy", "Market", "Laboratory",
         "Festival", "Bishop", "Patron", "Seer"]


def _improve_board():
    g = fresh(IMP_K, ["renaissance", "base"])
    give_hand(g, A, ["Village", "Cargo Ship", "Improve"])
    play(g, A, "Village")
    play(g, A, "Cargo Ship")
    play(g, A, "Improve")
    return g


def test_improve_may_remodel_a_cargo_ship_that_set_nothing_aside():
    """Cargo Ship 5 (p. 68): "Cargo Ship is discarded in Clean-up if you haven't
    set aside any cards, which means you may 'remodel' it with Improve."
    Improve's candidate set is `leaving_play`, and a Cargo Ship that caught
    nothing never registered a duration fx — so it is exactly what is about to
    hit the discard pile."""
    g = _improve_board()
    to_buy(g, A)
    end_turn(g, A)
    assert frame(g)["card"] == "Improve"
    assert frame(g)["constraint"]["cards"] == ["Cargo Ship", "Improve", "Village"]
    assert decide(g, A, cards=["Cargo Ship"])[0]
    assert frame(g)["constraint"]["piles"] == ["Bishop", "Patron", "Smithy"], \
        "Cargo Ship costs $3, so exactly $4"
    assert "Cargo Ship" in g["trash"]


def test_improve_never_offers_a_cargo_ship_that_is_staying_in_play():
    """The other half of the same ruling — "you can only choose a card that
    would be discarded this turn, so not a Duration card that will stay in
    play" (Improve, p. 108). A Cargo Ship that DID set a card aside persists,
    and `_cleanup_durations` has already promoted it out of `in_play` by the
    time `cleanup_start` fires."""
    g = _improve_board()
    to_buy(g, A)
    g["coins"] = 5
    assert mv(g, A, {"type": "buy", "card": "Market"})[0]
    assert frame(g)["card"] == "Cargo Ship"
    assert decide(g, A, ids=["yes"])[0]
    drain(g)
    assert g["seats"][A]["dur_aside"] == ["Market"]
    end_turn(g, A)
    assert frame(g)["card"] == "Improve"
    assert frame(g)["constraint"]["cards"] == ["Improve", "Village"], \
        "the persisting Cargo Ship must not be offered"


def test_a_cargo_ship_still_catches_the_card_improve_gained_from_remodelling_it():
    """The rest of the Cargo Ship 5 clarification: "The card you gain then may
    still be set aside with Cargo Ship." Improve's gain happens at
    `cleanup_start`, and a Cargo Ship watcher is `until="turn_end"` — the
    turn-end sweep only runs in `_k_cleanup_sweep`, after every start-of-
    Clean-up ability — so it is still armed.

    DELIBERATE DEVIATION, pinned here rather than fixed: the compendium adds
    "but the card would stay set aside for the rest of the game", because the
    2025 Duration rule stops a played Duration's later effects once the card
    fails to be in play (Improve has just trashed the Cargo Ship). We do not
    implement that rule anywhere in the engine, so the Smithy comes back to
    hand at the start of the next turn. Candidate row for the standing list."""
    g = _improve_board()
    to_buy(g, A)
    end_turn(g, A)
    assert decide(g, A, cards=["Cargo Ship"])[0]
    assert decide(g, A, pile="Smithy")[0]
    assert frame(g)["card"] == "Cargo Ship", "the watcher is still armed"
    assert decide(g, A, ids=["yes"])[0]
    drain(g)
    assert g["seats"][A]["dur_aside"] == ["Smithy"]
    assert "Cargo Ship" in g["trash"]
    end_turn(g, B)
    drain(g)
    assert g["turn"] == A
    assert "Smithy" in g["seats"][A]["hand"], \
        "DEVIATION: officially it would stay set aside for the rest of the game"


def test_improve_must_not_see_peddlers_buy_phase_discount_in_cleanup():
    """FOUND BUG (Prosperity x Renaissance).

    Improve 6 (compendium p. 108): "Remember that COST REDUCTIONS for this
    turn, or from cards in play, still apply in Clean-up (EXCEPT Peddler's cost
    reduction)." Peddler's own text scopes its discount to "a player's Buy
    phase", and Clean-up is not the Buy phase.

    `game["phase"]` never leaves `"buy"` during Clean-up — `_end_turn` is
    entered from the Buy phase and the next assignment is at the hand-off — so
    `effects_prosperity._peddler_discount` is still live when Improve prices
    the Supply. With Improve + one Village left in play, Peddler reads $4 and
    Improve "remodels" a $3 Village into it."""
    g = fresh(["Improve", "Peddler", "Village", "Smithy", "Market",
               "Laboratory", "Festival", "Bishop", "Watchtower", "Moat"],
              ["renaissance", "prosperity", "base"])
    give_hand(g, A, ["Village", "Village", "Improve"])
    play(g, A, "Village")
    play(g, A, "Village")
    play(g, A, "Improve")
    to_buy(g, A)
    end_turn(g, A)
    assert decide(g, A, cards=["Village"])[0]        # trash a $3
    piles = frame(g)["constraint"]["piles"]
    assert "Peddler" not in piles, \
        "Peddler's discount does not apply in Clean-up: it costs $8 there"
    assert piles == ["Bishop", "Smithy"]


def test_scheme_and_alchemist_always_resolve_before_improve():
    """DELIBERATE DEVIATION (extends standing-list row B1), pinned.

    Scheme (Seaside) and Alchemist (Alchemy) are both printed "at the start of
    Clean-up", the same timing as Improve, so officially the player orders the
    three in one pool (p23 §2). We ride Scheme/Alchemist/Herbalist on
    `buy_phase_end` (row B1) and Improve on the real `cleanup_start`, so
    Scheme/Alchemist ALWAYS go first and the choice is never offered.

    The visible cost is exactly what Improve 7 describes from the other side —
    "If you 'remodel' an Alchemist (current version) or Walled Village, that
    card's ability loses track of it and can't put it onto your deck" — a
    sequence our ordering makes unreachable, because the Alchemist has already
    topdecked itself before Improve is asked."""
    g = fresh(["Improve", "Alchemist", "Village", "Smithy", "Market",
               "Laboratory", "Festival", "Bishop", "Patron", "Seer"],
              ["renaissance", "alchemy", "base"])
    give_hand(g, A, ["Village", "Alchemist", "Improve", "Potion"])
    play(g, A, "Village")
    play(g, A, "Alchemist")
    play(g, A, "Improve")
    to_buy(g, A)
    assert mv(g, A, {"type": "play_treasure", "card": "Potion"})[0]
    end_turn(g, A)
    assert frame(g)["card"] == "Alchemist", "Alchemist is asked first, not pooled"
    assert decide(g, A, ids=["yes"])[0]
    assert frame(g)["card"] == "Improve"
    assert "Alchemist" not in frame(g)["constraint"]["cards"], \
        "DEVIATION: it already left play, so Improve can no longer remodel it"


def test_improve_reads_cost_reductions_that_do_apply_in_cleanup():
    """The positive half of the Improve 6 ruling — Bridge (turn-scoped), Canal
    (a Project cube, "during your turns cards cost $1 less") and Quarry (2022,
    turn-scoped, Actions only) all still apply while Improve prices the Supply,
    so "exactly $1 more" tracks the REDUCED costs."""
    def run(hand, landscapes=(), cube=None):
        g = fresh(["Improve", "Bridge", "Quarry", "Village", "Smithy", "Market",
                   "Laboratory", "Festival", "Bishop", "Moat"],
                  ["renaissance", "intrigue", "prosperity", "base"],
                  landscapes=list(landscapes))
        if cube:
            give_cube(g, cube, A)
        give_hand(g, A, hand)
        for c in hand:
            if engine.has_type(g, c, "action"):
                assert mv(g, A, {"type": "play_action", "card": c})[0]
        to_buy(g, A)
        for c in list(g["seats"][A]["hand"]):
            if engine.has_type(g, c, "treasure"):
                mv(g, A, {"type": "play_treasure", "card": c})
        end_turn(g, A)
        assert decide(g, A, cards=["Village"])[0]
        return g, frame(g)["constraint"]["piles"]

    PRINTED_4 = ["Bishop", "Bridge", "Quarry", "Smithy"]

    g, base = run(["Village", "Village", "Improve"])
    assert base == PRINTED_4, base                     # $3 Village -> $4
    assert engine.cost(g, "Village") == 3
    assert all(engine.cost(g, p) == 4 for p in base)

    g, bridged = run(["Village", "Bridge", "Village", "Improve"])
    assert engine.cost(g, "Village") == 2, "Bridge reaches Clean-up"
    assert bridged == PRINTED_4
    assert all(engine.cost(g, p) == 3 for p in bridged), \
        "the whole ladder moved down with the reduction"

    g, canaled = run(["Village", "Village", "Improve"],
                     landscapes=["Canal"], cube="Canal")
    assert engine.cost(g, "Village") == 2, "Canal reaches Clean-up"
    assert canaled == PRINTED_4
    assert all(engine.cost(g, p) == 3 for p in canaled)

    g, quarried = run(["Village", "Village", "Improve", "Quarry"])
    assert engine.cost(g, "Village") == 1, "Quarry is turn-scoped, Actions only"
    assert quarried == ["Bishop", "Bridge", "Estate", "Smithy"], \
        "an Estate at a flat $2 is now exactly $1 more than a $1 Village"


# =============================================================================
# EXPERIMENT x FERRYMAN — a pile IN THE GAME and NOT in the Supply
# =============================================================================

FERRY_K = ["Ferryman", "Village", "Smithy", "Market", "Laboratory", "Festival",
           "Bishop", "Patron", "Seer", "Improve"]


def _ferryman_experiment_board():
    """Ferryman's extra pile is drawn at random from the unused $3/$4 piles, so
    search seeds for one that lands on Experiment. NOT a skip: if no seed in
    the range produces it the test FAILS, because the interaction would then be
    unreachable and this file would be silently proving nothing."""
    for seed in range(200):
        g = fresh(FERRY_K, ["renaissance", "cornucopia", "base"], seed=seed)
        if g["ferryman_pile"] == "Experiment":
            return g
    raise AssertionError("no seed in 0..199 drew Experiment as Ferryman's pile")


def test_experiment_can_be_ferrymans_extra_non_supply_pile():
    """Experiment costs $3, so it is a legal Ferryman pile — "an unused Kingdom
    card pile costing $3 or $4", which is IN THE GAME and NOT in the Supply
    (ph. 3H's `nonsupply`). Gaining a Ferryman gains one from that pile, and
    Experiment's own when-gain chains a second (Experiment 3: "when you gain an
    Experiment due to Experiment's when-gain, the when-gain doesn't trigger
    again" — the Port marker on the gain EVENT)."""
    g = _ferryman_experiment_board()
    assert "Experiment" not in g["supply"]
    assert g["nonsupply"]["Experiment"] == 10
    assert engine.pile_count(g, "Experiment") == 10
    assert gain(g, A, "Ferryman")
    drain(g)
    assert g["seats"][A]["discard"].count("Experiment") == 2, "the chain fired once"
    assert engine.pile_count(g, "Experiment") == 8


def test_experiment_returns_to_ferrymans_pile_not_to_the_supply():
    """2022 errata: Experiment returns "to its PILE" (1V said "the Supply"),
    which is the whole reason it works as Ferryman's extra pile — there is no
    Supply pile to return to."""
    g = _ferryman_experiment_board()
    give_hand(g, A, ["Experiment", "Copper"])
    give_deck(g, A, ["Copper"] * 8)
    before = engine.pile_count(g, "Experiment")
    play(g, A, "Experiment")
    drain(g)
    assert g["seats"][A]["in_play"] == [], "returned, not left in play"
    assert engine.pile_count(g, "Experiment") == before + 1
    assert g["nonsupply"]["Experiment"] == before + 1, "it went home to the pile"


# =============================================================================
# INNOVATION x the shipped when-gain family
# =============================================================================

INNO_K = ["Villa", "Village", "Smithy", "Market", "Laboratory", "Festival",
          "Bishop", "Patron", "Seer", "Improve"]


def _buy_villa_with_innovation():
    g = fresh(INNO_K, ["renaissance", "empires", "base"], landscapes=["Innovation"])
    give_cube(g, "Innovation", A)
    give_hand(g, A, ["Copper"])
    to_buy(g, A)
    g["coins"] = 8
    assert mv(g, A, {"type": "buy", "card": "Villa"})[0]
    # the pool: Villa's own when-gain and Innovation's offer, in either order
    assert frame(g)["card"] == "__abilities"
    return g, [o["label"] for o in frame(g)["constraint"]["options"]]


def test_innovation_and_villas_own_when_gain_are_one_pool_the_player_orders():
    """Innovation 4 and Villa 5 (p. 160). Both fire on the same gain, so p23 §2
    puts them in one pool and the ORDER is the player's — and the two orders
    genuinely differ, which is the whole point of the pool."""
    g, labels = _buy_villa_with_innovation()
    assert labels == ["Villa", "Innovation"]


def test_a_gained_and_played_villa_cannot_put_itself_into_your_hand():
    """Villa 5: "When you put Villa into your hand, cards like Watchtower lose
    track of it. If you instead move it with Watchtower first, Villa fails to
    move itself to your hand, but you still get +1 Action and return to your
    Action phase." Innovation is the same shape — resolve it FIRST and the
    Villa is in play, so its own when-gain loses track of it."""
    g, _ = _buy_villa_with_innovation()
    assert decide(g, A, ids=["1"])[0]                 # Innovation first
    assert frame(g)["card"] == "Innovation"
    assert decide(g, A, ids=["yes"])[0]
    drain(g)
    assert g["seats"][A]["in_play"] == ["Villa"]
    assert "Villa" not in g["seats"][A]["hand"]
    assert [e for e in g["log"]
            if e.get("event") == "lost_track" and e.get("card") == "Villa"], \
        "the failed self-move must be logged, not silent"
    # ...and the rest of Villa's when-gain still happened
    assert [e for e in g["log"] if e.get("event") == "phase"
            and e.get("phase") == "action"], "still returned to the Action phase"
    assert g["turn_ctx"]["innovation_used"]


def test_innovation_playing_a_gained_attack_opens_the_reaction_window():
    """Innovation plays the gained card, and a played Attack is a played Attack:
    the reaction window opens for every opponent holding a Moat, exactly as it
    would from hand."""
    g = fresh(["Militia", "Moat", "Village", "Smithy", "Market", "Laboratory",
               "Festival", "Bishop", "Patron", "Improve"],
              ["renaissance", "base"], landscapes=["Innovation"])
    give_cube(g, "Innovation", A)
    give_hand(g, B, ["Moat", "Copper", "Copper", "Copper", "Copper"])
    give_hand(g, A, ["Copper"])
    to_buy(g, A)
    g["coins"] = 4
    assert mv(g, A, {"type": "buy", "card": "Militia"})[0]
    assert frame(g)["card"] == "Innovation"
    assert decide(g, A, ids=["yes"])[0]
    assert g["pending_pid"] == B, "no reaction window for the Innovation play"
    assert frame(g)["card"] == "Moat"


# =============================================================================
# FLEET — the game-end restructure meets the extra-turn family
# =============================================================================

FLEET_K = ["Village", "Smithy", "Market", "Laboratory", "Festival", "Bishop",
           "Patron", "Seer", "Improve", "Moat"]


def test_the_fleet_round_roster_starts_after_the_last_regular_turn():
    """Fleet (p. 92): "only players who have bought Fleet get a regular turn in
    this round. The first player to get a Fleet turn is the next player after
    the player who last had a regular turn." And "once the last Fleet turn has
    been played, the game is immediately over"."""
    g = fresh(FLEET_K, ["renaissance", "base"], landscapes=["Fleet"],
              players=(A, B, C))
    give_cube(g, "Fleet", B)
    give_cube(g, "Fleet", C)
    g["supply"]["Province"] = 1
    to_buy(g, A)
    g["coins"] = 8
    assert mv(g, A, {"type": "buy", "card": "Province"})[0]
    end_turn(g, A)
    drain(g)
    assert not g["over"], "the game continues for the Fleet round"
    assert [e["players"] for e in events(g, "fleet_round")] == [[B, C]]
    assert g["turn"] == B and g["fleet"]["on_turn"]
    end_turn(g, B)
    drain(g)
    assert g["turn"] == C and not g["over"]
    end_turn(g, C)
    drain(g)
    assert g["over"], "immediately over after the last Fleet turn"
    # "Like extra turns, these Fleet turns are not counted for tie-breaker"
    assert [g["seats"][p]["turns_taken"] for p in (A, B, C)] == [1, 0, 0]


def test_a_queued_outpost_turn_resolves_before_the_fleet_round():
    """Fleet (p. 92): "any extra turns (from … Outpost …) that were already in
    queue, which would normally not be resolved if the game had ended, will now
    be resolved." The Outpost turn keeps its own 3-card hand."""
    g = fresh(["Outpost"] + FLEET_K[:9], ["renaissance", "seaside", "base"],
              landscapes=["Fleet"])
    give_cube(g, "Fleet", B)
    give_hand(g, A, ["Outpost", "Copper"])
    play(g, A, "Outpost")
    g["supply"]["Province"] = 1
    to_buy(g, A)
    g["coins"] = 8
    assert mv(g, A, {"type": "buy", "card": "Province"})[0]
    end_turn(g, A)
    drain(g)
    assert g["turn"] == A and g["extra_turn"], "the Outpost turn came first"
    assert len(g["seats"][A]["hand"]) == 3
    assert g["fleet"] == {"remaining": [B], "on_turn": False}
    end_turn(g, A)
    drain(g)
    assert g["turn"] == B and g["fleet"]["on_turn"] and not g["over"]
    end_turn(g, B)
    drain(g)
    assert g["over"]


def test_the_fleet_round_also_triggers_on_a_colony_ending():
    """The end check has three branches and Fleet must sit in front of all of
    them: "there's an extra round of turns" after the game WOULD end, however it
    ends. Colony-empty is the Prosperity branch."""
    for seed in range(300):
        g = fresh(["Bishop", "Watchtower", "Peddler", "Charlatan", "Monument",
                   "Rabble", "Mint", "Vault", "City", "Quarry"],
                  ["prosperity", "renaissance"], landscapes=["Fleet"], seed=seed)
        if g["colony"]:
            break
    else:
        raise AssertionError("no seed in 0..299 produced a Colony game")
    give_cube(g, "Fleet", A)
    g["supply"]["Colony"] = 0
    end_turn(g, A)
    drain(g)
    assert not g["over"]
    assert [e["players"] for e in events(g, "fleet_round")] == [[A]]
    # B has no cube, so the round is A alone and ends the game
    assert g["turn"] == A and g["fleet"]["on_turn"]
    end_turn(g, A)
    drain(g)
    assert g["over"]


def test_buying_fleet_during_the_fleet_round_grants_nothing():
    """"The round's roster was fixed when the round began" — a Project buy runs
    no `LANDSCAPE_FX` at all, and `_fleet_owners` is only consulted once, at the
    end check that opened the round."""
    g = fresh(FLEET_K, ["renaissance", "base"], landscapes=["Fleet"])
    give_cube(g, "Fleet", A)
    g["supply"]["Province"] = 0
    end_turn(g, A)
    drain(g)
    assert g["fleet"] == {"remaining": [], "on_turn": True} and g["turn"] == A
    to_buy(g, A)
    g["coins"] = 5
    assert mv(g, A, {"type": "buy_landscape", "name": "Fleet"})[0]
    assert g["landscapes"]["Fleet"]["bought_by"] == [A, A] or \
        g["landscapes"]["Fleet"]["bought_by"] == [A]
    end_turn(g, A)
    drain(g)
    assert g["over"], "no second Fleet turn for a cube bought during the round"


# =============================================================================
# STAR CHART x the shipped shufflers
# =============================================================================

def test_star_chart_picks_when_inn_shuffles_your_discard_into_your_deck():
    """Star Chart (p. 149): "This also works when you shuffle your existing deck
    with Annex, Donate, Famine or Inn." `shuffle_into_deck` pushes the pick
    frame itself, so anything the caller must do afterwards has to be a
    continuation pushed BEFORE the call (Kernel v9)."""
    g = fresh(["Inn", "Village", "Smithy", "Market", "Laboratory", "Festival",
               "Bishop", "Patron", "Seer", "Improve"],
              ["renaissance", "hinterlands", "base"], landscapes=["Star Chart"])
    give_cube(g, "Star Chart", A)
    g["seats"][A]["discard"] = ["Smithy", "Village", "Estate"]
    g["seats"][A]["deck"] = ["Copper"] * 3
    assert gain(g, A, "Inn")
    assert frame(g)["card"] == "Inn"
    assert decide(g, A, cards=["Smithy", "Village"])[0]
    assert frame(g)["card"] == "Star Chart"
    assert decide(g, A, cards=["Smithy"])[0]
    assert g["seats"][A]["deck"][0] == "Smithy"
    assert len(g["seats"][A]["deck"]) == 5


def test_star_chart_picks_through_donates_whole_deck_shuffle():
    """Donate (ADVENTURES, 2021) rebuilds the deck at the start of your next
    turn and then shuffles your hand back in — the other `shuffle_into_deck`
    caller, and the one Donate was reshaped for so the pick frame has somewhere
    to park."""
    g = fresh(["Village", "Smithy", "Market", "Laboratory", "Festival",
               "Bishop", "Patron", "Seer", "Improve", "Moat"],
              ["renaissance", "adventures", "base"],
              landscapes=["Star Chart", "Donate"])
    give_cube(g, "Star Chart", A)
    to_buy(g, A)
    g["coins"] = 0
    assert mv(g, A, {"type": "buy_landscape", "name": "Donate"})[0]
    end_turn(g, A)
    drain(g)
    end_turn(g, B)
    drain(g, cap=400) if g["pending"] else None
    assert g["turn"] == A
    # Donate's own trash choice, then the Star Chart pick on the reshuffle
    seen = []
    for _ in range(20):
        if not g["pending"]:
            break
        seen.append(frame(g)["card"])
        if frame(g)["card"] == "Star Chart":
            assert decide(g, A, cards=["Estate"])[0]
        else:
            assert decide(g, A, cards=[])[0]
    assert "Star Chart" in seen, "no pick offered on Donate's reshuffle"
    assert g["seats"][A]["hand"][0] == "Estate", "the pick was drawn first"


def test_the_minus_one_card_token_does_not_move_the_star_chart_pick():
    """The −1 Card token (ADVENTURES) eats the next DRAW and nothing else — it
    does not change the shuffle, so the picked card is still on top afterwards
    (and is drawn, since the token only reduces the count)."""
    g = fresh(["Village", "Smithy", "Market", "Laboratory", "Festival",
               "Bishop", "Patron", "Seer", "Improve", "Moat"],
              ["renaissance", "adventures", "base"], landscapes=["Star Chart"])
    give_cube(g, "Star Chart", A)
    seat = g["seats"][A]
    seat["deck"], seat["hand"] = [], []
    seat["discard"] = ["Gold", "Estate", "Estate", "Estate", "Estate"]
    assert engine.take_seat_token(g, A, "-card")
    engine.final_draw(g, A, 3)
    engine._drive(g)
    assert frame(g)["card"] == "Star Chart"
    assert decide(g, A, cards=["Gold"])[0]
    assert seat["hand"][0] == "Gold", "the pick still landed on top"
    assert len(seat["hand"]) == 2, "the token ate one of the three"
    assert seat["tokens"] == {}, "and came off"


# =============================================================================
# PATRON — "when something causes you to REVEAL this"
# =============================================================================

def test_a_bureaucrat_forced_hand_reveal_pays_every_patron_in_it():
    """Patron's trigger is the WORD "reveal", and it fires "in an Action phase
    (which includes an OPPONENT's Action phase)". Bureaucrat (BASE) forces a
    victim with no Victory card to reveal their whole hand — and the emit is a
    BATCH for the cards' owner, so two Patrons pool to +2 Coffers."""
    g = fresh(["Bureaucrat", "Patron", "Village", "Smithy", "Market",
               "Laboratory", "Festival", "Bishop", "Seer", "Improve"],
              ["renaissance", "base"])
    give_hand(g, A, ["Bureaucrat"])
    give_hand(g, B, ["Patron", "Patron", "Copper"])
    play(g, A, "Bureaucrat")
    drain(g)
    assert g["coffers"] == {A: 0, B: 2}


def test_a_buy_phase_reveal_and_a_trash_pay_no_patron_coffers():
    """The 2022 errata confined Patron to an Action phase, which is what kills
    the Pursue infinite — so Investment (PROSPERITY), a Buy-phase Treasure that
    reveals your hand, pays nothing. And "discarding or trashing a Patron does
    not count as revealing it, even though the other players can see it"."""
    g = fresh(["Investment", "Patron", "Chapel", "Smithy", "Market",
               "Laboratory", "Festival", "Bishop", "Seer", "Improve"],
              ["renaissance", "prosperity", "base"])
    give_hand(g, A, ["Investment", "Patron", "Copper"])
    to_buy(g, A)
    assert mv(g, A, {"type": "play_treasure", "card": "Investment"})[0]
    assert decide(g, A, ids=["vp"])[0] if frame(g)["kind"] == "choose_option" \
        else decide(g, A, cards=["Patron"])[0]
    drain(g)
    revealed = [e for e in events(g, "reveal") if "Patron" in (e.get("cards") or [])]
    assert revealed, "control: the hand really was revealed"
    assert g["coffers"][A] == 0, "a Buy-phase reveal pays nothing"

    g = fresh(["Investment", "Patron", "Chapel", "Smithy", "Market",
               "Laboratory", "Festival", "Bishop", "Seer", "Improve"],
              ["renaissance", "prosperity", "base"])
    give_hand(g, A, ["Chapel", "Patron", "Patron"])
    play(g, A, "Chapel")
    assert decide(g, A, cards=["Patron", "Patron"])[0]
    drain(g)
    assert g["trash"] == ["Patron", "Patron"]
    assert g["coffers"][A] == 0, "trashing is not revealing"


def test_every_reveal_call_site_is_the_single_choke_point_for_patron():
    """The audit the kernel delta owes: `reveal()` is the ONLY thing that emits
    `reveal`, so a "reveal"-worded card that logged without calling it would be
    silently invisible to Patron. Sweeping the ten effects modules, every
    module that has a revealing card calls `E.reveal(`."""
    import inspect
    import re
    from games.dontminion import (effects_base, effects_intrigue, effects_seaside,
                                  effects_prosperity, effects_hinterlands,
                                  effects_cornucopia, effects_alchemy,
                                  effects_darkages, effects_adventures,
                                  effects_empires, effects_renaissance)
    mods = [effects_base, effects_intrigue, effects_seaside, effects_prosperity,
            effects_hinterlands, effects_cornucopia, effects_alchemy,
            effects_darkages, effects_adventures, effects_empires,
            effects_renaissance]
    for m in mods:
        src = inspect.getsource(m)
        # every module in the pool ships at least one revealing card
        assert "E.reveal(" in src, m.__name__
        # ...and nothing hand-rolls the log entry instead
        assert not re.search(r"_log\([^)]*['\"]reveal['\"]", src), \
            f"{m.__name__} logs a reveal without going through reveal()"
