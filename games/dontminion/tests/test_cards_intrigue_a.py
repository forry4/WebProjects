"""Intrigue batch A rules tests: Courtyard, Pawn, Shanty Town, Steward,
Wishing Well, Baron, Bridge, Conspirator, Ironworks, Mill, Mining Village,
Nobles, Upgrade, Trading Post."""

from games.dontminion import engine

A, B = "alice", "bob"
KIA = ["Courtyard", "Pawn", "Shanty Town", "Steward", "Wishing Well", "Baron",
       "Bridge", "Conspirator", "Ironworks", "Mill", "Mining Village", "Nobles",
       "Upgrade", "Trading Post", "Throne Room", "Smithy"]


def fresh(seed=42):
    return engine.new_game([A, B], ["base", "intrigue"], seed=seed, kingdom=KIA)


def give_hand(g, pid, cards):
    g["seats"][pid]["hand"] = list(cards)


def play(g, pid, card):
    return engine.apply_move(g, pid, {"type": "play_action", "card": card})


def decide(g, pid, **payload):
    return engine.apply_move(g, pid, {"type": "decision", **payload})


def test_courtyard():
    g = fresh()
    give_hand(g, A, ["Courtyard", "Estate"])
    g["seats"][A]["deck"] = ["Copper", "Silver", "Gold", "Copper"]
    assert play(g, A, "Courtyard")[0]
    assert len(g["seats"][A]["hand"]) == 4
    assert decide(g, A, cards=["Gold"])[0]
    assert g["seats"][A]["deck"][0] == "Gold"
    assert len(g["seats"][A]["hand"]) == 3


def test_pawn_two_distinct_enforced():
    g = fresh()
    give_hand(g, A, ["Pawn"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    assert play(g, A, "Pawn")[0]
    ok, _ = decide(g, A, ids=["card"])
    assert not ok                                    # must pick exactly 2
    ok, _ = decide(g, A, ids=["coin", "coin"])
    assert not ok                                    # must be different
    assert decide(g, A, ids=["card", "buy"])[0]
    assert len(g["seats"][A]["hand"]) == 1 and g["buys"] == 2


def test_pawn_action_and_coin():
    g = fresh()
    give_hand(g, A, ["Pawn"])
    assert play(g, A, "Pawn")[0]
    assert decide(g, A, ids=["action", "coin"])[0]
    assert g["actions"] == 1 and g["coins"] == 1     # spent 1, got 1 back


def test_shanty_town_conditional_draw():
    g = fresh()
    give_hand(g, A, ["Shanty Town", "Copper", "Estate"])
    g["seats"][A]["deck"] = ["Silver"] * 4
    assert play(g, A, "Shanty Town")[0]
    assert g["actions"] == 2                          # -1 play +2
    assert len(g["seats"][A]["hand"]) == 4            # no actions in hand -> +2 cards
    g2 = fresh()
    give_hand(g2, A, ["Shanty Town", "Smithy"])
    assert play(g2, A, "Shanty Town")[0]
    assert len(g2["seats"][A]["hand"]) == 1           # Smithy in hand -> no draw
    reveals = [e for e in g2["log"] if e["event"] == "reveal" and e["pid"] == A]
    assert reveals and "Smithy" in reveals[-1]["cards"]


def test_steward_three_branches_and_short_trash():
    g = fresh()
    give_hand(g, A, ["Steward"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    assert play(g, A, "Steward")[0]
    assert decide(g, A, ids=["cards"])[0]
    assert len(g["seats"][A]["hand"]) == 2
    g = fresh()
    give_hand(g, A, ["Steward"])
    assert play(g, A, "Steward")[0]
    assert decide(g, A, ids=["coins"])[0]
    assert g["coins"] == 2
    g = fresh()
    give_hand(g, A, ["Steward", "Curse"])             # only 1 card left after play
    assert play(g, A, "Steward")[0]
    assert decide(g, A, ids=["trash"])[0]
    assert g["pending"][-1]["constraint"]["min"] == 1  # clamped to the whole hand
    assert decide(g, A, cards=["Curse"])[0]
    assert g["trash"] == ["Curse"]                     # as much as possible


def test_wishing_well_hit_and_miss():
    g = fresh()
    give_hand(g, A, ["Wishing Well"])
    g["seats"][A]["deck"] = ["Copper", "Province", "Estate"]
    assert play(g, A, "Wishing Well")[0]              # draws the Copper
    assert g["pending_kind"] == "name_card"
    assert decide(g, A, card="Province")[0]
    assert "Province" in g["seats"][A]["hand"]        # named it -> in hand
    g2 = fresh()
    give_hand(g2, A, ["Wishing Well"])
    g2["seats"][A]["deck"] = ["Copper", "Estate", "Gold"]
    assert play(g2, A, "Wishing Well")[0]
    assert decide(g2, A, card="Province")[0]
    assert "Estate" not in g2["seats"][A]["hand"]     # miss -> back on top
    assert g2["seats"][A]["deck"][0] == "Estate"


def test_baron_all_branches():
    g = fresh()
    give_hand(g, A, ["Baron", "Estate"])
    assert play(g, A, "Baron")[0]
    assert g["buys"] == 2
    assert decide(g, A, ids=["discard"])[0]
    assert g["coins"] == 4 and g["seats"][A]["discard"] == ["Estate"]
    g = fresh()
    give_hand(g, A, ["Baron", "Estate"])
    assert play(g, A, "Baron")[0]
    assert decide(g, A, ids=["gain"])[0]
    assert g["coins"] == 0
    assert g["seats"][A]["discard"] == ["Estate"]     # gained one, kept the hand one
    assert "Estate" in g["seats"][A]["hand"]
    g = fresh()
    give_hand(g, A, ["Baron", "Copper"])
    assert play(g, A, "Baron")[0]                     # no Estate: auto-gain
    assert g["pending_pid"] is None
    assert g["seats"][A]["discard"] == ["Estate"]
    g = fresh()
    g["supply"]["Estate"] = 0
    give_hand(g, A, ["Baron", "Copper"])
    assert play(g, A, "Baron")[0]                     # empty pile: gain fizzles
    assert g["seats"][A]["discard"] == []


def test_bridge_stacks_and_buy_discount():
    g = fresh()
    give_hand(g, A, ["Bridge", "Bridge", "Smithy"])
    g["actions"] = 2                                  # Bridge grants buys, not actions
    assert play(g, A, "Bridge")[0]
    assert engine.apply_move(g, A, {"type": "play_action", "card": "Bridge"})[0]
    assert g["coins"] == 2 and g["buys"] == 3
    assert engine.cost(g, "Smithy") == 2 and engine.cost(g, "Copper") == 0
    assert g["phase"] == "buy"      # actions ran dry -> auto-advanced
    assert engine.apply_move(g, A, {"type": "buy", "card": "Smithy"})[0]
    assert g["coins"] == 0                            # paid the reduced 2


def test_conspirator_counts_and_throne_room_doubles():
    g = fresh()
    give_hand(g, A, ["Conspirator", "Conspirator", "Conspirator"])
    g["seats"][A]["deck"] = ["Gold"] * 3
    g["actions"] = 3
    assert play(g, A, "Conspirator")[0]               # 1st: no bonus
    assert len(g["seats"][A]["hand"]) == 2 and g["actions"] == 2
    assert play(g, A, "Conspirator")[0]               # 2nd: no bonus
    assert len(g["seats"][A]["hand"]) == 1 and g["actions"] == 1
    assert play(g, A, "Conspirator")[0]               # 3rd: +1 card +1 action
    assert len(g["seats"][A]["hand"]) == 1 and g["actions"] == 1
    g = fresh()
    give_hand(g, A, ["Throne Room", "Conspirator"])
    g["seats"][A]["deck"] = ["Gold"] * 3
    assert play(g, A, "Throne Room")[0]
    assert decide(g, A, cards=["Conspirator"])[0]
    # plays: TR(1) + Conspirator(2) -> no bonus; Conspirator again(3) -> bonus
    assert g["coins"] == 4
    assert len(g["seats"][A]["hand"]) == 1 and g["actions"] == 1


def test_ironworks_dual_type_bonuses():
    g = fresh()
    give_hand(g, A, ["Ironworks"])
    g["seats"][A]["deck"] = ["Gold"] * 2
    assert play(g, A, "Ironworks")[0]
    assert decide(g, A, pile="Mill")[0]               # action+victory
    assert g["actions"] == 1                          # -1 play, +1 back
    assert len(g["seats"][A]["hand"]) == 1            # +1 card from victory
    g = fresh()
    give_hand(g, A, ["Ironworks"])
    assert play(g, A, "Ironworks")[0]
    assert decide(g, A, pile="Silver")[0]
    assert g["coins"] == 1 and g["actions"] == 0


def test_mill_pay_only_on_full_discard():
    g = fresh()
    give_hand(g, A, ["Mill", "Copper", "Copper"])
    g["seats"][A]["deck"] = ["Estate"] * 2
    assert play(g, A, "Mill")[0]
    assert decide(g, A, ids=["discard"])[0]
    assert decide(g, A, cards=["Copper", "Copper"])[0]
    assert g["coins"] == 2
    g = fresh()
    give_hand(g, A, ["Mill"])                          # hand will hold only the draw
    g["seats"][A]["deck"] = ["Estate"]
    assert play(g, A, "Mill")[0]
    assert decide(g, A, ids=["discard"])[0]            # option offered regardless
    assert g["pending"][-1]["constraint"]["min"] == 1   # clamped
    assert decide(g, A, cards=["Estate"])[0]
    assert g["coins"] == 0                              # 1 discarded: unpaid
    g = fresh()
    give_hand(g, A, ["Mill", "Copper", "Copper"])
    g["seats"][A]["deck"] = ["Estate"]
    assert play(g, A, "Mill")[0]
    assert decide(g, A, ids=["keep"])[0]
    assert g["coins"] == 0 and g["pending_pid"] is None


def test_mining_village_trash_once_under_throne_room():
    g = fresh()
    give_hand(g, A, ["Mining Village"])
    g["seats"][A]["deck"] = ["Gold"] * 2
    assert play(g, A, "Mining Village")[0]
    assert decide(g, A, ids=["trash"])[0]
    assert "Mining Village" in g["trash"] and g["coins"] == 2
    g = fresh()
    give_hand(g, A, ["Throne Room", "Mining Village"])
    g["seats"][A]["deck"] = ["Gold"] * 3
    assert play(g, A, "Throne Room")[0]
    assert decide(g, A, cards=["Mining Village"])[0]
    assert decide(g, A, ids=["trash"])[0]              # trash on the FIRST play
    # second play: lost track — no prompt, but +1 Card +2 Actions still happen
    assert g["pending_pid"] is None
    assert g["coins"] == 2                             # +$2 only once
    assert g["trash"].count("Mining Village") == 1
    assert g["actions"] == 4                           # 1 - 1(TR) + 2 + 2
    assert len(g["seats"][A]["hand"]) == 2             # two draws


def test_nobles_both_modes():
    g = fresh()
    give_hand(g, A, ["Nobles"])
    g["seats"][A]["deck"] = ["Copper"] * 4
    assert play(g, A, "Nobles")[0]
    assert decide(g, A, ids=["cards"])[0]
    assert len(g["seats"][A]["hand"]) == 3
    g = fresh()
    give_hand(g, A, ["Nobles"])
    assert play(g, A, "Nobles")[0]
    assert decide(g, A, ids=["actions"])[0]
    assert g["actions"] == 2


def test_upgrade_exact_cost_and_bridge():
    g = fresh()
    give_hand(g, A, ["Upgrade", "Estate"])             # Estate $2 -> exactly $3
    g["seats"][A]["deck"] = ["Copper"] * 2
    assert play(g, A, "Upgrade")[0]
    assert decide(g, A, cards=["Estate"])[0]
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Silver" in piles and "Smithy" not in piles and "Estate" not in piles
    assert decide(g, A, pile="Silver")[0]
    assert g["seats"][A]["discard"][-1] == "Silver"
    # no pile costs exactly cost+1 -> trash only
    g = fresh()
    give_hand(g, A, ["Upgrade", "Copper"])             # $0 -> exactly $1: none
    g["seats"][A]["deck"] = ["Copper"] * 2
    assert play(g, A, "Upgrade")[0]
    assert decide(g, A, cards=["Copper"])[0]
    assert g["pending_pid"] is None and "Copper" in g["trash"]
    # Bridge shifts the printed costs uniformly: Copper($0)+1 == Silver(3-2=1)
    g = fresh()
    give_hand(g, A, ["Upgrade", "Copper"])
    g["seats"][A]["deck"] = ["Copper"] * 2
    g["turn_ctx"]["bridges"] = 2
    assert play(g, A, "Upgrade")[0]
    assert decide(g, A, cards=["Copper"])[0]
    assert "Silver" in g["pending"][-1]["constraint"]["piles"]


def test_trading_post_needs_both_trashed():
    g = fresh()
    give_hand(g, A, ["Trading Post", "Copper", "Estate"])
    assert play(g, A, "Trading Post")[0]
    assert decide(g, A, cards=["Copper", "Estate"])[0]
    assert "Silver" in g["seats"][A]["hand"]
    g = fresh()
    give_hand(g, A, ["Trading Post", "Copper"])        # only 1 card to trash
    assert play(g, A, "Trading Post")[0]
    assert decide(g, A, cards=["Copper"])[0]
    assert "Copper" in g["trash"]
    assert "Silver" not in g["seats"][A]["hand"]       # "if you did" failed
    g = fresh()
    give_hand(g, A, ["Trading Post"])                  # empty hand: nothing
    assert play(g, A, "Trading Post")[0]
    assert g["pending_pid"] is None
