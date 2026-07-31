"""Prosperity batch-A card tests — Anvil, Bank, Bishop, City, Expand, Forge,
Grand Market, Monument, Quarry, Rabble, Vault, War Chest, Worker's Village.

Positions are arranged by mutating the game dict directly (the repo's
board-fixture idiom). give_hand breaks card conservation, so no test here
asserts the census invariant (test_soak owns that).

Headline rulings pinned here (prosperity-spec.md):
  * Bishop's VP payout uses the trashed card's CURRENT cost (Bridge/Quarry
    reduce it), round down; opponents' trash is optional and pays them nothing.
  * Forge's total is the sum at trash time — the empty set is $0 (Copper /
    Curse), and with no exactly-matching non-empty pile the trash still stands.
  * Quarry (2022) is a TURN-scoped discount: it survives the Quarry being
    trashed from play, stacks per play, and dies with the turn.
  * Grand Market's Copper gate binds buying only — gaining bypasses it.
  * War Chest's named-card list accumulates across plays in the same turn.
"""

from games.dontminion import engine

A, B = "alice", "bob"

# Pinned kingdom = exactly this batch's 13 cards (the forced-kingdom test seam).
KA = ["Anvil", "Bank", "Bishop", "City", "Expand", "Forge", "Grand Market",
      "Monument", "Quarry", "Rabble", "Vault", "War Chest", "Worker's Village"]
# kingdom= mixes sets freely: Militia (a cheap Action to price), Moat (attack
# reaction fixture), Bridge (cost-reduction fixture).
KX = KA + ["Militia", "Moat", "Bridge"]


def fresh(players=(A, B), seed=42, kingdom=tuple(KA)):
    return engine.new_game(list(players), ["prosperity"], seed=seed,
                           kingdom=list(kingdom))


def give_hand(g, pid, cards):
    """Force a hand to exactly `cards` (conservation not preserved)."""
    g["seats"][pid]["hand"] = list(cards)


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def decide(g, pid, **payload):
    return engine.apply_move(g, pid, {"type": "decision", **payload})


def end_turn(g, pid):
    """Drive pid's turn to its end — 1 or 2 end_phase moves depending on
    whether the action phase already auto-advanced."""
    guard = 0
    while g["turn"] == pid and not g["over"]:
        ok, err = mv(g, pid, {"type": "end_phase"})
        assert ok, err
        guard += 1
        assert guard < 4, "end_turn did not terminate"


def to_buy(g):
    """Stage-a-hand fixtures enter the buy phase directly (treasure plays)."""
    g["phase"] = "buy"


# --- Worker's Village (vanilla) ----------------------------------------------

def test_workers_village():
    g = fresh()
    give_hand(g, A, ["Worker's Village"])
    g["seats"][A]["deck"] = ["Silver", "Gold"]
    assert mv(g, A, {"type": "play_action", "card": "Worker's Village"})[0]
    assert g["seats"][A]["hand"] == ["Silver"]
    assert g["actions"] == 2 and g["buys"] == 2 and g["coins"] == 0


# --- Monument ----------------------------------------------------------------

def test_monument_vp_tokens_and_score():
    g = fresh()
    give_hand(g, A, ["Monument"])
    # baseline AFTER staging — give_hand may have dropped dealt Estates
    base_vp = engine.score_game(g)[A]["vp"]
    assert mv(g, A, {"type": "play_action", "card": "Monument"})[0]
    assert g["coins"] == 2
    assert g["vp_tokens"][A] == 1
    # tokens flow into the live VP map and into score_game
    assert g["vp"][A] == base_vp + 1
    assert engine.score_game(g)[A]["vp"] == base_vp + 1


# --- City --------------------------------------------------------------------

def test_city_no_empty_piles():
    g = fresh()
    give_hand(g, A, ["City"])
    g["seats"][A]["deck"] = ["Silver", "Gold"]
    assert mv(g, A, {"type": "play_action", "card": "City"})[0]
    assert g["seats"][A]["hand"] == ["Silver"]
    assert g["actions"] == 2 and g["buys"] == 1 and g["coins"] == 0


def test_city_scales_with_empty_piles():
    # one empty pile -> +1 extra Card; two -> also +1 Buy and +$1
    g = fresh()
    give_hand(g, A, ["City"])
    g["seats"][A]["deck"] = ["Silver", "Gold", "Estate"]
    g["supply"]["Curse"] = 0
    assert mv(g, A, {"type": "play_action", "card": "City"})[0]
    assert sorted(g["seats"][A]["hand"]) == ["Gold", "Silver"]
    assert g["actions"] == 2 and g["buys"] == 1 and g["coins"] == 0

    g = fresh()
    give_hand(g, A, ["City"])
    g["seats"][A]["deck"] = ["Silver", "Gold", "Estate"]
    g["supply"]["Curse"] = 0
    g["supply"]["Anvil"] = 0
    assert mv(g, A, {"type": "play_action", "card": "City"})[0]
    assert sorted(g["seats"][A]["hand"]) == ["Gold", "Silver"]
    assert g["actions"] == 2 and g["buys"] == 2 and g["coins"] == 1


# --- Bank --------------------------------------------------------------------

def test_bank_counts_treasures_in_play_including_itself():
    g = fresh()
    give_hand(g, A, ["Copper", "Copper", "Bank"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Copper"})[0]
    assert mv(g, A, {"type": "play_treasure", "card": "Copper"})[0]
    assert g["coins"] == 2
    assert mv(g, A, {"type": "play_treasure", "card": "Bank"})[0]
    assert g["coins"] == 5                              # $0 printed + $3 counted


def test_bank_counts_duration_zone_treasures():
    # A persisting Treasure-Duration (Astrolabe) is still "in play"; its
    # non-Treasure rider (Throne Room) is not counted.
    g = fresh()
    g["seats"][A]["duration"] = [{"card": "Astrolabe", "fx": [],
                                  "riders": ["Throne Room"]}]
    give_hand(g, A, ["Bank"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Bank"})[0]
    assert g["coins"] == 2                              # Bank + Astrolabe


def test_play_all_treasures_plays_bank_last_whatever_hand_order():
    """Bank's value depends on what is already in play, and hand order is
    arbitrary from the player's side — leaving it where it fell silently cost
    up to 40% of the turn's coins ($6 vs $10 on this hand)."""
    hand = ["Bank", "Copper", "Copper", "Copper", "Silver"]
    for order in (hand, list(reversed(hand))):
        g = fresh()
        give_hand(g, A, order)
        to_buy(g)
        assert mv(g, A, {"type": "play_all_treasures"})[0]
        assert g["seats"][A]["in_play"][-1] == "Bank"    # always last
        assert g["coins"] == 10                          # 3 + 2 + $5 Bank
    # and the non-order-sensitive treasures keep hand order (replay stability)
    assert g["seats"][A]["in_play"][:-1] == ["Silver", "Copper", "Copper", "Copper"]


def test_autoplay_last_membership_is_justified():
    """Membership means "later is never worse". A treasure that might want to
    go EARLY belongs in MANUAL_TREASURES instead — the button must not choose
    for the player. Guards the two registries against overlap too."""
    assert engine.autoplay_last() == {"Bank"}
    assert not (engine.autoplay_last() & engine.manual_treasures())


# --- Anvil -------------------------------------------------------------------

def test_anvil_discard_treasure_to_gain_up_to_4():
    g = fresh()
    give_hand(g, A, ["Anvil", "Copper", "Estate"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Anvil"})[0]
    assert g["coins"] == 1                              # printed $1 banked first
    c = g["pending"][-1]["constraint"]
    assert g["pending_pid"] == A and g["pending_kind"] == "choose_cards"
    assert c["cards"] == ["Copper"]                     # Treasures only
    assert c["min"] == 0 and c["max"] == 1
    assert decide(g, A, cards=["Copper"])[0]
    assert g["pending_kind"] == "choose_pile"
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Silver" in piles and "Monument" in piles    # cost <= 4
    assert "Gold" not in piles and "City" not in piles  # cost > 4
    assert decide(g, A, pile="Silver")[0]
    assert g["seats"][A]["discard"] == ["Copper", "Silver"]
    assert g["supply"]["Silver"] == 39


def test_anvil_no_discard_no_gain():
    g = fresh()
    give_hand(g, A, ["Anvil", "Copper"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Anvil"})[0]
    assert decide(g, A, cards=[])[0]                    # decline the discard
    assert g["pending_pid"] is None
    assert g["seats"][A]["discard"] == []
    # no Treasure in hand at all -> no prompt either
    g = fresh()
    give_hand(g, A, ["Anvil", "Estate"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Anvil"})[0]
    assert g["coins"] == 1 and g["pending_pid"] is None


def test_manual_treasures_skipped_by_play_all():
    g = fresh()
    give_hand(g, A, ["Anvil", "War Chest", "Copper", "Copper"])
    to_buy(g)
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert g["coins"] == 2 and g["pending_pid"] is None
    assert sorted(g["seats"][A]["hand"]) == ["Anvil", "War Chest"]


# --- Bishop ------------------------------------------------------------------

def test_bishop_trash_payout_and_opponent_option():
    g = fresh()
    give_hand(g, A, ["Bishop", "Silver"])
    give_hand(g, B, ["Estate", "Copper"])
    assert mv(g, A, {"type": "play_action", "card": "Bishop"})[0]
    assert g["coins"] == 1 and g["vp_tokens"][A] == 1
    c = g["pending"][-1]["constraint"]
    assert g["pending_pid"] == A                        # own trash first
    assert c["min"] == 1 and c["max"] == 1 and c["cards"] == ["Silver"]
    assert decide(g, A, cards=["Silver"])[0]            # $3 -> +1 VP
    assert g["trash"] == ["Silver"] and g["vp_tokens"][A] == 2
    # then the opponent MAY trash (0..1) — and gets no VP for it
    c = g["pending"][-1]["constraint"]
    assert g["pending_pid"] == B and c["min"] == 0 and c["max"] == 1
    assert sorted(c["cards"]) == ["Copper", "Estate"]
    assert decide(g, B, cards=["Estate"])[0]
    assert g["trash"] == ["Silver", "Estate"]
    assert g["vp_tokens"][B] == 0 and g["pending_pid"] is None


def test_bishop_payout_uses_current_cost():
    # Bridge reduction: Gold $6 -> $4 at trash time -> +2 VP (not +3)
    g = fresh(kingdom=KX)
    give_hand(g, A, ["Bishop", "Gold"])
    give_hand(g, B, [])
    g["turn_ctx"]["bridges"] = 2
    assert mv(g, A, {"type": "play_action", "card": "Bishop"})[0]
    assert decide(g, A, cards=["Gold"])[0]
    assert g["vp_tokens"][A] == 3                       # 1 + 4//2
    # Quarry reduction hits Actions: Militia $4 -> $2 -> +1 VP (not +2)
    g = fresh(kingdom=KX)
    give_hand(g, A, ["Bishop", "Militia"])
    give_hand(g, B, [])
    g["turn_ctx"]["quarries"] = 1
    assert mv(g, A, {"type": "play_action", "card": "Bishop"})[0]
    assert decide(g, A, cards=["Militia"])[0]
    assert g["vp_tokens"][A] == 2                       # 1 + 2//2


def test_bishop_empty_hand_still_pays_and_offers_opponents():
    g = fresh()
    give_hand(g, A, ["Bishop"])
    give_hand(g, B, ["Copper"])
    assert mv(g, A, {"type": "play_action", "card": "Bishop"})[0]
    assert g["coins"] == 1 and g["vp_tokens"][A] == 1
    assert g["pending_pid"] == B                        # no own trash frame
    assert decide(g, B, cards=[])[0]                    # opponent may decline
    assert g["trash"] == [] and g["pending_pid"] is None


# --- Expand ------------------------------------------------------------------

def test_expand_trash_then_gain_up_to_plus_3():
    g = fresh()
    give_hand(g, A, ["Expand", "Estate"])
    assert mv(g, A, {"type": "play_action", "card": "Expand"})[0]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 1 and c["max"] == 1 and c["purpose"] == "trash"
    assert decide(g, A, cards=["Estate"])[0]
    assert g["trash"] == ["Estate"]
    piles = g["pending"][-1]["constraint"]["piles"]     # cost <= 2+3
    assert "Duchy" in piles and "Vault" in piles
    assert "Gold" not in piles and "Province" not in piles
    assert decide(g, A, pile="Duchy")[0]
    assert g["seats"][A]["discard"] == ["Duchy"]


def test_expand_empty_hand_does_nothing():
    g = fresh()
    give_hand(g, A, ["Expand"])
    assert mv(g, A, {"type": "play_action", "card": "Expand"})[0]
    assert g["pending_pid"] is None
    assert g["trash"] == [] and g["seats"][A]["discard"] == []


# --- Forge -------------------------------------------------------------------

def test_forge_multi_trash_exact_total():
    g = fresh()
    give_hand(g, A, ["Forge", "Estate", "Silver", "Copper"])
    assert mv(g, A, {"type": "play_action", "card": "Forge"})[0]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 0 and c["max"] == 3
    assert decide(g, A, cards=["Estate", "Silver"])[0]  # $2 + $3 = $5 exactly
    assert sorted(g["trash"]) == ["Estate", "Silver"]
    piles = g["pending"][-1]["constraint"]["piles"]
    assert sorted(piles) == ["City", "Duchy", "Rabble", "Vault", "War Chest"]
    assert decide(g, A, pile="Duchy")[0]
    assert g["seats"][A]["discard"] == ["Duchy"]


def test_forge_zero_total_gains_a_zero_cost_card():
    # trashing nothing -> the empty sum is $0 and the gain is still mandatory
    g = fresh()
    give_hand(g, A, ["Forge", "Estate"])
    assert mv(g, A, {"type": "play_action", "card": "Forge"})[0]
    assert decide(g, A, cards=[])[0]
    assert sorted(g["pending"][-1]["constraint"]["piles"]) == ["Copper", "Curse"]
    assert decide(g, A, pile="Copper")[0]
    assert g["trash"] == [] and g["seats"][A]["discard"] == ["Copper"]
    # an empty hand skips the (pointless) trash prompt but still offers the gain
    g = fresh()
    give_hand(g, A, ["Forge"])
    assert mv(g, A, {"type": "play_action", "card": "Forge"})[0]
    assert g["pending_kind"] == "choose_pile"
    assert sorted(g["pending"][-1]["constraint"]["piles"]) == ["Copper", "Curse"]


def test_forge_no_eligible_pile_trash_still_happened():
    g = fresh()
    g["supply"]["Copper"] = 0
    g["supply"]["Curse"] = 0                            # no $0 pile left
    give_hand(g, A, ["Forge", "Copper"])
    assert mv(g, A, {"type": "play_action", "card": "Forge"})[0]
    assert decide(g, A, cards=["Copper"])[0]            # total $0
    assert g["pending_pid"] is None
    assert g["trash"] == ["Copper"]                     # the trash stands
    assert g["seats"][A]["discard"] == []               # ... but nothing gained


# --- Grand Market ------------------------------------------------------------

def test_grand_market_vanilla_play():
    g = fresh()
    give_hand(g, A, ["Grand Market"])
    g["seats"][A]["deck"] = ["Silver", "Gold"]
    assert mv(g, A, {"type": "play_action", "card": "Grand Market"})[0]
    assert g["seats"][A]["hand"] == ["Silver"]
    assert g["actions"] == 1 and g["buys"] == 2 and g["coins"] == 2


def test_grand_market_gate_blocks_buy_not_gain():
    g = fresh()
    give_hand(g, A, [])
    to_buy(g)
    g["coins"] = 6
    g["seats"][A]["in_play"] = ["Copper"]
    ok, err = mv(g, A, {"type": "buy", "card": "Grand Market"})
    assert not ok and err == "can't buy Grand Market with Coppers in play"
    # legal_moves never offers the gated buy (other buys stay available)
    moves = engine.legal_moves(g, A)
    assert {"type": "buy", "card": "Grand Market"} not in moves
    assert {"type": "buy", "card": "Gold"} in moves
    # gaining bypasses the gate entirely (Coppers still in play)
    assert engine.gain(g, A, "Grand Market")
    assert g["seats"][A]["discard"] == ["Grand Market"]
    # with no Copper in play the buy goes through
    g["seats"][A]["in_play"] = []
    assert mv(g, A, {"type": "buy", "card": "Grand Market"})[0]
    assert g["coins"] == 0
    assert g["seats"][A]["discard"] == ["Grand Market", "Grand Market"]


# --- Quarry ------------------------------------------------------------------

def test_quarry_discount_survives_trash_stacks_and_ends_with_turn():
    g = fresh(kingdom=KX)
    give_hand(g, A, ["Quarry", "Quarry"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Quarry"})[0]
    assert g["coins"] == 1
    assert engine.cost(g, "Militia") == 2               # Action: $4 -> $2
    assert engine.cost(g, "Silver") == 3                # non-Action untouched
    # 2022 semantics: the discount is turn-scoped, NOT while-in-play — it
    # survives the Quarry being trashed from play (the canonical test).
    engine.trash(g, A, ["Quarry"], zone="in_play")
    assert g["seats"][A]["in_play"] == []
    assert engine.cost(g, "Militia") == 2
    # cumulative per play (floor $0)
    assert mv(g, A, {"type": "play_treasure", "card": "Quarry"})[0]
    assert engine.cost(g, "Militia") == 0
    assert engine.cost(g, "Grand Market") == 2
    # dies with the turn
    end_turn(g, A)
    assert g["turn"] == B
    assert engine.cost(g, "Militia") == 4


# --- Rabble ------------------------------------------------------------------

def test_rabble_discards_actions_and_treasures_owner_orders_rest():
    g = fresh()
    give_hand(g, A, ["Rabble"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    sb = g["seats"][B]
    sb["deck"], sb["discard"] = ["Copper", "Estate", "Duchy"], []
    assert mv(g, A, {"type": "play_action", "card": "Rabble"})[0]
    assert len(g["seats"][A]["hand"]) == 3              # attacker's +3 first
    assert sb["discard"] == ["Copper"]                  # the Treasure goes
    c = g["pending"][-1]["constraint"]
    assert g["pending_pid"] == B and g["pending_kind"] == "order_cards"
    assert sorted(c["cards"]) == ["Duchy", "Estate"]
    assert decide(g, B, order=["Duchy", "Estate"])[0]   # OWNER picks the order
    assert sb["deck"] == ["Duchy", "Estate"]            # order[0] on top
    assert sb["aside"] == [] and g["pending_pid"] is None


def test_rabble_single_leftover_goes_back_without_a_frame():
    g = fresh()
    give_hand(g, A, ["Rabble"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    sb = g["seats"][B]
    sb["deck"], sb["discard"] = ["Silver", "Rabble", "Estate"], []
    assert mv(g, A, {"type": "play_action", "card": "Rabble"})[0]
    assert g["pending_pid"] is None                     # <=1 remaining: no choice
    assert sorted(sb["discard"]) == ["Rabble", "Silver"]
    assert sb["deck"] == ["Estate"] and sb["aside"] == []


def test_rabble_moat_immunity():
    g = fresh(kingdom=KX)
    give_hand(g, A, ["Rabble"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    give_hand(g, B, ["Moat"])
    sb = g["seats"][B]
    sb["deck"], sb["discard"] = ["Copper", "Estate", "Duchy"], []
    assert mv(g, A, {"type": "play_action", "card": "Rabble"})[0]
    assert g["pending_pid"] == B and g["pending_kind"] == "choose_option"
    assert decide(g, B, ids=["react:Moat"])[0]
    # the play ability still ran for the attacker; B's deck is untouched
    assert len(g["seats"][A]["hand"]) == 3
    assert sb["deck"] == ["Copper", "Estate", "Duchy"]
    assert sb["discard"] == [] and g["pending_pid"] is None


# --- Vault -------------------------------------------------------------------

def test_vault_discard_for_coins_and_opponent_exchange():
    g = fresh()
    give_hand(g, A, ["Vault", "Estate", "Estate"])
    g["seats"][A]["deck"] = ["Copper", "Copper"]
    give_hand(g, B, ["Copper", "Copper", "Estate"])
    g["seats"][B]["deck"] = ["Gold"]
    assert mv(g, A, {"type": "play_action", "card": "Vault"})[0]
    c = g["pending"][-1]["constraint"]
    assert g["pending_pid"] == A and c["min"] == 0 and c["max"] == 4
    assert decide(g, A, cards=["Estate", "Estate"])[0]
    assert g["coins"] == 2                              # +$1 per discard
    # then the opponent: may discard EXACTLY 2 to draw 1
    assert g["pending_pid"] == B and g["pending_kind"] == "choose_option"
    assert decide(g, B, ids=["discard"])[0]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 2 and c["max"] == 2
    assert decide(g, B, cards=["Copper", "Copper"])[0]
    assert sorted(g["seats"][B]["hand"]) == ["Estate", "Gold"]
    assert g["pending_pid"] is None


def test_vault_opponent_decline_and_short_hand():
    g = fresh()
    give_hand(g, A, ["Vault"])
    g["seats"][A]["deck"] = ["Copper", "Copper"]
    give_hand(g, B, ["Copper", "Copper"])
    assert mv(g, A, {"type": "play_action", "card": "Vault"})[0]
    assert decide(g, A, cards=[])[0]                    # keep everything: +$0
    assert g["coins"] == 0
    assert decide(g, B, ids=["decline"])[0]
    assert g["pending_pid"] is None
    assert sorted(g["seats"][B]["hand"]) == ["Copper", "Copper"]
    # an EMPTY hand has nothing to discard -> no prompt
    g = fresh()
    give_hand(g, A, ["Vault"])
    g["seats"][A]["deck"] = ["Copper", "Copper"]
    give_hand(g, B, [])
    assert mv(g, A, {"type": "play_action", "card": "Vault"})[0]
    assert decide(g, A, cards=[])[0]
    assert g["pending_pid"] is None


def test_vault_offer_is_not_feasibility_filtered_for_a_one_card_hand():
    """LEDGER (paid pre-ph.3): the offer used to be skipped below 2 cards.
    Compendium, on Capital City under the same DISCARD-THEN-GET-FROM-DECK
    heading Vault is filed at: "If you choose to discard 2 cards with only 1
    card in your hand, you discard that card but do not get any +". So the
    option IS offered, the one card IS discarded, and no card is drawn ("if
    you do" needs the full first effect). That discard is observable — under
    Hinterlands it can be a Tunnel, which reveals for a Gold."""
    g = fresh()
    give_hand(g, A, ["Vault"])
    g["seats"][A]["deck"] = ["Copper", "Copper"]
    give_hand(g, B, ["Estate"])
    g["seats"][B]["deck"] = ["Gold"]
    assert mv(g, A, {"type": "play_action", "card": "Vault"})[0]
    assert decide(g, A, cards=[])[0]

    assert g["pending_pid"] == B, "the 1-card hand must still be offered"
    assert decide(g, B, ids=["discard"])[0]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 1 and c["max"] == 1        # clamped to availability
    assert decide(g, B, cards=["Estate"])[0]
    assert g["seats"][B]["discard"] == ["Estate"]  # the discard really happened
    assert g["seats"][B]["hand"] == []             # ...and NO card was drawn
    assert g["seats"][B]["deck"] == ["Gold"]
    assert g["pending_pid"] is None


# --- War Chest ---------------------------------------------------------------

def test_war_chest_left_player_names_then_gain():
    g = fresh()
    give_hand(g, A, ["War Chest"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "War Chest"})[0]
    assert g["coins"] == 0                              # produces no $
    assert g["pending_pid"] == B and g["pending_kind"] == "name_card"
    assert decide(g, B, card="Silver")[0]
    assert g["turn_ctx"]["war_chest_names"] == ["Silver"]
    assert g["pending_pid"] == A and g["pending_kind"] == "choose_pile"
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Silver" not in piles                        # named -> blocked
    assert "Gold" not in piles                          # $6 > $5
    assert "Duchy" in piles and "Vault" in piles
    assert decide(g, A, pile="Duchy")[0]
    assert g["seats"][A]["discard"] == ["Duchy"]


def test_war_chest_names_accumulate_across_plays_same_turn():
    g = fresh()
    give_hand(g, A, ["War Chest", "War Chest"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "War Chest"})[0]
    assert decide(g, B, card="Silver")[0]
    assert decide(g, A, pile="Duchy")[0]
    assert mv(g, A, {"type": "play_treasure", "card": "War Chest"})[0]
    assert decide(g, B, card="Duchy")[0]
    assert g["turn_ctx"]["war_chest_names"] == ["Silver", "Duchy"]
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Silver" not in piles and "Duchy" not in piles   # both plays' names
    assert decide(g, A, pile="Estate")[0]
    assert g["seats"][A]["discard"] == ["Duchy", "Estate"]


def test_war_chest_no_eligible_pile_gains_nothing():
    g = fresh()
    for p in list(g["supply"]):
        if engine.cost_le(g, p, 5):
            g["supply"][p] = 0                          # nothing gainable <= $5
    give_hand(g, A, ["War Chest"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "War Chest"})[0]
    assert decide(g, B, card="Province")[0]
    assert g["pending_pid"] is None                     # empty candidate set
    assert g["seats"][A]["discard"] == []
    assert g["turn_ctx"]["war_chest_names"] == ["Province"]
