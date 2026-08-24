"""Prosperity batch B rules tests: Charlatan, Clerk, Collection, Crystal Ball,
Hoard, Investment, King's Court, Magnate, Mint, Peddler, Tiara, Watchtower.

Idioms (see test_engine.py / test_cards_seaside_b.py): positions are arranged
by mutating the game dict directly; give_hand breaks conservation on purpose.
The engine AUTO-ADVANCES action -> buy once the turn player has no Actions
left or no Action card in hand; treasures need g["phase"] staged to "buy".
Direct engine.gain(...) calls must be followed by engine._drive(g) unless a
reaction window is expected to be pending. Both default kingdoms here have
>= 10 Prosperity piles, so new_game's randomizer rule ALWAYS deals a
Platinum/Colony game (probability prosperity_n/10 >= 1) — handy for the
Colony-buy fixtures.
"""

from games.dontminion import engine

A, B = "alice", "bob"
# The batch's 11 non-Charlatan cards + cross-set helpers (Quarry for Mint's
# canonical interaction, Astrolabe for Tiara's Duration throne, Fishing
# Village for King's Court's rider, Witch for an off-turn Watchtower gain).
KP = ["Clerk", "Collection", "Crystal Ball", "Hoard", "Investment",
      "King's Court", "Magnate", "Mint", "Peddler", "Tiara", "Watchtower",
      "Quarry", "Astrolabe", "Fishing Village", "Moat", "Smithy", "Village",
      "Witch", "Throne Room"]
KPC = KP + ["Charlatan"]          # Charlatan in the kingdom: Curse is a Treasure


def fresh(kingdom=KP, players=(A, B), seed=42):
    return engine.new_game(list(players), ["base", "seaside", "prosperity"],
                           seed=seed, kingdom=kingdom)


def give_hand(g, pid, cards):
    g["seats"][pid]["hand"] = list(cards)


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def play(g, pid, card):
    return mv(g, pid, {"type": "play_action", "card": card})


def decide(g, pid, **payload):
    return mv(g, pid, {"type": "decision", **payload})


# --- Charlatan ---------------------------------------------------------------

def test_charlatan_coins_and_curse_attack():
    g = fresh(kingdom=KPC)
    give_hand(g, A, ["Charlatan"])
    assert play(g, A, "Charlatan")[0]
    assert g["coins"] == 3
    assert "Curse" in g["seats"][B]["discard"]
    assert g["supply"]["Curse"] == 9


def test_charlatan_pays_even_with_no_curses_left():
    g = fresh(kingdom=KPC)
    g["supply"]["Curse"] = 0
    give_hand(g, A, ["Charlatan"])
    assert play(g, A, "Charlatan")[0]
    assert g["coins"] == 3
    assert "Curse" not in g["seats"][B]["discard"]


def test_charlatan_makes_curse_a_treasure_game_wide():
    g = fresh(kingdom=KPC)
    # the kernel rule is armed by the KINGDOM, not by any play
    assert g["curse_is_treasure"] is True
    assert engine.has_type(g, "Curse", "treasure")
    assert "curse" in engine.types_of(g, "Curse")       # still a Curse too
    assert engine.coins_of(g, "Curse") == 1
    give_hand(g, A, ["Curse", "Copper"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Curse"})[0]
    assert g["coins"] == 1                              # plays for $1
    assert mv(g, A, {"type": "play_all_treasures"})[0]  # picks up the Copper
    assert g["coins"] == 2
    assert g["seats"][A]["in_play"] == ["Curse", "Copper"]


def test_charlatan_play_all_plays_curses_too():
    g = fresh(kingdom=KPC)
    give_hand(g, A, ["Curse", "Curse", "Copper"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert g["coins"] == 3
    assert g["seats"][A]["hand"] == []


def test_without_charlatan_curse_stays_a_curse():
    g = fresh()                                         # KP has no Charlatan
    assert not g["curse_is_treasure"]
    assert not engine.has_type(g, "Curse", "treasure")
    give_hand(g, A, ["Curse", "Copper"])
    g["phase"] = "buy"
    ok, err = mv(g, A, {"type": "play_treasure", "card": "Curse"})
    assert not ok and "not a treasure" in err
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert g["seats"][A]["in_play"] == ["Copper"]
    assert "Curse" in g["seats"][A]["hand"]             # left behind


# --- Clerk -------------------------------------------------------------------

def test_clerk_attack_topdecks_from_five_card_hands():
    g = fresh()
    give_hand(g, A, ["Clerk"])
    give_hand(g, B, ["Estate", "Copper", "Copper", "Copper", "Copper"])
    assert play(g, A, "Clerk")[0]
    assert g["coins"] == 2
    assert g["pending_pid"] == B and g["pending_kind"] == "choose_cards"
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 1 and c["max"] == 1              # their choice, mandatory
    assert decide(g, B, cards=["Estate"])[0]
    assert g["seats"][B]["deck"][0] == "Estate"
    assert len(g["seats"][B]["hand"]) == 4


def test_clerk_attack_skips_hands_under_five():
    g = fresh()
    give_hand(g, A, ["Clerk"])
    give_hand(g, B, ["Copper"] * 4)
    assert play(g, A, "Clerk")[0]
    assert g["pending_pid"] is None                     # B unaffected
    assert len(g["seats"][B]["hand"]) == 4


def test_clerk_start_of_turn_chain_plays_each_copy_free():
    g = fresh()
    give_hand(g, B, ["Clerk", "Clerk", "Copper"])
    give_hand(g, A, ["Copper"])
    g["seats"][A]["deck"] = ["Copper"] * 10             # A's clean-up hand: 5 Coppers
    assert mv(g, A, {"type": "end_phase"})[0]           # action -> buy
    assert mv(g, A, {"type": "end_phase"})[0]           # clean-up -> B's turn start
    assert g["turn"] == B
    assert g["pending_pid"] == B and g["pending_kind"] == "choose_option"
    assert g["pending"][-1]["card"] == "Clerk"
    assert decide(g, B, ids=["play"])[0]
    # the second copy is re-offered right away (the Pirate re-offer pattern)
    assert g["pending_pid"] == B and g["pending"][-1]["card"] == "Clerk"
    assert decide(g, B, ids=["play"])[0]
    # both attacks land: A is at 5 cards for the first hit...
    assert g["pending_pid"] == A and g["pending_kind"] == "choose_cards"
    assert g["coins"] == 2                              # only one Clerk resolved yet
    assert decide(g, A, cards=["Copper"])[0]
    # ...and at 4 for the other, which therefore skips A
    assert g["pending_pid"] is None
    assert g["coins"] == 4
    assert g["seats"][B]["in_play"] == ["Clerk", "Clerk"]
    assert g["actions"] == 1                            # no Action from the pool spent
    assert len(g["seats"][A]["hand"]) == 4
    assert g["seats"][A]["deck"][0] == "Copper"


def test_clerk_start_of_turn_decline_keeps_it_in_hand():
    g = fresh()
    give_hand(g, B, ["Clerk", "Copper"])
    give_hand(g, A, ["Copper"])
    assert mv(g, A, {"type": "end_phase"})[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert g["pending_pid"] == B
    assert decide(g, B, ids=["decline"])[0]
    assert g["pending_pid"] is None
    assert g["seats"][B]["hand"].count("Clerk") == 1
    assert g["phase"] == "action"                       # still playable normally


# --- Collection --------------------------------------------------------------

def test_collection_vp_per_action_gained_cumulative():
    g = fresh()
    give_hand(g, A, ["Collection", "Collection"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Collection"})[0]
    assert mv(g, A, {"type": "play_treasure", "card": "Collection"})[0]
    assert g["coins"] == 4 and g["buys"] == 3
    g["coins"] = 10
    assert mv(g, A, {"type": "buy", "card": "Smithy"})[0]   # an Action gain
    assert g["vp_tokens"][A] == 2                           # +1 per play
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]   # not an Action
    assert g["vp_tokens"][A] == 2
    engine.gain(g, A, "Village"); engine._drive(g)          # gain, not buy: counts
    assert g["vp_tokens"][A] == 4
    # discards at THIS clean-up like any treasure (no duration-zone stranding)
    assert mv(g, A, {"type": "end_phase"})[0]
    assert g["turn"] == B
    assert g["seats"][A]["discard"].count("Collection") == 2
    assert g["seats"][A]["duration"] == []
    # the watcher died with the turn
    engine.gain(g, A, "Smithy"); engine._drive(g)
    assert g["vp_tokens"][A] == 4


def test_collection_survives_leaving_play_via_mint_gain():
    g = fresh()
    give_hand(g, A, ["Collection"] + ["Copper"] * 4)
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_all_treasures"})[0]  # Collection is not manual
    assert g["coins"] == 6
    assert mv(g, A, {"type": "buy", "card": "Mint"})[0]
    # gaining Mint trashed the played Collection...
    assert "Collection" in g["trash"]
    assert g["seats"][A]["in_play"] == []
    # ...but Mint is itself an Action gained this turn: the watcher still paid
    assert g["vp_tokens"][A] == 1
    engine.gain(g, A, "Village"); engine._drive(g)
    assert g["vp_tokens"][A] == 2                       # still alive off-table
    # clean-up neither crashes nor strands anything (the trashed copy stays
    # trashed; nothing enters the duration zone)
    assert mv(g, A, {"type": "end_phase"})[0]
    assert g["turn"] == B
    assert g["seats"][A]["duration"] == []
    assert g["trash"].count("Collection") == 1


# --- Crystal Ball ------------------------------------------------------------

def test_crystal_ball_plays_an_action_off_the_deck_in_the_buy_phase():
    g = fresh()
    give_hand(g, A, ["Crystal Ball"])
    g["seats"][A]["deck"] = ["Smithy", "Copper", "Copper", "Copper", "Copper"]
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Crystal Ball"})[0]
    assert g["coins"] == 1
    ids = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
    assert ids == ["trash", "discard", "play", "back"]
    a0 = g["actions"]
    assert decide(g, A, ids=["play"])[0]
    assert "Smithy" in g["seats"][A]["in_play"]         # a real play
    assert len(g["seats"][A]["hand"]) == 3              # its ability resolved
    assert g["actions"] == a0                           # no Action from the pool
    assert g["seats"][A]["aside"] == []


def test_crystal_ball_treasure_play_chains_its_coins():
    g = fresh()
    give_hand(g, A, ["Crystal Ball"])
    g["seats"][A]["deck"] = ["Silver"]
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Crystal Ball"})[0]
    assert decide(g, A, ids=["play"])[0]
    assert g["coins"] == 3                              # $1 + the Silver's $2
    assert "Silver" in g["seats"][A]["in_play"]


def test_crystal_ball_trash_discard_back_and_empty():
    g = fresh()
    give_hand(g, A, ["Crystal Ball"])
    g["seats"][A]["deck"] = ["Estate", "Copper"]
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Crystal Ball"})[0]
    ids = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
    assert "play" not in ids                            # a Victory card: no play
    assert decide(g, A, ids=["trash"])[0]
    assert "Estate" in g["trash"]
    give_hand(g, A, ["Crystal Ball"])                   # discard the top
    assert mv(g, A, {"type": "play_treasure", "card": "Crystal Ball"})[0]
    assert decide(g, A, ids=["discard"])[0]
    assert g["seats"][A]["discard"][-1] == "Copper"
    give_hand(g, A, ["Crystal Ball"])                   # put it back
    g["seats"][A]["deck"] = ["Silver"]
    g["seats"][A]["discard"] = []
    assert mv(g, A, {"type": "play_treasure", "card": "Crystal Ball"})[0]
    assert decide(g, A, ids=["back"])[0]
    assert g["seats"][A]["deck"][0] == "Silver"
    give_hand(g, A, ["Crystal Ball"])                   # nothing to look at
    g["seats"][A]["deck"] = []
    g["seats"][A]["discard"] = []
    assert mv(g, A, {"type": "play_treasure", "card": "Crystal Ball"})[0]
    assert g["pending_pid"] is None


# --- Hoard -------------------------------------------------------------------

def test_hoard_gold_on_bought_victory_only():
    g = fresh()
    give_hand(g, A, ["Hoard"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Hoard"})[0]
    assert g["coins"] == 2
    assert mv(g, A, {"type": "buy", "card": "Estate"})[0]
    assert g["seats"][A]["discard"].count("Gold") == 1  # bought -> Gold
    engine.gain(g, A, "Estate"); engine._drive(g)       # gained, NOT bought
    assert g["seats"][A]["discard"].count("Gold") == 1  # no extra Gold
    assert mv(g, A, {"type": "end_phase"})[0]           # clean clean-up
    assert g["turn"] == B
    assert "Hoard" in g["seats"][A]["discard"]
    assert g["seats"][A]["duration"] == []


def test_hoard_stacks_and_colony_counts_as_victory():
    g = fresh()
    # the >= 10-Prosperity kingdom makes this ALWAYS a Platinum/Colony game
    assert g["colony"] is True
    assert g["supply"]["Colony"] == 8 and g["supply"]["Platinum"] == 12
    give_hand(g, A, ["Hoard", "Hoard"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_all_treasures"})[0]  # Hoard is not manual
    assert g["coins"] == 4
    g["coins"] = 11
    assert mv(g, A, {"type": "buy", "card": "Colony"})[0]
    assert g["seats"][A]["discard"].count("Gold") == 2  # one per Hoard play


# --- Investment --------------------------------------------------------------

def test_investment_coin_mode():
    g = fresh()
    give_hand(g, A, ["Investment", "Estate"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Investment"})[0]
    assert g["coins"] == 0                              # produces nothing itself
    c = g["pending"][-1]["constraint"]
    assert c["cards"] == ["Estate"] and c["min"] == 1 and c["max"] == 1
    assert decide(g, A, cards=["Estate"])[0]            # mandatory trash first
    assert "Estate" in g["trash"]
    assert decide(g, A, ids=["coin"])[0]
    assert g["coins"] == 1


def test_investment_vp_mode_counts_differently_named_treasures():
    g = fresh()
    give_hand(g, A, ["Investment", "Copper", "Silver", "Gold", "Copper"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Investment"})[0]
    assert decide(g, A, cards=["Copper"])[0]
    assert decide(g, A, ids=["vp"])[0]
    assert "Investment" in g["trash"]                   # trashed from play
    assert g["seats"][A]["in_play"] == []
    assert g["vp_tokens"][A] == 3                       # {Copper, Silver, Gold}
    assert g["coins"] == 0
    rev = [e for e in g["log"] if e["event"] == "reveal"][-1]
    assert sorted(rev["cards"]) == ["Copper", "Gold", "Silver"]


def test_investment_vp_counts_a_charlatan_curse():
    g = fresh(kingdom=KPC)
    give_hand(g, A, ["Investment", "Estate", "Curse", "Copper"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Investment"})[0]
    assert decide(g, A, cards=["Estate"])[0]
    assert decide(g, A, ids=["vp"])[0]
    assert g["vp_tokens"][A] == 2                       # Curse counts as a name


def test_investment_empty_hand_still_offers_the_choice():
    g = fresh()
    give_hand(g, A, ["Investment"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Investment"})[0]
    assert g["pending_kind"] == "choose_option"         # straight to the mode
    assert decide(g, A, ids=["coin"])[0]
    assert g["coins"] == 1


def test_investment_tiara_replay_pays_vp_at_most_once():
    g = fresh()
    give_hand(g, A, ["Tiara", "Investment", "Copper", "Copper"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Tiara"})[0]
    assert decide(g, A, cards=["Investment"])[0]        # throne it
    # first resolution: trash, then the self-trash VP mode
    assert decide(g, A, cards=["Copper"])[0]
    assert decide(g, A, ids=["vp"])[0]
    assert g["vp_tokens"][A] == 1                       # {Copper}
    assert g["trash"].count("Investment") == 1
    # the replay: trashes from hand again, but the VP mode finds Investment
    # gone from play (membership guard) — no second payout (the Crown ruling)
    assert decide(g, A, cards=["Copper"])[0]
    assert decide(g, A, ids=["vp"])[0]
    assert g["vp_tokens"][A] == 1
    assert g["trash"].count("Investment") == 1
    assert g["trash"].count("Copper") == 2              # both trashes happened


# --- King's Court ------------------------------------------------------------

def test_kings_court_plays_an_action_three_times():
    g = fresh()
    give_hand(g, A, ["King's Court", "Smithy"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert play(g, A, "King's Court")[0]
    c = g["pending"][-1]["constraint"]
    assert c["cards"] == ["Smithy"] and c["min"] == 0 and c["max"] == 1
    assert decide(g, A, cards=["Smithy"])[0]
    assert len(g["seats"][A]["hand"]) == 9              # 3 x draw 3
    assert g["seats"][A]["in_play"] == ["King's Court", "Smithy"]
    assert g["turn_ctx"]["actions_played"] == 4         # KC + three Smithy plays


def test_kings_court_dead_play_and_decline():
    g = fresh()
    give_hand(g, A, ["King's Court"])
    assert play(g, A, "King's Court")[0]
    assert g["pending_pid"] is None                     # no Actions: nothing
    g = fresh()
    give_hand(g, A, ["King's Court", "Smithy"])
    assert play(g, A, "King's Court")[0]
    assert decide(g, A, cards=[])[0]                    # "may": declined
    assert g["seats"][A]["hand"] == ["Smithy"]


def test_kings_court_stays_out_with_a_thrice_played_duration():
    g = fresh()
    give_hand(g, A, ["King's Court", "Fishing Village"])
    assert play(g, A, "King's Court")[0]
    assert decide(g, A, cards=["Fishing Village"])[0]
    assert g["actions"] == 6                            # 3 x (+2 Actions)
    assert g["coins"] == 3                              # 3 x (+$1)
    entry = [e for e in g["seats"][A]["dur_setup"]
             if e["card"] == "Fishing Village"][-1]
    assert len(entry["fx"]) == 3                        # the ability happens 3x
    assert entry["riders"] == ["King's Court"]
    assert mv(g, A, {"type": "end_phase"})[0]           # auto-advanced to buy already
    assert "King's Court" not in g["seats"][A]["discard"]
    assert engine.duration_in_play(g, A, "Fishing Village")
    assert engine.duration_in_play(g, A, "King's Court")
    assert mv(g, B, {"type": "end_phase"})[0]
    # A's next turn start: the tripled next-turn half
    assert g["actions"] == 4 and g["coins"] == 3
    g["seats"][A]["deck"] = ["Copper"] * 10             # keep clean-up shuffle-free
    assert mv(g, A, {"type": "end_phase"})[0]           # then both discard together
    assert "King's Court" in g["seats"][A]["discard"]
    assert "Fishing Village" in g["seats"][A]["discard"]


# --- Magnate -----------------------------------------------------------------

def test_magnate_reveals_and_draws_per_treasure():
    g = fresh()
    give_hand(g, A, ["Magnate", "Copper", "Silver", "Estate", "Copper"])
    g["seats"][A]["deck"] = ["Copper"] * 6
    assert play(g, A, "Magnate")[0]
    assert len(g["seats"][A]["hand"]) == 7              # 4 kept + 3 drawn
    rev = [e for e in g["log"] if e["event"] == "reveal"][-1]
    assert sorted(rev["cards"]) == ["Copper", "Copper", "Estate", "Silver"]


def test_magnate_empty_hand_and_charlatan_curse():
    g = fresh()
    give_hand(g, A, ["Magnate"])
    assert play(g, A, "Magnate")[0]
    assert g["seats"][A]["hand"] == []                  # reveal nothing, draw 0
    g = fresh(kingdom=KPC)
    give_hand(g, A, ["Magnate", "Curse"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    assert play(g, A, "Magnate")[0]
    assert len(g["seats"][A]["hand"]) == 2              # the Curse counted


# --- Mint --------------------------------------------------------------------

def test_mint_gains_a_copy_of_a_revealed_treasure():
    g = fresh()
    give_hand(g, A, ["Mint", "Silver", "Estate"])
    assert play(g, A, "Mint")[0]
    c = g["pending"][-1]["constraint"]
    assert c["cards"] == ["Silver"] and c["min"] == 0   # treasures only, optional
    assert decide(g, A, cards=["Silver"])[0]
    assert g["seats"][A]["discard"] == ["Silver"]       # the gained copy
    assert "Silver" in g["seats"][A]["hand"]            # the revealed one stayed
    assert g["supply"]["Silver"] == 39


def test_mint_decline_and_empty_pile():
    g = fresh()
    give_hand(g, A, ["Mint", "Silver"])
    assert play(g, A, "Mint")[0]
    assert decide(g, A, cards=[])[0]                    # declined
    assert g["seats"][A]["discard"] == []
    g = fresh()
    give_hand(g, A, ["Mint", "Silver"])
    g["supply"]["Silver"] = 0
    assert play(g, A, "Mint")[0]
    assert decide(g, A, cards=["Silver"])[0]            # reveal ok, gain nothing
    assert g["seats"][A]["discard"] == []


def test_mint_gain_trashes_played_treasures_but_quarry_discount_stays():
    g = fresh()
    give_hand(g, A, [])
    g["phase"] = "buy"
    # staged table: a played Quarry (turn-scoped counter), a Copper, a
    # Duration Treasure, and an Action
    g["seats"][A]["in_play"] = ["Quarry", "Copper", "Astrolabe", "Smithy"]
    g["turn_ctx"]["quarries"] = 1
    assert engine.cost(g, "Smithy") == 2
    g["coins"] = 5
    assert mv(g, A, {"type": "buy", "card": "Mint"})[0]  # costs 5-2=3 (an Action)
    assert sorted(g["trash"]) == ["Copper", "Quarry"]    # all non-Duration Treasures
    assert g["seats"][A]["in_play"] == ["Astrolabe", "Smithy"]
    # the canonical 2022 ruling: the discount is turn-scoped, NOT while-in-play
    assert engine.cost(g, "Smithy") == 2


def pool_pick(g, pid, label):
    """Answer the p23 §2 what-resolves-first prompt by option label."""
    f = g["pending"][-1]
    assert (f["card"], f["stage"]) == ("__abilities", "pick"), (f["card"], f["stage"])
    opts = {o["label"]: o["id"] for o in f["constraint"]["options"]}
    ok, err = engine.apply_move(g, pid, {"type": "decision", "ids": [opts[label]]})
    assert ok, err


def test_mint_when_gain_fires_on_non_buy_gains_too():
    g = fresh()
    g["seats"][A]["in_play"] = ["Copper"]
    engine.gain(g, A, "Mint"); engine._drive(g)         # gained, not bought
    assert g["trash"] == ["Copper"]
    assert "Mint" in g["seats"][A]["discard"]


def test_watchtower_trashing_a_gained_mint_still_trashes_treasures():
    g = fresh()
    give_hand(g, A, ["Watchtower"])
    g["seats"][A]["in_play"] = ["Copper", "Copper"]
    engine.gain(g, A, "Mint"); engine._drive(g)
    # Mint's own when-gain and Watchtower are CONCURRENT: the player picks
    # what resolves first (p23 §2) — take Watchtower first, the old order
    pool_pick(g, A, "Watchtower")
    assert g["pending_pid"] == A and g["pending"][-1]["card"] == "Watchtower"
    assert decide(g, A, ids=["play"])[0]
    assert decide(g, A, ids=["trash"])[0]
    assert "Mint" in g["trash"]
    # ...but the gain HAPPENED: Mint's when-gain still trashed the Coppers
    assert g["trash"].count("Copper") == 2
    assert g["seats"][A]["in_play"] == []
    assert "Watchtower" in g["seats"][A]["hand"]        # revealed, never played


# --- Peddler -----------------------------------------------------------------

def test_peddler_vanilla_play():
    g = fresh()
    give_hand(g, A, ["Peddler"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    assert play(g, A, "Peddler")[0]
    assert len(g["seats"][A]["hand"]) == 1
    assert g["actions"] == 1 and g["coins"] == 1


def test_peddler_costs_8_outside_the_buy_phase():
    g = fresh()
    g["seats"][A]["in_play"] = ["Smithy", "Village"]    # irrelevant in action phase
    assert g["phase"] == "action"
    assert engine.cost(g, "Peddler") == 8


def test_peddler_buy_phase_discount_tracks_the_active_players_table():
    g = fresh()
    g["phase"] = "buy"
    assert engine.cost(g, "Peddler") == 8               # no Actions in play
    g["seats"][A]["in_play"] = ["Smithy", "Village", "Copper"]
    assert engine.cost(g, "Peddler") == 4               # 2 Actions x $2
    # duration-zone Actions and their riders count too; the cost floors at 0
    g["seats"][A]["duration"] = [{"card": "Fishing Village", "fx": [],
                                  "riders": ["Throne Room"]}]
    assert engine.cost(g, "Peddler") == 0
    g["coins"] = 0
    assert mv(g, A, {"type": "buy", "card": "Peddler"})[0]   # free
    assert "Peddler" in g["seats"][A]["discard"]
    # the cost is GLOBAL but keyed to the ACTIVE player: B's table is ignored
    g["seats"][B]["in_play"] = ["Smithy"] * 5
    g["seats"][A]["in_play"] = []
    g["seats"][A]["duration"] = []
    assert engine.cost(g, "Peddler") == 8


def test_peddler_price_resets_when_the_turn_passes():
    g = fresh()
    give_hand(g, A, ["Village", "Smithy"])
    g["seats"][A]["deck"] = ["Copper"] * 8
    assert play(g, A, "Village")[0]
    assert play(g, A, "Smithy")[0]
    assert g["phase"] == "buy"                          # auto-advanced
    assert engine.cost(g, "Peddler") == 4               # 2 Actions in play
    assert mv(g, A, {"type": "end_phase"})[0]
    assert g["turn"] == B
    assert engine.cost(g, "Peddler") == 8               # B's action phase
    g["phase"] = "buy"
    assert engine.cost(g, "Peddler") == 8               # B has no Actions in play


# --- Tiara -------------------------------------------------------------------

def test_tiara_may_topdeck_each_gain():
    g = fresh()
    give_hand(g, A, ["Tiara"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Tiara"})[0]
    assert g["coins"] == 0 and g["buys"] == 2           # $0, +1 Buy
    assert g["pending_pid"] is None                     # no treasure to throne
    g["coins"] = 8
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    assert g["pending_pid"] == A and g["pending"][-1]["card"] == "Tiara"
    assert decide(g, A, ids=["topdeck"])[0]
    assert g["seats"][A]["deck"][0] == "Silver"
    assert "Silver" not in g["seats"][A]["discard"]
    tops = [e for e in g["log"] if e["event"] == "topdeck"]
    assert tops and tops[-1]["card"] == "Silver"        # a public move
    assert mv(g, A, {"type": "buy", "card": "Smithy"})[0]
    assert decide(g, A, ids=["keep"])[0]                # optional per gain
    assert "Smithy" in g["seats"][A]["discard"]
    assert mv(g, A, {"type": "end_phase"})[0]           # no stranding at clean-up
    assert g["turn"] == B
    assert "Tiara" in g["seats"][A]["discard"]
    assert g["seats"][A]["duration"] == []


def test_tiara_plays_a_treasure_twice():
    g = fresh()
    give_hand(g, A, ["Tiara", "Gold"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Tiara"})[0]
    c = g["pending"][-1]["constraint"]
    assert c["cards"] == ["Gold"] and c["min"] == 0 and c["max"] == 1
    assert decide(g, A, cards=["Gold"])[0]
    assert g["coins"] == 6                              # $3 twice
    assert g["seats"][A]["in_play"] == ["Tiara", "Gold"]


def test_tiara_playing_collection_twice_doubles_the_vp():
    g = fresh()
    give_hand(g, A, ["Tiara", "Collection"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Tiara"})[0]
    assert decide(g, A, cards=["Collection"])[0]
    assert g["coins"] == 4                              # $2 twice
    assert g["buys"] == 4                               # 1 + Tiara + Collection x2
    assert mv(g, A, {"type": "buy", "card": "Smithy"})[0]
    # two Collection resolutions -> +2 VP for the Action gain; the Tiara rider
    # also offers the topdeck for it
    assert g["vp_tokens"][A] == 2
    assert g["pending"][-1]["card"] == "Tiara"
    assert decide(g, A, ids=["topdeck"])[0]
    assert g["seats"][A]["deck"][0] == "Smithy"


def test_tiara_astrolabe_double_play_and_rider():
    g = fresh()
    give_hand(g, A, ["Tiara", "Astrolabe"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Tiara"})[0]
    assert decide(g, A, cards=["Astrolabe"])[0]
    assert g["coins"] == 2                              # $1 twice
    assert g["buys"] == 4                               # 1 + Tiara + Astrolabe x2
    entry = [e for e in g["seats"][A]["dur_setup"] if e["card"] == "Astrolabe"][-1]
    assert len(entry["fx"]) == 2 and entry["riders"] == ["Tiara"]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert engine.duration_in_play(g, A, "Astrolabe")
    assert engine.duration_in_play(g, A, "Tiara")       # the thrower stays out
    assert "Tiara" not in g["seats"][A]["discard"]
    assert mv(g, B, {"type": "end_phase"})[0]
    # A's next turn: the doubled next-turn half
    assert g["coins"] == 2 and g["buys"] == 3
    g["seats"][A]["deck"] = ["Copper"] * 10             # keep clean-up shuffle-free
    assert mv(g, A, {"type": "end_phase"})[0]           # both discard together
    assert g["seats"][A]["discard"].count("Tiara") == 1
    assert g["seats"][A]["discard"].count("Astrolabe") == 1


def test_watchtower_moves_first_and_tiara_loses_track():
    g = fresh()
    give_hand(g, A, ["Tiara", "Watchtower"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Tiara"})[0]
    assert g["pending_pid"] is None                     # Watchtower isn't a Treasure
    g["coins"] = 3
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    # Tiara's may-topdeck and Watchtower are concurrent — pick Watchtower
    # first (whichever moves the Silver first, the other loses track)
    pool_pick(g, A, "Watchtower")
    assert g["pending"][-1]["card"] == "Watchtower"
    assert decide(g, A, ids=["play"])[0]
    assert decide(g, A, ids=["topdeck"])[0]
    assert g["seats"][A]["deck"][0] == "Silver"
    # then Tiara's prompt: saying yes quietly does nothing (lost track)
    assert g["pending"][-1]["card"] == "Tiara"
    assert decide(g, A, ids=["topdeck"])[0]
    assert g["seats"][A]["deck"].count("Silver") == 1   # not duplicated
    assert g["seats"][A]["discard"] == []


# --- Watchtower --------------------------------------------------------------

def test_watchtower_draws_up_to_six():
    g = fresh()
    give_hand(g, A, ["Watchtower", "Copper"])
    g["seats"][A]["deck"] = ["Copper"] * 8
    assert play(g, A, "Watchtower")[0]
    assert len(g["seats"][A]["hand"]) == 6
    g = fresh()
    give_hand(g, A, ["Watchtower"] + ["Copper"] * 6)
    assert play(g, A, "Watchtower")[0]
    assert len(g["seats"][A]["hand"]) == 6              # already at 6: no draw


def test_watchtower_reacts_to_every_separate_gain_from_hand():
    g = fresh()
    give_hand(g, A, ["Watchtower"])
    engine.gain(g, A, "Silver"); engine._drive(g)      # one consumer: no prompt
    assert g["pending"][-1]["card"] == "Watchtower"
    assert "Reveal" in g["pending"][-1]["constraint"]["options"][0]["label"]
    assert decide(g, A, ids=["play"])[0]
    assert decide(g, A, ids=["trash"])[0]
    assert "Silver" in g["trash"]
    assert g["supply"]["Silver"] == 39                  # the gain still happened
    assert "Watchtower" in g["seats"][A]["hand"]        # revealed, never left hand
    engine.gain(g, A, "Gold"); engine._drive(g)         # a second, separate gain
    assert g["pending"][-1]["card"] == "Watchtower"
    assert decide(g, A, ids=["play"])[0]
    assert decide(g, A, ids=["topdeck"])[0]
    assert g["seats"][A]["deck"][0] == "Gold"
    engine.gain(g, A, "Copper"); engine._drive(g)       # declining leaves it be
    assert decide(g, A, ids=["decline"])[0]
    assert "Copper" in g["seats"][A]["discard"]
    # someone else's gain never opens A's window ("when YOU gain")
    engine.gain(g, B, "Silver"); engine._drive(g)
    assert g["pending_pid"] is None


def test_watchtower_reacts_on_the_attackers_turn():
    g = fresh()
    give_hand(g, A, ["Witch"])
    g["seats"][A]["deck"] = ["Copper"] * 4
    give_hand(g, B, ["Watchtower", "Copper"])
    assert play(g, A, "Witch")[0]
    # no Moat: straight to the Curse gain, which opens B's Watchtower window
    assert g["pending_pid"] == B and g["pending"][-1]["card"] == "Watchtower"
    assert decide(g, B, ids=["play"])[0]
    assert decide(g, B, ids=["trash"])[0]
    assert "Curse" in g["trash"]
    assert "Curse" not in g["seats"][B]["discard"]
    assert g["supply"]["Curse"] == 9                    # gained, then trashed


def test_watchtower_deck_and_hand_destination_gains():
    g = fresh()
    give_hand(g, A, ["Watchtower"])
    engine.gain(g, A, "Silver", dest="deck"); engine._drive(g)
    assert decide(g, A, ids=["play"])[0]
    assert decide(g, A, ids=["topdeck"])[0]             # already there: a no-op
    assert g["seats"][A]["deck"][0] == "Silver"
    assert g["seats"][A]["deck"].count("Silver") == 1
    engine.gain(g, A, "Gold", dest="hand"); engine._drive(g)
    assert decide(g, A, ids=["play"])[0]
    assert decide(g, A, ids=["trash"])[0]               # trashed out of hand
    assert "Gold" in g["trash"]
    assert "Gold" not in g["seats"][A]["hand"]


# --- play_all autoplay contract ----------------------------------------------

def test_interactive_treasures_are_skipped_by_play_all():
    g = fresh()
    give_hand(g, A, ["Crystal Ball", "Investment", "Tiara",
                     "Collection", "Hoard", "Copper"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert sorted(g["seats"][A]["in_play"]) == ["Collection", "Copper", "Hoard"]
    assert sorted(g["seats"][A]["hand"]) == ["Crystal Ball", "Investment", "Tiara"]
    assert g["pending_pid"] is None                     # nothing left half-resolved


def test_clerk_attack_topdeck_is_not_named_in_the_log():
    """AUDIT REGRESSION: Clerk has no 'reveal' — the victim's topdecked card
    must not be named publicly (only Bureaucrat-class reveals name cards)."""
    g = fresh(players=(A, B))
    give_hand(g, A, ["Clerk"])
    give_hand(g, B, ["Gold", "Copper", "Copper", "Estate", "Estate"])
    assert mv(g, A, {"type": "play_action", "card": "Clerk"})[0]
    assert g["pending_pid"] == B
    assert decide(g, B, cards=["Gold"])[0]
    assert g["seats"][B]["deck"][0] == "Gold"
    ev = [e for e in g["log"] if e["event"] == "topdeck" and e["pid"] == B][-1]
    assert "card" not in ev                     # count-only, no name leaked
