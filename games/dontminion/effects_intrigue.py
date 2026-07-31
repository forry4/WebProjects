"""Intrigue 2E card effects — all 26 kingdom cards.

Baron, Bridge, Conspirator, Courtier, Courtyard, Diplomat (action side — its
Reaction lives in the engine's __attack window), Ironworks, Lurker, Masquerade,
Mill, Mining Village, Minion, Nobles, Patrol, Pawn, Replace, Secret Passage,
Shanty Town, Steward, Swindler, Torturer, Trading Post, Upgrade, Wishing Well.
(Duke and Farm are data-only.)

  Pawn/Courtier-style picks — "The choices must be different" (pick distinct).
  Mill / Baron / Mining Village — "do X, for +$" contingency: the bonus is paid
    only when the FULL first effect happened (Mill: exactly 2 discarded).
  Options are never feasibility-filtered (Mill's discard offer stands with a
    short hand; taking it then discards as much as possible, unpaid).
  Conspirator — actions_played is read at ITS resolution and includes itself
    (play_action_card increments before the effect runs); throne-room replays
    each count.
  Mining Village — the trash offer exists only while the card is in YOUR
    in_play (a throne-roomed copy trashed on the first play is lost track of:
    no second offer, but the +1 Card +2 Actions still happen).
  Upgrade — the gain must cost EXACTLY $1 more (engine.cost both sides).

Design notes (complex half):
  Masquerade — NOT an attack (no windows). The pass ring (players with cards,
    turn order from the current player) is collected SEQUENTIALLY as secret
    picks buffered in the walker frame's data (frame data never reaches the
    wire), then ALL passes execute at once — observationally identical to
    simultaneity since no pick is revealed before execution. pass_card logs
    the identity privately to the giver+receiver pair.
  Minion / Replace — their attack part runs in a LATER stage (after the mode /
    gain choice), so on_play captures list(game["_atk_immune"]) into the frame
    data and hands it back via attack_opponents(..., immune=...).
  Swindler — the replacement pile is the ATTACKER's choice ("that you choose");
    the same-cost comparison uses engine.cost on both sides (Bridge-aware).
  Secret Passage — the chosen deck POSITION is open information per the
    compendium ruling (logged publicly); the card identity is not.
  Torturer — both options are always offered ("They may pick an option they
    can't do."): a short hand discards what it can, an empty Curse pile gains
    nothing.

The EFFECTS/STAGES contract lives in games/dontminion/CLAUDE.md (the frozen
engine API); card code touches the game ONLY through the engine helpers.
"""

from . import engine as E


# ==========================================================================
# intrigue_a batch
# ==========================================================================

def _gain_piles(game, pred):
    return [p for p in sorted(game["supply"]) if game["supply"][p] > 0 and pred(p)]


# --- Courtyard ------------------------------------------------------------------

def _courtyard(game, pid):
    E.draw(game, pid, 3)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Courtyard", "topdeck",
                            cards=list(hand), mn=1, mx=1, purpose="topdeck")


def _courtyard_topdeck(game, pid, frame, choice):
    E.topdeck(game, pid, choice["cards"][0])


# --- Pawn -----------------------------------------------------------------------

_PAWN_OPTS = [{"id": "card", "label": "+1 Card"},
              {"id": "action", "label": "+1 Action"},
              {"id": "buy", "label": "+1 Buy"},
              {"id": "coin", "label": "+$1"}]


def _pawn(game, pid):
    E.push_choose_option(game, pid, "Pawn", "pick", options=list(_PAWN_OPTS),
                         pick=2, distinct=True)


def _pawn_pick(game, pid, frame, choice):
    for cid in choice["ids"]:
        if cid == "card":
            E.draw(game, pid, 1)
        elif cid == "action":
            E.add_actions(game, 1)
        elif cid == "buy":
            E.add_buys(game, 1)
        elif cid == "coin":
            E.add_coins(game, 1)


# --- Shanty Town ------------------------------------------------------------------

def _shanty_town(game, pid):
    E.add_actions(game, 2)
    hand = game["seats"][pid]["hand"]
    E.reveal(game, pid, list(hand), "hand")
    if not any(E.has_type(game, c, "action") for c in hand):
        E.draw(game, pid, 2)


# --- Steward ----------------------------------------------------------------------

def _steward(game, pid):
    E.push_choose_option(game, pid, "Steward", "pick",
                         options=[{"id": "cards", "label": "+2 Cards"},
                                  {"id": "coins", "label": "+$2"},
                                  {"id": "trash", "label": "Trash 2 cards from your hand"}],
                         pick=1)


def _steward_pick(game, pid, frame, choice):
    cid = choice["ids"][0]
    if cid == "cards":
        E.draw(game, pid, 2)
    elif cid == "coins":
        E.add_coins(game, 2)
    else:
        hand = game["seats"][pid]["hand"]
        if hand:
            E.push_choose_cards(game, pid, "Steward", "trash",
                                cards=list(hand), mn=2, mx=2, purpose="trash")


def _steward_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, choice["cards"])


# --- Wishing Well -----------------------------------------------------------------

def _wishing_well(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.push_name_card(game, pid, "Wishing Well", "wish")


def _wishing_well_wish(game, pid, frame, choice):
    named = choice["card"]
    E._log(game, pid, "named", card=named)
    moved = E.look_top(game, pid, 1)
    if not moved:
        return
    c = moved[0]
    E.reveal(game, pid, [c], "deck")
    if c == named:
        E.take_aside(game, pid, [c])          # into hand
    else:
        E.deck_from_aside(game, pid, [c])     # back on top


# --- Baron ------------------------------------------------------------------------

def _baron(game, pid):
    E.add_buys(game, 1)
    if "Estate" in game["seats"][pid]["hand"]:
        E.push_choose_option(game, pid, "Baron", "pick",
                             options=[{"id": "discard", "label": "Discard an Estate, for +$4"},
                                      {"id": "gain", "label": "Gain an Estate"}],
                             pick=1)
    else:
        E.gain(game, pid, "Estate")           # nothing to discard: gain (fizzle ok)


def _baron_pick(game, pid, frame, choice):
    if choice["ids"][0] == "discard" and "Estate" in game["seats"][pid]["hand"]:
        E.discard(game, pid, ["Estate"])
        E.add_coins(game, 4)
    else:
        E.gain(game, pid, "Estate")


# --- Bridge -----------------------------------------------------------------------

def _bridge(game, pid):
    E.add_buys(game, 1)
    E.add_coins(game, 1)
    game["turn_ctx"]["bridges"] += 1          # engine.cost applies it everywhere


# --- Conspirator ------------------------------------------------------------------

def _conspirator(game, pid):
    E.add_coins(game, 2)
    if game["turn_ctx"]["actions_played"] >= 3:   # includes this play
        E.draw(game, pid, 1)
        E.add_actions(game, 1)


# --- Ironworks --------------------------------------------------------------------

def _ironworks(game, pid):
    piles = _gain_piles(game, lambda p: E.cost_le(game, p, 4))
    if piles:
        E.push_choose_pile(game, pid, "Ironworks", "gain", piles=piles)


def _ironworks_gain(game, pid, frame, choice):
    card = choice["pile"]
    if not E.gain(game, pid, card):
        return
    types = E.types_of(game, card)            # dual types grant multiple bonuses
    if "action" in types:
        E.add_actions(game, 1)
    if "treasure" in types:
        E.add_coins(game, 1)
    if "victory" in types:
        E.draw(game, pid, 1)


# --- Mill -------------------------------------------------------------------------

def _mill(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.push_choose_option(game, pid, "Mill", "pick",
                         options=[{"id": "discard", "label": "Discard 2 cards, for +$2"},
                                  {"id": "keep", "label": "Don't discard"}],
                         pick=1)


def _mill_pick(game, pid, frame, choice):
    if choice["ids"][0] != "discard":
        return
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Mill", "discard",
                            cards=list(hand), mn=2, mx=2, purpose="discard")


def _mill_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])
    if len(choice["cards"]) == 2:             # "do X, for +$2" — full effect only
        E.add_coins(game, 2)


# --- Mining Village -----------------------------------------------------------------

def _mining_village(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 2)
    if "Mining Village" in game["seats"][pid]["in_play"]:
        E.push_choose_option(game, pid, "Mining Village", "pick",
                             options=[{"id": "trash", "label": "Trash this, for +$2"},
                                      {"id": "keep", "label": "Keep it"}],
                             pick=1)


def _mining_village_pick(game, pid, frame, choice):
    if choice["ids"][0] == "trash" and "Mining Village" in game["seats"][pid]["in_play"]:
        E.trash(game, pid, ["Mining Village"], zone="in_play")
        E.add_coins(game, 2)


# --- Nobles -----------------------------------------------------------------------

def _nobles(game, pid):
    E.push_choose_option(game, pid, "Nobles", "pick",
                         options=[{"id": "cards", "label": "+3 Cards"},
                                  {"id": "actions", "label": "+2 Actions"}],
                         pick=1)


def _nobles_pick(game, pid, frame, choice):
    if choice["ids"][0] == "cards":
        E.draw(game, pid, 3)
    else:
        E.add_actions(game, 2)


# --- Upgrade ----------------------------------------------------------------------

def _upgrade(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Upgrade", "trash",
                            cards=list(hand), mn=1, mx=1, purpose="trash")


def _upgrade_trash(game, pid, frame, choice):
    trashed = choice["cards"][0]
    target = E.cost(game, trashed) + 1        # EXACTLY $1 more (Bridge-aware)
    E.trash(game, pid, [trashed])
    piles = _gain_piles(game, lambda p: E.cost_eq(game, p, target))
    if piles:
        E.push_choose_pile(game, pid, "Upgrade", "gain", piles=piles)


def _upgrade_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Trading Post -------------------------------------------------------------------

def _trading_post(game, pid):
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Trading Post", "trash",
                            cards=list(hand), mn=2, mx=2, purpose="trash")


def _trading_post_trash(game, pid, frame, choice):
    E.trash(game, pid, choice["cards"])
    if len(choice["cards"]) == 2:             # "if you did" — both or no Silver
        E.gain(game, pid, "Silver", dest="hand")

# ==========================================================================
# intrigue_b batch
# ==========================================================================

# --- Lurker ---------------------------------------------------------------------

def _lurker(game, pid):
    E.add_actions(game, 1)
    E.push_choose_option(game, pid, "Lurker", "pick",
                         options=[{"id": "trash", "label": "Trash an Action card from the Supply"},
                                  {"id": "gain", "label": "Gain an Action card from the trash"}],
                         pick=1)


def _lurker_pick(game, pid, frame, choice):
    if choice["ids"][0] == "trash":
        piles = [p for p in sorted(game["supply"])
                 if game["supply"][p] > 0 and E.has_type(game, p, "action")]
        if piles:
            E.push_choose_pile(game, pid, "Lurker", "trash_pile", piles=piles)
    else:
        actions = sorted({c for c in game["trash"] if E.has_type(game, c, "action")})
        if actions:
            E.push_choose_cards(game, pid, "Lurker", "gain_trash",
                                cards=actions, mn=1, mx=1, purpose="gain")


def _lurker_trash_pile(game, pid, frame, choice):
    E.trash_from_supply(game, choice["pile"])
    E._log(game, pid, "supply_trash", card=choice["pile"])


def _lurker_gain_trash(game, pid, frame, choice):
    E.gain_from_trash(game, pid, choice["cards"][0])


# --- Masquerade -------------------------------------------------------------------

def _masquerade(game, pid):
    E.draw(game, pid, 2)
    order = [pid] + E.opponents(game, pid)
    ring = [p for p in order if game["seats"][p]["hand"]]
    if len(ring) >= 2:
        E.push_auto(game, pid, "Masquerade", "collect",
                    data={"ring": ring, "picks": {}, "owner": pid})
    else:
        _masquerade_trash_offer(game, pid)


def _masquerade_collect(game, pid, frame, choice):
    data = frame["data"]
    ring, picks = data["ring"], data["picks"]
    if len(picks) == len(ring):
        for i, giver in enumerate(ring):          # all passes execute at once
            receiver = ring[(i + 1) % len(ring)]
            E.pass_card(game, giver, receiver, picks[giver])
        _masquerade_trash_offer(game, data["owner"])
        return
    nxt = ring[len(picks)]
    hand = game["seats"][nxt]["hand"]
    E.push_choose_cards(game, nxt, "Masquerade", "pick",
                        cards=list(hand), mn=1, mx=1, purpose="pass",
                        data=dict(data))


def _masquerade_pick(game, pid, frame, choice):
    data = frame["data"]
    picks = dict(data["picks"])
    picks[pid] = choice["cards"][0]               # stays in hand until execution
    E.push_auto(game, data["owner"], "Masquerade", "collect",
                data={**data, "picks": picks})


def _masquerade_trash_offer(game, pid):
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Masquerade", "trash",
                            cards=list(hand), mn=0, mx=1, purpose="trash")


def _masquerade_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, choice["cards"])


# --- Swindler ---------------------------------------------------------------------

def _swindler(game, pid):
    E.add_coins(game, 2)
    E.attack_opponents(game, pid, "Swindler", "hit")


def _swindler_hit(game, pid, frame, choice):
    moved = E.look_top(game, pid, 1)
    if not moved:
        return
    c = moved[0]
    E.trash(game, pid, [c], zone="aside")         # trash log is public
    attacker = game["turn"]
    target = E.cost(game, c)
    piles = [p for p in sorted(game["supply"])
             if game["supply"][p] > 0 and E.cost_eq(game, p, target)]
    if piles:
        E.push_choose_pile(game, attacker, "Swindler", "gain",
                           piles=piles, data={"victim": pid})


def _swindler_gain(game, pid, frame, choice):
    E.gain(game, frame["data"]["victim"], choice["pile"])


# --- Diplomat (action side) ---------------------------------------------------------

def _diplomat(game, pid):
    E.draw(game, pid, 2)
    if len(game["seats"][pid]["hand"]) <= 5:
        E.add_actions(game, 2)


# --- Secret Passage -----------------------------------------------------------------

def _secret_passage(game, pid):
    E.draw(game, pid, 2)
    E.add_actions(game, 1)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Secret Passage", "pick",
                            cards=list(hand), mn=1, mx=1, purpose="put into your deck")


def _secret_passage_pick(game, pid, frame, choice):
    card = choice["cards"][0]
    E.push_place_in_deck(game, pid, "Secret Passage", "place", deck_card=card)


def _secret_passage_place(game, pid, frame, choice):
    card = frame["constraint"]["card"]
    pos = choice["position"]
    E.deck_insert(game, pid, card, pos)
    # Compendium ruling: the chosen position is open information (the card isn't).
    E._log(game, pid, "secret_passage", position=pos,
           depth=len(game["seats"][pid]["deck"]))


# --- Courtier ---------------------------------------------------------------------

_COURTIER_OPTS = [{"id": "action", "label": "+1 Action"},
                  {"id": "buy", "label": "+1 Buy"},
                  {"id": "coins", "label": "+$3"},
                  {"id": "gold", "label": "Gain a Gold"}]


def _courtier(game, pid):
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Courtier", "reveal",
                            cards=list(hand), mn=1, mx=1, purpose="reveal")


def _courtier_reveal(game, pid, frame, choice):
    card = choice["cards"][0]
    E.reveal(game, pid, [card], "hand")
    k = min(len(E.types_of(game, card)), len(_COURTIER_OPTS))
    E.push_choose_option(game, pid, "Courtier", "pick",
                         options=list(_COURTIER_OPTS), pick=k, distinct=True)


def _courtier_pick(game, pid, frame, choice):
    for cid in choice["ids"]:
        if cid == "action":
            E.add_actions(game, 1)
        elif cid == "buy":
            E.add_buys(game, 1)
        elif cid == "coins":
            E.add_coins(game, 3)
        elif cid == "gold":
            E.gain(game, pid, "Gold")


# --- Minion -----------------------------------------------------------------------

def _minion(game, pid):
    E.add_actions(game, 1)
    E.push_choose_option(game, pid, "Minion", "pick",
                         options=[{"id": "coins", "label": "+$2"},
                                  {"id": "discard",
                                   "label": "Discard your hand, +4 Cards; each other player "
                                            "with at least 5 cards in hand does the same"}],
                         pick=1,
                         data={"immune": list(game.get("_atk_immune", []))})


def _minion_pick(game, pid, frame, choice):
    if choice["ids"][0] == "coins":
        E.add_coins(game, 2)
        return
    hand = list(game["seats"][pid]["hand"])
    if hand:
        E.discard(game, pid, hand)
    E.draw(game, pid, 4)
    E.attack_opponents(game, pid, "Minion", "hit", immune=frame["data"]["immune"])


def _minion_hit(game, pid, frame, choice):
    hand = list(game["seats"][pid]["hand"])
    if len(hand) >= 5:
        E.discard(game, pid, hand)
        E.draw(game, pid, 4)


# --- Patrol -----------------------------------------------------------------------

def _patrol(game, pid):
    E.draw(game, pid, 3)
    moved = E.look_top(game, pid, 4)
    if not moved:
        return
    E.reveal(game, pid, list(moved), "deck")
    pocket = [c for c in moved
              if E.has_type(game, c, "victory") or E.has_type(game, c, "curse")]
    if pocket:
        E.take_aside(game, pid, pocket)           # into hand
    rest = list(game["seats"][pid]["aside"])
    if len(rest) >= 2:
        E.push_order_cards(game, pid, "Patrol", "order", cards=rest)
    elif rest:
        E.deck_from_aside(game, pid, rest)


def _patrol_order(game, pid, frame, choice):
    E.deck_from_aside(game, pid, choice["order"])


# --- Replace ----------------------------------------------------------------------

def _replace(game, pid):
    hand = game["seats"][pid]["hand"]
    if not hand:
        return                                    # no trash -> no gain, no curses
    E.push_choose_cards(game, pid, "Replace", "trash",
                        cards=list(hand), mn=1, mx=1, purpose="trash",
                        data={"immune": list(game.get("_atk_immune", []))})


def _replace_trash(game, pid, frame, choice):
    trashed = choice["cards"][0]
    cap = E.cost(game, trashed) + 2
    E.trash(game, pid, [trashed])
    piles = [p for p in sorted(game["supply"])
             if game["supply"][p] > 0 and E.cost_le(game, p, cap)]
    if piles:
        E.push_choose_pile(game, pid, "Replace", "gain",
                           piles=piles, data=dict(frame["data"]))


def _replace_gain(game, pid, frame, choice):
    card = choice["pile"]
    types = E.types_of(game, card)
    dest = "deck" if ("action" in types or "treasure" in types) else "discard"
    if not E.gain(game, pid, card, dest=dest):
        return
    if "victory" in types:                        # a dual-type gain does BOTH
        E.attack_opponents(game, pid, "Replace", "curse",
                           immune=frame["data"]["immune"])


def _replace_curse(game, pid, frame, choice):
    E.gain(game, pid, "Curse")


# --- Torturer ---------------------------------------------------------------------

def _torturer(game, pid):
    E.draw(game, pid, 3)
    E.attack_opponents(game, pid, "Torturer", "hit")


def _torturer_hit(game, pid, frame, choice):
    E.push_choose_option(game, pid, "Torturer", "pick",
                         options=[{"id": "discard", "label": "Discard 2 cards"},
                                  {"id": "curse", "label": "Gain a Curse to your hand"}],
                         pick=1)


def _torturer_pick(game, pid, frame, choice):
    if choice["ids"][0] == "curse":
        E.gain(game, pid, "Curse", dest="hand")   # empty pile: nothing
        return
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Torturer", "discard",
                            cards=list(hand), mn=2, mx=2, purpose="discard")


def _torturer_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


# --- registration ---------------------------------------------------------

EFFECTS = {
    "Courtyard": _courtyard,
    "Pawn": _pawn,
    "Shanty Town": _shanty_town,
    "Steward": _steward,
    "Wishing Well": _wishing_well,
    "Baron": _baron,
    "Bridge": _bridge,
    "Conspirator": _conspirator,
    "Ironworks": _ironworks,
    "Mill": _mill,
    "Mining Village": _mining_village,
    "Nobles": _nobles,
    "Upgrade": _upgrade,
    "Trading Post": _trading_post,
    "Lurker": _lurker,
    "Masquerade": _masquerade,
    "Swindler": _swindler,
    "Diplomat": _diplomat,
    "Secret Passage": _secret_passage,
    "Courtier": _courtier,
    "Minion": _minion,
    "Patrol": _patrol,
    "Replace": _replace,
    "Torturer": _torturer,
}

# Diplomat's REACTION half (its on-play half is _diplomat). Was hardcoded in
# the kernel's attack window; now a registry entry like any other reaction.
# "if you have 5 or more cards in hand" is checked when the window is offered.
ATTACK_REACTIONS = {
    "Diplomat": {"label": "Reveal Diplomat (+2 Cards, then discard 3)",
                 "when": lambda game, pid: len(game["seats"][pid]["hand"]) >= 5,
                 "mode": "reveal", "stage": "react", "repeatable": True},
}


def _diplomat_react(game, pid, frame, choice):
    E.draw(game, pid, 2)
    hand = game["seats"][pid]["hand"]
    E.push_choose_cards(game, pid, "Diplomat", "react_discard",
                        cards=list(hand), mn=3, mx=3, purpose="discard")


def _diplomat_react_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])
    E.reopen_attack_window(game, pid)      # may chain another reaction


STAGES = {
    ("Diplomat", "react"): _diplomat_react,
    ("Diplomat", "react_discard"): _diplomat_react_discard,
    ("Courtyard", "topdeck"): _courtyard_topdeck,
    ("Pawn", "pick"): _pawn_pick,
    ("Steward", "pick"): _steward_pick,
    ("Steward", "trash"): _steward_trash,
    ("Wishing Well", "wish"): _wishing_well_wish,
    ("Baron", "pick"): _baron_pick,
    ("Ironworks", "gain"): _ironworks_gain,
    ("Mill", "pick"): _mill_pick,
    ("Mill", "discard"): _mill_discard,
    ("Mining Village", "pick"): _mining_village_pick,
    ("Nobles", "pick"): _nobles_pick,
    ("Upgrade", "trash"): _upgrade_trash,
    ("Upgrade", "gain"): _upgrade_gain,
    ("Trading Post", "trash"): _trading_post_trash,
    ("Lurker", "pick"): _lurker_pick,
    ("Lurker", "trash_pile"): _lurker_trash_pile,
    ("Lurker", "gain_trash"): _lurker_gain_trash,
    ("Masquerade", "collect"): _masquerade_collect,
    ("Masquerade", "pick"): _masquerade_pick,
    ("Masquerade", "trash"): _masquerade_trash,
    ("Swindler", "hit"): _swindler_hit,
    ("Swindler", "gain"): _swindler_gain,
    ("Secret Passage", "pick"): _secret_passage_pick,
    ("Secret Passage", "place"): _secret_passage_place,
    ("Courtier", "reveal"): _courtier_reveal,
    ("Courtier", "pick"): _courtier_pick,
    ("Minion", "pick"): _minion_pick,
    ("Minion", "hit"): _minion_hit,
    ("Patrol", "order"): _patrol_order,
    ("Replace", "trash"): _replace_trash,
    ("Replace", "gain"): _replace_gain,
    ("Replace", "curse"): _replace_curse,
    ("Torturer", "hit"): _torturer_hit,
    ("Torturer", "pick"): _torturer_pick,
    ("Torturer", "discard"): _torturer_discard,
}
