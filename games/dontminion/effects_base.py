"""Base Set 2E card effects — all 26 kingdom cards.

Kernel exemplar card effects (WP2-owned — batch WPs must not edit this file).

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

The rest of the set: Artisan, Bandit, Bureaucrat, Cellar, Chapel, Council
Room, Festival, Harbinger, Laboratory, Library, Market, Merchant, Mine,
Moneylender, Poacher, Remodel, Sentry, Vassal, Workshop. (Gardens is
data-only — its VP rule lives in cards.py.)

Ruling sources: plan par.5 + compendium v11.1 Card Reference:
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

The EFFECTS/STAGES contract lives in games/dontminion/CLAUDE.md (the frozen
engine API); card code touches the game ONLY through the engine helpers.
"""

from . import engine as E


# ==========================================================================
# core batch
# ==========================================================================

def _smithy(game, pid):
    E.add_cards(game, 3, pid)


def _village(game, pid):
    E.add_cards(game, 1, pid)
    E.add_actions(game, 2)


def _moat(game, pid):
    E.add_cards(game, 2, pid)


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
    E.add_cards(game, 2, pid)
    E.attack_opponents(game, pid, "Witch", "curse")


def _witch_curse(game, pid, frame, choice):
    E.gain(game, pid, "Curse")


def _throne_room(game, pid):
    hand = game["seats"][pid]["hand"]
    actions = sorted({c for c in hand if E.has_type(game, c, "action")})
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
    if E.has_type(game, card, "duration"):
        E.mark_duration_rider(game, pid, card, "Throne Room")

# ==========================================================================
# base_a batch
# ==========================================================================

def _eligible_gain_piles(game, cap=None, ref=None, delta=0):
    """Non-empty supply piles a gain may reach, by ONE of two bounds:

    `cap`  — a literal "$N" (Workshop). A card with a Potion in its cost is
             never "up to $N", which engine.cost_le enforces.
    `ref`  — "up to `delta` more than THIS CARD" (Remodel). This is the form
             the cost VECTOR needs: "up to $2 more than {$3,P}" is
             "up to {$5,P}", and a number bound would exclude every Potion
             card instead."""
    if ref is not None:
        ok = lambda p: E.cost_le_card(game, p, ref, delta)      # noqa: E731
    else:
        ok = lambda p: E.cost_le(game, p, cap)                  # noqa: E731
    return [p for p in sorted(game["supply"]) if game["supply"][p] > 0 and ok(p)]


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
    # `draw`, NOT `add_cards`: Base 2E reads "discard any number of cards, THEN
    # DRAW THAT MANY", with no printed plus — the 1E card was "+1 Card per card
    # discarded" and we shipped that wording until ph. 10. The difference was
    # unobservable for nine phases and Way of the Chameleon makes it real: the
    # compendium names Cellar in exactly that list ("Cellar, Oracle, Storeroom
    # and Storyteller are functionally different with Way of the Chameleon
    # depending on which edition you're using"). Storeroom and Storyteller were
    # already on the current wording; Cellar was the one that slipped.
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
    E.add_cards(game, 1, pid)          # first — its shuffle may consume the discard
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
    E.add_cards(game, 1, pid)
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
    E.add_cards(game, 1, pid)
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
    ref = trashed                          # vector: "up to $2 more than IT"
    piles = _eligible_gain_piles(game, ref=ref, delta=2)
    if piles:
        E.push_choose_pile(game, pid, "Remodel", "gain", piles=piles)
    # No eligible pile -> nothing more (the trash already happened).


def _remodel_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


def _laboratory(game, pid):
    E.add_cards(game, 2, pid)
    E.add_actions(game, 1)


def _festival(game, pid):
    E.add_actions(game, 2)
    E.add_buys(game, 1)
    E.add_coins(game, 2)


def _market(game, pid):
    E.add_cards(game, 1, pid)
    E.add_actions(game, 1)
    E.add_buys(game, 1)
    E.add_coins(game, 1)

# ==========================================================================
# base_b batch
# ==========================================================================

# --- Bureaucrat ---------------------------------------------------------------

def _bureaucrat(game, pid):
    E.gain(game, pid, "Silver", dest="deck")    # empty pile: no Silver, attack anyway
    E.attack_opponents(game, pid, "Bureaucrat", "hit")


def _bureaucrat_hit(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    victories = sorted({c for c in hand if E.has_type(game, c, "victory")})
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
                if E.has_type(game, c, "treasure") and c != "Copper"]
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
    E.add_cards(game, 4, pid)
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
    if E.has_type(game, c, "action"):         # optional skip, per Action drawn
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
    treasures = sorted({c for c in hand if E.has_type(game, c, "treasure")})
    if not treasures:                           # nothing to trash: nothing at all
        return
    E.push_choose_cards(game, pid, "Mine", "trash",
                        cards=treasures, mn=0, mx=1, purpose="trash")


def _mine_trash(game, pid, frame, choice):
    if not choice["cards"]:
        return                                  # "may" — declined
    t = choice["cards"][0]
    ref = t                       # vector: "up to $3 more than IT" (Bridge-aware)
    E.trash(game, pid, [t])
    piles = [p for p in sorted(game["supply"])
             if game["supply"][p] > 0
             and E.has_type(game, p, "treasure")
             and E.cost_le_card(game, p, ref, 3)]
    if piles:
        E.push_choose_pile(game, pid, "Mine", "gain", piles=piles)


def _mine_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"], dest="hand")


# --- Sentry -------------------------------------------------------------------

def _sentry(game, pid):
    E.add_cards(game, 1, pid)
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
    chosen = list(choice["cards"])
    rest = [c for c in game["seats"][pid]["aside"]]
    for c in chosen:
        rest.remove(c)
    # "first trash, then discard, THEN put cards back" — the kernel helper owns
    # that order, so a discarded Tunnel/Trail reacts before the rest go back
    E.discard_then_putback(game, pid, "Sentry", chosen, rest)


# --- Artisan ------------------------------------------------------------------

def _artisan(game, pid):
    piles = [p for p in sorted(game["supply"])
             if game["supply"][p] > 0 and E.cost_le(game, p, 5)]
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


# --- registration ---------------------------------------------------------

# Cards that react to an Attack being PLAYED. The kernel used to hardcode Moat
# (and Diplomat) inside _reaction_options; they live with their own set now, so
# a new reaction is a registry entry rather than a kernel edit.
ATTACK_REACTIONS = {
    "Moat": {"label": "Reveal Moat (unaffected by this attack)",
             "immunity": True, "mode": "reveal", "repeatable": False},
}

EFFECTS = {
    "Smithy": _smithy,
    "Village": _village,
    "Moat": _moat,
    "Militia": _militia,
    "Witch": _witch,
    "Throne Room": _throne_room,
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
    "Bureaucrat": _bureaucrat,
    "Bandit": _bandit,
    "Council Room": _council_room,
    "Library": _library,
    "Mine": _mine,
    "Sentry": _sentry,
    "Artisan": _artisan,
}

STAGES = {
    ("Militia", "hit"): _militia_hit,
    ("Militia", "discard"): _militia_discard,
    ("Witch", "curse"): _witch_curse,
    ("Throne Room", "pick"): _throne_room_pick,
    ("Throne Room", "second"): _throne_room_second,
    ("Cellar", "discard"): _cellar_discard,
    ("Chapel", "trash"): _chapel_trash,
    ("Harbinger", "topdeck"): _harbinger_topdeck,
    ("Vassal", "top_action"): _vassal_top_action,
    ("Workshop", "gain"): _workshop_gain,
    ("Moneylender", "trash"): _moneylender_trash,
    ("Poacher", "discard"): _poacher_discard,
    ("Remodel", "trash"): _remodel_trash,
    ("Remodel", "gain"): _remodel_gain,
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
    ("Artisan", "gain"): _artisan_gain,
    ("Artisan", "topdeck"): _artisan_topdeck,
}
