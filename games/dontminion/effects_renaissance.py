"""Renaissance (2018) — 25 kingdom cards, 20 PROJECTS and 5 ARTIFACTS.

The two halves this set was built in are concatenated here (registry UNION —
each half declares the registries once at the top of this file and then only
`.update`s them, so neither can silently win). Half A is the simple half:
Lackeys, Acting Troupe, Flag Bearer, Hideout, Silk Merchant, Old Witch,
Recruiter, Scholar, Sculptor, Spices, Swashbuckler, Villain, Ducat, and the
eight Projects that ride seams the kernel already had (Academy, Guildhall,
Barracks, Fair, Cathedral, Crop Rotation, Silos, Pageant). Half B is the
mechanically complex one: Border Guard, Cargo Ship, Experiment, Improve,
Inventor, Mountain Village, Patron, Priest, Research, Scepter, Seer,
Treasurer, the twelve remaining Projects and the Artifacts.

Behaviour and every edge case from the Knutsen compendium v11.1 ch. VII
(per-card rulings), ch. IV (COFFERS AND VILLAGERS / EVENTS AND PROJECTS /
STATES AND ARTIFACTS) and ch. V (the errata). The Villagers mat, project cube
ownership, the artifacts table, `final_draw`, `duration_handle` and
`trash(**extra)` are all kernel — see `CLAUDE.md` "Kernel v9".

SEVEN OF THIS SET'S OBJECTS DIFFER FROM THEIR 2018 PRINTING, and four of them
change the code (ch. V): the 2019 **Lantern** triggers on ANY Border Guard the
holder plays; **Citadel** was changed in 2021 to play the card twice and
CHANGED BACK in 2022, so the current card replays it after it resolves (ph.
6H's `action_resolved`); the 2022 **Innovation** works on any Action you gain
on your turn, once per turn; the 2022 **Experiment** returns "to its PILE",
not to the Supply, which is what lets it work with Ferryman's extra pile; and
the 2024 **Scepter** is itself a Command card that may only replay non-Command
cards. **Exploration** and **Patron** carry the other two.

FOUR PROJECTS ARE ENTIRELY KERNEL-SIDE and deliberately have no entry here:
**Star Chart** (the interruptible shuffle), **Canal** (a `cost()` clause),
**Capitalism** (a `types_of` injection + the Buy-phase play routing) and
**Fleet** (the after-game-end round). They are contract-tested in
`tests/test_renaissance_kernel.py`.
"""

from . import engine as E

EFFECTS = {}
STAGES = {}
TRIGGERS = {}
WATCHER_WHENS = {}
MANUAL_TREASURES = set()
LANDSCAPE_FX = {}


# ============================================================================
# HALF A — the simple half
# ============================================================================
# ══ shared helpers ═══════════════════════════════════════════════════════════

def _hand(game, pid):
    return game["seats"][pid]["hand"]


def _gain_piles_up_to(game, coins):
    """Non-empty SUPPLY piles a "gain a card costing up to $N" may reach.
    `cost_le` is what keeps a Potion- or Debt-costed pile out of an upper
    bound; starting from `game["supply"]` is what keeps a non-Supply pile
    (Spoils, a Traveller, Ferryman's extra pile) out by construction."""
    return [p for p in sorted(game["supply"])
            if E.pile_top(game, p) is not None and E.cost_le(game, p, coins)]


# ══ THE KINGDOM CARDS ════════════════════════════════════════════════════════

# --- Lackeys ($2) ------------------------------------------------------------
# "+2 Cards. — When you gain this, +2 Villagers."

def _lackeys(game, pid):
    # the draw ENDS the ability, so it is the final_draw form (Star Chart)
    E.final_draw(game, pid, 2)


def _lackeys_gain(game, pid, frame, choice):
    E.add_villagers(game, 2, pid)


# --- Acting Troupe ($3) ------------------------------------------------------
# "+4 Villagers. Trash this."

def _acting_troupe(game, pid):
    # "You get +4 Villagers even if you don't trash this" — a Throne Room gives
    # 8 Villagers and one trash, because the second play finds nothing on the
    # table (the Farmers' Market precedent: the in_play test, silently).
    E.add_villagers(game, 4, pid)
    if "Acting Troupe" in game["seats"][pid]["in_play"]:
        E.trash(game, pid, ["Acting Troupe"], zone="in_play")


# --- Flag Bearer ($4) --------------------------------------------------------
# "+$2. — When you gain or trash this, take the Flag."

def _flag_bearer(game, pid):
    E.add_coins(game, 2)


def _flag_bearer_take(game, pid, frame, choice):
    # "You take the Artifact card from another player if they have it"; taking
    # your own is a logged no-op. Flag is kept available exactly when Flag
    # Bearer is in the game (cards.artifacts_for), which is the only way this
    # trigger can fire at all.
    E.take_artifact(game, pid, "Flag")


# --- Hideout ($4) ------------------------------------------------------------
# "+1 Card. +2 Actions. Trash a card from your hand. If it's a Victory card,
# gain a Curse."

def _hideout(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 2)
    hand = _hand(game, pid)
    if hand:
        E.push_choose_cards(game, pid, "Hideout", "trash", list(hand),
                            1, 1, "trash")


def _hideout_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    # the type is read BEFORE the trash (deviation B3), and the Curse gain is
    # parked BELOW it so the trashed card's own on-trash ability resolves first
    # — the phase-3/6/8 ordering lesson
    if E.has_type(game, card, "victory"):
        E.push_auto(game, pid, "Hideout", "curse")
    E.trash(game, pid, [card])


def _hideout_curse(game, pid, frame, choice):
    E.gain(game, pid, "Curse")


# --- Silk Merchant ($4) ------------------------------------------------------
# "+2 Cards. +1 Buy. — When you gain or trash this, +1 Coffers and +1 Villager."

def _silk_merchant(game, pid):
    E.draw(game, pid, 2)          # not final: the +1 Buy follows it
    E.add_buys(game, 1)


def _silk_merchant_bonus(game, pid, frame, choice):
    # Both mats persist, so this is real even on an opponent's turn (your Silk
    # Merchant trashed by a Knight, or gained from a Swindler-class attack).
    E.add_coffers(game, 1, pid)
    E.add_villagers(game, 1, pid)


# --- Old Witch ($5, Attack) --------------------------------------------------
# "+3 Cards. Each other player gains a Curse and may trash a Curse from their
# hand."

def _old_witch(game, pid):
    E.draw(game, pid, 3)          # not final: the attack follows it
    E.attack_opponents(game, pid, "Old Witch", "hit")


def _old_witch_hit(game, pid, frame, choice):
    # Park the trash offer FIRST so it sits BELOW whatever the Curse gain
    # pushes: "the when-gain abilities might make them draw before they trash",
    # so the gain (and its abilities) resolve, and only then the may-trash.
    # Parked unconditionally, because "if the Curse pile is empty, the other
    # players may still trash a Curse".
    E.push_auto(game, pid, "Old Witch", "may_trash")
    E.gain(game, pid, "Curse")


def _old_witch_may_trash(game, pid, frame, choice):
    if "Curse" in _hand(game, pid):
        E.push_choose_cards(game, pid, "Old Witch", "trash", ["Curse"],
                            0, 1, "trash")


def _old_witch_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, choice["cards"])


# --- Recruiter ($5) ----------------------------------------------------------
# "+2 Cards. Trash a card from your hand. +1 Villager per $1 it costs."

def _recruiter(game, pid):
    E.draw(game, pid, 2)          # not final: the trash follows it
    hand = _hand(game, pid)
    if hand:
        E.push_choose_cards(game, pid, "Recruiter", "trash", list(hand),
                            1, 1, "trash")


def _recruiter_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    # the cost is read BEFORE the trash (deviation B3) and the Villagers are
    # parked BELOW it, so the trashed card's own on-trash ability goes first
    n = E.cost(game, card)
    E.push_auto(game, pid, "Recruiter", "villagers", data={"n": n})
    E.trash(game, pid, [card])


def _recruiter_villagers(game, pid, frame, choice):
    E.add_villagers(game, frame["data"]["n"], pid)


# --- Scholar ($5) ------------------------------------------------------------
# "Discard your hand. +7 Cards."

def _scholar(game, pid):
    # The draw is parked FIRST — below the discard's when-discard triggers
    # (Tunnel/Trail/Weaver), and unconditionally, because "if you don't have
    # any cards in your hand to discard, you still draw 7 cards".
    E.push_auto(game, pid, "Scholar", "draw")
    hand = list(_hand(game, pid))
    if hand:
        E.discard(game, pid, hand)


def _scholar_draw(game, pid, frame, choice):
    E.final_draw(game, pid, 7)    # the draw ENDS the ability


# --- Sculptor ($5) -----------------------------------------------------------
# "Gain a card to your hand costing up to $4. If it's a Treasure, +1 Villager."

def _sculptor(game, pid):
    piles = _gain_piles_up_to(game, 4)
    if piles:
        E.push_choose_pile(game, pid, "Sculptor", "gain", piles=piles)


def _sculptor_gain(game, pid, frame, choice):
    pile = choice["pile"]
    # "'It' refers to the gained card", so the type test is on the card the
    # pile actually yields (an ordered pile gives its top card), and no gain
    # means no Villager.
    card = E.pile_top(game, pile)
    if card is None or not E.gain(game, pid, pile, dest="hand"):
        return
    if E.has_type(game, card, "treasure"):
        E.add_villagers(game, 1, pid)


# --- Spices ($5, Treasure) ---------------------------------------------------
# "$2. +1 Buy. — When you gain this, +2 Coffers."
# The $2 is the printed `coins` in cards.py; only the +1 Buy is an ability.

def _spices(game, pid):
    E.add_buys(game, 1)


def _spices_gain(game, pid, frame, choice):
    E.add_coffers(game, 2, pid)


# --- Swashbuckler ($5) -------------------------------------------------------
# "+3 Cards. If your discard pile has any cards in it: +1 Coffers, then if you
# have at least 4 Coffers tokens, take the Treasure Chest."

def _swashbuckler(game, pid):
    E.draw(game, pid, 3)          # not final: the discard-pile test follows it
    # "If your discard pile is empty AFTER drawing, you do nothing further" —
    # the +3 Cards can shuffle the discard pile away, and then there is none.
    if not game["seats"][pid]["discard"]:
        return
    E.add_coffers(game, 1, pid)
    # ...and the threshold is checked AFTER the +1
    if game["coffers"].get(pid, 0) >= 4:
        E.take_artifact(game, pid, "Treasure Chest")
    # The Treasure Chest's own ability ("at the start of your Buy phase, gain a
    # Gold") lives in half B with the other four Artifacts — Swashbuckler's job
    # ends at taking it.


# --- Villain ($5, Attack) ----------------------------------------------------
# "+2 Coffers. Each other player with 5 or more cards in hand discards one
# costing $2 or more (or reveals they can't)."

def _villain(game, pid):
    E.add_coffers(game, 2, pid)
    E.attack_opponents(game, pid, "Villain", "hit")


def _villain_hit(game, pid, frame, choice):
    hand = _hand(game, pid)
    if len(hand) < 5:
        return
    # "$x or more" reads the COIN component alone (Common Effects: CARD COSTS),
    # which is exactly what cost_ge is
    eligible = sorted({c for c in hand if E.cost_ge(game, c, 2)})
    if not eligible:
        # "or reveals they can't" — the WHOLE hand is revealed, so a Patron in
        # it pays its owner (the word "reveal" is the whole rule)
        E.reveal(game, pid, list(hand), "hand")
        return
    E.push_choose_cards(game, pid, "Villain", "discard", eligible,
                        1, 1, "discard")


def _villain_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


# --- Ducat ($2, Treasure) ----------------------------------------------------
# "+1 Coffers. +1 Buy. — When you gain this, you may trash a Copper from your
# hand."

def _ducat(game, pid):
    E.add_coffers(game, 1, pid)
    E.add_buys(game, 1)


def _ducat_gain(game, pid, frame, choice):
    # optional, and it orders freely against the other abilities the same gain
    # triggered (the ability pool does that for us)
    if "Copper" in _hand(game, pid):
        E.push_choose_cards(game, pid, "Ducat", "trash", ["Copper"],
                            0, 1, "trash")


def _ducat_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, choice["cards"])


# ══ THE PROJECTS ═════════════════════════════════════════════════════════════
#
# A Project has NO buy ability — "this Project's ongoing ability now applies to
# you for the rest of the game" — so none of these is a LANDSCAPE_FX row. Each
# is a TRIGGERS entry with `from:"landscape"`, which the kernel filters to cube
# owners; the default `recipients` ("owner-actor") is what all eight want.

# --- Academy ($5) — "When you gain an Action card, +1 Villager." -------------

def _academy_when(game, pid, ctx):
    return ctx["subject"] is not None and E.has_type(game, ctx["subject"], "action")


def _academy_villager(game, pid, frame, choice):
    E.add_villagers(game, 1, pid)


# --- Guildhall ($5) — "When you gain a Treasure, +1 Coffers." ----------------

def _guildhall_when(game, pid, ctx):
    return ctx["subject"] is not None and E.has_type(game, ctx["subject"], "treasure")


def _guildhall_coffers(game, pid, frame, choice):
    E.add_coffers(game, 1, pid)


# --- Barracks ($6) — "At the start of your turn, +1 Action." -----------------

def _barracks_action(game, pid, frame, choice):
    E.add_actions(game, 1, pid)


# --- Fair ($4) — "At the start of your turn, +1 Buy." ------------------------

def _fair_buy(game, pid, frame, choice):
    E.add_buys(game, 1, pid)


# --- Cathedral ($3) ----------------------------------------------------------
# "At the start of your turn, trash a card from your hand."

def _cathedral_trash(game, pid, frame, choice):
    # "Trashing is of course not optional" — min 1, not 0. With an empty hand
    # there is nothing to offer and nothing happens.
    hand = _hand(game, pid)
    if hand:
        E.push_choose_cards(game, pid, "Cathedral", "do", list(hand),
                            1, 1, "trash")


def _cathedral_do(game, pid, frame, choice):
    E.trash(game, pid, choice["cards"])


# --- Crop Rotation ($6) ------------------------------------------------------
# "At the start of your turn, you may discard a Victory card for +2 Cards."

def _crop_rotation_offer(game, pid, frame, choice):
    victories = sorted({c for c in _hand(game, pid)
                        if E.has_type(game, c, "victory")})
    if victories:
        E.push_choose_cards(game, pid, "Crop Rotation", "do", victories,
                            0, 1, "discard")


def _crop_rotation_do(game, pid, frame, choice):
    if not choice["cards"]:
        return
    # the draw is parked BELOW the discard's when-discard triggers (Tunnel)
    E.push_auto(game, pid, "Crop Rotation", "draw")
    E.discard(game, pid, choice["cards"])


def _crop_rotation_draw(game, pid, frame, choice):
    E.final_draw(game, pid, 2)    # the draw ENDS the ability


# --- Silos ($4) --------------------------------------------------------------
# "At the start of your turn, discard any number of Coppers, revealed, and draw
# that many cards."

def _silos_offer(game, pid, frame, choice):
    n = _hand(game, pid).count("Copper")
    if n:
        E.push_choose_cards(game, pid, "Silos", "do", ["Copper"] * n,
                            0, n, "discard")


def _silos_do(game, pid, frame, choice):
    picked = choice["cards"]
    if not picked:
        return
    E.push_auto(game, pid, "Silos", "draw", data={"n": len(picked)})
    # "revealed" is the card's own word, so it goes through E.reveal — a Patron
    # cannot be one of these, but the discipline is the rule, not the card
    E.reveal(game, pid, list(picked), "Silos")
    E.discard(game, pid, picked)


def _silos_draw(game, pid, frame, choice):
    E.final_draw(game, pid, frame["data"]["n"])   # the draw ENDS the ability


# --- Pageant ($3) ------------------------------------------------------------
# "At the end of your Buy phase, you may pay $1 for +1 Coffers."

def _pageant_when(game, pid, ctx):
    # "If you have at least $1 in your money pool, you may pay $1" — with none,
    # there is no choice to make and no prompt to open
    return game["coins"] >= 1


def _pageant_offer(game, pid, frame, choice):
    E.push_choose_option(game, pid, "Pageant", "do", options=[
        {"id": "pay", "label": "Pay $1 for +1 Coffers"},
        {"id": "no", "label": "Don't"}])


def _pageant_do(game, pid, frame, choice):
    if choice["ids"][0] != "pay" or game["coins"] < 1:
        return
    E.add_coins(game, -1, pid)
    E.add_coffers(game, 1, pid)


# ══ registration ═════════════════════════════════════════════════════════════

EFFECTS.update({
    "Acting Troupe": _acting_troupe,
    "Ducat": _ducat,
    "Flag Bearer": _flag_bearer,
    "Hideout": _hideout,
    "Lackeys": _lackeys,
    "Old Witch": _old_witch,
    "Recruiter": _recruiter,
    "Scholar": _scholar,
    "Sculptor": _sculptor,
    "Silk Merchant": _silk_merchant,
    "Spices": _spices,
    "Swashbuckler": _swashbuckler,
    "Villain": _villain,
})

STAGES.update({
    ("Ducat", "gain"): _ducat_gain,
    ("Ducat", "trash"): _ducat_trash,
    ("Flag Bearer", "take"): _flag_bearer_take,
    ("Hideout", "trash"): _hideout_trash,
    ("Hideout", "curse"): _hideout_curse,
    ("Lackeys", "gain"): _lackeys_gain,
    ("Old Witch", "hit"): _old_witch_hit,
    ("Old Witch", "may_trash"): _old_witch_may_trash,
    ("Old Witch", "trash"): _old_witch_trash,
    ("Recruiter", "trash"): _recruiter_trash,
    ("Recruiter", "villagers"): _recruiter_villagers,
    ("Scholar", "draw"): _scholar_draw,
    ("Sculptor", "gain"): _sculptor_gain,
    ("Silk Merchant", "bonus"): _silk_merchant_bonus,
    ("Spices", "gain"): _spices_gain,
    ("Villain", "hit"): _villain_hit,
    ("Villain", "discard"): _villain_discard,
    # the PROJECTS
    ("Academy", "villager"): _academy_villager,
    ("Barracks", "action"): _barracks_action,
    ("Cathedral", "trash"): _cathedral_trash,
    ("Cathedral", "do"): _cathedral_do,
    ("Crop Rotation", "offer"): _crop_rotation_offer,
    ("Crop Rotation", "do"): _crop_rotation_do,
    ("Crop Rotation", "draw"): _crop_rotation_draw,
    ("Fair", "buy"): _fair_buy,
    ("Guildhall", "coffers"): _guildhall_coffers,
    ("Pageant", "offer"): _pageant_offer,
    ("Pageant", "do"): _pageant_do,
    ("Silos", "offer"): _silos_offer,
    ("Silos", "do"): _silos_do,
    ("Silos", "draw"): _silos_draw,
})

TRIGGERS.update({
    # when-GAIN abilities. All four are decision-free and order-independent —
    # a mat token can never change what another pending ability does — so they
    # `commute` and never pollute the what-resolves-first prompt. Ducat's does
    # NOT: it opens a real choice.
    "Lackeys": [{"on": "gain", "from": "self", "stage": "gain",
                 "commutes": True}],
    "Spices": [{"on": "gain", "from": "self", "stage": "gain",
                "commutes": True}],
    "Ducat": [{"on": "gain", "from": "self", "stage": "gain"}],
    # "when you gain OR TRASH this" — two rows, one stage. The trash row reads
    # the same `trash` emit the whole Dark Ages on-trash theme rides.
    "Flag Bearer": [{"on": "gain", "from": "self", "stage": "take",
                     "commutes": True},
                    {"on": "trash", "from": "self", "stage": "take",
                     "commutes": True}],
    "Silk Merchant": [{"on": "gain", "from": "self", "stage": "bonus",
                       "commutes": True},
                      {"on": "trash", "from": "self", "stage": "bonus",
                       "commutes": True}],

    # THE PROJECTS — `from:"landscape"` with the kernel's ownership scoping.
    # `recipients` is left at its "owner-actor" default throughout: every one of
    # these is a "when YOU …" / "at the start of YOUR turn" ability. Academy and
    # Guildhall can still fire on an opponent's turn, because you can gain a
    # card on one (a Swindler replacement, a Masquerade pass-around) — which is
    # exactly what the compendium flags for both.
    "Academy": [{"on": "gain", "from": "landscape", "stage": "villager",
                 "when": _academy_when, "commutes": True}],
    "Guildhall": [{"on": "gain", "from": "landscape", "stage": "coffers",
                   "when": _guildhall_when, "commutes": True}],
    "Barracks": [{"on": "turn_start", "from": "landscape", "stage": "action",
                  "commutes": True}],
    "Fair": [{"on": "turn_start", "from": "landscape", "stage": "buy",
              "commutes": True}],
    # ...and the four that open a decision, so they join the start-of-turn pool
    # as ordinary options (Cathedral x Crop Rotation ordering changes what is
    # still in hand to discard, which is a real choice — p23 §2).
    "Cathedral": [{"on": "turn_start", "from": "landscape", "stage": "trash"}],
    "Crop Rotation": [{"on": "turn_start", "from": "landscape",
                       "stage": "offer"}],
    "Silos": [{"on": "turn_start", "from": "landscape", "stage": "offer"}],
    "Pageant": [{"on": "buy_phase_end", "from": "landscape", "stage": "offer",
                 "when": _pageant_when}],
})


# ============================================================================
# HALF B — the complex half
# ============================================================================
# ══ shared helpers ═══════════════════════════════════════════════════════════

def _piles(game, pred=None):
    """Non-empty SUPPLY piles, optionally filtered. Starting from
    `game["supply"]` is what makes "a card from the Supply" exclude the
    non-supply piles (Spoils, Travellers, Ferryman's extra pile) with no call
    site having to remember."""
    return sorted(n for n in game["supply"]
                  if E.pile_top(game, n) is not None and (pred is None or pred(n)))


def _names(cards):
    """The distinct names of a zone, for a choose_cards offer."""
    return sorted(set(cards))


def _subtract(cards, taken):
    """A MULTISET difference — zones hold NAMES, so "the rest of the three I
    revealed" is not a set operation (two Coppers revealed, one kept)."""
    out = list(cards)
    for c in taken:
        if c in out:
            out.remove(c)
    return out


# ══ BORDER GUARD ($2) ════════════════════════════════════════════════════════
# "+1 Action. Reveal the top 2 cards of your deck. Put one into your hand and
# discard the other. If both were Actions, take the Lantern or Horn."
#
# LANTERN (2019 errata): "Border Guards you play reveal 3 cards and discard 2.
# (It takes all 3 being Actions to take the Horn.)" — "it triggers when you
# play ANY Border Guard instead of changing just your Border Guards", so the
# check is on the PLAYER, not on the card, and a Border Guard played from the
# trash or the Supply by someone else is still modified for its player.
#
# "If you don't have enough cards (after shuffling) to reveal 2 cards (or 3
# with Lantern), you don't take Lantern or Horn. If you only have one card to
# reveal, put it into your hand."

def _border_guard(game, pid):
    E.add_actions(game, 1)
    want = 3 if E.holds_artifact(game, pid, "Lantern") else 2
    moved = E.look_top(game, pid, want)
    if not moved:
        return
    E.reveal(game, pid, list(moved), "deck")
    # PARKED FIRST so LIFO puts the artifact choice UNDER the keep/discard —
    # the card resolves in its printed order ("put one into your hand and
    # discard the other. If both were Actions, take the Lantern or Horn").
    if len(moved) == want and all(E.has_type(game, c, "action") for c in moved):
        E.push_auto(game, pid, "Border Guard", "artifact")
    if len(moved) == 1:
        E.take_aside(game, pid, list(moved), dest="hand")
        return
    E.push_choose_cards(game, pid, "Border Guard", "keep", _names(moved), 1, 1,
                        "put into your hand", data={"cards": list(moved)})


def _border_guard_keep(game, pid, frame, choice):
    card = choice["cards"][0]
    rest = _subtract(frame["data"]["cards"], [card])
    E.take_aside(game, pid, [card], dest="hand")
    if rest:
        # a real discard, not a quiet move — a discarded Tunnel reacts
        E.discard(game, pid, rest, zone="aside", public=True)


def _border_guard_artifact(game, pid, frame, choice):
    """"Either take Lantern or take Horn" — a SEVERAL OPTIONS choice, so a real
    frame. Only artifacts this game keeps available can be taken; a board that
    somehow has a Border Guard without them simply offers nothing."""
    opts = [{"id": n, "label": f"Take the {n}"}
            for n in ("Lantern", "Horn") if n in game["artifacts"]]
    if not opts:
        return
    E.push_choose_option(game, pid, "Border Guard", "take", options=opts)


def _border_guard_take(game, pid, frame, choice):
    E.take_artifact(game, pid, choice["ids"][0])


# ══ CARGO SHIP ($3, Action–Duration) ═════════════════════════════════════════
# "+$2. Once this turn, when you gain a card, you may set it aside face up (on
# this). At the start of your next turn, put it into your hand."
#
# Only cards gained AFTER it was played (the watcher is registered by the
# play); the choice is made AT GAIN TIME; two plays are two independent
# set-asides; and — the ruling that shapes the whole implementation — "Cargo
# Ship is discarded in Clean-up if you haven't set aside any cards", i.e. it
# does NOT stay in play unless it actually caught something.
#
# That is why the watcher is `until="turn_end"` (a this-turn watcher does not
# hold the card on the table) and why the duration fx is registered only when
# a card is really set aside: an entry with no fx and no watchers is "failed to
# set up" and discards normally, which is exactly the printed behaviour.

def _cargo_ship(game, pid):
    E.add_coins(game, 2)
    # Hoard's shape: a per-PLAY watcher, so it is cumulative with a throne
    # room, it survives the Cargo Ship being trashed from play, and it dies
    # with the turn ("ONCE THIS TURN").
    #
    # The HANDLE is captured HERE, during the play, because that is the only
    # moment `_cur_dur` names this physical Cargo Ship. The set-aside happens
    # in a later window (a gain), by which time any number of cards have been
    # played — see engine.duration_handle. Two separate Cargo Ships get two
    # handles and therefore two entries; a throne-roomed one gets two watchers
    # holding the SAME handle, so both set-asides land on the one card.
    E.add_watcher(game, pid, "Cargo Ship", "gain", stage="offer",
                  until="turn_end",
                  data={"used": False, "handle": E.duration_handle(game)})


def _cargo_free_data(game, pid):
    """The live data dict of an unspent Cargo Ship watcher, or None. Per-COPY
    bookkeeping: two Cargo Ships on the table each get their own set-aside, so
    the flag cannot live on the card or on turn_ctx."""
    for data in E.watcher_datas(game, pid, "Cargo Ship"):
        if not data.get("used"):
            return data
    return None


def _cargo_ship_when(game, watcher, ctx):
    """Join-time pool filter: only the owner's OWN gains ("when YOU gain a
    card"), and only while this copy's once-a-turn set-aside is unspent."""
    return (not watcher["data"].get("used")
            and ctx.get("actor") == watcher["owner"]
            and ctx.get("subject") is not None)


def _cargo_zone(game, pid, card):
    """Where the just-gained card landed — a gain's dest is discard, hand or
    deck. None means another ability moved it first, and "cards that are lost
    track of can't be moved"."""
    return E.find_card_zone(game, pid, card, zones=("discard", "hand", "deck"))


def _cargo_ship_offer(game, pid, frame, choice):
    if _cargo_free_data(game, pid) is None:
        return                      # every copy already caught something
    card = frame["data"].get("subject")
    zone = _cargo_zone(game, pid, card)
    if zone is None:
        E.lost_track(game, pid, card, why="it is no longer where it was gained")
        return
    E.push_choose_option(game, pid, "Cargo Ship", "answer",
                         options=[{"id": "yes", "label": f"Set the {card} aside on Cargo Ship"},
                                  {"id": "no", "label": "Don't set it aside"}],
                         data={"card": card})


def _cargo_ship_answer(game, pid, frame, choice):
    if choice["ids"][0] != "yes":
        return
    card = frame["data"]["card"]
    zone = _cargo_zone(game, pid, card)
    if zone is None:
        E.lost_track(game, pid, card, why="it is no longer where it was gained")
        return
    data = _cargo_free_data(game, pid)
    if data is None:
        return
    data["used"] = True
    E.set_aside_duration(game, pid, [card], zone=zone)
    _cargo_register_return(game, pid, card, data.get("handle"))


def _cargo_register_return(game, pid, card, handle):
    """Register "put it into your hand at the start of your next turn".

    THE SET-ASIDE HAPPENS IN A LATER WINDOW THAN THE PLAY, which is why the
    `handle` exists: `add_duration_fx` writes to the entry `_cur_dur` names,
    and every card played since has moved that pointer, so by gain time it no
    longer names this Cargo Ship. Minting a fresh entry would give ONE
    physical card TWO entries, and two entries each discard their card at
    Clean-up — a conjured copy, the ph.-7H `_restore_cur_dur` bug in a new
    place. The handle was captured during the play (see `_cargo_ship`).

    Two set-asides on the SAME physical card (a throne-roomed Cargo Ship, two
    watchers, one handle) pile onto the one return fx rather than adding a
    second, so the returns stay a single list."""
    entry = None
    if handle is not None:
        lst = game["seats"][handle[0]].get("dur_setup", [])
        if handle[1] < len(lst) and lst[handle[1]]["card"] == "Cargo Ship":
            entry = lst[handle[1]]
    if entry is not None:
        for fx in entry["fx"]:
            if fx["stage"] == "return":
                fx["data"]["cards"].append(card)
                return
    E.add_duration_fx(game, pid, "Cargo Ship", "return",
                      data={"cards": [card]}, handle=handle)


def _cargo_ship_return(game, pid, frame, choice):
    have = list(game["seats"][pid]["dur_aside"])
    cards = []
    for c in frame["data"]["cards"]:
        if c in have:               # multiset: two set-aside Coppers are two
            have.remove(c)
            cards.append(c)
    if not cards:
        return
    E.take_dur_aside(game, pid, cards, dest="hand")
    # face UP on the card, so the return is public
    E._log(game, pid, "to_hand", count=len(cards), cards=list(cards))


# ══ EXPERIMENT ($3) ══════════════════════════════════════════════════════════
# "+2 Cards. +1 Action. Return this to its pile. — When you gain this, gain
# another Experiment (that doesn't come with another)."
#
# 2022: "to its PILE", not "to the Supply" — which is what lets it be returned
# to Ferryman's extra pile. A play-without-moving (a throne-room replay, an
# Enchanted play) still gives the bonuses and simply has nothing to return.

def _experiment(game, pid):
    E.draw(game, pid, 2)
    E.add_actions(game, 1)
    E.return_to_pile(game, pid, "Experiment", zone="in_play")


def _experiment_when(game, pid, ctx):
    # Port's marker, verbatim: "when you gain an Experiment due to Experiment's
    # when-gain, the when-gain doesn't trigger again" — otherwise one buy
    # drains the pile. It rides the gain EVENT and not a transient, because the
    # would-gain protocol can park the physical gain long after the call.
    return not ctx.get("experiment_chain")


def _experiment_gain(game, pid, frame, choice):
    E.gain(game, pid, "Experiment", experiment_chain=True)


# ══ IMPROVE ($3) ═════════════════════════════════════════════════════════════
# "+$2. At the start of Clean-up, you may trash an Action card you would
# discard from play this turn, to gain a card costing exactly $1 more than it."
#
# The timing is literally `cleanup_start` (ph. 5H made Clean-up interruptible
# for exactly this class), and the candidate set is `leaving_play` — the
# Herbalist precedent: "you can only choose a card that would be discarded this
# turn, so not a Duration that will stay in play". By the time cleanup_start
# fires, the persisting Durations have already been promoted out of in_play, so
# leaving_play is precisely what is about to hit the discard pile.
#
# "You can choose the Improve itself." Cumulative per play (a throne-roomed
# Improve gets two goes).

def _improve(game, pid):
    E.add_coins(game, 2)
    E.add_watcher(game, pid, "Improve", "cleanup_start", stage="offer",
                  until="turn_end")


def _improve_candidates(game, pid):
    return sorted({c for c in E.leaving_play(game, pid)
                   if E.has_type(game, c, "action")})


def _improve_fires(game, watcher, ctx):
    """Join-time filter — an Improve with nothing to remodel never enters the
    pool, so it can't ask the player to order a no-op against a real ability."""
    return (ctx.get("actor") == watcher["owner"]
            and bool(_improve_candidates(game, watcher["owner"])))


def _improve_offer(game, pid, frame, choice):
    opts = _improve_candidates(game, pid)
    if not opts:
        return
    E.push_choose_cards(game, pid, "Improve", "answer", opts, 0, 1,
                        "trash an Action you would discard from play, to gain "
                        "one costing exactly $1 more")


def _improve_answer(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    if card not in E.leaving_play(game, pid):
        E.lost_track(game, pid, card, "trashed",
                     why="it is no longer being discarded from play")
        return
    # the GAIN is parked FIRST so it sits BELOW everything the trash pushes —
    # "trash …, to gain a card": the trash and its on-trash abilities resolve
    # before the replacement is chosen (ph. 8's Crown bug was this backwards)
    E.push_auto(game, pid, "Improve", "gain", data={"card": card})
    E.trash(game, pid, [card], zone="in_play")


def _improve_gain(game, pid, frame, choice):
    ref = frame["data"]["card"]
    piles = _piles(game, lambda p: E.cost_eq_card(game, p, ref, delta=1))
    if piles:
        E.push_choose_pile(game, pid, "Improve", "gain_pile", piles)


def _improve_gain_pile(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# ══ INVENTOR ($4) ════════════════════════════════════════════════════════════
# "Gain a card costing up to $4, then cards cost $1 less this turn."
#
# ORDER IS THE WHOLE CARD: "card costs are not reduced when you gain the card",
# so the gain (and every when-gain ability it triggers) resolves BEFORE the
# reduction exists. The reduction is Highway's turn-scoped counter — no new
# state — and is cumulative across plays.

def _inventor(game, pid):
    # parked FIRST => resolves AFTER the gain (LIFO)
    E.push_auto(game, pid, "Inventor", "reduce")
    piles = _piles(game, lambda p: E.cost_le(game, p, 4))
    if piles:
        E.push_choose_pile(game, pid, "Inventor", "gain", piles)


def _inventor_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


def _inventor_reduce(game, pid, frame, choice):
    game["turn_ctx"]["bridges"] += 1


# ══ MOUNTAIN VILLAGE ($4) ════════════════════════════════════════════════════
# "+2 Actions. Look through your discard pile and put a card from it into your
# hand; if you can't, +1 Card."
#
# "See NOT OPTIONAL 'IF YOU DO'. If you have any cards in your discard pile,
# you take one of them. You only draw a card if your discard pile is EMPTY."

def _mountain_village(game, pid):
    E.add_actions(game, 2)
    disc = game["seats"][pid]["discard"]
    if not disc:
        E.final_draw(game, pid, 1)      # the draw ENDS the ability
        return
    E.push_choose_cards(game, pid, "Mountain Village", "take", _names(disc), 1, 1,
                        "put into your hand")


def _mountain_village_take(game, pid, frame, choice):
    card = choice["cards"][0]
    if not E.to_hand(game, pid, card, zone="discard"):
        E.lost_track(game, pid, card)


# ══ PATRON ($4, Action–Reaction) ═════════════════════════════════════════════
# "+1 Villager. +$2. — When something causes you to reveal this (using the word
# 'reveal') in an Action phase, +1 Coffers."
#
# THE WORD IS THE WHOLE RULE: "discarding or trashing a Patron does not count
# as revealing it, even though the other players can see it. Revealing your
# hand or discard pile DOES count, since you reveal all cards in it" — which is
# why the kernel emits from `reveal()` and from nowhere else.
#
# 2022: only "during an Action phase (which includes an OPPONENT's Action
# phase)", which kills the old Pursue infinite and means a Buy-phase reveal
# (Loan, Venture) pays nothing. "If you reveal Patron at the start of your
# turn, you're in your Action phase at that point."

def _patron(game, pid):
    E.add_villagers(game, 1, pid)
    E.add_coins(game, 2)


def _patron_when(game, pid, ctx):
    # the TURN's phase, whoever's turn it is
    return game["phase"] == "action"


def _patron_reveal(game, pid, frame, choice):
    E.add_coffers(game, 1, pid)


# ══ PRIEST ($4) ══════════════════════════════════════════════════════════════
# "+$2. Trash a card from your hand. For the rest of this turn, when you trash
# a card, +$2."
#
# EFFECTS ARE IMMEDIATE, twice over: Priest's OWN trash precedes the ongoing
# ability, so it pays nothing, and a Sewers trash chained off that trash
# precedes it too. A SECOND Priest's trash IS paid by the first one's watcher.
# That ordering is why the watcher is armed by a continuation parked UNDER the
# trash frame rather than in on_play — and the arm still happens when your hand
# is empty, because the third line is not conditional on the second.

def _priest(game, pid):
    E.add_coins(game, 2)
    # parked FIRST => armed AFTER the trash (and after everything the trash
    # itself triggers) resolves
    E.push_auto(game, pid, "Priest", "arm")
    hand = _names(game["seats"][pid]["hand"])
    if hand:
        E.push_choose_cards(game, pid, "Priest", "trash", hand, 1, 1, "trash")


def _priest_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    zone = E.find_card_zone(game, pid, card, zones=("hand",))
    if zone is None:
        E.lost_track(game, pid, card, "trashed")
        return
    E.trash(game, pid, [card], zone="hand")


def _priest_arm(game, pid, frame, choice):
    # cumulative when throned: two plays arm two watchers, so a later trash
    # pays +$4
    E.add_watcher(game, pid, "Priest", "trash", stage="pay", until="turn_end",
                  commutes=True)


def _priest_fires(game, watcher, ctx):
    """"when YOU trash a card" — the owner's trashes only. It fires on a SUPPLY
    trash too (Gladiator, Lurker, Salt the Earth), which is why
    `trash_from_supply` emits."""
    return ctx.get("actor") == watcher["owner"]


def _priest_pay(game, pid, frame, choice):
    if frame["data"].get("actor") != pid:
        return
    E.add_coins(game, 2, pid)


# ══ RESEARCH ($4, Action–Duration) ═══════════════════════════════════════════
# "+1 Action. Trash a card from your hand. Per $1 it costs, set aside a card
# from your deck face down (on this). At the start of your next turn, put those
# cards into your hand."
#
# "If you trash a card that costs $0, or you don't have any cards in your deck
# to set aside, the Research doesn't stay in play" — which falls out for free:
# the fx is registered only when cards were actually set aside, and an entry
# that registered nothing is discarded normally. Cost reductions shrink the
# count (`cost()`, never the printed value).
#
# Unlike Cargo Ship the set-aside happens in a LATER STAGE OF THE SAME PLAY, so
# `_cur_dur` still names this Research's entry and add_duration_fx lands right.

def _research(game, pid):
    E.add_actions(game, 1)
    hand = _names(game["seats"][pid]["hand"])
    if not hand:
        return
    E.push_choose_cards(game, pid, "Research", "trash", hand, 1, 1, "trash")


def _research_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    zone = E.find_card_zone(game, pid, card, zones=("hand",))
    if zone is None:
        E.lost_track(game, pid, card, "trashed")
        return
    n = E.cost(game, card)          # read BEFORE the trash (deviation B3)
    E.trash(game, pid, [card], zone="hand")
    if n <= 0:
        return
    moved = E.look_top(game, pid, n)
    if not moved:
        return
    E.set_aside_duration(game, pid, list(moved), zone="aside")
    E.add_duration_fx(game, pid, "Research", "return", data={"cards": list(moved)})


def _research_return(game, pid, frame, choice):
    have = list(game["seats"][pid]["dur_aside"])
    cards = []
    for c in frame["data"]["cards"]:
        if c in have:
            have.remove(c)
            cards.append(c)
    if not cards:
        return
    E.take_dur_aside(game, pid, cards, dest="hand")
    # set aside FACE DOWN, so only its owner ever saw what they were
    E._log(game, pid, "to_hand", count=len(cards), cards=list(cards),
           private_to=[pid])


# ══ SCEPTER ($5, Treasure–Command) ═══════════════════════════════════════════
# "Choose one: +$2; or replay a non-Command Action card you played this turn
# that's still in play."
#
# 2024 (with Rising Sun): Scepter became a COMMAND card and may only replay
# NON-Command cards, "to prevent you from using Scepter to replay itself
# infinitely when Enlightenment is active".
#
# "'Still in play' means the Action card can't have left play after you played
# it, EVEN IF IT HAS ENTERED PLAY AGAIN" — a called Royal Carriage or a
# Duplicate is out. `turn_ctx["played_actions"]` is the names in play order and
# `in_play` is what is still on the table; the intersection is the answer, and
# it deliberately includes a card that is still RESOLVING ("Scepter can replay
# a card that isn't finished being resolved yet" — a Storyteller that played
# this Scepter is a legal target). Multiple Scepters may replay the same card
# repeatedly: nothing is marked.

def _scepter(game, pid):
    E.push_choose_option(game, pid, "Scepter", "mode", options=[
        {"id": "coins", "label": "+$2"},
        {"id": "replay", "label": "Replay an Action you played this turn"}])


def _scepter_targets(game, pid):
    out = []
    for name in game["turn_ctx"]["played_actions"]:
        # "Still in play" means CONTINUOUSLY in play — a Royal Carriage or
        # Duplicate played and then called the same turn left play, and "you
        # still can't replay it with Scepter" even though it is back on the
        # table (Scepter 5). Presence alone cannot say that.
        if name in out or E.continuously_in_play(game, pid, name) <= 0:
            continue
        if not E.has_type(game, name, "action"):
            continue
        if E.has_type(game, name, "command"):       # the 2024 exclusion
            continue
        out.append(name)
    return sorted(out)


def _scepter_mode(game, pid, frame, choice):
    if choice["ids"][0] == "coins":
        E.add_coins(game, 2)
        return
    targets = _scepter_targets(game, pid)
    if not targets:
        return
    E.push_choose_cards(game, pid, "Scepter", "replay", targets, 1, 1, "replay")


def _scepter_replay(game, pid, frame, choice):
    card = choice["cards"][0]
    if card not in game["seats"][pid]["in_play"]:
        E.lost_track(game, pid, card, "played")
        return
    E.play_action_card(game, pid, card, from_zone=None)


# ══ SEER ($5) ════════════════════════════════════════════════════════════════
# "+1 Card. +1 Action. Reveal the top 3 cards of your deck. Put the ones
# costing from $2 to $4 into your hand. Put the rest back in any order."
#
# The range is TWO different rules (see deviation A5): the $4 ceiling is the
# full cost VECTOR, so a {$3,P} or {$3,3D} card is out; the $2 floor reads the
# COIN COMPONENT alone, exactly as "costing $x or more" does everywhere else.
# `cost_le` and `cost_ge` already encode both.

def _seer(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    moved = E.look_top(game, pid, 3)
    if not moved:
        return
    E.reveal(game, pid, list(moved), "deck")
    keep = [c for c in moved
            if E.cost_ge(game, c, 2) and E.cost_le(game, c, 4)]
    if keep:
        E.take_aside(game, pid, keep, dest="hand")
    rest = _subtract(moved, keep)
    if len(rest) >= 2:
        E.push_order_cards(game, pid, "Seer", "order", cards=rest)
    elif rest:
        E.deck_from_aside(game, pid, rest)


def _seer_order(game, pid, frame, choice):
    E.deck_from_aside(game, pid, choice["order"])   # order[0] ends up on top


# ══ TREASURER ($5) ═══════════════════════════════════════════════════════════
# "+$3. Choose one: Trash a Treasure from your hand; or gain a Treasure from
# the trash to your hand; or take the Key."
#
# The middle option "is GAINED TO YOUR HAND", so when-gain abilities fire, and
# "it's possible to gain non-Kingdom Treasures from the trash, and Treasures
# with Potion or Debt in their cost".

def _treasurer(game, pid):
    E.add_coins(game, 3)
    E.push_choose_option(game, pid, "Treasurer", "mode", options=[
        {"id": "trash", "label": "Trash a Treasure from your hand"},
        {"id": "recover", "label": "Gain a Treasure from the trash to your hand"},
        {"id": "key", "label": "Take the Key"}])


def _treasurer_mode(game, pid, frame, choice):
    pick = choice["ids"][0]
    if pick == "key":
        if "Key" in game["artifacts"]:
            E.take_artifact(game, pid, "Key")
        return
    if pick == "trash":
        opts = sorted({c for c in game["seats"][pid]["hand"]
                       if E.has_type(game, c, "treasure")})
        if opts:
            E.push_choose_cards(game, pid, "Treasurer", "trash", opts, 1, 1, "trash")
        return
    opts = sorted({c for c in game["trash"] if E.has_type(game, c, "treasure")})
    if opts:
        E.push_choose_cards(game, pid, "Treasurer", "recover", opts, 1, 1,
                            "gain to your hand")


def _treasurer_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    zone = E.find_card_zone(game, pid, card, zones=("hand",))
    if zone is None:
        E.lost_track(game, pid, card, "trashed")
        return
    E.trash(game, pid, [card], zone="hand")


def _treasurer_recover(game, pid, frame, choice):
    E.gain_from_trash(game, pid, choice["cards"][0], dest="hand")


# ══ THE ARTIFACTS ════════════════════════════════════════════════════════════
# "There is only one copy of each Artifact… you take the Artifact card from
# another player if they have it. State and Artifact cards never belong to any
# player and are never considered to be in play."
#
# LANTERN has no trigger — it is read inside Border Guard's own effect. FLAG
# has none either: it is one clause on the Clean-up hand count, in the kernel.

# --- Key ---------------------------------------------------------------------
# "At the start of your turn, +$1." The money pool "remains until the end of
# your turn", so it is still there in the Buy phase.

def _key_coin(game, pid, frame, choice):
    E.add_coins(game, 1, pid)


# --- Treasure Chest ----------------------------------------------------------
# "At the start of your Buy phase, gain a Gold." Fires again after a Villa
# re-entrance, which its own entry says is correct (it names Cavalry,
# Continue, Launch and Villa). Half A's Swashbuckler only TAKES it.

def _treasure_chest_gold(game, pid, frame, choice):
    E.gain(game, pid, "Gold")


# --- Horn --------------------------------------------------------------------
# "Once per turn, when you discard a Border Guard from play, you may put it
# onto your deck." Scheme's exact seam (`cleanup_discard`, fired before
# anything has moved) plus a holder check and the per-turn flag: "you may only
# put ONE Border Guard onto your deck each turn with Horn".

def _horn_when(game, pid, ctx):
    return (ctx.get("subject") == "Border Guard"
            and not game["turn_ctx"]["horn_used"])


def _horn_offer(game, pid, frame, choice):
    if game["turn_ctx"]["horn_used"]:
        return          # a second Border Guard in the same batch: no prompt
    if "Border Guard" not in E.leaving_play(game, pid):
        E.lost_track(game, pid, "Border Guard")
        return
    E.push_choose_option(game, pid, "Horn", "answer", options=[
        {"id": "yes", "label": "Put the Border Guard onto your deck"},
        {"id": "no", "label": "Leave it in the discard"}])


def _horn_answer(game, pid, frame, choice):
    if choice["ids"][0] != "yes" or game["turn_ctx"]["horn_used"]:
        return
    if not E.topdeck_from_play(game, pid, "Border Guard"):
        E.lost_track(game, pid, "Border Guard")
        return
    game["turn_ctx"]["horn_used"] = True


# ══ THE PROJECTS ═════════════════════════════════════════════════════════════
# "A Project's ability is active for players who have a Project cube on the
# card" — `from:"landscape"` with ownership scoping, which the kernel resolves
# through `project_owned`. Nothing here is bought-time work: a Project buy runs
# no LANDSCAPE_FX at all (that registry is an Event's one-shot ability).

# --- Sewers ($3) -------------------------------------------------------------
# "When you trash a card other than with this, you may trash a card from your
# hand." Once PER CARD of a batch trash (a Chapel trashing 4 offers up to 4,
# each resolved in the concurrent-abilities pool alongside the trashed cards'
# own on-trash abilities); on opponents' turns; and on SUPPLY trashes.
#
# "OTHER THAN WITH THIS" is a re-entrancy rule, and it rides `trash(**extra)`
# — the twin of `gain(**extra)`, which is how Port marks its own gain, added
# to the kernel for this card (Kernel v9). A mark on the EVENT rather than a
# transient on the game dict is what makes it correct: the emit's pool can
# resolve long after the `trash()` call returned.

def _sewers_when(game, pid, ctx):
    return (not ctx.get("sewers")
            and bool(game["seats"][pid]["hand"]))


def _sewers_offer(game, pid, frame, choice):
    hand = _names(game["seats"][pid]["hand"])
    if not hand:
        return
    E.push_choose_cards(game, pid, "Sewers", "answer", hand, 0, 1,
                        "trash a card from your hand")


def _sewers_answer(game, pid, frame, choice):
    if not choice["cards"]:
        return                      # "if you fail to trash, it doesn't trigger"
    card = choice["cards"][0]
    zone = E.find_card_zone(game, pid, card, zones=("hand",))
    if zone is None:
        E.lost_track(game, pid, card, "trashed")
        return
    # `sewers=True` rides the event so this trash cannot re-trigger Sewers —
    # "other than with this". Without the mark it chains until the hand is
    # empty.
    E.trash(game, pid, [card], zone="hand", sewers=True)


# --- Academy-class helpers ---------------------------------------------------

def _exploration_when(game, pid, ctx):
    """"if you didn't gain any cards during it" — the count from THE EVENT.
    `buy_gains` counts per BUY PHASE, so a Villa re-entry is judged on its own
    phase ("Exploration triggers each time, checking the Buy phase that just
    ended", Exploration 4) — and the live counter is reset for that next phase
    before this pool resolves, so reading it here would answer about the wrong
    phase. `.get` fallback: expand/contract for a frame parked pre-deploy."""
    return not ctx.get("buy_gains", game["turn_ctx"]["buy_gains"])


def _exploration_take(game, pid, frame, choice):
    if frame["data"].get("buy_gains", game["turn_ctx"]["buy_gains"]):
        return
    E.add_coffers(game, 1, pid)
    E.add_villagers(game, 1, pid)


# --- Road Network ($5) -------------------------------------------------------
# "When ANOTHER player gains a Victory card, +1 Card." The one Project whose
# recipients are not the actor: every OTHER cube owner draws, mid-resolution if
# need be.

def _road_network_when(game, pid, ctx):
    return ctx.get("subject") is not None \
        and E.has_type(game, ctx["subject"], "victory")


def _road_network_draw(game, pid, frame, choice):
    E.final_draw(game, pid, 1)


# --- City Gate ($3) ----------------------------------------------------------
# "At the start of your turn, +1 Card, then put a card from your hand onto your
# deck." A plain draw, NOT final_draw: work follows it.

def _city_gate_start(game, pid, frame, choice):
    E.draw(game, pid, 1)
    hand = _names(game["seats"][pid]["hand"])
    if not hand:
        return
    E.push_choose_cards(game, pid, "City Gate", "topdeck", hand, 1, 1,
                        "put onto your deck")


def _city_gate_topdeck(game, pid, frame, choice):
    card = choice["cards"][0]
    zone = E.find_card_zone(game, pid, card, zones=("hand",))
    if zone is None:
        E.lost_track(game, pid, card)
        return
    E.topdeck(game, pid, card, zone="hand")


# --- Sinister Plot ($4) ------------------------------------------------------
# "At the start of your turn, add a token here, or remove your tokens here for
# +1 Card each." The tokens are the per-player landscape store; the take
# removes ALL of yours.

def _sinister_plot_start(game, pid, frame, choice):
    n = E.landscape_tokens(game, "Sinister Plot", pid)
    E.push_choose_option(game, pid, "Sinister Plot", "answer", options=[
        {"id": "add", "label": "Add a token to Sinister Plot"},
        {"id": "take", "label": f"Remove your {n} token(s) for +{n} Card(s)"}])


def _sinister_plot_answer(game, pid, frame, choice):
    if choice["ids"][0] == "add":
        E.add_landscape_tokens(game, "Sinister Plot", pid)
        return
    n = E.take_landscape_tokens(game, "Sinister Plot", pid)
    if n:
        E.final_draw(game, pid, n)      # the draw ENDS the ability


# --- Piazza ($5) -------------------------------------------------------------
# "At the start of your turn, reveal the top card of your deck. If it's an
# Action, play it." NOT optional; a non-Action goes back on top.

def _piazza_start(game, pid, frame, choice):
    moved = E.look_top(game, pid, 1)
    if not moved:
        return
    card = moved[0]
    E.reveal(game, pid, [card], "deck")
    if E.has_type(game, card, "action"):
        E.play_action_card(game, pid, card, from_zone="aside")
    else:
        E.deck_from_aside(game, pid, [card])


# --- Innovation ($6) ---------------------------------------------------------
# "Once during each of your turns, when you gain an Action card, you may play
# it." 2022: ANY qualifying gain, not just the first one — but only once a
# turn, and only on YOUR turn ("if you gain an Action card during an opponent's
# turn, Innovation doesn't trigger").
#
# The card is played from wherever it was gained, and the 2021 expanded
# lose-track rule replaced the old "set aside" clause: "if you move it with
# another ability first, Innovation can't play it".

def _innovation_when(game, pid, ctx):
    return (pid == game["turn"]
            and not game["turn_ctx"]["innovation_used"]
            and ctx.get("subject") is not None
            and E.has_type(game, ctx["subject"], "action"))


def _innovation_offer(game, pid, frame, choice):
    if game["turn_ctx"]["innovation_used"]:
        return
    card = frame["data"].get("subject")
    if E.find_card_zone(game, pid, card, zones=("discard", "hand", "deck")) is None:
        E.lost_track(game, pid, card, "played")
        return
    E.push_choose_option(game, pid, "Innovation", "answer", options=[
        {"id": "yes", "label": f"Play the {card}"},
        {"id": "no", "label": "Don't play it"}], data={"card": card})


def _innovation_answer(game, pid, frame, choice):
    if choice["ids"][0] != "yes" or game["turn_ctx"]["innovation_used"]:
        return
    card = frame["data"]["card"]
    zone = E.find_card_zone(game, pid, card, zones=("discard", "hand", "deck"))
    if zone is None:
        E.lost_track(game, pid, card, "played")
        return
    # DECLINING does not spend the once-a-turn use — the flag counts uses of
    # the ability, not triggers of it (a judgement call: see the batch report)
    game["turn_ctx"]["innovation_used"] = True
    E.play_action_card(game, pid, card, from_zone=zone)


# --- Citadel ($8) ------------------------------------------------------------
# "The first time you play an Action card during each of your turns, replay it
# afterwards." 2021 changed this to playing the card twice and 2022 CHANGED IT
# BACK, so the current card rides `action_resolved`: "you replay the Action
# card after having resolved its play ability".
#
# The target is `played_actions[0]` — "a card is considered played even before
# it's resolved", so a before-play reaction that plays another card first (a
# Caravan Guard) does NOT steal the slot even though it finishes resolving
# first. It is NOT triggered by calling a Reserve or by a Duration's later
# ability: only by a PLAY, which is exactly what emits `action_resolved`.

def _citadel_when(game, pid, ctx):
    return (pid == game["turn"]
            and not game["turn_ctx"]["citadel_used"]
            and not ctx.get("replay")
            and game["turn_ctx"]["played_actions"][:1] == [ctx.get("subject")])


def _citadel_replay(game, pid, frame, choice):
    if game["turn_ctx"]["citadel_used"]:
        return
    card = frame["data"].get("subject")
    if card not in game["seats"][pid]["in_play"]:
        E.lost_track(game, pid, card, "played")
        return
    game["turn_ctx"]["citadel_used"] = True     # set BEFORE the replay
    E.play_action_card(game, pid, card, from_zone=None)


# ══ registries ═══════════════════════════════════════════════════════════════

EFFECTS.update({
    "Border Guard": _border_guard,
    "Cargo Ship": _cargo_ship,
    "Experiment": _experiment,
    "Improve": _improve,
    "Inventor": _inventor,
    "Mountain Village": _mountain_village,
    "Patron": _patron,
    "Priest": _priest,
    "Research": _research,
    "Scepter": _scepter,
    "Seer": _seer,
    "Treasurer": _treasurer,
})

STAGES.update({
    ("Border Guard", "keep"): _border_guard_keep,
    ("Border Guard", "artifact"): _border_guard_artifact,
    ("Border Guard", "take"): _border_guard_take,
    ("Cargo Ship", "offer"): _cargo_ship_offer,
    ("Cargo Ship", "answer"): _cargo_ship_answer,
    ("Cargo Ship", "return"): _cargo_ship_return,
    ("Experiment", "gain"): _experiment_gain,
    ("Improve", "offer"): _improve_offer,
    ("Improve", "answer"): _improve_answer,
    ("Improve", "gain"): _improve_gain,
    ("Improve", "gain_pile"): _improve_gain_pile,
    ("Inventor", "gain"): _inventor_gain,
    ("Inventor", "reduce"): _inventor_reduce,
    ("Mountain Village", "take"): _mountain_village_take,
    ("Patron", "coffers"): _patron_reveal,
    ("Priest", "trash"): _priest_trash,
    ("Priest", "arm"): _priest_arm,
    ("Priest", "pay"): _priest_pay,
    ("Research", "trash"): _research_trash,
    ("Research", "return"): _research_return,
    ("Scepter", "mode"): _scepter_mode,
    ("Scepter", "replay"): _scepter_replay,
    ("Seer", "order"): _seer_order,
    ("Treasurer", "mode"): _treasurer_mode,
    ("Treasurer", "trash"): _treasurer_trash,
    ("Treasurer", "recover"): _treasurer_recover,
    # artifacts
    ("Key", "coin"): _key_coin,
    ("Treasure Chest", "gold"): _treasure_chest_gold,
    ("Horn", "offer"): _horn_offer,
    ("Horn", "answer"): _horn_answer,
    # projects
    ("Sewers", "offer"): _sewers_offer,
    ("Sewers", "answer"): _sewers_answer,
    ("Exploration", "take"): _exploration_take,
    ("Road Network", "draw"): _road_network_draw,
    ("City Gate", "start"): _city_gate_start,
    ("City Gate", "topdeck"): _city_gate_topdeck,
    ("Sinister Plot", "start"): _sinister_plot_start,
    ("Sinister Plot", "answer"): _sinister_plot_answer,
    ("Piazza", "start"): _piazza_start,
    ("Innovation", "offer"): _innovation_offer,
    ("Innovation", "answer"): _innovation_answer,
    ("Citadel", "replay"): _citadel_replay,
})

TRIGGERS.update({
    "Experiment": [{"on": "gain", "from": "self", "stage": "gain",
                    "when": _experiment_when}],
    "Patron": [{"on": "reveal", "from": "self", "stage": "coffers",
                "commutes": True, "when": _patron_when}],
    # --- artifacts (the holder's own ability; `from:"artifact"`) ---
    "Key": [{"on": "turn_start", "from": "artifact", "stage": "coin",
             "commutes": True}],
    "Treasure Chest": [{"on": "buy_phase_start", "from": "artifact",
                        "stage": "gold"}],
    "Horn": [{"on": "cleanup_discard", "from": "artifact", "stage": "offer",
              "when": _horn_when}],
    # --- projects (`from:"landscape"`, scoped to cube owners) ---
    "Sewers": [{"on": "trash", "from": "landscape", "stage": "offer",
                "when": _sewers_when}],
    "Exploration": [{"on": "buy_phase_end", "from": "landscape", "stage": "take",
                     "commutes": True, "when": _exploration_when}],
    "Road Network": [{"on": "gain", "from": "landscape",
                      "recipients": "owners-not-actor", "stage": "draw",
                      "commutes": True, "when": _road_network_when}],
    "City Gate": [{"on": "turn_start", "from": "landscape", "stage": "start"}],
    "Sinister Plot": [{"on": "turn_start", "from": "landscape", "stage": "start"}],
    "Piazza": [{"on": "turn_start", "from": "landscape", "stage": "start"}],
    "Innovation": [{"on": "gain", "from": "landscape", "stage": "offer",
                    "when": _innovation_when}],
    "Citadel": [{"on": "action_resolved", "from": "landscape", "stage": "replay",
                 "when": _citadel_when}],
})

WATCHER_WHENS.update({
    ("Cargo Ship", "offer"): _cargo_ship_when,
    ("Improve", "offer"): _improve_fires,
    ("Priest", "pay"): _priest_fires,
})

# Scepter pushes a real decision frame, so play_all_treasures must skip it.
MANUAL_TREASURES.add("Scepter")
