"""Cornucopia & Guilds batch-A card tests — Advisor, Baker, Candlestick Maker,
Carnival, Fairgrounds, Hamlet, Hunting Party, Joust, Menagerie, Merchant Guild,
Plaza, Remake, Shop, Soothsayer, and the Rewards Courser, Demesne, Housecarl,
Huge Turnip, Renown.

Positions are arranged by mutating the game dict directly (the repo's
board-fixture idiom). give_hand breaks card conservation, so no test here
asserts the census invariant (test_soak owns that).

Direct engine.gain(...) calls must be followed by engine._drive(g) — the
when-gain trigger parks an auto frame that only apply_move would drive.

Headline rulings pinned here:
  * DIFFERENTLY NAMED counting is the set's signature and it counts by NAME:
    Menagerie on an EMPTY hand draws 3 (all-different vacuously); Carnival
    keeps one of each and discards the duplicates; Housecarl counts distinct
    ACTIONS in play including itself; Fairgrounds scores 2 VP per 5 distinct
    cards over the whole deck.
  * CARDS YOU HAVE IN PLAY includes the duration zone and its riders, not just
    in_play — Housecarl and Shop both read it.
  * Advisor's choice belongs to THE PLAYER TO YOUR LEFT, on your turn, and it
    is not an attack (no reaction window).
  * Merchant Guild counts every card GAINED in the Buy phase, not just bought
    ones, including gains from before it was played; it is cumulative per play
    and pays at the END of the phase so the tokens can't be spent that turn.
  * Renown is Bridge (turn_ctx["bridges"] += 2), so it is cumulative and
    survives the card leaving play.
  * Joust's Province goes to the cleanup set-aside, NOT into play — a Province
    in play would feed Horn of Plenty and Shop — and it is discarded at
    Clean-up.
  * Hamlet's two offers are sequential, so the second one reads a hand the
    first may already have changed.
"""

import pytest

from games.dontminion import engine

A, B, C = "alice", "bob", "carol"

# Pinned kingdom = this batch's Supply cards (the forced-kingdom test seam).
KA = ["Advisor", "Baker", "Candlestick Maker", "Carnival", "Fairgrounds",
      "Hamlet", "Hunting Party", "Joust", "Menagerie", "Merchant Guild"]
KB = ["Plaza", "Remake", "Shop", "Soothsayer", "Village", "Smithy", "Moat",
      "Throne Room", "Market", "Festival"]


def fresh(players=(A, B), seed=42, kingdom=tuple(KA)):
    return engine.new_game(list(players), ["base"], seed=seed,
                           kingdom=list(kingdom))


def give_hand(g, pid, cards):
    g["seats"][pid]["hand"] = list(cards)


def give_deck(g, pid, cards):
    """Top of deck first."""
    g["seats"][pid]["deck"] = list(cards)


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def decide(g, pid, **payload):
    return engine.apply_move(g, pid, {"type": "decision", **payload})


def play(g, pid, card):
    return mv(g, pid, {"type": "play_action", "card": card})


def opt(g, pid, want):
    """Answer a choose_option frame by option id."""
    return decide(g, pid, ids=[want])


def frame(g):
    return g["pending"][-1] if g["pending"] else None


# --- Advisor -----------------------------------------------------------------

def test_advisor_the_player_to_your_left_picks_the_discard():
    g = fresh()
    give_hand(g, A, ["Advisor"])
    give_deck(g, A, ["Gold", "Estate", "Silver", "Copper"])
    ok, err = play(g, A, "Advisor")
    assert ok, err
    assert g["actions"] == 1                       # 1 - 1 spent + 1
    # the decision belongs to the LEFT-HAND player, not the Advisor's owner
    f = frame(g)
    assert f["pid"] == B and f["card"] == "Advisor"
    assert sorted(f["constraint"]["cards"]) == ["Estate", "Gold", "Silver"]
    assert engine.legal_moves(g, A) == []          # A cannot answer for B
    ok, err = decide(g, B, cards=["Gold"])
    assert ok, err
    assert "Gold" in g["seats"][A]["discard"]
    assert sorted(g["seats"][A]["hand"]) == ["Estate", "Silver"]
    assert g["seats"][A]["aside"] == []


def test_advisor_on_a_short_deck_reveals_what_there_is():
    g = fresh()
    give_hand(g, A, ["Advisor"])
    g["seats"][A]["deck"] = ["Gold"]
    g["seats"][A]["discard"] = []
    assert play(g, A, "Advisor")[0]
    assert frame(g)["constraint"]["cards"] == ["Gold"]
    decide(g, B, cards=["Gold"])
    assert g["seats"][A]["hand"] == []
    assert g["seats"][A]["discard"] == ["Gold"]


def test_advisor_is_not_an_attack_so_no_reaction_window_opens():
    g = fresh(kingdom=KA + ["Moat"])
    give_hand(g, A, ["Advisor"])
    give_deck(g, A, ["Gold", "Estate", "Silver"])
    g["seats"][B]["hand"] = ["Moat"]
    assert play(g, A, "Advisor")[0]
    # straight to B's pick — a Moat window would have been a choose_option
    assert frame(g)["kind"] == "choose_cards"


def test_advisor_asks_the_left_neighbour_in_a_three_player_game():
    g = fresh(players=(A, B, C))
    give_hand(g, A, ["Advisor"])
    give_deck(g, A, ["Gold", "Estate", "Silver"])
    assert play(g, A, "Advisor")[0]
    assert frame(g)["pid"] == B                    # turn order after A
    decide(g, B, cards=["Estate"])
    g2 = fresh(players=(A, B, C))
    g2["turn"] = C
    give_hand(g2, C, ["Advisor"])
    give_deck(g2, C, ["Gold", "Estate", "Silver"])
    assert play(g2, C, "Advisor")[0]
    assert frame(g2)["pid"] == A                   # wraps round


# --- Baker -------------------------------------------------------------------

def test_baker_is_a_cantrip_plus_a_coffers():
    g = fresh()
    give_hand(g, A, ["Baker", "Copper"])
    give_deck(g, A, ["Gold"])
    before = g["coffers"][A]
    assert play(g, A, "Baker")[0]
    assert "Gold" in g["seats"][A]["hand"]
    assert g["actions"] == 1
    assert g["coffers"][A] == before + 1


def test_baker_in_the_kingdom_starts_everyone_with_one_coffers():
    g = fresh()
    assert "Baker" in g["kingdom"]
    assert g["coffers"] == {A: 1, B: 1}
    # ...and a kingdom without Baker starts at zero
    g2 = fresh(kingdom=KB)
    assert "Baker" not in g2["kingdom"]
    assert g2["coffers"] == {A: 0, B: 0}


# --- Candlestick Maker -------------------------------------------------------

def test_candlestick_maker():
    g = fresh()
    give_hand(g, A, ["Candlestick Maker"])
    before = g["coffers"][A]
    assert play(g, A, "Candlestick Maker")[0]
    assert g["actions"] == 1 and g["buys"] == 2
    assert g["coffers"][A] == before + 1


# --- Carnival ----------------------------------------------------------------

def test_carnival_keeps_one_of_each_name_and_discards_the_duplicates():
    g = fresh()
    give_hand(g, A, ["Carnival"])
    give_deck(g, A, ["Copper", "Copper", "Estate", "Gold", "Silver"])
    assert play(g, A, "Carnival")[0]
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Estate", "Gold"]
    assert g["seats"][A]["discard"] == ["Copper"]
    assert g["seats"][A]["deck"] == ["Silver"]     # only 4 were revealed
    assert g["seats"][A]["aside"] == []


def test_carnival_with_four_of_a_kind_keeps_exactly_one():
    g = fresh()
    give_hand(g, A, ["Carnival"])
    give_deck(g, A, ["Copper"] * 4)
    assert play(g, A, "Carnival")[0]
    assert g["seats"][A]["hand"] == ["Copper"]
    assert g["seats"][A]["discard"] == ["Copper"] * 3


def test_carnival_with_one_card_to_reveal_puts_it_in_hand():
    g = fresh()
    give_hand(g, A, ["Carnival"])
    g["seats"][A]["deck"] = ["Gold"]
    g["seats"][A]["discard"] = []
    assert play(g, A, "Carnival")[0]
    assert g["seats"][A]["hand"] == ["Gold"]


def test_carnival_with_an_empty_deck_does_nothing():
    g = fresh()
    give_hand(g, A, ["Carnival"])
    g["seats"][A]["deck"] = []
    g["seats"][A]["discard"] = []
    assert play(g, A, "Carnival")[0]
    assert g["seats"][A]["hand"] == []
    assert g["pending"] == []


# --- Fairgrounds -------------------------------------------------------------

def test_fairgrounds_scores_two_vp_per_five_distinct_names():
    g = fresh()
    seat = g["seats"][A]
    seat["deck"], seat["hand"], seat["discard"], seat["in_play"] = [], [], [], []
    seat["deck"] = ["Fairgrounds", "Copper", "Silver", "Gold", "Estate"]
    assert engine._vp_of(g, A) == 1 + 2            # Estate 1, 5 names -> 2 VP
    seat["deck"] += ["Duchy", "Province", "Curse", "Village", "Smithy"]
    # 10 distinct names -> 4 VP, plus Estate 1 + Duchy 3 + Province 6 + Curse -1
    assert engine._vp_of(g, A) == 4 + 1 + 3 + 6 - 1


def test_fairgrounds_rounds_down_and_counts_by_name_not_by_copy():
    g = fresh()
    seat = g["seats"][A]
    seat["deck"], seat["hand"], seat["discard"], seat["in_play"] = [], [], [], []
    seat["deck"] = ["Fairgrounds"] + ["Copper"] * 20 + ["Silver", "Gold"]
    assert engine._vp_of(g, A) == 0                # only 4 distinct names
    seat["deck"].append("Estate")
    assert engine._vp_of(g, A) == 2 + 1            # 5 distinct -> 2 VP, +1 Estate


def test_two_fairgrounds_each_score():
    g = fresh()
    seat = g["seats"][A]
    seat["deck"], seat["hand"], seat["discard"], seat["in_play"] = [], [], [], []
    seat["deck"] = ["Fairgrounds", "Fairgrounds", "Copper", "Silver", "Gold",
                    "Estate"]
    # 5 distinct names (Fairgrounds/Copper/Silver/Gold/Estate) -> 2 VP each
    assert engine._vp_of(g, A) == 2 + 2 + 1


# --- Hamlet ------------------------------------------------------------------

def test_hamlet_both_discards_pay():
    g = fresh()
    give_hand(g, A, ["Hamlet", "Copper", "Estate"])
    give_deck(g, A, ["Silver"])
    assert play(g, A, "Hamlet")[0]
    assert g["actions"] == 1                       # cantrip so far
    assert frame(g)["data"]["kind"] == "action"
    assert decide(g, A, cards=["Copper"])[0]
    assert g["actions"] == 2
    assert frame(g)["data"]["kind"] == "buy"
    assert decide(g, A, cards=["Estate"])[0]
    assert g["buys"] == 2
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Estate"]


def test_hamlet_declining_both_pays_nothing():
    g = fresh()
    give_hand(g, A, ["Hamlet", "Copper"])
    give_deck(g, A, ["Silver"])
    assert play(g, A, "Hamlet")[0]
    assert decide(g, A, cards=[])[0]
    assert g["actions"] == 1
    assert decide(g, A, cards=[])[0]
    assert g["buys"] == 1
    assert g["seats"][A]["discard"] == []


def test_hamlets_second_offer_reads_the_hand_the_first_one_left():
    """The two offers are SEQUENTIAL. Pushed together they would both snapshot
    the same hand, and the second would then offer a card the first had already
    discarded — a decision the engine cannot apply."""
    g = fresh()
    give_hand(g, A, ["Hamlet", "Copper"])
    give_deck(g, A, ["Silver"])
    assert play(g, A, "Hamlet")[0]
    assert decide(g, A, cards=["Copper"])[0]       # spends the only discardable
    f = frame(g)
    assert f is not None and f["data"]["kind"] == "buy"
    assert "Copper" not in f["constraint"]["cards"]
    assert f["constraint"]["cards"] == ["Silver"]  # what the draw left


def test_hamlet_with_nothing_left_to_discard_stops_asking():
    g = fresh()
    give_hand(g, A, ["Hamlet"])
    g["seats"][A]["deck"] = []
    g["seats"][A]["discard"] = []
    assert play(g, A, "Hamlet")[0]
    assert g["pending"] == []                      # nothing to offer at all
    assert g["actions"] == 1 and g["buys"] == 1


# --- Hunting Party -----------------------------------------------------------

def test_hunting_party_digs_for_a_name_not_in_hand():
    g = fresh()
    give_hand(g, A, ["Hunting Party", "Copper"])
    give_deck(g, A, ["Estate", "Copper", "Copper", "Gold", "Silver"])
    assert play(g, A, "Hunting Party")[0]
    # +1 Card takes the Estate; hand is then {Copper, Estate}, so the dig skips
    # the two Coppers and stops on the Gold
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Estate", "Gold"]
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Copper"]
    assert g["seats"][A]["deck"] == ["Silver"]
    assert g["actions"] == 1


def test_hunting_party_that_finds_nothing_discards_the_whole_deck():
    g = fresh()
    give_hand(g, A, ["Hunting Party", "Copper"])
    g["seats"][A]["deck"] = ["Copper", "Copper", "Copper"]
    g["seats"][A]["discard"] = []
    assert play(g, A, "Hunting Party")[0]
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Copper"]
    assert g["seats"][A]["discard"] == ["Copper", "Copper"]
    assert g["seats"][A]["aside"] == []


# --- Joust -------------------------------------------------------------------

def test_joust_sets_the_province_aside_and_gains_any_reward_to_hand():
    g = fresh(kingdom=KA)
    give_hand(g, A, ["Joust", "Province"])
    give_deck(g, A, ["Copper"])
    assert play(g, A, "Joust")[0]
    assert g["coins"] == 1 and g["actions"] == 1
    assert decide(g, A, cards=["Province"])[0]
    f = frame(g)
    assert f["kind"] == "choose_pile"
    assert sorted(f["constraint"]["piles"]) == sorted(engine.REWARDS)
    assert decide(g, A, pile="Renown")[0]
    assert "Renown" in g["seats"][A]["hand"]       # GAINED TO YOUR HAND
    assert g["seats"][A]["cleanup_aside"] == ["Province"]
    assert "Province" not in g["seats"][A]["in_play"]


def test_the_set_aside_province_is_discarded_in_cleanup():
    g = fresh(kingdom=KA)
    give_hand(g, A, ["Joust", "Province"])
    give_deck(g, A, ["Copper"] * 8)
    assert play(g, A, "Joust")[0]
    decide(g, A, cards=["Province"])
    decide(g, A, pile="Courser")
    assert mv(g, A, {"type": "end_phase"})[0]      # action -> buy
    assert mv(g, A, {"type": "end_phase"})[0]      # buy -> clean-up
    assert g["seats"][A]["cleanup_aside"] == []
    assert "Province" in g["seats"][A]["discard"]


def test_joust_may_decline_and_keeps_the_province():
    g = fresh(kingdom=KA)
    give_hand(g, A, ["Joust", "Province"])
    give_deck(g, A, ["Copper"])
    assert play(g, A, "Joust")[0]
    assert decide(g, A, cards=[])[0]
    assert "Province" in g["seats"][A]["hand"]
    assert g["pending"] == []


def test_joust_without_a_province_offers_nothing():
    g = fresh(kingdom=KA)
    give_hand(g, A, ["Joust", "Copper"])
    give_deck(g, A, ["Copper"])
    assert play(g, A, "Joust")[0]
    assert g["pending"] == []


def test_the_reward_pile_exists_only_with_joust_and_is_never_buyable():
    g = fresh(kingdom=KA)                          # Joust IS in this kingdom
    for r in engine.REWARDS:
        assert r in g["piles"] and r not in g["supply"]
        assert engine.is_supply_pile(g, r) is False
    g2 = fresh(kingdom=KB)                         # no Joust
    for r in engine.REWARDS:
        assert r not in g2["piles"]
    g["phase"] = "buy"
    g["coins"] = 20
    assert {"type": "buy", "card": "Coronet"} not in engine.legal_moves(g, A)
    ok, err = mv(g, A, {"type": "buy", "card": "Coronet"})
    assert not ok and err == "no such pile"


@pytest.mark.parametrize("players,each", [((A, B), 1), ((A, B, C), 2)])
def test_the_reward_pile_is_one_of_each_at_two_players_and_two_otherwise(players, each):
    """"In a 2-player game, use one of each, otherwise two of each.\""""
    g = fresh(players=players, kingdom=KA)
    for r in engine.REWARDS:
        assert engine.pile_count(g, r) == each


def test_an_emptied_reward_pile_does_not_end_the_game():
    g = fresh(kingdom=KA)
    for r in engine.REWARDS:
        while engine.pile_count(g, r):
            engine.gain_from(g, A, r)
    assert engine.count_empty_piles(g) == 0


# --- Menagerie ---------------------------------------------------------------

def test_menagerie_all_different_draws_three():
    g = fresh()
    give_hand(g, A, ["Menagerie", "Copper", "Estate", "Silver"])
    give_deck(g, A, ["Gold"] * 4)
    assert play(g, A, "Menagerie")[0]
    assert g["seats"][A]["hand"].count("Gold") == 3
    assert g["actions"] == 1


def test_menagerie_a_duplicate_draws_one():
    g = fresh()
    give_hand(g, A, ["Menagerie", "Copper", "Copper"])
    give_deck(g, A, ["Gold"] * 4)
    assert play(g, A, "Menagerie")[0]
    assert g["seats"][A]["hand"].count("Gold") == 1


def test_menagerie_on_an_empty_hand_draws_three():
    """"If you have no cards in your hand, you draw 3 cards" — the empty set is
    vacuously all-different, and reading it the other way is the obvious bug."""
    g = fresh()
    give_hand(g, A, ["Menagerie"])
    give_deck(g, A, ["Gold"] * 4)
    assert play(g, A, "Menagerie")[0]
    assert g["seats"][A]["hand"].count("Gold") == 3


def test_menagerie_does_not_count_itself_it_is_already_in_play():
    g = fresh()
    give_hand(g, A, ["Menagerie", "Menagerie"])
    give_deck(g, A, ["Gold"] * 4)
    assert play(g, A, "Menagerie")[0]
    # the played copy is in play; the hand holds one Menagerie -> all different
    assert g["seats"][A]["hand"].count("Gold") == 3


# --- Merchant Guild ----------------------------------------------------------

def _end_buy_phase(g, pid):
    return mv(g, pid, {"type": "end_phase"})


def test_merchant_guild_pays_one_coffers_per_card_gained_in_the_buy_phase():
    g = fresh()
    give_hand(g, A, ["Merchant Guild"])
    assert play(g, A, "Merchant Guild")[0]
    assert g["buys"] == 2 and g["coins"] == 1
    before = g["coffers"][A]
    g["phase"] = "buy"
    g["coins"] = 10
    assert mv(g, A, {"type": "buy", "card": "Copper"})[0]
    assert mv(g, A, {"type": "buy", "card": "Copper"})[0]
    assert g["coffers"][A] == before, "the tokens must not arrive during the phase"
    assert _end_buy_phase(g, A)[0]
    assert g["coffers"][A] == before + 2


def test_merchant_guild_counts_gains_that_were_not_buys():
    """"It counts all cards gained (not just bought) in your Buy phase.\""""
    g = fresh()
    give_hand(g, A, ["Merchant Guild"])
    assert play(g, A, "Merchant Guild")[0]
    before = g["coffers"][A]
    g["phase"] = "buy"
    engine.gain(g, A, "Silver")
    engine._drive(g)
    assert _end_buy_phase(g, A)[0]
    assert g["coffers"][A] == before + 1


def test_merchant_guild_counts_gains_from_before_it_was_played():
    """"If you play Merchant Guild in your Buy phase, any cards you gained
    previously in the Buy phase still count.\""""
    g = fresh()
    g["phase"] = "buy"
    g["coins"] = 10
    assert mv(g, A, {"type": "buy", "card": "Copper"})[0]
    give_hand(g, A, ["Merchant Guild"])
    before = g["coffers"][A]
    engine.play_action_card(g, A, "Merchant Guild")
    engine._drive(g)
    assert _end_buy_phase(g, A)[0]
    assert g["coffers"][A] == before + 1


def test_merchant_guild_is_cumulative_per_play():
    g = fresh()
    give_hand(g, A, ["Merchant Guild", "Merchant Guild"])
    g["actions"] = 2
    assert play(g, A, "Merchant Guild")[0]
    assert play(g, A, "Merchant Guild")[0]
    before = g["coffers"][A]
    g["phase"] = "buy"
    g["coins"] = 10
    assert mv(g, A, {"type": "buy", "card": "Copper"})[0]
    assert _end_buy_phase(g, A)[0]
    assert g["coffers"][A] == before + 2          # one payout per play


def test_merchant_guild_with_no_gains_pays_nothing_and_prompts_nothing():
    g = fresh()
    give_hand(g, A, ["Merchant Guild"])
    assert play(g, A, "Merchant Guild")[0]
    before = g["coffers"][A]
    g["phase"] = "buy"
    assert _end_buy_phase(g, A)[0]
    assert g["coffers"][A] == before


def test_merchant_guilds_tokens_cannot_be_spent_the_turn_they_arrive():
    """The card was REWRITTEN for exactly this: the tokens land at the end of
    the Buy phase, which is after the last moment you could spend them."""
    g = fresh()
    give_hand(g, A, ["Merchant Guild"])
    assert play(g, A, "Merchant Guild")[0]
    g["phase"] = "buy"
    g["coins"] = 10
    assert mv(g, A, {"type": "buy", "card": "Copper"})[0]
    got = g["coffers"][A]
    assert _end_buy_phase(g, A)[0]
    assert g["coffers"][A] > got
    assert g["turn"] == B, "the turn ended with the payout"


# --- Plaza -------------------------------------------------------------------

def test_plaza_discards_a_treasure_for_a_coffers():
    g = fresh()
    give_hand(g, A, ["Plaza", "Copper", "Estate"])
    give_deck(g, A, ["Silver"])
    before = g["coffers"][A]
    assert play(g, A, "Plaza")[0]
    assert g["actions"] == 2
    f = frame(g)
    assert f["constraint"]["cards"] == ["Copper", "Silver"]   # Estate excluded
    assert decide(g, A, cards=["Copper"])[0]
    assert g["coffers"][A] == before + 1
    assert g["seats"][A]["discard"] == ["Copper"]


def test_plaza_may_decline():
    g = fresh()
    give_hand(g, A, ["Plaza", "Copper"])
    give_deck(g, A, ["Estate"])
    before = g["coffers"][A]
    assert play(g, A, "Plaza")[0]
    assert decide(g, A, cards=[])[0]
    assert g["coffers"][A] == before


def test_plaza_with_no_treasure_offers_nothing():
    g = fresh()
    give_hand(g, A, ["Plaza", "Estate"])
    give_deck(g, A, ["Estate"])
    assert play(g, A, "Plaza")[0]
    assert g["pending"] == []


# --- Remake ------------------------------------------------------------------

def test_remake_does_it_twice_gaining_exactly_one_more_each_time():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Remake", "Estate", "Moat"])
    assert play(g, A, "Remake")[0]
    assert decide(g, A, cards=["Estate"])[0]       # $2 -> gain exactly $3
    f = frame(g)
    assert f["kind"] == "choose_pile"
    assert all(engine.cost(g, p) == 3 for p in f["constraint"]["piles"])
    assert decide(g, A, pile="Silver")[0]
    # ...and now the SECOND remake
    f = frame(g)
    assert f["card"] == "Remake" and f["kind"] == "choose_cards"
    assert decide(g, A, cards=["Moat"])[0]         # $2 -> gain exactly $3
    f = frame(g)
    assert all(engine.cost(g, p) == 3 for p in f["constraint"]["piles"])
    assert decide(g, A, pile="Village")[0]
    assert "Silver" in g["seats"][A]["discard"]
    assert "Village" in g["seats"][A]["discard"]
    assert sorted(g["trash"]) == ["Estate", "Moat"]
    assert g["pending"] == []


def test_remake_with_one_card_in_hand_only_remakes_once():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Remake", "Estate"])
    assert play(g, A, "Remake")[0]
    assert decide(g, A, cards=["Estate"])[0]
    assert decide(g, A, pile="Silver")[0]
    assert g["pending"] == [], "nothing left in hand to remake"
    assert g["trash"] == ["Estate"]


def test_remake_trashing_a_copper_gains_nothing_because_no_pile_costs_one():
    """"Exactly $1 more" is exact: nothing in Dominion costs $1, so remaking a
    Copper trashes it and gains nothing at all."""
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Remake", "Copper"])
    assert play(g, A, "Remake")[0]
    assert decide(g, A, cards=["Copper"])[0]
    assert g["trash"] == ["Copper"]
    assert g["seats"][A]["discard"] == []
    assert g["pending"] == []


def test_remake_gains_nothing_when_no_pile_costs_exactly_one_more():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Remake", "Province"])
    assert play(g, A, "Remake")[0]
    assert decide(g, A, cards=["Province"])[0]     # $8 -> nothing costs $9
    assert g["trash"] == ["Province"]
    assert g["pending"] == []


# --- Shop --------------------------------------------------------------------

def test_shop_plays_an_action_with_no_copy_in_play():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Shop", "Village", "Smithy"])
    give_deck(g, A, ["Gold"] * 5)
    assert play(g, A, "Shop")[0]
    assert g["coins"] == 1
    f = frame(g)
    assert sorted(f["constraint"]["cards"]) == ["Smithy", "Village"]
    assert decide(g, A, cards=["Village"])[0]
    assert "Village" in g["seats"][A]["in_play"]


def test_shop_never_offers_a_second_shop_because_it_is_itself_in_play():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Shop", "Shop", "Village"])
    give_deck(g, A, ["Gold"] * 5)
    assert play(g, A, "Shop")[0]
    assert frame(g)["constraint"]["cards"] == ["Village"]


def test_shop_excludes_a_card_already_in_play():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Shop", "Village"])
    g["seats"][A]["in_play"] = ["Village"]
    give_deck(g, A, ["Gold"] * 5)
    assert play(g, A, "Shop")[0]
    assert g["pending"] == []                      # nothing left to offer


def test_shop_counts_the_duration_zone_as_cards_in_play():
    """CARDS YOU HAVE IN PLAY is not in_play alone — a Duration sitting in its
    own zone is still on the table."""
    g = fresh(kingdom=KB + ["Wharf"])
    give_hand(g, A, ["Shop", "Wharf"])
    g["seats"][A]["duration"] = [{"card": "Wharf", "fx": [], "riders": []}]
    give_deck(g, A, ["Gold"] * 5)
    assert play(g, A, "Shop")[0]
    assert g["pending"] == []


def test_shop_may_decline():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Shop", "Village"])
    give_deck(g, A, ["Gold"] * 5)
    assert play(g, A, "Shop")[0]
    assert decide(g, A, cards=[])[0]
    assert "Village" in g["seats"][A]["hand"]


# --- Soothsayer --------------------------------------------------------------

def test_soothsayer_gold_curse_and_the_draw_only_for_those_cursed():
    g = fresh(kingdom=KB, players=(A, B, C))
    give_hand(g, A, ["Soothsayer"])
    g["seats"][B]["deck"] = ["Gold"]
    g["seats"][C]["deck"] = ["Gold"]
    assert play(g, A, "Soothsayer")[0]
    assert "Gold" in g["seats"][A]["discard"]
    for p in (B, C):
        assert "Curse" in g["seats"][p]["discard"]
        assert g["seats"][p]["hand"].count("Gold") == 1


def test_soothsayer_no_curses_left_means_no_draw():
    g = fresh(kingdom=KB)
    g["supply"]["Curse"] = 0
    give_hand(g, A, ["Soothsayer"])
    g["seats"][B]["hand"] = []
    g["seats"][B]["deck"] = ["Gold"]
    assert play(g, A, "Soothsayer")[0]
    assert g["seats"][B]["hand"] == [], "no Curse gained, so no card drawn"


def test_soothsayer_gives_curses_even_with_no_gold_left():
    g = fresh(kingdom=KB)
    g["supply"]["Gold"] = 0
    give_hand(g, A, ["Soothsayer"])
    assert play(g, A, "Soothsayer")[0]
    assert "Gold" not in g["seats"][A]["discard"]
    assert "Curse" in g["seats"][B]["discard"]


def test_soothsayer_is_blocked_by_a_moat():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Soothsayer"])
    g["seats"][B]["hand"] = ["Moat"]
    assert play(g, A, "Soothsayer")[0]
    f = frame(g)
    assert f["pid"] == B and f["kind"] == "choose_option"
    assert decide(g, B, ids=["react:Moat"])[0]
    assert "Curse" not in g["seats"][B]["discard"]


# --- Rewards: Courser --------------------------------------------------------

def test_courser_picks_two_different_options_and_does_them_in_printed_order():
    g = fresh(kingdom=KA)
    g["seats"][A]["hand"] = ["Courser"]
    give_deck(g, A, ["Gold"] * 4)
    assert play(g, A, "Courser")[0]
    f = frame(g)
    assert f["constraint"]["pick"] == 2 and f["constraint"]["distinct"] is True
    assert [o["id"] for o in f["constraint"]["options"]] == [
        "cards", "actions", "coins", "silvers"]
    assert decide(g, A, ids=["coins", "cards"])[0]
    assert g["seats"][A]["hand"].count("Gold") == 2
    assert g["coins"] == 2


def test_courser_can_gain_four_silvers():
    g = fresh(kingdom=KA)
    g["seats"][A]["hand"] = ["Courser"]
    assert play(g, A, "Courser")[0]
    assert decide(g, A, ids=["silvers", "actions"])[0]
    assert g["seats"][A]["discard"].count("Silver") == 4
    assert g["actions"] == 2


# --- Rewards: Demesne --------------------------------------------------------

def test_demesne_gives_actions_buys_and_a_gold():
    g = fresh(kingdom=KA)
    g["seats"][A]["hand"] = ["Demesne"]
    assert play(g, A, "Demesne")[0]
    assert g["actions"] == 2 and g["buys"] == 3
    assert "Gold" in g["seats"][A]["discard"]


def test_demesne_scores_one_vp_per_gold():
    g = fresh(kingdom=KA)
    seat = g["seats"][A]
    seat["deck"], seat["hand"], seat["discard"], seat["in_play"] = [], [], [], []
    seat["deck"] = ["Demesne", "Gold", "Gold", "Gold"]
    assert engine._vp_of(g, A) == 3
    seat["deck"] += ["Demesne"]
    assert engine._vp_of(g, A) == 6                # both Demesnes count them


# --- Rewards: Housecarl ------------------------------------------------------

def test_housecarl_draws_one_per_distinct_action_in_play_counting_itself():
    g = fresh(kingdom=KB)
    g["seats"][A]["hand"] = ["Housecarl"]
    g["seats"][A]["in_play"] = ["Village", "Village", "Smithy", "Copper"]
    give_deck(g, A, ["Gold"] * 6)
    assert play(g, A, "Housecarl")[0]
    # distinct ACTIONS in play: Village, Smithy, Housecarl = 3 (Copper is not)
    assert g["seats"][A]["hand"].count("Gold") == 3


def test_housecarl_alone_draws_one():
    g = fresh(kingdom=KB)
    g["seats"][A]["hand"] = ["Housecarl"]
    g["seats"][A]["in_play"] = []
    give_deck(g, A, ["Gold"] * 6)
    assert play(g, A, "Housecarl")[0]
    assert g["seats"][A]["hand"].count("Gold") == 1


# --- Rewards: Huge Turnip ----------------------------------------------------

def test_huge_turnip_counts_coffers_after_its_own_two():
    g = fresh(kingdom=KA)
    g["coffers"][A] = 3
    g["seats"][A]["hand"] = ["Huge Turnip"]
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Huge Turnip"})[0]
    assert g["coffers"][A] == 5
    assert g["coins"] == 5, "counted AFTER the +2, not before"


def test_huge_turnip_from_zero_gives_two():
    g = fresh(kingdom=KB)
    g["coffers"][A] = 0
    g["seats"][A]["hand"] = ["Huge Turnip"]
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Huge Turnip"})[0]
    assert g["coins"] == 2 and g["coffers"][A] == 2


# --- Rewards: Renown ---------------------------------------------------------

def test_renown_is_a_turn_scoped_two_dollar_discount():
    g = fresh(kingdom=KB)
    g["seats"][A]["hand"] = ["Renown"]
    assert engine.cost(g, "Gold") == 6
    assert play(g, A, "Renown")[0]
    assert g["buys"] == 2
    assert engine.cost(g, "Gold") == 4
    assert engine.cost(g, "Copper") == 0           # never below $0


def test_renown_is_cumulative_and_survives_leaving_play():
    g = fresh(kingdom=KB)
    g["seats"][A]["hand"] = ["Renown", "Renown"]
    g["actions"] = 2
    assert play(g, A, "Renown")[0]
    assert play(g, A, "Renown")[0]
    assert engine.cost(g, "Gold") == 2
    g["seats"][A]["in_play"] = []                  # trashed from play
    assert engine.cost(g, "Gold") == 2, "turn-scoped, not while-in-play"


def test_renowns_discount_is_gone_next_turn():
    g = fresh(kingdom=KB)
    g["seats"][A]["hand"] = ["Renown"]
    assert play(g, A, "Renown")[0]
    assert g["phase"] == "buy", "an empty hand auto-advances the phase"
    assert mv(g, A, {"type": "end_phase"})[0]      # ...so this ends the TURN
    assert g["turn"] == B
    assert engine.cost(g, "Gold") == 6
