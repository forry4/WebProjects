"""Seaside batch B rules tests: Blockade, Corsair, Island, Monkey,
Native Village, Outpost, Pirate, Sailor, Smugglers, Tactician, Treasure Map,
Treasury.

Idioms (see test_engine.py): positions are arranged by mutating the game dict
directly; give_hand breaks conservation on purpose. The engine AUTO-ADVANCES
action -> buy once the turn player has no Actions left or no Action card in
hand, so most turns here need only one end_phase to reach clean-up. Direct
engine.gain(...) calls from a test must be followed by engine._drive(g) — the
watchers they fire are parked as auto frames until something drives them.
"""

from games.dontminion import engine

A, B, C = "alice", "bob", "carol"
KSB = ["Blockade", "Corsair", "Island", "Monkey", "Native Village", "Outpost",
       "Pirate", "Sailor", "Smugglers", "Tactician", "Treasure Map", "Treasury",
       "Militia", "Moat", "Smithy", "Throne Room"]


def fresh(players=(A, B), seed=42):
    return engine.new_game(list(players), ["base", "seaside"], seed=seed, kingdom=KSB)


def give_hand(g, pid, cards):
    g["seats"][pid]["hand"] = list(cards)


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def play(g, pid, card):
    return mv(g, pid, {"type": "play_action", "card": card})


def decide(g, pid, **payload):
    return mv(g, pid, {"type": "decision", **payload})


# --- Blockade --------------------------------------------------------------------

def test_blockade_gains_set_aside_and_returns_next_turn():
    g = fresh()
    give_hand(g, A, ["Blockade"])
    g["seats"][A]["deck"] = ["Copper"] * 10
    assert play(g, A, "Blockade")[0]
    # B holds no reaction -> straight to the attacker's pile pick, <=$4 only
    assert g["pending_pid"] == A and g["pending_kind"] == "choose_pile"
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Silver" in piles and "Estate" in piles and "Curse" in piles
    assert "Gold" not in piles and "Outpost" not in piles
    assert decide(g, A, pile="Silver")[0]
    assert g["seats"][A]["dur_aside"] == ["Silver"]     # gained straight there
    assert g["supply"]["Silver"] == 39
    assert [w["card"] for w in g["watchers"]] == ["Blockade"]
    assert mv(g, A, {"type": "end_phase"})[0]           # auto-advanced to buy already
    assert "Blockade" not in g["seats"][A]["discard"]   # set up work: stays out
    assert engine.duration_in_play(g, A, "Blockade")
    assert mv(g, B, {"type": "end_phase"})[0]           # B's uneventful turn
    # A's next turn start: the Silver comes to hand, the curse watcher expires
    assert "Silver" in g["seats"][A]["hand"]
    assert g["seats"][A]["dur_aside"] == []
    assert g["watchers"] == []
    assert mv(g, A, {"type": "end_phase"})[0]           # done: discarded at clean-up
    assert "Blockade" in g["seats"][A]["discard"]


def test_blockade_curse_only_on_the_gainers_own_turn():
    g = fresh()
    give_hand(g, A, ["Blockade"])
    g["seats"][A]["deck"] = ["Copper"] * 10
    assert play(g, A, "Blockade")[0]
    assert decide(g, A, pile="Silver")[0]
    # B gaining a copy during A's turn: no curse (not B's own turn)
    engine.gain(g, B, "Silver"); engine._drive(g)
    assert "Curse" not in g["seats"][B]["discard"]
    # the owner gaining a copy is never cursed
    engine.gain(g, A, "Silver"); engine._drive(g)
    assert "Curse" not in g["seats"][A]["discard"]
    assert mv(g, A, {"type": "end_phase"})[0]
    # B's own turn: buying a copy gains a Curse
    g["coins"] = 3
    assert mv(g, B, {"type": "buy", "card": "Silver"})[0]
    assert "Curse" in g["seats"][B]["discard"]
    assert g["supply"]["Curse"] == 9


def test_blockade_moat_reveal_blocks_the_later_curses():
    # Play-time immunity (Moat's reveal) is captured into the watcher: the
    # delayed curses respect it, per the official per-play attack semantics.
    g = fresh()
    give_hand(g, A, ["Blockade"])
    g["seats"][A]["deck"] = ["Copper"] * 10
    give_hand(g, B, ["Moat"] + ["Copper"] * 4)
    assert play(g, A, "Blockade")[0]
    assert g["pending_pid"] == B                        # the window opens
    assert decide(g, B, ids=["react:Moat"])[0]
    assert decide(g, A, pile="Silver")[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert mv(g, B, {"type": "end_phase"})[0]           # B's hand has Moat: action phase
    g["coins"] = 3
    assert mv(g, B, {"type": "buy", "card": "Silver"})[0]
    assert "Curse" not in g["seats"][B]["discard"]      # the Moat held


def test_blockade_no_eligible_pile_fails_to_set_up():
    g = fresh()
    for p in list(g["supply"]):
        if engine.cost(g, p) <= 4:
            g["supply"][p] = 0
    give_hand(g, A, ["Blockade"])
    assert play(g, A, "Blockade")[0]
    assert g["pending_pid"] is None                     # no pick, nothing registered
    entry = g["seats"][A]["dur_setup"][-1]
    assert entry["fx"] == [] and entry["watchers"] == 0
    assert mv(g, A, {"type": "end_phase"})[0]           # (also ends the game: piles)
    assert "Blockade" in g["seats"][A]["discard"]       # discarded normally


def test_blockade_on_curse_chains_through_the_pile():
    g = fresh()
    give_hand(g, A, ["Blockade"])
    g["seats"][A]["deck"] = ["Copper"] * 10
    assert play(g, A, "Blockade")[0]
    assert decide(g, A, pile="Curse")[0]
    assert g["seats"][A]["dur_aside"] == ["Curse"] and g["supply"]["Curse"] == 9
    assert mv(g, A, {"type": "end_phase"})[0]
    # B gains one Curse on B's own turn: the trigger chains until the pile is dry
    engine.gain(g, B, "Curse"); engine._drive(g)
    assert g["supply"]["Curse"] == 0
    assert g["seats"][B]["discard"].count("Curse") == 9


# --- Corsair ---------------------------------------------------------------------

def test_corsair_trashes_first_silver_or_gold_still_counting_its_coins():
    g = fresh()
    give_hand(g, A, ["Corsair"])
    g["seats"][A]["deck"] = ["Copper"] * 10
    assert play(g, A, "Corsair")[0]
    assert g["coins"] == 2 and g["pending_pid"] is None
    assert mv(g, A, {"type": "end_phase"})[0]
    assert engine.duration_in_play(g, A, "Corsair")
    give_hand(g, B, ["Copper", "Silver", "Gold"])
    assert mv(g, B, {"type": "play_treasure", "card": "Copper"})[0]
    assert g["seats"][B]["in_play"] == ["Copper"]       # Copper is safe
    assert mv(g, B, {"type": "play_treasure", "card": "Silver"})[0]
    assert g["coins"] == 3                              # the Silver's $2 counted
    assert "Silver" in g["trash"]                       # ...then it was trashed
    assert "Silver" not in g["seats"][B]["in_play"]
    assert mv(g, B, {"type": "play_treasure", "card": "Gold"})[0]
    assert g["coins"] == 6
    assert "Gold" in g["seats"][B]["in_play"]           # only the FIRST is hit
    assert mv(g, B, {"type": "end_phase"})[0]
    assert len(g["seats"][A]["hand"]) == 6              # next-turn +1 Card


def test_corsair_not_cumulative_with_two_copies():
    g = fresh()
    give_hand(g, A, ["Corsair", "Corsair"])
    g["seats"][A]["deck"] = ["Copper"] * 10
    g["actions"] = 2
    assert play(g, A, "Corsair")[0]
    assert play(g, A, "Corsair")[0]
    assert g["coins"] == 4
    assert mv(g, A, {"type": "end_phase"})[0]
    give_hand(g, B, ["Silver", "Gold"])
    assert mv(g, B, {"type": "play_treasure", "card": "Silver"})[0]
    assert "Silver" in g["trash"]
    assert mv(g, B, {"type": "play_treasure", "card": "Gold"})[0]
    assert "Gold" not in g["trash"]                     # the second play is safe
    assert "Gold" in g["seats"][B]["in_play"]


# --- Island ----------------------------------------------------------------------

def test_island_sets_aside_itself_and_a_hand_card():
    g = fresh()
    give_hand(g, A, ["Island", "Gold", "Copper"])
    assert play(g, A, "Island")[0]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 1 and c["max"] == 1
    assert decide(g, A, cards=["Gold"])[0]
    assert sorted(g["seats"][A]["island"]) == ["Gold", "Island"]
    assert g["seats"][A]["in_play"] == []
    assert "Gold" not in g["seats"][A]["hand"]
    # the Island mat is open information on the wire
    vb = engine.player_view(g, B)
    assert sorted(vb["seats"][A]["island"]) == ["Gold", "Island"]
    # mat cards are the owner's at game end: the Island scores its 2 VP there
    g["seats"][A]["deck"] = []
    g["seats"][A]["discard"] = []
    give_hand(g, A, [])
    assert engine.score_game(g)[A]["vp"] == 2


def test_island_with_empty_hand_goes_alone():
    g = fresh()
    give_hand(g, A, ["Island"])
    assert play(g, A, "Island")[0]
    assert g["pending_pid"] is None
    assert g["seats"][A]["island"] == ["Island"]
    assert g["seats"][A]["in_play"] == []


def test_island_throne_room_second_play_sets_aside_a_hand_card_only():
    g = fresh()
    give_hand(g, A, ["Throne Room", "Island", "Copper", "Estate"])
    assert play(g, A, "Throne Room")[0]
    assert decide(g, A, cards=["Island"])[0]
    assert decide(g, A, cards=["Copper"])[0]            # first play: card + Island
    assert decide(g, A, cards=["Estate"])[0]            # replay: hand card only
    assert g["seats"][A]["island"] == ["Copper", "Island", "Estate"]
    assert g["seats"][A]["island"].count("Island") == 1
    assert "Throne Room" in g["seats"][A]["in_play"]    # Island isn't a Duration


# --- Monkey ----------------------------------------------------------------------

def test_monkey_draws_on_right_players_gains():
    g = fresh()
    give_hand(g, A, ["Monkey"])
    g["seats"][A]["deck"] = ["Copper"] * 10
    assert play(g, A, "Monkey")[0]
    # in 2p the right-hand player is the opponent; it triggers on ANY turn —
    # here B gains during the OWNER's turn and A still draws
    engine.gain(g, B, "Copper"); engine._drive(g)
    assert len(g["seats"][A]["hand"]) == 1
    # the owner's own gains never trigger it
    engine.gain(g, A, "Silver"); engine._drive(g)
    assert len(g["seats"][A]["hand"]) == 1
    assert mv(g, A, {"type": "end_phase"})[0]
    # B's turn: a buy draws A a card immediately
    g["coins"] = 3
    assert mv(g, B, {"type": "buy", "card": "Silver"})[0]
    assert len(g["seats"][A]["hand"]) == 6
    assert mv(g, B, {"type": "end_phase"})[0]
    assert len(g["seats"][A]["hand"]) == 7              # next-turn +1 Card fx


# --- Native Village --------------------------------------------------------------

def test_native_village_mat_option_is_unseen():
    g = fresh()
    give_hand(g, A, ["Native Village"])
    g["seats"][A]["deck"] = ["Gold", "Copper", "Copper"]
    n0 = len(g["log"])
    assert play(g, A, "Native Village")[0]
    assert g["actions"] == 2
    ids = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
    assert ids == ["mat", "take"]                       # chosen BEFORE seeing anything
    assert decide(g, A, ids=["mat"])[0]
    assert g["seats"][A]["village_mat"] == ["Gold"]
    assert g["seats"][A]["deck"][0] == "Copper"
    assert g["seats"][A]["hand"] == []
    # face down: the card's name never reaches the log
    for e in g["log"][n0:]:
        assert "Gold" not in str(e.get("cards", "")) and e.get("card") != "Gold"
    # ...and other seats see only a count; the owner may look any time
    vb = engine.player_view(g, B)
    assert vb["seats"][A]["village_count"] == 1 and "village_mat" not in vb["seats"][A]
    assert engine.player_view(g, A)["seats"][A]["village_mat"] == ["Gold"]


def test_native_village_take_option_and_empty_deck():
    g = fresh()
    give_hand(g, A, ["Native Village", "Native Village"])
    g["seats"][A]["village_mat"] = ["Smithy", "Gold"]
    assert play(g, A, "Native Village")[0]
    assert decide(g, A, ids=["take"])[0]
    assert g["seats"][A]["village_mat"] == []
    assert "Smithy" in g["seats"][A]["hand"] and "Gold" in g["seats"][A]["hand"]
    # option 1 with nothing to look at sets nothing aside
    g["seats"][A]["deck"] = []
    g["seats"][A]["discard"] = []
    assert play(g, A, "Native Village")[0]
    assert decide(g, A, ids=["mat"])[0]
    assert g["seats"][A]["village_mat"] == []


# --- Outpost ---------------------------------------------------------------------

def test_outpost_extra_turn_three_cards_and_no_third_turn():
    g = fresh()
    give_hand(g, A, ["Outpost"])
    g["seats"][A]["deck"] = ["Outpost"] + ["Copper"] * 9
    assert play(g, A, "Outpost")[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    # the extra turn: still A, a 3-card hand, a counted turn
    assert g["turn"] == A and g["extra_turn"] is True
    assert len(g["seats"][A]["hand"]) == 3
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Copper", "Outpost"]
    assert g["seats"][A]["turns_taken"] == 1
    assert g["phase"] == "action"
    # a second Outpost on the extra turn: draws 3 again but NO 3rd turn in a row
    assert play(g, A, "Outpost")[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert g["turn"] == B and g["extra_turn"] is False
    assert len(g["seats"][A]["hand"]) == 3              # the 3-draw still applied
    assert g["seats"][A]["turns_taken"] == 2            # increments per turn
    # the first Outpost resolved and discarded; the second still on the table
    assert g["seats"][A]["discard"].count("Outpost") == 1
    assert engine.duration_in_play(g, A, "Outpost")


# --- Pirate ----------------------------------------------------------------------

def test_pirate_duration_gains_a_treasure_to_hand():
    g = fresh()
    give_hand(g, A, ["Pirate"])
    g["seats"][A]["deck"] = ["Copper"] * 10
    assert play(g, A, "Pirate")[0]
    assert g["pending_pid"] is None                     # nothing this turn
    assert mv(g, A, {"type": "end_phase"})[0]
    assert engine.duration_in_play(g, A, "Pirate")
    assert mv(g, B, {"type": "end_phase"})[0]
    # A's next turn start: pick a Treasure costing up to $6, gained to HAND
    assert g["pending_pid"] == A and g["pending_kind"] == "choose_pile"
    assert g["pending"][-1]["constraint"]["piles"] == ["Copper", "Gold", "Silver"]
    assert decide(g, A, pile="Gold")[0]
    assert "Gold" in g["seats"][A]["hand"]
    assert len(g["seats"][A]["hand"]) == 6
    assert g["supply"]["Gold"] == 29


def test_pirate_reaction_plays_from_hand_on_a_treasure_gain():
    g = fresh()
    give_hand(g, B, ["Pirate"] + ["Copper"] * 4)
    assert mv(g, A, {"type": "end_phase"})[0]
    g["coins"] = 3
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    # the gain opens B's window
    assert g["pending_pid"] == B and g["pending"][-1]["card"] == "Pirate"
    assert decide(g, B, ids=["play"])[0]
    assert g["seats"][B]["in_play"] == ["Pirate"]
    assert "Pirate" not in g["seats"][B]["hand"]
    assert g["turn_ctx"]["actions_played"] == 0         # off-turn play doesn't count
    assert mv(g, A, {"type": "end_phase"})[0]
    # An off-turn-played Duration resolves at the owner's IMMEDIATE next turn
    # start (the _start_of_turn dur_setup sweep): the gain prompt is already up.
    assert g["turn"] == B and g["pending_pid"] == B and g["pending_kind"] == "choose_pile"
    assert decide(g, B, pile="Silver")[0]
    assert "Silver" in g["seats"][B]["hand"]
    # spent: the Pirate discards from in_play at B's ordinary clean-up
    assert mv(g, B, {"type": "end_phase"})[0]
    assert "Pirate" not in g["seats"][B]["in_play"]
    assert not engine.duration_in_play(g, B, "Pirate")


def test_pirate_multiple_copies_react_to_one_gain_and_decline():
    g = fresh()
    give_hand(g, B, ["Pirate", "Pirate", "Copper"])
    assert mv(g, A, {"type": "end_phase"})[0]
    g["coins"] = 3
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    assert g["pending_pid"] == B
    assert decide(g, B, ids=["play"])[0]
    # a second Pirate remains in hand: the window is re-offered for the same gain
    assert g["pending_pid"] == B and g["pending"][-1]["card"] == "Pirate"
    assert decide(g, B, ids=["decline"])[0]
    assert g["pending_pid"] is None
    assert g["seats"][B]["in_play"] == ["Pirate"]
    assert g["seats"][B]["hand"].count("Pirate") == 1   # declined one stays put


# --- Sailor ----------------------------------------------------------------------

def test_sailor_plays_a_gained_duration_once_this_turn():
    g = fresh()
    give_hand(g, A, ["Sailor"])
    assert play(g, A, "Sailor")[0]
    assert g["actions"] == 1
    g["buys"] = 3
    g["coins"] = 20
    # a non-Duration gain opens no window
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    assert g["pending_pid"] is None
    # a Duration gain: may play it right away, from where it landed
    assert mv(g, A, {"type": "buy", "card": "Monkey"})[0]
    assert g["pending_pid"] == A and g["pending"][-1]["card"] == "Sailor"
    assert decide(g, A, ids=["play"])[0]
    assert "Monkey" in g["seats"][A]["in_play"]
    assert "Monkey" not in g["seats"][A]["discard"]
    assert any(w["card"] == "Monkey" for w in g["watchers"])   # its effect ran
    # once this turn: a second gained Duration gets no window
    assert mv(g, A, {"type": "buy", "card": "Corsair"})[0]
    assert g["pending_pid"] is None
    assert "Corsair" in g["seats"][A]["discard"]


def test_sailor_next_turn_coins_and_optional_trash():
    g = fresh()
    give_hand(g, A, ["Sailor", "Copper"])
    g["seats"][A]["deck"] = ["Copper"] * 10
    assert play(g, A, "Sailor")[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert engine.duration_in_play(g, A, "Sailor")      # persists unconditionally
    assert mv(g, B, {"type": "end_phase"})[0]
    # A's next turn start: +$2 and the may-trash
    assert g["coins"] == 2
    assert g["pending_pid"] == A
    c = g["pending"][-1]["constraint"]
    assert c["purpose"] == "trash" and c["min"] == 0 and c["max"] == 1
    assert decide(g, A, cards=["Copper"])[0]
    assert "Copper" in g["trash"]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert "Sailor" in g["seats"][A]["discard"]         # done: discarded at clean-up


# --- Smugglers -------------------------------------------------------------------

def test_smugglers_gains_a_copy_of_the_right_players_last_turn_gain():
    g = fresh()
    g["seats"][A]["deck"].insert(0, "Smugglers")        # reaches A's turn-3 hand
    assert mv(g, A, {"type": "end_phase"})[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    g["coins"] = 6
    assert mv(g, B, {"type": "buy", "card": "Gold"})[0]
    assert mv(g, B, {"type": "end_phase"})[0]
    assert g["last_turn_gains"][B] == ["Gold"]
    assert g["turn"] == A and g["phase"] == "action"
    assert play(g, A, "Smugglers")[0]
    assert g["pending_kind"] == "choose_pile"
    assert g["pending"][-1]["constraint"]["piles"] == ["Gold"]   # $6 is eligible
    assert decide(g, A, pile="Gold")[0]
    assert g["seats"][A]["discard"][-1] == "Gold"


def test_smugglers_nothing_eligible_does_nothing():
    # right player has gained nothing yet
    g = fresh()
    give_hand(g, A, ["Smugglers"])
    assert play(g, A, "Smugglers")[0]
    assert g["pending_pid"] is None
    # a >$6 gain is not a candidate (cost is checked NOW)
    g = fresh()
    g["seats"][A]["deck"].insert(0, "Smugglers")
    assert mv(g, A, {"type": "end_phase"})[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    g["coins"] = 8
    assert mv(g, B, {"type": "buy", "card": "Province"})[0]
    assert mv(g, B, {"type": "end_phase"})[0]
    assert play(g, A, "Smugglers")[0]
    assert g["pending_pid"] is None


def test_smugglers_may_choose_an_empty_pile_and_gain_nothing():
    g = fresh()
    g["seats"][A]["deck"].insert(0, "Smugglers")
    assert mv(g, A, {"type": "end_phase"})[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    g["coins"] = 6
    assert mv(g, B, {"type": "buy", "card": "Gold"})[0]
    assert mv(g, B, {"type": "end_phase"})[0]
    g["supply"]["Gold"] = 0                             # the pile ran dry since
    assert play(g, A, "Smugglers")[0]
    assert g["pending"][-1]["constraint"]["piles"] == ["Gold"]   # still offered
    assert decide(g, A, pile="Gold")[0]
    assert "Gold" not in g["seats"][A]["discard"]       # gained nothing, harmlessly
    assert g["pending_pid"] is None


# --- Tactician -------------------------------------------------------------------

def test_tactician_discards_the_hand_for_a_megaturn():
    g = fresh()
    give_hand(g, A, ["Tactician", "Copper", "Estate", "Copper"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert play(g, A, "Tactician")[0]
    assert g["seats"][A]["hand"] == []                  # one bulk discard
    assert g["seats"][A]["discard"][-3:] == ["Copper", "Estate", "Copper"]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert engine.duration_in_play(g, A, "Tactician")
    assert mv(g, B, {"type": "end_phase"})[0]
    # the megaturn: 5 (clean-up) + 5 (fx) cards, +1 Action, +1 Buy
    assert len(g["seats"][A]["hand"]) == 10
    assert g["actions"] == 2 and g["buys"] == 2


def test_tactician_empty_hand_fails_and_throne_room_does_not_double():
    g = fresh()
    give_hand(g, A, ["Tactician"])
    assert play(g, A, "Tactician")[0]
    entry = g["seats"][A]["dur_setup"][-1]
    assert entry["fx"] == []                            # failed to set up
    assert mv(g, A, {"type": "end_phase"})[0]
    assert "Tactician" in g["seats"][A]["discard"]      # discarded normally
    # Throne Room: the first play empties the hand, the replay registers nothing
    g = fresh()
    give_hand(g, A, ["Throne Room", "Tactician", "Copper"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert play(g, A, "Throne Room")[0]
    assert decide(g, A, cards=["Tactician"])[0]
    entry = [e for e in g["seats"][A]["dur_setup"] if e["card"] == "Tactician"][-1]
    assert len(entry["fx"]) == 1                        # ONE bonus, not two
    assert entry["riders"] == ["Throne Room"]           # TR stays out with it
    assert mv(g, A, {"type": "end_phase"})[0]
    assert "Throne Room" not in g["seats"][A]["discard"]
    assert mv(g, B, {"type": "end_phase"})[0]
    assert len(g["seats"][A]["hand"]) == 10
    assert g["actions"] == 2 and g["buys"] == 2         # not 3


# --- Treasure Map ----------------------------------------------------------------

def test_treasure_map_pair_gains_four_golds_onto_the_deck():
    g = fresh()
    give_hand(g, A, ["Treasure Map", "Treasure Map"])
    g["seats"][A]["deck"] = ["Copper"] * 5
    assert play(g, A, "Treasure Map")[0]
    assert g["trash"].count("Treasure Map") == 2        # both trashed, no choice
    assert g["seats"][A]["in_play"] == []
    assert g["seats"][A]["deck"][:4] == ["Gold"] * 4    # onto the deck
    assert g["supply"]["Gold"] == 26


def test_treasure_map_single_and_throne_room_gain_no_golds():
    g = fresh()
    give_hand(g, A, ["Treasure Map"])
    assert play(g, A, "Treasure Map")[0]
    assert g["trash"] == ["Treasure Map"]               # just the played copy
    assert g["supply"]["Gold"] == 30
    assert "Gold" not in g["seats"][A]["deck"]
    # Throne Room: the replay's "trash this" fails -> no second batch of Golds
    g = fresh()
    give_hand(g, A, ["Throne Room", "Treasure Map", "Treasure Map", "Treasure Map"])
    g["seats"][A]["deck"] = ["Copper"] * 5
    assert play(g, A, "Throne Room")[0]
    assert decide(g, A, cards=["Treasure Map"])[0]
    assert g["trash"].count("Treasure Map") == 3        # played + both hand copies
    assert g["seats"][A]["deck"].count("Gold") == 4     # once, not twice
    assert g["supply"]["Gold"] == 26


# --- Treasury --------------------------------------------------------------------

def test_treasury_topdeck_offered_and_drawn_in_cleanup():
    g = fresh()
    give_hand(g, A, ["Treasury"])
    g["seats"][A]["deck"] = ["Silver"] + ["Copper"] * 6
    assert play(g, A, "Treasury")[0]
    assert g["actions"] == 1 and g["coins"] == 1
    assert g["seats"][A]["hand"] == ["Silver"]          # +1 Card
    g["coins"] = 3
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]   # a non-Victory gain
    assert mv(g, A, {"type": "end_phase"})[0]
    # end of the buy phase: the may-topdeck prompt
    assert g["pending_pid"] == A and g["pending"][-1]["card"] == "Treasury"
    c = g["pending"][-1]["constraint"]
    assert c["cards"] == ["Treasury"] and c["min"] == 0 and c["purpose"] == "topdeck"
    assert decide(g, A, cards=["Treasury"])[0]
    # topdecked before clean-up: the clean-up draw picks it up
    assert g["turn"] == B
    assert "Treasury" in g["seats"][A]["hand"]
    assert "Treasury" not in g["seats"][A]["discard"]
    tops = [e for e in g["log"] if e["event"] == "topdeck"]
    assert tops and tops[-1]["card"] == "Treasury"      # public


def test_treasury_decline_discards_and_victory_gain_blocks_the_prompt():
    g = fresh()
    give_hand(g, A, ["Treasury"])
    g["seats"][A]["deck"] = ["Copper"] * 8
    assert play(g, A, "Treasury")[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert g["pending_pid"] == A
    assert decide(g, A, cards=[])[0]                    # declined
    assert "Treasury" in g["seats"][A]["discard"]
    # gaining a Victory card in the buy phase: no prompt at all
    g = fresh()
    give_hand(g, A, ["Treasury"])
    g["seats"][A]["deck"] = ["Copper"] * 8
    assert play(g, A, "Treasury")[0]
    g["coins"] = 2
    assert mv(g, A, {"type": "buy", "card": "Estate"})[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert g["turn"] == B                               # straight through clean-up
    assert "Treasury" in g["seats"][A]["discard"]
