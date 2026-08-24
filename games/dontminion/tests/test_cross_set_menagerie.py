"""Cross-set tests for phase 10 (MENAGERIE) — the combos where EXILE, WAYS and
HORSES meet the eleven already-shipped sets.

Step 5 of the per-phase playbook, and it is not optional: a card batch can only
ever be as correct as the precedent it copies, so per-set tests structurally
cannot find the class of bug where a NEW rule meets an OLD card. Everything
here builds a board that mixes Menagerie with at least one shipped expansion
through the forced-board `kingdom=` / `landscapes=` seams, and drives real
moves.

Every test names the rule it encodes and the compendium ruling it comes from
(Knutsen v11.1).

TWO DEFECTS FOUND, both in the KERNEL, each with a test that fails without its
fix (marked FOUND BUG in the docstring):

  1. **Way of the Mouse x every shipped Reaction** (Menagerie x Base/Intrigue/
     Seaside/…) — `test_a_way_of_the_mouse_attack_still_opens_the_reaction_window`.
     `play_mouse_card` ran the Mouse card's ability through
     `_run_supply_ability` unconditionally, while BOTH of its siblings in ch.
     VI's PLAY A CARD WHILE LEAVING IT family (`play_from_supply`,
     `play_set_aside`) branch on `has_type(card, "attack")` and open the
     reaction window first. A Swindler / Urchin / Ambassador / Fortune Teller
     Mouse card therefore hit a Moat holder with no window, no reveal and no
     immunity. Ch. VII Way of the Mouse names Swindler itself.
     The fix opens the loop this creates — the Mouse card's own play is an
     Action play, so Way of the Mouse would offer itself again, forever — which
     is why `_way_of_the_mouse_when` now refuses a play OF the Mouse card
     ("if there are two Ways in the game, you may use **the other** Way when
     playing the Mouse card", ch. VII).
  2. **Way of the Mouse's card brought no special setup** (Menagerie x
     Renaissance / Dark Ages / Adventures) —
     `test_a_border_guard_mouse_card_keeps_its_artifacts_available` and its
     three pile twins. Ch. I's Menagerie setup paragraph ends "*if this Action
     card has a special setup rule, do that setup*", and the Mouse card is BY
     DEFINITION not in the kingdom, so `in_play_cards` could not see it: a
     Border Guard Mouse card kept no Lantern or Horn (and its play ability then
     silently took nothing), an Urchin/Hermit one built no Mercenary/Madman
     pile, and a Page/Peasant one built no Traveller chain. The Bane/Ferryman
     clause four lines above says exactly this for its own extra piles.

TWO DIVERGENCES are pinned as PASSING tests rather than fixed, and are
candidate rows for CLAUDE.md's standing list — see the module report:

  * `test_a_way_is_offered_for_a_supply_played_attack_but_not_a_supply_played_action`
    — `_run_supply_ability` emits no `would_resolve`, so an Overlord (or Band
    of Misfits, or an inherited Estate) playing a Village offers no Way while
    the same Overlord playing a Militia does, because the attack path reaches
    the window through `_open_attack_window`. Inherited from ph. 8 (Enchantress
    has the same asymmetry); ph. 10 is what makes it routine.
  * Seize the Day was found NOT to honour ch. VII's documented exception to
    the 2023 no-third-turn rule ("you will get both extra turns as long as you
    take the Seize the Day turn last. This would give you three turns in a
    row"). It is a stated exception rather than an ambiguity, so it was FIXED
    in the kernel rather than ledgered — `_seize` is the one extra-turn slot
    that survives until a turn end with nothing else to grant, which is what
    "taken last" means. Pinned here with its single-source control.
"""

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


def pick(g, pid, oid):
    ok, err = decide(g, pid, ids=[oid])
    assert ok, err


def cards_(g, pid, picked):
    ok, err = decide(g, pid, cards=list(picked))
    assert ok, err


def pile(g, pid, name):
    ok, err = decide(g, pid, pile=name)
    assert ok, err


def give_hand(g, pid, cards_list):
    g["seats"][pid]["hand"] = list(cards_list)


def give_deck(g, pid, cards_list):
    g["seats"][pid]["deck"] = list(cards_list)


def give_cube(g, name, pid):
    g["landscapes"][name]["bought_by"].append(pid)


def play(g, pid, card):
    ok, err = mv(g, pid, {"type": "play_action", "card": card})
    assert ok, err


def buy(g, pid, card):
    ok, err = mv(g, pid, {"type": "buy", "card": card})
    assert ok, err


def events(g, name):
    return [e for e in g["log"] if e.get("event") == name]


def end_turn(g, pid):
    """End pid's turn — at most one phase step per phase, so an extra turn
    granted by the hand-off is NOT immediately ended as well."""
    if g["turn"] == pid and g["phase"] == "action" and not g["pending"]:
        ok, err = mv(g, pid, {"type": "end_phase"})
        assert ok, err
    if g["turn"] == pid and g["phase"] == "buy" and not g["pending"]:
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


def pass_turn_to(g, pid):
    """End turns until it is pid's again. Deliberately does NOT require the
    action phase: a hand of Coppers auto-advances (`_maybe_auto_buy`), which is
    correct and would otherwise look like a stall."""
    for i in range(12):
        if i and g["turn"] == pid and not g["pending"]:
            return
        end_turn(g, g["turn"])
        drain(g)
    raise AssertionError("never reached %s" % pid)


def horse_to_hand(g, pid):
    """A Horse in hand, taken off the real pile so the count stays honest."""
    assert engine.gain_from(g, pid, "Horse", dest="hand")
    engine._drive(g)


# =============================================================================
# WAY OF THE MOUSE x THE ELEVEN SHIPPED SETS
# The Mouse card is drawn from the kingdom cards this game did NOT deal, so it
# is the one object in the game that no "is it in the kingdom?" test can see.
# Both of this batch's defects live there.
# =============================================================================

MOUSE_KINGDOM = ["Village", "Smithy", "Market", "Laboratory", "Festival",
                 "Moat", "Cellar", "Militia", "Workshop", "Bureaucrat"]


def test_a_way_of_the_mouse_attack_still_opens_the_reaction_window():
    """FOUND BUG (kernel, fixed in `engine.play_mouse_card`).

    Ch. IV WAYS makes a Way usable "whenever any Action card is played", and
    ch. VII Way of the Mouse contemplates an ATTACK Mouse card by name: "when
    it's not your turn, if you play a card that affects the other players (like
    Swindler or Catapult), start with the current player." An Attack being
    played owes its victims a reaction window — `play_from_supply` and
    `play_set_aside`, the two other members of ch. VI's PLAY A CARD WHILE
    LEAVING IT family, both branch on the attack type and call
    `_open_attack_window` — and `play_mouse_card` did not, so a Moat in hand
    was never offered and its holder was not immune.

    Both branches are asserted: revealing the Moat protects, declining does
    not (without the control a Swindler that simply stopped working would
    pass)."""
    g = fresh(MOUSE_KINGDOM, ["base", "intrigue", "menagerie"],
              landscapes=["Way of the Mouse"])
    g["mouse_card"] = "Swindler"
    give_hand(g, A, ["Village"])
    give_deck(g, A, ["Copper"] * 10)
    give_hand(g, B, ["Moat"])
    give_deck(g, B, ["Copper", "Gold"])
    play(g, A, "Village")
    pick(g, A, "way")
    assert frame(g)["card"] == "__attack" and frame(g)["pid"] == B, \
        "an Attack played by Way of the Mouse must open a reaction window"
    assert "react:Moat" in opt_ids(g)
    pick(g, B, "react:Moat")
    assert not g["pending"]
    assert g["seats"][B]["deck"] == ["Copper", "Gold"], "Moat = unaffected"
    assert g["trash"] == []


def test_declining_the_moat_lets_the_mouse_card_swindler_through():
    """The control for the test above: the window is real, not a stall."""
    g = fresh(MOUSE_KINGDOM, ["base", "intrigue", "menagerie"],
              landscapes=["Way of the Mouse"])
    g["mouse_card"] = "Swindler"
    give_hand(g, A, ["Village"])
    give_deck(g, A, ["Copper"] * 10)
    give_hand(g, B, ["Moat"])
    give_deck(g, B, ["Copper", "Gold"])
    play(g, A, "Village")
    pick(g, A, "way")
    pick(g, B, "decline")
    assert g["trash"] == ["Copper"], "no Moat reveal: Swindler trashes"
    # ...and the victim is handed the "gain a card costing exactly $0" choice
    assert frame(g)["card"] == "Swindler" and frame(g)["pid"] == A


def test_way_of_the_mouse_is_not_offered_for_the_mouse_cards_own_play():
    """Ch. VII Way of the Mouse: "if there are two Ways in the game, you may use
    **the other** Way when playing the Mouse card." The wording excludes this
    Way from its own card's play, and it has to: the Mouse card's play is an
    Action play, so an offer there plays the Mouse card again, and again.

    Unreachable before the fix above (a play-while-leaving-it play only reaches
    the `would_resolve` window through the attack path), which is exactly why
    it is pinned here beside it."""
    g = fresh(MOUSE_KINGDOM, ["base", "intrigue", "menagerie"],
              landscapes=["Way of the Mouse"])
    g["mouse_card"] = "Swindler"
    give_hand(g, A, ["Village"])
    give_deck(g, A, ["Copper"] * 10)
    give_hand(g, B, [])
    give_deck(g, B, ["Copper", "Gold"])
    play(g, A, "Village")
    pick(g, A, "way")
    # the Swindler resolved once: its victim's card is trashed and A is asked
    # what to give them. No second Way offer anywhere on the stack.
    assert g["trash"] == ["Copper"]
    assert not [f for f in g["pending"] if f["card"] == "Way of the Mouse"]
    assert len(events(g, "play_mouse")) == 1


def test_a_border_guard_mouse_card_keeps_its_artifacts_available():
    """FOUND BUG (kernel, fixed in `engine.new_game`).

    Ch. I SPECIAL SETUP: MENAGERIE ends "*if this Action card has a special
    setup rule, do that setup; see elsewhere in this section*". Border Guard
    ($2, Renaissance, non-Duration Action) is an eligible Mouse card, and its
    setup rule is "keep the Lantern and Horn Artifacts available". The pick sat
    BELOW every setup block and none of them could see it, so `game["artifacts"]`
    stayed empty and `take_artifact` was a silent no-op: the play offered no
    choice at all.

    Driven end to end rather than asserted on the dict, because the observable
    failure was the missing PROMPT."""
    g = fresh(["Village", "Smithy", "Market", "Laboratory", "Festival", "Moat",
               "Cellar", "Militia", "Workshop", "Improve"],
              ["base", "renaissance", "menagerie"],
              landscapes=["Way of the Mouse"])
    # the pick is random over the unused kingdom; the seam under test is the
    # SETUP, so force the card and re-run setup's artifact clause the way
    # new_game does — see the roster test below for the un-forced path.
    assert set(g["artifacts"]) == set(), "no Border Guard in this kingdom"
    g["mouse_card"] = "Border Guard"
    for art in cards.artifacts_for(["Border Guard"]):
        g["artifacts"].setdefault(art, None)
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Village", "Village", "Silver", "Gold"])
    play(g, A, "Smithy")
    pick(g, A, "way")
    cards_(g, A, ["Village"])
    assert frame(g)["card"] == "Border Guard" and frame(g)["stage"] == "take"
    assert opt_ids(g) == ["Lantern", "Horn"]


def test_new_game_gives_every_mouse_card_its_own_setup():
    """The un-forced half of the bug above: `new_game` itself must build what
    the Mouse card brings. Four shipped setup rules are reachable from a
    $2/$3 non-Duration Action — Border Guard's Artifacts (Renaissance),
    Urchin's Mercenary and Hermit's Madman (Dark Ages) and Page/Peasant's
    Traveller chain (Adventures).

    Seeds are SEARCHED for rather than guessed, and every one of the four
    shapes must be found — a search that quietly found none would be a skip
    wearing a pass."""
    want = {
        "Border Guard": (["renaissance"],
                         lambda g: set(g["artifacts"]) == {"Lantern", "Horn"}),
        "Urchin": (["darkages"], lambda g: "Mercenary" in g["piles"]),
        "Hermit": (["darkages"], lambda g: "Madman" in g["piles"]),
        "Page": (["adventures"],
                 lambda g: "Treasure Hunter" in g["piles"] and "Champion" in g["piles"]),
        "Peasant": (["adventures"],
                    lambda g: "Fugitive" in g["piles"] and "Teacher" in g["piles"]),
    }
    for card, (exps, ok) in want.items():
        for seed in range(600):
            g = engine.new_game([A, B], exps + ["menagerie"], seed=seed,
                                landscapes=["Way of the Mouse"])
            if g["mouse_card"] != card:
                continue
            assert ok(g), f"{card} as the Mouse card brought no setup"
            break
        else:
            raise AssertionError(f"no seed made {card} the Mouse card")


def test_the_mouse_card_is_never_a_duration_on_any_board():
    """The 2025 erratum, enforced at setup, across a wide seed sweep — ch. I was
    never updated for it and still says plain "Action"."""
    seen = set()
    for seed in range(120):
        g = engine.new_game([A, B], ["seaside", "adventures", "renaissance",
                                     "menagerie"], seed=seed,
                            landscapes=["Way of the Mouse"])
        mc = g["mouse_card"]
        if mc is None:
            continue
        seen.add(mc)
        assert "duration" not in cards.CARDS[mc]["types"], mc
        assert cards.CARDS[mc]["cost"] in (2, 3)
        assert mc not in g["kingdom"]
    assert len(seen) >= 3, "the sweep never varied the pick"


# =============================================================================
# WAYS x THE CARDS THAT WRAP OR REPLACE A PLAY
# =============================================================================

WAY_KINGDOM = ["Village", "Smithy", "Market", "Laboratory", "Festival",
               "Moat", "Cellar", "Militia", "Workshop"]


def test_a_duration_played_with_a_way_does_not_stay_in_play():
    """Ch. IV WAYS: "A Duration played using a Way doesn't set anything up
    (even if it's the first version of Lighthouse or Bridge Troll), so it's
    discarded in Clean-up." Free from Kernel v2 ("an effect that registers
    NOTHING failed to set up"), and worth pinning because it is the rule three
    other tests here compose against."""
    g = fresh(["Caravan"] + WAY_KINGDOM, ["base", "seaside", "menagerie"],
              landscapes=["Way of the Sheep"])
    give_hand(g, A, ["Caravan"])
    give_deck(g, A, ["Copper"] * 10)
    play(g, A, "Caravan")
    pick(g, A, "way")
    assert g["coins"] == 2
    end_turn(g, A)
    assert g["seats"][A]["duration"] == []
    assert "Caravan" in g["seats"][A]["discard"]


def test_a_throne_roomed_duration_stays_in_play_if_any_play_was_normal():
    """Ch. IV WAYS: "If you play a Duration multiple times with a throne-room,
    it stays in play if it was played normally (not using a Way) at least one
    of the times. The throne-room then also stays in play." Our duration entry
    is per PHYSICAL card with an fx list, so a Way'd replay simply adds nothing
    — all four branches of the 2x2 are asserted."""
    def run(first, second):
        g = fresh(["Caravan", "Throne Room"] + WAY_KINGDOM[:8],
                  ["base", "seaside", "menagerie"],
                  landscapes=["Way of the Sheep"])
        give_hand(g, A, ["Throne Room", "Caravan"])
        give_deck(g, A, ["Copper"] * 10)
        play(g, A, "Throne Room")
        pick(g, A, "normal")             # the Throne Room itself
        cards_(g, A, ["Caravan"])
        pick(g, A, first)
        pick(g, A, second)
        coins = g["coins"]          # read BEFORE Clean-up empties the pool
        end_turn(g, A)
        return g, coins

    for first, second in (("normal", "way"), ("way", "normal"),
                          ("normal", "normal")):
        g, coins = run(first, second)
        assert coins == 2 * (first, second).count("way"), (first, second)
        assert len(g["seats"][A]["duration"]) == 1, (first, second)
        entry = g["seats"][A]["duration"][0]
        assert entry["card"] == "Caravan"
        assert entry["riders"] == ["Throne Room"], (first, second)
    g, coins = run("way", "way")
    assert coins == 4, "two Way of the Sheep resolutions"
    assert g["seats"][A]["duration"] == [], "both plays Way'd: nothing set up"
    assert sorted(g["seats"][A]["discard"]) == ["Caravan", "Throne Room"]


def test_after_play_abilities_still_fire_after_a_wayd_play():
    """Ch. IV WAYS: "After-play abilities (such as Coin of the Realm, Royal
    Carriage, Citadel …) still trigger after you play an Action card using a
    Way." Royal Carriage is ADVENTURES and Citadel is RENAISSANCE, so this is
    the same kernel seam read from two sets — and the Royal Carriage replay
    re-enters `play_action_card`, so the Way is offered again ("if you replay a
    card with a throne-room, you choose each time")."""
    g = fresh(["Royal Carriage"] + WAY_KINGDOM, ["base", "adventures", "menagerie"],
              landscapes=["Way of the Sheep"])
    g["seats"][A]["tavern"] = ["Royal Carriage"]
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Copper"] * 10)
    play(g, A, "Smithy")
    pick(g, A, "way")
    assert g["coins"] == 2
    assert frame(g)["card"] == "Royal Carriage"
    pick(g, A, "play")
    assert frame(g)["card"] == "Way of the Sheep", "the replay asks again"
    pick(g, A, "normal")
    assert len(g["seats"][A]["hand"]) == 3, "the replay drew Smithy's 3"

    g = fresh(WAY_KINGDOM + ["Improve"], ["base", "renaissance", "menagerie"],
              landscapes=["Citadel", "Way of the Sheep"])
    give_cube(g, "Citadel", A)
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Copper"] * 10)
    play(g, A, "Smithy")
    pick(g, A, "way")
    assert frame(g)["card"] == "Way of the Sheep", "Citadel replayed it"
    pick(g, A, "normal")
    assert g["coins"] == 2 and len(g["seats"][A]["hand"]) == 3


def test_a_way_is_offered_for_a_supply_played_attack_but_not_a_supply_played_action():
    """DIVERGENCE, pinned rather than fixed — a candidate CLAUDE.md row.

    `play_from_supply` (Overlord, Band of Misfits), `play_set_aside`
    (Inheritance's Estates) and `play_mouse_card` all run the borrowed ability
    through `_run_supply_ability`, which emits NO `would_resolve`. But their
    ATTACK branch goes through `_open_attack_window`, whose parked
    `__attack/play_ability` frame DOES call the gate. So one Overlord offers a
    Way for a Militia and not for a Village.

    Ch. IV WAYS ("whenever any Action card is played") and ch. VII Way of the
    Mouse ("you may use the other Way when playing the Mouse card") both say
    the offer belongs on BOTH paths. Not fixed here because closing it means a
    new `__play/resolve` routing flag AND a decision about whether an inherited
    Estate is one play or two — see the report."""
    def overlord_plays(target):
        g = fresh(["Overlord"] + WAY_KINGDOM, ["base", "empires", "menagerie"],
                  landscapes=["Way of the Sheep"])
        give_hand(g, A, ["Overlord"])
        give_deck(g, A, ["Copper"] * 10)
        give_hand(g, B, ["Copper"] * 5)
        play(g, A, "Overlord")
        assert frame(g)["card"] == "Way of the Sheep"   # for the Overlord
        pick(g, A, "normal")
        pile(g, A, target)
        return g

    g = overlord_plays("Village")
    assert not [f for f in g["pending"] if f["card"] == "Way of the Sheep"], \
        "today a Supply-played non-Attack gets no Way offer"
    assert g["actions"] == 2, "the Village's own ability ran"

    g = overlord_plays("Militia")
    assert frame(g)["card"] == "Way of the Sheep", \
        "...but a Supply-played Attack does, via the attack window"


# =============================================================================
# WAY OF THE CHAMELEON x THE SEAT TOKENS AND THE DURATIONS
# The +Cards/+$ swap is the widest-blast-radius item in the set.
# =============================================================================

def test_the_chameleon_swap_triggers_the_token_the_RESULT_deserves():
    """Ch. VII Way of the Chameleon 7: "Your −$ token and −1 Card token trigger
    on the CHANGED effects. (E.g., a Militia gives +2 Cards and will trigger
    your −1 Card token but not your −$ token.)" Both Adventures tokens, both
    directions, on one board."""
    # +$2 -> +2 Cards, and the -1 Card token eats one of them
    g = fresh(WAY_KINGDOM + ["Ratcatcher"], ["base", "adventures", "menagerie"],
              landscapes=["Way of the Chameleon"])
    g["seats"][A]["tokens"]["-card"] = True
    give_hand(g, A, ["Militia"])
    give_deck(g, A, ["Copper"] * 10)
    give_hand(g, B, ["Copper"] * 5)
    play(g, A, "Militia")
    pick(g, A, "way")
    assert g["coins"] == 0
    assert len(events(g, "minus_card_token")) == 1
    assert events(g, "draw")[-1]["count"] == 1, "2 swapped cards minus the token"
    assert g["seats"][A]["tokens"] == {}

    # ...and the other way: +3 Cards -> +$3, and the -$1 token eats a coin
    g = fresh(WAY_KINGDOM + ["Ratcatcher"], ["base", "adventures", "menagerie"],
              landscapes=["Way of the Chameleon"])
    g["seats"][A]["tokens"]["-coin"] = True
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Copper"] * 10)
    play(g, A, "Smithy")
    pick(g, A, "way")
    assert g["coins"] == 2, "+3 Cards became +$3, then the -$1 token"
    assert len(events(g, "minus_coin_token")) == 1
    assert g["seats"][A]["tokens"] == {}


def test_a_chameleond_duration_swaps_this_turn_and_not_the_next():
    """Ch. VII Way of the Chameleon 3: "Only +Cards and +$ you get THIS TURN are
    changed. For instance if you play Merchant Ship, you get +2 Cards this
    turn, but +$ next turn as normal." Wharf is the Seaside twin, and rule 9
    ("if the played card is a Duration, leave it in play as you normally
    would") is the counter-case to the Way'd-Duration test above — the
    Chameleon does not cancel the play, so the fx really is registered."""
    g = fresh(["Wharf"] + WAY_KINGDOM, ["base", "seaside", "menagerie"],
              landscapes=["Way of the Chameleon"])
    give_hand(g, A, ["Wharf"])
    give_deck(g, A, ["Copper"] * 20)
    play(g, A, "Wharf")
    pick(g, A, "way")
    assert g["coins"] == 2 and g["buys"] == 2
    assert g["seats"][A]["hand"] == [], "+2 Cards became +$2"
    end_turn(g, A)
    assert len(g["seats"][A]["duration"]) == 1, "rule 9: it stays in play"
    pass_turn_to(g, A)
    assert g["coins"] == 0
    assert len(g["seats"][A]["hand"]) == 7, "next turn the +2 Cards is normal"


# =============================================================================
# HORSES x THE PILE MODEL AND THE OLD SETS
# =============================================================================

HORSE_KINGDOM = ["Cavalry", "Village", "Smithy", "Market", "Laboratory",
                 "Festival", "Moat", "Cellar", "Militia"]


def test_throne_room_on_a_horse_gives_four_cards_and_returns_it_once():
    """Ch. VII Horse: "if you play Horse without moving it into play, you still
    get +2 Cards and +1 Action (Throne Room + Horse will give you +4 Cards and
    +2 Actions)". The second play finds nothing on the table and returns
    nothing — silently, because the card is where the player can see it."""
    g = fresh(["Throne Room"] + HORSE_KINGDOM, ["base", "menagerie"])
    give_deck(g, A, ["Copper"] * 12)
    give_hand(g, A, ["Throne Room"])
    horse_to_hand(g, A)
    before = engine.pile_count(g, "Horse")
    play(g, A, "Throne Room")
    cards_(g, A, ["Horse"])
    assert len(g["seats"][A]["hand"]) == 4, "+4 Cards"
    assert g["actions"] == 2, "+2 Actions (Throne Room spent the one it had)"
    assert engine.pile_count(g, "Horse") == before + 1, "returned exactly once"
    assert len(events(g, "return_to_pile")) == 1
    assert "Horse" not in g["seats"][A]["in_play"]


def test_procession_on_a_horse_loses_track_of_the_trash_and_still_gains():
    """DARK AGES x MENAGERIE. Procession "plays an Action twice, trashes it, and
    gains an Action costing exactly $1 more". Horse returns itself to its pile
    on the FIRST play, so there is nothing left to trash — the lose-track rule,
    which must SAY SO (the standing never-silent rule) — and the gain still
    happens, priced off Horse's $3."""
    g = fresh(["Procession"] + HORSE_KINGDOM, ["base", "darkages", "menagerie"])
    give_deck(g, A, ["Copper"] * 12)
    give_hand(g, A, ["Procession"])
    horse_to_hand(g, A)
    before = engine.pile_count(g, "Horse")
    play(g, A, "Procession")
    cards_(g, A, ["Horse"])
    assert engine.pile_count(g, "Horse") == before + 1
    assert g["trash"] == [], "the Horse was not on the table to trash"
    lost = events(g, "lost_track")
    assert lost and lost[-1]["card"] == "Horse" and lost[-1]["verb"] == "trashed"
    assert frame(g)["card"] == "Procession" and frame(g)["stage"] == "gain"
    # "exactly $1 more than it" = $4, Actions only
    assert all(engine.cost(g, p) == 4 for p in frame(g)["constraint"]["piles"])
    assert "Cavalry" in frame(g)["constraint"]["piles"]


def test_the_horse_pile_is_outside_the_supply_for_every_older_reader():
    """"Include the Horse pile (30 cards) OUTSIDE the Supply." Three shipped
    readers must all miss it, and each is a different mechanism: buying it
    (`game["supply"]`), a Workshop-class gain enumeration, and the
    three-empty-piles end (`count_empty_piles`)."""
    g = fresh(["Workshop"] + HORSE_KINGDOM[:9], ["base", "menagerie"])
    assert "Horse" in g["piles"] and "Horse" not in g["supply"]
    g["phase"] = "buy"
    g["coins"] = 20
    ok, err = mv(g, A, {"type": "buy", "card": "Horse"})
    assert not ok and err == "no such pile"
    g["phase"] = "action"
    give_hand(g, A, ["Workshop"])
    play(g, A, "Workshop")
    assert "Horse" not in frame(g)["constraint"]["piles"], "Workshop cannot reach it"
    decide(g, A, pile="Cellar")
    # drain it and the game-end count is unmoved
    g["nonsupply"]["Horse"] = 0
    g["piles"]["Horse"]["contents"] = None
    assert engine.count_empty_piles(g) == 0


def test_way_of_the_butterfly_returns_a_knight_to_its_ordered_pile():
    """DARK AGES x MENAGERIE. Ch. VII Way of the Butterfly: "you can't gain a
    card from the same pile you returned a card to (such as a split pile),
    since the returned card will be on top." Knights is a ph.-3H ordered pile,
    so the return must go back through `return_to_pile` and the gain list must
    be priced AFTER it — the Knights pile then shows the $5 card it just took
    back, not a $6 one."""
    g = fresh(["Knights"] + WAY_KINGDOM, ["base", "darkages", "menagerie"],
              landscapes=["Way of the Butterfly"])
    knight = engine.pile_top(g, "Knights")
    assert engine.cost(g, knight) == 5
    before = engine.pile_count(g, "Knights")
    engine._pile_take(g, "Knights")
    give_hand(g, A, [knight])
    give_deck(g, A, ["Copper"] * 10)
    give_deck(g, B, ["Copper"] * 10)
    play(g, A, knight)
    pick(g, A, "way")
    pick(g, A, "yes")
    assert engine.pile_count(g, "Knights") == before
    assert engine.pile_top(g, "Knights") == knight
    assert frame(g)["constraint"]["piles"] == ["Gold"], \
        "$6 only, and never the pile the Knight went back onto"


def test_way_of_the_butterfly_may_return_to_ferrymans_pile_but_not_gain_from_it():
    """CORNUCOPIA x MENAGERIE. Ch. VII Way of the Butterfly: "you may return a
    NON-KINGDOM card, AS LONG AS IT BELONGS TO A PILE" — Ferryman's extra pile
    is in the game and outside the Supply, so the return is legal; the GAIN
    reads the Supply, so that same pile can never be the thing you gain.
    (The seed is pinned because the extra pile is drawn from the unused
    kingdom, and the assertion is on the pile's identity, not its name.)"""
    g = engine.new_game([A, B], ["cornucopia", "menagerie"], seed=0,
                        kingdom=["Ferryman"] + WAY_KINGDOM,
                        landscapes=["Way of the Butterfly"])
    extra = [p for p in g["piles"] if p not in g["supply"] and p != "Horse"]
    assert len(extra) == 1, "Ferryman's extra pile"
    extra = extra[0]
    card = engine.pile_top(g, extra)
    engine._pile_take(g, extra)
    give_hand(g, A, [card])
    give_deck(g, A, ["Copper"] * 10)
    before = engine.pile_count(g, extra)
    play(g, A, card)
    pick(g, A, "way")
    pick(g, A, "yes")
    assert engine.pile_count(g, extra) == before + 1, "it belongs to a pile"
    assert extra not in frame(g)["constraint"]["piles"], \
        "...but 'gain a card' still means from the Supply"


# =============================================================================
# EXILE x EVERYTHING THAT COUNTS, MOVES OR SCORES CARDS
# =============================================================================

EXILE_KINGDOM = ["Camel Train", "Sheepdog", "Trader", "Watchtower", "Village",
                 "Smithy", "Market", "Laboratory", "Moat", "Cellar"]


def test_exiling_from_the_supply_fires_no_when_gain_watcher_in_any_set():
    """Ch. IV EXILE: "Exiling cards from the Supply is not considered gaining
    cards." Four shipped when-gain watchers are on the table at once —
    Watchtower (PROSPERITY), Trader (HINTERLANDS), Sheepdog (MENAGERIE) and the
    Innovation project (RENAISSANCE) — and NONE of them may see a Supply
    Exile. The control below is what makes it non-vacuous: a real gain of the
    same card offers all four."""
    g = fresh(EXILE_KINGDOM, ["base", "prosperity", "hinterlands", "menagerie",
                              "renaissance"], landscapes=["Innovation"])
    give_cube(g, "Innovation", A)
    give_hand(g, A, ["Camel Train", "Trader", "Watchtower", "Sheepdog"])
    give_deck(g, A, ["Copper"] * 10)
    play(g, A, "Camel Train")
    pile(g, A, "Gold")
    assert g["seats"][A]["exile"] == ["Gold"]
    assert not g["pending"], "no watcher may fire on a Supply Exile"
    assert events(g, "gain") == []

    # CONTROL: the same board, an ordinary gain, and the pool is full
    g2 = fresh(EXILE_KINGDOM, ["base", "prosperity", "hinterlands", "menagerie",
                               "renaissance"], landscapes=["Innovation"])
    give_cube(g2, "Innovation", A)
    give_hand(g2, A, ["Trader", "Watchtower", "Sheepdog"])
    engine.gain(g2, A, "Gold")
    engine._drive(g2)
    assert g2["pending"], "an actual gain still collects its watchers"


def test_discarding_from_exile_fires_an_older_sets_when_discard_ability():
    """Ch. VII Your Exile mat: "when you discard cards from your Exile mat,
    when-discard abilities (such as Faithful Hound, Trail, Tunnel, Village
    Green and Weaver) trigger." Tunnel is HINTERLANDS, and the discard is
    driven by the mat's OWN all-or-nothing when-gain ability — the kernel pool
    contributor, not a card."""
    g = fresh(["Tunnel", "Sanctuary", "Village", "Smithy", "Market",
               "Laboratory", "Festival", "Moat", "Cellar", "Militia"],
              ["base", "hinterlands", "menagerie"])
    g["seats"][A]["exile"] = ["Tunnel", "Tunnel"]
    give_hand(g, A, [])
    engine.gain(g, A, "Tunnel")
    engine._drive(g)
    assert frame(g)["card"] == "__exile"
    assert opt_ids(g) == ["yes", "no"], "all or nothing, never a choose_cards"
    pick(g, A, "yes")
    assert g["seats"][A]["exile"] == []
    assert events(g, "discard")[-1]["count"] == 2
    assert frame(g)["card"] == "Tunnel", "Tunnel's reveal-for-a-Gold offer"


def test_exiled_cards_score_for_the_old_victory_cards_and_the_landmarks():
    """Ch. IV EXILE: "Cards on your Exile mat are YOURS." So they score. Six
    shipped VP readers across four sets are asserted against the SAME deck with
    and without the mat, so the delta is the mat and nothing else: Gardens
    (base), Duke (intrigue), Fairgrounds (cornucopia), Feodum (dark ages), and
    the Empires landmarks Keep / Museum / Wall / Bandit Fort — all of which go
    through `engine.owned_cards`."""
    kingdom = ["Gardens", "Fairgrounds", "Duke", "Feodum", "Sanctuary",
               "Smithy", "Village", "Market", "Laboratory", "Moat"]
    exps = ["base", "intrigue", "cornucopia", "darkages", "empires", "menagerie"]
    lms = ["Keep", "Museum", "Wall", "Bandit Fort"]
    mat = ["Gardens", "Duke", "Duchy", "Feodum", "Silver", "Silver", "Silver"]

    bare = fresh(kingdom, exps, landscapes=lms)
    full = fresh(kingdom, exps, landscapes=lms)
    full["seats"][A]["exile"] = list(mat)

    assert engine.owned_cards(full, A).count("Duke") == 1
    assert engine._vp_of(full, A) > engine._vp_of(bare, A), "the mat scores"
    for lm in lms:
        fn = effects.LANDSCAPE_SCORING[lm]
        assert fn(full, A) != fn(bare, A), f"{lm} must see the Exile mat"
    # Wall and Bandit Fort are the two that get WORSE, which is the point:
    # an Exiled card is owned even when owning it hurts
    assert effects.LANDSCAPE_SCORING["Wall"](full, A) < \
        effects.LANDSCAPE_SCORING["Wall"](bare, A)
    assert effects.LANDSCAPE_SCORING["Bandit Fort"](full, A) == -6, \
        "3 Silvers on the mat"


def test_invest_pays_off_an_opponents_gain_of_a_card_from_another_set():
    """ADVENTURES x MENAGERIE. Invest ("Exile an Action card from the Supply.
    While it's in Exile, when another player gains or Invests in a copy of it,
    +2 Cards") is a REST-OF-THE-GAME landscape watcher, and it fires OFF-TURN —
    drawing is not a per-turn pool, so unlike +$ it does not evaporate."""
    g = fresh(["Amulet"] + WAY_KINGDOM, ["base", "adventures", "menagerie"],
              landscapes=["Invest"])
    mv(g, A, {"type": "end_phase"})
    g["coins"], g["buys"] = 8, 3
    ok, err = mv(g, A, {"type": "buy_landscape", "name": "Invest"})
    assert ok, err
    pile(g, A, "Amulet")
    assert g["seats"][A]["exile"] == ["Amulet"]
    assert sorted(w["event"] for w in g["watchers"]) == ["exile", "gain"]
    mv(g, A, {"type": "end_phase"})
    give_deck(g, A, ["Copper"] * 10)
    before = len(g["seats"][A]["hand"])
    engine.gain(g, B, "Amulet")
    engine._drive(g)
    assert len(g["seats"][A]["hand"]) == before + 2, "+2 Cards on B's turn"


def test_exiling_from_the_supply_can_empty_a_pile_for_the_game_end():
    """A Supply Exile really does take the card off the pile, so it counts
    toward the three-empty-piles end exactly like a gain would — and the Horse
    pile still cannot, however empty it gets."""
    g = fresh(["Camel Train"] + WAY_KINGDOM, ["base", "menagerie"])
    g["supply"]["Smithy"] = 1
    engine.exile(g, A, ["Smithy"], zone="supply")
    assert engine.pile_count(g, "Smithy") == 0
    assert engine.count_empty_piles(g) == 1


def test_village_green_reacts_to_militias_discard_and_does_not_discard_again():
    """BASE x MENAGERIE. Ch. VII Village Green: "if you need to DISCARD DOWN TO
    X CARDS IN HAND, you first discard all necessary cards, and then may react
    with Village Green to draw. You DON'T HAVE TO DISCARD AGAIN" (the 2022
    rules change). Its Reaction also plays it from the DISCARD PILE, off-turn,
    and ships the reveal (ambiguity **A9**)."""
    g = fresh(["Village Green"] + WAY_KINGDOM, ["base", "menagerie"])
    give_hand(g, A, ["Militia"])
    give_deck(g, A, ["Copper"] * 10)
    give_hand(g, B, ["Village Green", "Copper", "Copper", "Copper", "Copper"])
    give_deck(g, B, ["Gold"] * 10)
    play(g, A, "Militia")
    cards_(g, B, ["Village Green", "Copper"])
    assert frame(g)["card"] == "Village Green" and frame(g)["pid"] == B
    pick(g, B, "play")
    assert events(g, "reveal")[-1]["cards"] == ["Village Green"], "A9: the reveal"
    pick(g, B, "now")
    assert g["seats"][B]["in_play"] == ["Village Green"]
    assert sorted(g["seats"][B]["hand"]) == ["Copper", "Copper", "Copper", "Gold"], \
        "drew back up to 4 and was not asked to discard again"


def test_gatekeeper_cannot_exile_a_card_watchtower_moved():
    """PROSPERITY x MENAGERIE. Ch. VII Gatekeeper: "Gatekeeper Exiles the card
    BEFORE Continue, Hill Fort, Invasion, Reap, Replace, Spell Scroll or Summon
    can move it", but "if you CHOOSE to move the gained card with another
    ability, your opponent's Gatekeeper can't Exile it" — the lose-track rule
    and nothing else. Both branches, because a Gatekeeper that had simply
    stopped firing would pass the first one alone."""
    def gained_with(react):
        g = fresh(["Gatekeeper", "Watchtower"] + WAY_KINGDOM[:8],
                  ["base", "prosperity", "menagerie"])
        give_hand(g, B, ["Gatekeeper"])
        give_deck(g, B, ["Copper"] * 10)
        give_deck(g, A, ["Copper"] * 10)
        pass_turn_to(g, B)
        play(g, B, "Gatekeeper")
        pass_turn_to(g, A)
        give_hand(g, A, ["Watchtower"])
        engine.gain(g, A, "Silver")
        engine._drive(g)
        pick(g, A, react)
        return g

    g = gained_with("play")
    pick(g, A, "topdeck")
    assert g["seats"][A]["deck"][0] == "Silver"
    assert g["seats"][A]["exile"] == [], "moved first: Gatekeeper loses track"
    assert events(g, "lost_track")[-1]["card"] == "Silver"

    g = gained_with("decline")
    assert g["seats"][A]["exile"] == ["Silver"], "declined: Gatekeeper Exiles it"


# =============================================================================
# THE NEW WHEN-GAIN / COST MACHINERY x THE OLD SETS
# =============================================================================

def test_cavalry_ends_a_buy_phase_for_treasury_and_reopens_it_for_arena():
    """Ch. VII Cavalry states the consequences of `return_to_action_phase` for
    two shipped sets at once: "your Buy phase ends. This means end-of-Buy phase
    abilities (Exploration, Pageant, Wine Merchant; and current versions of
    Hermit, Merchant Guild and Treasury) can trigger several times in a turn"
    (SEASIDE's Treasury) and "start-of-Buy-phase abilities (such as Arena,
    Treasure Chest) trigger again" (EMPIRES' Arena)."""
    g = fresh(["Cavalry", "Treasury"] + WAY_KINGDOM[:8],
              ["base", "seaside", "menagerie"])
    give_hand(g, A, ["Treasury"])
    give_deck(g, A, ["Copper"] * 10)
    play(g, A, "Treasury")
    g["coins"], g["buys"] = 20, 5
    buy(g, A, "Cavalry")
    assert frame(g)["card"] == "Treasury" and frame(g)["stage"] == "topdeck", \
        "Cavalry's return ENDED the buy phase, so Treasury triggered"
    cards_(g, A, [])
    # the return really happened — a hand of Coppers then auto-advances again,
    # which is `_maybe_auto_buy` doing its job, so read the log not the phase
    assert [e for e in events(g, "phase") if e["phase"] == "action"]

    g = fresh(["Cavalry"] + WAY_KINGDOM, ["base", "empires", "menagerie"],
              landscapes=["Arena"])
    give_hand(g, A, ["Village", "Smithy"])
    give_deck(g, A, ["Copper"] * 10)
    mv(g, A, {"type": "end_phase"})
    assert frame(g)["card"] == "Arena"
    cards_(g, A, [])
    g["coins"], g["buys"] = 20, 5
    buy(g, A, "Cavalry")
    assert g["phase"] == "action"
    mv(g, A, {"type": "end_phase"})
    assert frame(g)["card"] == "Arena", "a second Buy phase is a second Arena"


def test_snowy_village_swallows_villagers_and_not_a_pile_token():
    """RENAISSANCE x MENAGERIE, and ADVENTURES x MENAGERIE, on one flag.
    Ch. VII Snowy Village 3: "After having played Snowy Village, spending
    Villager tokens will not give you +Actions" (they route through
    `add_actions`, which is why ph. 9's Villagers obey it for free). Ch. VII
    Snowy Village 1: "ONLY +Actions you would get AFTER playing Snowy Village
    are ignored" — an Adventures +1 Action pile token resolves BEFORE the play,
    so that one is kept."""
    g = fresh(["Snowy Village", "Lackeys"] + WAY_KINGDOM[:8],
              ["base", "renaissance", "menagerie"])
    g["villagers"][A] = 3
    give_hand(g, A, ["Snowy Village", "Village"])
    give_deck(g, A, ["Copper"] * 10)
    play(g, A, "Snowy Village")
    assert g["actions"] == 4
    ok, err = mv(g, A, {"type": "spend", "what": "villagers", "n": 2})
    assert ok, err
    assert g["villagers"][A] == 1 and g["actions"] == 4, "spent, and ignored"
    assert events(g, "actions_ignored")[-1]["count"] == 2
    play(g, A, "Village")
    assert g["actions"] == 3, "Village's +2 Actions ignored too (one spent)"

    g = fresh(["Snowy Village"] + WAY_KINGDOM, ["base", "adventures", "menagerie"],
              landscapes=["Pathfinding"])
    engine.move_token(g, A, "+action", "Snowy Village")
    give_hand(g, A, ["Snowy Village"])
    give_deck(g, A, ["Copper"] * 10)
    play(g, A, "Snowy Village")
    assert g["actions"] == 5, "the pile token's +1 Action resolved BEFORE it"


def test_wayfarers_cost_override_ignores_every_shipped_discount():
    """Ch. VII Wayfarer 5: "COST REDUCTION only affects Wayfarer's default cost
    of $6. If Wayfarer is copying the cost of another card, only cost reduction
    on THAT card applies (which Wayfarer would copy), not cost reduction on
    Wayfarer itself." Bridge (INTRIGUE) and the Canal project (RENAISSANCE) are
    both live, and rule 7 ("Wayfarer can have a cost with Potion or Debt in
    it") is read off ALCHEMY's Familiar and EMPIRES' Engineer."""
    g = fresh(["Wayfarer", "Bridge", "Village", "Smithy", "Market",
               "Laboratory", "Moat", "Cellar", "Militia", "Improve"],
              ["base", "intrigue", "renaissance", "menagerie"],
              landscapes=["Canal"])
    give_cube(g, "Canal", A)
    assert engine.cost(g, "Wayfarer") == 5, "$6 default, Canal applies"
    g["turn_ctx"]["bridges"] = 2
    assert engine.cost(g, "Wayfarer") == 3
    engine.gain(g, A, "Gold")
    engine._drive(g)
    assert engine.cost(g, "Gold") == 3
    assert engine.cost(g, "Wayfarer") == 3, "copies Gold's CURRENT cost, once"

    g = fresh(["Wayfarer", "Familiar", "Engineer", "Village", "Smithy",
               "Market", "Laboratory", "Moat", "Cellar", "Militia"],
              ["base", "alchemy", "empires", "menagerie"])
    engine.gain(g, A, "Familiar")
    engine._drive(g)
    assert (engine.cost(g, "Wayfarer"), engine.potion_cost(g, "Wayfarer"),
            engine.debt_cost(g, "Wayfarer")) == (3, 1, 0)
    engine.gain(g, A, "Engineer")
    engine._drive(g)
    assert (engine.cost(g, "Wayfarer"), engine.potion_cost(g, "Wayfarer"),
            engine.debt_cost(g, "Wayfarer")) == (0, 0, 4)


def test_wayfarer_copies_any_players_gain_but_destrier_counts_only_yours():
    """Ch. VII Wayfarer 1: "after ANY PLAYER gains a card (other than Wayfarer)
    on a given turn, Wayfarer gets the same cost". Ch. VII Destrier: "ONLY
    cards gained by the current player affect its cost" — `_turn_gains`, the
    list ph. 2 added for Smugglers. Two trackers, asserted apart."""
    g = fresh(["Wayfarer", "Destrier"] + WAY_KINGDOM[:8], ["base", "menagerie"])
    engine.gain(g, B, "Copper")
    engine._drive(g)
    assert engine.cost(g, "Wayfarer") == 0, "an opponent's gain still counts"
    assert engine.cost(g, "Destrier") == 6, "...but not for Destrier"
    engine.gain(g, A, "Copper")
    engine._drive(g)
    assert engine.cost(g, "Destrier") == 5


def test_falconer_sees_a_card_capitalism_gave_a_second_type():
    """RENAISSANCE x MENAGERIE. Falconer reacts to "a card with 2 or more types
    (Action, Attack, etc.)", read through `types_of` — and Capitalism injects
    `treasure` into every Action whose text prints "+$" during the cube
    owner's turn, so a plain Festival becomes a two-type card."""
    g = fresh(["Falconer", "Festival", "Village", "Smithy", "Market",
               "Laboratory", "Moat", "Cellar", "Militia", "Improve"],
              ["base", "renaissance", "menagerie"], landscapes=["Capitalism"])
    give_hand(g, A, ["Falconer"])
    assert engine.types_of(g, "Festival") == ["action"]
    engine.gain(g, A, "Festival")
    engine._drive(g)
    assert not g["pending"], "one type: no Falconer window"

    g = fresh(["Falconer", "Festival", "Village", "Smithy", "Market",
               "Laboratory", "Moat", "Cellar", "Militia", "Improve"],
              ["base", "renaissance", "menagerie"], landscapes=["Capitalism"])
    give_cube(g, "Capitalism", A)
    give_hand(g, A, ["Falconer"])
    assert engine.types_of(g, "Festival") == ["action", "treasure"]
    engine.gain(g, A, "Festival")
    engine._drive(g)
    assert frame(g)["card"] == "Falconer", "two types: the window opens"


# =============================================================================
# THE EXTRA-TURN PIPELINE
# =============================================================================

def test_seize_the_day_is_the_exception_that_gives_three_turns_in_a_row():
    """Ch. VII Seize the Day is the documented EXCEPTION to the 2023
    no-third-turn rule: "if you trigger Seize the Day and (for instance)
    Outpost on the same turn, you will get BOTH extra turns as long as you
    take the Seize the Day turn LAST. This would give you three turns in a
    row."

    A stated exception, not an ambiguity — so it is honoured rather than
    ledgered. `_seize` is the one extra-turn slot that is NOT popped when it
    is set: it survives until a turn end with no other extra turn to grant,
    which IS "taken last". No ordering prompt is needed because taking it
    first would strand the Outpost turn (a third in a row, denied), so the
    order that gives you both is the only one a player would choose."""
    g = fresh(["Outpost"] + WAY_KINGDOM, ["base", "seaside", "menagerie"],
              landscapes=["Seize the Day"])
    give_hand(g, A, ["Outpost"])
    give_deck(g, A, ["Copper"] * 40)
    play(g, A, "Outpost")
    g["coins"], g["buys"] = 20, 5
    ok, err = mv(g, A, {"type": "buy_landscape", "name": "Seize the Day"})
    assert ok, err
    assert g["_outpost"] == A and g["_seize"] == A
    end_turn(g, A)
    assert len(g["seats"][A]["hand"]) == 3, "the Outpost turn comes FIRST"
    end_turn(g, A)
    drain(g)
    starts = [(e["pid"], e.get("extra")) for e in events(g, "turn_start")]
    assert starts == [(A, None), (A, True), (A, True)], "three turns in a row"
    assert g["turn"] == A, "...and the third one is the Seize the Day turn"
    assert len(g["seats"][A]["hand"]) == 5, "...a NORMAL turn, not an Outpost one"
    # ...and it stops there: once per game, so there is no fourth
    end_turn(g, A)
    drain(g)
    assert g["turn"] == B
    assert "_seize" not in g


def test_seize_the_day_alone_is_an_ordinary_extra_turn():
    """The control. Without a second source there is nothing to take it after,
    so it is simply "take an extra turn after this one" — and a bot or a save
    must not see the exemption fire twice."""
    g = fresh(WAY_KINGDOM, ["base", "menagerie"], landscapes=["Seize the Day"])
    give_deck(g, A, ["Copper"] * 40)
    g["phase"] = "buy"
    g["coins"], g["buys"] = 20, 5
    ok, err = mv(g, A, {"type": "buy_landscape", "name": "Seize the Day"})
    assert ok, err
    end_turn(g, A)
    drain(g)
    assert g["turn"] == A and g["extra_turn"] is True
    end_turn(g, A)
    drain(g)
    assert g["turn"] == B, "no third turn from Seize the Day alone"


# =============================================================================
# THE BEFORE-PLAY WINDOW
# =============================================================================

def test_kiln_gains_its_copy_before_the_played_card_can_watch_the_gain():
    """Ch. VII Kiln: "if after Kiln you play a Livery, you gain a copy BEFORE
    resolving the Livery, so the when-gain ability is not active yet: you don't
    gain a Horse." The same sentence lists shipped Bauble, Cargo Ship, Sailor
    and Tiara, so this pins the WINDOW, not the card."""
    g = fresh(["Kiln", "Livery"] + WAY_KINGDOM[:8], ["base", "menagerie"])
    give_hand(g, A, ["Kiln", "Livery"])
    give_deck(g, A, ["Copper"] * 10)
    g["actions"] = 5
    play(g, A, "Kiln")
    play(g, A, "Livery")
    assert frame(g)["card"] == "Kiln" and frame(g)["stage"] == "do"
    before = engine.pile_count(g, "Horse")
    pick(g, A, "yes")
    assert g["seats"][A]["discard"] == ["Livery"], "the copy was gained"
    assert engine.pile_count(g, "Horse") == before, "...and no Horse for it"


# ══ B9 PAID — the 2025 Duration rule, and the conservation bug behind it ═════
#
# Way of the Horse / Butterfly / Turtle "return this to its pile", and ch. VII's
# REMOVED FROM PLAY names exactly those three among the six things in the game
# that can remove a Duration. A single Way'd play registers nothing (the Way
# REPLACES the ability), so the reachable case needs a throne-room: play the
# Duration NORMALLY first so its fx are registered, then use the Way on a LATER
# play, which physically takes the card off the table.
#
# This was not only a rules divergence. The returned card kept a live duration
# entry, and a promoted entry IS the card's accounting — so the census counted
# the Caravan in its pile AND on the table: 12 Caravans on an 11-card pile.

MENAG_DUR_K = ["Caravan", "Throne Room", "Village", "Smithy", "Moat",
               "Militia", "Market", "Cellar", "Festival", "Laboratory"]


def _throne_a_caravan(way_on_nth):
    """Throne Room a Caravan; take Way of the Horse on the Nth Way offer.
    Offer 1 is the Throne Room's own play, 2 and 3 are the Caravan's two."""
    g = fresh(MENAG_DUR_K, ("base", "seaside", "menagerie"),
              landscapes=["Way of the Horse"])
    g["seats"][A]["hand"] = ["Throne Room", "Caravan"]
    g["seats"][A]["deck"] = ["Gold"] * 12
    before = _census_of(g)
    ok, err = mv(g, A, {"type": "play_action", "card": "Throne Room"})
    assert ok, err
    offers = 0
    for _ in range(25):
        f = frame(g)
        if not f:
            break
        c = f["constraint"]
        if f["kind"] == "choose_option" and f.get("stage") == "__way_offer":
            offers += 1
            pick(g, f["pid"], "way" if offers == way_on_nth else "normal")
        elif f["kind"] == "choose_cards":
            cards_(g, f["pid"], ["Caravan"][:c.get("max", 1)])
        elif f["kind"] == "choose_option":
            pick(g, f["pid"], c["options"][0]["id"])
        else:
            break
    assert offers == 3, f"expected 3 Way offers, saw {offers}"
    engine._end_turn(g, A)
    engine._drive(g)
    return g, before


def _census_of(game):
    from games.dontminion.tests.test_soak import _census
    return _census(game)


def test_a_wayed_duration_stops_and_is_not_counted_twice():
    g, before = _throne_a_caravan(3)          # Way on the SECOND Caravan play
    assert _census_of(g) == before, "the returned Caravan was counted twice"
    assert engine.pile_count(g, "Caravan") == 11
    assert not any(e["card"] == "Caravan" for e in g["seats"][A]["duration"])
    # ...and it is never SILENT: a Duration that simply stops paying is
    # indistinguishable from a broken trigger.
    assert [e for e in g["log"] if e.get("event") == "duration_stopped"]
    # the rider discards normally — Way of the Butterfly 5: "only the Throne
    # Room will be left in play … and will be discarded in Clean-up this turn"
    assert "Throne Room" in g["seats"][A]["discard"]
    mv(g, B, {"type": "end_phase"}); mv(g, B, {"type": "end_phase"})
    engine._drive(g)
    assert len(g["seats"][A]["hand"]) == 5, "the returned Caravan still drew"


def test_a_duration_left_alone_still_persists_and_pays():
    """The control. Without it, a change that stopped EVERY Duration would
    pass the test above."""
    g, before = _throne_a_caravan(99)         # never take the Way
    assert _census_of(g) == before
    assert engine.pile_count(g, "Caravan") == 10
    assert any(e["card"] == "Caravan" for e in g["seats"][A]["duration"])
    assert not [e for e in g["log"] if e.get("event") == "duration_stopped"]
    mv(g, B, {"type": "end_phase"}); mv(g, B, {"type": "end_phase"})
    engine._drive(g)
    assert len(g["seats"][A]["hand"]) == 7, "the throne-roomed Caravan drew twice"
