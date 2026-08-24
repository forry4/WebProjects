"""Menagerie, half B — the 11 mechanically complex cards and all 20 WAYS.

Headline rulings pinned here (each one cost a design decision):

  * **A Way replaces the play ability, and the card is still PLAYED** — in
    play, `actions_played` bumped, after-play abilities still firing — and the
    offer is a two-option prompt on EVERY Action play, never a move.
  * **"This" on a Way is THE PLAYED ACTION CARD, not the Way** (Butterfly,
    Chameleon, Frog, Horse, Rat, Turtle).
  * **Way of the Chameleon is the one Way that does NOT cancel the play** — the
    card's own ability still runs, with every printed +Cards swapped for +$.
    And Way of the Owl's "draw until you have 6" is NOT a printed plus, so the
    Chameleon must not touch it.
  * **A Duration played using a Way sets nothing up**, so it is discarded in
    Clean-up — the counter-test to Chameleon, where it does stay.
  * **VILLAGE GREEN SHIPS THE REVEAL** (ambiguity **A9** — the compendium
    contradicts itself; chart + ch. VIII win over ch. VII 10's "reverted").
  * **Black Cat deals its Curses starting with the CURRENT player**, which is
    not the order `opponents()` gives in a 3-4 player game.
  * **Cardinal's Exile choice belongs to the ATTACKED player**, and only when
    both revealed cards are in range.
  * **Coven's fallback discards their EXILED Curses** (a real discard, so
    when-discard abilities fire) and the +1 Action/+$2 happen either way.
  * **Gatekeeper Exiles only what an opponent gains and has no Exiled copy
    of**, and loses track of a card that moved.
  * **Mastermind's three plays are ONE ability** — nothing else start-of-turn
    interleaves — and it rides the Duration it played, exactly once.
  * **A Sleigh gained to your hand may react with itself, and then stays in the
    discard pile** (the lose-track rule).
"""

from games.dontminion import cards, effects, engine

A, B, C, D = "alice", "bob", "carol", "dave"

# the half-B kingdom (every card here is registered by this half)
KB = ["Black Cat", "Sleigh", "Sheepdog", "Falconer", "Village Green", "Barge",
      "Coven", "Cardinal", "Gatekeeper", "Mastermind"]
# ...and the same board with Stockpile in it (Sleigh drops out, so this board
# has no Horse pile — which is itself worth having on the table once)
KS = ["Stockpile", "Black Cat", "Sheepdog", "Falconer", "Village Green",
      "Barge", "Coven", "Cardinal", "Gatekeeper", "Mastermind"]
# the WAYS board: base cards to play the Ways AT, plus two of this half's.
# Village is deliberately NOT here — it is the Way of the Mouse card.
KW = ["Smithy", "Market", "Laboratory", "Moat", "Throne Room", "Barge",
      "Sheepdog", "Cellar", "Militia", "Festival"]


def fresh(players=(A, B), seed=11, kingdom=tuple(KB), landscapes=(),
          expansions=("menagerie",)):
    """A board with NO landscapes by default. That matters more here than
    anywhere else: a dealt Way makes every Action play stop for a prompt, so a
    test that did not ask for one must not get one."""
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom), landscapes=list(landscapes))


def way_game(way, players=(A, B), seed=11, kingdom=tuple(KW), extra=()):
    return engine.new_game(list(players), ["base", "menagerie"], seed=seed,
                           kingdom=list(kingdom),
                           landscapes=[way, *extra])


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def decide(g, pid, **payload):
    ok, err = engine.apply_move(g, pid, {"type": "decision", **payload})
    assert ok, err
    return ok


def frame(g):
    return g["pending"][-1] if g["pending"] else None


def opt_ids(g):
    return [o["id"] for o in frame(g)["constraint"]["options"]]


def opt_labels(g):
    return [o["label"] for o in frame(g)["constraint"]["options"]]


def pick(g, pid, option_id):
    """Answer the open choose_option BY ID, never by index."""
    fr = frame(g)
    assert fr is not None and fr["kind"] == "choose_option", fr
    ids = [o["id"] for o in fr["constraint"]["options"]]
    assert option_id in ids, ids
    return decide(g, pid, ids=[option_id])


def give_hand(g, pid, cards_):
    g["seats"][pid]["hand"] = list(cards_)


def give_deck(g, pid, cards_):
    g["seats"][pid]["deck"] = list(cards_)


def events(g, name):
    return [e for e in g["log"] if e.get("event") == name]


def play(g, pid, card):
    ok, err = mv(g, pid, {"type": "play_action", "card": card})
    assert ok, err


def gain(g, pid, pile, **kw):
    out = engine.gain(g, pid, pile, **kw)
    engine._drive(g)
    return out


def to_buy(g, pid):
    if g["phase"] == "action":
        ok, err = mv(g, pid, {"type": "end_phase"})
        assert ok, err


def end_turn(g, pid):
    to_buy(g, pid)
    if g["over"] or g["pending"]:
        return
    ok, err = mv(g, pid, {"type": "end_phase"})
    assert ok, err


def play_with_way(g, pid, card, way, use=True):
    """Play an Action and answer the Way's two-option offer BY ID. The ids and
    their order are part of the contract (`push_way_offer`), so they are
    asserted rather than assumed."""
    play(g, pid, card)
    fr = frame(g)
    assert fr is not None and fr["kind"] == "choose_option", fr
    assert fr["card"] == way, fr["card"]
    assert [o["id"] for o in fr["constraint"]["options"]] == ["normal", "way"]
    assert fr["constraint"]["options"][1]["label"] == f"Play {card} using {way}"
    pick(g, pid, "way" if use else "normal")
    engine._drive(g)


# ══ BLACK CAT ════════════════════════════════════════════════════════════════

def test_black_cat_on_your_own_turn_draws_two_and_curses_nobody():
    """"If it ISN'T your turn, each other player gains a Curse" — so on your
    own turn it is a $2 Smithy-for-two and nothing else."""
    g = fresh()
    give_hand(g, A, ["Black Cat"])
    give_deck(g, A, ["Copper", "Estate", "Gold"])
    curses = g["supply"]["Curse"]
    play(g, A, "Black Cat")
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Estate"]
    assert g["supply"]["Curse"] == curses
    assert not g["pending"]


def test_black_cat_reacts_to_another_players_victory_gain_and_curses():
    g = fresh()
    give_hand(g, B, ["Black Cat"])
    give_deck(g, B, ["Copper", "Copper"])
    give_hand(g, A, [])
    curses = g["supply"]["Curse"]
    gain(g, A, "Estate")
    fr = frame(g)
    assert fr is not None and fr["card"] == "Black Cat" and fr["pid"] == B
    assert opt_ids(g) == ["play", "decline"]
    assert opt_labels(g)[0] == "Play Black Cat from your hand"
    pick(g, B, "play")
    engine._drive(g)
    assert g["seats"][B]["in_play"] == ["Black Cat"]
    assert sorted(g["seats"][B]["hand"]) == ["Copper", "Copper"]
    assert g["supply"]["Curse"] == curses - 1
    assert "Curse" in g["seats"][A]["discard"]
    # an off-turn reaction must not bump the TURN player's counter
    assert g["turn_ctx"]["actions_played"] == 0


def test_black_cat_may_decline_and_keeps_the_card():
    g = fresh()
    give_hand(g, B, ["Black Cat"])
    curses = g["supply"]["Curse"]
    gain(g, A, "Estate")
    pick(g, B, "decline")
    engine._drive(g)
    assert g["seats"][B]["hand"] == ["Black Cat"]
    assert g["supply"]["Curse"] == curses


def test_black_cat_does_not_react_to_a_non_victory_gain():
    g = fresh()
    give_hand(g, B, ["Black Cat"])
    gain(g, A, "Silver")
    assert not g["pending"]


def test_black_cat_does_not_react_to_your_own_gain():
    """"When ANOTHER player gains a Victory card" — the gainer's own Black Cat
    stays in hand."""
    g = fresh()
    give_hand(g, A, ["Black Cat"])
    gain(g, A, "Estate")
    assert not g["pending"]
    assert g["seats"][A]["hand"] == ["Black Cat"]


def test_black_cat_deals_the_curses_starting_with_the_current_player():
    """"If you play this when it's not your turn, deal out the Curses STARTING
    WITH THE CURRENT PLAYER." With four seats and the Black Cat two seats
    behind, the ordinary opponents() order would start with the wrong player —
    so with one Curse left, it must be the CURRENT player who gets it."""
    g = fresh(players=(A, B, C, D))
    assert g["turn"] == A
    give_hand(g, C, ["Black Cat"])
    give_deck(g, C, ["Copper", "Copper"])
    g["supply"]["Curse"] = 1
    gain(g, A, "Estate")
    pick(g, C, "play")
    engine._drive(g)
    assert "Curse" in g["seats"][A]["discard"], "the current player is first"
    assert "Curse" not in g["seats"][D]["discard"]
    assert "Curse" not in g["seats"][B]["discard"]
    assert g["supply"]["Curse"] == 0


def test_a_black_cat_played_off_turn_is_discarded_in_that_turns_cleanup():
    g = fresh()
    give_hand(g, B, ["Black Cat"])
    give_deck(g, B, ["Copper", "Copper"])
    gain(g, A, "Estate")
    pick(g, B, "play")
    engine._drive(g)
    end_turn(g, A)
    assert g["seats"][B]["in_play"] == []
    assert "Black Cat" in g["seats"][B]["discard"]


# ══ SLEIGH ═══════════════════════════════════════════════════════════════════

def test_sleigh_gains_two_horses_from_the_non_supply_pile():
    g = fresh()
    give_hand(g, A, ["Sleigh"])
    assert engine.pile_count(g, "Horse") == cards.HORSE_PILE
    play(g, A, "Sleigh")
    engine._drive(g)
    assert g["seats"][A]["discard"].count("Horse") == 2
    assert engine.pile_count(g, "Horse") == cards.HORSE_PILE - 2
    assert "Horse" not in g["supply"], "Horses are outside the Supply"


def test_sleigh_discards_itself_to_put_the_gained_card_into_your_hand():
    g = fresh()
    give_hand(g, A, ["Sleigh"])
    gain(g, A, "Gold")
    fr = frame(g)
    assert fr["card"] == "Sleigh" and opt_ids(g) == ["play", "decline"]
    assert opt_labels(g)[0] == "Discard Sleigh from your hand"
    pick(g, A, "play")
    engine._drive(g)
    assert opt_ids(g) == ["hand", "deck"]
    pick(g, A, "hand")
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Gold"]
    assert g["seats"][A]["discard"] == ["Sleigh"]


def test_sleigh_can_put_the_gained_card_onto_your_deck_instead():
    g = fresh()
    give_hand(g, A, ["Sleigh"])
    give_deck(g, A, ["Copper"])
    gain(g, A, "Gold")
    pick(g, A, "play")
    engine._drive(g)
    pick(g, A, "deck")
    engine._drive(g)
    assert g["seats"][A]["deck"][0] == "Gold"
    assert "Gold" not in g["seats"][A]["discard"]


def test_a_sleigh_gained_to_your_hand_reacts_but_stays_in_the_discard_pile():
    """"If you gain a Sleigh to your hand, you may react with that same Sleigh.
    HOWEVER, the Sleigh would stay in your discard pile due to the 'lose track'
    rule." — and the skip is never silent."""
    g = fresh()
    give_hand(g, A, [])
    gain(g, A, "Sleigh", dest="hand")
    assert frame(g)["card"] == "Sleigh"
    pick(g, A, "play")
    engine._drive(g)
    assert g["seats"][A]["hand"] == []
    assert g["seats"][A]["discard"] == ["Sleigh"]
    assert not g["pending"], "no hand-or-deck choice: the card was lost track of"
    assert events(g, "lost_track")[-1]["card"] == "Sleigh"


def test_sleigh_only_reacts_to_your_own_gains():
    g = fresh()
    give_hand(g, B, ["Sleigh"])
    gain(g, A, "Gold")
    assert not g["pending"]


# ══ SHEEPDOG ═════════════════════════════════════════════════════════════════

def test_sheepdog_plays_itself_on_a_gain_and_draws_two():
    g = fresh()
    give_hand(g, A, ["Sheepdog"])
    give_deck(g, A, ["Gold", "Silver", "Copper"])
    gain(g, A, "Estate")
    pick(g, A, "play")
    engine._drive(g)
    assert sorted(g["seats"][A]["hand"]) == ["Gold", "Silver"]
    assert g["seats"][A]["in_play"] == ["Sheepdog"]
    assert g["turn_ctx"]["actions_played"] == 1
    assert g["actions"] == 1, "a reaction that plays itself spends no Action"


def test_sheepdog_reacting_off_turn_does_not_touch_the_turn_players_counter():
    """"When YOU gain a card" (`who:"actor"`), so the off-turn case is a card
    gained BY the Sheepdog's owner on someone else's turn — a Curse from a
    Witch, or a Silver from a Swindler-class attack."""
    g = fresh()
    give_hand(g, B, ["Sheepdog"])
    give_deck(g, B, ["Gold", "Silver"])
    assert g["turn"] == A
    gain(g, B, "Curse")
    pick(g, B, "play")
    engine._drive(g)
    assert sorted(g["seats"][B]["hand"]) == ["Gold", "Silver"]
    assert g["turn_ctx"]["actions_played"] == 0


def test_sheepdog_does_not_react_to_someone_elses_gain():
    g = fresh()
    give_hand(g, B, ["Sheepdog"])
    gain(g, A, "Estate")
    assert not g["pending"]


# ══ FALCONER ═════════════════════════════════════════════════════════════════

def test_falconer_gains_a_cheaper_card_to_your_hand():
    g = fresh()
    give_hand(g, A, ["Falconer"])
    play(g, A, "Falconer")
    piles = frame(g)["constraint"]["piles"]
    assert "Cardinal" in piles, "$4 < $5"
    assert "Barge" not in piles and "Falconer" not in piles, "$5 is not less than $5"
    decide(g, A, pile="Cardinal")
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Cardinal"], "GAINED TO YOUR HAND"


def test_falconer_reacts_to_any_players_gain_of_a_two_type_card():
    """"When ANY player gains a card with 2 or more types" — so the Falconer's
    owner reacts to an opponent's gain as well as their own."""
    g = fresh()
    give_hand(g, B, ["Falconer"])
    gain(g, A, "Sleigh")            # Action - Reaction: two types
    fr = frame(g)
    assert fr is not None and fr["card"] == "Falconer" and fr["pid"] == B
    pick(g, B, "play")
    engine._drive(g)
    assert g["seats"][B]["in_play"] == ["Falconer"]
    assert frame(g)["kind"] == "choose_pile" and frame(g)["pid"] == B


def test_falconer_does_not_react_to_a_one_type_card():
    g = fresh()
    give_hand(g, B, ["Falconer"])
    assert len(engine.types_of(g, "Estate")) == 1
    gain(g, A, "Estate")
    assert not g["pending"]


def test_falconer_reacts_to_your_own_gain_too():
    g = fresh()
    give_hand(g, A, ["Falconer"])
    gain(g, A, "Black Cat")         # Action - Attack - Reaction
    assert frame(g)["card"] == "Falconer" and frame(g)["pid"] == A


# ══ VILLAGE GREEN ════════════════════════════════════════════════════════════

def test_village_green_now_pays_at_once_and_does_not_stay_in_play():
    g = fresh()
    give_hand(g, A, ["Village Green"])
    give_deck(g, A, ["Gold"] + ["Copper"] * 12)
    play(g, A, "Village Green")
    assert opt_ids(g) == ["now", "next"]
    pick(g, A, "now")
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Gold"]
    assert g["actions"] == 2                      # 1 - 1 spent + 2
    end_turn(g, A)
    assert g["seats"][A]["duration"] == []
    assert "Village Green" in g["seats"][A]["discard"]


def test_village_green_next_turn_stays_in_play_and_pays_at_your_turn_start():
    g = fresh()
    give_hand(g, A, ["Village Green"])
    give_deck(g, A, ["Copper"] * 12)
    play(g, A, "Village Green")
    pick(g, A, "next")
    engine._drive(g)
    assert g["actions"] == 0 and len(g["seats"][A]["hand"]) == 0
    end_turn(g, A)
    assert [e["card"] for e in g["seats"][A]["duration"]] == ["Village Green"]
    end_turn(g, B)
    engine._drive(g)
    assert g["turn"] == A
    assert g["actions"] == 3                      # 1 + 2
    assert len(g["seats"][A]["hand"]) == 6         # 5 + 1


def test_village_green_reveals_itself_to_play_from_the_discard_pile():
    """AMBIGUITY **A9** — we ship the REVEAL. Two sources (the 2025-10 chart and
    ch. VIII's own timing model, "you may reveal This. If you do: Play This")
    against ch. VII 10's "reverted", so the majority and the more conservative
    reading win. The observable difference is exactly this `reveal` event."""
    g = fresh()
    give_hand(g, A, ["Village Green", "Copper"])
    give_deck(g, A, ["Gold", "Silver"])
    engine.discard(g, A, ["Village Green"])
    engine._drive(g)
    fr = frame(g)
    assert fr["card"] == "Village Green"
    assert opt_labels(g)[0] == "Reveal Village Green to play it"
    pick(g, A, "play")
    engine._drive(g)
    rev = [e for e in events(g, "reveal") if e.get("cards") == ["Village Green"]]
    assert rev, "the 2020 errata's reveal is what we ship (A9)"
    assert g["seats"][A]["in_play"] == ["Village Green"]
    assert opt_ids(g) == ["now", "next"], "and it is really PLAYED"


def test_village_green_may_decline_the_reaction():
    g = fresh()
    give_hand(g, A, ["Village Green"])
    engine.discard(g, A, ["Village Green"])
    engine._drive(g)
    pick(g, A, "decline")
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Village Green"]
    assert not events(g, "reveal")


def test_village_green_does_not_react_to_a_cleanup_discard():
    """"When you discard this OTHER THAN DURING CLEAN-UP" — Clean-up moves the
    hand to the discard pile directly and never calls discard(), so the
    exclusion needs no condition of its own."""
    g = fresh()
    give_hand(g, A, ["Village Green"])
    give_deck(g, A, ["Copper"] * 10)
    end_turn(g, A)
    assert not g["pending"]
    assert "Village Green" in g["seats"][A]["discard"]


def test_village_green_reacts_to_a_discard_from_the_exile_mat():
    """"When you discard cards from your Exile mat, when-discard abilities such
    as … Village Green … trigger" — the one direction of the Exile mat that IS
    part of the discard economy."""
    g = fresh()
    give_hand(g, A, [])
    g["seats"][A]["exile"] = ["Village Green"]
    engine.discard_from_exile(g, A, ["Village Green"])
    engine._drive(g)
    assert frame(g)["card"] == "Village Green"
    pick(g, A, "play")
    engine._drive(g)
    assert g["seats"][A]["in_play"] == ["Village Green"]


# ══ BARGE ════════════════════════════════════════════════════════════════════

def test_barge_now_draws_three_and_gives_a_buy():
    g = fresh()
    give_hand(g, A, ["Barge"])
    give_deck(g, A, ["Copper"] * 5)
    play(g, A, "Barge")
    assert opt_ids(g) == ["now", "next"]
    pick(g, A, "now")
    engine._drive(g)
    assert len(g["seats"][A]["hand"]) == 3 and g["buys"] == 2
    end_turn(g, A)
    assert g["seats"][A]["duration"] == []


def test_barge_next_turn_stays_in_play_and_pays_at_your_turn_start():
    g = fresh()
    give_hand(g, A, ["Barge"])
    give_deck(g, A, ["Copper"] * 15)
    play(g, A, "Barge")
    pick(g, A, "next")
    engine._drive(g)
    assert g["seats"][A]["hand"] == [] and g["buys"] == 1
    end_turn(g, A)
    assert [e["card"] for e in g["seats"][A]["duration"]] == ["Barge"]
    end_turn(g, B)
    engine._drive(g)
    assert len(g["seats"][A]["hand"]) == 8 and g["buys"] == 2


# ══ COVEN ════════════════════════════════════════════════════════════════════

def test_coven_makes_each_opponent_exile_a_curse_from_the_supply():
    g = fresh(players=(A, B, C))
    give_hand(g, A, ["Coven"])
    curses = g["supply"]["Curse"]
    play(g, A, "Coven")
    engine._drive(g)
    assert g["actions"] == 1 and g["coins"] == 2
    assert g["seats"][B]["exile"] == ["Curse"]
    assert g["seats"][C]["exile"] == ["Curse"]
    assert g["seats"][A]["exile"] == []
    assert g["supply"]["Curse"] == curses - 2
    assert not events(g, "gain"), "Exiling from the Supply is NOT gaining"


def test_coven_with_no_curses_left_discards_their_exiled_curses():
    """"See NOT OPTIONAL 'IF YOU DO'. If a player CAN'T Exile a Curse, they
    discard their Exiled Curses instead" — through discard(), so a when-discard
    ability fires. And "you get the initial +1 Action and +$2 even if there are
    no Curses left"."""
    g = fresh()
    give_hand(g, A, ["Coven"])
    g["supply"]["Curse"] = 0
    g["seats"][B]["exile"] = ["Curse", "Curse", "Estate"]
    play(g, A, "Coven")
    engine._drive(g)
    assert g["actions"] == 1 and g["coins"] == 2
    assert g["seats"][B]["exile"] == ["Estate"]
    assert g["seats"][B]["discard"].count("Curse") == 2


def test_coven_with_no_curses_and_an_empty_mat_does_nothing_to_them():
    g = fresh()
    give_hand(g, A, ["Coven"])
    g["supply"]["Curse"] = 0
    play(g, A, "Coven")
    engine._drive(g)
    assert g["seats"][B]["exile"] == [] and g["coins"] == 2


# ══ CARDINAL ═════════════════════════════════════════════════════════════════

def test_cardinal_exiles_the_only_eligible_card_and_discards_the_rest():
    g = fresh()
    give_hand(g, A, ["Cardinal"])
    give_deck(g, B, ["Silver", "Copper", "Estate"])
    play(g, A, "Cardinal")
    engine._drive(g)
    assert g["coins"] == 2
    assert g["seats"][B]["exile"] == ["Silver"], "$3 is in the $3-$6 range"
    assert g["seats"][B]["discard"] == ["Copper"]
    assert g["seats"][B]["aside"] == []
    assert not g["pending"], "one eligible card is not a choice"


def test_cardinal_lets_the_attacked_player_choose_between_two_eligible():
    """"The ATTACKED player chooses which card to Exile if both cards have the
    appropriate cost"."""
    g = fresh()
    give_hand(g, A, ["Cardinal"])
    give_deck(g, B, ["Silver", "Gatekeeper", "Estate"])
    play(g, A, "Cardinal")
    engine._drive(g)
    fr = frame(g)
    assert fr["kind"] == "choose_cards" and fr["pid"] == B
    assert sorted(fr["constraint"]["cards"]) == ["Gatekeeper", "Silver"]
    assert fr["constraint"]["min"] == fr["constraint"]["max"] == 1
    decide(g, B, cards=["Gatekeeper"])
    engine._drive(g)
    assert g["seats"][B]["exile"] == ["Gatekeeper"]
    assert g["seats"][B]["discard"] == ["Silver"]


def test_cardinal_exiles_nothing_when_neither_card_is_in_range():
    g = fresh()
    give_hand(g, A, ["Cardinal"])
    give_deck(g, B, ["Copper", "Estate", "Gold"])
    play(g, A, "Cardinal")
    engine._drive(g)
    assert g["seats"][B]["exile"] == []
    assert sorted(g["seats"][B]["discard"]) == ["Copper", "Estate"]
    assert g["seats"][B]["deck"] == ["Gold"]


def test_cardinal_with_an_empty_deck_does_nothing_to_that_player():
    g = fresh()
    give_hand(g, A, ["Cardinal"])
    give_deck(g, B, [])
    g["seats"][B]["discard"] = []
    play(g, A, "Cardinal")
    engine._drive(g)
    assert g["seats"][B]["exile"] == [] and g["coins"] == 2


# ══ GATEKEEPER ═══════════════════════════════════════════════════════════════

def test_gatekeeper_pays_three_at_your_next_turn_start_and_stays_in_play():
    g = fresh()
    give_hand(g, A, ["Gatekeeper"])
    give_deck(g, A, ["Copper"] * 12)
    play(g, A, "Gatekeeper")
    engine._drive(g)
    assert g["coins"] == 0
    end_turn(g, A)
    assert [e["card"] for e in g["seats"][A]["duration"]] == ["Gatekeeper"]
    end_turn(g, B)
    engine._drive(g)
    assert g["turn"] == A and g["coins"] == 3


def test_gatekeeper_exiles_an_opponents_action_or_treasure_gain():
    g = fresh()
    give_hand(g, A, ["Gatekeeper"])
    give_deck(g, A, ["Copper"] * 12)
    play(g, A, "Gatekeeper")
    engine._drive(g)
    end_turn(g, A)
    assert g["turn"] == B
    gain(g, B, "Silver")
    assert g["seats"][B]["exile"] == ["Silver"]
    assert "Silver" not in g["seats"][B]["discard"]
    # ...and a SECOND copy is left alone: "a card they don't have an Exiled
    # copy of"
    gain(g, B, "Silver")
    assert g["seats"][B]["exile"] == ["Silver"]
    assert g["seats"][B]["discard"] == ["Silver"]


def test_gatekeeper_ignores_a_victory_gain_and_your_own_gains():
    g = fresh()
    give_hand(g, A, ["Gatekeeper"])
    give_deck(g, A, ["Copper"] * 12)
    play(g, A, "Gatekeeper")
    engine._drive(g)
    gain(g, A, "Silver")             # the Gatekeeper's OWNER gains
    assert g["seats"][A]["exile"] == []
    end_turn(g, A)
    gain(g, B, "Estate")             # a Victory card is neither Action nor Treasure
    assert g["seats"][B]["exile"] == []


def test_gatekeeper_stops_at_your_next_turn():
    g = fresh()
    give_hand(g, A, ["Gatekeeper"])
    give_deck(g, A, ["Copper"] * 12)
    play(g, A, "Gatekeeper")
    engine._drive(g)
    end_turn(g, A)
    end_turn(g, B)
    engine._drive(g)
    assert g["turn"] == A
    end_turn(g, A)
    gain(g, B, "Silver")
    assert g["seats"][B]["exile"] == [], "the watcher expired at A's turn start"


def test_gatekeeper_loses_track_of_a_card_that_moved():
    """"If you choose to move the gained card with another ability, your
    opponent's Gatekeeper CAN'T Exile it" — and the skip is logged."""
    g = fresh()
    give_hand(g, A, ["Gatekeeper"])
    give_deck(g, A, ["Copper"] * 12)
    play(g, A, "Gatekeeper")
    engine._drive(g)
    end_turn(g, A)
    give_hand(g, B, ["Sleigh"])
    gain(g, B, "Silver")
    # B's own pool (the Sleigh window) parks ABOVE A's (the Gatekeeper), since
    # pools park in reversed turn order and B is the turn player — so the
    # Sleigh moves the Silver into hand first and the Gatekeeper misses it.
    assert frame(g)["card"] == "Sleigh"
    pick(g, B, "play")
    engine._drive(g)
    pick(g, B, "hand")
    engine._drive(g)
    assert g["seats"][B]["hand"].count("Silver") == 1
    assert g["seats"][B]["exile"] == []
    assert any(e["card"] == "Silver" for e in events(g, "lost_track"))


# ══ MASTERMIND ═══════════════════════════════════════════════════════════════

def _mastermind_to_next_turn(g, hand_next):
    """Play a Mastermind, then hand A the hand they will be HOLDING when their
    next turn starts — the start-of-turn ability reads it before any test could
    stage it afterwards."""
    give_hand(g, A, ["Mastermind"])
    give_deck(g, A, ["Copper"] * 20)
    play(g, A, "Mastermind")
    engine._drive(g)
    end_turn(g, A)
    give_hand(g, A, list(hand_next))
    end_turn(g, B)
    engine._drive(g)
    assert g["turn"] == A
    return g


def test_mastermind_plays_an_action_from_your_hand_three_times():
    g = fresh(kingdom=KB + [], expansions=("base", "menagerie"))
    g = _mastermind_to_next_turn(g, ["Barge"])
    # the start-of-turn ability re-offers the hand once the turn has begun
    engine._drive(g)
    fr = frame(g)
    assert fr["card"] == "Mastermind" and fr["kind"] == "choose_cards"
    assert fr["constraint"]["cards"] == ["Barge"]
    assert fr["constraint"]["min"] == 0 and fr["constraint"]["max"] == 1
    decide(g, A, cards=["Barge"])
    engine._drive(g)
    for _ in range(3):
        assert opt_ids(g) == ["now", "next"], "one Barge play at a time"
        pick(g, A, "now")
        engine._drive(g)
    assert g["buys"] == 4          # 1 + three Barges
    # the Barge registered nothing (three "now"s), so it does NOT stay in play
    # — and neither does the Mastermind riding it
    assert sorted(g["seats"][A]["in_play"]) == ["Barge", "Mastermind"]
    end_turn(g, A)
    assert g["seats"][A]["duration"] == []
    assert engine.owned_cards(g, A).count("Mastermind") == 1


def test_mastermind_may_decline_and_needs_an_action_in_hand():
    g = fresh()
    g = _mastermind_to_next_turn(g, ["Copper", "Copper"])
    engine._drive(g)
    assert not g["pending"], "no Action in hand: no prompt at all"
    g2 = fresh(seed=12)
    g2 = _mastermind_to_next_turn(g2, ["Barge"])
    engine._drive(g2)
    decide(g2, A, cards=[])
    engine._drive(g2)
    assert g2["seats"][A]["hand"] == ["Barge"]
    assert g2["buys"] == 1


def test_mastermind_stays_in_play_with_the_duration_it_played_exactly_once():
    """"If the card is a Duration, Mastermind stays in play as long as that
    Duration stays in play" — as a RIDER, and the physical card must be counted
    exactly once by `owned_cards` at every step (it is one card, not two)."""
    g = fresh()
    g = _mastermind_to_next_turn(g, ["Barge"])
    engine._drive(g)
    decide(g, A, cards=["Barge"])
    engine._drive(g)
    for _ in range(3):
        pick(g, A, "next")
        engine._drive(g)
    assert engine.owned_cards(g, A).count("Mastermind") == 1
    end_turn(g, A)
    entries = g["seats"][A]["duration"]
    assert [e["card"] for e in entries] == ["Barge"]
    assert entries[0]["riders"] == ["Mastermind"]
    assert "Mastermind" not in g["seats"][A]["discard"]
    assert engine.owned_cards(g, A).count("Mastermind") == 1
    end_turn(g, B)
    engine._drive(g)                       # A's turn: the three Barge fx fire
    assert engine.owned_cards(g, A).count("Mastermind") == 1
    end_turn(g, A)
    # both leave the table together, and the Mastermind is still exactly one
    # card (the Clean-up draw may have reshuffled it out of the discard pile)
    assert g["seats"][A]["duration"] == []
    assert "Mastermind" not in g["seats"][A]["in_play"]
    assert engine.owned_cards(g, A).count("Mastermind") == 1
    assert engine.owned_cards(g, A).count("Barge") == 1


def test_mastermind_does_not_stay_out_behind_a_non_duration():
    g = fresh(expansions=("base", "menagerie"), kingdom=KB[:9] + ["Smithy"])
    g = _mastermind_to_next_turn(g, ["Smithy"])
    engine._drive(g)
    decide(g, A, cards=["Smithy"])
    engine._drive(g)
    end_turn(g, A)
    assert g["seats"][A]["duration"] == []
    assert g["seats"][A]["discard"].count("Mastermind") == 1


def test_mastermind_is_one_ability_and_nothing_interleaves():
    """"Mastermind's start-of-turn ability is ONE ability, so you can't resolve
    any other start-of-turn abilities in between playing the Action card three
    times" — the ability pool's atomicity contract."""
    g = fresh()
    give_hand(g, A, ["Mastermind", "Barge"])
    give_deck(g, A, ["Copper"] * 25)
    g["actions"] = 2
    play(g, A, "Mastermind")
    engine._drive(g)
    play(g, A, "Barge")
    pick(g, A, "next")
    engine._drive(g)
    end_turn(g, A)
    give_hand(g, A, ["Village Green"])
    end_turn(g, B)
    engine._drive(g)
    # two concurrent start-of-turn abilities: Barge's delayed half and
    # Mastermind's. Pick Mastermind's.
    fr = frame(g)
    assert fr["card"] == "__abilities"
    labels = [o["label"] for o in fr["constraint"]["options"]]
    ids = [o["id"] for o in fr["constraint"]["options"]]
    mm = ids[[i for i, s in enumerate(labels) if "Mastermind" in s][0]]
    pick(g, A, mm)
    engine._drive(g)
    decide(g, A, cards=["Village Green"])
    engine._drive(g)
    buys_before = g["buys"]
    for i in range(3):
        assert opt_ids(g) == ["now", "next"], f"Village Green play {i + 1}"
        assert g["buys"] == buys_before, \
            "Barge's +1 Buy must not arrive between Mastermind's plays"
        pick(g, A, "now")
        engine._drive(g)
    assert g["buys"] == buys_before + 1, "...and only then"


# ══ STOCKPILE ════════════════════════════════════════════════════════════════

def test_stockpile_pays_three_gives_a_buy_and_exiles_itself():
    g = fresh(kingdom=KS)
    give_hand(g, A, ["Stockpile"])
    g["phase"] = "buy"
    ok, err = mv(g, A, {"type": "play_treasure", "card": "Stockpile"})
    assert ok, err
    engine._drive(g)
    assert g["coins"] == 3 and g["buys"] == 2
    assert g["seats"][A]["exile"] == ["Stockpile"]
    assert g["seats"][A]["in_play"] == [], "REMOVED FROM PLAY"
    assert not events(g, "gain"), "Exiling is not gaining"


def test_stockpile_is_never_fired_by_the_play_all_treasures_button():
    """Bucket 1 (`MANUAL_TREASURES`), deliberately: Stockpile removes ITSELF
    from play, which changes "cards you have in play" for everything that
    counts them — Stampede is in this very set — so playing it early is a real
    choice and the button must not make it."""
    assert "Stockpile" in effects.MANUAL_TREASURES
    assert "Stockpile" not in effects.AUTOPLAY_LAST
    g = fresh(kingdom=KS)
    give_hand(g, A, ["Stockpile", "Copper"])
    g["phase"] = "buy"
    assert engine.autoplay_treasures(g, A) == ["Copper"]
    ok, err = mv(g, A, {"type": "play_all_treasures"})
    assert ok, err
    engine._drive(g)
    assert g["coins"] == 1
    assert g["seats"][A]["hand"] == ["Stockpile"]


def test_a_replayed_stockpile_pays_again_and_loses_track_of_the_exile():
    """"If you use Coronet, Counterfeit, Crown, Specialist or Tiara to play
    Stockpile twice, you get +$3 and +1 Buy BOTH times" — the second play finds
    nothing in play to Exile, which is the lose-track rule and is logged."""
    g = fresh(kingdom=KS)
    give_hand(g, A, ["Stockpile"])
    g["phase"] = "buy"
    mv(g, A, {"type": "play_treasure", "card": "Stockpile"})
    engine._drive(g)
    engine.play_treasure_card(g, A, "Stockpile", from_zone=None)
    engine._drive(g)
    assert g["coins"] == 6 and g["buys"] == 3
    assert g["seats"][A]["exile"] == ["Stockpile"]
    assert events(g, "lost_track")[-1]["card"] == "Stockpile"


# ══ THE WAYS — the shared contract ═══════════════════════════════════════════

def test_a_way_replaces_the_played_cards_ability_but_it_is_still_played():
    """"You just resolve the Way instead" — and the card is in play, counted as
    an Action played, and its after-play abilities still fire."""
    g = way_game("Way of the Otter")
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Copper"] * 6)
    play_with_way(g, A, "Smithy", "Way of the Otter")
    assert len(g["seats"][A]["hand"]) == 2, "the Way's +2 Cards, not Smithy's +3"
    assert g["seats"][A]["in_play"] == ["Smithy"]
    assert g["turn_ctx"]["actions_played"] == 1
    e = events(g, "way")[-1]
    assert e["name"] == "Way of the Otter" and e["card"] == "Smithy"


def test_declining_a_way_runs_the_printed_ability():
    g = way_game("Way of the Otter")
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Copper"] * 6)
    play_with_way(g, A, "Smithy", "Way of the Otter", use=False)
    assert len(g["seats"][A]["hand"]) == 3
    assert not events(g, "way")


def test_a_way_is_never_offered_for_a_treasure_play():
    g = way_game("Way of the Otter")
    give_hand(g, A, ["Copper"])
    g["phase"] = "buy"
    ok, err = mv(g, A, {"type": "play_treasure", "card": "Copper"})
    assert ok, err
    assert not g["pending"] and g["coins"] == 1


def test_a_way_is_offered_off_turn_too():
    """"You can use a Way even when playing an Action card when it's not your
    turn" — a Sheepdog reacting to a card gained on an opponent's turn."""
    g = way_game("Way of the Sheep")
    give_hand(g, B, ["Sheepdog"])
    give_deck(g, B, ["Gold", "Silver"])
    assert g["turn"] == A
    gain(g, B, "Curse")
    pick(g, B, "play")            # play the Sheepdog
    engine._drive(g)
    fr = frame(g)
    assert fr["card"] == "Way of the Sheep" and fr["pid"] == B
    pick(g, B, "way")
    engine._drive(g)
    assert g["seats"][B]["hand"] == [], "the Way replaced the +2 Cards"
    assert g["coins"] == 0, "and $ earned off-turn evaporates by rule"
    assert events(g, "off_turn_bonus")


def test_a_duration_played_using_a_way_does_not_stay_in_play():
    """"A Duration played using a Way doesn't set anything up, so it's
    discarded in Clean-up" — free, because a cancelled play registers no fx and
    an entry that registers nothing "failed to set up"."""
    g = way_game("Way of the Sheep")
    give_hand(g, A, ["Barge"])
    give_deck(g, A, ["Copper"] * 10)
    play_with_way(g, A, "Barge", "Way of the Sheep")
    assert g["coins"] == 2
    assert not g["pending"], "no now/next prompt: Barge's ability never ran"
    end_turn(g, A)
    assert g["seats"][A]["duration"] == []
    assert "Barge" in g["seats"][A]["discard"]


def test_a_throne_roomed_action_is_offered_the_way_on_each_play():
    """"If you replay a card with a throne-room, you choose EACH TIME whether to
    use the Way or play it normally"."""
    g = way_game("Way of the Sheep")
    give_hand(g, A, ["Throne Room", "Smithy"])
    give_deck(g, A, ["Copper"] * 8)
    play(g, A, "Throne Room")
    fr = frame(g)
    assert fr["card"] == "Way of the Sheep"     # the Throne Room's own play
    pick(g, A, "normal")
    engine._drive(g)
    decide(g, A, cards=["Smithy"])
    engine._drive(g)
    assert frame(g)["card"] == "Way of the Sheep"
    pick(g, A, "way")                            # first Smithy play: the Way
    engine._drive(g)
    assert frame(g)["card"] == "Way of the Sheep"
    pick(g, A, "normal")                         # second: the printed ability
    engine._drive(g)
    assert g["coins"] == 2 and len(g["seats"][A]["hand"]) == 3


# ══ THE WAYS — one at a time ═════════════════════════════════════════════════

def test_way_of_the_butterfly_returns_the_played_card_and_gains_one_dollar_up():
    g = way_game("Way of the Butterfly")
    give_hand(g, A, ["Smithy"])
    before = engine.pile_count(g, "Smithy")
    play_with_way(g, A, "Smithy", "Way of the Butterfly")
    assert opt_ids(g) == ["yes", "no"]
    pick(g, A, "yes")
    engine._drive(g)
    assert engine.pile_count(g, "Smithy") == before + 1
    assert g["seats"][A]["in_play"] == []
    piles = frame(g)["constraint"]["piles"]
    assert set(piles) == {"Market", "Laboratory", "Festival", "Barge", "Duchy"}
    assert "Smithy" not in piles, "$4 is not exactly $1 more than $4"
    decide(g, A, pile="Market")
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Market"]


def test_way_of_the_butterfly_may_be_declined():
    g = way_game("Way of the Butterfly")
    give_hand(g, A, ["Smithy"])
    before = engine.pile_count(g, "Smithy")
    play_with_way(g, A, "Smithy", "Way of the Butterfly")
    pick(g, A, "no")
    engine._drive(g)
    assert engine.pile_count(g, "Smithy") == before
    assert g["seats"][A]["in_play"] == ["Smithy"]
    assert not g["pending"]


def test_way_of_the_camel_exiles_a_gold_from_the_supply():
    g = way_game("Way of the Camel")
    give_hand(g, A, ["Smithy"])
    golds = g["supply"]["Gold"]
    play_with_way(g, A, "Smithy", "Way of the Camel")
    assert g["seats"][A]["exile"] == ["Gold"]
    assert g["supply"]["Gold"] == golds - 1
    assert not events(g, "gain")


def test_way_of_the_chameleon_swaps_the_cards_own_plusses_without_cancelling():
    """Ch. VII 1/6: "you RESOLVE THE EFFECTS of the card you played, but all
    +Cards you get this turn are +$ instead" — the one Way that does not
    replace the play. Market prints both, so one play proves both directions."""
    g = way_game("Way of the Chameleon")
    give_hand(g, A, ["Market"])
    give_deck(g, A, ["Gold", "Silver"])
    play_with_way(g, A, "Market", "Way of the Chameleon")
    assert g["turn_ctx"]["chameleon"] is True
    assert g["coins"] == 1                      # the +1 Card, swapped
    assert g["seats"][A]["hand"] == ["Gold"]     # the +$1, swapped
    assert g["buys"] == 2 and g["actions"] == 1  # untouched by the Way
    assert events(g, "way")[-1]["name"] == "Way of the Chameleon"


def test_way_of_the_chameleon_is_sticky_for_the_rest_of_the_turn():
    """"Only +Cards and +$ you get THIS TURN are changed" — a turn flag, not a
    play flag, so the NEXT card played is swapped too and next turn is not."""
    g = way_game("Way of the Chameleon")
    give_hand(g, A, ["Market", "Smithy"])
    give_deck(g, A, ["Copper"] * 12)
    play_with_way(g, A, "Market", "Way of the Chameleon")
    play_with_way(g, A, "Smithy", "Way of the Chameleon", use=False)
    assert g["coins"] == 1 + 3, "Smithy's printed +3 Cards, swapped, unasked"
    end_turn(g, A)
    end_turn(g, B)
    assert g["turn"] == A and g["turn_ctx"]["chameleon"] is False


def test_declining_way_of_the_chameleon_leaves_the_card_alone():
    g = way_game("Way of the Chameleon")
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Copper"] * 5)
    play_with_way(g, A, "Smithy", "Way of the Chameleon", use=False)
    assert g["turn_ctx"]["chameleon"] is False
    assert len(g["seats"][A]["hand"]) == 3 and g["coins"] == 0


def test_way_of_the_chameleon_leaves_a_duration_in_play():
    """Ch. VII 9: "if the played card is a Duration, LEAVE IT IN PLAY as you
    normally would … if you play a Caravan using Way of the Mule, the Caravan
    doesn't stay in play, but if you play it using Way of the Chameleon, it
    does." The counter-test to the "a Way'd Duration is discarded" rule."""
    g = way_game("Way of the Chameleon")
    give_hand(g, A, ["Barge"])
    give_deck(g, A, ["Copper"] * 12)
    play_with_way(g, A, "Barge", "Way of the Chameleon")
    assert opt_ids(g) == ["now", "next"], "Barge's own ability really ran"
    pick(g, A, "next")
    engine._drive(g)
    end_turn(g, A)
    assert [e["card"] for e in g["seats"][A]["duration"]] == ["Barge"]


def test_way_of_the_frog_topdecks_the_played_card_at_cleanup():
    g = way_game("Way of the Frog")
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Copper"] * 12)
    play_with_way(g, A, "Smithy", "Way of the Frog")
    assert g["actions"] == 1                    # 1 - 1 spent + 1
    end_turn(g, A)
    assert "Smithy" not in g["seats"][A]["discard"]
    assert "Smithy" in g["seats"][A]["hand"], "topdecked, then drawn"


def test_without_way_of_the_frog_the_card_is_discarded_as_usual():
    g = way_game("Way of the Frog")
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Copper"] * 12)
    play_with_way(g, A, "Smithy", "Way of the Frog", use=False)
    end_turn(g, A)
    assert "Smithy" in g["seats"][A]["discard"]


def test_way_of_the_goat_trashes_a_card_from_your_hand():
    g = way_game("Way of the Goat")
    give_hand(g, A, ["Smithy", "Copper", "Estate"])
    play_with_way(g, A, "Smithy", "Way of the Goat")
    fr = frame(g)
    assert fr["kind"] == "choose_cards"
    assert fr["constraint"]["min"] == 1, "not optional"
    assert sorted(fr["constraint"]["cards"]) == ["Copper", "Estate"]
    decide(g, A, cards=["Estate"])
    engine._drive(g)
    assert g["trash"] == ["Estate"]


def test_way_of_the_goat_with_an_empty_hand_does_nothing():
    g = way_game("Way of the Goat")
    give_hand(g, A, ["Smithy"])
    play_with_way(g, A, "Smithy", "Way of the Goat")
    assert not g["pending"] and g["trash"] == []


def test_way_of_the_horse_pays_then_returns_the_played_card_to_its_pile():
    g = way_game("Way of the Horse")
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Copper"] * 4)
    before = engine.pile_count(g, "Smithy")
    play_with_way(g, A, "Smithy", "Way of the Horse")
    assert len(g["seats"][A]["hand"]) == 2 and g["actions"] == 1
    assert engine.pile_count(g, "Smithy") == before + 1
    assert g["seats"][A]["in_play"] == []


def test_way_of_the_horse_still_pays_when_the_card_cannot_be_returned():
    """"If you can't return it, the card STAYS IN PLAY (you still get +2 Cards
    and +1 Action)" — and the failure is logged, never silent."""
    g = way_game("Way of the Horse")
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Copper"] * 4)
    del g["piles"]["Smithy"]
    del g["supply"]["Smithy"]
    play_with_way(g, A, "Smithy", "Way of the Horse")
    assert len(g["seats"][A]["hand"]) == 2 and g["actions"] == 1
    assert g["seats"][A]["in_play"] == ["Smithy"]
    assert events(g, "lost_track")[-1]["card"] == "Smithy"


def test_way_of_the_mole_discards_your_hand_and_draws_three():
    g = way_game("Way of the Mole")
    give_hand(g, A, ["Smithy", "Copper", "Estate"])
    give_deck(g, A, ["Gold", "Gold", "Gold", "Silver"])
    play_with_way(g, A, "Smithy", "Way of the Mole")
    assert g["actions"] == 1
    assert sorted(g["seats"][A]["hand"]) == ["Gold", "Gold", "Gold"]
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Estate"]


def test_way_of_the_mole_draws_three_even_with_no_hand_to_discard():
    g = way_game("Way of the Mole")
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Gold", "Gold", "Gold"])
    play_with_way(g, A, "Smithy", "Way of the Mole")
    assert len(g["seats"][A]["hand"]) == 3 and g["actions"] == 1


def test_way_of_the_monkey_gives_a_buy_and_a_coin():
    g = way_game("Way of the Monkey")
    give_hand(g, A, ["Smithy"])
    play_with_way(g, A, "Smithy", "Way of the Monkey")
    assert g["buys"] == 2 and g["coins"] == 1


def test_way_of_the_mouse_plays_the_set_aside_card_leaving_it_there():
    g = way_game("Way of the Mouse")
    assert g["mouse_card"] is not None, "setup picks one"
    g["mouse_card"] = "Village"
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Gold"])
    play_with_way(g, A, "Smithy", "Way of the Mouse")
    assert g["seats"][A]["hand"] == ["Gold"]      # Village's +1 Card
    assert g["actions"] == 2                       # 1 - 1 spent + 2
    assert g["mouse_card"] == "Village"
    assert "Village" not in g["seats"][A]["in_play"]
    assert events(g, "play_mouse")[-1]["card"] == "Village"


def test_way_of_the_mouse_is_not_offered_without_a_mouse_card():
    """The join-time pool rule: an offer that can do nothing must never be
    collected."""
    g = way_game("Way of the Mouse")
    g["mouse_card"] = None
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Copper"] * 4)
    play(g, A, "Smithy")
    assert not g["pending"], "no Way prompt at all"
    assert len(g["seats"][A]["hand"]) == 3


def test_way_of_the_mule_gives_an_action_and_a_coin():
    g = way_game("Way of the Mule")
    give_hand(g, A, ["Smithy"])
    play_with_way(g, A, "Smithy", "Way of the Mule")
    assert g["actions"] == 1 and g["coins"] == 1


def test_way_of_the_otter_draws_two():
    g = way_game("Way of the Otter")
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Gold", "Silver", "Copper"])
    play_with_way(g, A, "Smithy", "Way of the Otter")
    assert sorted(g["seats"][A]["hand"]) == ["Gold", "Silver"]


def test_way_of_the_ox_gives_two_actions():
    g = way_game("Way of the Ox")
    give_hand(g, A, ["Smithy"])
    play_with_way(g, A, "Smithy", "Way of the Ox")
    assert g["actions"] == 2


def test_way_of_the_owl_draws_up_to_six():
    g = way_game("Way of the Owl")
    give_hand(g, A, ["Smithy", "Copper"])
    give_deck(g, A, ["Gold"] * 8)
    play_with_way(g, A, "Smithy", "Way of the Owl")
    assert len(g["seats"][A]["hand"]) == 6      # 1 left in hand + 5 drawn


def test_way_of_the_owl_never_draws_below_your_hand():
    g = way_game("Way of the Owl")
    give_hand(g, A, ["Smithy"] + ["Copper"] * 7)
    give_deck(g, A, ["Gold"] * 8)
    play_with_way(g, A, "Smithy", "Way of the Owl")
    assert len(g["seats"][A]["hand"]) == 7      # already above 6: draw nothing


def test_way_of_the_owl_is_not_a_printed_plus_so_the_chameleon_misses_it():
    """"Only card drawing denoted with '+' is changed to +$. For instance 'draw
    2 cards' is unchanged" (ch. VII Way of the Chameleon 4) — which is the whole
    reason `add_cards` and `draw` are separate primitives."""
    g = way_game("Way of the Owl")
    give_hand(g, A, ["Smithy", "Copper"])
    give_deck(g, A, ["Gold"] * 8)
    g["turn_ctx"]["chameleon"] = True
    play_with_way(g, A, "Smithy", "Way of the Owl")
    assert len(g["seats"][A]["hand"]) == 6
    assert g["coins"] == 0


def test_way_of_the_pig_gives_a_card_and_an_action():
    g = way_game("Way of the Pig")
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Gold", "Silver"])
    play_with_way(g, A, "Smithy", "Way of the Pig")
    assert g["seats"][A]["hand"] == ["Gold"] and g["actions"] == 1


def test_way_of_the_rat_discards_a_treasure_to_gain_a_copy_of_the_played_card():
    """"You GAIN A COPY of the played card" — "this" is the Action, not the
    Way."""
    g = way_game("Way of the Rat")
    give_hand(g, A, ["Smithy", "Copper", "Estate"])
    before = engine.pile_count(g, "Smithy")
    play_with_way(g, A, "Smithy", "Way of the Rat")
    fr = frame(g)
    assert fr["constraint"]["cards"] == ["Copper"], "Treasures only"
    assert fr["constraint"]["min"] == 0, "'you may'"
    decide(g, A, cards=["Copper"])
    engine._drive(g)
    assert g["seats"][A]["discard"].count("Copper") == 1
    assert g["seats"][A]["discard"].count("Smithy") == 1
    assert engine.pile_count(g, "Smithy") == before - 1


def test_way_of_the_rat_may_be_declined_and_needs_a_treasure():
    g = way_game("Way of the Rat")
    give_hand(g, A, ["Smithy", "Copper"])
    play_with_way(g, A, "Smithy", "Way of the Rat")
    decide(g, A, cards=[])
    engine._drive(g)
    assert g["seats"][A]["discard"] == []
    g2 = way_game("Way of the Rat")
    give_hand(g2, A, ["Smithy", "Estate"])
    play_with_way(g2, A, "Smithy", "Way of the Rat")
    assert not g2["pending"], "no Treasure in hand: no prompt"


def test_way_of_the_rat_gains_nothing_when_the_pile_is_empty():
    g = way_game("Way of the Rat")
    give_hand(g, A, ["Smithy", "Copper"])
    play_with_way(g, A, "Smithy", "Way of the Rat")
    g["supply"]["Smithy"] = 0
    decide(g, A, cards=["Copper"])
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Copper"]
    assert events(g, "lost_track")[-1]["card"] == "Smithy"


def test_way_of_the_seal_may_topdeck_each_card_you_gain_this_turn():
    g = way_game("Way of the Seal")
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Copper"])
    play_with_way(g, A, "Smithy", "Way of the Seal")
    assert g["coins"] == 1
    gain(g, A, "Gold")
    assert frame(g)["card"] == "Way of the Seal"
    assert opt_ids(g) == ["yes", "no"]
    pick(g, A, "yes")
    engine._drive(g)
    assert g["seats"][A]["deck"][0] == "Gold"
    # ...and again for the next gain — it is a rest-of-turn ability
    gain(g, A, "Silver")
    pick(g, A, "no")
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Silver"]


def test_way_of_the_seal_dies_with_the_turn():
    g = way_game("Way of the Seal")
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Copper"] * 12)
    play_with_way(g, A, "Smithy", "Way of the Seal")
    end_turn(g, A)
    end_turn(g, B)
    engine._drive(g)
    assert g["turn"] == A
    gain(g, A, "Gold")
    assert not g["pending"]


def test_way_of_the_sheep_gives_two_coins():
    g = way_game("Way of the Sheep")
    give_hand(g, A, ["Smithy"])
    play_with_way(g, A, "Smithy", "Way of the Sheep")
    assert g["coins"] == 2 and g["seats"][A]["hand"] == []


def test_way_of_the_squirrel_draws_two_at_the_end_of_the_turn():
    """"+2 Cards at the END of this turn" — after the new hand is drawn, so the
    cards are for next turn. "You can use this several times in a turn"."""
    g = way_game("Way of the Squirrel")
    give_hand(g, A, ["Smithy", "Market"])
    give_deck(g, A, ["Copper"] * 20)
    g["actions"] = 2
    play_with_way(g, A, "Smithy", "Way of the Squirrel")
    assert g["seats"][A]["hand"] == ["Market"], "nothing drawn yet"
    play_with_way(g, A, "Market", "Way of the Squirrel")
    assert g["turn_ctx"]["end_draw"] == 4, "it accumulates"
    end_turn(g, A)
    assert len(g["seats"][A]["hand"]) == 9      # 5 + 4


def test_way_of_the_turtle_sets_the_card_aside_and_plays_it_next_turn():
    g = way_game("Way of the Turtle")
    give_hand(g, A, ["Smithy"])
    give_deck(g, A, ["Copper"] * 20)
    play_with_way(g, A, "Smithy", "Way of the Turtle")
    assert g["seats"][A]["set_aside"] == ["Smithy"]
    assert g["seats"][A]["in_play"] == []
    end_turn(g, A)
    assert g["seats"][A]["set_aside"] == ["Smithy"], "not discarded in Clean-up"
    end_turn(g, B)
    engine._drive(g)
    assert g["turn"] == A
    # "You may then choose to use Turtle again (and so on)" — the replay goes
    # through play_action_card, so the offer comes round again.
    fr = frame(g)
    assert fr["card"] == "Way of the Turtle" and fr["kind"] == "choose_option"
    pick(g, A, "normal")
    engine._drive(g)
    assert g["seats"][A]["in_play"] == ["Smithy"]
    assert len(g["seats"][A]["hand"]) == 8      # 5 + Smithy's 3
    assert g["actions"] == 1, "played by the Turtle, not out of your Action pool"


def test_way_of_the_turtle_on_a_card_that_is_not_in_play_does_nothing():
    """"If you play a card WITHOUT MOVING IT INTO PLAY, and use the Way, you
    can't set it aside" — and the skip is logged."""
    g = way_game("Way of the Turtle")
    give_hand(g, A, ["Throne Room", "Smithy"])
    give_deck(g, A, ["Copper"] * 20)
    play(g, A, "Throne Room")
    pick(g, A, "normal")
    engine._drive(g)
    decide(g, A, cards=["Smithy"])
    engine._drive(g)
    pick(g, A, "normal")            # first Smithy play: normal, so it IS in play
    engine._drive(g)
    pick(g, A, "way")               # the replay: the Turtle takes it off the table
    engine._drive(g)
    assert g["seats"][A]["set_aside"] == ["Smithy"]
    end_turn(g, A)
    end_turn(g, B)
    engine._drive(g)
    assert frame(g)["card"] == "Way of the Turtle"


def test_way_of_the_worm_exiles_an_estate_from_the_supply():
    g = way_game("Way of the Worm")
    give_hand(g, A, ["Smithy"])
    estates = g["supply"]["Estate"]
    play_with_way(g, A, "Smithy", "Way of the Worm")
    assert g["seats"][A]["exile"] == ["Estate"]
    assert g["supply"]["Estate"] == estates - 1
    assert not events(g, "gain")


# ══ THE ROSTER ═══════════════════════════════════════════════════════════════

def test_every_way_in_the_data_has_a_would_resolve_consumer():
    """The roster is a HAND-WRITTEN list in the module (the REVIEWED lesson) —
    this is the test that it matches the data, in both directions, so a Way
    added to cards.py without a stage fails here rather than at a table."""
    from games.dontminion import effects_menagerie as men
    dealt = {n for n, d in cards.LANDSCAPES.items() if d["kind"] == "way"}
    assert set(men.WAYS) == dealt
    assert len(dealt) == 20
    for way in sorted(dealt):
        specs = effects.TRIGGERS[way]
        assert [s["on"] for s in specs] == ["would_resolve"], way
        assert specs[0]["from"] == "landscape" and specs[0]["stage"] == "offer"
        assert ("way", "offer") != (way, "offer")     # both stages registered
        assert (way, "offer") in effects.STAGES, way
        assert (way, "do") in effects.STAGES, way


def test_every_half_b_card_is_registered():
    """Half B's roster, pinned against the data. It read the two batch HALVES
    until they were concatenated into `effects_menagerie.py`; the disjointness
    half of the claim is now enforced structurally by that merge (one file,
    one registry per name) and by `effects.py`'s duplicate check, so what is
    left to assert is the part the merge cannot prove: that every card this
    half owns really is in the set's data and really did register."""
    mine = {"Black Cat", "Sleigh", "Sheepdog", "Falconer", "Village Green",
            "Barge", "Coven", "Cardinal", "Gatekeeper", "Mastermind",
            "Stockpile"}
    for name in sorted(mine):
        assert name in cards.CARDS and cards.CARDS[name]["expansion"] == "menagerie"
        assert name in effects.EFFECTS, name


def test_every_menagerie_card_that_needs_an_effect_has_one():
    """The stronger claim the half-disjointness test was standing in for, and
    the one a future set actually wants: walk the DATA and demand a registered
    ability for every card whose text is more than its printed coins. A pure
    Treasure or Victory card needs no entry (the handlers plus cards.py cover
    it) — nothing in Menagerie is one, which is itself worth pinning."""
    men = [n for n, c in cards.CARDS.items() if c["expansion"] == "menagerie"]
    assert len(men) == 31                      # 30 kingdom piles + Horse
    for name in sorted(men):
        assert name in effects.EFFECTS, f"{name} ships with no ability"


# ══ B13 — an OFF-TURN Way with an end-of-turn seam ═══════════════════════════
#
# Way of the Frog 4 and Way of the Squirrel 1 carry the same sentence — "this
# Way also works if you use it on an opponent's turn" — and neither has a seam
# in the engine today (deviation B13: `_end_turn`'s off-turn seat sweep emits
# no `cleanup_discard`, and `turn_ctx["end_draw"]` is a single counter drained
# for the turn player).
#
# What is NOT negotiable is that the skip be VISIBLE. A correct skip and a
# broken trigger leave identical game state, which is the whole reason
# `lost_track` exists — and Frog was silent until this landed.

def _way_frame(pid, card):
    return {"kind": "auto", "pid": pid, "card": "w", "stage": "do",
            "constraint": {}, "data": {"card": card}}


def _logged(g, event):
    return [e for e in g["log"] if e.get("event") == event]


def test_an_off_turn_way_of_the_frog_says_it_cannot_topdeck():
    from games.dontminion import effects_menagerie as men
    g = fresh()
    g["turn"] = A
    men._w_frog(g, B, _way_frame(B, "Moat"), None)
    assert _logged(g, "lost_track"), "an off-turn Frog must not fail silently"
    # ...and it registered NO watcher, rather than one that could never fire
    assert not [w for w in g["watchers"] if w["card"] == "Way of the Frog"]


def test_an_on_turn_way_of_the_frog_still_registers_its_watcher():
    """The control — without it, a Frog that stopped working entirely would
    pass the test above."""
    from games.dontminion import effects_menagerie as men
    g = fresh()
    men._w_frog(g, A, _way_frame(A, "Moat"), None)
    assert [w for w in g["watchers"] if w["card"] == "Way of the Frog"]
    assert not _logged(g, "lost_track")


def test_an_off_turn_way_of_the_squirrel_says_it_cannot_draw():
    from games.dontminion import effects_menagerie as men
    g = fresh()
    g["turn"] = A
    before = g["turn_ctx"]["end_draw"]
    men._w_squirrel(g, B, _way_frame(B, "Moat"), None)
    assert _logged(g, "lost_track")
    # the turn player's counter must NOT have been fed someone else's draw
    assert g["turn_ctx"]["end_draw"] == before


def test_an_on_turn_way_of_the_squirrel_still_queues_the_draw():
    from games.dontminion import effects_menagerie as men
    g = fresh()
    men._w_squirrel(g, A, _way_frame(A, "Moat"), None)
    assert g["turn_ctx"]["end_draw"] == 2
    assert not _logged(g, "lost_track")
