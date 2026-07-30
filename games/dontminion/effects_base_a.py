"""Base-set card effects, batch A (WP3a).

Owns: Cellar, Chapel, Harbinger, Merchant, Vassal, Workshop, Moneylender,
Poacher, Remodel, Laboratory, Festival, Market.
(Village lives in effects_core.py as a kernel exemplar.)

See effects_core.py for the EFFECTS/STAGES contract.
"""

from . import engine as E


def _eligible_gain_piles(game, cap):
    """Non-empty supply piles costing <= cap — ALWAYS via engine.cost (Bridge)."""
    return [p for p in sorted(game["supply"])
            if game["supply"][p] > 0 and E.cost_le(game, p, cap)]


def _cellar(game, pid):
    E.add_actions(game, 1)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Cellar", "discard",
                            cards=list(hand), mn=0, mx=len(hand), purpose="discard")


def _cellar_discard(game, pid, frame, choice):
    picked = choice["cards"]
    if not picked:
        return
    # All chosen cards are discarded at once, THEN the draw — so a mid-draw
    # shuffle includes the just-discarded cards (rulebook clarification).
    E.discard(game, pid, picked)
    E.draw(game, pid, len(picked))


def _chapel(game, pid):
    hand = game["seats"][pid]["hand"]
    if not hand:
        return
    E.push_choose_cards(game, pid, "Chapel", "trash",
                        cards=list(hand), mn=0, mx=4, purpose="trash")


def _chapel_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, choice["cards"])


def _harbinger(game, pid):
    E.draw(game, pid, 1)          # first — its shuffle may consume the discard
    E.add_actions(game, 1)
    discard_pile = game["seats"][pid]["discard"]
    if discard_pile:
        # The frame constraint carries the full discard contents — the one
        # place a player legally browses their whole discard (actor-only view).
        E.push_choose_cards(game, pid, "Harbinger", "topdeck",
                            cards=list(discard_pile), mn=0, mx=1, purpose="topdeck")


def _harbinger_topdeck(game, pid, frame, choice):
    if choice["cards"]:
        E.topdeck(game, pid, choice["cards"][0], zone="discard", public=True)


def _merchant(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    # The play_treasure handler pays +$1 per merchant on the first Silver.
    game["turn_ctx"]["merchants"] += 1


def _vassal(game, pid):
    E.add_coins(game, 2)
    looked = E.look_top(game, pid, 1)
    if not looked:
        return
    card = looked[0]
    if E.has_type(game, card, "action"):
        E.push_choose_option(game, pid, "Vassal", "top_action",
                             options=[{"id": "play", "label": f"Play {card}"},
                                      {"id": "discard", "label": f"Discard {card}"}],
                             pick=1, data={"card": card})
    else:
        E.discard(game, pid, [card], zone="aside", public=True)


def _vassal_top_action(game, pid, frame, choice):
    card = frame["data"]["card"]
    if choice["ids"] == ["play"]:
        # Counts actions_played and wraps Attack plays; consumes no action.
        E.play_action_card(game, pid, card, from_zone="aside")
    else:
        E.discard(game, pid, [card], zone="aside", public=True)


def _workshop(game, pid):
    piles = _eligible_gain_piles(game, 4)
    if piles:
        E.push_choose_pile(game, pid, "Workshop", "gain", piles=piles)


def _workshop_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


def _moneylender(game, pid):
    if "Copper" in game["seats"][pid]["hand"]:
        E.push_choose_cards(game, pid, "Moneylender", "trash",
                            cards=["Copper"], mn=0, mx=1, purpose="trash")


def _moneylender_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, ["Copper"])
        E.add_coins(game, 3)


def _poacher(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_coins(game, 1)
    n = E.count_empty_piles(game)      # read at the card's own resolution
    hand = game["seats"][pid]["hand"]
    if n > 0 and hand:
        k = min(n, len(hand))
        E.push_choose_cards(game, pid, "Poacher", "discard",
                            cards=list(hand), mn=k, mx=k, purpose="discard")


def _poacher_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


def _remodel(game, pid):
    hand = game["seats"][pid]["hand"]
    if not hand:
        return                          # no trash target -> nothing at all
    E.push_choose_cards(game, pid, "Remodel", "trash",
                        cards=list(hand), mn=1, mx=1, purpose="trash")


def _remodel_trash(game, pid, frame, choice):
    trashed = choice["cards"][0]
    E.trash(game, pid, [trashed])
    cap = E.cost(game, trashed) + 2
    piles = _eligible_gain_piles(game, cap)
    if piles:
        E.push_choose_pile(game, pid, "Remodel", "gain", piles=piles)
    # No eligible pile -> nothing more (the trash already happened).


def _remodel_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


def _laboratory(game, pid):
    E.draw(game, pid, 2)
    E.add_actions(game, 1)


def _festival(game, pid):
    E.add_actions(game, 2)
    E.add_buys(game, 1)
    E.add_coins(game, 2)


def _market(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_buys(game, 1)
    E.add_coins(game, 1)


EFFECTS = {
    "Cellar": _cellar,
    "Chapel": _chapel,
    "Harbinger": _harbinger,
    "Merchant": _merchant,
    "Vassal": _vassal,
    "Workshop": _workshop,
    "Moneylender": _moneylender,
    "Poacher": _poacher,
    "Remodel": _remodel,
    "Laboratory": _laboratory,
    "Festival": _festival,
    "Market": _market,
}

STAGES = {
    ("Cellar", "discard"): _cellar_discard,
    ("Chapel", "trash"): _chapel_trash,
    ("Harbinger", "topdeck"): _harbinger_topdeck,
    ("Vassal", "top_action"): _vassal_top_action,
    ("Workshop", "gain"): _workshop_gain,
    ("Moneylender", "trash"): _moneylender_trash,
    ("Poacher", "discard"): _poacher_discard,
    ("Remodel", "trash"): _remodel_trash,
    ("Remodel", "gain"): _remodel_gain,
}
