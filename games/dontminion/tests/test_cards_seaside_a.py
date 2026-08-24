"""Seaside batch-A card tests — Astrolabe, Bazaar, Caravan, Cutpurse, Fishing
Village, Haven, Lighthouse, Lookout, Merchant Ship, Salvager, Sea Chart,
Sea Witch, Tide Pools, Warehouse, Wharf.

Positions are arranged by mutating the game dict directly (the repo's
board-fixture idiom). give_hand breaks card conservation, so no test here
asserts the census invariant (test_soak owns that).

Duration lifecycle assertions per games/dontminion/CLAUDE.md Kernel v2: a
duration played this turn must survive its own clean-up (seat["duration"], not
discard), fire its fx at the owner's NEXT turn start, and land in the discard
at THAT turn's clean-up.
"""

from games.dontminion import engine

A, B = "alice", "bob"

# Pinned kingdom = exactly this batch's 15 cards (the forced-kingdom test seam).
KA = ["Astrolabe", "Bazaar", "Caravan", "Cutpurse", "Fishing Village", "Haven",
      "Lighthouse", "Lookout", "Merchant Ship", "Salvager", "Sea Chart",
      "Sea Witch", "Tide Pools", "Warehouse", "Wharf"]
# kingdom= mixes sets freely: Militia (attack fixture) + Throne Room (rider).
KX = KA + ["Militia", "Throne Room"]


def fresh(players=(A, B), seed=42, kingdom=tuple(KA)):
    return engine.new_game(list(players), ["seaside"], seed=seed,
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


def dur_cards(g, pid):
    return [e["card"] for e in g["seats"][pid]["duration"]]


def pad_deck(g, pid, n=8):
    """Top up the deck before a clean-up whose discard pile the test asserts —
    a short deck would shuffle the just-discarded cards back in."""
    g["seats"][pid]["deck"] = ["Copper"] * n + g["seats"][pid]["deck"]


# --- Bazaar (vanilla) --------------------------------------------------------

def test_bazaar():
    g = fresh()
    give_hand(g, A, ["Bazaar"])
    g["seats"][A]["deck"] = ["Silver", "Gold"]
    assert mv(g, A, {"type": "play_action", "card": "Bazaar"})[0]
    assert g["seats"][A]["hand"] == ["Silver"]
    assert g["actions"] == 2 and g["coins"] == 1 and g["buys"] == 1


# --- Astrolabe (Treasure-Duration) -------------------------------------------

def test_astrolabe_duration_cycle():
    g = fresh()
    give_hand(g, A, ["Astrolabe"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 6
    assert mv(g, A, {"type": "end_phase"})[0]           # action -> buy
    assert mv(g, A, {"type": "play_treasure", "card": "Astrolabe"})[0]
    assert g["coins"] == 1 and g["buys"] == 2           # printed $1 + the +1 Buy
    assert "Astrolabe" in s["in_play"]
    end_turn(g, A)
    assert "Astrolabe" not in s["discard"]              # stayed on the table
    assert dur_cards(g, A) == ["Astrolabe"]
    end_turn(g, B)
    # Owner's next turn: the fx fired ($1 + 1 Buy on top of the turn's base).
    assert g["turn"] == A and g["coins"] == 1 and g["buys"] == 2
    pad_deck(g, A)
    end_turn(g, A)
    assert "Astrolabe" in s["discard"] and dur_cards(g, A) == []


# --- Caravan -----------------------------------------------------------------

def test_caravan_duration_cycle():
    g = fresh()
    give_hand(g, A, ["Caravan"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 8
    assert mv(g, A, {"type": "play_action", "card": "Caravan"})[0]
    assert len(s["hand"]) == 1 and g["actions"] == 1    # +1 Card, +1 Action
    end_turn(g, A)
    assert "Caravan" not in s["discard"]
    assert dur_cards(g, A) == ["Caravan"]
    end_turn(g, B)
    assert g["turn"] == A and len(s["hand"]) == 6       # 5 dealt + 1 fx draw
    pad_deck(g, A)
    end_turn(g, A)
    assert "Caravan" in s["discard"] and dur_cards(g, A) == []


def test_caravan_throne_room_stays_out():
    g = fresh(kingdom=KX)
    give_hand(g, A, ["Throne Room", "Caravan"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 12
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert decide(g, A, cards=["Caravan"])[0]
    assert len(s["hand"]) == 2 and g["actions"] == 2    # doubled draw + actions
    end_turn(g, A)
    # Both the Caravan and the Throne Room that played it stay on the table.
    assert "Caravan" not in s["discard"] and "Throne Room" not in s["discard"]
    entries = s["duration"]
    assert len(entries) == 1 and entries[0]["card"] == "Caravan"
    assert entries[0]["riders"] == ["Throne Room"]
    end_turn(g, B)
    assert g["turn"] == A and len(s["hand"]) == 7       # 5 dealt + doubled fx
    pad_deck(g, A)
    end_turn(g, A)
    assert "Caravan" in s["discard"] and "Throne Room" in s["discard"]
    assert dur_cards(g, A) == []


# --- Cutpurse ----------------------------------------------------------------

def test_cutpurse_discards_exactly_one_copper():
    g = fresh()
    give_hand(g, A, ["Cutpurse"])
    give_hand(g, B, ["Copper", "Copper", "Estate"])
    assert mv(g, A, {"type": "play_action", "card": "Cutpurse"})[0]
    assert g["coins"] == 2
    assert g["pending_pid"] is None                     # mandatory, no choice
    assert sorted(g["seats"][B]["hand"]) == ["Copper", "Estate"]
    assert g["seats"][B]["discard"] == ["Copper"]


def test_cutpurse_no_copper_reveals_hand():
    g = fresh()
    give_hand(g, A, ["Cutpurse"])
    give_hand(g, B, ["Estate", "Silver"])
    assert mv(g, A, {"type": "play_action", "card": "Cutpurse"})[0]
    assert sorted(g["seats"][B]["hand"]) == ["Estate", "Silver"]
    assert g["seats"][B]["discard"] == []
    rev = [e for e in g["log"] if e["event"] == "reveal"][-1]
    assert rev["pid"] == B and rev["source"] == "hand"
    assert sorted(rev["cards"]) == ["Estate", "Silver"]
    # An empty hand reveals empty (it proves the no-Copper claim).
    g = fresh()
    give_hand(g, A, ["Cutpurse"])
    give_hand(g, B, [])
    assert mv(g, A, {"type": "play_action", "card": "Cutpurse"})[0]
    rev = [e for e in g["log"] if e["event"] == "reveal"][-1]
    assert rev["pid"] == B and rev["cards"] == []


# --- Fishing Village ---------------------------------------------------------

def test_fishing_village_duration_cycle():
    g = fresh()
    give_hand(g, A, ["Fishing Village"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 6
    assert mv(g, A, {"type": "play_action", "card": "Fishing Village"})[0]
    assert g["actions"] == 2 and g["coins"] == 1        # 1 - 1 + 2, +$1
    end_turn(g, A)
    assert "Fishing Village" not in s["discard"]
    assert dur_cards(g, A) == ["Fishing Village"]
    end_turn(g, B)
    assert g["turn"] == A and g["actions"] == 2 and g["coins"] == 1
    pad_deck(g, A)
    end_turn(g, A)
    assert "Fishing Village" in s["discard"] and dur_cards(g, A) == []


# --- Haven -------------------------------------------------------------------

def test_haven_sets_aside_and_returns():
    g = fresh()
    give_hand(g, A, ["Haven", "Silver"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 8
    assert mv(g, A, {"type": "play_action", "card": "Haven"})[0]
    assert g["actions"] == 1
    c = g["pending"][-1]["constraint"]
    assert g["pending_kind"] == "choose_cards" and g["pending_pid"] == A
    assert c["min"] == 1 and c["max"] == 1 and c["purpose"] == "set aside"
    assert sorted(c["cards"]) == ["Copper", "Silver"]   # hand after the draw
    assert decide(g, A, cards=["Silver"])[0]
    assert s["dur_aside"] == ["Silver"] and "Silver" not in s["hand"]
    end_turn(g, A)
    assert dur_cards(g, A) == ["Haven"]
    # Set-aside card is NOT in hand (nor discard) across the opponent's turn.
    assert s["dur_aside"] == ["Silver"]
    assert "Silver" not in s["hand"] and "Silver" not in s["discard"]
    end_turn(g, B)
    assert g["turn"] == A
    assert s["dur_aside"] == [] and "Silver" in s["hand"]
    assert len(s["hand"]) == 6                          # 5 dealt + the return
    pad_deck(g, A)
    end_turn(g, A)
    assert "Haven" in s["discard"] and dur_cards(g, A) == []


def test_haven_empty_hand_fails_setup():
    g = fresh()
    give_hand(g, A, ["Haven"])
    s = g["seats"][A]
    s["deck"], s["discard"] = [], []                    # the draw finds nothing
    assert mv(g, A, {"type": "play_action", "card": "Haven"})[0]
    assert g["pending_pid"] is None                     # no frame, no fx
    pad_deck(g, A)
    end_turn(g, A)
    # Failed setup: discarded at THIS turn's clean-up, never persists.
    assert "Haven" in s["discard"] and dur_cards(g, A) == []


# --- Lighthouse --------------------------------------------------------------

def test_lighthouse_protects_until_own_next_turn():
    g = fresh(kingdom=KX)
    sa, sb = g["seats"][A], g["seats"][B]
    give_hand(g, A, ["Lighthouse"])
    sa["deck"] = ["Copper"] * 12
    sb["deck"] = ["Copper"] * 12
    assert mv(g, A, {"type": "play_action", "card": "Lighthouse"})[0]
    assert g["actions"] == 1 and g["coins"] == 1
    give_hand(g, B, ["Militia"])                        # staged pre-hand-off
    end_turn(g, A)
    assert dur_cards(g, A) == ["Lighthouse"]
    assert engine.attack_protected(g, A)
    # Opponent's attack: A is unaffected and gets NO window/prompt at all.
    assert g["turn"] == B
    assert mv(g, B, {"type": "play_action", "card": "Militia"})[0]
    assert g["pending_pid"] is None
    assert len(sa["hand"]) == 5                         # untouched
    end_turn(g, B)
    # Owner's next turn: the +$1 fx fired and the protection is GONE.
    assert g["turn"] == A and g["coins"] == 1
    assert not engine.attack_protected(g, A)
    give_hand(g, B, ["Militia"])
    end_turn(g, A)
    assert "Lighthouse" in sa["discard"]
    # Second Militia hits normally: discard-to-3 prompt for A.
    assert mv(g, B, {"type": "play_action", "card": "Militia"})[0]
    assert g["pending_pid"] == A and g["pending_kind"] == "choose_cards"
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 2 and c["max"] == 2              # 5-card hand -> 3
    assert decide(g, A, cards=sa["hand"][:2])[0]
    assert len(sa["hand"]) == 3


# --- Lookout -----------------------------------------------------------------

def test_lookout_three_cards_trash_discard_topdeck():
    g = fresh()
    give_hand(g, A, ["Lookout"])
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Estate", "Copper", "Silver", "Gold"], []
    assert mv(g, A, {"type": "play_action", "card": "Lookout"})[0]
    assert g["actions"] == 1
    c = g["pending"][-1]["constraint"]
    assert c["purpose"] == "trash" and c["min"] == 1 and c["max"] == 1
    assert sorted(c["cards"]) == ["Copper", "Estate", "Silver"]
    assert decide(g, A, cards=["Estate"])[0]            # mandatory trash
    assert g["trash"] == ["Estate"]
    c = g["pending"][-1]["constraint"]
    assert c["purpose"] == "discard" and sorted(c["cards"]) == ["Copper", "Silver"]
    assert decide(g, A, cards=["Copper"])[0]
    assert s["discard"] == ["Copper"]
    assert s["deck"] == ["Silver", "Gold"]              # last one back on top
    assert s["aside"] == [] and g["pending_pid"] is None


def test_lookout_two_cards_trash_then_forced_discard():
    g = fresh()
    give_hand(g, A, ["Lookout"])
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Estate", "Copper"], []
    assert mv(g, A, {"type": "play_action", "card": "Lookout"})[0]
    c = g["pending"][-1]["constraint"]
    assert c["purpose"] == "trash" and sorted(c["cards"]) == ["Copper", "Estate"]
    assert decide(g, A, cards=["Estate"])[0]
    # Single-card remainder: no choice of WHICH -> discarded without a frame.
    assert g["pending_pid"] is None
    assert g["trash"] == ["Estate"] and s["discard"] == ["Copper"]
    assert s["deck"] == [] and s["aside"] == []


def test_lookout_one_card_forced_trash():
    g = fresh()
    give_hand(g, A, ["Lookout"])
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Estate"], []
    assert mv(g, A, {"type": "play_action", "card": "Lookout"})[0]
    assert g["pending_pid"] is None                     # forced: no frame
    assert g["trash"] == ["Estate"]
    assert s["deck"] == [] and s["discard"] == [] and s["aside"] == []


def test_lookout_empty_deck_and_discard():
    g = fresh()
    give_hand(g, A, ["Lookout"])
    s = g["seats"][A]
    s["deck"], s["discard"] = [], []
    assert mv(g, A, {"type": "play_action", "card": "Lookout"})[0]
    assert g["actions"] == 1 and g["pending_pid"] is None
    assert g["trash"] == [] and s["aside"] == []


# --- Merchant Ship -----------------------------------------------------------

def test_merchant_ship_duration_cycle():
    g = fresh()
    give_hand(g, A, ["Merchant Ship"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 6
    assert mv(g, A, {"type": "play_action", "card": "Merchant Ship"})[0]
    assert g["coins"] == 2
    end_turn(g, A)
    assert "Merchant Ship" not in s["discard"]
    assert dur_cards(g, A) == ["Merchant Ship"]
    end_turn(g, B)
    assert g["turn"] == A and g["coins"] == 2
    pad_deck(g, A)
    end_turn(g, A)
    assert "Merchant Ship" in s["discard"] and dur_cards(g, A) == []


# --- Salvager ----------------------------------------------------------------

def test_salvager_trashes_for_cost():
    g = fresh()
    give_hand(g, A, ["Salvager", "Gold"])
    assert mv(g, A, {"type": "play_action", "card": "Salvager"})[0]
    assert g["buys"] == 2
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 1 and c["max"] == 1 and c["purpose"] == "trash"
    assert decide(g, A, cards=["Gold"])[0]
    assert g["trash"] == ["Gold"] and g["coins"] == 6


def test_salvager_cost_at_trash_time_with_bridges():
    g = fresh()
    give_hand(g, A, ["Salvager", "Gold"])
    g["turn_ctx"]["bridges"] = 2                        # cost 6 -> 4 at trash
    assert mv(g, A, {"type": "play_action", "card": "Salvager"})[0]
    assert decide(g, A, cards=["Gold"])[0]
    assert g["coins"] == 4


def test_salvager_empty_hand_keeps_the_buy():
    g = fresh()
    give_hand(g, A, ["Salvager"])
    assert mv(g, A, {"type": "play_action", "card": "Salvager"})[0]
    assert g["buys"] == 2 and g["pending_pid"] is None
    assert g["trash"] == [] and g["coins"] == 0


# --- Sea Chart ---------------------------------------------------------------

def test_sea_chart_hit_copy_in_play():
    # The played Sea Chart itself is in play, so a revealed Sea Chart always hits.
    g = fresh()
    give_hand(g, A, ["Sea Chart"])
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Copper", "Sea Chart", "Gold"], []
    assert mv(g, A, {"type": "play_action", "card": "Sea Chart"})[0]
    assert g["actions"] == 1
    assert sorted(s["hand"]) == ["Copper", "Sea Chart"]
    assert s["deck"] == ["Gold"] and s["aside"] == []
    # putting the revealed match into hand is LOGGED (was silent)
    assert any(e.get("event") == "to_hand" and e.get("cards") == ["Sea Chart"]
               for e in g["log"])


def test_sea_chart_miss_goes_back_on_top():
    g = fresh()
    give_hand(g, A, ["Sea Chart"])
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Copper", "Gold", "Estate"], []
    assert mv(g, A, {"type": "play_action", "card": "Sea Chart"})[0]
    assert s["hand"] == ["Copper"]
    assert s["deck"] == ["Gold", "Estate"] and s["aside"] == []
    rev = [e for e in g["log"] if e["event"] == "reveal"][-1]
    assert rev["cards"] == ["Gold"] and rev["source"] == "deck"


def test_sea_chart_counts_persisting_durations():
    g = fresh()
    give_hand(g, A, ["Caravan"])
    g["seats"][A]["deck"] = ["Copper"] * 8
    assert mv(g, A, {"type": "play_action", "card": "Caravan"})[0]
    end_turn(g, A)
    end_turn(g, B)
    assert g["turn"] == A and dur_cards(g, A) == ["Caravan"]
    s = g["seats"][A]
    give_hand(g, A, ["Sea Chart"])
    s["deck"], s["discard"] = ["Copper", "Caravan"], []
    g["phase"] = "action"       # the no-action dealt hand auto-advanced to buy
    assert mv(g, A, {"type": "play_action", "card": "Sea Chart"})[0]
    # The persisting Caravan is "in play" -> the revealed copy goes to hand.
    assert "Caravan" in s["hand"] and s["deck"] == []


# --- Sea Witch ---------------------------------------------------------------

def test_sea_witch_curses_now_and_sifts_next_turn():
    g = fresh()
    give_hand(g, A, ["Sea Witch"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 10
    assert mv(g, A, {"type": "play_action", "card": "Sea Witch"})[0]
    assert len(s["hand"]) == 2                          # +2 Cards
    assert g["seats"][B]["discard"] == ["Curse"]        # play-time attack
    assert g["supply"]["Curse"] == 9
    end_turn(g, A)
    assert "Sea Witch" not in s["discard"]
    assert dur_cards(g, A) == ["Sea Witch"]
    end_turn(g, B)
    # Next turn: draw 2 THEN discard exactly 2 (from the whole hand).
    assert g["turn"] == A and len(s["hand"]) == 7
    assert g["pending_pid"] == A and g["pending_kind"] == "choose_cards"
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 2 and c["max"] == 2 and c["purpose"] == "discard"
    assert decide(g, A, cards=["Copper", "Copper"])[0]
    assert len(s["hand"]) == 5
    pad_deck(g, A)
    end_turn(g, A)
    assert "Sea Witch" in s["discard"] and dur_cards(g, A) == []


# --- Tide Pools --------------------------------------------------------------

def test_tide_pools_duration_cycle():
    g = fresh()
    give_hand(g, A, ["Tide Pools"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 10
    assert mv(g, A, {"type": "play_action", "card": "Tide Pools"})[0]
    assert len(s["hand"]) == 3 and g["actions"] == 1
    end_turn(g, A)
    assert dur_cards(g, A) == ["Tide Pools"]
    end_turn(g, B)
    assert g["turn"] == A
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 2 and c["max"] == 2 and c["purpose"] == "discard"
    assert decide(g, A, cards=["Copper", "Copper"])[0]
    assert len(s["hand"]) == 3
    pad_deck(g, A)
    end_turn(g, A)
    assert "Tide Pools" in s["discard"] and dur_cards(g, A) == []


def test_tide_pools_discard_clamps_to_hand():
    g = fresh()
    give_hand(g, A, ["Tide Pools"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 4
    assert mv(g, A, {"type": "play_action", "card": "Tide Pools"})[0]
    # Leave exactly ONE card reachable for the clean-up redraw.
    s["hand"], s["deck"], s["discard"] = [], ["Copper"], []
    end_turn(g, A)
    end_turn(g, B)
    assert g["turn"] == A and s["hand"] == ["Copper"]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 1 and c["max"] == 1              # clamped from 2
    assert decide(g, A, cards=["Copper"])[0]
    assert s["hand"] == []


# --- Warehouse ---------------------------------------------------------------

def test_warehouse_draw_three_discard_three():
    g = fresh()
    give_hand(g, A, ["Warehouse", "Estate"])
    s = g["seats"][A]
    s["deck"] = ["Copper", "Copper", "Silver", "Gold"]
    assert mv(g, A, {"type": "play_action", "card": "Warehouse"})[0]
    assert g["actions"] == 1
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 3 and c["max"] == 3 and c["purpose"] == "discard"
    # Discards may be ANY hand cards, not just the drawn ones.
    assert decide(g, A, cards=["Estate", "Copper", "Copper"])[0]
    assert s["hand"] == ["Silver"]
    assert sorted(s["discard"]) == ["Copper", "Copper", "Estate"]


def test_warehouse_clamps_to_hand():
    g = fresh()
    give_hand(g, A, ["Warehouse"])
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Copper"], []
    assert mv(g, A, {"type": "play_action", "card": "Warehouse"})[0]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 1 and c["max"] == 1              # clamped from 3
    assert decide(g, A, cards=["Copper"])[0]
    assert s["hand"] == [] and s["discard"] == ["Copper"]


# --- Wharf -------------------------------------------------------------------

def test_wharf_duration_cycle():
    g = fresh()
    give_hand(g, A, ["Wharf"])
    s = g["seats"][A]
    s["deck"] = ["Copper"] * 12
    assert mv(g, A, {"type": "play_action", "card": "Wharf"})[0]
    assert len(s["hand"]) == 2 and g["buys"] == 2
    end_turn(g, A)
    assert "Wharf" not in s["discard"]
    assert dur_cards(g, A) == ["Wharf"]
    end_turn(g, B)
    assert g["turn"] == A and len(s["hand"]) == 7 and g["buys"] == 2
    pad_deck(g, A)
    end_turn(g, A)
    assert "Wharf" in s["discard"] and dur_cards(g, A) == []
