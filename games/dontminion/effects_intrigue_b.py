"""Intrigue card effects, batch B (WP3d).

Owns: Lurker, Masquerade, Swindler, Diplomat (action side — its Reaction lives
in the engine's __attack window), Secret Passage, Courtier, Minion, Patrol,
Replace, Torturer.

Design notes:
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
"""

from . import engine as E


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


EFFECTS = {
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

STAGES = {
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
