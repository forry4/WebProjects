"""Base-set card effects, batch B (WP3b).

Owns: Bureaucrat, Bandit, Council Room, Library, Mine, Sentry, Artisan.

See effects_core.py for the EFFECTS/STAGES contract; card code touches the
game only through the engine kernel helpers. Ruling sources: plan par.5 +
compendium v11.1 Card Reference:
  Bureaucrat — the Silver is GAINED TO YOUR DECK; you "attack" even if the
    Silver pile is empty. A victim with no Victory cards reveals their whole
    hand; with exactly one distinct Victory name the reveal+topdeck is forced,
    so it auto-resolves without a frame.
  Bandit — gains a Gold (empty pile ok, still attacks); each opponent reveals
    their top 2 (shuffle-if-short via look_top), first trashes a revealed
    non-Copper Treasure, then discards the rest. With two DISTINCT eligible
    Treasures the VICTIM picks which one is trashed (the trash is that
    player's own instruction — cards.BANDIT_VICTIM_CHOOSES).
  Council Room — the opponents' draw is mandatory and NOT an attack (no
    reaction windows; a direct loop over opponents).
  Library — draws one card at a time via an auto-frame loop; skipped Actions
    sit in the aside zone (excluded from mid-draw shuffles, not counted
    toward 7) and are discarded at the end.
  Mine — optional trash ("may"); the gain arrives IN HAND, cost cap =
    engine.cost of the trashed card at trash time + 3 (Bridge applies).
  Sentry — first trash, then discard, then put the rest back in any order
    (the order frame is skipped when <=1 card remains).
  Artisan — gain to hand (cost <= 5), THEN put a card onto the deck even if
    the gain fizzled (skipped only when the hand is empty).
"""

from . import engine as E


# --- Bureaucrat ---------------------------------------------------------------

def _bureaucrat(game, pid):
    E.gain(game, pid, "Silver", dest="deck")    # empty pile: no Silver, attack anyway
    E.attack_opponents(game, pid, "Bureaucrat", "hit")


def _bureaucrat_hit(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    victories = sorted({c for c in hand if "victory" in E.CARDS[c]["types"]})
    if not victories:
        E.reveal(game, pid, list(hand), "hand")
        return
    if len(victories) == 1:                     # forced — no pointless prompt
        _bureaucrat_topdeck_one(game, pid, victories[0])
        return
    E.push_choose_cards(game, pid, "Bureaucrat", "topdeck",
                        cards=victories, mn=1, mx=1, purpose="topdeck")


def _bureaucrat_topdeck(game, pid, frame, choice):
    _bureaucrat_topdeck_one(game, pid, choice["cards"][0])


def _bureaucrat_topdeck_one(game, pid, card):
    E.reveal(game, pid, [card], "hand")
    E.topdeck(game, pid, card, zone="hand", public=True)


# --- Bandit -------------------------------------------------------------------

def _bandit(game, pid):
    E.gain(game, pid, "Gold")                   # empty pile: no Gold, attack anyway
    E.attack_opponents(game, pid, "Bandit", "hit")


def _bandit_hit(game, pid, frame, choice):
    moved = E.look_top(game, pid, 2)            # shuffle-if-short built in
    if not moved:
        return
    E.reveal(game, pid, list(moved), "deck")
    eligible = [c for c in moved
                if "treasure" in E.CARDS[c]["types"] and c != "Copper"]
    if not eligible:
        E.discard(game, pid, list(moved), zone="aside", public=True)
        return
    distinct = sorted(set(eligible))
    if len(distinct) >= 2:
        # BANDIT_VICTIM_CHOOSES: the victim picks which Treasure is trashed.
        E.push_choose_cards(game, pid, "Bandit", "trash",
                            cards=distinct, mn=1, mx=1, purpose="trash")
        return
    _bandit_trash_rest(game, pid, eligible[0])  # only one way to do it


def _bandit_trash(game, pid, frame, choice):
    _bandit_trash_rest(game, pid, choice["cards"][0])


def _bandit_trash_rest(game, pid, card):
    """First the trash, then the rest of the revealed cards are discarded
    face up (they are still in the aside zone, which holds exactly this
    Bandit hit's revealed cards — each opponent's chain fully resolves
    before the next starts)."""
    E.trash(game, pid, [card], zone="aside")
    rest = list(game["seats"][pid]["aside"])
    if rest:
        E.discard(game, pid, rest, zone="aside", public=True)


# --- Council Room -------------------------------------------------------------

def _council_room(game, pid):
    E.draw(game, pid, 4)
    E.add_buys(game, 1)
    for o in E.opponents(game, pid):            # mandatory draw — NOT an attack
        E.draw(game, o, 1)


# --- Library ------------------------------------------------------------------

def _library(game, pid):
    E.push_auto(game, pid, "Library", "step")


def _library_step(game, pid, frame, choice):
    seat = game["seats"][pid]
    if len(seat["hand"]) >= 7:                  # set-asides don't count toward 7
        _library_finish(game, pid)
        return
    moved = E.look_top(game, pid, 1)            # aside: excluded from any shuffle
    if not moved:                               # deck + discard exhausted
        _library_finish(game, pid)
        return
    c = moved[0]
    if "action" in E.CARDS[c]["types"]:         # optional skip, per Action drawn
        E.push_choose_option(
            game, pid, "Library", "choice",
            options=[{"id": "hand", "label": f"Put {c} in your hand"},
                     {"id": "aside", "label": f"Set {c} aside (discarded afterwards)"}],
            pick=1, data={"card": c})
        return
    E.take_aside(game, pid, [c])                # non-Action: straight to hand
    E.push_auto(game, pid, "Library", "step")


def _library_choice(game, pid, frame, choice):
    if choice["ids"][0] == "hand":
        E.take_aside(game, pid, [frame["data"]["card"]])
    # "aside": the card stays in the aside zone until the final discard
    E.push_auto(game, pid, "Library", "step")


def _library_finish(game, pid):
    aside = list(game["seats"][pid]["aside"])
    if aside:                                   # skipped Actions, discarded at the end
        E.discard(game, pid, aside, zone="aside", public=True)


# --- Mine ---------------------------------------------------------------------

def _mine(game, pid):
    hand = game["seats"][pid]["hand"]
    treasures = sorted({c for c in hand if "treasure" in E.CARDS[c]["types"]})
    if not treasures:                           # nothing to trash: nothing at all
        return
    E.push_choose_cards(game, pid, "Mine", "trash",
                        cards=treasures, mn=0, mx=1, purpose="trash")


def _mine_trash(game, pid, frame, choice):
    if not choice["cards"]:
        return                                  # "may" — declined
    t = choice["cards"][0]
    cap = E.cost(game, t) + 3                   # cost read at trash time (Bridge applies)
    E.trash(game, pid, [t])
    piles = [p for p in sorted(game["supply"])
             if game["supply"][p] > 0
             and "treasure" in E.CARDS[p]["types"]
             and E.cost(game, p) <= cap]
    if piles:
        E.push_choose_pile(game, pid, "Mine", "gain", piles=piles)


def _mine_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"], dest="hand")


# --- Sentry -------------------------------------------------------------------

def _sentry(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    moved = E.look_top(game, pid, 2)
    if not moved:
        return
    E.push_choose_cards(game, pid, "Sentry", "trash",
                        cards=list(moved), mn=0, mx=len(moved), purpose="trash")


def _sentry_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, choice["cards"], zone="aside")
    rest = list(game["seats"][pid]["aside"])
    if not rest:
        return
    E.push_choose_cards(game, pid, "Sentry", "discard",
                        cards=rest, mn=0, mx=len(rest), purpose="discard")


def _sentry_discard(game, pid, frame, choice):
    if choice["cards"]:
        E.discard(game, pid, choice["cards"], zone="aside", public=True)
    rest = list(game["seats"][pid]["aside"])
    if len(rest) >= 2:
        E.push_order_cards(game, pid, "Sentry", "order", cards=rest)
    elif rest:                                  # one card: only one possible order
        E.deck_from_aside(game, pid, rest)


def _sentry_order(game, pid, frame, choice):
    E.deck_from_aside(game, pid, choice["order"])   # order[0] ends up on top


# --- Artisan ------------------------------------------------------------------

def _artisan(game, pid):
    piles = [p for p in sorted(game["supply"])
             if game["supply"][p] > 0 and E.cost(game, p) <= 5]
    if piles:
        E.push_choose_pile(game, pid, "Artisan", "gain", piles=piles)
    else:                                       # nothing gainable — topdeck anyway
        _artisan_topdeck_frame(game, pid)


def _artisan_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"], dest="hand")
    _artisan_topdeck_frame(game, pid)


def _artisan_topdeck_frame(game, pid):
    hand = game["seats"][pid]["hand"]
    if not hand:                                # fizzled gain + empty hand
        return
    E.push_choose_cards(game, pid, "Artisan", "topdeck",
                        cards=list(hand), mn=1, mx=1, purpose="topdeck")


def _artisan_topdeck(game, pid, frame, choice):
    E.topdeck(game, pid, choice["cards"][0])    # from hand, not public


EFFECTS = {
    "Bureaucrat": _bureaucrat,
    "Bandit": _bandit,
    "Council Room": _council_room,
    "Library": _library,
    "Mine": _mine,
    "Sentry": _sentry,
    "Artisan": _artisan,
}

STAGES = {
    ("Bureaucrat", "hit"): _bureaucrat_hit,
    ("Bureaucrat", "topdeck"): _bureaucrat_topdeck,
    ("Bandit", "hit"): _bandit_hit,
    ("Bandit", "trash"): _bandit_trash,
    ("Library", "step"): _library_step,
    ("Library", "choice"): _library_choice,
    ("Mine", "trash"): _mine_trash,
    ("Mine", "gain"): _mine_gain,
    ("Sentry", "trash"): _sentry_trash,
    ("Sentry", "discard"): _sentry_discard,
    ("Sentry", "order"): _sentry_order,
    ("Artisan", "gain"): _artisan_gain,
    ("Artisan", "topdeck"): _artisan_topdeck,
}
