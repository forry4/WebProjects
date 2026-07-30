"""Kernel exemplar card effects (WP2-owned — batch WPs must not edit this file).

These six cards are living documentation of the frozen effects API:
  Smithy      — vanilla draw
  Village     — draw + actions
  Moat        — vanilla play ability (its Reaction side lives in the engine's
                __attack window; reactions are kernel machinery, not card code)
  Militia     — attack + per-opponent choose_cards
  Witch       — attack + per-opponent gain (Curse depletion falls out of gain())
  Throne Room — auto-frame nesting (play an Action twice)

Contract (games/dontminion/CLAUDE.md §frozen API):
  EFFECTS[name](game, pid)                 — on_play; runs inside the attack
                                             play_ability frame for Attack cards
  STAGES[(name, stage)](game, pid, frame, choice)
                                           — choice is the validated decision
                                             payload, or None for auto frames.
Card code touches the game ONLY through engine kernel helpers.
"""

from . import engine as E


def _smithy(game, pid):
    E.draw(game, pid, 3)


def _village(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 2)


def _moat(game, pid):
    E.draw(game, pid, 2)


def _militia(game, pid):
    E.add_coins(game, 2)
    E.attack_opponents(game, pid, "Militia", "hit")


def _militia_hit(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    if len(hand) > 3:
        n = len(hand) - 3
        E.push_choose_cards(game, pid, "Militia", "discard",
                            cards=list(hand), mn=n, mx=n, purpose="discard")


def _militia_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


def _witch(game, pid):
    E.draw(game, pid, 2)
    E.attack_opponents(game, pid, "Witch", "curse")


def _witch_curse(game, pid, frame, choice):
    E.gain(game, pid, "Curse")


def _throne_room(game, pid):
    hand = game["seats"][pid]["hand"]
    actions = sorted({c for c in hand if "action" in E.CARDS[c]["types"]})
    if not actions:
        return
    E.push_choose_cards(game, pid, "Throne Room", "pick",
                        cards=actions, mn=0, mx=1, purpose="play twice")


def _throne_room_pick(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    # The second play is parked BELOW the first play's frames (LIFO), so the
    # first play fully resolves before the replay — the throne-room rule.
    E.push_auto(game, pid, "Throne Room", "second", data={"card": card})
    E.play_action_card(game, pid, card, from_zone="hand")


def _throne_room_second(game, pid, frame, choice):
    # from_zone=None: the card is already in play (or lost track of, e.g. a
    # trashed Mining Village) — it is played again without moving.
    card = frame["data"]["card"]
    E.play_action_card(game, pid, card, from_zone=None)
    # Duration rule: the Throne Room that played a persisting Duration stays
    # on the table with it (discarded together at that Duration's clean-up).
    if "duration" in E.CARDS[card]["types"]:
        E.mark_duration_rider(game, pid, card, "Throne Room")


EFFECTS = {
    "Smithy": _smithy,
    "Village": _village,
    "Moat": _moat,
    "Militia": _militia,
    "Witch": _witch,
    "Throne Room": _throne_room,
}

STAGES = {
    ("Militia", "hit"): _militia_hit,
    ("Militia", "discard"): _militia_discard,
    ("Witch", "curse"): _witch_curse,
    ("Throne Room", "pick"): _throne_room_pick,
    ("Throne Room", "second"): _throne_room_second,
}
