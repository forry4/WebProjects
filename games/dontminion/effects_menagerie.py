"""MENAGERIE (phase 10) — 30 kingdom piles + the Horse pile + 20 Events + the
first 20 WAYS.

Written against **Kernel v10**, frozen in `games/dontminion/CLAUDE.md`.

THE TWO BATCH HALVES ARE CONCATENATED HERE, registries declared ONCE at the top
and each half only ever `.update()`-ing into them. Half A is the cards whose
interest is their own play ability plus all 20 Events; half B is the 20 Ways,
the Reactions that play themselves, the Attacks, the Durations and the two
Treasures. The section banners below mark the seam.

**The merge is not a copy-paste, and this set proved why.** Half B declared
`MANUAL_TREASURES = {"Stockpile"}` — a REBIND, which in one file silently drops
half A's Supplies and hands the autoplay button a Treasure that gains a card
mid-bulk-play. Both halves also defined `_hand` and `_supply_piles`; those
turned out to be behaviourally identical (only the docstrings differed) and
half A's were kept, but that was checked rather than assumed. Any future merge
owes the same two checks: every registry write must be `.update()`/`.add()`,
and every top-level name defined by both halves must be compared BODY-first.

WHAT THIS SET ADDS TO THE GAME, in the order the rules force:

  * **EXILE** — an owned, public, SCORING zone that sits outside the
    gain/discard economy in one direction only. 14 objects use it, plus the
    mat's own all-or-nothing when-gain ability, which is not on any card.
  * **WAYS** — a `would_resolve` consumer (the Enchantress class), so every
    Action play stops to ask. Six of the twenty say "this", which means THE
    PLAYED ACTION CARD and never the Way (ch. IV WAYS).
  * **HORSES** — a non-Supply pile of 30 that 12 objects feed from.
  * Three 2025 errata that change code: **Gamble** discards first and plays out
    of the discard pile, **Reap** gains its Gold straight to the set-aside
    area, and **Way of the Mouse**'s card may no longer be a Duration.

The per-card rulings are the Knutsen compendium v11.1 ch. VII, cited inline.
"""

from . import engine as E

EFFECTS = {}
STAGES = {}
TRIGGERS = {}
COST_MODS = {}
DYN_COSTS = {}
COST_OVERRIDE = {}
BUY_PAY_ALT = {}
BUY_GATES = {}
MANUAL_TREASURES = set()
AUTOPLAY_LAST = set()
ATTACK_REACTIONS = {}
WATCHER_WHENS = {}
LANDSCAPE_FX = {}
LANDSCAPE_SCORING = {}
LANDSCAPE_SETUP = {}


# ==========================================================================
# HALF A — the cards whose interest is their own play ability, and the
#          20 Events.
# ==========================================================================

# ══ shared helpers ═══════════════════════════════════════════════════════════

def _hand(game, pid):
    return game["seats"][pid]["hand"]


def _supply_piles(game, pred=None):
    """Non-empty SUPPLY piles, sorted. Starting from `game["supply"]` is what
    keeps a NON-Supply pile (the Horse pile, Spoils, a Traveller, Ferryman's
    extra pile) out by construction — "gain a card from the Supply" excludes
    them with no call site to remember (the ph.-3H pile model)."""
    return [p for p in sorted(game["supply"])
            if E.pile_top(game, p) is not None and (pred is None or pred(p))]


def _gain_piles_up_to(game, coins):
    """"…costing up to $N". `cost_le` is what keeps a Potion- or Debt-costed
    pile out of an upper bound — never a raw `cost() <= n`."""
    return _supply_piles(game, lambda p: E.cost_le(game, p, coins))


def _action_supply_piles(game):
    """"An Action card from the Supply" (Invest, Transport, Populate).

    Read through the PILE's own identity, not its face: "split piles instead
    follow the Randomizer card" (ph. 8's `pile_has_type`), so a Catapult/Rocks
    pile is an Action pile even with the Rocks showing. Empty piles are
    excluded here — unlike an Adventures token, every consumer of this list
    takes a card off the pile."""
    return [p for p in sorted(game["supply"])
            if E.pile_top(game, p) is not None and E.pile_has_type(game, p, "action")]


def _hand_actions(game, pid):
    return sorted({c for c in _hand(game, pid) if E.has_type(game, c, "action")})


def _seq_gain(game, pid, frame, choice):
    """THE ordered multi-gain runner — "you gain each card in turn and in the
    order given" (Alliance) — shared by every card here that gains a LIST.

    The remainder is parked BELOW the current gain, so everything that gain
    triggers (a when-gain ability, a reaction, the Exile mat's own offer)
    resolves fully before the next one. A plain `for` loop over `E.gain` looks
    equivalent and is not: each gain PARKS its ability pool, so the pools come
    off the stack in reverse and the last card's abilities resolve first.

    An empty pile is skipped, not a stop: "you gain the ones you can, even if
    some piles are empty"."""
    d = frame["data"]
    piles = list(d["piles"])
    pile = piles.pop(0)
    if piles:
        E.push_auto(game, pid, frame["card"], "seq_gain",
                    data={"piles": piles, "dest": d["dest"]})
    E.gain(game, pid, pile, dest=d["dest"])


def _gain_seq(game, pid, card, piles, dest="discard"):
    """Kick off `_seq_gain`. `card` must register ("<card>", "seq_gain")."""
    if piles:
        E.push_auto(game, pid, card, "seq_gain",
                    data={"piles": list(piles), "dest": dest})


def _landscape_watcher(game, pid, name, event, stage, data=None):
    """Register a REST-OF-THE-GAME watcher owned by a LANDSCAPE (Invest).

    This was a KERNEL GAP when the batch found it, and it is now fixed IN THE
    KERNEL rather than worked around here: `add_watcher` mints no duration
    entry when the owner is not a real card. The entry exists for exactly one
    job — keep the PLAYED CARD on the table while its watcher lives — and a
    landscape has no physical card to keep; minting one anyway conjured a card
    into `owned_cards` and the next scoring pass raised on `CARDS["Invest"]`.
    Travelling Fair (ph. 7) escaped it only by being `until="turn_end"`.

    The wrapper stays as the NAME of the requirement — a future landscape
    watcher should call this and inherit the guarantee rather than rediscover
    it — and `test_an_invest_watcher_never_conjures_a_card_into_the_census`
    pins the behaviour end to end from this side of the boundary."""
    E.add_watcher(game, pid, name, event, stage=stage, data=data, until="forever")


# ══ THE HORSE PILE ═══════════════════════════════════════════════════════════

# --- Horse ($3, non-Supply) --------------------------------------------------
# "+2 Cards. +1 Action. Return this to its pile. (This is not in the Supply.)"
# Its cost is $3 "for any ability that refers to its cost" — printed in
# cards.py, so Scrap, Kiln and Wayfarer all read it through `cost()`.

def _horse(game, pid):
    E.add_cards(game, 2, pid)          # not final: the +1 Action follows it
    E.add_actions(game, 1)
    # "This is REMOVED FROM PLAY." — but "if you play Horse WITHOUT MOVING IT
    # INTO PLAY, you still get +2 Cards and +1 Action (Throne Room + Horse will
    # give you +4 Cards and +2 Actions)", so the second play finds nothing on
    # the table and returns nothing. Silent by design, like Adventures'
    # `_to_tavern_if_in_play`: the card is where the player can see it.
    if "Horse" in game["seats"][pid]["in_play"]:
        E.return_to_pile(game, pid, "Horse")


# ══ $2 ═══════════════════════════════════════════════════════════════════════

# --- Supplies ($2, Treasure) -------------------------------------------------
# "$1. Gain a Horse onto your deck." The $1 is the printed `coins` in cards.py
# and the kernel pays it — "you get the initial +$1 even if there are no Horses
# left" falls out of that ordering.
#
# AUTOPLAY BUCKET: **MANUAL_TREASURES**, and the reason is the GAIN, not the $.
# Bucket 1 is "playing it pushes a DECISION frame, which can't be answered
# mid-autoplay", and a gain is the single most-watched occurrence in the game:
# Watchtower's would-gain window, this set's Sleigh/Sheepdog/Falconer, the
# Exile mat's own all-or-nothing offer and Travelling Fair / Way of the Seal's
# topdeck offers all open a prompt on it. `play_all_treasures` is ONE move that
# fires the whole hand in a loop, so a prompt opened halfway through would sit
# under everything played after it. The Horse also lands on the DECK, which is
# the one place a bulk play cannot be un-decided, and "you don't have to play
# all your Treasures" is the card's own escape hatch.

def _supplies(game, pid):
    E.gain_from(game, pid, "Horse", dest="deck")


# ══ $3 ═══════════════════════════════════════════════════════════════════════

# --- Camel Train ($3) --------------------------------------------------------
# "Exile a non-Victory card from the Supply. — When you gain this, Exile a Gold
# from the Supply."

def _camel_train(game, pid):
    piles = _supply_piles(game, lambda p: not E.has_type(game, p, "victory"))
    if piles:
        E.push_choose_pile(game, pid, "Camel Train", "exile", piles)


def _camel_train_exile(game, pid, frame, choice):
    # "Exiling cards from the Supply is not considered gaining cards" — which
    # is `exile(zone="supply")`'s whole job: it takes the pile's top card and
    # emits no `gain`.
    E.exile(game, pid, [choice["pile"]], zone="supply")


def _camel_train_gain(game, pid, frame, choice):
    # Deliberately NOT `commutes`: it takes a card off the Gold pile, which can
    # change what another ability the same gain triggered is able to do.
    E.exile(game, pid, ["Gold"], zone="supply")


# --- Goatherd ($3) -----------------------------------------------------------
# "+1 Action. You may trash a card from your hand. +1 Card per card the player
# to your right trashed on their last turn."

def _goatherd(game, pid):
    E.add_actions(game, 1)
    order = game["players"]
    # "the player to your right" = the seat BEFORE you in turn order (the
    # Smugglers/Monkey precedent, which reads the same neighbour).
    right = order[order.index(pid) - 1]
    # A COUNT, not a card list: "Goatherd counts HOW MANY TIMES your right-hand
    # player trashed a card (so a Fortress trashed twice counts as two)", and
    # "only cards the player trashed during their LAST COMPLETED TURN count".
    n = game["last_turn_trashes"].get(right, 0)
    # the draw is parked BELOW the trash — the card's own order, and it lets
    # the trashed card's on-trash ability resolve first
    E.push_auto(game, pid, "Goatherd", "draw", data={"n": n})
    hand = _hand(game, pid)
    if hand:
        E.push_choose_cards(game, pid, "Goatherd", "trash", sorted(hand),
                            0, 1, "trash")


def _goatherd_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, choice["cards"])


def _goatherd_draw(game, pid, frame, choice):
    E.add_cards(game, frame["data"]["n"], pid, final=True)   # ENDS the ability


# --- Scrap ($3) --------------------------------------------------------------
# "Trash a card from your hand. Choose a different thing per $1 it costs:
#  +1 Card; +1 Action; +1 Buy; +$1; gain a Silver; gain a Horse."

_SCRAP_OPTIONS = [("card", "+1 Card"), ("action", "+1 Action"),
                  ("buy", "+1 Buy"), ("coin", "+$1"),
                  ("silver", "Gain a Silver"), ("horse", "Gain a Horse")]


def _scrap(game, pid):
    hand = _hand(game, pid)
    if hand:
        E.push_choose_cards(game, pid, "Scrap", "trash", sorted(hand),
                            1, 1, "trash")


def _scrap_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    # parked BELOW the trash, so the trashed card's on-trash ability (a
    # Fortress, a Rocks) resolves before the cost is read and the bonuses run.
    # **THE COST IS READ IN THE PARKED STAGE, NOT HERE** — ch. VII Scrap ❖ is
    # explicit about the order: "first trash, THEN CHECK COST, then resolve the
    # bonuses in the order given". That is NOT deviation B3's capture-first
    # shape (Develop/Farmland/Trader), and this set is where the difference
    # became observable: Destrier costs "$1 less per card you've gained this
    # turn", so trashing one while a Market Square is in hand gains a Gold on
    # the trash and Scrap must then see the LOWER cost — one fewer option.
    E.push_auto(game, pid, "Scrap", "pick", data={"card": card})
    E.trash(game, pid, [card])


def _scrap_pick(game, pid, frame, choice):
    # "you get MAXIMUM SIX bonuses, even if the trashed card costs more"; "if
    # there is a COST REDUCTION, Scrap will give you fewer options" falls out
    # of `cost()`, which is asked HERE — after the trash and everything it
    # triggered (see `_scrap_trash`).
    n = min(len(_SCRAP_OPTIONS), E.cost(game, frame["data"]["card"]))
    if n <= 0:
        return
    # "SEVERAL OPTIONS (six) … Pick DIFFERENT options, one per $1 the trashed
    # card costs. It's NOT OPTIONAL: you can't choose to do less." — so an
    # exact-N distinct pick, never a 0..N one.
    E.push_choose_option(game, pid, "Scrap", "do",
                         options=[{"id": k, "label": lab}
                                  for k, lab in _SCRAP_OPTIONS],
                         pick=n, distinct=True)


def _scrap_do(game, pid, frame, choice):
    # "You have to choose the options first, then DO THEM, IN THE ORDER GIVEN"
    # — so the printed order, never the order the ids happened to arrive in.
    picked = set(choice["ids"])
    for key, _label in _SCRAP_OPTIONS:
        if key not in picked:
            continue
        if key == "card":
            E.add_cards(game, 1, pid)
        elif key == "action":
            E.add_actions(game, 1)
        elif key == "buy":
            E.add_buys(game, 1)
        elif key == "coin":
            E.add_coins(game, 1)
        elif key == "silver":
            E.gain(game, pid, "Silver")
        else:
            E.gain_from(game, pid, "Horse")


# --- Snowy Village ($3) ------------------------------------------------------
# "+1 Card. +4 Actions. +1 Buy. Ignore any further +Actions you get this turn."

def _snowy_village(game, pid):
    E.add_cards(game, 1, pid)
    E.add_actions(game, 4)
    E.add_buys(game, 1)
    # "ONLY +Actions you would get AFTER playing Snowy Village are ignored
    # (EFFECTS ARE IMMEDIATE). You keep any Actions you already had" — so the
    # flag is set LAST, after its own +4. From here `add_actions` DROPS every
    # grant (and logs `actions_ignored`), which is also why a spent Villager
    # gives nothing: spending one is "+1 Action" through the same function.
    game["turn_ctx"]["ignore_actions"] = True


# ══ $4 ═══════════════════════════════════════════════════════════════════════

# --- Bounty Hunter ($4) ------------------------------------------------------
# "+1 Action. Exile a card from your hand. If you didn't have a copy of it in
# Exile, +$3."

def _bounty_hunter(game, pid):
    E.add_actions(game, 1)
    hand = _hand(game, pid)
    # "You HAVE TO Exile a card (if you have one in hand)" — min 1, not 0. With
    # an empty hand there is nothing to offer and "if you can't Exile a card,
    # you don't get +$3".
    if hand:
        E.push_choose_cards(game, pid, "Bounty Hunter", "exile", sorted(hand),
                            1, 1, "exile")


def _bounty_hunter_exile(game, pid, frame, choice):
    card = choice["cards"][0]
    # read BEFORE the Exile: the +$3 is for "the only COPY OF THAT CARD you
    # have in Exile", so a Throne Room + Bounty Hunter pays twice only if you
    # Exile a DIFFERENT card each time.
    had = E.on_exile(game, pid, card)
    E.exile(game, pid, [card])
    if not had:
        E.add_coins(game, 3)


# --- Cavalry ($4) ------------------------------------------------------------
# "Gain 2 Horses. — When you gain this, +2 Cards, +1 Buy, and if it's your Buy
# phase return to your Action phase."

def _cavalry(game, pid):
    for _ in range(2):
        E.gain_from(game, pid, "Horse")


def _cavalry_gain(game, pid, frame, choice):
    E.add_cards(game, 2, pid)
    E.add_buys(game, 1, pid)
    # `return_to_action_phase` (ph. 8, Villa) owns the WHOLE rule, and Cavalry
    # is where the compendium states its consequences: you keep the Actions,
    # Buys and $ you had left; start-of-turn abilities do NOT trigger;
    # start-of-BUY-phase abilities (Arena, Treasure Chest) trigger again; and
    # your Buy phase ENDS, so Exploration / Merchant Guild / Treasury / Wine
    # Merchant can trigger several times in a turn — "resolved AFTER drawing 2
    # cards with Cavalry", which is why the emit sits below the +2 Cards.
    # It refuses off-turn and outside the Buy phase by itself: "if you gain
    # Cavalry when it's not your turn, or in your Night or Clean-up phase, the
    # +1 Buy is not usable, and you don't get an Action phase".
    E.return_to_action_phase(game, pid)


# --- Groom ($4) --------------------------------------------------------------
# "Gain a card costing up to $4. If it's an… Action card, gain a Horse;
#  Treasure card, gain a Silver; Victory card, +1 Card and +1 Action."

def _groom(game, pid):
    piles = _gain_piles_up_to(game, 4)
    if piles:
        E.push_choose_pile(game, pid, "Groom", "gain", piles)


_GROOM_BONUS = (("action", "horse"), ("treasure", "silver"), ("victory", "vp"))


def _groom_gain(game, pid, frame, choice):
    pile = choice["pile"]
    # "'It' refers to the GAINED CARD. If you didn't gain the card, you don't
    # get any bonus" — so the types are read off the card the pile actually
    # yields (an ordered pile gives its top card), and no gain means nothing.
    card = E.pile_top(game, pile)
    if card is None:
        return
    # "If you gain a card that has SEVERAL of the types, you get ALL relevant
    # bonuses" and "resolve them IN THE ORDER GIVEN".
    #
    # **EACH BONUS IS PARKED BELOW THE GAIN BEFORE IT** (`_seq_gain`'s rule,
    # applied here rather than rediscovered): "you gain each card in turn, see
    # TRIGGERED ABILITY. Any when-gain ability (like Tracker or Abundance)
    # applied after the first card WILL BE IN EFFECT WHEN YOU GAIN THE NEXT"
    # (Groom 4). A straight-line `gain(); gain_from("Horse"); gain("Silver")`
    # parks three pools that then come off the stack in REVERSE, so the Silver's
    # reactions resolved before the gained card's — a Sleigh was offered for the
    # Silver first and could no longer move the card Groom actually gained.
    left = [b for t, b in _GROOM_BONUS if E.has_type(game, card, t)]
    if left:
        E.push_auto(game, pid, "Groom", "bonus", data={"left": left})
    E.gain(game, pid, pile)


def _groom_bonus(game, pid, frame, choice):
    left = list(frame["data"]["left"])
    if not left:
        return
    kind, rest = left[0], left[1:]
    if rest:
        E.push_auto(game, pid, "Groom", "bonus", data={"left": rest})
    if kind == "horse":
        E.gain_from(game, pid, "Horse")
    elif kind == "silver":
        E.gain(game, pid, "Silver")
    else:
        E.add_cards(game, 1, pid)      # not final: the +1 Action follows it
        E.add_actions(game, 1)


# --- Hostelry ($4) -----------------------------------------------------------
# "+1 Card. +2 Actions. — When you gain this, you may discard any number of
# Treasures, revealed, to gain that many Horses."

def _hostelry(game, pid):
    E.add_cards(game, 1, pid)          # not final: the +2 Actions follow it
    E.add_actions(game, 2)


def _hostelry_gain(game, pid, frame, choice):
    # "You gain the Horses ON WHEN-GAIN", and "when gaining Hostelry you may
    # resolve other when-gain abilities, such as drawing, BEFORE discarding
    # Treasures" — which the ability pool gives us: this is one entry in it.
    treasures = sorted(c for c in _hand(game, pid) if E.has_type(game, c, "treasure"))
    if treasures:
        E.push_choose_cards(game, pid, "Hostelry", "discard", treasures,
                            0, len(treasures), "discard")


def _hostelry_discard(game, pid, frame, choice):
    picked = choice["cards"]
    if not picked:
        return
    # the Horses are parked BELOW the discard's when-discard triggers (Tunnel,
    # Village Green, Weaver)
    E.push_auto(game, pid, "Hostelry", "horses", data={"n": len(picked)})
    # "You REVEAL the Treasures before discarding them" — the word is the whole
    # rule, so it goes through E.reveal (a revealed Patron pays its owner).
    E.reveal(game, pid, list(picked), "Hostelry")
    E.discard(game, pid, picked)


def _hostelry_horses(game, pid, frame, choice):
    for _ in range(frame["data"]["n"]):
        E.gain_from(game, pid, "Horse")


# ══ $5 ═══════════════════════════════════════════════════════════════════════

# --- Displace ($5) -----------------------------------------------------------
# "Exile a card from your hand. Gain a differently named card costing up to $2
# more than it."

def _displace(game, pid):
    hand = _hand(game, pid)
    if hand:
        E.push_choose_cards(game, pid, "Displace", "exile", sorted(hand),
                            1, 1, "exile")


def _displace_exile(game, pid, frame, choice):
    card = choice["cards"][0]
    # the gain prompt is parked BELOW the Exile, so anything the Exile triggers
    # (an opponent's Invest) resolves first and the pile list is built from the
    # board as it stands when the gain actually happens
    E.push_auto(game, pid, "Displace", "pick", data={"ref": card})
    E.exile(game, pid, [card])


def _displace_pick(game, pid, frame, choice):
    ref = frame["data"]["ref"]
    # "costing up to $2 MORE THAN IT" is a card reference, never a number
    # bound: `cost_le_card` is what makes "up to $2 more than {$3,2D}" mean
    # "up to {$5,2D}". "Differently named" is tested against the card the pile
    # would yield.
    piles = _supply_piles(
        game, lambda p: E.pile_top(game, p) != ref and E.cost_le_card(game, p, ref, 2))
    if piles:
        E.push_choose_pile(game, pid, "Displace", "gain", piles)


def _displace_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Fisherman ($5*) ---------------------------------------------------------
# "+1 Card. +1 Action. +$1. — During your turns, if your discard pile is empty,
# this costs $3 less."

def _fisherman(game, pid):
    E.add_cards(game, 1, pid)          # not final: two more grants follow
    E.add_actions(game, 1)
    E.add_coins(game, 1)


def _fisherman_cost(game):
    """A REDUCTION (`DYN_COSTS`), unlike Wayfarer's absolute override.

    Keyed on the TURN player's discard pile — "during YOUR TURNS" — which is
    the Ferry-token signature trick and what lets `cost()` keep its
    two-argument signature. "All Fishermen have the modified cost during your
    turn, including those belonging to other players." And: "remember that when
    you gain a card (for instance through buying it), it's normally placed
    straight in your discard pile", so buying anything at all un-discounts it
    for the rest of the turn."""
    return 3 if not game["seats"][game["turn"]]["discard"] else 0


# --- Hunting Lodge ($5) ------------------------------------------------------
# "+1 Card. +2 Actions. You may discard your hand for +5 Cards."

def _hunting_lodge(game, pid):
    E.add_cards(game, 1, pid)          # not final: the offer follows it
    E.add_actions(game, 2)
    # offered unconditionally — choices are never feasibility-filtered, and an
    # empty hand still draws 5 (the Scholar shape)
    E.push_choose_option(game, pid, "Hunting Lodge", "choose", options=[
        {"id": "discard", "label": "Discard your hand for +5 Cards"},
        {"id": "keep", "label": "Keep your hand"}])


def _hunting_lodge_choose(game, pid, frame, choice):
    if choice["ids"][0] != "discard":
        return
    # the draw is parked FIRST — below the discard's when-discard triggers —
    # and unconditionally, so an empty hand still gets its +5
    E.push_auto(game, pid, "Hunting Lodge", "draw")
    hand = list(_hand(game, pid))
    if hand:
        E.discard(game, pid, hand)


def _hunting_lodge_draw(game, pid, frame, choice):
    E.add_cards(game, 5, pid, final=True)   # a printed +5 that ENDS the ability


# --- Kiln ($5) ---------------------------------------------------------------
# "+$2. The next time you play a card this turn, you may first gain a copy of
# it." Ph. 10 widened `before_play` to a card of ANY TYPE for exactly this, so
# an ordinary Copper play now opens the window too.

def _kiln(game, pid):
    E.add_coins(game, 2)
    # `until="turn_end"`: a this-turn watcher, so it never keeps Kiln on the
    # table ("the next time you play a card THIS TURN").
    E.add_watcher(game, pid, "Kiln", "before_play", stage="copy", until="turn_end")


def _kiln_when(game, w, ctx):
    """"the next time YOU play a card" — never an opponent's play. Evaluated at
    JOIN time, so a Kiln that cannot act never enters the pool."""
    return ctx.get("actor") == w["owner"]


def _kiln_copy(game, pid, frame, choice):
    # "You can only use Kiln on the VERY NEXT card you play" — spent whether or
    # not a copy is gained, and spent BEFORE the offer so an unavailable pile
    # cannot carry it over to the card after.
    E.remove_watcher(game, pid, "Kiln", 1)
    card = frame["data"].get("subject")
    pile = E.pile_of(game, card)
    # GAIN A COPY (ch. VII, p. 49) — the rule for the whole family, and Kiln is
    # named in it: "you can only gain a copy of a card **if it's available in
    # the Supply**. If it's a Ruins, Castle or card from a split pile, the TOP
    # CARD OF THE PILE HAS TO HAVE THE SAME NAME. If it's a Knight … it's
    # impossible, because they all have different names." Ch. VIII's Kiln model
    # says "gain a copy of it FROM THE SUPPLY" in as many words, and ch. III
    # GAINING A CARD closes the other half: "cards from non-Supply piles can
    # only be gained by effects that specifically say to gain them from that
    # pile or effects that NAME the card" — Kiln does neither, so a played
    # Horse, Spoils, Madman, Mercenary or Traveller copies nothing.
    if pile is None or not E.is_supply_pile(game, pile) \
            or E.pile_top(game, pile) != card:
        E.lost_track(game, pid, card, "copied",
                     why="no copy of it is available in the Supply")
        return
    E.push_choose_option(game, pid, "Kiln", "do",
                         data={"pile": pile, "card": card},
                         options=[{"id": "yes", "label": f"Gain a copy of {card}"},
                                  {"id": "no", "label": "Don't"}])


def _kiln_do(game, pid, frame, choice):
    if choice["ids"][0] != "yes":
        return
    # "You gain a copy BEFORE RESOLVING the card" — which is what the whole
    # before_play window buys: a Livery played after a Kiln does NOT give a
    # Horse for its own copy, because its when-gain ability is not active yet.
    E.gain(game, pid, frame["data"]["pile"])


# --- Livery ($5) -------------------------------------------------------------
# "+$3. This turn, when you gain a card costing $4 or more, gain a Horse."

def _livery(game, pid):
    E.add_coins(game, 3)
    # "Only cards gained AFTER playing Livery" — the watcher starts here — and
    # `until="turn_end"`, so Livery discards at its own Clean-up like any card.
    E.add_watcher(game, pid, "Livery", "gain", stage="horse", until="turn_end")


def _livery_when(game, w, ctx):
    """"Livery triggers based on the card's cost RIGHT WHEN YOU GAIN IT, no
    matter if it changes cost afterwards" — and the join-time filter IS right
    when you gain it. `cost_ge` reads the coin component alone ("$4 or more" is
    a LOWER bound, so a Potion- or Debt-costed card is not excluded)."""
    return (ctx.get("actor") == w["owner"] and ctx.get("subject") is not None
            and E.cost_ge(game, ctx["subject"], 4))


def _livery_horse(game, pid, frame, choice):
    # "You gain the Horse ON WHEN-GAIN." Two Liverys are two watchers and so
    # two Horses for one $4+ gain.
    E.gain_from(game, pid, "Horse")


# --- Paddock ($5) ------------------------------------------------------------
# "+$2. Gain 2 Horses. +1 Action per empty Supply pile."

def _paddock(game, pid):
    E.add_coins(game, 2)
    # "You get the initial +$2 even if you can't gain 2 Horses, and you still
    # get the +Actions."
    for _ in range(2):
        E.gain_from(game, pid, "Horse")
    # "Each time you play a Paddock, COUNT EMPTY SUPPLY PILES (EFFECTS ARE
    # IMMEDIATE)" — and `count_empty_piles` counts SUPPLY piles only, so the
    # Horse pile can never be one of them however empty it gets.
    E.add_actions(game, E.count_empty_piles(game))


# --- Sanctuary ($5) ----------------------------------------------------------
# "+1 Card. +1 Action. +1 Buy. You may Exile a card from your hand."

def _sanctuary(game, pid):
    E.add_cards(game, 1, pid)          # not final: three more clauses follow
    E.add_actions(game, 1)
    E.add_buys(game, 1)
    hand = _hand(game, pid)
    if hand:
        E.push_choose_cards(game, pid, "Sanctuary", "exile", sorted(hand),
                            0, 1, "exile")


def _sanctuary_exile(game, pid, frame, choice):
    if choice["cards"]:
        E.exile(game, pid, choice["cards"])


# ══ $6 ═══════════════════════════════════════════════════════════════════════

# --- Destrier ($6*) ----------------------------------------------------------
# "+2 Cards. +1 Action. — During your turns, this costs $1 less per card you've
# gained this turn."

def _destrier(game, pid):
    E.add_cards(game, 2, pid)          # not final: the +1 Action follows it
    E.add_actions(game, 1)


def _destrier_cost(game):
    """A REDUCTION (`DYN_COSTS`), unlike Wayfarer's absolute override.

    "ONLY CARDS GAINED BY THE CURRENT PLAYER affect its cost" — which is
    exactly `_turn_gains`, the list ph. 2 added for Smugglers: it records the
    turn player's own gains and nobody else's. "All Destriers have the modified
    cost during your turn, including those in your hand or deck OR BELONGING TO
    OTHER PLAYERS" falls out of `cost()` having no asker."""
    return len(game.get("_turn_gains", ()))


# --- Wayfarer ($6*) ----------------------------------------------------------
# "+3 Cards. You may gain a Silver. — This has the same cost as the last other
# card gained this turn, if any."

def _wayfarer(game, pid):
    E.add_cards(game, 3, pid)          # not final: the Silver offer follows it
    # offered even with an empty Silver pile — choices are never
    # feasibility-filtered, and `gain` then does nothing
    E.push_choose_option(game, pid, "Wayfarer", "silver", options=[
        {"id": "yes", "label": "Gain a Silver"},
        {"id": "no", "label": "Don't"}])


def _wayfarer_silver(game, pid, frame, choice):
    if choice["ids"][0] == "yes":
        E.gain(game, pid, "Silver")


def _wayfarer_cost(game):
    """AN ABSOLUTE COST (`COST_OVERRIDE`), not a reduction — and a VECTOR.

    "After any player gains a card (other than Wayfarer) on a given turn,
    Wayfarer gets THE SAME COST. This lasts for the rest of the turn or until
    another card is gained", so the tracker is `turn_ctx["last_gain"]`, which
    the kernel writes on every gain BY ANY PLAYER and skips for a Wayfarer.

    Returning None means "use the normal path", i.e. the printed $6 WITH cost
    reduction applied — "cost reduction only affects Wayfarer's DEFAULT cost of
    $6. If Wayfarer is copying the cost of another card, only cost reduction on
    THAT card applies (which Wayfarer would copy), not cost reduction on
    Wayfarer itself."

    It copies the CURRENT cost ("if you gain a Destrier costing $5, Destrier's
    cost will immediately fall to $4, and Wayfarer's cost will follow") and it
    copies all three components: "Wayfarer can have a cost with Potion or Debt
    in it". The kernel's re-entry guard is what makes asking `cost()` here
    safe."""
    last = game["turn_ctx"].get("last_gain")
    if last is None:
        return None
    return {"coins": E.cost(game, last),
            "potions": E.potion_cost(game, last),
            "debt": E.debt_cost(game, last)}


# ══ $7 ═══════════════════════════════════════════════════════════════════════

# --- Animal Fair ($7*) -------------------------------------------------------
# "+$4. +1 Buy per empty Supply pile. — Instead of paying this card's cost, you
# may trash an Action card from your hand."

def _animal_fair(game, pid):
    E.add_coins(game, 4)
    E.add_buys(game, E.count_empty_piles(game))


def _animal_fair_avail(game, pid):
    """"You are allowed to choose Animal Fair EVEN WITHOUT HAVING $7, as long as
    you have an Action card in hand." THE reader for both `legal_moves` and
    `_h_buy` — an enumerator and a handler that disagree hand the bot a move
    that does nothing."""
    return any(E.has_type(game, c, "action") for c in _hand(game, pid))


def _animal_fair_pay_alt(game, pid, frame, choice):
    if choice["ids"][0] == "pay":
        # the kernel spent the Buy and parked the gain; paying is all that is
        # left. Animal Fair's cost is plain coins ({$7}, no Potion, no Debt) —
        # "the cost of Animal Fair is ALWAYS $7", which is why nothing here
        # reads the vector.
        game["coins"] -= frame["data"]["cost"]
        return
    actions = _hand_actions(game, pid)
    if actions:
        E.push_choose_cards(game, pid, "Animal Fair", "trash", actions,
                            1, 1, "trash")


def _animal_fair_trash(game, pid, frame, choice):
    # "If you buy it by trashing a card, the trashing happens BEFORE any
    # when-buy abilities" — the kernel parks ("__buy","finish") under this
    # stage, so the gain and its abilities follow.
    E.trash(game, pid, choice["cards"])


# ══ THE 20 EVENTS ════════════════════════════════════════════════════════════
#
# An Event's ability is a `LANDSCAPE_FX` entry run when it is BOUGHT. Buying an
# Event is not buying a card: no `gain`, no `buy`, no `buy_gains` bump. Several
# of these print "+1 Buy" purely so that "after resolving this Event, you still
# have the same number of Buys as you had before" (Desperation, Gamble, Pursue,
# Toil) — the Buy the purchase spent is handed straight back.

# --- Delay ($0) --------------------------------------------------------------
# "You may set aside an Action card from your hand. At the start of your next
# turn, play it."

def _ev_delay(game, pid):
    actions = _hand_actions(game, pid)
    if actions:
        E.push_choose_cards(game, pid, "Delay", "aside", actions, 0, 1,
                            "set aside to play next turn")


def _ev_delay_aside(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    E.set_aside(game, pid, [card])
    # `add_start_fx` (ph. 4, Farmhands) — a start-of-turn ability with no
    # Duration on the table to hang off, pooled with every other one.
    E.add_start_fx(game, pid, "Delay", "play", data={"card": card})


def _ev_delay_play(game, pid, frame, choice):
    card = frame["data"]["card"]
    if card not in game["seats"][pid]["set_aside"]:
        E.lost_track(game, pid, card, "played")
        return
    E.take_set_aside(game, pid, [card], dest="aside")
    E.play_action_card(game, pid, card, from_zone="aside")


# --- Desperation ($0, once per turn) -----------------------------------------
# "Once per turn: You may gain a Curse. If you do, +1 Buy and +$2."

def _ev_desperation(game, pid):
    E.push_choose_option(game, pid, "Desperation", "do", options=[
        {"id": "yes", "label": "Gain a Curse"},
        {"id": "no", "label": "Don't"}])


def _ev_desperation_do(game, pid, frame, choice):
    if choice["ids"][0] != "yes":
        return
    # "If you do" — an empty Curse pile means no Buy and no $
    if E.gain(game, pid, "Curse"):
        E.add_buys(game, 1)
        E.add_coins(game, 2)


# --- Gamble ($2) — 2025 ERRATUM ----------------------------------------------
# "+1 Buy. Discard the top card of your deck. If it's an Action or Treasure,
# you may play it."
#
# "2025 (current) version: Gamble now ALWAYS discards the top card first. Then,
# if you play it, it MOVES FROM YOUR DISCARD PILE to play." Pre-2025 it
# revealed and only discarded on a decline. The consequence the compendium
# spells out: "See TRIGGERED ABILITY (first discard, then play)", so a
# discarded Village Green / Trail / Weaver / Faithful Hound reacts FIRST — and
# per Village Green 8, a Village Green that reacts by playing itself cannot
# then also be played by Gamble (the expanded lose-track rule, which our
# `find_card_zone` guard enforces).

def _ev_gamble(game, pid):
    E.add_buys(game, 1)
    seen = E.look_top(game, pid, 1)
    if not seen:
        return
    # the play offer is parked BELOW the discard, so the discard's own
    # when-discard abilities resolve before it
    E.push_auto(game, pid, "Gamble", "offer", data={"card": seen[0]})
    E.discard(game, pid, list(seen), zone="aside", public=True)


def _ev_gamble_offer(game, pid, frame, choice):
    card = frame["data"]["card"]
    if not (E.has_type(game, card, "action") or E.has_type(game, card, "treasure")):
        return
    zone = E.find_card_zone(game, pid, card, zones=("discard",))
    if zone is None:
        E.lost_track(game, pid, card, "played")
        return
    E.push_choose_option(game, pid, "Gamble", "play", data={"card": card},
                         options=[{"id": "yes", "label": f"Play {card}"},
                                  {"id": "no", "label": "Don't"}])


def _ev_gamble_play(game, pid, frame, choice):
    if choice["ids"][0] != "yes":
        return
    card = frame["data"]["card"]
    zone = E.find_card_zone(game, pid, card, zones=("discard",))
    if zone is None:
        E.lost_track(game, pid, card, "played")
        return
    # a card that is BOTH (an Action-Treasure) is played as the Action, which
    # is the play path that runs its ability; `play_action_card` pays a
    # Treasure's printed $ on the way through anyway
    if E.has_type(game, card, "action"):
        E.play_action_card(game, pid, card, from_zone="discard")
    else:
        E.play_treasure_card(game, pid, card, from_zone="discard")


# --- Pursue ($2) -------------------------------------------------------------
# "+1 Buy. Name a card. Reveal the top 4 cards from your deck. Put the matches
# back and discard the rest."

def _ev_pursue(game, pid):
    E.add_buys(game, 1)
    E.push_name_card(game, pid, "Pursue", "named")


def _ev_pursue_named(game, pid, frame, choice):
    named = choice["card"]
    seen = E.look_top(game, pid, 4)
    if not seen:
        return
    E.reveal(game, pid, list(seen), "Pursue")
    matches = [c for c in seen if c == named]
    rest = [c for c in seen if c != named]
    # `discard_then_putback` pushes the put-back FIRST so it sits BELOW the
    # discard's when-discard triggers — "first discard, THEN put cards back".
    E.discard_then_putback(game, pid, "Pursue", rest, matches)


# --- Ride ($2) ---------------------------------------------------------------

def _ev_ride(game, pid):
    E.gain_from(game, pid, "Horse")


# --- Toil ($2) ---------------------------------------------------------------
# "+1 Buy. You may play an Action card from your hand."

def _ev_toil(game, pid):
    E.add_buys(game, 1)
    actions = _hand_actions(game, pid)
    if actions:
        E.push_choose_cards(game, pid, "Toil", "play", actions, 0, 1, "play")


def _ev_toil_play(game, pid, frame, choice):
    if choice["cards"]:
        # an Action played in your BUY phase — it does not use an Action from
        # your Action pool, which `play_action_card` already reflects (only
        # `_h_play_action` spends one)
        E.play_action_card(game, pid, choice["cards"][0], from_zone="hand")


# --- Enhance ($3) ------------------------------------------------------------
# "You may trash a non-Victory card from your hand, to gain a card costing up
# to $2 more than it."

def _ev_enhance(game, pid):
    opts = sorted({c for c in _hand(game, pid) if not E.has_type(game, c, "victory")})
    if opts:
        E.push_choose_cards(game, pid, "Enhance", "trash", opts, 0, 1, "trash")


def _ev_enhance_trash(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    # A GAIN THAT FOLLOWS A TRASH IS PARKED BELOW IT (the ph.-6 ordering
    # lesson): push the continuation FIRST, then trash, so the trashed card's
    # own on-trash ability resolves before the player is asked what to gain.
    E.push_auto(game, pid, "Enhance", "gain", data={"ref": card})
    E.trash(game, pid, [card])


def _ev_enhance_gain(game, pid, frame, choice):
    ref = frame["data"]["ref"]
    piles = _supply_piles(game, lambda p: E.cost_le_card(game, p, ref, 2))
    if piles:
        E.push_choose_pile(game, pid, "Enhance", "take", piles)


def _ev_enhance_take(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- March ($3) --------------------------------------------------------------
# "Look through your discard pile. You may play an Action card from it."

def _ev_march(game, pid):
    actions = sorted({c for c in game["seats"][pid]["discard"]
                      if E.has_type(game, c, "action")})
    if actions:
        E.push_choose_cards(game, pid, "March", "play", actions, 0, 1, "play")


def _ev_march_play(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    zone = E.find_card_zone(game, pid, card, zones=("discard",))
    if zone is None:
        E.lost_track(game, pid, card, "played")
        return
    E.play_action_card(game, pid, card, from_zone="discard")


# --- Transport ($3) ----------------------------------------------------------
# "Choose one: Exile an Action card from the Supply; or put an Action card you
# have in Exile onto your deck."

def _ev_transport(game, pid):
    E.push_choose_option(game, pid, "Transport", "mode", options=[
        {"id": "exile", "label": "Exile an Action card from the Supply"},
        {"id": "deck", "label": "Put an Action card from your Exile mat onto your deck"}])


def _ev_transport_mode(game, pid, frame, choice):
    if choice["ids"][0] == "exile":
        piles = _action_supply_piles(game)
        if piles:
            E.push_choose_pile(game, pid, "Transport", "exile", piles)
        return
    # "You may move an Action card from your Exile mat WHETHER IT WAS PUT THERE
    # BY TRANSPORT OR BY ANOTHER ABILITY."
    on_mat = sorted({c for c in game["seats"][pid]["exile"]
                     if E.has_type(game, c, "action")})
    if on_mat:
        E.push_choose_cards(game, pid, "Transport", "deck", on_mat, 1, 1,
                            "put onto your deck")


def _ev_transport_exile(game, pid, frame, choice):
    E.exile(game, pid, [choice["pile"]], zone="supply")


def _ev_transport_deck(game, pid, frame, choice):
    # onto the DECK, not into the discard — so this is NOT a discard from Exile
    # and no when-discard ability sees it
    E.topdeck(game, pid, choice["cards"][0], zone="exile", public=True)


# --- Banish ($4) -------------------------------------------------------------
# "Exile any number of cards with the same name from your hand."

def _ev_banish(game, pid):
    names = sorted(set(_hand(game, pid)))
    if names:
        E.push_choose_option(game, pid, "Banish", "name",
                             options=[{"id": n, "label": n} for n in names])


def _ev_banish_name(game, pid, frame, choice):
    name = choice["ids"][0]
    n = _hand(game, pid).count(name)
    if n:
        # "ANY NUMBER", so 0 is a legal answer even after naming
        E.push_choose_cards(game, pid, "Banish", "exile", [name] * n,
                            0, n, "exile")


def _ev_banish_exile(game, pid, frame, choice):
    if choice["cards"]:
        E.exile(game, pid, choice["cards"])


# --- Bargain ($4) ------------------------------------------------------------
# "Gain a non-Victory card costing up to $5. Each other player gains a Horse."

def _ev_bargain(game, pid):
    # "First gain, THEN opponents gain" — the opponents' half is parked BELOW
    # the buyer's own pile choice. "You can buy this Event even with no Horses
    # left."
    E.push_auto(game, pid, "Bargain", "horses")
    piles = _gain_piles_up_to(game, 5)
    piles = [p for p in piles if not E.has_type(game, p, "victory")]
    if piles:
        E.push_choose_pile(game, pid, "Bargain", "gain", piles)


def _ev_bargain_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


def _ev_bargain_horses(game, pid, frame, choice):
    # turn order from the current player (E.opponents gives exactly that)
    for opp in E.opponents(game, pid):
        E.gain_from(game, opp, "Horse")


# --- Invest ($4) -------------------------------------------------------------
# "Exile an Action card from the Supply. While it's in Exile, when another
# player gains or Invests in a copy of it, +2 Cards."

def _ev_invest(game, pid):
    piles = _action_supply_piles(game)
    if piles:
        E.push_choose_pile(game, pid, "Invest", "exile", piles)


def _ev_invest_exile(game, pid, frame, choice):
    pile = choice["pile"]
    card = E.pile_top(game, pile)
    # `exile()` cannot say WHY a card was Exiled, and it must not: Camel Train,
    # Coven, Enclave and the two Supply-Exiling Ways all move cards the same
    # way and none of them is "Investing". So Invest marks its own move with a
    # transient that the join-time watcher filter reads — set and cleared
    # inside this call, so it can never reach a save.
    game["_investing"] = card
    try:
        got = E.exile(game, pid, [pile], zone="supply")
    finally:
        game.pop("_investing", None)
    if not got:
        return
    # ONE WATCHER PER PURCHASE, deliberately: "if you Invest in another copy of
    # the same card, you draw 4 cards, etc." — two Invests are two pool entries
    # of +2 Cards each. Counting invested copies on the watchers rather than
    # off the mat is forced, because zones hold NAMES: "keep the Invested cards
    # separate from any other cards you might Exile … other Exiled cards — even
    # if they happen to be copies of an Invested card — do not draw you cards".
    for event in ("gain", "exile"):
        _landscape_watcher(game, pid, "Invest", event,
                           "draw_" + event, data={"card": got[0]})


def _invest_gain_when(game, w, ctx):
    """"When ANOTHER PLAYER gains … a copy of it", and only "WHILE IT'S IN
    EXILE" — the mat's own ability can end an Invest, since discarding copies
    from the mat is all-or-nothing."""
    card = w["data"]["card"]
    return (ctx.get("actor") != w["owner"] and ctx.get("subject") == card
            and E.on_exile(game, w["owner"], card) > 0)


def _invest_exile_when(game, w, ctx):
    """"…or INVESTS in a copy of it" — the second half, keyed on the marker
    Invest's own stage sets, so no other Supply Exile can fire it."""
    card = w["data"]["card"]
    return (game.get("_investing") == card and ctx.get("actor") != w["owner"]
            and ctx.get("subject") == card
            and E.on_exile(game, w["owner"], card) > 0)


def _invest_draw(game, pid, frame, choice):
    E.add_cards(game, 2, pid, final=True)   # a printed +2 that ENDS the ability


# --- Seize the Day ($4, once per GAME) ---------------------------------------
# "Once per game: Take an extra turn after this one."

def _ev_seize_the_day(game, pid):
    # "Each player can buy this Event once per game" — the `once: "game"` gate
    # in cards.py is per player and `landscape_gate` owns it.
    E.request_extra_turn(game, pid, source="Seize the Day")


# --- Commerce ($5) -----------------------------------------------------------
# "Gain a Gold per differently named card you've gained this turn."

def _ev_commerce(game, pid):
    # "Only the cards gained BEFORE buying Commerce are counted" — so the count
    # is taken before the first Gold lands. `_turn_gains` is the turn player's
    # own gains, which is what "you've gained" means.
    n = len(set(game.get("_turn_gains", ())))
    _gain_seq(game, pid, "Commerce", ["Gold"] * n)


# --- Demand ($5) -------------------------------------------------------------
# "Gain a Horse and a card costing up to $4, both onto your deck."

def _ev_demand(game, pid):
    # "You gain each card IN TURN and in the order given, see TRIGGERED
    # ABILITY" — so the second gain is parked BELOW the Horse's, and everything
    # the Horse gain triggered (a Sleigh, a Way of the Seal offer, an
    # opponent's Gatekeeper) resolves before the pile list is even built. "If
    # there are no Horses left, you still gain the other card" falls out of
    # parking it unconditionally.
    E.push_auto(game, pid, "Demand", "pick")
    E.gain_from(game, pid, "Horse", dest="deck")


def _ev_demand_pick(game, pid, frame, choice):
    piles = _gain_piles_up_to(game, 4)
    if piles:
        E.push_choose_pile(game, pid, "Demand", "gain", piles)


def _ev_demand_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"], dest="deck")


# --- Stampede ($5) -----------------------------------------------------------
# "If you have 5 or fewer cards in play, gain 5 Horses onto your deck."

def _ev_stampede(game, pid):
    # "This checks the CARDS YOU HAVE IN PLAY" — the table, not the deck.
    if len(game["seats"][pid]["in_play"]) > 5:
        return
    for _ in range(5):
        E.gain_from(game, pid, "Horse", dest="deck")


# --- Reap ($7) — 2025 ERRATUM ------------------------------------------------
# "Gain a Gold, setting it aside. At the start of your next turn, play it."
#
# "2025 (current) version: the card is now GAINED DIRECTLY to your 'set aside'
# area (similarly to gaining to your hand/deck)" — ph. 10 added that `dest`.
# With the first version the Gold visited the discard pile, so a when-gain
# ability could shuffle it in and lose track of it.

def _ev_reap(game, pid):
    if not E.gain(game, pid, "Gold", dest="set_aside"):
        return
    E.add_start_fx(game, pid, "Reap", "play", data={"card": "Gold"})


def _ev_reap_play(game, pid, frame, choice):
    card = frame["data"]["card"]
    # "If you MOVE the Gold when you gain it (e.g. with Watchtower), Reap loses
    # track of it and can't play it next turn."
    if card not in game["seats"][pid]["set_aside"]:
        E.lost_track(game, pid, card, "played")
        return
    E.take_set_aside(game, pid, [card], dest="aside")
    E.play_treasure_card(game, pid, card, from_zone="aside")


# --- Enclave ($8) ------------------------------------------------------------
# "Gain a Gold. Exile a Duchy from the Supply."

def _ev_enclave(game, pid):
    # "If there are no Golds left, you still Exile a Duchy, and vice versa" —
    # so the Duchy half is parked unconditionally, BELOW the Gold gain.
    E.push_auto(game, pid, "Enclave", "duchy")
    E.gain(game, pid, "Gold")


def _ev_enclave_duchy(game, pid, frame, choice):
    E.exile(game, pid, ["Duchy"], zone="supply")


# --- Alliance ($10) ----------------------------------------------------------
# "Gain a Province, a Duchy, an Estate, a Gold, a Silver, and a Copper."

def _ev_alliance(game, pid):
    # "You gain the ones you can, even if some piles are empty … each card IN
    # TURN and IN THE ORDER GIVEN" — which is what `_seq_gain` is for.
    _gain_seq(game, pid, "Alliance",
              ["Province", "Duchy", "Estate", "Gold", "Silver", "Copper"])


# --- Populate ($10) ----------------------------------------------------------
# "Gain one card from each Action Supply pile."

def _ev_populate(game, pid):
    # "You do not gain a card from NON-SUPPLY piles" (so no Horse), and "you
    # WILL gain a Ruins" — the pile's own type is what decides, not its face.
    piles = _action_supply_piles(game)
    if piles:
        E.push_auto(game, pid, "Populate", "next", data={"left": piles})


def _ev_populate_next(game, pid, frame, choice):
    # "You gain them IN WHATEVER ORDER YOU CHOOSE", and "keep track of which
    # piles you have gained from already in case when-gain abilities trigger" —
    # so one pick at a time off a shrinking list, never a single batch.
    left = [p for p in frame["data"]["left"] if E.pile_top(game, p) is not None]
    if not left:
        return
    if len(left) == 1:
        E.gain(game, pid, left[0])          # no choice left to make
        return
    E.push_choose_pile(game, pid, "Populate", "take", left, data={"left": left})


def _ev_populate_take(game, pid, frame, choice):
    pile = choice["pile"]
    rest = [p for p in frame["data"]["left"] if p != pile]
    if rest:
        # the remainder is parked BELOW this gain, so its when-gain abilities
        # resolve before the next pile is picked
        E.push_auto(game, pid, "Populate", "next", data={"left": rest})
    E.gain(game, pid, pile)


# ══ registration ═════════════════════════════════════════════════════════════

EFFECTS.update({
    "Animal Fair": _animal_fair,
    "Bounty Hunter": _bounty_hunter,
    "Camel Train": _camel_train,
    "Cavalry": _cavalry,
    "Destrier": _destrier,
    "Displace": _displace,
    "Fisherman": _fisherman,
    "Goatherd": _goatherd,
    "Groom": _groom,
    "Horse": _horse,
    "Hostelry": _hostelry,
    "Hunting Lodge": _hunting_lodge,
    "Kiln": _kiln,
    "Livery": _livery,
    "Paddock": _paddock,
    "Sanctuary": _sanctuary,
    "Scrap": _scrap,
    "Snowy Village": _snowy_village,
    "Supplies": _supplies,
    "Wayfarer": _wayfarer,
})

STAGES.update({
    ("Animal Fair", "pay_alt"): _animal_fair_pay_alt,
    ("Animal Fair", "trash"): _animal_fair_trash,
    ("Bounty Hunter", "exile"): _bounty_hunter_exile,
    ("Camel Train", "exile"): _camel_train_exile,
    ("Camel Train", "gain"): _camel_train_gain,
    ("Cavalry", "gain"): _cavalry_gain,
    ("Displace", "exile"): _displace_exile,
    ("Displace", "pick"): _displace_pick,
    ("Displace", "gain"): _displace_gain,
    ("Goatherd", "trash"): _goatherd_trash,
    ("Goatherd", "draw"): _goatherd_draw,
    ("Groom", "gain"): _groom_gain,
    ("Groom", "bonus"): _groom_bonus,
    ("Hostelry", "gain"): _hostelry_gain,
    ("Hostelry", "discard"): _hostelry_discard,
    ("Hostelry", "horses"): _hostelry_horses,
    ("Hunting Lodge", "choose"): _hunting_lodge_choose,
    ("Hunting Lodge", "draw"): _hunting_lodge_draw,
    ("Kiln", "copy"): _kiln_copy,
    ("Kiln", "do"): _kiln_do,
    ("Livery", "horse"): _livery_horse,
    ("Sanctuary", "exile"): _sanctuary_exile,
    ("Scrap", "trash"): _scrap_trash,
    ("Scrap", "pick"): _scrap_pick,
    ("Scrap", "do"): _scrap_do,
    ("Wayfarer", "silver"): _wayfarer_silver,
    # the EVENTS
    ("Alliance", "seq_gain"): _seq_gain,
    ("Banish", "name"): _ev_banish_name,
    ("Banish", "exile"): _ev_banish_exile,
    ("Bargain", "gain"): _ev_bargain_gain,
    ("Bargain", "horses"): _ev_bargain_horses,
    ("Commerce", "seq_gain"): _seq_gain,
    ("Delay", "aside"): _ev_delay_aside,
    ("Delay", "play"): _ev_delay_play,
    ("Demand", "pick"): _ev_demand_pick,
    ("Demand", "gain"): _ev_demand_gain,
    ("Desperation", "do"): _ev_desperation_do,
    ("Enclave", "duchy"): _ev_enclave_duchy,
    ("Enhance", "trash"): _ev_enhance_trash,
    ("Enhance", "gain"): _ev_enhance_gain,
    ("Enhance", "take"): _ev_enhance_take,
    ("Gamble", "offer"): _ev_gamble_offer,
    ("Gamble", "play"): _ev_gamble_play,
    ("Invest", "exile"): _ev_invest_exile,
    ("Invest", "draw_gain"): _invest_draw,
    ("Invest", "draw_exile"): _invest_draw,
    ("March", "play"): _ev_march_play,
    ("Populate", "next"): _ev_populate_next,
    ("Populate", "take"): _ev_populate_take,
    ("Pursue", "named"): _ev_pursue_named,
    ("Reap", "play"): _ev_reap_play,
    ("Toil", "play"): _ev_toil_play,
    ("Transport", "mode"): _ev_transport_mode,
    ("Transport", "exile"): _ev_transport_exile,
    ("Transport", "deck"): _ev_transport_deck,
})

TRIGGERS.update({
    # WHEN-GAIN abilities. None of the three `commutes`: Camel Train's takes a
    # Gold off its pile, Cavalry's can send you back to your Action phase, and
    # Hostelry's opens a real choice — every one of them can change what
    # another ability the same gain triggered is able to do.
    "Camel Train": [{"on": "gain", "from": "self", "stage": "gain"}],
    "Cavalry": [{"on": "gain", "from": "self", "stage": "gain"}],
    "Hostelry": [{"on": "gain", "from": "self", "stage": "gain"}],
})

WATCHER_WHENS.update({
    ("Kiln", "copy"): _kiln_when,
    ("Livery", "horse"): _livery_when,
    ("Invest", "draw_gain"): _invest_gain_when,
    ("Invest", "draw_exile"): _invest_exile_when,
})

DYN_COSTS.update({
    "Destrier": _destrier_cost,
    "Fisherman": _fisherman_cost,
})

COST_OVERRIDE.update({
    "Wayfarer": _wayfarer_cost,
})

BUY_PAY_ALT.update({
    "Animal Fair": {"avail": _animal_fair_avail,
                    "label": "Trash an Action card from your hand",
                    "stage": "pay_alt"},
})

# See the bucket argument above Supplies: its play GAINS a card, and a gain is
# the most-watched occurrence in the game, so it can open a decision frame
# halfway through a bulk play that is one move with one undo snapshot.
MANUAL_TREASURES.add("Supplies")

LANDSCAPE_FX.update({
    "Alliance": _ev_alliance,
    "Banish": _ev_banish,
    "Bargain": _ev_bargain,
    "Commerce": _ev_commerce,
    "Delay": _ev_delay,
    "Demand": _ev_demand,
    "Desperation": _ev_desperation,
    "Enclave": _ev_enclave,
    "Enhance": _ev_enhance,
    "Gamble": _ev_gamble,
    "Invest": _ev_invest,
    "March": _ev_march,
    "Populate": _ev_populate,
    "Pursue": _ev_pursue,
    "Reap": _ev_reap,
    "Ride": _ev_ride,
    "Seize the Day": _ev_seize_the_day,
    "Stampede": _ev_stampede,
    "Toil": _ev_toil,
    "Transport": _ev_transport,
})


# ==========================================================================
# HALF B — the 20 WAYS, the Reactions that play themselves, the Attacks,
#          the Durations and the two Treasures.
# ==========================================================================

# ══ shared helpers ═══════════════════════════════════════════════════════════



def _in_play(game, pid):
    return game["seats"][pid]["in_play"]




def _react_zone(frame):
    """WHERE a self-triggered card is, read off the emit's own context rather
    than guessed: a `gain` carries "dest", a `discard` carries the SOURCE
    "zone" (the card itself is in the discard pile by then), a `trash` neither.
    The Hinterlands `_self_zone` shape — half B owns none of those cards, so it
    gets its own copy rather than importing across a module boundary."""
    d = frame["data"]
    if "dest" in d:
        return d["dest"]
    if "zone" in d:
        return "discard"
    return "trash"


# ============================================================================
# THE KINGDOM CARDS
# ============================================================================

# ══ BLACK CAT ($2, Action–Attack–Reaction) ═══════════════════════════════════
# "+2 Cards. If it isn't your turn, each other player gains a Curse.
#  — When another player gains a Victory card, you may play this from your
#  hand."
#
# The attack half only exists OFF-TURN, which makes this the set's one card
# whose victim ORDER is stated: "if you play this when it's not your turn, deal
# out the Curses STARTING WITH THE CURRENT PLAYER". `attack_opponents` orders
# from the PLAYER, which is the same thing in 2p and is not in 3-4p (players
# [A,B,C,D], A's turn, C reacts: opponents(C) is [D,A,B] and the rules want
# [A,B,D]). So the queue is built here from the current player and handed to
# the same one-opponent-at-a-time chain — `_atk_immune` is still the kernel's,
# read exactly the way a later-stage attack reads it.

def _black_cat(game, pid):
    E.add_cards(game, 2, pid)
    if pid == game["turn"]:
        return                  # "If it ISN'T your turn" — on your own turn, nothing
    immune = list(game.get("_atk_immune", []))
    order = game["players"]
    i = order.index(game["turn"])
    queue = [p for p in order[i:] + order[:i] if p != pid and p not in immune]
    if queue:
        E.push_auto(game, pid, "Black Cat", "deal", data={"queue": queue})


def _black_cat_deal(game, pid, frame, choice):
    """One opponent at a time, each whole chain before the next — the
    `__attack/next` shape, spelled out here because the queue ORDER is the
    card's own rule rather than the kernel's default."""
    queue = frame["data"]["queue"]
    if not queue:
        return
    o, rest = queue[0], queue[1:]
    if rest:
        E.push_auto(game, pid, "Black Cat", "deal", data={"queue": rest})
    E.push_auto(game, o, "Black Cat", "curse")


def _black_cat_curse(game, pid, frame, choice):
    E.gain(game, pid, "Curse")


def _black_cat_when(game, pid, ctx):
    """"When ANOTHER player gains a Victory card" — another player than the one
    holding the Black Cat, so the gainer is excluded and every other holder is
    offered (this is not a `who:"actor"` reaction)."""
    subject = ctx.get("subject")
    return (subject is not None and ctx.get("actor") != pid
            and E.has_type(game, subject, "victory"))


def _black_cat_react(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if "Black Cat" not in _hand(game, pid):
        E.lost_track(game, pid, "Black Cat", "played")
        return
    # REACTION THAT PLAYS ITSELF: no Action is spent, and an off-turn play must
    # not count toward the TURN player's actions_played (Conspirator's counter).
    E.play_action_card(game, pid, "Black Cat", from_zone="hand",
                       count=(pid == game["turn"]))


# ══ SLEIGH ($2, Action–Reaction) ═════════════════════════════════════════════
# "Gain 2 Horses. — When you gain a card, you may discard this, to put that
#  card into your hand or onto your deck."
#
# The two Horses are gained ONE AT A TIME: each is its own `gain` event, so a
# second Sleigh in hand may react to each of them and the pile may run dry
# between them (the Weaver/Trader `silvers` chain).

def _sleigh(game, pid):
    E.push_auto(game, pid, "Sleigh", "horse", data={"n": 2})


def _sleigh_horse(game, pid, frame, choice):
    n = frame["data"]["n"]
    if n <= 0:
        return
    if n > 1:
        E.push_auto(game, pid, "Sleigh", "horse", data={"n": n - 1})
    E.gain_from(game, pid, "Horse")


def _sleigh_when(game, pid, ctx):
    return ctx.get("subject") is not None


def _sleigh_react(game, pid, frame, choice):
    """"Sleigh may only be discarded from your hand" — which the `from:"hand"`
    source already guarantees. The MOVE is parked first so it sits below
    whatever the discard triggers: "you can move the gained card with Sleigh
    even though you discarded the Sleigh on top of it"."""
    if choice["ids"][0] != "play":
        return
    if "Sleigh" not in _hand(game, pid):
        E.lost_track(game, pid, "Sleigh", "discarded")
        return
    d = frame["data"]
    card = d.get("gained")
    if card is not None:
        E.push_auto(game, pid, "Sleigh", "move",
                    data={"card": card, "dest": d.get("dest", "discard")})
    E.discard(game, pid, ["Sleigh"])


def _sleigh_move(game, pid, frame, choice):
    """"If you gain a Sleigh to your hand, you may react with that same Sleigh.
    HOWEVER, the Sleigh would stay in your discard pile due to the 'lose track'
    rule" — which falls out: the gained card was the Sleigh, discarding it took
    it out of the hand it was gained to, and the zone check below then fails."""
    card, dest = frame["data"]["card"], frame["data"]["dest"]
    zone = E.find_card_zone(game, pid, card, (dest,))
    if zone is None:
        E.lost_track(game, pid, card,
                     why="it is no longer where it was gained")
        return
    E.push_choose_option(
        game, pid, "Sleigh", "where",
        options=[{"id": "hand", "label": f"Put the {card} into your hand"},
                 {"id": "deck", "label": f"Put the {card} onto your deck"}],
        data={"card": card, "zone": zone})


def _sleigh_where(game, pid, frame, choice):
    card, zone = frame["data"]["card"], frame["data"]["zone"]
    if E.find_card_zone(game, pid, card, (zone,)) is None:
        # a second Sleigh reacting to the same gain: "only the FIRST one would
        # let you move the gained card"
        E.lost_track(game, pid, card, why="it moved before Sleigh could")
        return
    if choice["ids"][0] == "hand":
        E.to_hand(game, pid, card, zone=zone)
    else:
        E.topdeck(game, pid, card, zone=zone, public=True)


# ══ SHEEPDOG ($3, Action–Reaction) ═══════════════════════════════════════════
# "+2 Cards. — When you gain a card, you may play this from your hand."

def _sheepdog(game, pid):
    # a printed "+2 Cards" that also ENDS the ability, so `final=True` gets it
    # BOTH seams: the Chameleon swap and a Star Chart owner's shuffle pick
    E.add_cards(game, 2, pid, final=True)


def _sheepdog_react(game, pid, frame, choice):
    """"You may react with Sheepdog when you buy & gain a card in your Buy
    phase. If this makes you draw Treasures, you cannot play them" — the second
    half is `turn_ctx["bought"]`, which the kernel already enforces."""
    if choice["ids"][0] != "play":
        return
    if "Sheepdog" not in _hand(game, pid):
        E.lost_track(game, pid, "Sheepdog", "played")
        return
    E.play_action_card(game, pid, "Sheepdog", from_zone="hand",
                       count=(pid == game["turn"]))


# ══ FALCONER ($5, Action–Reaction) ═══════════════════════════════════════════
# "Gain a card to your hand costing less than this. — When any player gains a
#  card with 2 or more types (Action, Attack, etc.), you may play this from
#  your hand."
#
# "costing less than THIS" is a card reference, never a number bound —
# `cost_lt_card` is what makes it a cost VECTOR comparison ("both {$4} and {4D}
# are lower than {$4,4D}").

def _falconer(game, pid):
    piles = _supply_piles(game, lambda p: E.cost_lt_card(game, p, "Falconer"))
    if piles:
        E.push_choose_pile(game, pid, "Falconer", "gain", piles)


def _falconer_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"], dest="hand")     # "GAINED TO YOUR HAND"


def _falconer_when(game, pid, ctx):
    """"When ANY player gains a card with 2 or more types" — no `who` scoping,
    so every Falconer holder is offered a window, including the gainer."""
    subject = ctx.get("subject")
    return subject is not None and len(E.types_of(game, subject)) >= 2


def _falconer_react(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if "Falconer" not in _hand(game, pid):
        E.lost_track(game, pid, "Falconer", "played")
        return
    E.play_action_card(game, pid, "Falconer", from_zone="hand",
                       count=(pid == game["turn"]))


# ══ VILLAGE GREEN ($4, Action–Duration–Reaction) ═════════════════════════════
# "Either now or at the start of your next turn, +1 Card and +2 Actions.
#  — When you discard this other than during Clean-up, you may reveal it to
#  play it."
#
# ⚠ THE REVEAL IS AMBIGUITY **A9** (CLAUDE.md). Ch. V's 2020 errata list adds
# it; ch. VII 10 then says the change "was reverted back to the original
# version when printed in 2025"; ch. VIII's timing model, in the SAME document,
# is headed "Village Green (current version, 2020)" and reads "you may reveal
# This. If you do: Play This" — and the 2025-10 chart carries the reveal too.
# Two sources to one, so WE SHIP THE REVEAL. The observable difference is one
# `reveal()` call, pinned in `tests/test_cards_menagerie_b.py`.
#
# Clean-up is excluded for free: `_end_turn` moves in_play and hand to the
# discard pile directly and never calls `discard()`, so the `discard` emit
# cannot fire there.

def _village_green(game, pid):
    E.push_choose_option(
        game, pid, "Village Green", "mode",
        options=[{"id": "now", "label": "+1 Card and +2 Actions now"},
                 {"id": "next",
                  "label": "+1 Card and +2 Actions at the start of your next turn"}])


def _village_green_mode(game, pid, frame, choice):
    if choice["ids"][0] == "now":
        # NOTHING is registered, so the entry "failed to set up" and the card
        # discards normally in Clean-up — the Cargo Ship class.
        _village_green_bonus(game, pid, frame, choice)
        return
    # "If you react with this during another player's turn and choose 'next
    # turn', you get +1 Card and +2 Actions when it's YOUR turn and discard it
    # in THAT turn's Clean-up" — `_start_of_turn` sweeps the seat's own
    # dur_setup entries, so an off-turn play needs nothing extra.
    E.add_duration_fx(game, pid, "Village Green", "bonus")


def _village_green_bonus(game, pid, frame, choice):
    E.add_cards(game, 1, pid)          # not final: the +2 Actions follow it
    E.add_actions(game, 2)


def _village_green_on_discard(game, pid, frame, choice):
    zone = _react_zone(frame)
    if E.find_card_zone(game, pid, "Village Green", (zone,)) is None:
        # "When discarding several Village Greens at once, if playing one
        # causes another one to be shuffled in, you can't play that one" — the
        # Trail lesson, and it must SAY SO.
        E.lost_track(game, pid, "Village Green", "played")
        return
    E.push_choose_option(
        game, pid, "Village Green", "self_play",
        options=[{"id": "play", "label": "Reveal Village Green to play it"},
                 {"id": "decline", "label": "Don't play it"}],
        data={"zone": zone})


def _village_green_self_play(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    zone = E.find_card_zone(game, pid, "Village Green", (frame["data"]["zone"],))
    if zone is None:
        E.lost_track(game, pid, "Village Green", "played")
        return
    # The PLAY is parked first so it sits BELOW whatever the reveal's own emit
    # collects (a Patron pays for the reveal before the card resolves).
    E.push_auto(game, pid, "Village Green", "do_play", data={"zone": zone})
    E.reveal(game, pid, ["Village Green"], zone)


def _village_green_do_play(game, pid, frame, choice):
    zone = E.find_card_zone(game, pid, "Village Green", (frame["data"]["zone"],))
    if zone is None:
        E.lost_track(game, pid, "Village Green", "played")
        return
    E.play_action_card(game, pid, "Village Green", from_zone=zone,
                       count=(pid == game["turn"]))


# ══ BARGE ($5, Action–Duration) ══════════════════════════════════════════════
# "Either now or at the start of your next turn, +3 Cards and +1 Buy."

def _barge(game, pid):
    E.push_choose_option(
        game, pid, "Barge", "mode",
        options=[{"id": "now", "label": "+3 Cards and +1 Buy now"},
                 {"id": "next",
                  "label": "+3 Cards and +1 Buy at the start of your next turn"}])


def _barge_mode(game, pid, frame, choice):
    if choice["ids"][0] == "now":
        _barge_bonus(game, pid, frame, choice)
        return
    E.add_duration_fx(game, pid, "Barge", "bonus")


def _barge_bonus(game, pid, frame, choice):
    E.add_cards(game, 3, pid)          # not final: the +1 Buy follows it
    E.add_buys(game, 1)


# ══ COVEN ($5, Action–Attack) ════════════════════════════════════════════════
# "+1 Action. +$2. Each other player Exiles a Curse from the Supply. If they
#  can't, they discard their Exiled Curses."
#
# "You get the initial +1 Action and +$2 EVEN IF there are no Curses left in
# the Supply", and the fallback is NOT OPTIONAL "IF YOU DO": a player who
# cannot Exile one discards every Curse already on their mat — through
# `discard()`, so when-discard abilities fire.

def _coven(game, pid):
    E.add_actions(game, 1)
    E.add_coins(game, 2)
    E.attack_opponents(game, pid, "Coven", "hit")


def _coven_hit(game, pid, frame, choice):
    if E.exile(game, pid, ["Curse"], zone="supply"):
        return
    n = E.on_exile(game, pid, "Curse")
    if n:
        E.discard_from_exile(game, pid, ["Curse"] * n)


# ══ CARDINAL ($4, Action–Attack) ═════════════════════════════════════════════
# "+$2. Each other player reveals the top 2 cards of their deck, Exiles one
#  costing from $3 to $6, and discards the rest."
#
# "The ATTACKED player chooses which card to Exile if both cards have the
# appropriate cost" — a decision frame for the victim, not the attacker. The
# range is a CARD COSTS range, and ch. VI names Cardinal explicitly under "a
# card costing 'from $x to $y' cannot have Potion or Debt in its cost", which
# is exactly what the `cost_le` half of the pair enforces.

def _cardinal(game, pid):
    E.add_coins(game, 2)
    E.attack_opponents(game, pid, "Cardinal", "hit")


def _cardinal_hit(game, pid, frame, choice):
    moved = E.look_top(game, pid, 2)
    if not moved:
        return
    E.reveal(game, pid, list(moved), "deck")
    eligible = sorted({c for c in moved
                       if E.cost_ge(game, c, 3) and E.cost_le(game, c, 6)})
    if not eligible:
        E.discard(game, pid, list(moved), zone="aside", public=True)
        return
    if len(eligible) == 1:
        _cardinal_take(game, pid, eligible[0], moved)
        return
    E.push_choose_cards(game, pid, "Cardinal", "pick", eligible, 1, 1,
                        "Exile", data={"moved": list(moved)})


def _cardinal_pick(game, pid, frame, choice):
    _cardinal_take(game, pid, choice["cards"][0], frame["data"]["moved"])


def _cardinal_take(game, pid, card, moved):
    """Exile one, discard the rest — in that printed order, so the discard is
    parked FIRST and the Exile's own emit resolves on top of it."""
    rest = list(moved)
    rest.remove(card)
    if rest:
        E.push_auto(game, pid, "Cardinal", "rest", data={"rest": rest})
    E.exile(game, pid, [card], zone="aside")


def _cardinal_rest(game, pid, frame, choice):
    rest = [c for c in frame["data"]["rest"]
            if c in game["seats"][pid]["aside"]]
    if rest:
        E.discard(game, pid, rest, zone="aside", public=True)


# ══ GATEKEEPER ($5, Action–Duration–Attack) ══════════════════════════════════
# "At the start of your next turn, +$3. Until then, when another player gains
#  an Action or Treasure card they don't have an Exiled copy of, they Exile
#  it."
#
# "SETS UP TWO LATER ABILITIES", and the attack half is Haunted Woods' exact
# shape: an until-your-next-turn watcher whose immunity set `add_watcher`
# captures from the play automatically (a Moat-revealing opponent is immune to
# the delayed effect too).
#
# "Gatekeeper Exiles the card BEFORE Continue, Hill Fort, Invasion, Reap
# (FIRST VERSION), Replace, Spell Scroll or Summon can move it" — the
# qualifier matters and was dropped once: the Reap we ship is the 2025 card,
# which gains its Gold straight to the set-aside area and so never moves a
# card Gatekeeper could have Exiled. But "if you choose to move the
# gained card with another ability, your opponent's Gatekeeper CAN'T Exile it"
# — which is the lose-track rule and nothing else: the Exile happens from
# wherever the gain put the card, and a card that has moved since is gone.

def _gatekeeper(game, pid):
    E.add_duration_fx(game, pid, "Gatekeeper", "next")
    E.add_watcher(game, pid, "Gatekeeper", "gain", stage="hit")


def _gatekeeper_next(game, pid, frame, choice):
    E.add_coins(game, 3)


def _gatekeeper_when(game, w, ctx):
    """Join-time pool filter (and the stage keeps its own re-check): ANOTHER
    player, an Action or Treasure, and no Exiled copy already."""
    actor, subject = ctx.get("actor"), ctx.get("subject")
    return (actor is not None and subject is not None and actor != w["owner"]
            and (E.has_type(game, subject, "action")
                 or E.has_type(game, subject, "treasure"))
            and E.on_exile(game, actor, subject) == 0)


def _gatekeeper_hit(game, pid, frame, choice):
    """`pid` is the GATEKEEPER'S OWNER (a watcher's ability lands in its
    owner's pool); the player who Exiles is the gain's actor."""
    d = frame["data"]
    victim, card = d["actor"], d["subject"]
    if E.on_exile(game, victim, card):
        return                  # they acquired a copy since the pool was built
    zone = E.find_card_zone(game, victim, card, (d.get("dest", "discard"),))
    if zone is None:
        E.lost_track(game, victim, card,
                     why="it is no longer where it was gained, so Gatekeeper "
                         "cannot Exile it")
        return
    E.exile(game, victim, [card], zone=zone)


# ══ MASTERMIND ($5, Action–Duration) ═════════════════════════════════════════
# "At the start of your next turn, you may play an Action card from your hand
#  three times."
#
# Rule 4 — "Mastermind's start-of-turn ability is ONE ability, so you can't
# resolve any other start-of-turn abilities in between playing the Action card
# three times" — is the ability pool's atomicity contract, free: a pooled
# ability resolves fully on top of the stack before the remainder re-surfaces.
#
# Rule 1 — "if the card is a Duration, Mastermind stays in play as long as that
# Duration stays in play" — is `link_duration`, attached from a start-of-turn
# stage a whole turn after Mastermind's own entry was created, which is what
# ph. 9's `duration_handle` exists for. Rule 2's CHAIN (Mastermind on
# Mastermind on a Duration) is `link_duration`'s transitivity.

def _mastermind(game, pid):
    E.add_duration_fx(game, pid, "Mastermind", "next")


def _mastermind_next(game, pid, frame, choice):
    actions = sorted({c for c in _hand(game, pid) if E.has_type(game, c, "action")})
    if not actions:
        return
    E.push_choose_cards(game, pid, "Mastermind", "pick", actions, 0, 1,
                        "play three times")


def _mastermind_pick(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    # The two replays are parked BELOW the first play's frames (LIFO), so each
    # play fully resolves before the next — "completely resolve the play
    # ability before playing it again".
    E.push_auto(game, pid, "Mastermind", "again", data={"card": card, "left": 2})
    E.play_action_card(game, pid, card, from_zone="hand")
    if E.has_type(game, card, "duration"):
        _mastermind_link(game, pid, E.duration_handle(game))


def _mastermind_again(game, pid, frame, choice):
    d = frame["data"]
    left = d["left"]
    if left <= 0:
        return
    if left > 1:
        E.push_auto(game, pid, "Mastermind", "again",
                    data={"card": d["card"], "left": left - 1})
    # from_zone=None: the card is already in play (or lost track of) — it is
    # played again without moving, and duration fx pile onto the SAME entry.
    E.play_action_card(game, pid, d["card"], from_zone=None)


def _mastermind_link(game, pid, handle):
    """Make this Mastermind ride the Duration it just played.

    Retiring this Mastermind's own spent entry (and putting the card back into
    `in_play`, where a rider physically sits) was a KERNEL GAP when the batch
    found it, and `link_duration` now does both — leaving the entry
    double-counts the card at Clean-up, dropping it without the `in_play`
    half counts it in no zone at all, and the census catches either.

    The one corner this cannot reach is a Mastermind played OFF-TURN: its
    entry lives in `dur_setup` with `fired` rather than in `duration`, so
    there is nothing to retire and the link is skipped. Nothing in the game
    can play a Mastermind on an opponent's turn.
    """
    if handle is None:
        return False
    return E.link_duration(game, pid, "Mastermind", handle)


# ══ STOCKPILE ($3, Treasure) ═════════════════════════════════════════════════
# "$3. +1 Buy. Exile this."
#
# The $3 is the printed `coins` in cards.py; only the +1 Buy and the Exile are
# an ability. "If you use Coronet, Counterfeit, Crown, Specialist or Tiara to
# play Stockpile twice, you get +$3 and +1 Buy BOTH times" — the second play
# finds nothing in play to Exile, which is the lose-track rule and is logged.
#
# **AUTOPLAY BUCKET: `MANUAL_TREASURES` (bucket 1), deliberately.** Stockpile
# pushes no decision frame and draws/looks/reveals nothing, so buckets 2 and 3
# were both arguable — but it REMOVES ITSELF FROM PLAY, which changes "cards
# you have in play" for everything that counts them, and Menagerie ships the
# card that makes that a real decision: Stampede ("if you have 5 or fewer cards
# in play, gain 5 Horses onto your deck"). Playing it early is sometimes
# exactly right and sometimes exactly wrong, so `AUTOPLAY_LAST` ("later is
# NEVER worse") is false of it and the bulk-play button must not choose for the
# player. Bucket 1 is the documented home for "a Treasure where playing EARLY
# might genuinely be right".

def _stockpile(game, pid):
    E.add_buys(game, 1)
    if "Stockpile" not in _in_play(game, pid):
        E.lost_track(game, pid, "Stockpile", "Exiled",
                     why="it is not in play")
        return
    E.exile(game, pid, ["Stockpile"], zone="in_play")


# ============================================================================
# THE 20 WAYS
# ============================================================================
# Ch. IV WAYS, verbatim: "A Way's ability is available for ALL PLAYERS and can
# be used whenever any Action card is played. When you play an Action card, you
# may choose to resolve the Way INSTEAD of resolving the play ability of the
# Action card." · "A Duration played using a Way doesn't set anything up, so
# it's discarded in Clean-up." · "After-play abilities still trigger." · "You
# can use a Way even when playing an Action card when it's not your turn."
#
# All of that is kernel: `from:"landscape"` routes an unowned landscape's
# ability to the ACTOR, `push_way_offer` builds the two-option prompt,
# `_k_way_offer` calls `cancel_pending_play` and runs the "do" stage with
# `frame["data"]["card"]` = the played Action card, and a cancelled play
# registers no duration fx so "failed to set up" discards it.
#
# ⚠ **"THIS" MEANS THE PLAYED ACTION CARD, NOT THE WAY** for Butterfly,
# Chameleon, Frog, Horse, Rat and Turtle (ch. IV WAYS).
#
# ⚠ **DEVIATION (recorded, not silent):** with two Ways forced onto one board
# (`_WAY_CAP` is 1, so only the `landscapes=` test seam can do it) both offers
# join the same pool and a player could pick both, which ch. VII Way of the
# Chameleon 10 forbids ("if you play a card using another Way, you can't also
# use Way of the Chameleon"). Unreachable on any dealt board.


def _way_card(frame):
    """The PLAYED ACTION CARD — what "this" means on a Way."""
    return frame["data"]["card"]


def _way_when(game, pid, ctx):
    """Every Way applies to an ACTION play. `would_resolve` is also emitted for
    a Capitalism-changed Action played in the Buy phase, which is correct — "you
    can play it using a Way even in your Buy phase" — and that card is still an
    Action, so one test covers both."""
    subject = ctx.get("subject")
    return subject is not None and E.has_type(game, subject, "action")


def _way_of_the_mouse_when(game, pid, ctx):
    """The offer must not be collected when it can do NOTHING (the join-time
    pool rule): with no Mouse card set aside — a board where no unused Action
    costing $2/$3 was available — Way of the Mouse has nothing to play.

    ...and it must NOT be collected for a play OF THE MOUSE CARD ITSELF. Ch.
    VII Way of the Mouse: "if there are two Ways in the game, you may use **the
    other** Way when playing the Mouse card" — the wording excludes this one,
    and it has to, because the Mouse card's own play is an Action play: an
    offer here would play the Mouse card again, and again, for free and
    forever. Only reachable at all once the Mouse card is an ATTACK (the
    reaction window is what re-emits `would_resolve` for a play-while-leaving-
    it play), which is the pairing the ph.-10 cross-set batch opened."""
    return (_way_when(game, pid, ctx) and bool(game.get("mouse_card"))
            and ctx.get("subject") != game["mouse_card"])


def _make_way_offer(way):
    """Every Way's `would_resolve` stage is the same two-option offer. The one
    exception is Way of the Chameleon, which must NOT cancel the play."""
    def offer(game, pid, frame, choice):
        E.push_way_offer(game, pid, way, frame["data"]["subject"], "do")
    offer.__name__ = f"_offer_{way.replace(' ', '_').lower()}"
    return offer


# --- Way of the Butterfly ----------------------------------------------------
# "You may return this to its pile to gain a card costing exactly $1 more than
#  it."
#
# "You may return a NON-KINGDOM card, as long as it belongs to a pile. You may
# NOT return cards that don't belong to a pile, such as Shelters, Zombies, or
# cards from the Black Market deck" — `pile_of` is that test. · "You can't gain
# a card from the same pile you returned a card to (such as a split pile),
# since the returned card will be on top" — which falls out by pricing the
# piles AFTER the return: that pile's face is now the returned card, so it
# costs the same rather than $1 more.

def _w_butterfly(game, pid, frame, choice):
    card = _way_card(frame)
    if card not in _in_play(game, pid):
        # "If you play a card WITHOUT MOVING IT INTO PLAY, and use the Way, you
        # can't return it" (EFFECT WHEN MOVED FROM PLAY).
        E.lost_track(game, pid, card, "returned", why="it is not in play")
        return
    if E.pile_of(game, card) is None:
        E.lost_track(game, pid, card, "returned", why="it belongs to no pile")
        return
    E.push_choose_option(
        game, pid, "Way of the Butterfly", "answer",
        options=[{"id": "yes",
                  "label": f"Return {card} to its pile to gain a card costing "
                           f"exactly $1 more"},
                 {"id": "no", "label": f"Leave {card} in play"}],
        data={"card": card})


def _w_butterfly_answer(game, pid, frame, choice):
    if choice["ids"][0] != "yes":
        return
    card = frame["data"]["card"]
    if not E.return_to_pile(game, pid, card, zone="in_play"):
        E.lost_track(game, pid, card, "returned")
        return
    piles = _supply_piles(game, lambda p: E.cost_eq_card(game, p, card, delta=1))
    if piles:
        E.push_choose_pile(game, pid, "Way of the Butterfly", "gain", piles)


def _w_butterfly_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Way of the Camel --------------------------------------------------------
# "Exile a Gold from the Supply."

def _w_camel(game, pid, frame, choice):
    E.exile(game, pid, ["Gold"], zone="supply")


# --- Way of the Chameleon ----------------------------------------------------
# "Follow this card's instructions; each time that would give you +Cards this
#  turn, you get +$ instead, and vice-versa."
#
# ⚠ **THE ONE WAY THAT DOES NOT REPLACE THE PLAY.** Ch. VII 1: "You RESOLVE THE
# EFFECTS of (the play ability of) the card you played, but all +Cards you get
# this turn are +$ instead"; ch. VII 6 (2023): "unlike with the other Ways,
# with Way of the Chameleon you're FOLLOWING the Action card's play ability.
# This means Enchantress, Enlightenment and Highwayman will still affect the
# card." So it must not call `cancel_pending_play` — and `push_way_offer`'s
# answer stage calls it unconditionally, which is why this Way pushes the same
# two-option prompt itself instead. The labels and option ids are identical, so
# the offer is indistinguishable from the client's side.
#
# The flag is TURN-scoped and sticky (ch. VII 3: "only +Cards and +$ you get
# THIS TURN are changed. For instance if you play Merchant Ship, you get +2
# Cards this turn, but +$ next turn as normal"), which is why it lives in
# `turn_ctx` and not on the play. Everything else — the swap itself, "only what
# YOU get", "−$ is not changed", the −1 Card / −$1 tokens applying to the
# RESULT, and a Duration still staying in play (ch. VII 9) — is kernel
# (`add_cards` / `add_coins`).

def _chameleon_offer(game, pid, frame, choice):
    """THE ONE WAY THAT DOES NOT REPLACE THE PLAY. "You resolve the effects of
    the card you played, but all +Cards you get this turn are +$ instead" —
    and the 2023 ruling is explicit: "unlike with the other Ways, with Way of
    the Chameleon you're FOLLOWING the Action card's play ability."

    So it takes the kernel's own offer with `cancels=False` rather than
    pushing a second copy of the same prompt: the two are identical except for
    that one behaviour, and a duplicate prompt shape is somewhere for them to
    drift apart."""
    E.push_way_offer(game, pid, "Way of the Chameleon",
                     frame["data"]["subject"], "do", cancels=False)


def _w_chameleon(game, pid, frame, choice):
    """Runs only when the player PICKED the Way — the kernel's `_k_way_offer`
    owns the answer now, and calls this as an auto frame (`choice` is None).
    It is the one Way whose pick leaves the parked play ability alone."""
    card = frame["data"]["card"]
    if pid != game["turn"]:
        # "all +Cards YOU get this turn" — the flag lives on the turn, and off
        # turn there is no money pool to swap into anyway ($ evaporates by
        # rule). Setting it would swap the TURN PLAYER's grants instead, so the
        # Way simply does nothing here — and says so.
        E.lost_track(game, pid, card,
                     why="Way of the Chameleon only changes what you get on "
                         "your own turn")
        return
    E._log(game, pid, "way", name="Way of the Chameleon", card=card)
    game["turn_ctx"]["chameleon"] = True


# --- Way of the Frog ---------------------------------------------------------
# "+1 Action. When you discard this from play this turn, put it onto your
#  deck."
#
# "This sets up a WHEN-DISCARD ability" — on the played card, not on the Way.
# The only thing in the pool that discards a card from play is Clean-up, so the
# seam is `cleanup_discard` (fired before anything has moved, which is what
# lets a consumer relocate the card — Scheme's and Horn's seam). · "If you play
# a Duration multiple times with a throne-room and use Way of the Frog one of
# the times, the Duration will not be discarded, so Way of the Frog does
# nothing" — free: a persisting card is not in `leaving_play`.

def _w_frog(game, pid, frame, choice):
    E.add_actions(game, 1)
    if pid != game["turn"]:
        # DEVIATION B13, and it must not be SILENT. Frog 4 says outright that
        # "this Way also works if you use it on an opponent's turn" — the card
        # is discarded from play in THAT turn's Clean-up and should go onto the
        # reactor's deck. It can't: `_end_turn`'s all-seats sweep moves an
        # off-turn seat's `in_play` straight to their discard WITHOUT emitting
        # `cleanup_discard`, so the watcher below could never fire and would
        # simply expire. Registering it anyway would leave a correct-looking
        # trigger that does nothing, which is indistinguishable from a broken
        # one — so say so instead. The real fix is an interruptible off-turn
        # sweep (kernel, scheduled as B13).
        E.lost_track(game, pid, _way_card(frame), "topdecked",
                     why="it is discarded in another player's Clean-up")
        return
    E.add_watcher(game, pid, "Way of the Frog", "cleanup_discard",
                  stage="topdeck", until="turn_end",
                  data={"card": _way_card(frame)})


def _w_frog_when(game, w, ctx):
    return (ctx.get("actor") == w["owner"]
            and ctx.get("subject") == w["data"].get("card"))


def _w_frog_topdeck(game, pid, frame, choice):
    card = frame["data"]["card"]
    if card not in E.leaving_play(game, pid):
        E.lost_track(game, pid, card, "topdecked")
        return
    if not E.topdeck_from_play(game, pid, card):
        E.lost_track(game, pid, card, "topdecked")


# --- Way of the Goat ---------------------------------------------------------
# "Trash a card from your hand." Not optional with a non-empty hand.

def _w_goat(game, pid, frame, choice):
    hand = _hand(game, pid)
    if hand:
        E.push_choose_cards(game, pid, "Way of the Goat", "trash",
                            list(hand), 1, 1, "trash")


def _w_goat_trash(game, pid, frame, choice):
    E.trash(game, pid, choice["cards"])


# --- Way of the Horse --------------------------------------------------------
# "+2 Cards. +1 Action. Return this to its pile."
#
# "If you can't return it, the card STAYS IN PLAY (you still get +2 Cards and
# +1 Action)" — so the bonuses come first and unconditionally.

def _w_horse(game, pid, frame, choice):
    card = _way_card(frame)
    E.add_cards(game, 2, pid)          # not final: the +1 Action follows it
    E.add_actions(game, 1)
    if card not in _in_play(game, pid):
        E.lost_track(game, pid, card, "returned", why="it is not in play")
        return
    if not E.return_to_pile(game, pid, card, zone="in_play"):
        E.lost_track(game, pid, card, "returned", why="it belongs to no pile")


# --- Way of the Mole ---------------------------------------------------------
# "+1 Action. Discard your hand. +3 Cards."
#
# "If you don't have any cards in your hand to discard, you still get +1 Action
# and draw 3 cards" — so the draw is parked unconditionally, and BELOW the
# discard's when-discard triggers (Tunnel/Trail/Weaver), the Scholar shape.

def _w_mole(game, pid, frame, choice):
    E.add_actions(game, 1)
    E.push_auto(game, pid, "Way of the Mole", "draw")
    hand = list(_hand(game, pid))
    if hand:
        E.discard(game, pid, hand)


def _w_mole_draw(game, pid, frame, choice):
    E.add_cards(game, 3, pid, final=True)     # a printed +3 that ENDS the ability


# --- Way of the Monkey -------------------------------------------------------

def _w_monkey(game, pid, frame, choice):
    E.add_buys(game, 1)
    E.add_coins(game, 1)


# --- Way of the Mouse --------------------------------------------------------
# "Play the set-aside card, leaving it there."
#
# Everything that follows from "leaving it there" is the kernel's
# `play_mouse_card`: while-in-play abilities are not active, when-discard
# abilities never trigger, an instruction to move the card is lost track of and
# logged, and "if the Mouse card is Shop or Vassal, any Action card in your
# deck could be played" falls out because the borrowed ability runs in full.

def _w_mouse(game, pid, frame, choice):
    E.play_mouse_card(game, pid)


# --- Way of the Mule ---------------------------------------------------------

def _w_mule(game, pid, frame, choice):
    E.add_actions(game, 1)
    E.add_coins(game, 1)


# --- Way of the Otter --------------------------------------------------------

def _w_otter(game, pid, frame, choice):
    E.add_cards(game, 2, pid, final=True)


# --- Way of the Ox -----------------------------------------------------------

def _w_ox(game, pid, frame, choice):
    E.add_actions(game, 2)


# --- Way of the Owl ----------------------------------------------------------
# "Draw until you have 6 cards in hand."
#
# ⚠ **NOT a printed "+Cards"**, so this is `E.draw` and Way of the Chameleon
# must not touch it: "only card drawing denoted with '+' is changed to +$. For
# instance 'draw 2 cards' is unchanged" (ch. VII Way of the Chameleon 4).
# Watchtower's "draw until you have 6 cards in hand" is the same wording and
# the same call. Recorded in `tests/test_plus_cards.py`'s `DRAW_NOT_PLUS`.

def _w_owl(game, pid, frame, choice):
    n = 6 - len(_hand(game, pid))
    if n > 0:
        # `final_draw`, not `draw`: this ENDS the Way, so a Star Chart owner
        # gets their pick at the shuffle it may cause (the ph.-9 frozen rule —
        # a draw that ends its ability calls final_draw). It is still NOT a
        # printed "+N Cards", so it is not `add_cards` and Way of the
        # Chameleon must leave it alone — the two seams are independent, and
        # the Owl is the card that shows it.
        E.final_draw(game, pid, n)


# --- Way of the Pig ----------------------------------------------------------

def _w_pig(game, pid, frame, choice):
    E.add_cards(game, 1, pid)          # not final: the +1 Action follows it
    E.add_actions(game, 1)


# --- Way of the Rat ----------------------------------------------------------
# "You may discard a Treasure to gain a copy of this."
#
# "You GAIN A COPY of the played card", so an unavailable Supply copy gains
# nothing — and for a split pile whose top card is the other half, there is no
# copy to gain either.

def _w_rat(game, pid, frame, choice):
    card = _way_card(frame)
    treasures = sorted({c for c in _hand(game, pid)
                        if E.has_type(game, c, "treasure")})
    if not treasures:
        return
    E.push_choose_cards(game, pid, "Way of the Rat", "discard", treasures,
                        0, 1, f"discard to gain a copy of {card}",
                        data={"card": card})


def _w_rat_discard(game, pid, frame, choice):
    if not choice["cards"]:
        return
    # the GAIN is parked FIRST so it sits BELOW everything the discard pushes
    E.push_auto(game, pid, "Way of the Rat", "gain",
                data={"card": frame["data"]["card"]})
    E.discard(game, pid, choice["cards"])


def _w_rat_gain(game, pid, frame, choice):
    card = frame["data"]["card"]
    pile = E.pile_of(game, card)
    # GAIN A COPY (ch. VII, p. 49), which names Way of the Rat: "you can only
    # gain a copy of a card IF IT'S AVAILABLE IN THE SUPPLY … the top card of
    # the pile has to have the same name." The Supply clause is the one this
    # set can actually reach every game — Way of the Rat on a played **Horse**
    # would otherwise gain from the 30-card non-Supply pile, which ch. III
    # forbids ("cards from non-Supply piles can only be gained by effects that
    # specifically say to gain them from that pile or effects that name the
    # card"; "gain a copy of this" does neither).
    if pile is None or not E.is_supply_pile(game, pile) \
            or E.pile_top(game, pile) != card:
        E.lost_track(game, pid, card, "gained",
                     why="no copy of it is available in the Supply")
        return
    E.gain(game, pid, pile)


# --- Way of the Seal ---------------------------------------------------------
# "+$1. This turn, when you gain a card, you may put it onto your deck."
#
# An ongoing rest-of-turn when-gain — the Bauble / Travelling Fair shape, so a
# `until="turn_end"` watcher (which correctly does NOT hold anything on the
# table). "You gain a copy BEFORE resolving the card" interactions belong to
# Kiln; this one just relocates a completed gain.

def _w_seal(game, pid, frame, choice):
    E.add_coins(game, 1)
    # NOT stage="offer": every Way's would_resolve trigger already owns
    # ("<Way>", "offer"), and a watcher sharing that key silently turns its own
    # firing into a second Way prompt. The registration loop below now refuses
    # the collision outright.
    E.add_watcher(game, pid, "Way of the Seal", "gain", stage="topdeck_offer",
                  until="turn_end")


def _w_seal_when(game, w, ctx):
    """"When YOU gain a card" — the Seal's user, and only where the card is not
    already on the deck (a topdeck offer that could do nothing is exactly the
    dead pool option the join-time filter exists to keep out)."""
    return (ctx.get("actor") == w["owner"] and ctx.get("subject") is not None
            and ctx.get("dest") != "deck")


def _w_seal_offer(game, pid, frame, choice):
    d = frame["data"]
    card = d.get("subject")
    zone = E.find_card_zone(game, pid, card, (d.get("dest", "discard"),))
    if zone is None:
        E.lost_track(game, pid, card,
                     why="it is no longer where it was gained")
        return
    E.push_choose_option(
        game, pid, "Way of the Seal", "answer",
        options=[{"id": "yes", "label": f"Put the {card} onto your deck"},
                 {"id": "no", "label": "Leave it where it is"}],
        data={"card": card, "zone": zone})


def _w_seal_answer(game, pid, frame, choice):
    if choice["ids"][0] != "yes":
        return
    card, zone = frame["data"]["card"], frame["data"]["zone"]
    if E.find_card_zone(game, pid, card, (zone,)) is None:
        E.lost_track(game, pid, card,
                     why="it moved before Way of the Seal could")
        return
    E.topdeck(game, pid, card, zone=zone, public=True)


# --- Way of the Sheep --------------------------------------------------------

def _w_sheep(game, pid, frame, choice):
    E.add_coins(game, 2)


# --- Way of the Squirrel -----------------------------------------------------
# "+2 Cards at the end of this turn."
#
# `turn_ctx["end_draw"]` (ph. 4, Farrier) — drawn by `_end_turn` AFTER the new
# hand, so the cards are for NEXT turn. "You can use this SEVERAL TIMES in a
# turn, to draw more cards" ⇒ it accumulates.

def _w_squirrel(game, pid, frame, choice):
    if pid != game["turn"]:
        # DEVIATION B13. Squirrel 1 says this Way "also works if you use it on
        # an opponent's turn", and ch. VI's chart files it under "at the end of
        # THIS turn" — the current turn, whoever's it is — so the cards should
        # be drawn by the REACTOR at the end of the turn player's turn.
        #
        # It can't be done today for a mechanical reason, not a rules one:
        # `turn_ctx["end_draw"]` is a SINGLE counter drained for the turn
        # player, so there is nowhere to record someone else's. It is NOT
        # "an off-turn bonus that evaporates" — that rule is about the
        # per-turn Action/Buy/coin POOLS, and drawing is not one of them
        # (`add_cards`' own docstring says so, which is why an off-turn
        # reaction can draw at all). The stated reason here was wrong until
        # the ph.-10 audit corrected it. Needs a per-seat `end_draw` (B13).
        E.lost_track(game, pid, "Way of the Squirrel", "drawn",
                     why="there is no end-of-turn draw for a player whose turn it isn't")
        return
    game["turn_ctx"]["end_draw"] += 2
    E._log(game, pid, "end_draw", count=2)


# --- Way of the Turtle -------------------------------------------------------
# "Set this aside. If you did, play it at the start of your next turn."
#
# NOT OPTIONAL "IF YOU DO": setting it aside is automatic and so is next turn's
# play. "You may then choose to use Turtle again (and so on)" is free — the
# replay goes through `play_action_card`, which emits `would_resolve` again.

def _w_turtle(game, pid, frame, choice):
    card = _way_card(frame)
    if card not in _in_play(game, pid):
        E.lost_track(game, pid, card, "set aside", why="it is not in play")
        return
    E.set_aside(game, pid, [card], zone="in_play")
    E.add_start_fx(game, pid, "Way of the Turtle", "play", data={"card": card})


def _w_turtle_play(game, pid, frame, choice):
    card = frame["data"]["card"]
    if card not in game["seats"][pid]["set_aside"]:
        E.lost_track(game, pid, card, "played")
        return
    E.play_action_card(game, pid, card, from_zone="set_aside",
                       count=(pid == game["turn"]))


# --- Way of the Worm ---------------------------------------------------------
# "Exile an Estate from the Supply."

def _w_worm(game, pid, frame, choice):
    E.exile(game, pid, ["Estate"], zone="supply")


# ============================================================================
# REGISTRATION
# ============================================================================

EFFECTS.update({
    "Black Cat": _black_cat,
    "Sleigh": _sleigh,
    "Sheepdog": _sheepdog,
    "Falconer": _falconer,
    "Village Green": _village_green,
    "Barge": _barge,
    "Coven": _coven,
    "Cardinal": _cardinal,
    "Gatekeeper": _gatekeeper,
    "Mastermind": _mastermind,
    "Stockpile": _stockpile,
})

STAGES.update({
    ("Black Cat", "deal"): _black_cat_deal,
    ("Black Cat", "curse"): _black_cat_curse,
    ("Black Cat", "react"): _black_cat_react,
    ("Sleigh", "horse"): _sleigh_horse,
    ("Sleigh", "react"): _sleigh_react,
    ("Sleigh", "move"): _sleigh_move,
    ("Sleigh", "where"): _sleigh_where,
    ("Sheepdog", "react"): _sheepdog_react,
    ("Falconer", "gain"): _falconer_gain,
    ("Falconer", "react"): _falconer_react,
    ("Village Green", "mode"): _village_green_mode,
    ("Village Green", "bonus"): _village_green_bonus,
    ("Village Green", "on_discard"): _village_green_on_discard,
    ("Village Green", "self_play"): _village_green_self_play,
    ("Village Green", "do_play"): _village_green_do_play,
    ("Barge", "mode"): _barge_mode,
    ("Barge", "bonus"): _barge_bonus,
    ("Coven", "hit"): _coven_hit,
    ("Cardinal", "hit"): _cardinal_hit,
    ("Cardinal", "pick"): _cardinal_pick,
    ("Cardinal", "rest"): _cardinal_rest,
    ("Gatekeeper", "next"): _gatekeeper_next,
    ("Gatekeeper", "hit"): _gatekeeper_hit,
    ("Mastermind", "next"): _mastermind_next,
    ("Mastermind", "pick"): _mastermind_pick,
    ("Mastermind", "again"): _mastermind_again,
    # the Ways' own stages ("do" is what `_k_way_offer` runs)
    ("Way of the Butterfly", "do"): _w_butterfly,
    ("Way of the Butterfly", "answer"): _w_butterfly_answer,
    ("Way of the Butterfly", "gain"): _w_butterfly_gain,
    ("Way of the Camel", "do"): _w_camel,
    ("Way of the Chameleon", "do"): _w_chameleon,
    ("Way of the Frog", "do"): _w_frog,
    ("Way of the Frog", "topdeck"): _w_frog_topdeck,
    ("Way of the Goat", "do"): _w_goat,
    ("Way of the Goat", "trash"): _w_goat_trash,
    ("Way of the Horse", "do"): _w_horse,
    ("Way of the Mole", "do"): _w_mole,
    ("Way of the Mole", "draw"): _w_mole_draw,
    ("Way of the Monkey", "do"): _w_monkey,
    ("Way of the Mouse", "do"): _w_mouse,
    ("Way of the Mule", "do"): _w_mule,
    ("Way of the Otter", "do"): _w_otter,
    ("Way of the Ox", "do"): _w_ox,
    ("Way of the Owl", "do"): _w_owl,
    ("Way of the Pig", "do"): _w_pig,
    ("Way of the Rat", "do"): _w_rat,
    ("Way of the Rat", "discard"): _w_rat_discard,
    ("Way of the Rat", "gain"): _w_rat_gain,
    ("Way of the Seal", "do"): _w_seal,
    ("Way of the Seal", "topdeck_offer"): _w_seal_offer,
    ("Way of the Seal", "answer"): _w_seal_answer,
    ("Way of the Sheep", "do"): _w_sheep,
    ("Way of the Squirrel", "do"): _w_squirrel,
    ("Way of the Turtle", "do"): _w_turtle,
    ("Way of the Turtle", "play"): _w_turtle_play,
    ("Way of the Worm", "do"): _w_worm,
})

TRIGGERS.update({
    # REACTIONS THAT PLAY THEMSELVES (mode "play") and one that DISCARDS itself.
    # No `who` on Black Cat or Falconer: they react to ANOTHER / ANY player's
    # gain, so every holder gets a window, in turn order.
    "Black Cat": [{"on": "gain", "from": "hand", "mode": "play",
                   "stage": "react", "when": _black_cat_when}],
    "Falconer": [{"on": "gain", "from": "hand", "mode": "play",
                  "stage": "react", "when": _falconer_when}],
    "Sheepdog": [{"on": "gain", "from": "hand", "who": "actor", "mode": "play",
                  "stage": "react"}],
    "Sleigh": [{"on": "gain", "from": "hand", "who": "actor",
                "mode": "discard", "stage": "react", "when": _sleigh_when}],
    # "When you discard this OTHER THAN DURING CLEAN-UP" — Clean-up never calls
    # discard(), so the exclusion needs no `when`.
    "Village Green": [{"on": "discard", "from": "self", "stage": "on_discard"}],
})

# THE 20 WAYS — one `would_resolve` consumer each, listed by hand (never a
# comprehension over the LANDSCAPES table: this is the human-reviewed roster,
# the `bot_traits.REVIEWED` lesson).
WAYS = (
    "Way of the Butterfly", "Way of the Camel", "Way of the Chameleon",
    "Way of the Frog", "Way of the Goat", "Way of the Horse",
    "Way of the Mole", "Way of the Monkey", "Way of the Mouse",
    "Way of the Mule", "Way of the Otter", "Way of the Ox", "Way of the Owl",
    "Way of the Pig", "Way of the Rat", "Way of the Seal",
    "Way of the Sheep", "Way of the Squirrel", "Way of the Turtle",
    "Way of the Worm",
)

# per-Way join-time conditions beyond "an Action was played"
_WAY_WHENS = {"Way of the Mouse": _way_of_the_mouse_when}
# Way of the Chameleon does not replace the play, so it takes the kernel's
# offer with `cancels=False` — see `_chameleon_offer`.
_WAY_OFFERS = {"Way of the Chameleon": _chameleon_offer}

for _way in WAYS:
    if (_way, "offer") in STAGES:
        # a Way's `would_resolve` trigger OWNS ("<Way>", "offer"); a helper
        # stage that took the same key would silently replace the offer with
        # itself (or be replaced by it). Way of the Seal did exactly that once.
        raise RuntimeError(f"dontminion: {_way!r} already registers an 'offer' stage")
    STAGES[(_way, "offer")] = _WAY_OFFERS.get(_way) or _make_way_offer(_way)
    TRIGGERS[_way] = [{"on": "would_resolve", "from": "landscape",
                       "stage": "offer",
                       "when": _WAY_WHENS.get(_way, _way_when)}]
del _way

# Join-time watcher filters for the ability pool. Each mirrors its stage's own
# resolve-time guard (a watcher whose ability would no-op must never enter the
# pool — a prompt ordering a no-op against a real ability implies it will do
# something).
WATCHER_WHENS.update({
    ("Gatekeeper", "hit"): _gatekeeper_when,
    ("Way of the Frog", "topdeck"): _w_frog_when,
    ("Way of the Seal", "topdeck_offer"): _w_seal_when,
})

# See the Stockpile block for why bucket 1 rather than 2 or 3.
MANUAL_TREASURES.add("Stockpile")
