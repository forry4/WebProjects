"""ADVERSARIAL AUDIT of phase 10 (Menagerie) — the second, hostile reading.

Every test here was written from the Knutsen compendium v11.1 FIRST and only
then checked against the code, so a misunderstanding shared by the batch and
its own tests could not survive. Each block cites the chapter it came from.

WHAT THIS FILE PINS (five real defects, all found this way):

  * **"GAIN A COPY" IS A SUPPLY-ONLY EFFECT, and two cards ignored it.**
    Ch. VII COMMON EFFECTS: GAIN A COPY (p. 49) is one rule for a named family:
    "You can only gain a copy of a card **if it's available in the Supply**. If
    it's a Ruins, Castle or card from a split pile, **the top card of the pile
    has to have the same name**. If it's a **Knight** … it's impossible,
    because they all have different names. Includes: … **Kiln** … **Way of the
    Rat**." Ch. VIII's Kiln model repeats it ("gain a copy of it FROM THE
    SUPPLY") and ch. III GAINING A CARD (p. 20) closes the other half: "cards
    from non-Supply piles can only be gained by effects that specifically say
    to gain them from that pile or effects that NAME the card."
    Both cards read `pile_of()` and gained whatever it returned, so Kiln on a
    played Horse and Way of the Rat on a played Horse each minted a card out
    of the 30-card non-Supply pile — reachable in **every** Menagerie game with
    a Horse producer — and Kiln on a Knight/Ruins/split pile gained the pile's
    top card under the played card's name.

  * **A GAIN THAT FOLLOWS A GAIN IS PARKED BELOW IT** (Groom 4, Demand 3):
    "you gain each card in turn … Any when-gain ability applied after the first
    card will be in effect when you gain the next." Groom and Demand both ran
    straight-line `gain(); gain(...)`, which parks two pools that come off the
    stack in REVERSE — the *second* card's reactions were offered first. This
    is the very trap `_seq_gain`'s docstring describes, applied to Alliance and
    Commerce and missed on the two cards that gain a Horse alongside something.

  * **SCRAP CHECKS THE COST AFTER THE TRASH**, not before. Ch. VII Scrap ❖:
    "See TRIGGERED ABILITY (first trash, **then check cost**, then resolve the
    bonuses in the order given)." This is not deviation B3's capture-first
    shape, and Menagerie is where the difference became observable: Destrier
    costs "$1 less per card you've gained this turn", so a Market Square
    reacting to the trash by gaining a Gold must cost Scrap one option.

The four *questions* the audit was asked also have tests here where the answer
is behavioural rather than a citation — Seize the Day's stated exception to the
2023 no-third-turn rule, and Way of the Chameleon's turn-wide scope.
"""

from games.dontminion import cards, effects, engine

A, B = "alice", "bob"


# ── helpers (this file's own, deliberately: an audit that reuses the batch's
#    fixtures inherits the batch's assumptions) ────────────────────────────────

def new(kingdom, expansions=("menagerie", "base"), landscapes=(), players=(A, B),
        seed=7):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom), landscapes=list(landscapes))


def frame(g):
    return g["pending"][-1] if g["pending"] else None


def decide(g, pid, **payload):
    ok, err = engine.apply_move(g, pid, {"type": "decision", **payload})
    assert ok, err


def pick(g, pid, option_id):
    fr = frame(g)
    assert fr is not None and fr["kind"] == "choose_option", fr
    ids = [o["id"] for o in fr["constraint"]["options"]]
    assert option_id in ids, ids
    decide(g, pid, ids=[option_id])


def play(g, pid, card):
    ok, err = engine.apply_move(g, pid, {"type": "play_action", "card": card})
    assert ok, err


def logs(g, event):
    return [e for e in g["log"] if e.get("event") == event]


def gains(g):
    return [e["card"] for e in logs(g, "gain")]


# ══════════════════════════════════════════════════════════════════════════════
# 1. "GAIN A COPY" IS SUPPLY-ONLY — KILN
# ══════════════════════════════════════════════════════════════════════════════

KILN = ["Kiln", "Hunting Lodge", "Livery", "Paddock", "Sanctuary", "Destrier",
        "Fisherman", "Wayfarer", "Animal Fair", "Scrap"]


def test_kiln_may_not_gain_a_copy_of_a_horse_the_pile_is_not_in_the_supply():
    """Ch. VII GAIN A COPY: "you can only gain a copy of a card if it's
    available in the SUPPLY … Includes: … Kiln". The Horse pile is explicitly
    "outside the Supply" (ch. I Menagerie setup), and ch. III GAINING A CARD
    only lets an effect reach a non-Supply pile if it names the pile or the
    card — Kiln's "gain a copy of it" does neither.

    This board has a Horse pile in every game (Livery, Paddock and Scrap all
    say Horse), so before the fix a Kiln + Horse turn minted one for free."""
    g = new(KILN, landscapes=[])
    assert "Horse" in g["piles"] and "Horse" not in g["supply"]
    before = engine.pile_count(g, "Horse")
    g["seats"][A]["hand"] = ["Kiln", "Horse"]
    g["actions"] = 5
    play(g, A, "Kiln")
    play(g, A, "Horse")
    # no offer at all — and it is NOT silent (the lose-track discipline)
    assert frame(g) is None, frame(g)
    assert [e["card"] for e in logs(g, "lost_track")] == ["Horse"]
    assert "Horse" not in gains(g)
    # the played Horse returned ITSELF to the pile (its own play ability), and
    # nothing was taken off it — the pile only ever grew
    assert engine.pile_count(g, "Horse") == before + 1


def test_kiln_may_not_gain_a_copy_of_a_knight_they_all_have_different_names():
    """Ch. VII GAIN A COPY: "if it's a Ruins, Castle or card from a split pile,
    THE TOP CARD OF THE PILE HAS TO HAVE THE SAME NAME. If it's a Knight …
    it's impossible, because they all have different names."

    Before the fix Kiln offered "Gain a copy of <the played Knight>" and handed
    over whichever Knight happened to be on top."""
    g = new(["Kiln", "Knights", "Hunting Lodge", "Livery", "Paddock",
             "Sanctuary", "Destrier", "Fisherman", "Wayfarer", "Scrap"],
            expansions=("menagerie", "darkages"), landscapes=[])
    top = engine.pile_top(g, "Knights")
    other = [m for m in g["piles"]["Knights"]["members"] if m != top][0]
    g["seats"][A]["hand"] = ["Kiln", other]
    g["actions"] = 5
    play(g, A, "Kiln")
    play(g, A, other)
    assert frame(g) is None, frame(g)
    assert engine.pile_top(g, "Knights") == top          # nothing was taken
    assert [e["card"] for e in logs(g, "lost_track")] == [other]


def test_kiln_still_copies_an_ordinary_supply_card():
    """The control: the whole point of Kiln still works."""
    g = new(KILN, landscapes=[])
    g["seats"][A]["hand"] = ["Kiln", "Sanctuary"]
    g["actions"] = 5
    play(g, A, "Kiln")
    play(g, A, "Sanctuary")
    fr = frame(g)
    assert fr is not None and fr["card"] == "Kiln", fr
    assert fr["constraint"]["options"][0]["label"] == "Gain a copy of Sanctuary"
    pick(g, A, "yes")
    assert "Sanctuary" in gains(g)


# ══════════════════════════════════════════════════════════════════════════════
# 2. "GAIN A COPY" IS SUPPLY-ONLY — WAY OF THE RAT
# ══════════════════════════════════════════════════════════════════════════════

WAYS_KINGDOM = ["Smithy", "Market", "Laboratory", "Moat", "Throne Room",
                "Sanctuary", "Livery", "Cellar", "Militia", "Festival"]


def test_way_of_the_rat_may_not_gain_a_horse():
    """Ch. VII GAIN A COPY names Way of the Rat in the same list as Kiln, and
    Way of the Rat 1 is "you GAIN A COPY of the played card" — so playing a
    Horse using this Way discards the Treasure for nothing.

    This is the most reachable shape of the bug in the whole set: any board
    with a Horse producer and Way of the Rat dealt."""
    g = new(WAYS_KINGDOM, landscapes=["Way of the Rat"])
    assert "Horse" in g["piles"] and "Horse" not in g["supply"]
    before = engine.pile_count(g, "Horse")
    g["seats"][A]["hand"] = ["Horse", "Copper"]
    g["actions"] = 5
    play(g, A, "Horse")
    pick(g, A, "way")                    # resolve Way of the Rat
    fr = frame(g)
    assert fr is not None and fr["card"] == "Way of the Rat", fr
    decide(g, A, cards=["Copper"])       # discard a Treasure to "gain a copy"
    assert "Horse" not in gains(g)
    # the Way REPLACED Horse's play ability, so it never returned itself either
    assert engine.pile_count(g, "Horse") == before
    assert [e["card"] for e in logs(g, "lost_track")] == ["Horse"]


def test_way_of_the_rat_still_gains_an_ordinary_supply_copy():
    """The control."""
    g = new(WAYS_KINGDOM, landscapes=["Way of the Rat"])
    g["seats"][A]["hand"] = ["Smithy", "Copper"]
    g["actions"] = 5
    play(g, A, "Smithy")
    pick(g, A, "way")
    decide(g, A, cards=["Copper"])
    assert "Smithy" in gains(g)


# ══════════════════════════════════════════════════════════════════════════════
# 3. A GAIN THAT FOLLOWS A GAIN IS PARKED BELOW IT
# ══════════════════════════════════════════════════════════════════════════════

def _sleigh_targets(g, pid):
    """Every gained card a Sleigh reaction was offered for, in the order the
    offers arrived. Sleigh is the probe because its window is per-gain and the
    prompt names the card ("MOVE GAINED CARD", ch. VII p. 51)."""
    out = []
    while True:
        fr = frame(g)
        if fr is None or fr["card"] != "Sleigh":
            return out
        out.append(fr["data"]["gained"])
        pick(g, pid, "decline")


def test_groom_resolves_the_gained_cards_own_gain_before_the_horse():
    """Groom 4: "You gain each card IN TURN … Any when-gain ability (like
    Tracker or Abundance) applied after the first card WILL BE IN EFFECT WHEN
    YOU GAIN THE NEXT." So the card Groom gains is a completed gain — its
    reactions offered and resolved — before the Horse is gained.

    Straight-line `gain(pile); gain_from("Horse")` parks two pools that come
    off the stack in reverse, so the HORSE's Sleigh window opened first and a
    player who wanted to redirect the card Groom actually gained had already
    lost track of it."""
    g = new(["Groom", "Sleigh", "Village", "Smithy", "Market", "Moat",
             "Cellar", "Workshop", "Vassal", "Mill"], landscapes=[])
    g["seats"][A]["hand"] = ["Groom", "Sleigh"]
    g["actions"] = 5
    play(g, A, "Groom")
    decide(g, A, pile="Village")          # an ACTION, so a Horse follows
    assert _sleigh_targets(g, A) == ["Village", "Horse"]


def test_groom_still_gives_every_bonus_for_a_multi_type_card_in_order():
    """"If you gain a card that has SEVERAL of the types, you get ALL relevant
    bonuses" and "resolve them IN THE ORDER GIVEN" (Groom 1–2) — the control
    for the re-ordering, on a card that is Action AND Victory."""
    g = new(["Groom", "Mill", "Village", "Smithy", "Market", "Moat",
             "Cellar", "Workshop", "Vassal", "Sanctuary"], landscapes=[])
    g["seats"][A]["hand"] = ["Groom"]
    g["seats"][A]["deck"] = ["Copper"] * 5
    g["actions"] = 5
    before = g["actions"]
    play(g, A, "Groom")
    decide(g, A, pile="Mill")             # Action + Victory
    assert gains(g) == ["Mill", "Horse"]  # Horse (Action), then the Victory half
    assert g["actions"] == before - 1 + 1  # the Groom play, then Mill's +1 Action


def test_demand_resolves_the_horses_gain_before_choosing_the_second_card():
    """Demand 3: "You gain each card in turn and IN THE ORDER GIVEN, see
    TRIGGERED ABILITY." The Horse is gained first, so its window comes first —
    and the $4 pile list is built from the board as it stands afterwards."""
    g = new(["Sleigh", "Village", "Smithy", "Market", "Moat", "Cellar",
             "Workshop", "Vassal", "Mill", "Sanctuary"],
            landscapes=["Demand"])
    g["seats"][A]["hand"] = ["Sleigh"]
    g["coins"], g["buys"] = 5, 1
    g["phase"] = "buy"
    ok, err = engine.apply_move(g, A, {"type": "buy_landscape", "name": "Demand"})
    assert ok, err
    # the Horse's own window, first — and only then the pile choice
    assert _sleigh_targets(g, A) == ["Horse"]
    fr = frame(g)
    assert fr is not None and fr["card"] == "Demand" and fr["kind"] == "choose_pile", fr


def test_demand_still_gains_the_second_card_with_no_horses_left():
    """"If there are no Horses left, you still gain the other card" (Demand 1)
    — which is why the continuation is parked unconditionally."""
    g = new(["Village", "Smithy", "Market", "Moat", "Cellar", "Workshop",
             "Vassal", "Mill", "Sanctuary", "Livery"], landscapes=["Demand"])
    g["piles"]["Horse"]["contents"] = []
    g["coins"], g["buys"] = 5, 1
    g["phase"] = "buy"
    ok, err = engine.apply_move(g, A, {"type": "buy_landscape", "name": "Demand"})
    assert ok, err
    decide(g, A, pile="Village")
    assert gains(g) == ["Village"]
    assert g["seats"][A]["deck"][0] == "Village"      # "both onto your deck"


# ══════════════════════════════════════════════════════════════════════════════
# 4. SCRAP CHECKS THE COST AFTER THE TRASH
# ══════════════════════════════════════════════════════════════════════════════

def test_scrap_reads_the_trashed_cards_cost_after_the_trash_resolves():
    """Ch. VII Scrap ❖: "first trash, THEN CHECK COST, then resolve the bonuses
    in the order given."

    Destrier "costs $1 less per card you've gained this turn" (Destrier 1), and
    Market Square gains a Gold when one of your cards is trashed — so trashing a
    Destrier with Scrap gains a card DURING the trash and Destrier is $5 by the
    time Scrap counts. Reading the cost before the trash gave six options."""
    g = new(["Scrap", "Market Square", "Destrier", "Village", "Smithy",
             "Market", "Moat", "Cellar", "Workshop", "Vassal"],
            expansions=("menagerie", "base", "darkages"), landscapes=[])
    assert engine.cost(g, "Destrier") == 6
    g["seats"][A]["hand"] = ["Scrap", "Destrier", "Market Square"]
    g["actions"] = 5
    play(g, A, "Scrap")
    decide(g, A, cards=["Destrier"])
    # Market Square's own window, on the trash
    fr = frame(g)
    assert fr is not None and fr["card"] == "Market Square", fr
    pick(g, A, "play")
    assert "Gold" in gains(g)
    assert engine.cost(g, "Destrier") == 5      # the gain moved it
    fr = frame(g)
    assert fr is not None and fr["card"] == "Scrap" and fr["stage"] == "do", fr
    assert fr["constraint"]["pick"] == 5


def test_scrap_still_gives_one_option_per_coin_with_nothing_intervening():
    """The control — an ordinary trash reads the same cost either way."""
    g = new(["Scrap", "Destrier", "Village", "Smithy", "Market", "Moat",
             "Cellar", "Workshop", "Vassal", "Sanctuary"], landscapes=[])
    g["seats"][A]["hand"] = ["Scrap", "Destrier"]
    g["actions"] = 5
    play(g, A, "Scrap")
    decide(g, A, cards=["Destrier"])
    fr = frame(g)
    assert fr is not None and fr["card"] == "Scrap" and fr["stage"] == "do", fr
    assert fr["constraint"]["pick"] == 6


def test_scrap_on_a_copper_still_offers_nothing():
    """"If there is a COST REDUCTION, Scrap will give you fewer options" — and
    at $0 there is nothing to pick, which the parked stage must handle rather
    than open an impossible prompt."""
    g = new(["Scrap", "Village", "Smithy", "Market", "Moat", "Cellar",
             "Workshop", "Vassal", "Mill", "Sanctuary"], landscapes=[])
    g["seats"][A]["hand"] = ["Scrap", "Copper"]
    g["actions"] = 5
    play(g, A, "Scrap")
    decide(g, A, cards=["Copper"])
    assert frame(g) is None
    assert g["trash"].count("Copper") == 1


# ══════════════════════════════════════════════════════════════════════════════
# 5. THE OPEN QUESTIONS THE AUDIT WAS ASKED — behaviour that the citations
#    settle, pinned so a later change is on purpose.
# ══════════════════════════════════════════════════════════════════════════════

def test_seize_the_day_and_outpost_give_three_turns_in_a_row():
    """Ch. VII Seize the Day 2, verbatim: "If you trigger Seize the Day and
    (for instance) Outpost on the same turn, you will get both extra turns as
    long as you take the Seize the Day turn last. THIS WOULD GIVE YOU THREE
    TURNS IN A ROW."

    The sentence exists and says what the kernel now does. The player is never
    asked which order: taking Seize's turn first would strand the Outpost turn
    (a third in a row, denied by the 2023 errata), so the order that gives you
    both is the only one anyone would pick — the same reasoning as B8."""
    g = new(["Village", "Smithy", "Market", "Moat", "Cellar", "Workshop",
             "Vassal", "Mill", "Sanctuary", "Livery"],
            expansions=("menagerie", "base", "seaside"),
            landscapes=["Seize the Day"])
    g["seats"][A]["hand"] = ["Outpost", "Copper", "Copper"]
    g["seats"][A]["deck"] = ["Copper"] * 40
    g["seats"][B]["deck"] = ["Copper"] * 40
    g["actions"] = 5
    play(g, A, "Outpost")
    assert g["_outpost"] == A
    engine.apply_move(g, A, {"type": "end_phase"})       # -> buy
    assert g["phase"] == "buy" and g["turn"] == A
    g["coins"], g["buys"] = 4, 1
    ok, err = engine.apply_move(g, A, {"type": "buy_landscape",
                                       "name": "Seize the Day"})
    assert ok, err
    assert g["_seize"] == A
    order = []
    for _ in range(40):
        order = [e["pid"] for e in logs(g, "turn_start")]
        if len(order) >= 5 or g["over"]:
            break
        assert not g["pending"], g["pending"][-1]
        ok, err = engine.apply_move(g, g["turn"], {"type": "end_phase"})
        assert ok, err
    # turn 1 (Outpost + Seize bought), then Outpost's extra turn, then Seize
    # the Day's — three in a row — and only then does the opponent play
    assert order[:4] == [A, A, A, B], order


def test_way_of_the_chameleon_swaps_a_card_played_later_in_the_same_turn():
    """Ch. VII Way of the Chameleon 1 and 3: "all +Cards YOU get THIS TURN are
    +$ instead, and vice versa"; ch. VIII models it as "effects that would give
    you +Cards this turn". Ch. VII 12 settles the reach directly — a Copper
    "played in your Buy phase" is still changed — so the flag is TURN-scoped
    and not play-scoped.

    (The one sentence pulling the other way is Chameleon 5, "if you play a
    Vassal, Throne Room or similar using this Way, the card that it plays is
    unaffected" — see the audit's report; nothing here implements it.)"""
    g = new(WAYS_KINGDOM, landscapes=["Way of the Chameleon"])
    g["seats"][A]["hand"] = ["Laboratory", "Smithy"]
    g["seats"][A]["deck"] = ["Copper"] * 10
    g["actions"] = 5
    coins, hand = g["coins"], len(g["seats"][A]["hand"])
    play(g, A, "Laboratory")                   # +2 Cards, +1 Action
    pick(g, A, "way")
    assert g["coins"] == coins + 2             # its own +2 Cards became +$2
    assert len(g["seats"][A]["hand"]) == hand - 1        # and drew nothing
    hand = len(g["seats"][A]["hand"])
    play(g, A, "Smithy")                       # a LATER card, played NORMALLY
    pick(g, A, "normal")
    assert g["coins"] == coins + 2 + 3         # its +3 Cards is +$3 all the same
    assert len(g["seats"][A]["hand"]) == hand - 1


def test_way_of_the_chameleon_leaves_an_opponents_plus_cards_alone():
    """Chameleon 2: "Only +Cards and +$ THAT YOU GET are changed. For instance
    if you play Governor using this Way, the other players' '+1 Card' is
    unchanged.\""""
    g = new(["Council Room", "Market", "Laboratory", "Moat", "Throne Room",
             "Sanctuary", "Livery", "Cellar", "Militia", "Festival"],
            landscapes=["Way of the Chameleon"])
    g["seats"][A]["hand"] = ["Council Room"]
    g["seats"][A]["deck"] = ["Copper"] * 10
    g["seats"][B]["deck"] = ["Estate"] * 10
    g["actions"] = 5
    b_hand = len(g["seats"][B]["hand"])
    coins = g["coins"]
    play(g, A, "Council Room")
    pick(g, A, "way")
    assert g["coins"] == coins + 4             # A's own +4 Cards -> +$4
    assert len(g["seats"][B]["hand"]) == b_hand + 1   # B still DRAWS


def test_way_of_the_chameleon_does_not_touch_a_draw_without_a_printed_plus():
    """Chameleon 4 (from the rulebook): "Only card drawing denoted with '+' is
    changed to +$. For instance 'draw 2 cards' is unchanged." Way of the Owl's
    "draw until you have 6 cards in hand" is that wording, and the two seams
    (`add_cards` vs `draw`) are independent by construction."""
    g = new(WAYS_KINGDOM, landscapes=["Way of the Chameleon"])
    g["seats"][A]["hand"] = ["Laboratory", "Smithy"]
    g["seats"][A]["deck"] = ["Copper"] * 10
    g["actions"] = 5
    play(g, A, "Laboratory")
    pick(g, A, "way")
    # the Owl's wording, reached through the kernel the Owl uses
    coins = g["coins"]
    before = len(g["seats"][A]["hand"])
    engine.draw(g, A, 2)
    assert g["coins"] == coins
    assert len(g["seats"][A]["hand"]) == before + 2


def test_way_of_the_chameleon_swaps_a_printed_plus_coin_into_cards_too():
    """"…and vice versa (keeping their values)" (Chameleon 1). Market's printed
    +$1 draws a card instead, and its printed +1 Card pays $1 — the two halves
    cross in the same play."""
    g = new(WAYS_KINGDOM, landscapes=["Way of the Chameleon"])
    g["seats"][A]["hand"] = ["Market"]
    g["seats"][A]["deck"] = ["Copper"] * 10
    g["actions"] = 5
    coins, hand = g["coins"], len(g["seats"][A]["hand"])
    play(g, A, "Market")                       # +1 Card, +1 Action, +1 Buy, +$1
    pick(g, A, "way")
    assert g["coins"] == coins + 1             # the +1 Card
    assert len(g["seats"][A]["hand"]) == hand - 1 + 1    # ...and the +$1 drew


def test_the_2E_cellar_is_unchanged_by_the_chameleon_and_the_1E_one_would_not_be():
    """Ch. VII Way of the Chameleon 4's own note: "some cards that were revised
    in the 2016–18 editions are functionally different with Way of the
    Chameleon depending on which edition you're using; namely **Cellar**,
    Oracle, Storeroom and Storyteller."

    That list is the whole argument for shipping Base 2E's Cellar ("discard any
    number of cards, THEN DRAW THAT MANY" — no printed plus) rather than 1E's
    "+1 Card per card discarded". Under the Chameleon the 2E card still draws;
    the 1E one would have paid $ instead. Pinned from both ends: the printed
    text and the behaviour."""
    assert "then draw that many" in cards.CARDS["Cellar"]["text"].lower()
    assert "+1 Card per card" not in cards.CARDS["Cellar"]["text"]
    g = new(WAYS_KINGDOM, landscapes=["Way of the Chameleon"])
    g["seats"][A]["hand"] = ["Laboratory", "Cellar", "Estate", "Estate"]
    g["seats"][A]["deck"] = ["Copper"] * 10
    g["actions"] = 5
    play(g, A, "Laboratory")
    pick(g, A, "way")                      # the Chameleon is now live all turn
    coins = g["coins"]
    play(g, A, "Cellar")
    pick(g, A, "normal")
    decide(g, A, cards=["Estate", "Estate"])
    assert g["coins"] == coins             # NOT +$2
    assert g["seats"][A]["hand"].count("Copper") == 2


# ══════════════════════════════════════════════════════════════════════════════
# 6. EXILE EDGE CASES (ch. IV EXILE, ch. VII Your Exile mat, Gatekeeper 6)
# ══════════════════════════════════════════════════════════════════════════════

def test_exiling_from_an_empty_supply_pile_does_nothing_and_the_rest_still_runs():
    """Ch. IV EXILE plus each card's own "if you can't" clause. Enclave 1 is
    the explicit one: "if there are no Golds left in the Supply, you still
    Exile a Duchy, AND VICE VERSA.\""""
    g = new(["Village", "Smithy", "Market", "Moat", "Cellar", "Workshop",
             "Vassal", "Mill", "Sanctuary", "Livery"], landscapes=["Enclave"])
    g["piles"]["Duchy"]["contents"] = []
    g["coins"], g["buys"] = 8, 1
    g["phase"] = "buy"
    ok, err = engine.apply_move(g, A, {"type": "buy_landscape", "name": "Enclave"})
    assert ok, err
    assert gains(g) == ["Gold"]                    # the Gold half still happened
    assert g["seats"][A]["exile"] == []            # ...and the Duchy half did not


def test_the_exile_mat_offers_all_or_nothing_and_only_when_a_copy_is_there():
    """Ch. VII Your Exile mat 1: "When you gain a card, you may discard ALL
    OTHER copies from your mat. (See COPY OF A CARD.) **You can't choose to
    just discard some of them.**" So it is a yes/no on the whole stack, keyed
    on the NAME (ch. VII COPY OF A CARD, p. 47), and a gain of something you
    have no Exiled copy of opens no window at all."""
    g = new(["Sanctuary", "Village", "Smithy", "Market", "Moat", "Cellar",
             "Workshop", "Vassal", "Mill", "Livery"], landscapes=[])
    g["seats"][A]["exile"] = ["Village", "Village", "Smithy"]
    engine.gain(g, A, "Market")
    engine._drive(g)
    assert frame(g) is None                        # no copy of Market on the mat
    engine.gain(g, A, "Village")
    engine._drive(g)
    fr = frame(g)
    assert fr is not None and fr["kind"] == "choose_option", fr
    assert [o["id"] for o in fr["constraint"]["options"]] == ["yes", "no"]
    assert "2 Village" in fr["constraint"]["options"][0]["label"]
    pick(g, A, "yes")
    assert g["seats"][A]["exile"] == ["Smithy"]    # ALL of them, never some


def test_gatekeeper_exiles_the_gained_card_and_the_mat_may_not_then_discard_it():
    """Gatekeeper 6, which is the rule that makes "other copies" load-bearing:
    "Your Exile mat only allows you to discard 'other copies', meaning NOT THE
    ONE YOU JUST GAINED. So if you Exile the gained card, you may not also
    discard it. (If you already have a copy there, Gatekeeper does nothing, and
    you may discard all copies from the mat as usual.)"

    Both halves, in one test."""
    g = new(["Gatekeeper", "Village", "Smithy", "Market", "Moat", "Cellar",
             "Workshop", "Vassal", "Mill", "Sanctuary"], landscapes=[])
    g["seats"][A]["hand"] = ["Gatekeeper"]
    g["actions"] = 5
    play(g, A, "Gatekeeper")
    engine.apply_move(g, A, {"type": "end_phase"})
    engine.apply_move(g, A, {"type": "end_phase"})
    assert g["turn"] == B
    # (a) B has no Exiled Village: Gatekeeper Exiles the gained one, and the
    #     mat opens no window for it
    engine.gain(g, B, "Village")
    engine._drive(g)
    assert frame(g) is None, frame(g)
    assert g["seats"][B]["exile"] == ["Village"]
    # (b) B now HAS a copy there: Gatekeeper does nothing and the mat offers
    engine.gain(g, B, "Village")
    engine._drive(g)
    fr = frame(g)
    assert fr is not None and fr["kind"] == "choose_option", fr
    pick(g, B, "yes")
    assert g["seats"][B]["exile"] == []
    assert g["seats"][B]["discard"].count("Village") == 2


def test_exiling_from_the_supply_is_not_a_gain():
    """Ch. IV EXILE: "Cards on your Exile mat are yours, but **Exiling cards
    from the Supply is not considered gaining cards.** Neither is discarding
    cards from your Exile mat." Way of the Camel/Worm and Camel Train all say
    so in their own entries too.

    The observable half is that no when-gain watcher fires — probed here with
    Livery, whose "when you gain a card costing $4 or more, gain a Horse" would
    otherwise pay out for a Gold nobody gained."""
    g = new(["Livery", "Camel Train", "Village", "Smithy", "Market", "Moat",
             "Cellar", "Workshop", "Vassal", "Sanctuary"], landscapes=[])
    g["seats"][A]["hand"] = ["Livery", "Camel Train"]
    g["actions"] = 5
    play(g, A, "Livery")
    play(g, A, "Camel Train")
    decide(g, A, pile="Gold")
    assert g["seats"][A]["exile"] == ["Gold"]
    assert gains(g) == []                # no gain emit, so no Livery Horse


# ══════════════════════════════════════════════════════════════════════════════
# 7. THE HORSE PILE (ch. VII Horse, ch. I Menagerie setup, ch. VII EMPTY
#    SUPPLY PILES)
# ══════════════════════════════════════════════════════════════════════════════

def test_the_horse_pile_running_out_stops_the_gains_and_ends_nothing():
    """Ch. VII EMPTY SUPPLY PILES: "when counting empty Supply piles, remember
    that NON-SUPPLY PILES ARE NOT COUNTED." The Horse pile is outside the
    Supply (ch. I), so an empty one never moves the three-pile game end and
    never feeds Paddock's or Animal Fair's "+1 per empty Supply pile" — while
    "you get the initial +$2 even if you can't gain 2 Horses, and you still get
    the +Actions" (Paddock 1) keeps the rest of the card intact."""
    g = new(["Paddock", "Village", "Smithy", "Market", "Moat", "Cellar",
             "Workshop", "Vassal", "Mill", "Sanctuary"], landscapes=[])
    g["piles"]["Horse"]["contents"] = []
    assert engine.count_empty_piles(g) == 0
    g["seats"][A]["hand"] = ["Paddock"]
    g["actions"] = 5
    coins, acts = g["coins"], g["actions"]
    play(g, A, "Paddock")
    assert g["coins"] == coins + 2
    assert g["actions"] == acts - 1 + 0     # no empty SUPPLY pile to count
    assert gains(g) == []
    assert not g["over"]


def test_a_horse_played_from_somewhere_it_cannot_return_from_still_pays_out():
    """Horse 2: "If you play Horse without moving it into play, you still get
    +2 Cards and +1 Action. (Throne Room + Horse will give you +4 Cards and
    +2 Actions.)" — the second play finds nothing on the table to return."""
    g = new(["Throne Room", "Livery", "Village", "Smithy", "Market", "Moat",
             "Cellar", "Workshop", "Vassal", "Sanctuary"], landscapes=[])
    g["seats"][A]["hand"] = ["Throne Room", "Horse"]
    g["seats"][A]["deck"] = ["Copper"] * 10
    g["actions"] = 5
    before = engine.pile_count(g, "Horse")
    acts, hand = g["actions"], len(g["seats"][A]["hand"])
    play(g, A, "Throne Room")
    decide(g, A, cards=["Horse"])
    # +4 Cards and +2 Actions, one return
    assert len(g["seats"][A]["hand"]) == hand - 2 + 4
    assert g["actions"] == acts - 1 + 2
    assert engine.pile_count(g, "Horse") == before + 1
    assert "Horse" not in g["seats"][A]["in_play"]


def test_the_cost_of_horse_is_three_for_any_ability_that_refers_to_it():
    """Horse 3: "The cost of Horse is $3 for any ability that refers to its
    cost." Read through the comparator family, not a printed-cost lookup."""
    g = new(["Scrap", "Livery", "Village", "Smithy", "Market", "Moat",
             "Cellar", "Workshop", "Vassal", "Sanctuary"], landscapes=[])
    assert engine.cost(g, "Horse") == 3
    assert engine.cost_ge(g, "Horse", 3) and not engine.cost_ge(g, "Horse", 4)
    assert engine.cost_le(g, "Horse", 3)
    g["seats"][A]["hand"] = ["Scrap", "Horse"]
    g["actions"] = 5
    play(g, A, "Scrap")
    decide(g, A, cards=["Horse"])
    fr = frame(g)
    assert fr is not None and fr["stage"] == "do", fr
    assert fr["constraint"]["pick"] == 3


# ══════════════════════════════════════════════════════════════════════════════
# 8. THE 2025 ERRATA WE SHIPPED (ch. V + per-card)
# ══════════════════════════════════════════════════════════════════════════════

def test_way_of_the_mouse_never_sets_aside_a_duration():
    """Ch. V's 2025 errata list names Way of the Mouse, and ch. VII Way of the
    Mouse 2 spells it out: "2025 (current) version: **The Mouse card can no
    longer be a Duration card.**" Ch. I's setup paragraph was never updated and
    still says only "an unused Action Kingdom card costing $2 or $3" — the card
    and ch. VII win.

    Derived from the catalogue rather than a hardcoded roster, so the next set
    that adds a $2/$3 Duration is covered without anyone remembering."""
    duration_23 = {c for c, d in cards.CARDS.items()
                   if d.get("kingdom") and d["cost"] in (2, 3)
                   and "duration" in d["types"]}
    assert duration_23, "no $2/$3 Duration in the catalogue — the test proves nothing"
    seen = set()
    for seed in range(40):
        g = engine.new_game([A, B], ["menagerie", "seaside", "base", "adventures"],
                            seed=seed, landscapes=["Way of the Mouse"])
        if g["mouse_card"]:
            seen.add(g["mouse_card"])
            assert "duration" not in cards.CARDS[g["mouse_card"]]["types"], g["mouse_card"]
            assert cards.CARDS[g["mouse_card"]]["cost"] in (2, 3)
    assert seen, "no board dealt a Mouse card"


def test_gamble_2025_discards_first_so_a_when_discard_reaction_fires_first():
    """Ch. V lists "Gamble 2025"; ch. VII Gamble 5: "2025 (current) version:
    Gamble now **always discards the top card first**. Then, if you play it, it
    moves from your discard pile to play." Its ❖ line adds "See TRIGGERED
    ABILITY (first discard, then play). Also see … Village Green 7."

    And Village Green 8 is the follow-on this pins: a Village Green that reacts
    to the discard by playing itself "cannot also be played by Vassal/Gamble"
    (the expanded 2021 lose-track rule)."""
    g = new(["Village Green", "Village", "Smithy", "Market", "Moat", "Cellar",
             "Workshop", "Vassal", "Mill", "Sanctuary"], landscapes=["Gamble"])
    g["seats"][A]["deck"] = ["Village Green"] + ["Copper"] * 5
    g["coins"], g["buys"] = 2, 1
    g["phase"] = "buy"
    ok, err = engine.apply_move(g, A, {"type": "buy_landscape", "name": "Gamble"})
    assert ok, err
    # the DISCARD happened, and Village Green's own when-discard window is what
    # opens first — before Gamble's play offer
    assert logs(g, "discard"), "Gamble did not discard first"
    fr = frame(g)
    assert fr is not None and fr["card"] == "Village Green", fr
    pick(g, A, "play")
    assert "Village Green" in g["seats"][A]["in_play"]
    pick(g, A, "now")            # Village Green's own two options
    # ...and Gamble can no longer play it: it is not in the discard pile
    assert [e["card"] for e in logs(g, "lost_track")] == ["Village Green"]


def test_reap_2025_gains_its_gold_straight_to_the_set_aside_area():
    """Ch. V lists "Reap 2025"; ch. VII Reap 2: "the card is now gained
    directly to your 'set aside' area (similarly to gaining to your hand/deck)"
    — and ch. VII GAIN TO YOUR HAND/DECK (p. 50) confirms the family:
    "Blockade, Quartermaster and Reap (CV) gain a card directly to your 'set
    aside' area." The Gold must never visit the discard pile."""
    g = new(["Village", "Smithy", "Market", "Moat", "Cellar", "Workshop",
             "Vassal", "Mill", "Sanctuary", "Livery"], landscapes=["Reap"])
    g["coins"], g["buys"] = 7, 1
    g["phase"] = "buy"
    ok, err = engine.apply_move(g, A, {"type": "buy_landscape", "name": "Reap"})
    assert ok, err
    assert g["seats"][A]["set_aside"] == ["Gold"]
    assert "Gold" not in g["seats"][A]["discard"]
    dest = [e.get("dest") for e in logs(g, "gain")]
    assert dest == ["set_aside"]


def test_village_green_ships_the_reveal_which_is_ambiguity_A9():
    """A9 is a CHOICE, not a bug — re-checked here rather than re-litigated.
    Ch. V's 2020 errata list is exactly "Trader (printed 2020), Village Green",
    so the change is real; ch. VII Village Green 10 then says it "was reverted
    back to the original version when printed in 2025"; and ch. VIII, in the
    same document, still heads its model "Village Green (current version,
    2020)" with "you may reveal This. If you do: Play This". The row's
    reasoning and both citations check out."""
    g = new(["Village Green", "Village", "Smithy", "Market", "Moat", "Cellar",
             "Workshop", "Vassal", "Mill", "Sanctuary"], landscapes=[])
    g["seats"][A]["hand"] = ["Village Green"]
    engine.discard(g, A, ["Village Green"])
    engine._drive(g)
    fr = frame(g)
    assert fr is not None and fr["card"] == "Village Green", fr
    pick(g, A, "play")
    engine._drive(g)
    assert logs(g, "reveal"), "A9 ships the reveal"
    assert "Village Green" in g["seats"][A]["in_play"]
