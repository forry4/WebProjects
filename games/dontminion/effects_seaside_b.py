"""Seaside card effects, batch B (the complex half).

Owns: Blockade, Corsair, Island, Monkey, Native Village, Outpost, Pirate,
Sailor, Smugglers, Tactician, Treasure Map, Treasury.

Design notes:
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
"""

from . import engine as E
from .cards import CARDS


# --- Blockade --------------------------------------------------------------------

def _blockade(game, pid):
    piles = [p for p in sorted(game["supply"])
             if game["supply"][p] > 0 and E.cost(game, p) <= 4]
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
             if game["supply"][p] > 0 and "treasure" in E.CARDS[p]["types"]
             and E.cost(game, p) <= 6]          # cost checked at fx time
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
    names = sorted({c for c in gained if E.cost(game, c) <= 6})
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


EFFECTS = {
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

# Trigger-bus registrations (see engine.py "THE TRIGGER BUS"):
# - Pirate: when any player gains a Treasure, each holder may play it from hand.
# - Treasury: at the end of the Buy phase, may topdeck played Treasuries if no
#   Victory card was gained in it (the kernel sets gained_victory_in_buy in gain()).
TRIGGERS = {
    "Pirate": [{"on": "gain", "from": "hand", "stage": "gain_react",
                "when": lambda game, pid, ctx: "treasure" in CARDS[ctx["subject"]]["types"]}],
    "Treasury": [{"on": "buy_phase_end", "from": "in_play",
                  "when": lambda game, pid, ctx: not game["turn_ctx"].get("gained_victory_in_buy"),
                  "push": _treasury_prompt}],
}
