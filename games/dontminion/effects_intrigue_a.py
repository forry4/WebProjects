"""Intrigue card effects, batch A (WP3c).

Owns: Courtyard, Pawn, Shanty Town, Steward, Wishing Well, Baron, Bridge,
Conspirator, Ironworks, Mill, Mining Village, Nobles, Upgrade, Trading Post.

See effects_core.py for the EFFECTS/STAGES contract. Rulings applied here:
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
"""

from . import engine as E


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
    if not any("action" in E.CARDS[c]["types"] for c in hand):
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
    piles = _gain_piles(game, lambda p: E.cost(game, p) <= 4)
    if piles:
        E.push_choose_pile(game, pid, "Ironworks", "gain", piles=piles)


def _ironworks_gain(game, pid, frame, choice):
    card = choice["pile"]
    if not E.gain(game, pid, card):
        return
    types = E.CARDS[card]["types"]            # dual types grant multiple bonuses
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
    piles = _gain_piles(game, lambda p: E.cost(game, p) == target)
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
}

STAGES = {
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
}
