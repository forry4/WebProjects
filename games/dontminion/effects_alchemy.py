"""Alchemy card effects — 11 of the 12 kingdom cards, plus the Potion pile.

**POSSESSION IS DELIBERATELY NOT IMPLEMENTED** (`cards.DEFERRED`). It needs a
turn one player takes and another CONTROLS — ~10 kernel seams, two of them
security-adjacent — and is scoped in
`.claude-plans/dontminion-phase5-alchemy-possession-scope.md`. Everything else
in the set is here.

THE COST VECTOR is this set's kernel contribution and it lives in engine.py:
a cost is {coins, potions}, so "up to $5" excludes every Potion card and
"exactly $1 more" requires the potion components to MATCH. Card code never
computes that — it calls `E.cost_le` / `E.cost_eq_card` / `E.cost_lt_card` and
the rule is applied once, centrally. `E.potion_cost` is the only place a card
may read the potion component directly (Apprentice's "+2 Cards if it has
Potion in its cost").

Headline rulings:
  * ALCHEMIST and HERBALIST are the set's two Clean-up cards, and both are
    registered as per-play `until="turn_end"` watchers on `buy_phase_end` —
    the SAME shape as Scheme, and for the same reason: `_end_turn` is not
    interruptible, so a `cleanup_discard` consumer cannot yet MOVE the card.
    The candidate set comes from `E.leaving_play`, which is what makes the
    dodge faithful rather than approximate: it is exactly "the cards that WILL
    be discarded from play at this Clean-up", so a Duration that stays out is
    correctly excluded — "if a card is not discarded (for instance if it's a
    Duration that stays in play) Herbalist can't put it onto your deck".
  * Both are cumulative per play (a throne-roomed Herbalist may choose two
    Treasures), which falls out of the per-play watcher for free.
  * APPRENTICE reads the trashed card's cost AFTER the trash, per its own
    ruling ("first trash, then check cost, then draw"), and a cost reduction
    genuinely makes it draw fewer cards.
  * TRANSMUTE gains ALL the relevant cards when the trashed card has several
    types, in the printed order (Action -> Duchy, Treasure -> Transmute,
    Victory -> Gold).
  * SCRYING POOL's reveal-and-choose is the ATTACKER's decision for every
    player including themselves; only then comes the dig, which digs for a
    NON-Action (the 2018 rulebook says "Action card" and is an erratum).
  * GOLEM's two plays are NOT optional, and it digs past Golems.
"""

from . import engine as E


def _piles(game, pred=None):
    return [p for p in sorted(game["supply"])
            if game["supply"][p] > 0 and (pred is None or pred(p))]


def _on_table(game, pid):
    """CARDS YOU HAVE IN PLAY — in_play plus the duration zone and its riders."""
    seat = game["seats"][pid]
    out = list(seat["in_play"])
    for e in seat["duration"]:
        out.append(e["card"])
        out.extend(e.get("riders", []))
    return out


# --- Alchemist ---------------------------------------------------------------
# +2 Cards +1 Action. 2022 version: it SETS UP A LATER ABILITY when played,
# triggering at the start of Clean-up — "you can put Alchemists onto your deck
# as long as you have a Potion in play; it doesn't matter if you used the
# Potion to buy anything".

def _alchemist(game, pid):
    E.draw(game, pid, 2)
    E.add_actions(game, 1)
    E.add_watcher(game, pid, "Alchemist", "buy_phase_end",
                  stage="topdeck", until="turn_end")


def _alchemist_topdeck(game, pid, frame, choice):
    if "Potion" not in _on_table(game, pid):
        return
    if "Alchemist" not in E.leaving_play(game, pid):
        E.lost_track(game, pid, "Alchemist", why="it is not being discarded from play")
        return
    E.push_choose_option(game, pid, "Alchemist", "answer",
                         options=[{"id": "yes", "label": "Put Alchemist onto your deck"},
                                  {"id": "no", "label": "Leave it"}])


def _alchemist_answer(game, pid, frame, choice):
    if choice["ids"][0] == "yes":
        E.topdeck_from_play(game, pid, "Alchemist")


def _alchemist_fires(game, watcher, ctx):
    """Join-time pool filter: no Potion in play, or the Alchemist already gone,
    means the ability visibly does nothing and must not be offered for
    ordering against a real one."""
    return ("Potion" in _on_table(game, watcher["owner"])
            and "Alchemist" in E.leaving_play(game, watcher["owner"]))


# --- Apothecary --------------------------------------------------------------
# +1 Card +1 Action, reveal 4, Coppers and Potions to hand, the rest back in
# any order.

def _apothecary(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    seen = E.look_top(game, pid, 4)
    if not seen:
        return
    E.reveal(game, pid, seen, "deck")
    keep = [c for c in seen if c in ("Copper", "Potion")]
    rest = [c for c in seen if c not in ("Copper", "Potion")]
    if keep:
        E.take_aside(game, pid, keep, dest="hand")
    if len(rest) > 1:
        E.push_order_cards(game, pid, "Apothecary", "putback", rest)
    elif rest:
        E.deck_from_aside(game, pid, rest)


def _apothecary_putback(game, pid, frame, choice):
    E.deck_from_aside(game, pid, list(choice["order"]))


# --- Apprentice --------------------------------------------------------------
# +1 Action, trash a card, +1 Card per $1 it costs, +2 Cards if it has a Potion
# in its cost. "If there is a COST REDUCTION, Apprentice will draw fewer cards."

def _apprentice(game, pid):
    E.add_actions(game, 1)
    hand = sorted(game["seats"][pid]["hand"])
    if not hand:
        return
    E.push_choose_cards(game, pid, "Apprentice", "trash", hand, 1, 1,
                        "trash a card (Apprentice)")


def _apprentice_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    E.trash(game, pid, [card])
    # read AFTER the trash, per the card's own ruling ("first trash, then check
    # cost, then draw"). Trashing cannot change what a card costs in this pool,
    # so this agrees with the B3 convention; it is written this way because the
    # ruling is explicit.
    n = E.cost(game, card) + (2 if E.potion_cost(game, card) else 0)
    if n:
        E.draw(game, pid, n)


# --- Familiar ----------------------------------------------------------------

def _familiar(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.attack_opponents(game, pid, "Familiar", "hit")


def _familiar_hit(game, opp, frame, choice):
    E.gain(game, opp, "Curse")


# --- Golem -------------------------------------------------------------------
# Dig for 2 Action cards OTHER THAN GOLEMS, discard everything else, then play
# both in either order. Not optional.

def _golem(game, pid):
    seat = game["seats"][pid]
    found = []
    while len(found) < 2:
        got = E.look_top(game, pid, 1)
        if not got:
            break
        E.reveal(game, pid, got, "deck")
        if E.has_type(game, got[0], "action") and got[0] != "Golem":
            found.append(got[0])
    rest = [c for c in seat["aside"] if c not in found or found.count(c) < seat["aside"].count(c)]
    # discard everything revealed that is not one of the two found Actions
    leftover = list(seat["aside"])
    for c in found:
        leftover.remove(c)
    if leftover:
        E.discard(game, pid, leftover, zone="aside", public=True)
    if not found:
        return
    if len(found) == 2 and found[0] != found[1]:
        E.push_choose_option(
            game, pid, "Golem", "order",
            options=[{"id": "first", "label": f"Play {found[0]} first"},
                     {"id": "second", "label": f"Play {found[1]} first"}],
            data={"found": found})
        return
    _golem_play(game, pid, found)


def _golem_order(game, pid, frame, choice):
    found = list(frame["data"]["found"])
    if choice["ids"][0] == "second":
        found.reverse()
    _golem_play(game, pid, found)


def _golem_play(game, pid, order):
    """Queue the plays so each resolves fully before the next — "first discard,
    then play each card in turn". Pushed in reverse so order[0] runs first."""
    for card in reversed(order):
        E.push_auto(game, pid, "Golem", "play_one", data={"card": card})


def _golem_play_one(game, pid, frame, choice):
    card = frame["data"]["card"]
    if card not in game["seats"][pid]["aside"]:
        E.lost_track(game, pid, card, "played")
        return
    E.play_action_card(game, pid, card, from_zone="aside")


# --- Herbalist ---------------------------------------------------------------
# +1 Buy +$1. 2022 version: SETS UP A LATER ABILITY when played, letting you
# choose ONE Treasure you discard this turn and put it onto your deck.
# Cumulative per play (a throne-roomed Herbalist chooses two).

def _herbalist(game, pid):
    E.add_buys(game, 1)
    E.add_coins(game, 1)
    E.add_watcher(game, pid, "Herbalist", "buy_phase_end",
                  stage="topdeck", until="turn_end")


def _herbalist_candidates(game, pid):
    """Treasures that WILL be discarded from play at this Clean-up. Using
    leaving_play rather than in_play is what excludes a Duration that stays
    out — "if a card is not discarded... Herbalist can't put it onto your
    deck"."""
    return sorted({c for c in E.leaving_play(game, pid)
                   if E.has_type(game, c, "treasure")})


def _herbalist_topdeck(game, pid, frame, choice):
    opts = _herbalist_candidates(game, pid)
    if not opts:
        return
    E.push_choose_cards(game, pid, "Herbalist", "answer", opts, 0, 1,
                        "put a Treasure you discard this turn onto your deck")


def _herbalist_answer(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    if card not in E.leaving_play(game, pid):
        E.lost_track(game, pid, card, why="it is no longer being discarded from play")
        return
    E.topdeck_from_play(game, pid, card)


def _herbalist_fires(game, watcher, ctx):
    return bool(_herbalist_candidates(game, watcher["owner"]))


# --- Philosopher's Stone -----------------------------------------------------
# A Treasure worth no printed $: count your deck AND discard pile, +$1 per 5.

def _philosophers_stone(game, pid):
    seat = game["seats"][pid]
    total = len(seat["deck"]) + len(seat["discard"])
    E.add_coins(game, total // 5)


# --- Scrying Pool ------------------------------------------------------------
# +1 Action. EACH player including you reveals their top card and the ATTACKER
# chooses discard-or-put-back. Then dig for a non-Action; every card revealed
# by the dig (the Actions and the one non-Action) goes to hand.

def _scrying_pool(game, pid):
    E.add_actions(game, 1)
    # the dig is parked FIRST so it resolves after every reveal-and-choose
    E.push_auto(game, pid, "Scrying Pool", "dig", data={})
    E.attack_opponents(game, pid, "Scrying Pool", "peek", data={"attacker": pid})
    _scrying_peek_at(game, pid, pid)          # "including you"


def _scrying_peek_at(game, attacker, target):
    got = E.look_top(game, target, 1)
    if not got:
        return
    E.reveal(game, target, got, "deck")
    name = game["names"].get(target, target)
    E.push_choose_option(
        game, attacker, "Scrying Pool", "choose",
        options=[{"id": "discard", "label": f"{name}: discard the {got[0]}"},
                 {"id": "keep", "label": f"{name}: put the {got[0]} back"}],
        data={"target": target, "card": got[0]})


def _scrying_peek(game, opp, frame, choice):
    _scrying_peek_at(game, frame["data"]["attacker"], opp)


def _scrying_choose(game, attacker, frame, choice):
    d = frame["data"]
    target, card = d["target"], d["card"]
    if card not in game["seats"][target]["aside"]:
        E.lost_track(game, target, card, why="it moved")
        return
    if choice["ids"][0] == "discard":
        E.discard(game, target, [card], zone="aside", public=True)
    else:
        E.deck_from_aside(game, target, [card])


def _scrying_dig(game, pid, frame, choice):
    seat = game["seats"][pid]
    while True:
        got = E.look_top(game, pid, 1)
        if not got:
            break
        E.reveal(game, pid, got, "deck")
        if not E.has_type(game, got[0], "action"):
            break
    if seat["aside"]:
        E.take_aside(game, pid, list(seat["aside"]), dest="hand")


# --- Transmute ---------------------------------------------------------------
# Trash a card; Action -> Duchy, Treasure -> Transmute, Victory -> Gold. A card
# with several of those types gains ALL the matching cards, in that order.

def _transmute(game, pid):
    hand = sorted(game["seats"][pid]["hand"])
    if not hand:
        return
    E.push_choose_cards(game, pid, "Transmute", "trash", hand, 1, 1,
                        "trash a card (Transmute)")


def _transmute_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    types = list(E.types_of(game, card))       # captured before the trash
    E.trash(game, pid, [card])
    for t, gained in (("action", "Duchy"), ("treasure", "Transmute"),
                      ("victory", "Gold")):
        if t in types:
            E.gain(game, pid, gained)


# --- University --------------------------------------------------------------

def _university(game, pid):
    E.add_actions(game, 2)
    piles = _piles(game, lambda p: E.has_type(game, p, "action")
                   and E.cost_le(game, p, 5))
    if not piles:
        return
    E.push_choose_pile(game, pid, "University", "gain", piles)


def _university_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Vineyard ----------------------------------------------------------------
# Pure Victory: 1 VP per 3 Action cards you have, scored in engine._vp_of
# ("vineyard"). No play ability, so no EFFECTS entry.


# ── registries ───────────────────────────────────────────────────────────────

EFFECTS = {
    "Alchemist": _alchemist,
    "Apothecary": _apothecary,
    "Apprentice": _apprentice,
    "Familiar": _familiar,
    "Golem": _golem,
    "Herbalist": _herbalist,
    "Philosopher's Stone": _philosophers_stone,
    "Scrying Pool": _scrying_pool,
    "Transmute": _transmute,
    "University": _university,
}

STAGES = {
    ("Alchemist", "topdeck"): _alchemist_topdeck,
    ("Alchemist", "answer"): _alchemist_answer,
    ("Apothecary", "putback"): _apothecary_putback,
    ("Apprentice", "trash"): _apprentice_trash,
    ("Familiar", "hit"): _familiar_hit,
    ("Golem", "order"): _golem_order,
    ("Golem", "play_one"): _golem_play_one,
    ("Herbalist", "topdeck"): _herbalist_topdeck,
    ("Herbalist", "answer"): _herbalist_answer,
    ("Scrying Pool", "peek"): _scrying_peek,
    ("Scrying Pool", "choose"): _scrying_choose,
    ("Scrying Pool", "dig"): _scrying_dig,
    ("Transmute", "trash"): _transmute_trash,
    ("University", "gain"): _university_gain,
}

WATCHER_WHENS = {
    ("Alchemist", "topdeck"): _alchemist_fires,
    ("Herbalist", "topdeck"): _herbalist_fires,
}

# Philosopher's Stone counts your deck and discard — it neither draws, looks
# nor reveals, and its value can't be changed by playing another Treasure
# first, so it is plain autoplay (bucket 3). Potion likewise.
