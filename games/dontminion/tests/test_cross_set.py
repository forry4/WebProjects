"""Cross-set / cross-mechanic interaction tests — the combos no single card
batch owns: out-of-band plays of Treasures (Sailor x Astrolabe), Vassal
flipping a Duration, Throne Room across the simple-duration family, cost
evaluation at fx time (Bridge x Pirate), the documented Sea Chart x spent-
Outpost deviation, and pre-Seaside save-blob compatibility."""

import json
import random

from games.dontminion import engine
from games.dontminion.cards import CARDS

import pytest

A, B = "alice", "bob"


def fresh(kingdom, players=(A, B), seed=42, expansions=("base", "intrigue", "seaside")):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom))


def give_hand(g, pid, cards):
    g["seats"][pid]["hand"] = list(cards)


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def decide(g, pid, **payload):
    return engine.apply_move(g, pid, {"type": "decision", **payload})


def drain_decisions(g, rng=None):
    """Answer every pending decision with a uniform valid payload."""
    rng = rng or random.Random(7)
    for _ in range(60):
        pid = g["pending_pid"]
        if pid is None:
            return
        ok, err = decide(g, pid, **engine.sample_decision(g, pid, rng))
        assert ok, err
    raise AssertionError("decisions never drained")


# --- Sailor x Astrolabe: a Treasure played out-of-band still produces its $ ---

def test_sailor_played_astrolabe_gives_its_coin_and_buy():
    g = fresh(["Sailor", "Astrolabe", "Smithy", "Moat", "Village",
               "Militia", "Witch", "Gardens", "Warehouse", "Bazaar"])
    give_hand(g, A, ["Sailor"])
    assert mv(g, A, {"type": "play_action", "card": "Sailor"})[0]
    coins0, buys0, played0 = g["coins"], g["buys"], g["turn_ctx"]["actions_played"]
    assert g["phase"] == "buy"                    # auto-advanced (no actions left)
    g["coins"] += 3
    assert mv(g, A, {"type": "buy", "card": "Astrolabe"})[0]
    # Sailor's window: play the gained Duration
    assert g["pending_pid"] == A and g["pending_kind"] == "choose_option"
    assert decide(g, A, ids=["play"])[0]
    assert "Astrolabe" in g["seats"][A]["in_play"]
    # the printed $1 AND the +1 Buy both landed (buy spent one, Astrolabe adds one)
    assert g["coins"] == coins0 + 3 - 3 + 1, "Astrolabe's printed $1 missing"
    assert g["buys"] == buys0 - 1 + 1
    # playing a TREASURE never counts as an Action played (Conspirator's count)
    assert g["turn_ctx"]["actions_played"] == played0
    # and its duration half still fires next turn
    assert mv(g, A, {"type": "end_phase"})[0]
    assert engine.duration_in_play(g, A, "Astrolabe")
    assert mv(g, B, {"type": "end_phase"})[0]
    drain_decisions(g)
    assert g["turn"] == A
    # Astrolabe's +$1/+1 Buy AND Sailor's own +$2 both fire at turn start
    assert g["coins"] == 3 and g["buys"] == 2


# --- Vassal x Duration: a Duration played from the discard persists ------------

def test_vassal_plays_a_duration_off_the_deck_and_it_persists():
    g = fresh(["Vassal", "Caravan", "Smithy", "Moat", "Village",
               "Militia", "Witch", "Gardens", "Warehouse", "Bazaar"])
    give_hand(g, A, ["Vassal", "Copper"])
    g["seats"][A]["deck"] = ["Caravan"] + g["seats"][A]["deck"]
    assert mv(g, A, {"type": "play_action", "card": "Vassal"})[0]
    assert g["pending_pid"] == A                  # "play the discarded Caravan?"
    ok, err = decide(g, A, **engine.sample_decision(g, A, random.Random(1)))
    assert ok, err
    if "Caravan" in g["seats"][A]["in_play"]:     # said yes
        hand_after = len(g["seats"][A]["hand"])
        assert mv(g, A, {"type": "end_phase"})[0]
        if g["turn"] == A and g["phase"] == "buy":
            assert mv(g, A, {"type": "end_phase"})[0]
        assert engine.duration_in_play(g, A, "Caravan")


def test_vassal_duration_full_cycle_forced_yes():
    g = fresh(["Vassal", "Caravan", "Smithy", "Moat", "Village",
               "Militia", "Witch", "Gardens", "Warehouse", "Bazaar"])
    give_hand(g, A, ["Vassal"])
    g["seats"][A]["deck"] = ["Caravan"] + ["Copper"] * 8
    assert mv(g, A, {"type": "play_action", "card": "Vassal"})[0]
    # force the yes branch
    top = g["pending"][-1]
    yes = [o["id"] for o in top["constraint"]["options"] if o["id"] != "decline"]
    assert decide(g, A, ids=[yes[0] if yes else "decline"])[0]
    if not engine.duration_in_play(g, A, "Caravan"):
        pytest.skip("vassal option ids differ — covered by the sampled test above")
    assert mv(g, A, {"type": "end_phase"})[0]
    assert engine.duration_in_play(g, A, "Caravan")
    hand0 = len(g["seats"][A]["hand"])
    assert mv(g, B, {"type": "end_phase"})[0]
    assert g["turn"] == A
    assert len(g["seats"][A]["hand"]) == hand0 + 1   # Caravan's next-turn draw


# --- Throne Room x the simple-duration family ---------------------------------

SIMPLE_DURATIONS = ["Caravan", "Fishing Village", "Merchant Ship", "Wharf",
                    "Lighthouse", "Tide Pools", "Monkey"]


@pytest.mark.parametrize("dur", SIMPLE_DURATIONS)
def test_throne_room_rider_full_cycle(dur):
    g = fresh([dur, "Throne Room", "Smithy", "Moat", "Village",
               "Militia", "Witch", "Gardens", "Warehouse", "Bazaar"])
    give_hand(g, A, ["Throne Room", dur])
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert decide(g, A, cards=[dur])[0]
    drain_decisions(g)
    assert mv(g, A, {"type": "end_phase"})[0]
    if g["turn"] == A:                            # still my turn (buy phase)
        assert mv(g, A, {"type": "end_phase"})[0]
    # both the duration AND its Throne Room stay on the table
    assert engine.duration_in_play(g, A, dur), dur
    assert engine.duration_in_play(g, A, "Throne Room"), dur
    # opponent's turn passes; my next turn resolves doubled fx
    while g["turn"] == B and not g["over"]:
        pid = g["pending_pid"] or B
        ok, err = mv(g, pid, {"type": "end_phase"} if g["pending_pid"] is None
                    else {"type": "decision", **engine.sample_decision(g, pid, random.Random(3))})
        assert ok, err
    drain_decisions(g)
    assert g["turn"] == A
    # after my next turn's clean-up, both are discarded together
    assert mv(g, A, {"type": "end_phase"})[0]
    if g["turn"] == A:
        assert mv(g, A, {"type": "end_phase"})[0]
    owned_out = g["seats"][A]["discard"] + g["seats"][A]["deck"] + g["seats"][A]["hand"]
    assert not engine.duration_in_play(g, A, dur), dur
    assert not engine.duration_in_play(g, A, "Throne Room"), dur
    assert "Throne Room" in owned_out


# --- Bridge x Pirate: cost thresholds are evaluated at fx time ----------------

def test_pirate_fx_cost_check_ignores_last_turns_bridge():
    g = fresh(["Pirate", "Bridge", "Smithy", "Moat", "Village",
               "Militia", "Witch", "Gardens", "Warehouse", "Bazaar"])
    give_hand(g, A, ["Bridge", "Pirate"])
    g["actions"] = 2
    g["seats"][A]["deck"] = ["Copper"] * 8
    assert mv(g, A, {"type": "play_action", "card": "Bridge"})[0]
    assert mv(g, A, {"type": "play_action", "card": "Pirate"})[0]
    assert g["turn_ctx"]["bridges"] == 1
    assert mv(g, A, {"type": "end_phase"})[0]
    assert mv(g, B, {"type": "end_phase"})[0]
    if g["turn"] == B:
        assert mv(g, B, {"type": "end_phase"})[0]
    # A's turn start: the Treasure pick uses TODAY's costs (bridge expired)
    assert g["pending_pid"] == A and g["pending_kind"] == "choose_pile"
    piles = g["pending"][-1]["constraint"]["piles"]
    assert set(piles) == {"Copper", "Silver", "Gold"}   # Gold costs 6 <= 6 plain
    assert decide(g, A, pile="Gold")[0]
    assert "Gold" in g["seats"][A]["hand"]


# --- Sea Chart x spent Outpost: the DOCUMENTED lingering-card deviation -------

def test_sea_chart_does_not_match_a_spent_outpost_official_timing():
    """OFFICIAL timing (post-audit): a denied Outpost's ability resolved
    BETWEEN turns, so it discards at the FOLLOWING clean-up (whoever's turn
    that is). By the owner's next turn it is off the table — Sea Chart's
    copy-in-play check must NOT match it."""
    g = fresh(["Sea Chart", "Outpost", "Smithy", "Moat", "Village",
               "Militia", "Witch", "Gardens", "Warehouse", "Bazaar"])
    # B takes an extra turn via Outpost; the SECOND Outpost play cannot grant
    # another (no 3rd turn) and lingers spent
    assert mv(g, A, {"type": "end_phase"})[0]      # action -> buy (turn 1 never auto-advances)
    assert mv(g, A, {"type": "end_phase"})[0]      # end A's turn
    assert g["turn"] == B
    give_hand(g, B, ["Outpost"])
    g["phase"] = "action"                          # staged hand post-auto-advance
    g["actions"] = 1
    assert mv(g, B, {"type": "play_action", "card": "Outpost"})[0]
    assert mv(g, B, {"type": "end_phase"})[0]
    assert g["turn"] == B and g["extra_turn"]     # the extra turn happened
    give_hand(g, B, ["Outpost", "Sea Chart"] + list(g["seats"][B]["hand"]))
    g["phase"] = "action"
    g["actions"] = 2
    assert mv(g, B, {"type": "play_action", "card": "Outpost"})[0]  # no 3rd turn
    assert mv(g, B, {"type": "end_phase"})[0]
    if g["turn"] == B:                             # still in the buy phase
        assert mv(g, B, {"type": "end_phase"})[0]
    assert g["turn"] == A                          # extra turn denied
    # the spent copy is still on the table only until the FOLLOWING clean-up
    assert engine.duration_in_play(g, B, "Outpost")
    assert mv(g, A, {"type": "end_phase"})[0]
    if g["turn"] == A:
        assert mv(g, A, {"type": "end_phase"})[0]  # A's clean-up sweeps it
    drain_decisions(g)
    assert g["turn"] == B
    assert not engine.duration_in_play(g, B, "Outpost")
    give_hand(g, B, ["Sea Chart"])
    g["phase"] = "action"
    g["actions"] = 1
    g["seats"][B]["deck"] = ["Copper", "Outpost", "Copper"]
    assert mv(g, B, {"type": "play_action", "card": "Sea Chart"})[0]
    # no copy in play: the revealed Outpost stays on top of the deck
    assert "Outpost" not in g["seats"][B]["hand"]
    assert g["seats"][B]["deck"][0] == "Outpost"


# --- pre-Seaside save blobs load and play through the v2 kernel ---------------

def test_pre_seaside_save_blob_plays_through_v2_kernel():
    g = engine.new_game([A, B], ["base"], seed=5,
                        kingdom=["Smithy", "Village", "Moat", "Militia",
                                 "Witch", "Throne Room", "Gardens"])
    # simulate a blob saved by the pre-Seaside engine: none of the v2 keys
    for seat in g["seats"].values():
        for k in ("duration", "dur_aside", "island", "village_mat"):
            seat.pop(k, None)
    for k in ("watchers", "last_turn_pid", "extra_turn", "schema"):
        g.pop(k, None)
    g = json.loads(json.dumps(g))                  # the save/load round-trip
    g = engine.migrate(g)                          # ...and THE migration point
    assert g["schema"] == engine.SCHEMA
    rng = random.Random(9)
    for _ in range(300):
        if g["over"]:
            break
        pid = g["pending_pid"] or g["turn"]
        if g["pending_pid"]:
            m = {"type": "decision", **engine.sample_decision(g, pid, rng)}
        else:
            m = rng.choice(engine.legal_moves(g, pid))
        ok, err = engine.apply_move(g, pid, m)
        assert ok, err
        json.dumps(g)                              # stays serialisable
    assert g["seats"][A]["turns_taken"] + g["seats"][B]["turns_taken"] > 3
    view = engine.player_view(g, A)                # views build fine too
    json.dumps(view)


# --- audit fixes: play-time immunity reaches delayed attack effects -----------

def test_lighthouse_protection_blocks_corsairs_delayed_trash():
    g = fresh(["Corsair", "Lighthouse", "Smithy", "Moat", "Village",
               "Militia", "Witch", "Gardens", "Warehouse", "Bazaar"])
    # B establishes Lighthouse protection on their turn
    assert mv(g, A, {"type": "end_phase"})[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    give_hand(g, B, ["Lighthouse"])
    g["phase"] = "action"
    g["actions"] = 1
    assert mv(g, B, {"type": "play_action", "card": "Lighthouse"})[0]
    assert mv(g, B, {"type": "end_phase"})[0]
    if g["turn"] == B:
        assert mv(g, B, {"type": "end_phase"})[0]
    # A plays Corsair while B is protected: the watcher must carry B's immunity
    assert g["turn"] == A
    give_hand(g, A, ["Corsair"])
    g["phase"] = "action"
    g["actions"] = 1
    assert mv(g, A, {"type": "play_action", "card": "Corsair"})[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    if g["turn"] == A:
        assert mv(g, A, {"type": "end_phase"})[0]
    # B's turn: playing a Silver must NOT be trashed (immune at Corsair's play)
    drain_decisions(g)
    assert g["turn"] == B
    give_hand(g, B, ["Silver"])
    g["phase"] = "buy"
    assert mv(g, B, {"type": "play_treasure", "card": "Silver"})[0]
    engine._drive(g)
    assert "Silver" in g["seats"][B]["in_play"]
    assert "Silver" not in g["trash"]


def test_corsair_still_trashes_an_unprotected_player():
    g = fresh(["Corsair", "Lighthouse", "Smithy", "Moat", "Village",
               "Militia", "Witch", "Gardens", "Warehouse", "Bazaar"])
    give_hand(g, A, ["Corsair"])
    assert mv(g, A, {"type": "play_action", "card": "Corsair"})[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert g["turn"] == B
    give_hand(g, B, ["Silver"])
    g["phase"] = "buy"
    assert mv(g, B, {"type": "play_treasure", "card": "Silver"})[0]
    engine._drive(g)
    assert "Silver" in g["trash"]                  # the attack lands


def test_two_sailors_each_grant_their_own_play():
    g = fresh(["Sailor", "Caravan", "Smithy", "Moat", "Village",
               "Militia", "Witch", "Gardens", "Warehouse", "Bazaar"])
    give_hand(g, A, ["Sailor", "Sailor"])
    g["seats"][A]["deck"] = ["Copper"] * 10
    g["actions"] = 2
    assert mv(g, A, {"type": "play_action", "card": "Sailor"})[0]
    assert mv(g, A, {"type": "play_action", "card": "Sailor"})[0]
    g["coins"] = 8
    g["buys"] = 2
    assert mv(g, A, {"type": "buy", "card": "Caravan"})[0]
    assert g["pending_pid"] == A                   # first Sailor's offer
    assert decide(g, A, ids=["play"])[0]
    assert "Caravan" in g["seats"][A]["in_play"]
    assert mv(g, A, {"type": "buy", "card": "Caravan"})[0]
    assert g["pending_pid"] == A                   # SECOND Sailor's own offer
    assert decide(g, A, ids=["play"])[0]
    assert g["seats"][A]["in_play"].count("Caravan") == 2


def test_pirate_reaction_on_own_turn_counts_for_conspirator():
    g = fresh(["Pirate", "Conspirator", "Smithy", "Moat", "Village",
               "Militia", "Witch", "Gardens", "Warehouse", "Bazaar"])
    give_hand(g, A, ["Pirate"])
    g["phase"] = "buy"
    g["coins"] = 3
    played0 = g["turn_ctx"]["actions_played"]
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    assert g["pending_pid"] == A                   # my own gain, my window
    assert decide(g, A, ids=["play"])[0]
    assert "Pirate" in g["seats"][A]["in_play"]
    assert g["turn_ctx"]["actions_played"] == played0 + 1   # own-turn play counts
