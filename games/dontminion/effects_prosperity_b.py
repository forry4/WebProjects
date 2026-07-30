"""Prosperity-2E card effects, batch B (WP-prosperity-b — the complex half).

Owns: Charlatan, Clerk, Collection, Crystal Ball, Hoard, Investment,
King's Court, Magnate, Mint, Peddler, Tiara, Watchtower.

See effects_core.py for the EFFECTS/STAGES contract. Design notes:
  * Charlatan's below-line rule ("Curse is also a Treasure worth $1") is
    KERNEL-side: new_game sets game["curse_is_treasure"] from the kingdom and
    types_of/has_type/coins_of honor it everywhere — this module ships only
    the attack half (Witch-shaped). Card code never reads CARDS[x]["types"].
  * Collection / Hoard / Tiara are the 2022 "this turn, when you gain ..."
    treasures: a per-play add_watcher(until="turn_end") on "gain", so the
    ability is cumulative per play and survives the card leaving play (the
    canonical fixture: gaining a Mint trashes them from play mid-turn).
  * Clerk's below-line reaction and Watchtower's are TRIGGERS registrations
    ("turn_start"/"gain" from hand); Mint's on-gain mass trash is a "self"
    trigger (fires on ANY gain of a Mint, not just buys).
  * King's Court is Throne Room's exact shape with TWO parked replays (LIFO:
    each full resolution before the next); Tiara is the treasure-throne
    (play_action_card plays treasures too, banking printed $). Both mark
    themselves as duration RIDERS when they directly played a Duration.
  * Crystal Ball / Investment / Tiara make decisions on play — exported in
    MANUAL_TREASURES so play_all_treasures skips them.
  * Peddler's dynamic self-cost is the DYN_COSTS seam: -$2 per Action the
    ACTIVE player has on the table, buy phase only, cost() floors at 0.
"""

from . import engine as E


def _this_turn_gain_watcher(game, pid, card, stage):
    """add_watcher(until="turn_end") for the 2022 "this turn, when you gain"
    treasures. The kernel counts only CROSS-TURN watchers toward duration
    persistence, so the card discards at its own clean-up (and may be trashed
    from play mid-turn) while the live watcher keeps firing until turn end."""
    E.add_watcher(game, pid, card, "gain", stage=stage, until="turn_end")


# --- Charlatan ---------------------------------------------------------------
# +$3 (even with no Curses left); each other player gains a Curse. The
# game-wide Curse-is-a-Treasure rule is applied by the kernel from the kingdom.

def _charlatan(game, pid):
    E.add_coins(game, 3)
    E.attack_opponents(game, pid, "Charlatan", "curse")


def _charlatan_curse(game, pid, frame, choice):
    E.gain(game, pid, "Curse")


# --- Clerk -------------------------------------------------------------------
# +$2; each other player with 5+ cards in hand topdecks one of their choice.
# Below the line: at the start of your turn you may play it from hand (a real
# play — no Action from the pool is spent; play_action_card never touches
# game["actions"]), repeatable per copy (the Pirate re-offer pattern).

def _clerk(game, pid):
    E.add_coins(game, 2)
    E.attack_opponents(game, pid, "Clerk", "hit")


def _clerk_hit(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    if len(hand) >= 5:
        E.push_choose_cards(game, pid, "Clerk", "topdeck",
                            cards=list(hand), mn=1, mx=1,
                            purpose="put onto your deck")


def _clerk_topdeck(game, pid, frame, choice):
    # AUDIT FIX: no "reveal" on Clerk's text — the victim's pick is hidden
    # information (unlike Bureaucrat's revealed Victory card). public=False
    # logs "puts a card onto their deck" without naming it.
    E.topdeck(game, pid, choice["cards"][0], public=False)


def _clerk_start_react(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if "Clerk" not in game["seats"][pid]["hand"]:
        return                                 # moved since the window opened
    E.play_action_card(game, pid, "Clerk", from_zone="hand")
    if "Clerk" in game["seats"][pid]["hand"]:  # several may play, one at a time
        E.push_choose_option(game, pid, "Clerk", "start_react",
                             options=[{"id": "play",
                                       "label": "Play Clerk from your hand"},
                                      {"id": "decline", "label": "Don't react"}],
                             pick=1, data=dict(frame["data"]))


# --- Collection (Treasure $2) ------------------------------------------------
# Printed $2 banked by the kernel; +1 Buy; this turn, +1 VP per Action card
# YOU gain — cumulative per play, survives Collection leaving play (watcher,
# not position).

def _collection(game, pid):
    E.add_buys(game, 1)
    _this_turn_gain_watcher(game, pid, "Collection", "vp_check")


def _collection_vp_check(game, pid, frame, choice):
    d = frame["data"]
    if d["actor"] == d["owner"] == game["turn"] \
            and E.has_type(game, d["subject"], "action"):
        E.add_vp_tokens(game, d["owner"], 1)


# --- Crystal Ball (Treasure $1, manual) --------------------------------------
# Look at the top card; trash it, discard it, play it (Action or Treasure —
# a Buy-phase Action play is legal via this route, per the ruling), or put it
# back. The looked-at card waits in the aside zone.

def _crystal_ball(game, pid):
    moved = E.look_top(game, pid, 1)
    if not moved:
        return                                 # deck + discard empty
    card = moved[0]
    opts = [{"id": "trash", "label": f"Trash {card}"},
            {"id": "discard", "label": f"Discard {card}"}]
    if E.has_type(game, card, "action") or E.has_type(game, card, "treasure"):
        opts.append({"id": "play", "label": f"Play {card}"})
    opts.append({"id": "back", "label": "Put it back"})
    E.push_choose_option(game, pid, "Crystal Ball", "decide",
                         options=opts, pick=1, data={"card": card})


def _crystal_ball_decide(game, pid, frame, choice):
    card = frame["data"]["card"]
    cid = choice["ids"][0]
    if cid == "trash":
        E.trash(game, pid, [card], zone="aside")
    elif cid == "discard":
        E.discard(game, pid, [card], zone="aside", public=True)
    elif cid == "play":
        # a real play from the deck top (via aside) — no Action from the pool
        E.play_action_card(game, pid, card, from_zone="aside")
    else:
        E.deck_from_aside(game, pid, [card])   # leave it: back on top


# --- Hoard (Treasure $2) -----------------------------------------------------
# Printed $2 banked by the kernel. This turn, when you gain a Victory card,
# IF YOU BOUGHT IT, gain a Gold — via_buy rides the gain event; a gained-not-
# bought Victory card gives nothing. Cumulative per play.

def _hoard(game, pid):
    _this_turn_gain_watcher(game, pid, "Hoard", "gold_check")


def _hoard_gold_check(game, pid, frame, choice):
    d = frame["data"]
    if d["actor"] != d["owner"] or not d.get("via_buy"):
        return
    if E.has_type(game, d["subject"], "victory"):
        E.gain(game, d["owner"], "Gold")       # its own when-gain window applies


# --- Investment (Treasure $0, manual) ----------------------------------------
# Mandatory trash-1-from-hand first (skipped only on an empty hand — you
# still choose a mode); then +$1 OR trash Investment from play to reveal your
# hand for +1 VP per differently named Treasure there. The in_play membership
# guard makes a Tiara replay pay the VP at most once (the Crown ruling).

def _investment(game, pid):
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Investment", "trash",
                            cards=list(hand), mn=1, mx=1, purpose="trash")
    else:
        _investment_mode_prompt(game, pid)


def _investment_trash(game, pid, frame, choice):
    E.trash(game, pid, choice["cards"])
    _investment_mode_prompt(game, pid)


def _investment_mode_prompt(game, pid):
    E.push_choose_option(game, pid, "Investment", "mode",
                         options=[{"id": "coin", "label": "+$1"},
                                  {"id": "vp",
                                   "label": "Trash Investment: +1 VP per "
                                            "differently named Treasure in hand"}],
                         pick=1)


def _investment_mode(game, pid, frame, choice):
    if choice["ids"][0] == "coin":
        E.add_coins(game, 1)
        return
    seat = game["seats"][pid]
    if "Investment" not in seat["in_play"]:
        return          # already trashed (a Tiara replay): no second VP payout
    E.trash(game, pid, ["Investment"], zone="in_play")
    hand = list(seat["hand"])
    if hand:
        E.reveal(game, pid, hand, "hand")
    # differently NAMED treasure-typed cards (a Charlatan-game Curse counts)
    names = {c for c in hand if E.has_type(game, c, "treasure")}
    E.add_vp_tokens(game, pid, len(names))


# --- King's Court ------------------------------------------------------------
# Throne Room's exact structure with THREE plays: once from hand + two parked
# replays (LIFO — each full resolution before the next). The rider marking
# runs on the LAST replay, mirroring Throne Room's "second" stage.

def _kings_court(game, pid):
    hand = game["seats"][pid]["hand"]
    actions = sorted({c for c in hand if E.has_type(game, c, "action")})
    if not actions:
        return
    E.push_choose_cards(game, pid, "King's Court", "pick",
                        cards=actions, mn=0, mx=1, purpose="play three times")


def _kings_court_pick(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    # LIFO: the deepest frame resolves last — it carries the rider marking.
    E.push_auto(game, pid, "King's Court", "replay", data={"card": card, "last": True})
    E.push_auto(game, pid, "King's Court", "replay", data={"card": card, "last": False})
    E.play_action_card(game, pid, card, from_zone="hand")


def _kings_court_replay(game, pid, frame, choice):
    card = frame["data"]["card"]
    E.play_action_card(game, pid, card, from_zone=None)
    # Duration rule: the King's Court that directly played a persisting
    # Duration stays on the table with it (discarded together).
    if frame["data"]["last"] and E.has_type(game, card, "duration"):
        E.mark_duration_rider(game, pid, card, "King's Court")


# --- Magnate -----------------------------------------------------------------
# Reveal your hand; +1 Card per Treasure in it, counted AT REVEAL TIME
# (drawn cards never re-count). A Charlatan-game Curse in hand counts.

def _magnate(game, pid):
    hand = list(game["seats"][pid]["hand"])
    if not hand:
        return                                 # reveal nothing, draw 0
    E.reveal(game, pid, hand, "hand")
    E.draw(game, pid, sum(1 for c in hand if E.has_type(game, c, "treasure")))


# --- Mint --------------------------------------------------------------------
# On-play: may reveal a Treasure from hand, gain a copy (empty pile: nothing).
# Below the line (2022): when you GAIN this — any gain, not just buys — trash
# ALL non-Duration Treasures you have in play, at once. Quarry's turn-scoped
# discount survives its own trashing (turn_ctx counter, kernel-side).

def _mint(game, pid):
    hand = game["seats"][pid]["hand"]
    treasures = sorted({c for c in hand if E.has_type(game, c, "treasure")})
    if treasures:
        E.push_choose_cards(game, pid, "Mint", "reveal_pick",
                            cards=treasures, mn=0, mx=1, purpose="reveal")


def _mint_reveal_pick(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    E.reveal(game, pid, [card], "hand")
    E.gain(game, pid, card)                    # a copy from the supply


def _mint_on_gain(game, pid, frame, choice):
    # "self" trigger: pid IS the gainer. One trash event for all of them.
    seat = game["seats"][pid]
    hits = [c for c in seat["in_play"]
            if E.has_type(game, c, "treasure")
            and not E.has_type(game, c, "duration")]
    if hits:
        E.trash(game, pid, hits, zone="in_play")


# --- Peddler -----------------------------------------------------------------
# Cantrip +$1. Dynamic self-cost: during a Buy phase, $2 less per Action card
# the ACTIVE player has on the table (in play + duration zone + riders) —
# global (every copy, priced by anyone), $8 at all other times, floored at 0
# by cost().

def _peddler(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_coins(game, 1)


def _peddler_discount(game):
    if game["phase"] != "buy":
        return 0
    seat = game["seats"][game["turn"]]
    on_table = list(seat["in_play"])
    for e in seat.get("duration", []):
        on_table.append(e["card"])
        on_table.extend(e.get("riders", []))
    return 2 * sum(1 for c in on_table if E.has_type(game, c, "action"))


# --- Tiara (Treasure $0, manual) ---------------------------------------------
# +1 Buy; this turn, each card you gain MAY be put onto your deck (per-gain
# choice, cumulative prompts per play, lose-track guarded); then you may play
# a Treasure from your hand twice (the treasure-throne — stays out with a
# throned Duration Treasure, Astrolabe).

def _tiara(game, pid):
    E.add_buys(game, 1)
    # the rider first, so gains from the throned Treasure are already covered
    _this_turn_gain_watcher(game, pid, "Tiara", "gain_check")
    treasures = sorted({c for c in game["seats"][pid]["hand"]
                        if E.has_type(game, c, "treasure")})
    if treasures:
        E.push_choose_cards(game, pid, "Tiara", "throne_pick",
                            cards=treasures, mn=0, mx=1, purpose="play twice")


def _tiara_gain_check(game, pid, frame, choice):
    d = frame["data"]
    if d["actor"] != d["owner"] or d["owner"] != game["turn"]:
        return
    E.push_choose_option(game, d["owner"], "Tiara", "topdeck",
                         options=[{"id": "topdeck",
                                   "label": f"Put the gained {d['subject']} onto your deck"},
                                  {"id": "keep", "label": "Leave it"}],
                         pick=1,
                         data={"card": d["subject"], "dest": d.get("dest", "discard")})


def _tiara_topdeck(game, pid, frame, choice):
    if choice["ids"][0] != "topdeck":
        return
    card, dest = frame["data"]["card"], frame["data"]["dest"]
    # membership-guarded lose-track: if something already moved the card
    # (Watchtower topdecked/trashed it), this quietly does nothing; a gain
    # straight to the deck is already there (no-op); other zones: skip.
    if dest in ("discard", "hand") and card in game["seats"][pid][dest]:
        E.topdeck(game, pid, card, zone=dest, public=True)


def _tiara_throne_pick(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    E.push_auto(game, pid, "Tiara", "replay", data={"card": card})
    E.play_action_card(game, pid, card, from_zone="hand")


def _tiara_replay(game, pid, frame, choice):
    card = frame["data"]["card"]
    E.play_action_card(game, pid, card, from_zone=None)
    if E.has_type(game, card, "duration"):
        E.mark_duration_rider(game, pid, card, "Tiara")


# --- Watchtower --------------------------------------------------------------
# Action: draw until 6 in hand. Reaction: on each of YOUR gains you may REVEAL
# it (it stays in hand — reusable on every separate gain) to trash the gained
# card or put it onto your deck. The gain itself already happened (when-gain
# abilities of the card still fire even if it's trashed).

def _watchtower(game, pid):
    n = 6 - len(game["seats"][pid]["hand"])
    if n > 0:
        E.draw(game, pid, n)


def _watchtower_react(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if "Watchtower" not in game["seats"][pid]["hand"]:
        return                                 # moved since the window opened
    E.reveal(game, pid, ["Watchtower"], "hand")
    card = frame["data"]["gained"]
    E.push_choose_option(game, pid, "Watchtower", "act",
                         options=[{"id": "trash", "label": f"Trash the gained {card}"},
                                  {"id": "topdeck",
                                   "label": f"Put the gained {card} onto your deck"},
                                  {"id": "keep", "label": "Do neither"}],
                         pick=1,
                         data={"card": card, "dest": frame["data"].get("dest", "discard")})


def _watchtower_act(game, pid, frame, choice):
    cid = choice["ids"][0]
    if cid == "keep":
        return
    card, dest = frame["data"]["card"], frame["data"]["dest"]
    seat = game["seats"][pid]
    if dest not in ("discard", "hand", "deck", "dur_aside") \
            or card not in seat.get(dest, []):
        return                                 # lose track: someone moved it
    if cid == "trash":
        E.trash(game, pid, [card], zone=dest)
    elif dest != "deck":                       # gained to the deck: already there
        if dest in ("discard", "hand"):
            E.topdeck(game, pid, card, zone=dest, public=True)
        # dur_aside: no topdeck path from there — treat as lost track


EFFECTS = {
    "Charlatan": _charlatan,
    "Clerk": _clerk,
    "Collection": _collection,
    "Crystal Ball": _crystal_ball,
    "Hoard": _hoard,
    "Investment": _investment,
    "King's Court": _kings_court,
    "Magnate": _magnate,
    "Mint": _mint,
    "Peddler": _peddler,
    "Tiara": _tiara,
    "Watchtower": _watchtower,
}

STAGES = {
    ("Charlatan", "curse"): _charlatan_curse,
    ("Clerk", "hit"): _clerk_hit,
    ("Clerk", "topdeck"): _clerk_topdeck,
    ("Clerk", "start_react"): _clerk_start_react,
    ("Collection", "vp_check"): _collection_vp_check,
    ("Crystal Ball", "decide"): _crystal_ball_decide,
    ("Hoard", "gold_check"): _hoard_gold_check,
    ("Investment", "trash"): _investment_trash,
    ("Investment", "mode"): _investment_mode,
    ("King's Court", "pick"): _kings_court_pick,
    ("King's Court", "replay"): _kings_court_replay,
    ("Mint", "reveal_pick"): _mint_reveal_pick,
    ("Mint", "on_gain"): _mint_on_gain,
    ("Tiara", "gain_check"): _tiara_gain_check,
    ("Tiara", "topdeck"): _tiara_topdeck,
    ("Tiara", "throne_pick"): _tiara_throne_pick,
    ("Tiara", "replay"): _tiara_replay,
    ("Watchtower", "react"): _watchtower_react,
    ("Watchtower", "act"): _watchtower_act,
}

# Trigger-bus registrations (engine.py "THE TRIGGER BUS"):
# - Clerk: at the start of your turn, a play/decline window per copy in hand.
# - Mint: when a Mint is GAINED (any gain), the gainer's played non-Duration
#   Treasures are trashed. Registered before Watchtower so Watchtower's window
#   stacks ON TOP for the same gain and resolves first — even a trashed/
#   topdecked Mint still trashes the Treasures (the gain happened).
# - Watchtower: a reveal window on each of the holder's own gains.
TRIGGERS = {
    "Clerk": [{"on": "turn_start", "from": "hand", "who": "actor",
               "stage": "start_react"}],
    "Mint": [{"on": "gain", "from": "self", "stage": "on_gain"}],
    "Watchtower": [{"on": "gain", "from": "hand", "who": "actor",
                    "mode": "reveal", "stage": "react"}],
}

DYN_COSTS = {
    "Peddler": _peddler_discount,
}

MANUAL_TREASURES = {"Crystal Ball", "Investment", "Tiara"}
