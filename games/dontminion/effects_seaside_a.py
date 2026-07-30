"""Seaside-2E card effects, batch A (WP-seaside-a).

Owns: Astrolabe, Bazaar, Caravan, Cutpurse, Fishing Village, Haven, Lighthouse,
Lookout, Merchant Ship, Salvager, Sea Chart, Sea Witch, Tide Pools, Warehouse,
Wharf.

See effects_core.py for the EFFECTS/STAGES contract and engine.py's DURATION
kernel notes: add_duration_fx registers a start-of-NEXT-turn ability on the
card currently being played; an effect that registers nothing "failed to set
up" and the kernel discards the card normally this turn.
"""

from . import engine as E


# Shared next-turn "discard exactly N" resolver (Sea Witch / Tide Pools /
# Warehouse) — the pushers clamp via push_choose_cards and skip empty hands.
def _discard_picked(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


# --- Astrolabe (Treasure-Duration) -------------------------------------------
# Called by the treasure handler AFTER its printed $1 is banked.

def _astrolabe(game, pid):
    E.add_buys(game, 1)
    E.add_duration_fx(game, pid, "Astrolabe", "turn_start")


def _astrolabe_turn_start(game, pid, frame, choice):
    E.add_coins(game, 1)
    E.add_buys(game, 1)


# --- Bazaar ------------------------------------------------------------------

def _bazaar(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 2)
    E.add_coins(game, 1)


# --- Caravan -----------------------------------------------------------------

def _caravan(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_duration_fx(game, pid, "Caravan", "turn_start")


def _caravan_turn_start(game, pid, frame, choice):
    E.draw(game, pid, 1)


# --- Cutpurse ----------------------------------------------------------------

def _cutpurse(game, pid):
    E.add_coins(game, 2)
    E.attack_opponents(game, pid, "Cutpurse", "hit")


def _cutpurse_hit(game, pid, frame, choice):
    # Mandatory, no choice: exactly one Copper, or the whole hand is revealed
    # (an empty hand reveals empty — it proves the no-Copper claim).
    hand = game["seats"][pid]["hand"]
    if "Copper" in hand:
        E.discard(game, pid, ["Copper"])
    else:
        E.reveal(game, pid, list(hand), "hand")


# --- Fishing Village ---------------------------------------------------------

def _fishing_village(game, pid):
    E.add_actions(game, 2)
    E.add_coins(game, 1)
    E.add_duration_fx(game, pid, "Fishing Village", "turn_start")


def _fishing_village_turn_start(game, pid, frame, choice):
    E.add_actions(game, 1)
    E.add_coins(game, 1)


# --- Haven -------------------------------------------------------------------

def _haven(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    hand = game["seats"][pid]["hand"]
    # Empty hand after the draw: no frame, no fx — "failed to set up", the
    # kernel discards Haven normally at this turn's clean-up.
    if hand:
        E.push_choose_cards(game, pid, "Haven", "aside",
                            cards=list(hand), mn=1, mx=1, purpose="set aside")


def _haven_aside(game, pid, frame, choice):
    card = choice["cards"][0]
    E.set_aside_duration(game, pid, [card])
    E.add_duration_fx(game, pid, "Haven", "turn_start", data={"card": card})


def _haven_turn_start(game, pid, frame, choice):
    E.take_dur_aside(game, pid, [frame["data"]["card"]], dest="hand")


# --- Lighthouse --------------------------------------------------------------

def _lighthouse(game, pid):
    E.add_actions(game, 1)
    E.add_coins(game, 1)
    E.add_duration_fx(game, pid, "Lighthouse", "turn_start")
    # 2022 wording: an until-your-next-turn ongoing protection, NOT
    # while-in-play. No stage — the kernel's attack wrap consults it.
    E.add_watcher(game, pid, "Lighthouse", "protect")


def _lighthouse_turn_start(game, pid, frame, choice):
    E.add_coins(game, 1)


# --- Lookout -----------------------------------------------------------------
# Trash 1 (mandatory), discard 1, last one back on top. A frame is pushed only
# while there is a genuine choice of WHICH card; a single-card remainder is
# resolved directly.

def _lookout(game, pid):
    E.add_actions(game, 1)
    looked = E.look_top(game, pid, 3)
    if not looked:
        return
    if len(looked) == 1:
        E.trash(game, pid, looked, zone="aside")
        return
    E.push_choose_cards(game, pid, "Lookout", "trash",
                        cards=list(looked), mn=1, mx=1, purpose="trash",
                        data={"looked": list(looked)})


def _lookout_trash(game, pid, frame, choice):
    E.trash(game, pid, choice["cards"], zone="aside")
    rest = list(frame["data"]["looked"])
    rest.remove(choice["cards"][0])
    if len(rest) == 1:
        E.discard(game, pid, rest, zone="aside", public=True)
        return
    E.push_choose_cards(game, pid, "Lookout", "discard",
                        cards=rest, mn=1, mx=1, purpose="discard",
                        data={"rest": rest})


def _lookout_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"], zone="aside", public=True)
    rest = list(frame["data"]["rest"])
    rest.remove(choice["cards"][0])
    E.deck_from_aside(game, pid, rest)


# --- Merchant Ship -----------------------------------------------------------

def _merchant_ship(game, pid):
    E.add_coins(game, 2)
    E.add_duration_fx(game, pid, "Merchant Ship", "turn_start")


def _merchant_ship_turn_start(game, pid, frame, choice):
    E.add_coins(game, 2)


# --- Salvager ----------------------------------------------------------------

def _salvager(game, pid):
    E.add_buys(game, 1)                 # +1 Buy even with nothing to trash
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Salvager", "trash",
                            cards=list(hand), mn=1, mx=1, purpose="trash")


def _salvager_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    E.trash(game, pid, [card])
    # Cost read AT TRASH TIME — Bridge reductions apply (engine.cost, never
    # the printed cost).
    E.add_coins(game, E.cost(game, card))


# --- Sea Chart ---------------------------------------------------------------

def _sea_chart(game, pid):
    E.draw(game, pid, 1)                # draw first, THEN reveal the new top
    E.add_actions(game, 1)
    looked = E.look_top(game, pid, 1)
    if not looked:
        return
    card = looked[0]
    E.reveal(game, pid, [card], "deck")
    # "In play" includes the played Sea Chart itself and persisting durations.
    if E.duration_in_play(game, pid, card):
        E.take_aside(game, pid, [card], dest="hand")
    else:
        E.deck_from_aside(game, pid, [card])


# --- Sea Witch ---------------------------------------------------------------
# The Curses are play-time only; the duration half is the delayed sifter.

def _sea_witch(game, pid):
    E.draw(game, pid, 2)
    E.attack_opponents(game, pid, "Sea Witch", "curse")
    E.add_duration_fx(game, pid, "Sea Witch", "turn_start")


def _sea_witch_curse(game, pid, frame, choice):
    E.gain(game, pid, "Curse")


def _sea_witch_turn_start(game, pid, frame, choice):
    E.draw(game, pid, 2)                # draw first; discards may be any cards
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Sea Witch", "discard",
                            cards=list(hand), mn=2, mx=2, purpose="discard")


# --- Tide Pools --------------------------------------------------------------

def _tide_pools(game, pid):
    E.draw(game, pid, 3)
    E.add_actions(game, 1)
    E.add_duration_fx(game, pid, "Tide Pools", "turn_start")


def _tide_pools_turn_start(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Tide Pools", "discard",
                            cards=list(hand), mn=2, mx=2, purpose="discard")


# --- Warehouse ---------------------------------------------------------------

def _warehouse(game, pid):
    E.draw(game, pid, 3)
    E.add_actions(game, 1)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Warehouse", "discard",
                            cards=list(hand), mn=3, mx=3, purpose="discard")


# --- Wharf -------------------------------------------------------------------

def _wharf(game, pid):
    E.draw(game, pid, 2)
    E.add_buys(game, 1)
    E.add_duration_fx(game, pid, "Wharf", "turn_start")


def _wharf_turn_start(game, pid, frame, choice):
    E.draw(game, pid, 2)
    E.add_buys(game, 1)


EFFECTS = {
    "Astrolabe": _astrolabe,
    "Bazaar": _bazaar,
    "Caravan": _caravan,
    "Cutpurse": _cutpurse,
    "Fishing Village": _fishing_village,
    "Haven": _haven,
    "Lighthouse": _lighthouse,
    "Lookout": _lookout,
    "Merchant Ship": _merchant_ship,
    "Salvager": _salvager,
    "Sea Chart": _sea_chart,
    "Sea Witch": _sea_witch,
    "Tide Pools": _tide_pools,
    "Warehouse": _warehouse,
    "Wharf": _wharf,
}

STAGES = {
    ("Astrolabe", "turn_start"): _astrolabe_turn_start,
    ("Caravan", "turn_start"): _caravan_turn_start,
    ("Cutpurse", "hit"): _cutpurse_hit,
    ("Fishing Village", "turn_start"): _fishing_village_turn_start,
    ("Haven", "aside"): _haven_aside,
    ("Haven", "turn_start"): _haven_turn_start,
    ("Lighthouse", "turn_start"): _lighthouse_turn_start,
    ("Lookout", "trash"): _lookout_trash,
    ("Lookout", "discard"): _lookout_discard,
    ("Merchant Ship", "turn_start"): _merchant_ship_turn_start,
    ("Salvager", "trash"): _salvager_trash,
    ("Sea Witch", "curse"): _sea_witch_curse,
    ("Sea Witch", "turn_start"): _sea_witch_turn_start,
    ("Sea Witch", "discard"): _discard_picked,
    ("Tide Pools", "turn_start"): _tide_pools_turn_start,
    ("Tide Pools", "discard"): _discard_picked,
    ("Warehouse", "discard"): _discard_picked,
    ("Wharf", "turn_start"): _wharf_turn_start,
}
