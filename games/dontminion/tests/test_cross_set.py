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

# Vassal's frame, pinned: a test that picks its branch by "whichever id isn't
# 'decline'" is guessing, and a guess that misses has to fail rather than opt out.
VASSAL_OPTIONS = ["play", "discard"]


def test_vassal_plays_a_duration_off_the_deck_and_it_persists():
    g = fresh(["Vassal", "Caravan", "Smithy", "Moat", "Village",
               "Militia", "Witch", "Gardens", "Warehouse", "Bazaar"])
    give_hand(g, A, ["Vassal", "Copper"])
    g["seats"][A]["deck"] = ["Caravan"] + g["seats"][A]["deck"]
    assert mv(g, A, {"type": "play_action", "card": "Vassal"})[0]
    assert g["pending_pid"] == A                  # "play the discarded Caravan?"
    ok, err = decide(g, A, **engine.sample_decision(g, A, random.Random(1)))
    assert ok, err
    # The choice is SAMPLED, so either branch is a legitimate outcome — but both
    # have to land somewhere. Asserting only the play branch (as this once did)
    # made a Vassal that plays nothing at all a silent pass.
    assert g["seats"][A]["aside"] == []            # left the look-at zone either way
    if "Caravan" in g["seats"][A]["in_play"]:      # chose "play"
        assert mv(g, A, {"type": "end_phase"})[0]
        if g["turn"] == A and g["phase"] == "buy":
            assert mv(g, A, {"type": "end_phase"})[0]
        assert engine.duration_in_play(g, A, "Caravan")
    else:                                          # chose "discard"
        assert "Caravan" in g["seats"][A]["discard"]
        assert not engine.duration_in_play(g, A, "Caravan")


def test_vassal_duration_full_cycle_forced_yes():
    g = fresh(["Vassal", "Caravan", "Smithy", "Moat", "Village",
               "Militia", "Witch", "Gardens", "Warehouse", "Bazaar"])
    give_hand(g, A, ["Vassal"])
    g["seats"][A]["deck"] = ["Caravan"] + ["Copper"] * 8
    assert mv(g, A, {"type": "play_action", "card": "Vassal"})[0]
    # Force the play branch BY ID. This used to take "the first id that isn't
    # 'decline'" and pytest.skip() if the Caravan never reached play — which
    # turned every regression in this path into a PASS, and did exactly that
    # for a real duration_in_play breakage during the 2026-07-31 Scheme fix.
    opts = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
    assert opts == VASSAL_OPTIONS, opts
    assert decide(g, A, ids=["play"])[0]
    assert engine.duration_in_play(g, A, "Caravan")
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


# ============================================================================
# PHASE 3 — HINTERLANDS x THE OLDER SETS
#
# The interactions no single-set batch owns: throne-rooms over the new
# cumulative-per-play effects, the new when-gain cards under Watchtower and
# Trader, the three cost-reduction mechanisms against the new cost checks, the
# undo/reveal audit, Guard Dog vs the older attacks and Lighthouse vs the new
# ones, and the save/wire shape with the new state on the table.
#
# Own fixtures (`xs_*`) on purpose: the helpers above default to the Seaside
# expansion set, and rebinding them would silently change what the tests above
# exercise (the same reason the per-batch card files stay split).
# ============================================================================

import copy

from games.dontminion.cards import CARDS as XS_CARDS

XS_EXPS = ["base", "intrigue", "seaside", "prosperity", "hinterlands"]
# A deliberately WIDE forced kingdom: every card these cross-tests reach for,
# from five sets at once. The forced-kingdom seam takes any list.
XS_KINGDOM = [
    # Hinterlands
    "Berserker", "Border Village", "Cartographer", "Cauldron", "Crossroads",
    "Develop", "Farmland", "Fool's Gold", "Guard Dog", "Haggler", "Highway",
    "Inn", "Jack of All Trades", "Margrave", "Nomads", "Oasis", "Scheme",
    "Souk", "Spice Merchant", "Stables", "Trader", "Trail", "Tunnel", "Weaver",
    "Wheelwright", "Witch's Hut",
    # the older sets these have to interact with
    "Moat", "Militia", "Witch", "Throne Room", "Village",          # base
    "Bridge", "Torturer", "Minion", "Swindler", "Diplomat",        # intrigue
    "Lighthouse",                                                  # seaside
    "King's Court", "Quarry", "Rabble", "Watchtower",              # prosperity
]


def xs_fresh(players=(A, B), seed=42, kingdom=None):
    g = engine.new_game(list(players), XS_EXPS, seed=seed,
                        kingdom=list(kingdom or XS_KINGDOM))
    # Platinum/Colony ride on a random Prosperity proportion; pin them off so
    # the pile lists and the end-game condition are identical in every test.
    g["colony"] = False
    g["supply"].pop("Platinum", None)
    g["supply"].pop("Colony", None)
    return g


def xs_hand(g, pid, cards):
    """Force a hand to exactly `cards` (card conservation not preserved)."""
    g["seats"][pid]["hand"] = list(cards)


def xs_top(g):
    return g["pending"][-1] if g["pending"] else None


def xs_ids(g):
    return [o["id"] for o in g["pending"][-1]["constraint"]["options"]]


def xs_piles(g):
    return g["pending"][-1]["constraint"]["piles"]


def xs_pool(g, label):
    """Answer the p23 §2 what-resolves-first prompt by option label."""
    f = xs_top(g)
    assert (f["card"], f["stage"]) == ("__abilities", "pick"), (f["card"], f["stage"])
    opts = {o["label"]: o["id"] for o in f["constraint"]["options"]}
    assert label in opts, (label, sorted(opts))
    ok, err = mv(g, f["pid"], {"type": "decision", "ids": [opts[label]]})
    assert ok, err
    return sorted(opts)


def xs_play(g, pid, card):
    return mv(g, pid, {"type": "play_action", "card": card})


def xs_run(g, limit=24, prefer=("play",), pile=None):
    """Answer every open frame with a neutral choice until the stack drains.

    Used by the tests whose POINT is the frame ORDER: they have to reach the
    same end state under either ordering, so the assertion (not the script) is
    what fails when the order is wrong.
    """
    seen = []
    for _ in range(limit):
        f = xs_top(g)
        if f is None:
            return seen
        seen.append((f["pid"], f["card"], f["stage"]))
        c, k, pid = f["constraint"], f["kind"], f["pid"]
        if k == "order_cards":
            ok, err = mv(g, pid, {"type": "decision", "order": list(c["cards"])})
        elif k == "choose_option":
            ids = [o["id"] for o in c["options"]]
            pick = next((i for i in ids if i in prefer), ids[0])
            ok, err = mv(g, pid, {"type": "decision", "ids": [pick]})
        elif k == "choose_cards":
            ok, err = mv(g, pid, {"type": "decision",
                                  "cards": list(c["cards"])[:c["min"]]})
        elif k == "choose_pile":
            want = pile if pile in c["piles"] else c["piles"][0]
            ok, err = mv(g, pid, {"type": "decision", "pile": want})
        else:
            raise AssertionError(f"unhandled frame kind {k}")
        assert ok, err
    raise AssertionError("frames never drained")


def xs_end_turn(g, pid):
    if g["phase"] == "action":
        assert mv(g, pid, {"type": "end_phase"})[0]
    assert mv(g, pid, {"type": "end_phase"})[0]


def xs_lighthouse_for_b(g):
    """Give B an active Lighthouse protection and hand the turn back to A."""
    assert mv(g, A, {"type": "end_phase"})[0]      # turn 1 never auto-advances
    assert mv(g, A, {"type": "end_phase"})[0]
    assert g["turn"] == B
    xs_hand(g, B, ["Lighthouse"])
    g["phase"] = "action"
    g["actions"] = 1
    assert xs_play(g, B, "Lighthouse")[0]
    xs_end_turn(g, B)
    assert g["turn"] == A
    assert engine.attack_protected(g, B)


# ---------------------------------------------------------------------------
# 1. THRONE ROOM / KING'S COURT x the new cumulative-per-play effects
# ---------------------------------------------------------------------------

def test_throne_room_doubles_hagglers_watcher():
    """Haggler is a per-PLAY watcher (the Hoard shape), so a throne-roomed
    Haggler registers two of them: +$4, and one bought card hands out two
    cheaper non-Victory cards."""
    g = xs_fresh()
    xs_hand(g, A, ["Throne Room", "Haggler"])
    assert xs_play(g, A, "Throne Room")[0]
    assert decide(g, A, cards=["Haggler"])[0]
    assert g["coins"] == 4                                   # +$2 twice
    assert [w["card"] for w in g["watchers"]] == ["Haggler", "Haggler"]
    g["phase"] = "buy"
    g["coins"] = 5
    assert mv(g, A, {"type": "buy", "card": "Highway"})[0]
    assert xs_top(g)["card"] == "Haggler"
    assert decide(g, A, pile="Bridge")[0]
    assert xs_top(g)["card"] == "Haggler"                    # the SECOND watcher
    assert decide(g, A, pile="Bridge")[0]
    assert g["seats"][A]["discard"] == ["Highway", "Bridge", "Bridge"]


def test_kings_court_triples_schemes_offer():
    """Scheme 'sets up a later ability' per play — three plays, three separate
    offers at the end of the buy phase, each seeing what the previous left."""
    g = xs_fresh()
    xs_hand(g, A, ["King's Court", "Scheme", "Village", "Village", "Village"])
    g["seats"][A]["deck"] = ["Copper"] * 15
    assert xs_play(g, A, "King's Court")[0]
    assert decide(g, A, cards=["Scheme"])[0]
    assert len([w for w in g["watchers"] if w["card"] == "Scheme"]) == 3
    for _ in range(3):
        assert xs_play(g, A, "Village")[0]
    xs_end_turn(g, A)                    # the buy phase already auto-advanced
    picked = []
    for _ in range(3):
        f = xs_top(g)
        assert f is not None and (f["card"], f["stage"]) == ("Scheme", "topdeck")
        card = f["constraint"]["cards"][0]
        picked.append(card)
        assert decide(g, A, cards=[card])[0]
    assert picked == ["King's Court", "Scheme", "Village"]
    assert xs_top(g) is None
    assert g["turn"] == B


def test_a_throne_roomed_berserker_plays_each_gained_trail_mid_resolution():
    """'You can react with Trail when gaining it in the middle of resolving an
    ability' (p157). Throne Room + Berserker gains twice, and each gained Trail
    plays itself before the second Berserker play begins."""
    g = xs_fresh()
    xs_hand(g, A, ["Throne Room", "Berserker"])
    xs_hand(g, B, ["Copper"] * 5)
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert xs_play(g, A, "Throne Room")[0]
    assert decide(g, A, cards=["Berserker"])[0]
    stages = [(c, s) for _, c, s in xs_run(g, pile="Trail")]
    assert stages.count(("Trail", "self_play")) == 2
    # the SECOND Berserker gain came after the first Trail had already played
    gains = [i for i, s in enumerate(stages) if s == ("Berserker", "gain")]
    assert stages.index(("Trail", "self_play")) < gains[1]
    assert g["seats"][A]["in_play"].count("Trail") == 2
    # Throne Room + Berserker x2 + Trail x2 (Conspirator's count)
    assert g["turn_ctx"]["actions_played"] == 5


def test_cauldron_is_a_treasure_so_no_throne_room_can_double_its_counter():
    """The set's other cumulative-per-play effect can't be throne-roomed at all
    — Cauldron is a Treasure-Attack and Throne Room only plays Actions. (Two
    separate Cauldrons each keeping their own counter is the per-copy case, and
    lives in the batch file.)"""
    g = xs_fresh()
    xs_hand(g, A, ["Throne Room", "Cauldron"])
    assert xs_play(g, A, "Throne Room")[0]
    assert xs_top(g) is None                       # no Action to pick: no frame
    assert g["seats"][A]["in_play"] == ["Throne Room"]
    assert "Cauldron" in g["seats"][A]["hand"]


def test_throne_room_on_a_new_attack_opens_a_reaction_window_per_play():
    """BEHAVIOUR PIN, not a rules verdict. The kernel treats each replay as a
    fresh play of the Attack, so the reaction window (and the per-play immunity
    set) is rebuilt for it: a Moat holder is asked twice and must reveal twice
    to be unaffected twice. The compendium is not explicit for a throne-roomed
    Attack ('it triggers whenever an Attack card is played' vs Moat's
    'unaffected by IT'), and the neighbouring rulings point both ways (Cultist
    3 wants a reveal per Cultist PLAY; Reckless 8 says one reveal covers both
    resolutions of ONE play). Recorded so a deliberate change is visible."""
    g = xs_fresh()
    xs_hand(g, A, ["Throne Room", "Margrave"])
    xs_hand(g, B, ["Moat"] + ["Copper"] * 4)
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert xs_play(g, A, "Throne Room")[0]
    assert decide(g, A, cards=["Margrave"])[0]
    assert (xs_top(g)["card"], xs_top(g)["pid"]) == ("__attack", B)
    assert decide(g, B, ids=["react:Moat"])[0]
    assert xs_top(g)["card"] == "__attack"          # asked again for the replay
    assert decide(g, B, ids=["react:Moat"])[0]
    assert g["seats"][B]["hand"] == ["Moat"] + ["Copper"] * 4
    assert xs_top(g) is None


def test_declining_the_second_window_lets_the_replayed_attack_land():
    """The other half of the pin above: immunity is per PLAY, so a Moat kept
    back on the replay is a real hit."""
    g = xs_fresh()
    xs_hand(g, A, ["Throne Room", "Margrave"])
    xs_hand(g, B, ["Moat"] + ["Copper"] * 4)
    g["seats"][A]["deck"] = ["Copper"] * 12
    g["seats"][B]["deck"] = ["Estate"] * 6
    assert xs_play(g, A, "Throne Room")[0]
    assert decide(g, A, cards=["Margrave"])[0]
    assert decide(g, B, ids=["react:Moat"])[0]
    assert decide(g, B, ids=["decline"])[0]
    f = xs_top(g)
    assert (f["pid"], f["card"], f["stage"]) == (B, "Margrave", "discard")
    assert decide(g, B, cards=f["constraint"]["cards"][:f["constraint"]["min"]])[0]
    assert len(g["seats"][B]["hand"]) == 3


# ---------------------------------------------------------------------------
# 2. CARTOGRAPHER'S FRAME ORDERING — the flagged open question
#
# Cartographer is "REVEAL / LOOK AT CARDS AND DISCARD" (p69). That common
# effect says the un-discarded cards "are kept aside. They're not in your hand,
# in play, or in your deck. This matters if, for example, discarding or
# trashing triggers an ability that lets you draw" (p54) — and Sentry, the same
# shape, is annotated "TRIGGERED ABILITY (first trash, then discard, then put
# cards back)" (p144). So the when-discard triggers of the discarded cards
# resolve BEFORE the rest go back on the deck.
#
# The engine parks the discard's triggers and then pushes the put-back ON TOP
# of them, so the put-back resolves first. Nothing in the shipped Rabble
# precedent could observe the difference; Tunnel, Trail and Weaver can.
# ---------------------------------------------------------------------------

def test_cartographer_tunnel_reacts_before_the_cards_go_back():
    g = xs_fresh()
    xs_hand(g, A, ["Cartographer"])
    g["seats"][A]["deck"] = ["Copper", "Tunnel", "Estate", "Estate", "Gold", "Silver"]
    assert xs_play(g, A, "Cartographer")[0]
    assert decide(g, A, cards=["Tunnel"])[0]
    f = xs_top(g)
    assert (f["card"], f["stage"]) == ("Tunnel", "reveal"), \
        f"the put-back jumped the when-discard trigger: got {f['card']}/{f['stage']}"


def test_cartographer_discarded_trail_draws_from_under_the_looked_at_cards():
    g = xs_fresh()
    xs_hand(g, A, ["Cartographer"])
    g["seats"][A]["deck"] = ["Copper", "Trail", "Estate", "Duchy", "Gold", "Silver"]
    assert xs_play(g, A, "Cartographer")[0]
    assert g["seats"][A]["aside"] == ["Trail", "Estate", "Duchy", "Gold"]
    assert g["seats"][A]["deck"] == ["Silver"]
    assert decide(g, A, cards=["Trail"])[0]
    xs_run(g)                                   # order-independent by design
    assert "Trail" in g["seats"][A]["in_play"]
    assert "Silver" in g["seats"][A]["hand"], "Trail drew a card it can't see yet"
    assert g["seats"][A]["deck"] == ["Estate", "Duchy", "Gold"]


def test_rabble_discarded_trail_reacts_before_the_cards_go_back():
    g = xs_fresh()
    xs_hand(g, A, ["Rabble"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    xs_hand(g, B, [])
    g["seats"][B]["deck"] = ["Trail", "Estate", "Duchy", "Silver", "Gold"]
    g["seats"][B]["discard"] = []
    assert xs_play(g, A, "Rabble")[0]
    xs_run(g)
    assert "Trail" in g["seats"][B]["in_play"]
    assert g["seats"][B]["deck"][:2] == ["Estate", "Duchy"]
    assert "Silver" in g["seats"][B]["hand"]


def test_cartographer_still_fires_the_when_discard_trigger_at_all():
    """The defect above is an ORDER defect, not a dropped trigger: the Tunnel
    offer does arrive, just late. Pinned separately so a fix to the ordering
    can't quietly drop the trigger instead."""
    g = xs_fresh()
    xs_hand(g, A, ["Cartographer"])
    g["seats"][A]["deck"] = ["Copper", "Tunnel", "Estate", "Estate", "Gold", "Silver"]
    assert xs_play(g, A, "Cartographer")[0]
    assert decide(g, A, cards=["Tunnel"])[0]
    seen = [(c, s) for _, c, s in xs_run(g, prefer=("reveal",))]
    assert ("Tunnel", "reveal") in seen
    assert "Gold" in g["seats"][A]["discard"]


# ---------------------------------------------------------------------------
# 3. WATCHTOWER x the new when-gain cards
# ---------------------------------------------------------------------------

def test_watchtower_and_inn_the_player_chooses_and_each_order_differs():
    """The compendium's own worked example (p26, Example 1), now implemented as
    the rules write it: the player CHOOSES which when-gain resolves first, and
    the two orders genuinely differ — Inn first shuffles itself in and the
    Watchtower loses track; Watchtower first can trash the Inn before its own
    ability ever runs."""
    # Branch A: Inn first — Watchtower then holds a dead trash option
    g = xs_fresh()
    xs_hand(g, A, ["Watchtower"])
    g["seats"][A]["discard"] = ["Village"]
    assert engine.gain(g, A, "Inn")
    engine._drive(g)
    assert xs_pool(g, "Inn") == ["Inn", "Watchtower"]
    assert (xs_top(g)["card"], xs_top(g)["stage"]) == ("Inn", "shuffle")
    assert decide(g, A, cards=["Inn", "Village"])[0]      # Inn shuffles itself in
    assert "Inn" not in g["seats"][A]["discard"]
    assert "Inn" in g["seats"][A]["deck"]
    assert (xs_top(g)["card"], xs_top(g)["stage"]) == ("Watchtower", "react")
    assert decide(g, A, ids=["play"])[0]
    assert decide(g, A, ids=["trash"])[0]
    assert g["trash"] == []                              # lost track: a no-op
    assert "Inn" in g["seats"][A]["deck"]
    assert any(e.get("event") == "lost_track" and e.get("card") == "Inn"
               for e in g["log"])                        # ...and it SAYS so

    # Branch B: Watchtower first — the Inn is trashed, then Inn's own ability
    # still resolves ("effects are immediate"), just without the Inn in it
    g = xs_fresh()
    xs_hand(g, A, ["Watchtower"])
    g["seats"][A]["discard"] = ["Village"]
    assert engine.gain(g, A, "Inn")
    engine._drive(g)
    xs_pool(g, "Watchtower")
    assert decide(g, A, ids=["play"])[0]
    assert decide(g, A, ids=["trash"])[0]
    assert "Inn" in g["trash"]                           # tracked: the trash lands
    assert (xs_top(g)["card"], xs_top(g)["stage"]) == ("Inn", "shuffle")
    assert decide(g, A, cards=["Village"])[0]            # Inn itself is gone
    assert "Village" in g["seats"][A]["deck"]


def test_watchtower_trashes_a_gained_farmland_after_its_when_gain_resolved():
    """'They move it AFTER it has been gained' (p22) — Farmland's when-gain
    trash-and-upgrade stands even though the Farmland itself is then trashed."""
    g = xs_fresh()
    xs_hand(g, A, ["Watchtower", "Estate"])
    assert engine.gain(g, A, "Farmland")
    engine._drive(g)
    xs_pool(g, "Farmland")                               # resolve its when-gain first
    assert (xs_top(g)["card"], xs_top(g)["stage"]) == ("Farmland", "trash")
    assert decide(g, A, cards=["Estate"])[0]             # Estate ($2) -> a $4
    gained = xs_piles(g)[0]
    assert engine.cost_eq(g, gained, 4)
    assert decide(g, A, pile=gained)[0]
    # two gains, two Watchtower windows: the INNER one (the upgraded card) is on
    # top; keep that, then trash the Farmland with the outer one
    for want in (gained, "Farmland"):
        f = xs_top(g)
        assert (f["card"], f["stage"]) == ("Watchtower", "react")
        assert decide(g, A, ids=["play"])[0]
        f = xs_top(g)
        assert (f["card"], f["stage"], f["data"]["card"]) == ("Watchtower", "act", want)
        assert decide(g, A, ids=["trash" if want == "Farmland" else "keep"])[0]
    assert "Farmland" in g["trash"] and "Estate" in g["trash"]
    assert gained in g["seats"][A]["discard"]            # the upgrade stands


def test_watchtower_gets_a_window_for_the_border_village_and_its_cheaper_card():
    """Two separate gains => two separate Watchtower windows (p22: 'if one
    effect tells you to gain several cards, you resolve each gain in turn,
    resolving any when-gain abilities after each')."""
    g = xs_fresh()
    xs_hand(g, A, ["Watchtower"])
    assert engine.gain(g, A, "Border Village")
    engine._drive(g)
    xs_pool(g, "Border Village")                         # its when-gain first
    assert (xs_top(g)["card"], xs_top(g)["stage"]) == ("Border Village", "gain")
    assert decide(g, A, pile="Village")[0]
    windows = 0
    for _ in range(4):
        f = xs_top(g)
        if f is None:
            break
        assert f["card"] == "Watchtower"
        if f["stage"] == "react":
            windows += 1
            assert decide(g, A, ids=["play"])[0]
        else:
            assert decide(g, A, ids=["topdeck"])[0]
    assert windows == 2
    assert g["seats"][A]["deck"][:2] == ["Border Village", "Village"]
    assert g["seats"][A]["discard"] == []


def test_watchtower_topdecking_a_gained_souk_keeps_the_souk_trash():
    """Souk's when-gain trashes up to 2 from HAND; moving the Souk afterwards
    cannot undo that."""
    g = xs_fresh()
    xs_hand(g, A, ["Watchtower", "Estate", "Estate"])
    assert engine.gain(g, A, "Souk")
    engine._drive(g)
    xs_pool(g, "Souk")                                   # its when-gain first
    assert (xs_top(g)["card"], xs_top(g)["stage"]) == ("Souk", "trash")
    assert decide(g, A, cards=["Estate", "Estate"])[0]
    assert g["trash"] == ["Estate", "Estate"]
    assert decide(g, A, ids=["play"])[0]
    assert decide(g, A, ids=["topdeck"])[0]
    assert g["seats"][A]["deck"][0] == "Souk"
    assert g["trash"] == ["Estate", "Estate"]


# ---------------------------------------------------------------------------
# 4. TRADER's exchange x the new when-gain triggers
# ---------------------------------------------------------------------------

def test_trader_exchanging_a_border_village_still_gains_the_cheaper_card():
    """'Even if you exchanged it, you DID gain the card (and triggered any
    when-gain ability). You DIDN'T gain the Silver.'"""
    g = xs_fresh()
    xs_hand(g, A, ["Trader"])
    g["phase"] = "buy"
    g["coins"] = 6
    n0 = g["supply"]["Border Village"]
    assert mv(g, A, {"type": "buy", "card": "Border Village"})[0]
    xs_pool(g, "Trader")                                 # exchange it FIRST
    assert (xs_top(g)["card"], xs_top(g)["stage"]) == ("Trader", "react")
    assert decide(g, A, ids=["play"])[0]
    assert g["supply"]["Border Village"] == n0           # handed straight back
    assert g["seats"][A]["discard"] == ["Silver"]
    # ...and Border Village's own when-gain still fires
    assert (xs_top(g)["card"], xs_top(g)["stage"]) == ("Border Village", "gain")
    assert decide(g, A, pile="Village")[0]
    assert decide(g, A, ids=["decline"])[0]              # Trader's next window
    assert g["seats"][A]["discard"] == ["Silver", "Village"]


def test_trader_exchange_fires_no_when_gain_for_the_silver():
    """exchange() emits nothing: the Silver is not gained, so it opens no
    when-gain window of its own. A Watchtower in hand counts the windows —
    exactly one, for the Gold that WAS gained."""
    g = xs_fresh()
    xs_hand(g, A, ["Trader", "Watchtower"])
    assert engine.gain(g, A, "Gold")
    engine._drive(g)
    windows = 0
    for _ in range(8):
        f = xs_top(g)
        if f is None:
            break
        if (f["card"], f["stage"]) == ("__abilities", "pick"):
            xs_pool(g, "Trader" if "Trader" in {o["label"] for o in
                                                f["constraint"]["options"]} else "Watchtower")
        elif (f["card"], f["stage"]) == ("Watchtower", "react"):
            windows += 1
            assert decide(g, A, ids=["decline"])[0]
        elif (f["card"], f["stage"]) == ("Trader", "react"):
            assert decide(g, A, ids=["play"])[0]
        else:
            assert decide(g, A, ids=["keep"])[0]
    assert windows == 1
    assert g["seats"][A]["discard"] == ["Silver"]
    assert g["supply"]["Gold"] == 30


def test_trader_exchanging_a_farmland_still_trashes_and_upgrades():
    g = xs_fresh()
    xs_hand(g, A, ["Trader", "Estate"])
    n0 = g["supply"]["Farmland"]
    assert engine.gain(g, A, "Farmland")
    engine._drive(g)
    xs_pool(g, "Trader")                                 # exchange it FIRST
    assert (xs_top(g)["card"], xs_top(g)["stage"]) == ("Trader", "react")
    assert decide(g, A, ids=["play"])[0]
    assert g["supply"]["Farmland"] == n0
    assert (xs_top(g)["card"], xs_top(g)["stage"]) == ("Farmland", "trash")
    assert decide(g, A, cards=["Estate"])[0]
    gained = xs_piles(g)[0]
    assert decide(g, A, pile=gained)[0]
    assert decide(g, A, ids=["decline"])[0]              # Trader sees THAT gain
    assert "Estate" in g["trash"]
    assert sorted(g["seats"][A]["discard"]) == sorted(["Silver", gained])


# ---------------------------------------------------------------------------
# 5. COST REDUCTION x the new cost checks
#    Bridge/Highway shift EVERY card; Quarry shifts only Actions; both floor at
#    $0. A uniform shift moves both sides of a comparison, so the tests that
#    matter are the asymmetric one (Quarry) and the ones where the floor bites.
# ---------------------------------------------------------------------------

def _xs_border_village_piles(g):
    assert engine.gain(g, A, "Border Village")
    engine._drive(g)
    return set(xs_piles(g))


def test_highway_shifts_border_villages_cheaper_cap_with_it():
    """'a cheaper card' is read against Border Village's CURRENT cost, so a
    uniform reduction moves both sides and the qualifying set is unchanged."""
    plain = _xs_border_village_piles(xs_fresh())
    g = xs_fresh()
    xs_hand(g, A, ["Highway"])
    assert xs_play(g, A, "Highway")[0]
    assert engine.cost(g, "Border Village") == 5
    assert _xs_border_village_piles(g) == plain
    assert "Duchy" in plain                              # $5 < $6, and $4 < $5
    assert "Border Village" not in plain                 # never itself: strict
    assert "Gold" not in plain                           # $6 is not cheaper


def test_quarry_splits_border_villages_cheaper_list_by_card_type():
    """Quarry only discounts ACTIONS, so the shift is asymmetric: Border
    Village drops to $4 and a $5 Victory card stops qualifying while a $5
    Action (now $3) still does."""
    g = xs_fresh()
    xs_hand(g, A, ["Quarry"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Quarry"})[0]
    assert engine.cost(g, "Border Village") == 4
    piles = _xs_border_village_piles(g)
    assert "Duchy" not in piles                          # $5 Victory: no discount
    assert "Highway" in piles                            # $5 Action -> $3
    assert "Duchy" in _xs_border_village_piles(xs_fresh())          # control


def test_quarry_shrinks_berserkers_own_cap_asymmetrically():
    g = xs_fresh()
    xs_hand(g, A, ["Quarry"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Quarry"})[0]
    g["phase"] = "action"
    g["actions"] = 1
    xs_hand(g, A, ["Berserker"])
    assert xs_play(g, A, "Berserker")[0]
    assert engine.cost(g, "Berserker") == 3
    piles = set(xs_piles(g))
    assert "Village" in piles                            # $3 Action -> $1
    assert "Silver" not in piles                         # $3 Treasure: not < $3
    assert "Highway" not in piles                        # $5 Action -> $3, not <


def test_quarry_lets_wheelwright_reach_a_seven_cost_action():
    """'as much as it or less' compares the DISCOUNTED costs, so a $5 Victory
    discard reaches a $7 Action while Quarry is out."""
    g = xs_fresh()
    xs_hand(g, A, ["Quarry"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Quarry"})[0]
    g["phase"] = "action"
    g["actions"] = 1
    xs_hand(g, A, ["Wheelwright", "Duchy"])
    g["seats"][A]["deck"] = ["Estate"] * 5
    assert xs_play(g, A, "Wheelwright")[0]
    assert decide(g, A, cards=["Duchy"])[0]
    assert "King's Court" in xs_piles(g)                 # $7 -> $5 <= $5
    g2 = xs_fresh()                                      # control, no Quarry
    xs_hand(g2, A, ["Wheelwright", "Duchy"])
    g2["seats"][A]["deck"] = ["Estate"] * 5
    assert xs_play(g2, A, "Wheelwright")[0]
    assert decide(g2, A, cards=["Duchy"])[0]
    assert "King's Court" not in xs_piles(g2)


def test_highway_floors_a_coppers_cost_so_farmland_upgrades_one_step_higher():
    """THE floor case: Copper reads $0 either way (max(0, -1) == 0), but the
    piles it is compared against ARE reduced — so 'exactly $2 more' resolves to
    the printed-$3 piles instead of the printed-$2 ones."""
    g = xs_fresh()
    xs_hand(g, A, ["Highway"])
    assert xs_play(g, A, "Highway")[0]
    xs_hand(g, A, ["Copper"])
    assert engine.cost(g, "Copper") == 0
    assert engine.gain(g, A, "Farmland")
    engine._drive(g)
    assert decide(g, A, cards=["Copper"])[0]
    piles = set(xs_piles(g))
    assert piles and all(XS_CARDS[p]["cost"] == 3 for p in piles), piles
    assert "Village" in piles and "Estate" not in piles
    g2 = xs_fresh()                                      # control, no Highway
    xs_hand(g2, A, ["Copper"])
    assert engine.gain(g2, A, "Farmland")
    engine._drive(g2)
    assert decide(g2, A, cards=["Copper"])[0]
    assert all(XS_CARDS[p]["cost"] == 2 for p in xs_piles(g2))


def test_highway_floors_a_coppers_cost_so_develop_has_no_cheaper_side():
    """Develop's 'exactly $1 less' side needs cost >= 1; the floor kills it, so
    the order question is never asked and only the $1-more side is offered."""
    g = xs_fresh()
    xs_hand(g, A, ["Highway", "Develop", "Copper"])
    g["actions"] = 2
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert xs_play(g, A, "Highway")[0]
    xs_hand(g, A, ["Develop", "Copper"])
    assert xs_play(g, A, "Develop")[0]
    assert decide(g, A, cards=["Copper"])[0]
    f = xs_top(g)
    assert (f["card"], f["stage"]) == ("Develop", "gain")   # not the order frame
    assert all(XS_CARDS[p]["cost"] == 2 for p in f["constraint"]["piles"])


def test_two_highways_floor_hagglers_cap_to_nothing():
    """Haggler's cap is the bought card's CURRENT cost; floored to $0 nothing
    is cheaper, so the watcher fires and offers nothing at all."""
    g = xs_fresh()
    xs_hand(g, A, ["Highway", "Highway", "Haggler"])
    g["actions"] = 3
    g["seats"][A]["deck"] = ["Copper"] * 12
    for c in ("Highway", "Highway", "Haggler"):
        assert xs_play(g, A, c)[0]
    assert g["turn_ctx"]["bridges"] == 2
    g["phase"] = "buy"
    g["coins"] = 3
    assert mv(g, A, {"type": "buy", "card": "Estate"})[0]
    assert engine.cost(g, "Estate") == 0
    assert xs_top(g) is None
    g2 = xs_fresh()                                      # control, no Highway
    xs_hand(g2, A, ["Haggler"])
    assert xs_play(g2, A, "Haggler")[0]
    g2["phase"] = "buy"
    g2["coins"] = 3
    assert mv(g2, A, {"type": "buy", "card": "Estate"})[0]
    assert set(xs_piles(g2)) == {"Copper", "Curse"}


# ---------------------------------------------------------------------------
# 6. THE UNDO AUDIT — undo is gated on HIDDEN INFORMATION, so every new card
#    that draws, looks or reveals must clear the stack, and every one that does
#    not must leave it standing.
# ---------------------------------------------------------------------------

XS_REVEALERS = [
    "Border Village",       # +1 Card
    "Cartographer",         # look at the top 4
    "Crossroads",           # reveal your hand
    "Jack of All Trades",   # look at the top card
    "Guard Dog", "Highway", "Inn", "Margrave", "Oasis", "Scheme", "Trail",
    "Wheelwright", "Witch's Hut",
]
XS_NON_REVEALERS = ["Berserker", "Develop", "Haggler", "Nomads", "Souk",
                    "Spice Merchant", "Stables", "Trader", "Weaver"]


@pytest.mark.parametrize("card", XS_REVEALERS)
def test_a_new_card_that_exposes_information_clears_the_undo_stack(card):
    g = xs_fresh()
    xs_hand(g, A, [card, "Copper", "Estate", "Estate"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert xs_play(g, A, card)[0]
    assert g["turn_revealed"] is True, card
    assert g["undo_stack"] == [], card
    assert mv(g, A, {"type": "undo_turn"}) == (False, "nothing to undo")


@pytest.mark.parametrize("card", XS_NON_REVEALERS)
def test_a_new_card_that_exposes_nothing_stays_undoable(card):
    g = xs_fresh()
    xs_hand(g, A, [card, "Copper", "Estate", "Estate"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    hand0 = list(g["seats"][A]["hand"])
    assert xs_play(g, A, card)[0]
    assert g["turn_revealed"] is False, card
    assert len(g["undo_stack"]) == 1, card
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["seats"][A]["hand"] == hand0
    assert g["seats"][A]["in_play"] == []
    assert g["pending"] == []


def test_inns_on_gain_shuffle_clears_the_undo_stack_even_with_nothing_to_shuffle():
    """'If you shuffle zero cards into your deck, you still shuffle' — the deck
    order changed under the player, so nothing before it may be rewound."""
    g = xs_fresh()
    xs_hand(g, A, ["Copper"])
    g["seats"][A]["discard"] = []
    g["phase"] = "buy"
    g["coins"] = 5
    assert mv(g, A, {"type": "buy", "card": "Inn"})[0]
    # the just-gained Inn is itself the only Action in the discard pile
    f = xs_top(g)
    assert (f["card"], f["stage"]) == ("Inn", "shuffle")
    assert f["constraint"]["cards"] == ["Inn"]
    assert g["undo_stack"] != []                 # the buy alone revealed nothing
    assert decide(g, A, cards=[])[0]             # shuffle ZERO cards...
    assert g["undo_stack"] == []                 # ...and the deck still shuffled
    assert g["turn_revealed"] is True
    assert "Inn" in g["seats"][A]["discard"]


def test_bulk_treasure_play_with_fools_gold_and_cauldron_stays_undoable():
    """Cauldron is a MANUAL treasure (its play opens an opponent window) and is
    skipped; Fool's Gold is bucket 3 and autoplays. Nothing in the bulk draws,
    looks or reveals, so the one move stays fully reversible."""
    g = xs_fresh()
    xs_hand(g, A, ["Fool's Gold", "Cauldron", "Copper", "Silver"])
    g["phase"] = "buy"
    keys = ("seats", "supply", "coins", "buys", "actions", "phase", "watchers",
            "turn_ctx", "pending", "trash")
    before = copy.deepcopy({k: g[k] for k in keys})
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert g["seats"][A]["hand"] == ["Cauldron"]           # manual: left behind
    assert sorted(g["seats"][A]["in_play"]) == ["Copper", "Fool's Gold", "Silver"]
    assert g["coins"] == 4                                 # 1 + 1 + 2
    assert g["turn_revealed"] is False
    assert len(g["undo_stack"]) == 1
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert {k: g[k] for k in keys} == before


def test_a_manual_cauldron_is_undoable_until_an_opponent_answers():
    """The manual bucket does not itself burn undo — an opponent's DECISION
    does (it is information the turn player did not have)."""
    g = xs_fresh()
    xs_hand(g, A, ["Cauldron"])
    xs_hand(g, B, ["Copper"] * 5)                # no reaction: no window opens
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Cauldron"})[0]
    assert g["undo_stack"] != []
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["seats"][A]["hand"] == ["Cauldron"]
    assert g["coins"] == 0 and g["buys"] == 1

    g2 = xs_fresh()
    xs_hand(g2, A, ["Cauldron"])
    xs_hand(g2, B, ["Moat"] + ["Copper"] * 4)
    g2["phase"] = "buy"
    assert mv(g2, A, {"type": "play_treasure", "card": "Cauldron"})[0]
    assert g2["pending_pid"] == B
    assert decide(g2, B, ids=["decline"])[0]
    assert g2["undo_stack"] == []                # the opponent answered: locked


# ---------------------------------------------------------------------------
# 7. ATTACK x REACTION cross-products
# ---------------------------------------------------------------------------

XS_OLD_ATTACKS = ["Militia", "Witch", "Torturer", "Minion", "Rabble", "Swindler"]
XS_NEW_ATTACKS = ["Margrave", "Witch's Hut", "Berserker"]


@pytest.mark.parametrize("atk", XS_OLD_ATTACKS)
def test_guard_dog_reacts_to_every_older_attack(atk):
    """Guard Dog is a REACTION THAT PLAYS ITSELF against ANY Attack, from any
    set — ATTACK_REACTIONS is what the kernel consults, so one registry entry
    covers every older attack the day it lands."""
    g = xs_fresh()
    xs_hand(g, A, [atk])
    g["seats"][A]["deck"] = ["Copper"] * 12
    xs_hand(g, B, ["Guard Dog", "Copper"])
    g["seats"][B]["deck"] = ["Estate"] * 10
    g["seats"][B]["discard"] = []
    assert xs_play(g, A, atk)[0]
    f = xs_top(g)
    assert (f["pid"], f["card"]) == (B, "__attack"), atk
    assert "react:Guard Dog" in [o["id"] for o in f["constraint"]["options"]]
    assert decide(g, B, ids=["react:Guard Dog"])[0]
    # 1 left in hand + 2 drawn, then <= 5 so +2 more
    assert len(g["seats"][B]["hand"]) == 5, atk
    assert g["seats"][B]["in_play"] == ["Guard Dog"]


def test_guard_dog_grants_no_immunity_to_an_older_attack():
    g = xs_fresh()
    xs_hand(g, A, ["Witch"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    xs_hand(g, B, ["Guard Dog", "Copper"])
    g["seats"][B]["deck"] = ["Estate"] * 10
    g["seats"][B]["discard"] = []
    assert xs_play(g, A, "Witch")[0]
    assert decide(g, B, ids=["react:Guard Dog"])[0]
    xs_run(g)
    assert "Curse" in g["seats"][B]["discard"]           # the attack still lands


def test_guard_dog_then_moat_chain_against_one_attack():
    """Several reactions against ONE played Attack: Guard Dog first (it grants
    no immunity, so the window re-opens), then the Moat that ends it."""
    g = xs_fresh()
    xs_hand(g, A, ["Militia"])
    xs_hand(g, B, ["Guard Dog", "Moat", "Copper"])
    g["seats"][B]["deck"] = ["Estate"] * 10
    g["seats"][B]["discard"] = []
    assert xs_play(g, A, "Militia")[0]
    assert set(xs_ids(g)) == {"react:Guard Dog", "react:Moat", "decline"}
    assert decide(g, B, ids=["react:Guard Dog"])[0]
    assert set(xs_ids(g)) == {"react:Moat", "decline"}   # the Guard Dog is spent
    assert decide(g, B, ids=["react:Moat"])[0]
    assert xs_top(g) is None                             # no discard: immune
    assert len(g["seats"][B]["hand"]) == 6


@pytest.mark.parametrize("atk", XS_NEW_ATTACKS)
def test_lighthouse_blocks_the_new_attacks(atk):
    """Lighthouse protection is a watcher, not a card in play; the kernel
    applies and logs it before any reaction window opens. (Moat vs each of
    these lives in the batch files; Lighthouse is the cross-set case.)"""
    g = xs_fresh()
    xs_lighthouse_for_b(g)
    xs_hand(g, A, [atk])
    xs_hand(g, B, ["Copper"] * 5)
    g["seats"][B]["discard"] = []
    g["phase"] = "action"
    g["actions"] = 1
    g["seats"][A]["deck"] = ["Village", "Village", "Copper", "Copper", "Copper"]
    assert xs_play(g, A, atk)[0]
    for _ in range(4):
        f = xs_top(g)
        if f is None:
            break
        assert f["pid"] == A, f"{atk}: the protected player was asked {f['card']}"
        c = f["constraint"]
        if f["kind"] == "choose_cards":
            assert decide(g, A, cards=list(c["cards"])[:c["min"]])[0]
        else:
            assert decide(g, A, pile=c["piles"][0])[0]
    assert len(g["seats"][B]["hand"]) == 5, atk
    assert g["seats"][B]["discard"] == [], atk


def test_lighthouse_blocks_the_cauldrons_curses():
    """Cauldron is an Attack TREASURE whose Curses land from a much later
    stage; the immunity captured at PLAY time has to reach them."""
    g = xs_fresh()
    xs_lighthouse_for_b(g)
    xs_hand(g, A, ["Cauldron"])
    g["seats"][B]["discard"] = []
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Cauldron"})[0]
    for _ in range(3):
        assert engine.gain(g, A, "Village")
        engine._drive(g)
    assert g["seats"][B]["discard"] == []
    assert g["supply"]["Curse"] == 10


def test_militia_discarding_a_tunnel_and_a_weaver_fires_both_reactions():
    """DISCARD DOWN TO X is ONE batch: the per-card when-discard triggers fire
    after the whole hand has moved, and BOTH new reactions get their window on
    the attacker's turn."""
    g = xs_fresh()
    xs_hand(g, A, ["Militia"])
    xs_hand(g, B, ["Tunnel", "Weaver", "Trail", "Copper", "Estate"])
    g["seats"][B]["deck"] = ["Estate"] * 6
    g["seats"][B]["discard"] = []
    assert xs_play(g, A, "Militia")[0]
    assert decide(g, B, cards=["Tunnel", "Weaver"])[0]
    seen = [(c, s) for _, c, s in xs_run(g, prefer=("play", "reveal", "silvers"))]
    assert ("Weaver", "self_play") in seen
    assert ("Tunnel", "reveal") in seen
    assert "Weaver" in g["seats"][B]["in_play"]          # it played itself
    assert g["seats"][B]["discard"].count("Gold") == 1   # Tunnel's Gold
    assert g["seats"][B]["discard"].count("Silver") == 2  # Weaver's Silvers
    assert "Trail" in g["seats"][B]["hand"]              # never discarded, never fired


def test_an_off_turn_weaver_is_swept_by_the_attackers_cleanup():
    """'You discard the card in THAT turn's Clean-up phase' — the attacker's."""
    g = xs_fresh()
    xs_hand(g, A, ["Margrave"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    xs_hand(g, B, ["Weaver", "Copper", "Copper", "Copper", "Estate"])
    g["seats"][B]["deck"] = ["Estate"] * 6
    g["seats"][B]["discard"] = []
    assert xs_play(g, A, "Margrave")[0]
    f = xs_top(g)
    assert (f["pid"], f["card"], f["stage"]) == (B, "Margrave", "discard")
    assert decide(g, B, cards=["Weaver", "Copper", "Copper"])[0]
    xs_run(g, prefer=("play", "silvers"))
    assert g["seats"][B]["in_play"] == ["Weaver"]
    xs_end_turn(g, A)
    assert g["seats"][B]["in_play"] == []
    assert "Weaver" in g["seats"][B]["discard"]


# ---------------------------------------------------------------------------
# 8. SAVE / MIGRATE / WIRE with the new state on the table
# ---------------------------------------------------------------------------

def _xs_loaded_position():
    """A game carrying the phase-3 state a save has to survive: three per-play
    watchers with live data, both lazy turn counters, and an open frame."""
    g = xs_fresh()
    xs_hand(g, A, ["Haggler", "Scheme", "Crossroads", "Estate"])
    g["actions"] = 3
    g["seats"][A]["deck"] = ["Copper"] * 12
    for c in ("Haggler", "Scheme", "Crossroads"):
        assert xs_play(g, A, c)[0]
    g["phase"] = "buy"
    xs_hand(g, A, ["Fool's Gold", "Cauldron"])
    assert mv(g, A, {"type": "play_treasure", "card": "Fool's Gold"})[0]
    assert mv(g, A, {"type": "play_treasure", "card": "Cauldron"})[0]
    engine._drive(g)
    assert g["turn_ctx"]["crossroads"] == 1
    assert g["turn_ctx"]["fools_gold"] == 1
    assert {w["card"] for w in g["watchers"]} == {"Haggler", "Scheme", "Cauldron"}
    return g


def test_a_hinterlands_position_round_trips_through_json_and_migrate():
    g = _xs_loaded_position()
    blob = json.dumps(g)
    loaded = engine.migrate(json.loads(blob))
    assert loaded == json.loads(blob), "migrate mutated a current-shape save"
    assert loaded["schema"] == engine.SCHEMA == 8
    rng = random.Random(11)
    for _ in range(120):                          # and it plays on from the blob
        if loaded["over"]:
            break
        pid = loaded["pending_pid"] or loaded["turn"]
        m = ({"type": "decision", **engine.sample_decision(loaded, pid, rng)}
             if loaded["pending_pid"] else rng.choice(engine.legal_moves(loaded, pid)))
        ok, err = engine.apply_move(loaded, pid, m)
        assert ok, err
        json.dumps(loaded)


def test_a_random_hinterlands_game_stays_json_safe_and_migration_stable():
    for seed in (1, 2, 3):
        g = xs_fresh(seed=seed)
        rng = random.Random(seed)
        for i in range(400):
            if g["over"]:
                break
            pid = g["pending_pid"] or g["turn"]
            m = ({"type": "decision", **engine.sample_decision(g, pid, rng)}
                 if g["pending_pid"] else rng.choice(engine.legal_moves(g, pid)))
            ok, err = engine.apply_move(g, pid, m)
            assert ok, err
            if i % 50 == 0:
                blob = json.dumps(g)
                assert engine.migrate(json.loads(blob)) == json.loads(blob)
        assert sum(s["turns_taken"] for s in g["seats"].values()) > 20


def test_player_view_leaks_no_new_hinterlands_state():
    g = _xs_loaded_position()
    xs_hand(g, A, ["Souk"])
    assert engine.gain(g, A, "Souk")
    engine._drive(g)
    assert g["pending_pid"] == A                  # a frame OWNED by A is open
    view = engine.player_view(g, B)
    json.dumps(view)
    assert "pending" not in view                  # no raw frames (frame DATA!)
    assert set(view["pending_view"]) == {"card", "waiting_on"}
    # watchers ship IDENTITY only — Cauldron's data holds its counter AND the
    # per-play immunity set; Haggler's and Scheme's hold resume context
    for w in view["watchers"]:
        assert set(w) == {"event", "owner", "card"}, w
    seat = view["seats"][A]
    for hidden in ("deck", "discard", "hand", "aside", "duration", "dur_setup"):
        assert hidden not in seat, hidden
    assert seat["discard_view"]["count"] >= 1
    assert set(seat["discard_view"]) == {"top", "count"}
    for gone in ("rng_state", "seed", "_cur_dur", "_actor", "undo_stack",
                 "_atk_immune"):
        assert gone not in view, gone
    assert view["undo_depth"] == len(g["undo_stack"])
    own = engine.player_view(g, A)                # the owner does see their hand
    assert own["seats"][A]["hand"] == ["Souk"]
    assert "deck" not in own["seats"][A]


# --- Tide Pools x two discarded Trails: the second is SHUFFLED AWAY -----------

def test_playing_the_first_discarded_trail_can_lose_track_of_the_second():
    """Reported from a real game as "I discarded two Trails and was only offered
    one". It is the lose-track rule, not a missed trigger: playing Trail #1
    draws, the draw finds an empty deck and SHUFFLES, and the shuffle sweeps the
    discard pile — Trail #2 with it — into the deck. "Cards that are lost track
    of can't be played", so its offer correctly never opens. The compendium
    walks through this very sequence in the Witch's Hut ruling (p168).

    What WAS wrong is that it happened in silence, so it is now logged."""
    g = fresh(["Trail", "Tide Pools", "Sea Chart", "Bazaar", "Nobles", "Market",
               "Festival", "Bishop", "Anvil", "Blockade"],
              expansions=("base", "seaside", "hinterlands"))
    # two Tide Pools played on turn 1 both finish at the start of turn 2
    give_hand(g, A, ["Tide Pools", "Tide Pools"])
    g["actions"] = 2
    assert mv(g, A, {"type": "play_action", "card": "Tide Pools"})[0]
    g["phase"] = "action"
    assert mv(g, A, {"type": "play_action", "card": "Tide Pools"})[0]
    drain_decisions(g)
    if g["phase"] == "action":
        assert mv(g, A, {"type": "end_phase"})[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    drain_decisions(g)
    assert mv(g, B, {"type": "end_phase"})[0]
    if g["turn"] == B:
        assert mv(g, B, {"type": "end_phase"})[0]
    assert g["turn"] == A
    assert [e.get("done") for e in g["seats"][A]["duration"]] == [True, True]

    # turn 2: two Trails in hand and an EMPTY deck, so Trail's +1 Card must shuffle
    mark = len(g["log"])
    give_hand(g, A, ["Trail", "Trail", "Copper", "Nobles", "Bazaar"])
    g["seats"][A]["deck"] = []
    g["seats"][A]["discard"] = []
    g["pending"][-1]["constraint"]["cards"] = list(g["seats"][A]["hand"])

    assert decide(g, A, cards=["Trail", "Trail"])[0]        # Tide Pools #1
    assert g["pending_kind"] == "choose_option" and g["pending"][-1]["card"] == "Trail"
    assert g["seats"][A]["discard"].count("Trail") == 2
    assert decide(g, A, ids=["play"])[0]                    # play the first one

    events = [e["event"] for e in g["log"][mark:]]
    assert "shuffle" in events, events                      # the draw emptied the deck
    assert g["seats"][A]["discard"].count("Trail") == 0     # #2 left the discard pile
    assert g["seats"][A]["in_play"].count("Trail") == 1     # only one was played
    # no second offer — and the log now SAYS why
    assert g["pending"][-1]["card"] == "Tide Pools"         # straight on to the next fx
    assert any(e.get("event") == "lost_track" and e.get("card") == "Trail"
               for e in g["log"][mark:]), g["log"][mark:]


def test_a_discarded_trail_that_stays_put_is_still_offered_twice():
    """The control: with cards left in the deck there is no shuffle, so BOTH
    discarded Trails keep their offer. Without this the test above would pass on
    a Trail trigger that had simply stopped firing."""
    g = fresh(["Trail", "Tide Pools", "Sea Chart", "Bazaar", "Nobles", "Market",
               "Festival", "Bishop", "Anvil", "Blockade"],
              expansions=("base", "seaside", "hinterlands"))
    give_hand(g, A, ["Tide Pools"])
    assert mv(g, A, {"type": "play_action", "card": "Tide Pools"})[0]
    drain_decisions(g)
    if g["phase"] == "action":
        assert mv(g, A, {"type": "end_phase"})[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    drain_decisions(g)
    assert mv(g, B, {"type": "end_phase"})[0]
    if g["turn"] == B:
        assert mv(g, B, {"type": "end_phase"})[0]
    assert g["turn"] == A

    give_hand(g, A, ["Trail", "Trail", "Copper"])
    g["seats"][A]["deck"] = ["Copper"] * 10        # deep enough that no draw shuffles
    g["seats"][A]["discard"] = []
    g["pending"][-1]["constraint"]["cards"] = list(g["seats"][A]["hand"])

    assert decide(g, A, cards=["Trail", "Trail"])[0]
    offers = 0
    for _ in range(6):
        if g["pending_kind"] == "choose_option" and g["pending"][-1]["card"] == "Trail":
            offers += 1
            assert decide(g, A, ids=["play"])[0]
        else:
            break
    assert offers == 2, f"both Trails must be offered, got {offers}"
    assert g["seats"][A]["in_play"].count("Trail") == 2
    assert not any(e.get("event") == "lost_track" for e in g["log"])


# --- batch discard: TWO reaction cards in one batch — the player ORDERS them ---

def test_batch_discard_reactions_are_the_players_choice_not_click_order():
    """Phase 3 (retires the old B4 accident). A multi-card discard moves the
    cards SIMULTANEOUSLY, so their when-discard abilities are concurrent and
    the owner picks what resolves first (p23 §2). Before this, the order was
    the reverse of the order the player happened to click the cards in the
    discard picker — a pure LIFO accident pinned by this test's predecessor.
    Now BOTH payload orders produce the same prompt, and the payload order is
    irrelevant to resolution."""
    def run(payload, pick_first):
        g = fresh(["Trail", "Tunnel", "Militia", "Village", "Smithy", "Moat",
                   "Market", "Festival", "Gardens", "Cellar"],
                  expansions=("base", "hinterlands"))
        g["seats"][B]["hand"] = ["Militia"]
        give_hand(g, A, ["Trail", "Tunnel", "Copper", "Copper", "Copper"])
        g["seats"][A]["deck"] = ["Gold"] * 5          # Trail's draw won't shuffle
        g["turn"] = B
        g["phase"] = "action"
        g["actions"] = 1
        assert mv(g, B, {"type": "play_action", "card": "Militia"})[0]
        assert g["pending_pid"] == A and g["pending_kind"] == "choose_cards"
        assert mv(g, A, {"type": "decision", "cards": list(payload)})[0]
        opts = xs_pool(g, pick_first)                 # ONE pool, the owner picks
        seq = []                                      # offers, in resolution order
        while g["pending_pid"] == A:
            top = g["pending"][-1]
            if (top["card"], top["stage"]) == ("__abilities", "pick"):
                xs_pool(g, top["constraint"]["options"][0]["label"])
            else:
                seq.append(top["card"])
                # decline every offer (last option = the don't-react branch)
                assert decide(g, A, ids=[top["constraint"]["options"][-1]["id"]])[0]
        return opts, seq

    # both payload orders present the SAME choice, and the player's pick — not
    # the click order — decides what resolves first
    for payload in (["Trail", "Tunnel"], ["Tunnel", "Trail"]):
        opts, seq = run(payload, "Tunnel")
        assert opts == ["Trail", "Tunnel"], opts
        assert seq == ["Tunnel", "Trail"], (payload, seq)
        opts, seq = run(payload, "Trail")
        assert seq == ["Trail", "Tunnel"], (payload, seq)


def test_batch_trash_reactions_share_one_pool_too():
    """The Steward ruling generalized: a multi-card trash is simultaneous, so
    a Trail trashed WITH other cards reacts from one pool (a single on-trash
    consumer: no prompt, exactly the old behaviour)."""
    g = fresh(["Trail", "Tunnel", "Militia", "Village", "Smithy", "Moat",
               "Market", "Festival", "Gardens", "Cellar"],
              expansions=("base", "hinterlands"))
    give_hand(g, A, ["Trail", "Copper"])
    engine.trash(g, A, ["Trail", "Copper"])           # one batch
    engine._drive(g)
    assert g["pending_kind"] == "choose_option"       # straight to Trail's offer
    assert g["pending"][-1]["card"] == "Trail"
    assert decide(g, A, ids=["play"])[0]              # plays from the trash
    assert "Trail" in g["seats"][A]["in_play"]
    assert g["trash"] == ["Copper"]


# --- Scheme x two copies of one Duration (the same-name, different-copy trap) --

def test_scheme_topdecks_the_finishing_duration_not_the_one_just_played():
    """A seat can hold a Tide Pools finishing at THIS clean-up and a second one
    just played, and the zones hold only NAMES. Scheme rightly offers the
    finishing copy — but `topdeck_from_play` matched in_play by name and took
    the fresh one, which then vanished from under `_cleanup_durations`' unguarded
    kept-out removal: `_end_turn` raised ValueError and the game was unplayable.
    Found by replaying bot games (the random-legal bot hits it in ~1.5% of games
    on a Scheme + Tide Pools kingdom)."""
    g = fresh(["Scheme", "Tide Pools", "Smithy", "Moat", "Village", "Militia",
               "Witch", "Gardens", "Warehouse", "Bazaar"],
              expansions=("base", "seaside", "hinterlands"))
    # turn 1: A plays a Tide Pools, which finishes at the START of A's turn 2
    give_hand(g, A, ["Tide Pools"])
    assert mv(g, A, {"type": "play_action", "card": "Tide Pools"})[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert mv(g, B, {"type": "end_phase"})[0]
    drain_decisions(g)                      # A's turn start: discard 2
    assert g["turn"] == A
    entry = g["seats"][A]["duration"][0]
    assert entry["card"] == "Tide Pools" and entry["done"]

    # turn 2: Scheme, then a SECOND Tide Pools - two copies on the table at once
    give_hand(g, A, ["Scheme", "Tide Pools"])
    g["phase"] = "action"                   # the turn-start discard auto-advanced it
    g["actions"] = 2
    assert mv(g, A, {"type": "play_action", "card": "Scheme"})[0]
    assert mv(g, A, {"type": "play_action", "card": "Tide Pools"})[0]
    assert g["seats"][A]["in_play"].count("Tide Pools") == 1
    assert engine.leaving_play(g, A).count("Tide Pools") == 1   # only the finishing one

    assert g["phase"] == "buy"                       # auto-advanced (no Actions left)
    assert mv(g, A, {"type": "end_phase"})[0]        # -> Scheme's offer
    assert g["pending_kind"] == "choose_cards" and g["pending_pid"] == A
    assert decide(g, A, cards=["Tide Pools"])[0]     # used to strand the fresh copy
    drain_decisions(g)

    # The finishing copy was topdecked (clean-up's draw-5 may have taken it
    # straight back into hand); the one played this turn is still on the table,
    # set up for A's next turn — and neither was discarded.
    seat = g["seats"][A]
    assert any(e.get("event") == "topdeck" and e.get("card") == "Tide Pools"
               and e.get("pid") == A for e in g["log"])
    assert seat["deck"].count("Tide Pools") + seat["hand"].count("Tide Pools") == 1
    assert seat["discard"].count("Tide Pools") == 0
    assert seat["in_play"] == []
    assert engine.duration_in_play(g, A, "Tide Pools")
    assert [e["card"] for e in seat["duration"]] == ["Tide Pools"]
    assert not seat["duration"][0].get("done")
    assert engine.owned_cards(g, A).count("Tide Pools") == 2   # nothing lost
    assert g["turn"] == B                                      # the turn ENDED


# ---------------------------------------------------------------------------
# 9. THE ABILITY POOL on one gain (p23 §2) — join filters and commuters
# ---------------------------------------------------------------------------

def test_pool_offers_only_abilities_that_would_actually_fire():
    """A watcher whose ability would no-op for THIS occurrence (a Haggler on a
    non-buy gain) must not join the pool — a prompt ordering a no-op against a
    real ability implies the no-op will do something. WATCHER_WHENS is the
    join-time filter; the stage keeps its own guard as the resolve-time
    re-check."""
    g = xs_fresh()
    xs_hand(g, A, ["Watchtower"])
    g["seats"][A]["in_play"] = ["Haggler"]
    from games.dontminion import engine as E2
    E2.add_watcher(g, A, "Haggler", "gain", stage="gain_check", until="turn_end")
    # a NON-buy gain: Haggler's when reads via_buy=False -> it never joins, so
    # the only consumer is Watchtower and there is NO pool prompt at all
    assert engine.gain(g, A, "Inn")
    engine._drive(g)
    f = xs_top(g)
    assert (f["card"], f["stage"]) == ("__abilities", "pick")
    labels = {o["label"] for o in f["constraint"]["options"]}
    assert labels == {"Inn", "Watchtower"}, labels        # no Haggler option


def test_commuting_abilities_never_prompt_and_still_pay():
    """Collection's +1 VP is decision-free and order-independent: it runs
    automatically, FIRST, and never appears in the what-resolves-first prompt —
    but it must still pay. Inn's own when-gain vs Watchtower remains a real
    choice on the same gain."""
    g = xs_fresh()
    xs_hand(g, A, ["Watchtower"])
    from games.dontminion import engine as E2
    E2.add_watcher(g, A, "Collection", "gain", stage="vp_check",
                   until="turn_end", commutes=True)
    assert engine.gain(g, A, "Inn")                       # an Action: VP due
    engine._drive(g)
    assert g["vp_tokens"][A] == 1                         # paid, no prompt for it
    f = xs_top(g)
    assert (f["card"], f["stage"]) == ("__abilities", "pick")
    labels = {o["label"] for o in f["constraint"]["options"]}
    assert labels == {"Inn", "Watchtower"}, labels        # Collection absent
    xs_pool2 = {o["label"]: o["id"] for o in f["constraint"]["options"]}
    assert decide(g, A, ids=[xs_pool2["Inn"]])[0]
    assert (xs_top(g)["card"], xs_top(g)["stage"]) == ("Inn", "shuffle")


# ═══════════════════════════════════════════════════════════════════════════
# Cornucopia & Guilds (phase 4) — the new mechanics against the old ones.
#
# This is the step that found the put-back/when-discard bug in FOUR cards in
# phase 3, three of them already shipped: a per-set batch can only ever be as
# correct as the precedent it copies, so the combos live here.
# ═══════════════════════════════════════════════════════════════════════════

CG = ("base", "intrigue", "cornucopia")


def cg(kingdom, players=(A, B), seed=42):
    return engine.new_game(list(players), list(CG), seed=seed,
                           kingdom=list(kingdom))


def _cg_board(*extra):
    """Ten piles: this set's cards plus enough ordinary ones to fill up."""
    base = ["Village", "Smithy", "Market", "Festival", "Laboratory",
            "Militia", "Mine", "Library", "Council Room", "Moat"]
    picked = list(extra) + [c for c in base if c not in extra]
    return picked[:10]


# --- Throne Room x the new cards ---------------------------------------------

def test_throne_room_on_merchant_guild_pays_twice():
    """"It's cumulative if played with a throne-room" — two watchers, two
    payouts, both reading the same Buy phase."""
    g = cg(_cg_board("Merchant Guild", "Throne Room"))
    give_hand(g, A, ["Throne Room", "Merchant Guild"])
    before = g["coffers"][A]
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert decide(g, A, cards=["Merchant Guild"])[0]
    assert g["buys"] == 3 and g["coins"] == 2          # both plays paid
    g["phase"] = "buy"
    g["coins"] = 10
    assert mv(g, A, {"type": "buy", "card": "Copper"})[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert g["coffers"][A] == before + 2, "one Coffers per PLAY, per card gained"


def test_throne_room_on_young_witch_opens_a_reaction_window_per_play():
    """Pinned deviation A1: one window PER REPLAY, so a Moat holder is asked
    twice."""
    g = cg(["Young Witch", "Throne Room", "Moat", "Village", "Smithy",
            "Market", "Festival", "Laboratory", "Militia", "Mine"])
    give_hand(g, A, ["Throne Room", "Young Witch"])
    g["seats"][A]["deck"] = ["Gold"] * 8
    give_hand(g, B, ["Moat"])
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert decide(g, A, cards=["Young Witch"])[0]
    windows = 0
    for _ in range(40):
        f = g["pending"][-1] if g["pending"] else None
        if f is None:
            break
        if f["pid"] == B and f["kind"] == "choose_option":
            windows += 1
            assert decide(g, B, ids=["react:Moat"])[0]
        else:
            pid = g["pending_pid"]
            assert decide(g, pid,
                          **engine.sample_decision(g, pid, random.Random(1)))[0]
    assert windows == 2, "one reaction window per replay"
    assert "Curse" not in g["seats"][B]["discard"]


def test_throne_room_on_butcher_gives_four_coffers_and_two_remodels():
    g = cg(_cg_board("Butcher", "Throne Room"))
    g["coffers"][A] = 0
    give_hand(g, A, ["Throne Room", "Butcher", "Estate", "Copper"])
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert decide(g, A, cards=["Butcher"])[0]
    assert g["coffers"][A] == 2
    assert decide(g, A, cards=[])[0]                   # decline the first trash
    assert g["coffers"][A] == 4, "the second play's +2 Coffers"
    assert decide(g, A, cards=["Estate"])[0]
    assert decide(g, A, ids=["4"])[0]                  # spend all four
    assert g["coffers"][A] == 0 and g["coins"] == 4


def test_throne_room_on_shop_cannot_replay_the_same_action():
    """Shop's "no copy in play" is re-read on the SECOND play, by which time
    the first play's card is on the table."""
    g = cg(_cg_board("Shop", "Throne Room"))
    give_hand(g, A, ["Throne Room", "Shop", "Village"])
    g["seats"][A]["deck"] = ["Gold"] * 8
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert decide(g, A, cards=["Shop"])[0]
    assert decide(g, A, cards=["Village"])[0]          # first play takes it
    f = g["pending"][-1] if g["pending"] else None
    assert f is None or "Village" not in f["constraint"].get("cards", [])


# --- Watchtower / the would-gain protocol x the new gains ---------------------

def test_watchtower_on_a_gained_farrier_and_the_overpay_still_pays():
    """The overpay ability is a WHEN-GAIN ability, so it fires on the same
    occurrence Watchtower reacts to — the player orders the two, and the
    overpay pays whichever way they order it."""
    g = engine.new_game([A, B], ["base", "prosperity", "cornucopia"], seed=4,
                        kingdom=["Farrier", "Watchtower", "Village", "Smithy",
                                 "Market", "Festival", "Laboratory", "Militia",
                                 "Mine", "Library"])
    g["phase"] = "buy"
    g["coins"] = 5
    give_hand(g, A, ["Watchtower"])
    g["seats"][A]["deck"] = ["Gold"] * 10
    assert mv(g, A, {"type": "buy", "card": "Farrier"})[0]
    assert decide(g, A, ids=["2"])[0]                  # overpay $2
    drain_decisions(g)
    assert g["turn_ctx"]["end_draw"] == 2, "the overpay paid regardless"


def test_watchtower_and_heralds_overpay_leave_exactly_one_herald():
    """"If you move the gained Herald from your discard pile after overpaying,
    cards like Watchtower lose track of it." Whichever order the pool resolves
    in, the card is neither duplicated nor lost."""
    g = engine.new_game([A, B], ["base", "prosperity", "cornucopia"], seed=4,
                        kingdom=["Herald", "Watchtower", "Village", "Smithy",
                                 "Market", "Festival", "Laboratory", "Militia",
                                 "Mine", "Library"])
    g["phase"] = "buy"
    g["coins"] = 6
    give_hand(g, A, ["Watchtower"])
    g["seats"][A]["discard"] = []
    g["seats"][A]["deck"] = ["Gold"] * 10
    assert mv(g, A, {"type": "buy", "card": "Herald"})[0]
    assert decide(g, A, ids=["2"])[0]
    drain_decisions(g)
    owned = engine.owned_cards(g, A)
    assert owned.count("Herald") + g["trash"].count("Herald") == 1


def test_trader_can_exchange_a_gained_farmhands():
    """Trader's exchange happens on the same gain; "you DID gain the card (and
    triggered any when-gain ability). You DIDN'T gain the Silver.\""""
    g = engine.new_game([A, B], ["base", "hinterlands", "cornucopia"], seed=4,
                        kingdom=["Farmhands", "Trader", "Village", "Smithy",
                                 "Market", "Festival", "Laboratory", "Militia",
                                 "Mine", "Library"])
    give_hand(g, A, ["Trader", "Copper"])
    engine.gain(g, A, "Farmhands")
    engine._drive(g)              # a direct gain parks an auto frame
    drain_decisions(g)
    owned = engine.owned_cards(g, A)
    assert owned.count("Farmhands") + owned.count("Silver") >= 1
    assert engine.pile_count(g, "Farmhands") in (9, 10)


# --- cost changes x the new cost checks --------------------------------------

def test_renown_and_bridge_stack_on_the_same_turn():
    g = engine.new_game([A, B], ["base", "intrigue", "cornucopia"], seed=4,
                        kingdom=["Joust", "Bridge", "Village", "Smithy",
                                 "Market", "Festival", "Laboratory", "Militia",
                                 "Mine", "Library"])
    give_hand(g, A, ["Bridge", "Renown"])
    g["actions"] = 2
    assert mv(g, A, {"type": "play_action", "card": "Bridge"})[0]
    assert mv(g, A, {"type": "play_action", "card": "Renown"})[0]
    assert engine.cost(g, "Gold") == 6 - 1 - 2
    assert g["buys"] == 3                              # 1 + Bridge + Renown


def test_a_cost_reduction_reaches_stonemasons_overpay_gains():
    """"Cost reduction might be applied on when-gain before you resolve the
    overpay ability" — the overpay gains are priced when they are chosen."""
    g = engine.new_game([A, B], ["base", "intrigue", "cornucopia"], seed=4,
                        kingdom=["Stonemason", "Bridge", "Village", "Smithy",
                                 "Market", "Festival", "Laboratory", "Militia",
                                 "Mine", "Library"])
    give_hand(g, A, ["Bridge"])
    assert mv(g, A, {"type": "play_action", "card": "Bridge"})[0]
    g["phase"] = "buy"
    g["coins"] = 6
    assert mv(g, A, {"type": "buy", "card": "Stonemason"})[0]   # now $1
    assert decide(g, A, ids=["2"])[0]                  # Actions costing $2 NOW
    f = g["pending"][-1]
    for p in f["constraint"]["piles"]:
        assert engine.cost(g, p) == 2


def test_horn_of_plenty_prices_with_the_turns_discount():
    g = engine.new_game([A, B], ["base", "intrigue", "cornucopia"], seed=4,
                        kingdom=["Horn of Plenty", "Bridge", "Village", "Smithy",
                                 "Market", "Festival", "Laboratory", "Militia",
                                 "Mine", "Library"])
    give_hand(g, A, ["Bridge", "Horn of Plenty"])
    assert mv(g, A, {"type": "play_action", "card": "Bridge"})[0]
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Horn of Plenty"})[0]
    f = g["pending"][-1]
    # 2 distinct cards in play (Bridge, Horn of Plenty) -> cap $2; Bridge has
    # made everything $1 cheaper, so the $3 Silver qualifies
    assert "Silver" in f["constraint"]["piles"]


# --- Coffers x the rest of the engine ----------------------------------------

def test_coffers_spent_before_a_buy_pay_for_it():
    g = cg(_cg_board("Candlestick Maker"))
    g["coffers"][A] = 3
    g["phase"] = "buy"
    g["coins"] = 3
    assert mv(g, A, {"type": "spend", "what": "coffers", "n": 3})[0]
    assert g["coins"] == 6
    assert mv(g, A, {"type": "buy", "card": "Gold"})[0]
    assert "Gold" in g["seats"][A]["discard"]


def test_spending_coffers_is_undoable_like_any_other_move():
    g = cg(_cg_board("Candlestick Maker"))
    g["coffers"][A] = 2
    engine._arm_undo(g)
    assert mv(g, A, {"type": "spend", "what": "coffers", "n": 2})[0]
    assert g["coins"] == 2 and g["coffers"][A] == 0
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["coins"] == 0 and g["coffers"][A] == 2


def test_choosing_an_overpay_amount_is_undoable():
    """Nothing about a buy is hidden information, so the whole thing — the
    price, the overpay and the gain — must still walk back."""
    g = cg(_cg_board("Farrier"))
    g["phase"] = "buy"
    g["coins"] = 5
    engine._arm_undo(g)
    assert mv(g, A, {"type": "buy", "card": "Farrier"})[0]
    assert decide(g, A, ids=["3"])[0]
    assert g["coins"] == 0 and g["turn_ctx"]["end_draw"] == 3
    for _ in range(4):
        if g["coins"] == 5:
            break
        assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["coins"] == 5
    assert g["turn_ctx"]["end_draw"] == 0
    assert "Farrier" not in g["seats"][A]["discard"]


# --- when-discard x the new discards -----------------------------------------

def test_tunnel_reacts_to_ferrymans_discard():
    """Ferryman's discard is an ordinary discard (not Clean-up), so a discarded
    Tunnel may be revealed for its Gold."""
    g = engine.new_game([A, B], ["base", "hinterlands", "cornucopia"], seed=4,
                        kingdom=["Ferryman", "Tunnel", "Village", "Smithy",
                                 "Market", "Festival", "Laboratory", "Militia",
                                 "Mine", "Library"])
    give_hand(g, A, ["Ferryman", "Tunnel"])
    g["seats"][A]["deck"] = ["Copper", "Copper"]
    assert mv(g, A, {"type": "play_action", "card": "Ferryman"})[0]
    assert decide(g, A, cards=["Tunnel"])[0]
    f = g["pending"][-1]
    assert f["card"] == "Tunnel"
    assert decide(g, A, ids=["reveal"])[0]
    assert "Gold" in g["seats"][A]["discard"]


def test_a_joust_province_set_aside_is_not_in_play_for_horn_of_plenty():
    """The set-aside is deliberately its own zone: a Province sitting in play
    would raise Horn of Plenty's cap by one, and Shop could count it."""
    g = cg(["Joust", "Horn of Plenty", "Village", "Smithy", "Market",
            "Festival", "Laboratory", "Militia", "Mine", "Library"])
    give_hand(g, A, ["Joust", "Province", "Horn of Plenty"])
    g["seats"][A]["deck"] = ["Copper"] * 5
    assert mv(g, A, {"type": "play_action", "card": "Joust"})[0]
    assert decide(g, A, cards=["Province"])[0]
    assert decide(g, A, pile="Renown")[0]
    assert g["seats"][A]["cleanup_aside"] == ["Province"]
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Horn of Plenty"})[0]
    f = g["pending"][-1]
    # in play: Joust + Horn of Plenty = 2 distinct. The Province is NOT there.
    assert all(engine.cost(g, p) <= 2 for p in f["constraint"]["piles"])


# --- the whole set under the bot ---------------------------------------------

@pytest.mark.parametrize("chunk", [0, 1, 2])
def test_the_bot_plays_a_cornucopia_board_to_the_end(chunk):
    """The tiers read the Supply to decide what to buy, and this set adds a
    spendable counter, an overpay prompt and two setup-chosen piles. Each of
    those is a place bot.choose could raise inside the server's guaranteed
    turn-finisher, where the failure is a stuck live game."""
    from games.dontminion import bot
    from games.dontminion.cards import KINGDOM
    names = sorted(KINGDOM["cornucopia"])
    kingdom = (names[chunk * 8: chunk * 8 + 10] + names)[:10]
    g = engine.new_game([A, B], list(CG), seed=100 + chunk, kingdom=kingdom)
    rng = random.Random(chunk)
    for _ in range(4000):
        if g["over"]:
            break
        pid = g["pending_pid"] or g["turn"]
        ok, err = engine.apply_move(g, pid, bot.choose(g, pid, rng, "bmplus"))
        assert ok, err
    assert g["over"], "the bots did not finish a Cornucopia & Guilds board"


# ═══════════════════════════════════════════════════════════════════════════
# Alchemy (phase 5) — the COST VECTOR against every other set's cost check.
#
# The vector's whole design claim is that the NUMBER forms absorbed it with no
# call-site change and only the CARD-reference forms had to move. That claim is
# about cards in other modules, so it can only be tested here.
# ═══════════════════════════════════════════════════════════════════════════

ALC = ("base", "intrigue", "alchemy")


def _alc(kingdom, players=(A, B), seed=42, expansions=ALC):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom))


def _fill(*extra):
    base = ["Village", "Smithy", "Market", "Festival", "Laboratory",
            "Militia", "Mine", "Library", "Council Room", "Moat"]
    return (list(extra) + [c for c in base if c not in extra])[:10]


@pytest.mark.parametrize("card,setup", [
    ("Workshop", None),
    ("Ironworks", None),
])
def test_a_number_bounded_gainer_never_offers_a_potion_card(card, setup):
    """The payoff claim, on cards nobody edited: their bound is "$N", and
    "up to $N" means "and no Potion"."""
    g = _alc(_fill(card, "Golem", "University", "Transmute"))
    give_hand(g, A, [card])
    assert mv(g, A, {"type": "play_action", "card": card})[0]
    f = g["pending"][-1]
    piles = f["constraint"].get("piles") or f["constraint"].get("cards")
    for p in ("Golem", "University", "Transmute"):
        assert p not in piles, f"{card} must not reach {p}"


def test_horn_of_plenty_never_gains_a_potion_card():
    g = engine.new_game([A, B], ["base", "cornucopia", "alchemy"], seed=4,
                        kingdom=["Horn of Plenty", "Transmute", "University",
                                 "Village", "Smithy", "Market", "Festival",
                                 "Laboratory", "Militia", "Moat"])
    g["seats"][A]["in_play"] = ["Village", "Smithy", "Market", "Festival"]
    give_hand(g, A, ["Horn of Plenty"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Horn of Plenty"})[0]
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Transmute" not in piles, "{$0,P} is not 'up to $5'"
    assert "University" not in piles
    assert "Silver" in piles


def test_stonemason_uses_the_vector_when_it_trashes_a_potion_card():
    """"Each costing less than it" against {$4,P}: {$3,P} and {$4} are both
    lower, {$5} is not, and {$4,P} itself is not."""
    g = engine.new_game([A, B], ["base", "cornucopia", "alchemy"], seed=4,
                        kingdom=["Stonemason", "Golem", "Alchemist", "Duchy"
                                 if False else "Village", "Smithy", "Market",
                                 "Festival", "Laboratory", "Militia", "Moat"])
    give_hand(g, A, ["Stonemason", "Golem"])
    assert mv(g, A, {"type": "play_action", "card": "Stonemason"})[0]
    assert decide(g, A, cards=["Golem"])[0]
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Alchemist" in piles, "{$3,P} is lower than {$4,P}"
    assert "Village" in piles, "{$3} is lower — nothing is higher"
    assert "Golem" not in piles, "equal is not lower"
    assert "Duchy" not in piles, "{$5} has higher coins"


def test_butchers_coffers_delta_reaches_a_potion_card():
    """Butcher's bound is "up to $1 more per Coffers spent than IT", a CARD
    reference — so trashing a Potion card can reach another one."""
    g = engine.new_game([A, B], ["base", "cornucopia", "alchemy"], seed=4,
                        kingdom=["Butcher", "Golem", "Alchemist", "University",
                                 "Village", "Smithy", "Market", "Festival",
                                 "Laboratory", "Moat"])
    g["coffers"][A] = 0
    give_hand(g, A, ["Butcher", "Alchemist"])
    assert mv(g, A, {"type": "play_action", "card": "Butcher"})[0]
    assert decide(g, A, cards=["Alchemist"])[0]        # trash {$3,P}
    assert decide(g, A, ids=["1"])[0]                  # up to {$4,P}
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Golem" in piles, "{$4,P} is within 'up to $1 more than {$3,P}'"
    assert "Village" in piles, "a cheaper non-Potion card is still reachable"


def test_a_cost_reduction_moves_the_coins_and_leaves_the_potion_alone():
    """Bridge reduces $ costs. It does not make a Golem cost fewer Potions, so
    a Potion is still required to buy one."""
    g = _alc(_fill("Bridge", "Golem"))
    give_hand(g, A, ["Bridge"])
    assert mv(g, A, {"type": "play_action", "card": "Bridge"})[0]
    assert engine.cost(g, "Golem") == 3
    assert engine.potion_cost(g, "Golem") == 1
    g["phase"] = "buy"
    g["coins"] = 9
    g["potions"] = 0
    assert {"type": "buy", "card": "Golem"} not in engine.legal_moves(g, A)
    ok, err = mv(g, A, {"type": "buy", "card": "Golem"})
    assert not ok and err == "not enough Potions"


def test_upgrade_needs_the_potion_components_to_match():
    """Upgrade is "exactly $1 more", which means "the same cost plus $1" —
    trashing a plain $2 card can never reach a {$3,P}."""
    g = _alc(_fill("Upgrade", "Alchemist", "Apothecary"))
    give_hand(g, A, ["Upgrade", "Estate"])
    assert mv(g, A, {"type": "play_action", "card": "Upgrade"})[0]
    assert decide(g, A, cards=["Estate"])[0]           # {$2} -> exactly {$3}
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Silver" in piles
    assert "Alchemist" not in piles, "{$3,P} is not exactly $1 more than {$2}"


def test_upgrading_a_potion_card_reaches_the_next_potion_card_up():
    g = _alc(_fill("Upgrade", "Alchemist", "Apothecary"))
    give_hand(g, A, ["Upgrade", "Apothecary"])
    assert mv(g, A, {"type": "play_action", "card": "Upgrade"})[0]
    assert decide(g, A, cards=["Apothecary"])[0]       # {$2,P} -> exactly {$3,P}
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Alchemist" in piles
    assert "Silver" not in piles, "{$3} is not exactly $1 more than {$2,P}"


def test_the_potion_pool_is_undoable_like_the_coin_pool():
    g = _alc(_fill("Golem"))
    give_hand(g, A, ["Potion"])
    g["phase"] = "buy"
    engine._arm_undo(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Potion"})[0]
    assert g["potions"] == 1
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["potions"] == 0
    assert "Potion" in g["seats"][A]["hand"]


@pytest.mark.parametrize("seed", [0, 1])
def test_the_bot_plays_an_alchemy_board_to_the_end(seed):
    """The tiers price every pile they consider, and this set adds a second
    cost component. A bot that ignored it would try to buy what it cannot
    afford — inside the server's guaranteed turn-finisher."""
    from games.dontminion import bot
    from games.dontminion.cards import KINGDOM
    kingdom = (sorted(KINGDOM["alchemy"]) + _fill())[:10]
    g = engine.new_game([A, B], list(ALC), seed=200 + seed, kingdom=kingdom)
    rng = random.Random(seed)
    for _ in range(4000):
        if g["over"]:
            break
        pid = g["pending_pid"] or g["turn"]
        ok, err = engine.apply_move(g, pid, bot.choose(g, pid, rng, "bmplus"))
        assert ok, err
    assert g["over"], "the bots did not finish an Alchemy board"


def test_a_mandatory_trasher_cannot_eat_the_bots_whole_deck():
    """THE REGRESSION. On an Alchemy board (seed 7) two bmplus bots each bought
    an Apprentice, and the decision policy fed it the cheapest card in hand
    every turn — Coppers, then Silvers, then everything. Both decks reached a
    single Apprentice, neither could ever buy again, and the game ran 9908
    turns without ending. The economy guard existed but only covered OPTIONAL
    thinning; a mandatory trash walked straight past it into the fallback.

    Asserted as "the game ends", because that is the property that broke: a
    live room would have hung forever."""
    from games.dontminion import bot
    g = engine.new_game([A, B], ["alchemy"], seed=7)
    rng = random.Random(7)
    for _ in range(6000):
        if g["over"]:
            break
        pid = g["pending_pid"] or g["turn"]
        ok, err = engine.apply_move(g, pid, bot.choose(g, pid, rng, "bmplus"))
        assert ok, err
    assert g["over"], "the bots ground each other into an unwinnable stalemate"
    for p in (A, B):
        owned = engine.owned_cards(g, p)
        money = sum(engine.coins_of(g, c) for c in owned
                    if engine.has_type(g, c, "treasure"))
        assert money > 3, f"{p} trashed its economy away ({sorted(set(owned))})"


def test_no_alchemy_card_is_ranked_as_a_big_money_terminal():
    """A measurement, not an oversight — see BM_TERMINALS. Ranking Apprentice
    there read 0.1875 against plain bigmoney, because a money deck that buys a
    mandatory trasher feeds it Treasures."""
    from games.dontminion import bot_traits
    from games.dontminion.cards import KINGDOM
    for name in KINGDOM["alchemy"]:
        assert bot_traits.traits(name)["bm_terminal_rank"] == 0, name
