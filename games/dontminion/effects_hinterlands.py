"""Hinterlands 2E card effects — all 26 kingdom cards.

Merged from the two batch halves; the per-card notes from each are kept
verbatim below. Registry entries are UNIONED, never re-assigned.

=== batch A notes ===
Border Village, Cartographer, Cauldron, Crossroads, Develop, Farmland,
Guard Dog, Haggler, Highway, Inn, Margrave, Oasis, Wheelwright, Witch's Hut.

  * ALL cost comparisons go through E.cost / E.cost_le / E.cost_eq / E.cost_lt,
    and every type query through E.has_type — never CARDS[x]["types"]. The
    Hinterlands theme is "a cheaper card", which is STRICT: cost_lt, not
    cost_le (Border Village, Haggler).
  * The when-gain theme is the trigger bus' "self" source: Border Village,
    Farmland and Inn fire on ANY gain of themselves (buy, Workshop, Develop),
    never only on a buy. Their gained card lands in the DISCARD pile even when
    the trigger card itself was gained to the deck (GAIN ON WHEN-GAIN, p49).
  * HIGHWAY NEEDS NO NEW COUNTER. Its 2022 text is word for word Bridge's, so
    it increments the existing turn_ctx["bridges"] — the generic turn-scoped
    "-$1 to everything" counter that engine.cost already subtracts and the
    frontend already renders as a "cards cost -N" banner. Being turn-scoped
    (not while-in-play) is also what makes the discount survive the Highway
    being trashed from play, which a COST_MODS entry would not. Do NOT add a
    second counter summed in the same place.
  * HAGGLER 2022 is a per-play watcher, not a while-in-play trigger — the
    Hoard shape verbatim: add_watcher("gain", until="turn_end") reading
    via_buy. Cumulative per play, survives Haggler leaving play, and only
    cards gained AFTER it was played count.
  * CAULDRON counts Actions gained FROM TURN START but only fires if the third
    one lands after Cauldron was played ("the first two could be gained
    before" — p70), so its counter is SEEDED from the turn's gains so far. It
    is an Attack TREASURE: the kernel opens the reaction window on the play,
    and the immune set is captured into the watcher's data because the Curses
    are handed out from a much later stage.
  * WITCH'S HUT reveals both cards BEFORE discarding them, so a discarded
    Trail/Village Green that shuffles the other card away still gives Curses.
    Its attack half also runs from a later stage => it must capture
    game["_atk_immune"] at play time (the Minion/Replace rule).
  * GUARD DOG is a REACTION THAT PLAYS ITSELF (ATTACK_REACTIONS, mode "play"):
    no Action is spent, it grants NO immunity, several may react to one attack,
    and it is discarded in THAT turn's clean-up (the kernel's all-seats sweep).
    Its hand-size check runs AFTER the first +2 Cards.

The EFFECTS/STAGES contract lives in games/dontminion/CLAUDE.md (the frozen
engine API); card code touches the game ONLY through the engine helpers.

=== batch B notes ===
Berserker, Fool's Gold, Jack of All Trades, Nomads, Scheme, Souk,
Spice Merchant, Stables, Trader, Trail, Tunnel, Weaver.

The half that owns the set's REACTIONS-THAT-PLAY-THEMSELVES, the EXCHANGE
primitive, variable production, and the Clean-up hook. Headline rulings:

  * REACTIONS THAT PLAY THEMSELVES (compendium p53) — Trail, Weaver and
    Berserker all play themselves out of a NON-hand zone, so they share one
    lose-track guard (`_self_zone` + E.find_card_zone) and one play helper.
    "This doesn't use up an Action from your Action pool. You discard the card
    in THAT turn's Clean-up phase" — so the play is count=(pid == turn) (an
    off-turn play must not bump the turn player's actions_played) and the
    kernel's all-seats clean-up sweep does the discarding.
  * Trail has THREE self-triggers (gain / trash / discard) and three source
    zones; the WHEN-TRASH one plays it out of `game["trash"]`
    (play_action_card from_zone="trash"): "moving it from trash to play. This
    is not gaining it, but it's yours again. It was still trashed."
  * OFF-TURN RESOURCES — Trail's +1 Action and Nomads' +$2 can be earned on an
    opponent's turn. Card code still calls E.add_actions/E.add_coins with no
    pid: the kernel binds `_actor` around every effect and stage, and a bonus
    earned off-turn EVAPORATES (logged off_turn_bonus) instead of landing in
    the turn player's pool. Never bank it here.
  * TRADER IS AN EXCHANGE, NOT A REPLACEMENT (2020 version). It is registered
    like Watchtower — on="gain", from="hand", who="actor", mode="reveal" — and
    calls E.exchange: "even if you exchanged it, you DID gain the card (and
    triggered any when-gain ability). You DIDN'T gain the Silver." The kernel's
    would-gain protocol is deliberately NOT used (it would suppress the gain
    and every when-gain ability with it).
  * TUNNEL / TRAIL / WEAVER when-discard fire per card AFTER the whole discard
    batch has moved (E.discard's contract) — the compendium's Minion/Militia
    case: with Tunnel + Watchtower in hand you may reveal the Tunnel for its
    Gold, but the Watchtower has already left your hand by then. None of them
    fire in Clean-up (E.discard is not the Clean-up path).
  * SOUK is VARIABLE PRODUCTION: +$7 then -$1 per card in hand as two separate
    add_coins calls (the second NEGATIVE), so the log shows both movements and
    the kernel's floor applies after both — "your money pool can never go below
    $0, but if you had any $ before playing Souk, you might lose more than $7".
  * FOOL'S GOLD is autoplay bucket 3 (plain autoplay): its value depends only
    on how many Fool's Golds you already played, so order among treasures can't
    matter, and playing it pushes no frame / draws / looks / reveals — the bulk
    play stays undoable.
  * BERSERKER's "if you have an Action in play" is the CARDS-YOU-HAVE-IN-PLAY
    rule: in_play PLUS the duration zone's cards PLUS their riders (the _bank /
    _peddler_discount on-table walk), read AT RESOLUTION.
  * SCHEME is registered on "buy_phase_end" (a per-play until="turn_end"
    watcher, the Hoard shape) rather than on the kernel's `cleanup_discard`
    event: `_end_turn` is not interruptible, so a cleanup_discard consumer
    cannot yet MOVE the card. The compendium sanctions this exactly — "2016
    (current) version: you no longer choose a card in the start of Clean-up.
    Rather you choose a card when you discard it from play. THIS HAS NO
    PRACTICAL DIFFERENCE." The watcher shape also buys the two rulings a
    cleanup hook would have had to special-case: it is cumulative per play
    (two Schemes = two offers) and it survives the Scheme being trashed from
    play ("if the removed card had set up future effects — such as Charm or
    Scheme — these continue").

The EFFECTS/STAGES contract lives in games/dontminion/CLAUDE.md (the frozen
engine API); card code touches the game ONLY through the engine helpers.
"""

from . import engine as E


# --- batch A: Border Village, Cartographer, Cauldron, Crossroads, Develop,
#     Farmland, Guard Dog, Haggler, Highway, Inn, Margrave, Oasis,
#     Wheelwright, Witch's Hut ------------------------------------------

def _piles(game, want=None, pred=None):
    """Non-empty supply piles, deterministically ordered, filtered by an
    optional cost and predicate. Every caller prices through engine.cost*."""
    out = []
    for p in sorted(game["supply"]):
        if game["supply"][p] <= 0:
            continue
        if want is not None and not E.cost_eq(game, p, want):
            continue
        if pred is not None and not pred(p):
            continue
        out.append(p)
    return out


# --- Oasis -------------------------------------------------------------------
# +1 Card, +1 Action, +$1, then discard a card. The discard is MANDATORY but
# the bonuses are not contingent on it: "you get +1 Action and +$1 even if you
# don't have a card in your hand to discard" (p125). GET FROM DECK, THEN
# DISCARD (p50) — push_choose_cards clamps mn/mx to a short hand.

def _oasis(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_coins(game, 1)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Oasis", "discard",
                            cards=list(hand), mn=1, mx=1, purpose="discard")


def _oasis_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


# --- Cartographer ------------------------------------------------------------
# +1 Card, +1 Action, then look at the top 4, discard any number, put the rest
# back in any order. REVEAL / LOOK AT CARDS AND DISCARD (p54): the un-discarded
# cards live in `aside` — not hand, not deck — until they are put back. This is
# Rabble's exact shape with a player-chosen discard set instead of a filter.

def _cartographer(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    looked = E.look_top(game, pid, 4)
    if not looked:
        return
    E.push_choose_cards(game, pid, "Cartographer", "discard",
                        cards=list(looked), mn=0, mx=len(looked),
                        purpose="discard", data={"looked": list(looked)})


def _cartographer_discard(game, pid, frame, choice):
    chosen = list(choice["cards"])
    rest = list(frame["data"]["looked"])
    for c in chosen:
        rest.remove(c)
    # "first discard, THEN put cards back" — the kernel helper owns that order
    E.discard_then_putback(game, pid, "Cartographer", chosen, rest)


# --- Margrave ----------------------------------------------------------------
# +3 Cards, +1 Buy; each other player draws a card then discards down to 3.
# DISCARD DOWN TO X (p47) is ONE simultaneous discard — a single discard()
# call, whose per-card emits fire after the whole batch moved (the Tunnel /
# Watchtower ruling turns on exactly that).

def _margrave(game, pid):
    E.draw(game, pid, 3)
    E.add_buys(game, 1)
    E.attack_opponents(game, pid, "Margrave", "hit")


def _margrave_hit(game, pid, frame, choice):
    E.draw(game, pid, 1)
    hand = game["seats"][pid]["hand"]
    if len(hand) > 3:
        n = len(hand) - 3
        E.push_choose_cards(game, pid, "Margrave", "discard",
                            cards=list(hand), mn=n, mx=n, purpose="discard")


def _margrave_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


# --- Crossroads --------------------------------------------------------------
# Reveal your hand, +1 Card per Victory card revealed, and +3 Actions the FIRST
# time a Crossroads is played this turn. The counter is per TURN and keyed on
# the card NAME (any copy counts, and a throne-roomed Crossroads gets the
# Actions only once — p78). turn_ctx["crossroads"] is a lazy transient, like
# turn_ctx["quarries"]: absent on a fresh turn, reset by _fresh_turn_ctx.
# Order is load-bearing: the Victory count is read from the pre-draw hand, so a
# drawn Victory card never counts itself.

def _crossroads(game, pid):
    ctx = game["turn_ctx"]
    n = ctx.get("crossroads", 0) + 1
    ctx["crossroads"] = n
    hand = list(game["seats"][pid]["hand"])
    if hand:
        E.reveal(game, pid, hand, "hand")
    E.draw(game, pid, sum(1 for c in hand if E.has_type(game, c, "victory")))
    if n == 1:
        E.add_actions(game, 3)


# --- Highway -----------------------------------------------------------------
# +1 Card, +1 Action, and this turn every card costs $1 less. See the module
# docstring: this is Bridge's counter, deliberately.

def _highway(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    game["turn_ctx"]["bridges"] += 1


# --- Border Village ----------------------------------------------------------
# +1 Card, +2 Actions. When you GAIN this (any gain, not just a buy), gain a
# CHEAPER card — strictly cheaper than Border Village's CURRENT cost, so a
# Highway shifts the cap with it. Mandatory, but "gain nothing" when no
# non-empty pile qualifies. The cheaper card goes to the discard pile even if
# the Border Village itself was gained to the deck (GAIN ON WHEN-GAIN, p49).

def _border_village(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 2)


def _border_village_on_gain(game, pid, frame, choice):
    cap = E.cost(game, "Border Village")
    piles = _piles(game, pred=lambda p: E.cost_lt(game, p, cap))
    if piles:
        E.push_choose_pile(game, pid, "Border Village", "gain", piles)


def _border_village_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Wheelwright -------------------------------------------------------------
# +1 Card, +1 Action, then you MAY discard a card to gain an Action card
# costing as much as it or less. "DO X TO" (p48): no discard => no gain at all.
# "You may discard a card even if there are no Action cards of that cost or
# less", and the gain may be a copy of the discarded card (p167).
# The pile offer is parked BELOW the discard's own triggers so the discard
# fully resolves first — it can change which piles are non-empty.

def _wheelwright(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Wheelwright", "discard",
                            cards=list(hand), mn=0, mx=1, purpose="discard")


def _wheelwright_discard(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    E.push_auto(game, pid, "Wheelwright", "offer", data={"card": card})
    E.discard(game, pid, [card])


def _wheelwright_offer(game, pid, frame, choice):
    cap = E.cost(game, frame["data"]["card"])
    piles = _piles(game, pred=lambda p: E.has_type(game, p, "action")
                   and E.cost_le(game, p, cap))
    if piles:
        E.push_choose_pile(game, pid, "Wheelwright", "gain", piles)


def _wheelwright_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Develop -----------------------------------------------------------------
# Trash a card from your hand, then gain a card costing exactly $1 more and one
# costing exactly $1 less, ONTO YOUR DECK, in either order (p81). The order is
# a real player choice whenever both sides have candidates. Each pile list is
# rebuilt at the moment of its own gain — "any cost reduction or when-gain
# ability applied after the first card will be in effect when you gain the
# next". Trashing a $0 card gains nothing on the low side. Both cards go to the
# deck, so the SECOND ends up on top of the first (gain(dest="deck") inserts at
# index 0), and the first is lost track of.

def _develop(game, pid):
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Develop", "trash",
                            cards=list(hand), mn=1, mx=1, purpose="trash")


def _develop_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    c = E.cost(game, card)                       # read at TRASH time
    E.trash(game, pid, [card])
    hi = _piles(game, want=c + 1)
    lo = _piles(game, want=c - 1) if c >= 1 else []
    if hi and lo:
        E.push_choose_option(
            game, pid, "Develop", "order",
            options=[{"id": "hi_first", "label": f"Gain the ${c + 1} card first"},
                     {"id": "lo_first", "label": f"Gain the ${c - 1} card first"}],
            data={"cost": c})
    elif hi or lo:
        E.push_auto(game, pid, "Develop", "offer",
                    data={"want": c + 1 if hi else c - 1})


def _develop_order(game, pid, frame, choice):
    c = frame["data"]["cost"]
    first, second = (c + 1, c - 1) if choice["ids"][0] == "hi_first" else (c - 1, c + 1)
    # LIFO: the second offer is parked BELOW the first, so the first gain fully
    # resolves (and can change the board) before the second list is built.
    E.push_auto(game, pid, "Develop", "offer", data={"want": second})
    E.push_auto(game, pid, "Develop", "offer", data={"want": first})


def _develop_offer(game, pid, frame, choice):
    want = frame["data"]["want"]
    if want < 0:
        return
    piles = _piles(game, want=want)
    if piles:
        E.push_choose_pile(game, pid, "Develop", "gain", piles)


def _develop_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"], dest="deck")


# --- Farmland ----------------------------------------------------------------
# A Victory card (2 VP) with a when-GAIN ability (2022; it used to be
# when-buy): trash a card from your hand and gain a NON-Farmland card costing
# exactly $2 more than it. The trash is mandatory when the hand is non-empty;
# the gain does as much as it can (no matching pile => nothing, but the trash
# stands). "not another Farmland" is a NAME exclusion, not a cost one.

def _farmland_on_gain(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Farmland", "trash",
                            cards=list(hand), mn=1, mx=1, purpose="trash")


def _farmland_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    c = E.cost(game, card)
    E.push_auto(game, pid, "Farmland", "offer", data={"want": c + 2})
    E.trash(game, pid, [card])


def _farmland_offer(game, pid, frame, choice):
    piles = _piles(game, want=frame["data"]["want"],
                   pred=lambda p: p != "Farmland")
    if piles:
        E.push_choose_pile(game, pid, "Farmland", "gain", piles)


def _farmland_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Inn ---------------------------------------------------------------------
# +2 Cards, +2 Actions, discard 2 (GET FROM DECK THEN DISCARD — you discard 2
# even if you could not draw 2). When you gain it: reveal any number of Action
# cards from your discard pile and shuffle them into your deck. The just-gained
# Inn is itself a legal choice when it landed in the discard pile, and
# shuffle_into_deck shuffles EVEN WHEN NOTHING IS CHOSEN ("if you shuffle zero
# cards into your deck, you still shuffle" — p109).

def _inn(game, pid):
    E.draw(game, pid, 2)
    E.add_actions(game, 2)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Inn", "discard",
                            cards=list(hand), mn=2, mx=2, purpose="discard")


def _inn_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


def _inn_on_gain(game, pid, frame, choice):
    acts = sorted(c for c in game["seats"][pid]["discard"]
                  if E.has_type(game, c, "action"))
    if not acts:
        E.shuffle_into_deck(game, pid, [])       # zero cards: you still shuffle
        return
    E.push_choose_cards(game, pid, "Inn", "shuffle", cards=acts,
                        mn=0, mx=len(acts),
                        purpose="reveal and shuffle into your deck")


def _inn_shuffle(game, pid, frame, choice):
    cards = list(choice["cards"])
    if cards:
        E.reveal(game, pid, cards, "discard")
    E.shuffle_into_deck(game, pid, cards)


# --- Haggler -----------------------------------------------------------------
# +$2 and, for the rest of THIS TURN, when you gain a card you bought, gain a
# cheaper non-Victory card. The Hoard shape: a per-play until="turn_end"
# watcher, so it is cumulative per play, only sees gains made after the play,
# and keeps firing even if the Haggler is trashed from play mid-turn. The
# bought card's cost is read INSIDE the stage — "if you gain a card that
# changes cost right after you gain it, Haggler follows the new cost" (p102).

def _haggler(game, pid):
    E.add_coins(game, 2)
    E.add_watcher(game, pid, "Haggler", "gain", stage="gain_check",
                  until="turn_end")


def _haggler_gain_check(game, pid, frame, choice):
    d = frame["data"]
    if d["actor"] != d["owner"] or d["owner"] != game["turn"] or not d.get("via_buy"):
        return
    cap = E.cost(game, d["subject"])
    piles = _piles(game, pred=lambda p: not E.has_type(game, p, "victory")
                   and E.cost_lt(game, p, cap))
    if piles:
        E.push_choose_pile(game, d["owner"], "Haggler", "gain", piles)


def _haggler_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])            # its own when-gain applies


# --- Witch's Hut -------------------------------------------------------------
# +4 Cards, then discard 2 cards REVEALED; if both are Actions each other
# player gains a Curse. "You reveal both cards before discarding them. So if
# you discard a Trail or Village Green and playing it makes you shuffle the
# other discarded card into your deck, you still give out Curses" (p168) —
# hence the both-Actions test is evaluated on the revealed pair BEFORE the
# discard resolves anything. A short hand can't satisfy "both", so no Curses.
# The attack half runs from a LATER stage, so the per-play immunity set has to
# be captured during on_play and handed back via immune= (the Minion rule).

def _witchs_hut(game, pid):
    E.draw(game, pid, 4)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Witch's Hut", "discard",
                            cards=list(hand), mn=2, mx=2, purpose="discard",
                            data={"immune": list(game.get("_atk_immune", []))})


def _witchs_hut_discard(game, pid, frame, choice):
    cards = list(choice["cards"])
    if cards:
        E.reveal(game, pid, cards, "hand")       # REVEAL BEFORE DISCARDING
    both = len(cards) == 2 and all(E.has_type(game, c, "action") for c in cards)
    if both:
        # parked below the discard's own triggers: a discarded Trail playing
        # itself must not be able to cancel the Curses
        E.push_auto(game, pid, "Witch's Hut", "curses",
                    data={"immune": frame["data"]["immune"]})
    E.discard(game, pid, cards, public=True)


def _witchs_hut_curses(game, pid, frame, choice):
    E.attack_opponents(game, pid, "Witch's Hut", "curse",
                       immune=frame["data"]["immune"])


def _witchs_hut_curse(game, pid, frame, choice):
    E.gain(game, pid, "Curse")


# --- Cauldron (Treasure-Attack $2, manual) -----------------------------------
# Printed $2 banked by the kernel; +1 Buy, and the THIRD time you gain an
# Action this turn each other player gains a Curse.
#
# The counting rule is the bug trap. "The Cursing ability only triggers if the
# third Action is gained after Cauldron was played. (The first two could be
# gained before.)" (p70) — so the count runs from TURN START while the FIRING
# only happens for a gain after the play. The watcher's n is therefore SEEDED
# with the Actions already gained this turn (the kernel's _turn_gains, its
# Smugglers bookkeeping) and incremented from there.
#
# Cumulative per play: each Cauldron keeps its own counter, identified by the
# index stashed in its data (emit hands stages a COPY of the watcher data, so
# the counter has to be mutated on the LIVE dict via watcher_datas).
# MANUAL_TREASURES: playing it opens an opponent reaction window, i.e. a
# decision frame that can't be answered mid-play_all_treasures.

def _cauldron(game, pid):
    E.add_buys(game, 1)
    seen = sum(1 for c in game.get("_turn_gains", [])
               if E.has_type(game, c, "action"))
    E.add_watcher(game, pid, "Cauldron", "gain", stage="count", until="turn_end",
                  data={"n": seen, "fired": False,
                        "i": len(E.watcher_datas(game, pid, "Cauldron")),
                        # the Curses land from a much later stage; the play's
                        # immunity transient is long gone by then
                        "immune": list(game.get("_atk_immune", []))})


def _cauldron_count(game, pid, frame, choice):
    d = frame["data"]
    if d["actor"] != d["owner"] or d["owner"] != game["turn"]:
        return
    if not E.has_type(game, d["subject"], "action"):
        return
    live = None
    for w in E.watcher_datas(game, d["owner"], "Cauldron"):
        if w.get("i") == d.get("i"):
            live = w
            break
    if live is None:
        return
    live["n"] += 1
    if live["n"] == 3 and not live["fired"]:
        live["fired"] = True                     # a 4th gain does not re-fire
        E.attack_opponents(game, d["owner"], "Cauldron", "curse",
                           immune=d.get("immune"))


def _cauldron_curse(game, pid, frame, choice):
    E.gain(game, pid, "Curse")


# --- Guard Dog ---------------------------------------------------------------
# +2 Cards, and +2 more if you have 5 or fewer cards in hand — CHECKED AFTER
# the first draw ("each time you play a Guard Dog, after drawing two cards,
# check how many cards you have in hand", p101). The played Guard Dog is
# already in play, so it doesn't count itself.
#
# Below the line it is a REACTION THAT PLAYS ITSELF against another player's
# Attack: no Action from the pool, NO immunity granted, repeatable (several
# Guard Dogs may react to one attack, including one drawn off the first — the
# kernel re-opens the window after a stage-less reaction), and discarded in
# that turn's clean-up by the kernel's all-seats sweep.

def _guard_dog(game, pid):
    E.draw(game, pid, 2)
    if len(game["seats"][pid]["hand"]) <= 5:
        E.draw(game, pid, 2)


# --- registration ---------------------------------------------------------





# Playing Cauldron opens an opponent reaction window — a decision frame that
# can't be answered mid-autoplay, and an opponent's decision marks the turn
# revealed, which would take the whole bulk play's undo down with it.


# --- batch B: Berserker, Fool's Gold, Jack of All Trades, Nomads, Scheme,
#     Souk, Spice Merchant, Stables, Trader, Trail, Tunnel, Weaver -------

# ==========================================================================
# shared helpers — the three self-playing reactions and the on-table walk
# ==========================================================================

def _self_zone(frame):
    """WHERE the self-triggered card is, decided from the emit's own context
    rather than guessed: a `gain` carries "dest", a `discard` carries the
    SOURCE "zone" (the card itself is in the discard pile by then), and a
    `trash` carries neither — it is in the shared trash pile."""
    d = frame["data"]
    if "dest" in d:
        return d["dest"]
    if "zone" in d:
        return "discard"
    return "trash"


def _offer_self_play(game, pid, card, frame, stage, label):
    """Offer "you may play it" for a card that just triggered on itself. The
    lose-track rule is checked BEFORE the offer (something may already have
    moved the card — a Watchtower that trashed the gained Trail) and AGAIN in
    the answering stage: "cards that are lost track of can't be played"."""
    zone = _self_zone(frame)
    if E.find_card_zone(game, pid, card, (zone,)) is None:
        # SAY SO. Discard two Trails and play the first: its +1 Card can shuffle
        # the discard pile — the second Trail with it — and that copy is now
        # lost track of, so its offer never opens. Correct (compendium p168
        # walks through exactly this), but silently skipping the second prompt
        # reads as the trigger having failed to fire. Reported as a bug from a
        # real game; the log line is the whole fix.
        E.lost_track(game, pid, card, "played")
        return
    E.push_choose_option(game, pid, card, stage,
                         options=[{"id": "play", "label": label},
                                  {"id": "decline", "label": "Don't play it"}],
                         pick=1, data={"zone": zone})


def _resolve_self_play(game, pid, card, frame, choice):
    if choice["ids"][0] != "play":
        return
    zone = E.find_card_zone(game, pid, card, (frame["data"]["zone"],))
    if zone is None:
        E.lost_track(game, pid, card, "played")   # moved since the window opened
        return
    # REACTION THAT PLAYS ITSELF: no Action is spent, and an off-turn play must
    # not count toward the TURN player's actions_played (Conspirator's counter)
    E.play_action_card(game, pid, card, from_zone=zone,
                       count=(pid == game["turn"]))


def _on_table(game, pid):
    """"Cards you have in play" (compendium p47): in_play plus the persisting
    duration entries and their riders — a Duration can be in play without
    having been played this turn — and never a trashed/removed card."""
    seat = game["seats"][pid]
    out = list(seat["in_play"])
    for e in seat.get("duration", []):
        out.append(e["card"])
        out.extend(e.get("riders", []))
    return out


# ==========================================================================
# B1. Stables — $5 Action
# "You may discard a Treasure, for +3 Cards and +1 Action."
# "DO X FOR" (p48): at most once and CONTINGENT — no discard, no +s at all.
# The discarded Treasure can be reshuffled back in by the draw (DISCARD, THEN
# GET FROM DECK) — E.draw gives that for free.
# ==========================================================================

def _stables(game, pid):
    treasures = [c for c in game["seats"][pid]["hand"]
                 if E.has_type(game, c, "treasure")]
    if treasures:
        E.push_choose_cards(game, pid, "Stables", "discard",
                            cards=treasures, mn=0, mx=1, purpose="discard")


def _stables_discard(game, pid, frame, choice):
    if not choice["cards"]:
        return                       # declined: no +3 Cards, no +1 Action
    E.discard(game, pid, choice["cards"])
    E.draw(game, pid, 3)
    E.add_actions(game, 1)


# ==========================================================================
# B2. Spice Merchant — $4 Action
# "You may trash a Treasure from your hand to choose one: +2 Cards and
#  +1 Action; or +1 Buy and +$2."
# "DO X TO" (p48): no trash => the mode choice is never offered at all.
# The trash resolves (and fires its when-trash triggers) BEFORE the options.
# ==========================================================================

def _spice_merchant(game, pid):
    treasures = [c for c in game["seats"][pid]["hand"]
                 if E.has_type(game, c, "treasure")]
    if treasures:
        E.push_choose_cards(game, pid, "Spice Merchant", "trash",
                            cards=treasures, mn=0, mx=1, purpose="trash")


def _spice_merchant_trash(game, pid, frame, choice):
    if not choice["cards"]:
        return                       # no trash -> no options
    E.push_choose_option(game, pid, "Spice Merchant", "mode",
                         options=[{"id": "cards", "label": "+2 Cards and +1 Action"},
                                  {"id": "coins", "label": "+1 Buy and +$2"}],
                         pick=1)
    E.trash(game, pid, choice["cards"])


def _spice_merchant_mode(game, pid, frame, choice):
    if choice["ids"][0] == "cards":
        E.draw(game, pid, 2)
        E.add_actions(game, 1)
    else:
        E.add_buys(game, 1)
        E.add_coins(game, 2)


# ==========================================================================
# B3. Jack of All Trades — $4 Action
# "Gain a Silver. Look at the top card of your deck; you may discard it. Draw
#  until you have 5 cards in hand. You may trash a non-Treasure card from your
#  hand."
# FOUR steps, each parked so triggered abilities interleave correctly: "if you
# play Jack of All Trades and discard a Tunnel from the top of your deck, you
# gain the Gold from Tunnel's when-discard BEFORE drawing to five cards in
# hand" (TRIGGERED ABILITY, p54). Every step pushes the NEXT step first, so
# whatever the current step triggers lands on top of it and resolves first.
# ==========================================================================

def _jack(game, pid):
    E.push_auto(game, pid, "Jack of All Trades", "look")
    E.gain(game, pid, "Silver")      # empty pile: gain nothing, carry on


def _jack_look(game, pid, frame, choice):
    looked = E.look_top(game, pid, 1)
    E.push_auto(game, pid, "Jack of All Trades", "draw")
    if looked:
        # REVEAL/LOOK AT CARDS AND DISCARD (p54): it sits in `aside` — not in
        # hand, not in the deck — while the player decides.
        E.push_choose_option(game, pid, "Jack of All Trades", "top",
                             options=[{"id": "discard",
                                       "label": f"Discard the {looked[0]}"},
                                      {"id": "keep",
                                       "label": f"Keep the {looked[0]} on top"}],
                             pick=1, data={"card": looked[0]})


def _jack_top(game, pid, frame, choice):
    card = frame["data"]["card"]
    if choice["ids"][0] == "discard":
        E.discard(game, pid, [card], zone="aside", public=True)
    else:
        E.deck_from_aside(game, pid, [card])


def _jack_draw(game, pid, frame, choice):
    n = 5 - len(game["seats"][pid]["hand"])
    if n > 0:
        E.draw(game, pid, n)
    # "a non-Treasure card" — has_type, so a Charlatan-game Curse (a Treasure)
    # is correctly NOT trashable here
    hand = game["seats"][pid]["hand"]
    others = [c for c in hand if not E.has_type(game, c, "treasure")]
    if others:
        E.push_choose_cards(game, pid, "Jack of All Trades", "trash",
                            cards=others, mn=0, mx=1, purpose="trash")


def _jack_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, choice["cards"])


# ==========================================================================
# B4. Tunnel — $3 Victory-Reaction, 2 VP
# "When you discard this other than during Clean-up, you may reveal it to gain
#  a Gold."
# No EFFECTS entry (a Victory card is never played). The reveal is the COST of
# the ability, not a separate trigger: "you don't gain a Gold if Tunnel is
# revealed for some other reason". Clean-up can't fire it — _end_turn never
# goes through E.discard.
# ==========================================================================

def _tunnel_on_discard(game, pid, frame, choice):
    if E.find_card_zone(game, pid, "Tunnel", ("discard",)) is None:
        E.lost_track(game, pid, "Tunnel", "revealed")   # nothing left to reveal
        return
    E.push_choose_option(game, pid, "Tunnel", "reveal",
                         options=[{"id": "reveal",
                                   "label": "Reveal Tunnel to gain a Gold"},
                                  {"id": "decline", "label": "Don't reveal it"}],
                         pick=1)


def _tunnel_reveal(game, pid, frame, choice):
    if choice["ids"][0] != "reveal":
        return
    if E.find_card_zone(game, pid, "Tunnel", ("discard",)) is None:
        E.lost_track(game, pid, "Tunnel", "revealed")
        return
    E.reveal(game, pid, ["Tunnel"], "discard")
    E.gain(game, pid, "Gold")        # empty pile: the reveal still happened


# ==========================================================================
# B5. Nomads — $4 Action
# "+1 Buy / +$2 / When you gain or trash this, +$2."
# EFFECTS WHEN IT'S NOT YOUR TURN (p48): the +$2 belongs to whoever gained or
# trashed it, and Nomads can be gained OR trashed on an opponent's turn. The
# kernel binds `_actor` to the stage's pid, so a plain add_coins credits the
# right player — and evaporates off-turn instead of handing the attacker $2.
# Both triggers fire independently: gained and then trashed pays twice.
# ==========================================================================

def _nomads(game, pid):
    E.add_buys(game, 1)
    E.add_coins(game, 2)


def _nomads_bonus(game, pid, frame, choice):
    E.add_coins(game, 2)


# ==========================================================================
# B6. Souk — $5 Action
# "+1 Buy / +$7 / -$1 per card in your hand (you can't go below $0)."
# "When you gain this, trash up to 2 cards from your hand."
# VARIABLE PRODUCTION (p56): counted when the effect RESOLVES; later draws
# never change it. The Souk itself is already in in_play, so it isn't counted.
# Two add_coins calls, not one expression: the log shows both movements and
# the $0 floor lives inside add_coins ("you might lose more than $7").
# ==========================================================================

def _souk(game, pid):
    E.add_buys(game, 1)
    E.add_coins(game, 7)
    E.add_coins(game, -len(game["seats"][pid]["hand"]))


def _souk_on_gain(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Souk", "trash",
                            cards=list(hand), mn=0, mx=2, purpose="trash")


def _souk_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, choice["cards"])   # ONE event: "trash several at once"


# ==========================================================================
# B7. Fool's Gold — $2 Treasure-Reaction (printed $0 in data)
# "If this is the first time you played a Fool's Gold this turn, +$1,
#  otherwise +$4."
# "When another player gains a Province, you may trash this from your hand, to
#  gain a Gold onto your deck."
# The counter is per TURN and keyed on the NAME (any copy counts). The
# reaction is NOT who="actor" — it is offered to every OTHER holder, in turn
# order, and may fire on your own turn if you made an opponent gain a
# Province. Trashing a Fool's Gold any other way gains nothing, which is why
# this is a self-contained reaction stage and never a when-trash trigger.
# ==========================================================================

def _fools_gold(game, pid):
    n = game["turn_ctx"].get("fools_gold", 0) + 1
    game["turn_ctx"]["fools_gold"] = n
    E.add_coins(game, 1 if n == 1 else 4)


def _fools_gold_when(game, pid, ctx):
    return ctx["subject"] == "Province" and ctx["actor"] != pid


def _fools_gold_react(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if "Fool's Gold" not in game["seats"][pid]["hand"]:
        return                       # an earlier window already spent it
    E.trash(game, pid, ["Fool's Gold"])
    E.gain(game, pid, "Gold", dest="deck")
    if "Fool's Gold" in game["seats"][pid]["hand"]:
        # "You may react with several Fool's Golds to the same gained Province"
        E.push_choose_option(game, pid, "Fool's Gold", "react",
                             options=[{"id": "play",
                                       "label": "Trash Fool's Gold to gain a Gold onto your deck"},
                                      {"id": "decline", "label": "Don't react"}],
                             pick=1, data=dict(frame["data"]))


# ==========================================================================
# B8. Trader — $4 Action-Reaction
# "Trash a card from your hand. Gain a Silver per $1 it costs."
# "When you gain a card, you may reveal this from your hand, to exchange the
#  card for a Silver."
# The 2020 (current) version. The reaction is an EXCHANGE, so the gain already
# COMPLETED and every when-gain ability of the gained card fired; the Silver is
# NOT gained (no event, no when-gain chain of its own). Cost is read at trash
# time, so a cost reduction gives fewer Silvers; the Silvers are gained ONE AT
# A TIME (each its own event, its own Trader window, and the pile may run dry).
# ==========================================================================

def _trader(game, pid):
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Trader", "trash",
                            cards=list(hand), mn=1, mx=1, purpose="trash")


def _trader_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    n = E.cost(game, card)           # AT TRASH TIME: a Highway means one fewer
    if n > 0:
        E.push_auto(game, pid, "Trader", "silvers", data={"n": n})
    E.trash(game, pid, [card])


def _trader_silvers(game, pid, frame, choice):
    n = frame["data"]["n"]
    if n <= 0:
        return
    if n > 1:
        E.push_auto(game, pid, "Trader", "silvers", data={"n": n - 1})
    E.gain(game, pid, "Silver")


def _trader_react(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if "Trader" not in game["seats"][pid]["hand"]:
        return                       # moved since the window opened
    E.reveal(game, pid, ["Trader"], "hand")   # revealed, so it stays in hand
    d = frame["data"]
    # "You return the card to its pile no matter where you gained it from. You
    # place the Silver in your discard pile no matter where you gained the card
    # to." exchange() no-ops if the card moved, or if no Silvers are left.
    E.exchange(game, pid, d["gained"], "Silver", zone=d.get("dest", "discard"))


# ==========================================================================
# B9. Weaver — $4 Action-Reaction
# "Gain two Silvers or a card costing up to $4."
# "When you discard this other than in Clean-up, you may play it."
# SEVERAL OPTIONS (p54): you may pick an option you can't carry out (empty
# Silver pile / no eligible pile => gain what you can, or nothing).
# ==========================================================================

def _weaver(game, pid):
    E.push_choose_option(game, pid, "Weaver", "mode",
                         options=[{"id": "silvers", "label": "Gain two Silvers"},
                                  {"id": "card",
                                   "label": "Gain a card costing up to $4"}],
                         pick=1)


def _weaver_mode(game, pid, frame, choice):
    if choice["ids"][0] == "silvers":
        E.push_auto(game, pid, "Weaver", "silvers", data={"n": 2})
        return
    piles = sorted(p for p in game["supply"]
                   if game["supply"][p] > 0 and E.cost_le(game, p, 4))
    if piles:
        E.push_choose_pile(game, pid, "Weaver", "gain", piles)


def _weaver_silvers(game, pid, frame, choice):
    n = frame["data"]["n"]
    if n <= 0:
        return
    if n > 1:
        E.push_auto(game, pid, "Weaver", "silvers", data={"n": n - 1})
    E.gain(game, pid, "Silver")      # separate events: each is exchangeable


def _weaver_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


def _weaver_on_discard(game, pid, frame, choice):
    _offer_self_play(game, pid, "Weaver", frame, "self_play",
                     "Play the discarded Weaver")


def _weaver_self_play(game, pid, frame, choice):
    _resolve_self_play(game, pid, "Weaver", frame, choice)


# ==========================================================================
# B10. Trail — $4 Action-Reaction
# "+1 Card / +1 Action"
# "When you gain, trash, or discard this, other than in Clean-up, you may play
#  it."
# Three self-triggers over three source zones. The when-TRASH play moves it out
# of game["trash"] into play: "this is not gaining it, but it's yours again. It
# was still trashed." Watchtower trashing a just-gained Trail triggers BOTH
# when-gain and when-trash, but the lose-track guard means it can only play
# itself once.
# ==========================================================================

def _trail(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)           # off-turn: evaporates (no pool to join)


def _trail_on_event(game, pid, frame, choice):
    _offer_self_play(game, pid, "Trail", frame, "self_play", "Play the Trail")


def _trail_self_play(game, pid, frame, choice):
    _resolve_self_play(game, pid, "Trail", frame, choice)


# ==========================================================================
# B11. Berserker — $5 Action-Attack
# "Gain a card costing less than this. Each other player discards down to 3
#  cards in hand."
# "When you gain this, if you have an Action in play, play this."
# The attack part runs from a LATER stage (after the gain pile choice), so the
# play's immunity set MUST be captured into the frame data during on_play — the
# _atk_immune transient is gone by then (the Minion/Replace rule).
# The when-gain play is NOT optional ("play this", not "you may play this") and
# its condition is read AT RESOLUTION: an Action played on when-gain counts.
# ==========================================================================

def _berserker(game, pid):
    immune = list(game.get("_atk_immune", []))
    cap = E.cost(game, "Berserker")          # CURRENT cost (Highway/Bridge)
    piles = sorted(p for p in game["supply"]
                   if game["supply"][p] > 0 and E.cost_lt(game, p, cap))
    if piles:
        E.push_choose_pile(game, pid, "Berserker", "gain", piles,
                           data={"immune": immune})
    else:
        E.attack_opponents(game, pid, "Berserker", "hit", immune=immune)


def _berserker_gain(game, pid, frame, choice):
    E.attack_opponents(game, pid, "Berserker", "hit",
                       immune=frame["data"]["immune"])
    E.gain(game, pid, choice["pile"])        # gain first, then they discard


def _berserker_hit(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    if len(hand) > 3:
        n = len(hand) - 3
        E.push_choose_cards(game, pid, "Berserker", "discard",
                            cards=list(hand), mn=n, mx=n, purpose="discard")


def _berserker_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])    # ONE batch (discard down to x)


def _berserker_on_gain(game, pid, frame, choice):
    if not any(E.has_type(game, c, "action") for c in _on_table(game, pid)):
        return                               # read AT RESOLUTION, not at gain
    zone = E.find_card_zone(game, pid, "Berserker", (_self_zone(frame),))
    if zone is None:
        E.lost_track(game, pid, "Berserker", "played")   # a Watchtower moved it
        return
    E.play_action_card(game, pid, "Berserker", from_zone=zone,
                       count=(pid == game["turn"]))


# ==========================================================================
# B12. Scheme — $3 Action
# "+1 Card / +1 Action / This turn, you may put one of your Action cards onto
#  your deck when you discard it from play."
# Registered as a per-play until="turn_end" watcher on "buy_phase_end" (the
# Hoard shape), i.e. the pre-2016 "at the start of Clean-up, choose a card"
# timing, which the compendium says has NO PRACTICAL DIFFERENCE from the
# current wording. See the module docstring: the kernel's `cleanup_discard`
# event fires but _end_turn is not interruptible, so a consumer there cannot
# move the card. Consequences of the watcher shape, both correct:
#   * cumulative per play (a throne-roomed Scheme offers twice), and
#   * it survives the Scheme being trashed from play ("set up future effects
#     ... these continue").
# A Duration that will STAY on the table is not a candidate ("if a card is not
# discarded ... Scheme can't put it onto your deck").
# ==========================================================================

def _scheme(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_watcher(game, pid, "Scheme", "buy_phase_end", stage="cleanup",
                  until="turn_end")


def _scheme_cleanup(game, pid, frame, choice):
    if frame["data"].get("actor") != pid:
        return
    # E.leaving_play covers in_play AND a Duration finishing at THIS clean-up
    # (plus its riders) — that Duration is being discarded from play too, so it
    # is a legal Scheme target. Reading in_play alone hid it.
    cands = [c for c in E.leaving_play(game, pid) if E.has_type(game, c, "action")]
    if cands:
        E.push_choose_cards(game, pid, "Scheme", "topdeck",
                            cards=cands, mn=0, mx=1,
                            purpose="put onto your deck")


def _scheme_topdeck(game, pid, frame, choice):
    if not choice["cards"]:
        return
    E.topdeck_from_play(game, pid, choice["cards"][0])   # False = lost track


# --- registration ---------------------------------------------------------




# No MANUAL_TREASURES / AUTOPLAY_LAST / ATTACK_REACTIONS / COST_MODS /
# DYN_COSTS / BUY_GATES in this half — deliberately not declared empty, because
# the two halves are CONCATENATED into one module at integration and a second
# `X = set()` would silently clobber the other half's entries (batch A owns
# MANUAL_TREASURES = {"Cauldron"} and ATTACK_REACTIONS = {"Guard Dog": ...}).
# Fool's Gold is autoplay bucket 3: its value depends only on how many Fool's
# Golds you already played this turn, so order among treasures is irrelevant to
# the total, and playing it pushes no frame and draws/looks/reveals nothing —
# the bulk play stays undoable.


# --- registration (UNION of both halves) ---------------------------------

EFFECTS = {
    "Border Village": _border_village,
    "Cartographer": _cartographer,
    "Cauldron": _cauldron,
    "Crossroads": _crossroads,
    "Develop": _develop,
    "Guard Dog": _guard_dog,
    "Haggler": _haggler,
    "Highway": _highway,
    "Inn": _inn,
    "Margrave": _margrave,
    "Oasis": _oasis,
    "Wheelwright": _wheelwright,
    "Witch's Hut": _witchs_hut,
    # Farmland is a Victory card — never played, so no EFFECTS entry.,

    "Berserker": _berserker,
    "Fool's Gold": _fools_gold,
    "Jack of All Trades": _jack,
    "Nomads": _nomads,
    "Scheme": _scheme,
    "Souk": _souk,
    "Spice Merchant": _spice_merchant,
    "Stables": _stables,
    "Trader": _trader,
    "Trail": _trail,
    "Weaver": _weaver,
}

STAGES = {
    ("Border Village", "on_gain"): _border_village_on_gain,
    ("Border Village", "gain"): _border_village_gain,
    ("Cartographer", "discard"): _cartographer_discard,
    ("Cauldron", "count"): _cauldron_count,
    ("Cauldron", "curse"): _cauldron_curse,
    ("Develop", "trash"): _develop_trash,
    ("Develop", "order"): _develop_order,
    ("Develop", "offer"): _develop_offer,
    ("Develop", "gain"): _develop_gain,
    ("Farmland", "on_gain"): _farmland_on_gain,
    ("Farmland", "trash"): _farmland_trash,
    ("Farmland", "offer"): _farmland_offer,
    ("Farmland", "gain"): _farmland_gain,
    ("Haggler", "gain_check"): _haggler_gain_check,
    ("Haggler", "gain"): _haggler_gain,
    ("Inn", "discard"): _inn_discard,
    ("Inn", "on_gain"): _inn_on_gain,
    ("Inn", "shuffle"): _inn_shuffle,
    ("Margrave", "hit"): _margrave_hit,
    ("Margrave", "discard"): _margrave_discard,
    ("Oasis", "discard"): _oasis_discard,
    ("Wheelwright", "discard"): _wheelwright_discard,
    ("Wheelwright", "offer"): _wheelwright_offer,
    ("Wheelwright", "gain"): _wheelwright_gain,
    ("Witch's Hut", "discard"): _witchs_hut_discard,
    ("Witch's Hut", "curses"): _witchs_hut_curses,
    ("Witch's Hut", "curse"): _witchs_hut_curse,

    ("Berserker", "gain"): _berserker_gain,
    ("Berserker", "hit"): _berserker_hit,
    ("Berserker", "discard"): _berserker_discard,
    ("Berserker", "on_gain"): _berserker_on_gain,
    ("Fool's Gold", "react"): _fools_gold_react,
    ("Jack of All Trades", "look"): _jack_look,
    ("Jack of All Trades", "top"): _jack_top,
    ("Jack of All Trades", "draw"): _jack_draw,
    ("Jack of All Trades", "trash"): _jack_trash,
    ("Nomads", "bonus"): _nomads_bonus,
    ("Scheme", "cleanup"): _scheme_cleanup,
    ("Scheme", "topdeck"): _scheme_topdeck,
    ("Souk", "on_gain"): _souk_on_gain,
    ("Souk", "trash"): _souk_trash,
    ("Spice Merchant", "trash"): _spice_merchant_trash,
    ("Spice Merchant", "mode"): _spice_merchant_mode,
    ("Stables", "discard"): _stables_discard,
    ("Trader", "trash"): _trader_trash,
    ("Trader", "silvers"): _trader_silvers,
    ("Trader", "react"): _trader_react,
    ("Trail", "on_event"): _trail_on_event,
    ("Trail", "self_play"): _trail_self_play,
    ("Tunnel", "on_discard"): _tunnel_on_discard,
    ("Tunnel", "reveal"): _tunnel_reveal,
    ("Weaver", "mode"): _weaver_mode,
    ("Weaver", "silvers"): _weaver_silvers,
    ("Weaver", "gain"): _weaver_gain,
    ("Weaver", "on_discard"): _weaver_on_discard,
    ("Weaver", "self_play"): _weaver_self_play,
}

TRIGGERS = {
    # the Hinterlands when-gain theme: "self" fires on ANY gain of the card
    "Border Village": [{"on": "gain", "from": "self", "stage": "on_gain"}],
    "Farmland": [{"on": "gain", "from": "self", "stage": "on_gain"}],
    "Inn": [{"on": "gain", "from": "self", "stage": "on_gain"}],

    "Berserker": [{"on": "gain", "from": "self", "stage": "on_gain"}],
    # NOT who="actor": every OTHER holder is offered, in turn order, and it may
    # fire on your own turn if you made an opponent gain a Province.
    "Fool's Gold": [{"on": "gain", "from": "hand", "mode": "reveal",
                     "stage": "react", "when": _fools_gold_when}],
    # commutes: the +$2 is decision-free and order-independent, so the ability
    # pool auto-runs it instead of offering "Nomads first or Watchtower first?"
    "Nomads": [{"on": "gain", "from": "self", "stage": "bonus", "commutes": True},
               {"on": "trash", "from": "self", "stage": "bonus", "commutes": True}],
    "Souk": [{"on": "gain", "from": "self", "stage": "on_gain"}],
    # Watchtower's exact shape — an EXCHANGE on a completed gain, never the
    # would-gain replacement protocol (see the module docstring).
    "Trader": [{"on": "gain", "from": "hand", "who": "actor",
                "mode": "reveal", "stage": "react"}],
    "Trail": [{"on": "gain", "from": "self", "stage": "on_event"},
              {"on": "trash", "from": "self", "stage": "on_event"},
              {"on": "discard", "from": "self", "stage": "on_event"}],
    "Tunnel": [{"on": "discard", "from": "self", "stage": "on_discard"}],
    "Weaver": [{"on": "discard", "from": "self", "stage": "on_discard"}],
}

ATTACK_REACTIONS = {
    "Guard Dog": {"label": "Play Guard Dog (+2 Cards, +2 more if you have 5 "
                           "or fewer cards in hand)",
                  "immunity": False, "mode": "play", "repeatable": True},
}

MANUAL_TREASURES = {"Cauldron"}


# Join-time watcher filters for the ability pool (contract in effects.py) —
# each mirrors its stage's own resolve-time guard.
WATCHER_WHENS = {
    ("Haggler", "gain_check"): lambda game, w, ctx: (
        ctx["actor"] == w["owner"] == game["turn"] and bool(ctx.get("via_buy"))),
    # `final` (ph. 9): Scheme prints "when you discard it from play" and only
    # RIDES buy_phase_end (deviation B1). Villa can end a Buy phase mid-turn,
    # and topdecking the Scheme then would take it off a table still in use.
    ("Scheme", "cleanup"): lambda game, w, ctx: (
        ctx["actor"] == w["owner"] and ctx.get("final", True)
        and any(E.has_type(game, c, "action")
                for c in E.leaving_play(game, w["owner"]))),
}
