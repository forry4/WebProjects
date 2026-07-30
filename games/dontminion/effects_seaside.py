"""Seaside 2E card effects — all 27 kingdom cards.

Astrolabe, Bazaar, Blockade, Caravan, Corsair, Cutpurse, Fishing Village,
Haven, Island, Lighthouse, Lookout, Merchant Ship, Monkey, Native Village,
Outpost, Pirate, Sailor, Salvager, Sea Chart, Sea Witch, Smugglers, Tactician,
Tide Pools, Treasure Map, Treasury, Warehouse, Wharf.

Kernel notes: add_duration_fx registers a start-of-NEXT-turn ability on the
card currently being played; an effect that registers nothing "failed to set
up" and the kernel discards the card normally this turn.

Design notes (complex half):
  Blockade — the gained card goes STRAIGHT to the duration set-aside
    (gain dest="dur_aside"); the curse trigger is a "gain" watcher that lives
    until the owner's next turn start — exactly when the set-aside card
    returns to hand, so the ongoing ability ends on time. The curse only
    lands when the gainer takes a copy on THEIR OWN turn, and it chains when
    the blockaded pile is Curse itself (the watcher fires again on the Curse
    it just handed out — correct per the compendium; gain() returning False
    on the empty pile terminates the chain). The play's immunity set (Moat
    reveals / Lighthouse protection) is threaded through the pick frame into
    the watcher, so immune players never receive the delayed curses.
  Corsair — an after-play "play_treasure" watcher; a trashed Silver/Gold
    already produced its $ (the kernel fires watchers after the play
    resolves). First-Silver/Gold-per-player-per-turn bookkeeping lives in the
    watcher's LIVE data (watcher_data); the marker is recorded for the first
    Silver/Gold OBSERVED each turn whether or not the trash lands, and the
    in_play membership guard makes multiple Corsairs non-cumulative (a prior
    copy already trashed it).
  Island / Native Village — the scoring mats. Island moves itself only if
    still in play (a Throne Room replay finds it already on the mat and sets
    aside a hand card only, per the ruling). Native Village's option is
    chosen BEFORE seeing anything: look_top runs inside the option stage.
  Outpost — request_extra_turn + a no-op next-turn fx: the kernel applies
    the 3-card draw and the no-3rd-turn gate; the no-op fx keeps Outpost on
    the table through the next turn per the duration lifecycle.
  Pirate — the below-the-line Reaction is a TRIGGERS from-hand registration
    (the bus opens the play/decline window per holder); the stage plays Pirate
    with count=False (an off-turn play must not count toward the turn
    player's actions_played) and re-offers while more Pirates remain in hand
    (several may react to the same gain).
  Sailor — a this-turn ("turn_end") gain watcher + an UNCONDITIONAL
    next-turn fx (Sailor always persists). The once-per-turn "used" flag
    lives in the live watcher data; declining does not consume it. (With two
    Sailors out, watcher_data resolves to the first copy's dict, so the flag
    is shared — a second gained Duration can't be played. Accepted edge.)
  Treasury — the CURRENT (2022) end-of-Buy-phase version via a TRIGGERS
    "buy_phase_end"/"in_play" registration, NOT the pre-2022 on-discard
    trigger; gated on turn_ctx["gained_victory_in_buy"] (gains, not buys, and
    only in the Buy phase — the kernel sets the flag inside gain()).

The EFFECTS/STAGES contract lives in games/dontminion/CLAUDE.md (the frozen
engine API); card code touches the game ONLY through the engine helpers.
"""

from . import engine as E
from .cards import CARDS


# ==========================================================================
# seaside_a batch
# ==========================================================================

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

# ==========================================================================
# seaside_b batch
# ==========================================================================

# --- Blockade --------------------------------------------------------------------

def _blockade(game, pid):
    piles = [p for p in sorted(game["supply"])
             if game["supply"][p] > 0 and E.cost_le(game, p, 4)]
    if piles:                                  # no eligible pile: failed to set up
        # the attack part registers in a LATER stage — capture this play's
        # immunity set now (the documented immune= threading pattern)
        E.push_choose_pile(game, pid, "Blockade", "pick", piles=piles,
                           data={"immune": list(game.get("_atk_immune", []))})


def _blockade_pick(game, pid, frame, choice):
    pile = choice["pile"]
    E.gain(game, pid, pile, dest="dur_aside")  # gained directly to the set-aside
    E.add_duration_fx(game, pid, "Blockade", "turn_start", data={"card": pile})
    E.add_watcher(game, pid, "Blockade", "gain", stage="curse_check",
                  data={"card": pile}, immune=frame["data"]["immune"])


def _blockade_turn_start(game, pid, frame, choice):
    card = frame["data"]["card"]
    if card in game["seats"][pid].get("dur_aside", []):
        E.take_dur_aside(game, pid, [card], dest="hand")


def _blockade_curse_check(game, pid, frame, choice):
    d = frame["data"]
    if d["actor"] == d["owner"] or d["subject"] != d["card"]:
        return
    if d["actor"] != game["turn"]:             # only gains on their OWN turn
        return
    E.gain(game, d["actor"], "Curse")          # chains if the blockaded card IS Curse


# --- Corsair ---------------------------------------------------------------------

def _corsair(game, pid):
    E.add_coins(game, 2)
    E.add_duration_fx(game, pid, "Corsair", "turn_start")
    E.add_watcher(game, pid, "Corsair", "play_treasure", stage="hit",
                  data={"hit": {}})


def _corsair_turn_start(game, pid, frame, choice):
    E.draw(game, pid, 1)


def _corsair_hit(game, pid, frame, choice):
    d = frame["data"]
    actor, subject = d["actor"], d["subject"]
    if actor == d["owner"] or subject not in ("Silver", "Gold"):
        return
    live = E.watcher_data(game, d["owner"], "Corsair")
    if live is None:
        return
    hits = live.setdefault("hit", {})
    if hits.get(actor) == game["turn_number"]:
        return                                 # not their first Silver/Gold this turn
    # This play IS their first this turn — mark it whether or not the trash
    # lands, so a later Silver/Gold this turn is safe ("the first ... each turn").
    hits[actor] = game["turn_number"]
    if subject in game["seats"][actor]["in_play"]:
        E.trash(game, actor, [subject], zone="in_play")


# --- Island ----------------------------------------------------------------------

def _island(game, pid):
    seat = game["seats"][pid]
    if seat["hand"]:
        E.push_choose_cards(game, pid, "Island", "set_aside",
                            cards=list(seat["hand"]), mn=1, mx=1,
                            purpose="set aside")
    elif "Island" in seat["in_play"]:
        E.to_island(game, pid, ["Island"], zone="in_play")


def _island_set_aside(game, pid, frame, choice):
    E.to_island(game, pid, choice["cards"], zone="hand")
    # Throne Room replay: the Island is already on the mat — the membership
    # guard makes the second play set aside a hand card only (the ruling).
    if "Island" in game["seats"][pid]["in_play"]:
        E.to_island(game, pid, ["Island"], zone="in_play")


# --- Monkey ----------------------------------------------------------------------

def _monkey(game, pid):
    E.add_duration_fx(game, pid, "Monkey", "turn_start")
    E.add_watcher(game, pid, "Monkey", "gain", stage="peek")


def _monkey_turn_start(game, pid, frame, choice):
    E.draw(game, pid, 1)


def _monkey_peek(game, pid, frame, choice):
    d = frame["data"]
    order = game["players"]
    right = order[order.index(d["owner"]) - 1]  # the seat BEFORE the owner (wraps)
    if d["actor"] == right:                     # whoever's turn it is
        E.draw(game, d["owner"], 1)


# --- Native Village --------------------------------------------------------------

def _native_village(game, pid):
    E.add_actions(game, 2)
    # The option is picked BEFORE seeing anything ("you are not allowed to
    # look at the top card of your deck before choosing").
    E.push_choose_option(game, pid, "Native Village", "pick",
                         options=[{"id": "mat",
                                   "label": "Put the top card of your deck onto your mat"},
                                  {"id": "take",
                                   "label": "Put all the cards from your mat into your hand"}],
                         pick=1)


def _native_village_pick(game, pid, frame, choice):
    if choice["ids"][0] == "mat":
        moved = E.look_top(game, pid, 1)       # empty deck+discard: nothing
        if moved:
            E.to_village_mat(game, pid, moved, zone="aside")
    else:
        E.take_village_mat(game, pid)


# --- Outpost ---------------------------------------------------------------------

def _outpost(game, pid):
    # The kernel does the work at _end_turn: the 3-card clean-up draw ALWAYS
    # applies once played; the extra turn only if the previous turn wasn't
    # also pid's (no 3rd turn in a row).
    E.request_extra_turn(game, pid)
    # No-op next-turn fx: keeps Outpost on the table through the next turn
    # (the duration lifecycle), discarded at that turn's clean-up.
    E.add_duration_fx(game, pid, "Outpost", "turn_start")


def _outpost_turn_start(game, pid, frame, choice):
    pass


# --- Pirate ----------------------------------------------------------------------

def _pirate(game, pid):
    # The play ability does nothing this turn — it only sets up the gain.
    E.add_duration_fx(game, pid, "Pirate", "turn_start")


def _pirate_turn_start(game, pid, frame, choice):
    piles = [p for p in sorted(game["supply"])
             if game["supply"][p] > 0 and E.has_type(game, p, "treasure")
             and E.cost_le(game, p, 6)]       # cost checked at fx time
    if piles:
        E.push_choose_pile(game, pid, "Pirate", "gain_pick", piles=piles)


def _pirate_gain_pick(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"], dest="hand")


def _pirate_gain_react(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if "Pirate" not in game["seats"][pid]["hand"]:
        return                                 # an earlier window already played it
    # a reaction play on YOUR OWN turn is still an Action you played this turn
    # (Conspirator counts it); off-turn plays must not touch the counter
    E.play_action_card(game, pid, "Pirate", from_zone="hand",
                       count=(pid == game["turn"]))
    if "Pirate" in game["seats"][pid]["hand"]:  # several may react to one gain
        E.push_choose_option(game, pid, "Pirate", "gain_react",
                             options=[{"id": "play",
                                       "label": "Play Pirate from your hand"},
                                      {"id": "decline", "label": "Don't react"}],
                             pick=1, data=dict(frame["data"]))


# --- Sailor ----------------------------------------------------------------------

def _sailor(game, pid):
    E.add_actions(game, 1)
    E.add_watcher(game, pid, "Sailor", "gain", stage="gained_dur",
                  until="turn_end", data={"used": False})
    # The next-turn ability is UNCONDITIONAL — Sailor always persists.
    E.add_duration_fx(game, pid, "Sailor", "turn_start")


def _sailor_zone(game, pid, card):
    """Where the gain put the card, if we can still play it from there.
    dur_aside (a Blockade set-aside) is deliberately NOT playable — don't
    even prompt for it (a wasted prompt would burn nothing, but it's noise)."""
    for zone in ("discard", "hand"):
        if card in game["seats"][pid][zone]:
            return zone
    return None


def _sailor_gained_dur(game, pid, frame, choice):
    d = frame["data"]
    if d["actor"] != d["owner"] or d["owner"] != game["turn"]:
        return
    if "duration" not in E.CARDS[d["subject"]]["types"]:
        return
    # per-INSTANCE once-per-turn: each played Sailor grants its own play
    if not any(not x.get("used") for x in E.watcher_datas(game, d["owner"], "Sailor")):
        return
    if _sailor_zone(game, pid, d["subject"]) is None:
        return                                 # can't be played from where it went
    E.push_choose_option(game, pid, "Sailor", "play_gained",
                         options=[{"id": "play",
                                   "label": f"Play the gained {d['subject']}"},
                                  {"id": "decline", "label": "Don't play it"}],
                         pick=1, data={"card": d["subject"]})


def _sailor_play_gained(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return                                 # declining does not consume the once
    card = frame["data"]["card"]
    zone = _sailor_zone(game, pid, card)
    if zone is None:
        return                                 # moved since the prompt: lose track
    # burn ONE Sailor's flag, only now that the play actually happens
    for live in E.watcher_datas(game, pid, "Sailor"):
        if not live.get("used"):
            live["used"] = True
            break
    E.play_action_card(game, pid, card, from_zone=zone)


def _sailor_turn_start(game, pid, frame, choice):
    E.add_coins(game, 2)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Sailor", "trash",
                            cards=list(hand), mn=0, mx=1, purpose="trash")


def _sailor_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, choice["cards"])


# --- Smugglers -------------------------------------------------------------------

def _smugglers(game, pid):
    order = game["players"]
    right = order[order.index(pid) - 1]        # the seat BEFORE pid (wraps)
    gained = game.get("last_turn_gains", {}).get(right, [])
    # Cost is checked NOW; empty-supply names stay eligible (you may choose an
    # unavailable one and gain nothing — the ruling).
    names = sorted({c for c in gained if E.cost_le(game, c, 6)})
    if names:
        E.push_choose_pile(game, pid, "Smugglers", "pick", piles=names)


def _smugglers_pick(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])          # empty pile: gains nothing


# --- Tactician -------------------------------------------------------------------

def _tactician(game, pid):
    hand = list(game["seats"][pid]["hand"])
    if not hand:
        return                                 # the canonical failed setup
    E.discard(game, pid, hand)                 # one bulk discard
    E.add_duration_fx(game, pid, "Tactician", "turn_start")
    # Throne Room + Tactician: the replay finds an empty hand and registers
    # nothing extra — the not-doubled ruling comes free.


def _tactician_turn_start(game, pid, frame, choice):
    E.draw(game, pid, 5)
    E.add_actions(game, 1)
    E.add_buys(game, 1)


# --- Treasure Map ----------------------------------------------------------------

def _treasure_map(game, pid):
    seat = game["seats"][pid]
    trashed_played = "Treasure Map" in seat["in_play"]
    if trashed_played:
        E.trash(game, pid, ["Treasure Map"], zone="in_play")
    trashed_hand = "Treasure Map" in seat["hand"]
    if trashed_hand:                           # mandatory, no choice
        E.trash(game, pid, ["Treasure Map"])
    # "Those two Treasure Maps": BOTH trashes must have happened. A Throne
    # Room replay finds the played copy gone -> no Golds a second time.
    if trashed_played and trashed_hand:
        for _ in range(4):                     # fewer if the pile empties
            E.gain(game, pid, "Gold", dest="deck")


# --- Treasury --------------------------------------------------------------------

def _treasury(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_coins(game, 1)


def _treasury_prompt(game, pid):
    tr = [c for c in game["seats"][pid]["in_play"] if c == "Treasury"]
    E.push_choose_cards(game, pid, "Treasury", "topdeck",
                        cards=tr, mn=0, mx=len(tr), purpose="topdeck")


def _treasury_topdeck(game, pid, frame, choice):
    for c in choice["cards"]:                  # each copy decides independently
        E.topdeck(game, pid, c, zone="in_play", public=True)


# --- registration ---------------------------------------------------------

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
    "Blockade": _blockade,
    "Corsair": _corsair,
    "Island": _island,
    "Monkey": _monkey,
    "Native Village": _native_village,
    "Outpost": _outpost,
    "Pirate": _pirate,
    "Sailor": _sailor,
    "Smugglers": _smugglers,
    "Tactician": _tactician,
    "Treasure Map": _treasure_map,
    "Treasury": _treasury,
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
    ("Blockade", "pick"): _blockade_pick,
    ("Blockade", "turn_start"): _blockade_turn_start,
    ("Blockade", "curse_check"): _blockade_curse_check,
    ("Corsair", "turn_start"): _corsair_turn_start,
    ("Corsair", "hit"): _corsair_hit,
    ("Island", "set_aside"): _island_set_aside,
    ("Monkey", "turn_start"): _monkey_turn_start,
    ("Monkey", "peek"): _monkey_peek,
    ("Native Village", "pick"): _native_village_pick,
    ("Outpost", "turn_start"): _outpost_turn_start,
    ("Pirate", "turn_start"): _pirate_turn_start,
    ("Pirate", "gain_pick"): _pirate_gain_pick,
    ("Pirate", "gain_react"): _pirate_gain_react,
    ("Sailor", "gained_dur"): _sailor_gained_dur,
    ("Sailor", "play_gained"): _sailor_play_gained,
    ("Sailor", "turn_start"): _sailor_turn_start,
    ("Sailor", "trash"): _sailor_trash,
    ("Smugglers", "pick"): _smugglers_pick,
    ("Tactician", "turn_start"): _tactician_turn_start,
    ("Treasury", "topdeck"): _treasury_topdeck,
}

TRIGGERS = {
    "Pirate": [{"on": "gain", "from": "hand", "stage": "gain_react",
                "when": lambda game, pid, ctx: "treasure" in CARDS[ctx["subject"]]["types"]}],
    "Treasury": [{"on": "buy_phase_end", "from": "in_play",
                  "when": lambda game, pid, ctx: not game["turn_ctx"].get("gained_victory_in_buy"),
                  "push": _treasury_prompt}],
}
