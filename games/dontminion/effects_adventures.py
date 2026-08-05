"""Adventures card effects — 30 kingdom cards, the 8 Traveller upgrades and the
20 Events.

Sources: names/costs/types from the wiki chart via dominionstrategy's card list,
behaviour and every edge case from the Knutsen compendium v11.1 ch. VII. The
LANDSCAPE kernel this set consumes was built and contract-tested one phase
earlier (ph. 6H) — see `CLAUDE.md` "Kernel v6H".

**TEN CARDS DIFFER FROM EVERY CARD-LIST SITE, and that is on purpose.** The
compendium's ch. V lists Bonfire, Bridge Troll, Haunted Woods, Inheritance,
Messenger, Plan, Port, Storyteller and Swamp Hag among the cards printed in
2022, and Mission among the 2023 no-third-turn changes. The 2022 pass did two
things across the catalogue — "when-buy triggers were changed to when-gain, and
while-in-play timers were removed" — and both bite here. See `cards.py` for the
per-card list. Any card-list page, and the 2015 rulebook, still show the old
wording; the compendium is this package's source of truth.

The set's four THEMES, and how each lands on the kernel:

  * **RESERVE cards** are played like any Action and then put on the Tavern mat
    by their own ability (`to_tavern`); they wait there until a timed window
    lets their owner CALL them (`from:"tavern"` triggers + `call_card`). Every
    call in the set is a window — start of your turn, on a gain, after
    resolving an Action, at the end of your Buy phase — which is why calling is
    not a move: it has to be ordered in the ability POOL against everything
    else the same occurrence triggered.
  * **EVENTS** are `LANDSCAPE_FX` entries bought with `buy_landscape`. Their
    cost is the PRINTED one ("its cost cannot be changed by cards like
    Bridge"), and buying one is not buying a card — no gain, no buy emit.
  * **TRAVELLERS** exchange upward when discarded from play. That is the ph. 5H
    interruptible Clean-up (`cleanup_discard` fires while the card is still in
    `in_play`) plus ph. 3's `exchange`, which deliberately emits nothing: you
    did not gain the upgrade.
  * **TOKENS** are kernel state, not cards. The four "+" tokens are before-play
    abilities, the Trashing token is a when-gain one, and both are contributed
    to the ability pool by the kernel itself (`_collect_token_abilities`) —
    a token has no `TRIGGERS` entry to hang off.

Rulings that changed an implementation (each read in ch. VII, not recalled):

  * **Champion's +1 Action is a BEFORE-play ability** ("when you play an Action
    card with Champion in effect, you get +1 Action FIRST"), and when you play
    the Champion itself you get +1 Action, not 2 — the before-play window for
    that play opens before the Champion's own ability sets anything up.
  * **Royal Carriage may only be called if the played Action is STILL IN PLAY**,
    may be called several times for the same play, and may not be called after
    calling a Reserve card or after a Duration's start-of-turn ability — which
    falls out of `action_resolved` being emitted only by `play_action_card`.
  * **A Reserve played WITHOUT MOVING IT INTO PLAY doesn't reach the mat**
    (a throne-roomed Ratcatcher, a Band of Misfits copy): "if you play it
    without moving it into play, it won't go to your Tavern mat". Every
    to_tavern here is therefore guarded on the card being in `in_play` — and
    Wine Merchant still gives its +1 Buy and +$4 either way.
  * **Warrior counts Travellers IN PLAY including itself**, and each Warrior
    played re-reads the table, so two Warriors hit for 1 then 2.
  * **Soldier counts OTHER Attack cards in play** — it does not count itself,
    but it does count other Soldiers.
  * **Treasure Hunter reads the right-hand neighbour's LAST COMPLETED turn**,
    which is exactly what the kernel already records for Smugglers.
  * **Giant's victim gains a Curse when their deck is empty** ("if you're
    attacked by Giant but you have no cards in your deck, even after
    shuffling, you gain a Curse").
  * **Magpie does BOTH** when the revealed card is a Treasure-Action or a
    Treasure-Victory: into your hand AND gain a Magpie.
  * **Port's when-gain does not re-trigger** for the Port it gains.
  * **Messenger's when-gain is "your first gain this Buy phase"** and the
    opponents' copies come after your own gain resolves.
  * **Hireling and Champion STAY IN PLAY FOREVER** — `forever=True` entries
    that are never marked done (ph. 7's one duration-kernel addition).
  * **Storyteller pays your whole money pool**, and Coffers may be spent in the
    middle of resolving it — which is what retired deviation B6.
"""

from . import engine as E
from .cards import CARDS, TRAVELLERS

EFFECTS = {}
STAGES = {}
TRIGGERS = {}
WATCHER_WHENS = {}
MANUAL_TREASURES = set()
LANDSCAPE_FX = {}


def _in_play(game, pid, card):
    return card in game["seats"][pid]["in_play"]


def _to_tavern_if_in_play(game, pid, card):
    """"Put this on your Tavern mat" — but "if you play it without moving it
    into play, it won't go to your Tavern mat" (a throne-room replay, a Band of
    Misfits copy). Silent by design: the card is where the player can see it,
    so there is no skipped ability to announce."""
    if _in_play(game, pid, card):
        E.to_tavern(game, pid, card)


def _supply_names(game, pred=None):
    return sorted(n for n in game["supply"]
                  if E.pile_top(game, n) is not None and (pred is None or pred(n)))


def _action_supply_piles(game):
    """Piles an Adventures token may be moved to: "an ACTION Supply pile".

    Read through the PILE's own identity, not its face: "split piles follow the
    Randomizer card", so a Catapult/Rocks pile is an Action pile even when the
    Rocks (a Treasure) are showing — "you can put your +$1 token on the
    Catapult/Rocks pile, and then get +$1 when you play a Catapult or a Rocks".
    An EMPTY pile still counts, because "tokens may be put on an empty pile"."""
    return sorted(n for n in game["supply"] if E.pile_has_type(game, n, "action"))


# ══ $2 ═══════════════════════════════════════════════════════════════════════

# --- Coin of the Realm -------------------------------------------------------
# A $1 Treasure that goes to the mat when played, and is CALLED after you
# finish resolving an Action for +2 Actions. "You may call several Coins of the
# Realm after the same played Action."

def _coin_of_the_realm(game, pid):
    _to_tavern_if_in_play(game, pid, "Coin of the Realm")


def _cotr_call(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if not E.call_card(game, pid, "Coin of the Realm"):
        E.lost_track(game, pid, "Coin of the Realm", "called")
        return
    E.add_actions(game, 2, pid)


# --- Page / Peasant (the two Traveller heads) --------------------------------

def _page(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)


def _peasant(game, pid):
    E.add_buys(game, 1)
    E.add_coins(game, 1)


# --- Ratcatcher --------------------------------------------------------------

def _ratcatcher(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    _to_tavern_if_in_play(game, pid, "Ratcatcher")


def _ratcatcher_call(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if not E.call_card(game, pid, "Ratcatcher"):
        E.lost_track(game, pid, "Ratcatcher", "called")
        return
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Ratcatcher", "trash", sorted(hand),
                            1, 1, "trash")


def _ratcatcher_trash(game, pid, frame, choice):
    E.trash(game, pid, choice["cards"])


# --- Raze --------------------------------------------------------------------
# "+1 Action. Trash this or a card from your hand. Look at one card from your
# deck per $1 the trashed card costs. Put one into your hand, discard the rest."

def _raze(game, pid):
    E.add_actions(game, 1)
    hand = game["seats"][pid]["hand"]
    opts = [{"id": "self", "label": "Trash Raze"}]
    if hand:
        opts.append({"id": "hand", "label": "Trash a card from your hand"})
    E.push_choose_option(game, pid, "Raze", "pick", options=opts)


def _raze_pick(game, pid, frame, choice):
    if choice["ids"][0] == "self":
        # "You get +1 Action even if you trash this", and a Raze played without
        # moving into play simply has nothing to trash — then nothing happens.
        if not _in_play(game, pid, "Raze"):
            E.lost_track(game, pid, "Raze", "trashed")
            return
        n = E.cost(game, "Raze")
        E.push_auto(game, pid, "Raze", "look", data={"n": n})
        E.trash(game, pid, ["Raze"], zone="in_play")
        return
    hand = game["seats"][pid]["hand"]
    if not hand:
        return
    E.push_choose_cards(game, pid, "Raze", "trash", sorted(hand), 1, 1, "trash")


def _raze_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    n = E.cost(game, card)              # read BEFORE the trash (deviation B3)
    E.push_auto(game, pid, "Raze", "look", data={"n": n})
    E.trash(game, pid, [card])


def _raze_look(game, pid, frame, choice):
    n = frame["data"]["n"]
    if n <= 0:
        return
    seen = E.look_top(game, pid, n)
    if not seen:
        return
    E.push_choose_cards(game, pid, "Raze", "keep", sorted(seen), 1, 1, "put into your hand")


def _raze_keep(game, pid, frame, choice):
    kept = choice["cards"]
    E.take_aside(game, pid, kept, dest="hand")
    rest = list(game["seats"][pid]["aside"])
    if rest:
        E.discard(game, pid, rest, zone="aside", public=True)


# ══ $3 ═══════════════════════════════════════════════════════════════════════

# --- Amulet ------------------------------------------------------------------
# "Now and at the start of your next turn, choose one: +$1; or trash a card
# from your hand; or gain a Silver."

_AMULET_OPTS = [{"id": "coin", "label": "+$1"},
                {"id": "trash", "label": "Trash a card from your hand"},
                {"id": "silver", "label": "Gain a Silver"}]


def _amulet(game, pid):
    E.add_duration_fx(game, pid, "Amulet", "again")
    E.push_choose_option(game, pid, "Amulet", "mode", options=list(_AMULET_OPTS))


def _amulet_again(game, pid, frame, choice):
    E.push_choose_option(game, pid, "Amulet", "mode", options=list(_AMULET_OPTS))


def _amulet_mode(game, pid, frame, choice):
    pick = choice["ids"][0]
    if pick == "coin":
        E.add_coins(game, 1, pid)
    elif pick == "silver":
        E.gain(game, pid, "Silver")
    else:
        hand = game["seats"][pid]["hand"]
        if hand:
            E.push_choose_cards(game, pid, "Amulet", "trash", sorted(hand),
                                1, 1, "trash")


def _amulet_trash(game, pid, frame, choice):
    E.trash(game, pid, choice["cards"])


# --- Caravan Guard -----------------------------------------------------------

def _caravan_guard(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_duration_fx(game, pid, "Caravan Guard", "next")


def _caravan_guard_next(game, pid, frame, choice):
    E.add_coins(game, 1, pid)


def _caravan_guard_react(game, pid, frame, choice):
    # a REACTION THAT PLAYS ITSELF: the kernel's attack window already played
    # it (mode "play") and re-opens the window for us.
    E.reopen_attack_window(game, pid)


# --- Dungeon -----------------------------------------------------------------

def _dungeon(game, pid):
    E.add_actions(game, 1)
    E.add_duration_fx(game, pid, "Dungeon", "again")
    _dungeon_cycle(game, pid)


def _dungeon_again(game, pid, frame, choice):
    _dungeon_cycle(game, pid)


def _dungeon_cycle(game, pid):
    E.draw(game, pid, 2)
    hand = game["seats"][pid]["hand"]
    if hand:
        n = min(2, len(hand))
        E.push_choose_cards(game, pid, "Dungeon", "discard", sorted(hand), n, n,
                            "discard")


def _dungeon_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


# --- Gear --------------------------------------------------------------------

def _gear(game, pid):
    E.draw(game, pid, 2)
    hand = game["seats"][pid]["hand"]
    if not hand:
        return                          # registers nothing: Gear doesn't persist
    E.push_choose_cards(game, pid, "Gear", "aside", sorted(hand), 0,
                        min(2, len(hand)), "set aside")


def _gear_aside(game, pid, frame, choice):
    cards = choice["cards"]
    if not cards:
        return                          # "you may choose to not set aside any"
    E.set_aside_duration(game, pid, cards, zone="hand")
    E.add_duration_fx(game, pid, "Gear", "back", data={"cards": list(cards)})


def _gear_back(game, pid, frame, choice):
    E.take_dur_aside(game, pid, frame["data"]["cards"], dest="hand")


# --- Guide -------------------------------------------------------------------

def _guide(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    _to_tavern_if_in_play(game, pid, "Guide")


def _guide_call(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if not E.call_card(game, pid, "Guide"):
        E.lost_track(game, pid, "Guide", "called")
        return
    hand = list(game["seats"][pid]["hand"])
    if hand:
        E.discard(game, pid, hand)
    E.draw(game, pid, 5)               # "even if you have no cards in hand"


# ══ $4 ═══════════════════════════════════════════════════════════════════════

# --- Duplicate ---------------------------------------------------------------
# Called when you gain a card costing up to $6 — on ANYONE's turn, and several
# Duplicates may be called for the same gain.

def _duplicate(game, pid):
    _to_tavern_if_in_play(game, pid, "Duplicate")


def _duplicate_when(game, pid, ctx):
    got = ctx.get("subject")
    return got is not None and got in CARDS and E.cost_le(game, got, 6)


def _duplicate_call(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if not E.call_card(game, pid, "Duplicate"):
        E.lost_track(game, pid, "Duplicate", "called")
        return
    got = frame["data"].get("gained")
    if got is None:
        return
    pile = E.pile_of(game, got)
    if pile is not None:
        E.gain_from(game, pid, pile)


# --- Magpie ------------------------------------------------------------------

def _magpie(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    seen = E.look_top(game, pid, 1)
    if not seen:
        return
    card = seen[0]
    E.reveal(game, pid, [card], "deck")
    # "If a card is revealed that is both a Treasure and a Victory, or a
    # Treasure and an Action, you do BOTH."
    if E.has_type(game, card, "treasure"):
        E.take_aside(game, pid, [card], dest="hand")
    else:
        E.deck_from_aside(game, pid, [card])       # back on top, as revealed
    if E.has_type(game, card, "action") or E.has_type(game, card, "victory"):
        E.gain(game, pid, "Magpie")


# --- Messenger ---------------------------------------------------------------

def _messenger(game, pid):
    E.add_buys(game, 1)
    E.add_coins(game, 2)
    if game["seats"][pid]["deck"]:
        E.push_choose_option(game, pid, "Messenger", "deck", options=[
            {"id": "yes", "label": "Put your deck into your discard pile"},
            {"id": "no", "label": "Keep your deck"}])


def _messenger_deck(game, pid, frame, choice):
    if choice["ids"][0] == "yes":
        E.deck_to_discard(game, pid)


def _messenger_when(game, pid, ctx):
    # "if it's your first gain this Buy phase". buy_gains counts the gains
    # already made in this Buy phase INCLUDING this one, so the first is 1.
    return game["phase"] == "buy" and game["turn_ctx"]["buy_gains"] <= 1


def _messenger_gain(game, pid, frame, choice):
    picks = _supply_names(game, lambda n: E.cost_le(game, n, 4))
    if not picks:
        return
    E.push_choose_pile(game, pid, "Messenger", "give", picks)


def _messenger_give(game, pid, frame, choice):
    pile = choice["pile"]
    got = E.pile_top(game, pile)
    if not E.gain(game, pid, pile):
        return          # "if you didn't gain the card, the others don't either"
    for o in E.opponents(game, pid):
        E.push_auto(game, o, "Messenger", "copy", data={"card": got})


def _messenger_copy(game, pid, frame, choice):
    pile = E.pile_of(game, frame["data"]["card"])
    if pile is not None:
        E.gain(game, pid, pile)


# --- Miser -------------------------------------------------------------------
# The Coppers go on the TAVERN mat, which is why Miser needs no mat of its own.

def _miser(game, pid):
    opts = [{"id": "put", "label": "Put a Copper from your hand onto your Tavern mat"},
            {"id": "coins", "label": "+$1 per Copper on your Tavern mat"}]
    E.push_choose_option(game, pid, "Miser", "mode", options=opts)


def _miser_mode(game, pid, frame, choice):
    seat = game["seats"][pid]
    if choice["ids"][0] == "put":
        if "Copper" in seat["hand"]:
            E.to_tavern(game, pid, "Copper", zone="hand")
        return
    n = seat["tavern"].count("Copper")
    E.add_coins(game, n, pid)          # +$0 leaves a -$1 token alone (p169)


# --- Port --------------------------------------------------------------------

def _port(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 2)


def _port_when(game, pid, ctx):
    # "When you gain a Port due to Port's when-gain, the when-gain doesn't
    # trigger again" — otherwise the pile empties itself on one buy. The mark
    # rides the gain EVENT rather than a transient, because the would-gain
    # protocol can park the physical gain until long after the call returned.
    return not ctx.get("port_chain")


def _port_gain(game, pid, frame, choice):
    E.gain(game, pid, "Port", port_chain=True)


# --- Ranger ------------------------------------------------------------------

def _ranger(game, pid):
    E.add_buys(game, 1)
    if E.flip_journey(game, pid):
        E.draw(game, pid, 5)


# --- Transmogrify ------------------------------------------------------------

def _transmogrify(game, pid):
    E.add_actions(game, 1)
    _to_tavern_if_in_play(game, pid, "Transmogrify")


def _transmogrify_call(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if not E.call_card(game, pid, "Transmogrify"):
        E.lost_track(game, pid, "Transmogrify", "called")
        return
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Transmogrify", "trash", sorted(hand),
                            1, 1, "trash")


def _transmogrify_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    E.push_auto(game, pid, "Transmogrify", "gain", data={"card": card})
    E.trash(game, pid, [card])


def _transmogrify_gain(game, pid, frame, choice):
    ref = frame["data"]["card"]
    picks = _supply_names(game, lambda n: E.cost_le_card(game, n, ref, 1))
    if picks:
        # "The card is GAINED TO YOUR HAND" (clear in the current card text)
        E.push_choose_pile(game, pid, "Transmogrify", "take", picks)


def _transmogrify_take(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"], dest="hand")


# ══ $5 ═══════════════════════════════════════════════════════════════════════

# --- Artificer ---------------------------------------------------------------

def _artificer(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_coins(game, 1)
    hand = game["seats"][pid]["hand"]
    E.push_choose_cards(game, pid, "Artificer", "discard", sorted(hand),
                        0, len(hand), "discard")


def _artificer_discard(game, pid, frame, choice):
    cards = choice["cards"]
    n = len(cards)
    # "first discard, then gain" — the gain is parked BELOW so a discarded
    # Tunnel/Trail resolves before the choice of what to gain onto the deck
    E.push_auto(game, pid, "Artificer", "gain", data={"n": n})
    if cards:
        E.discard(game, pid, cards)


def _artificer_gain(game, pid, frame, choice):
    n = frame["data"]["n"]
    picks = _supply_names(game, lambda c: E.cost_eq(game, c, n))
    if not picks:
        return
    E.push_choose_option(game, pid, "Artificer", "which", options=(
        [{"id": p, "label": f"Gain {p} onto your deck"} for p in picks]
        + [{"id": "decline", "label": "Gain nothing"}]))


def _artificer_which(game, pid, frame, choice):
    pick = choice["ids"][0]
    if pick != "decline":
        E.gain(game, pid, pick, dest="deck")


# --- Bridge Troll ------------------------------------------------------------
# 2022: the cost reduction is TURN-SCOPED (this turn and your next turn), like
# Highway's — not while-in-play — and it is cumulative with a throne-room.

def _bridge_troll(game, pid):
    for o in E.opponents(game, pid):
        if o in game.get("_atk_immune", []):
            continue
        E.take_seat_token(game, o, "-coin")
    game["turn_ctx"]["bridges"] += 1
    E.add_buys(game, 1)
    E.add_duration_fx(game, pid, "Bridge Troll", "next")


def _bridge_troll_next(game, pid, frame, choice):
    game["turn_ctx"]["bridges"] += 1
    E.add_buys(game, 1)


# --- Distant Lands -----------------------------------------------------------
# Scores 4 VP only while it sits on the mat — engine._vp_of owns that, because
# a flat list of owned card names cannot say where a card is.

def _distant_lands(game, pid):
    _to_tavern_if_in_play(game, pid, "Distant Lands")


# --- Giant -------------------------------------------------------------------

def _giant(game, pid):
    if not E.flip_journey(game, pid):
        E.add_coins(game, 1)
        return
    E.add_coins(game, 5)
    E.attack_opponents(game, pid, "Giant", "hit")


def _giant_hit(game, pid, frame, choice):
    seen = E.look_top(game, pid, 1)
    if not seen:
        # "if you're attacked by Giant but you have no cards in your deck
        # (even after shuffling), you gain a Curse"
        E.gain(game, pid, "Curse")
        return
    card = seen[0]
    E.reveal(game, pid, [card], "deck")
    # the card is still in the `aside` zone, which both kernel movers take a
    # zone for — so this goes through trash()/discard() and gets their logs and
    # their emits, rather than reimplementing either
    if E.cost_ge(game, card, 3) and E.cost_le(game, card, 6):
        E.trash(game, pid, [card], zone="aside")
    else:
        E.discard(game, pid, [card], zone="aside", public=True)
        E.gain(game, pid, "Curse")


# --- Haunted Woods -----------------------------------------------------------
# 2022: triggers when another player GAINS A BOUGHT CARD, not on the buy.

def _haunted_woods(game, pid):
    E.add_duration_fx(game, pid, "Haunted Woods", "next")
    E.add_watcher(game, pid, "Haunted Woods", "gain", stage="hit")


def _haunted_woods_next(game, pid, frame, choice):
    E.draw(game, pid, 3)


def _haunted_woods_when(game, w, ctx):
    return bool(ctx.get("via_buy")) and ctx.get("actor") != w["owner"]


def _haunted_woods_hit(game, pid, frame, choice):
    victim = frame["data"]["actor"]
    hand = game["seats"][victim]["hand"]
    if not hand:
        return
    if len(hand) == 1:
        E.topdeck(game, victim, hand[0], zone="hand", public=True)
        return
    E.push_order_cards(game, victim, "Haunted Woods", "order", cards=list(hand))


def _haunted_woods_order(game, pid, frame, choice):
    for card in reversed(choice["order"]):
        E.topdeck(game, pid, card, zone="hand", public=True)


# --- Lost City ---------------------------------------------------------------

def _lost_city(game, pid):
    E.draw(game, pid, 2)
    E.add_actions(game, 2)


def _lost_city_gain(game, pid, frame, choice):
    for o in E.opponents(game, pid):
        E.push_auto(game, o, "Lost City", "draw")


def _lost_city_draw(game, pid, frame, choice):
    E.draw(game, pid, 1)


# --- Relic -------------------------------------------------------------------
# An Attack TREASURE: the kernel opens the reaction window for it, which is why
# this is in MANUAL_TREASURES (a decision frame can't be answered mid-autoplay).

def _relic(game, pid):
    E.attack_opponents(game, pid, "Relic", "hit")


def _relic_hit(game, pid, frame, choice):
    E.take_seat_token(game, pid, "-card")


# --- Royal Carriage ----------------------------------------------------------

def _royal_carriage(game, pid):
    E.add_actions(game, 1)
    _to_tavern_if_in_play(game, pid, "Royal Carriage")


def _royal_carriage_when(game, pid, ctx):
    # "You may only call Royal Carriage if the played Action card is STILL IN
    # PLAY" — a Mining Village that trashed itself can't be replayed.
    card = ctx.get("subject")
    return card is not None and _in_play(game, pid, card)


def _royal_carriage_call(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    # the offer window files the event's subject under "gained" (the key the
    # kernel's hand/tavern branch uses for every source), not "subject"
    card = frame["data"].get("gained")
    if not E.call_card(game, pid, "Royal Carriage"):
        E.lost_track(game, pid, "Royal Carriage", "called")
        return
    if card is None or not _in_play(game, pid, card):
        E.lost_track(game, pid, card or "the card", "played")
        return
    E.play_action_card(game, pid, card, from_zone=None)


# --- Storyteller -------------------------------------------------------------
# 2022: +1 Card instead of the +$1 the old one paid itself with.

def _storyteller(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    _storyteller_offer(game, pid, 3)


def _storyteller_offer(game, pid, left):
    treasures = sorted({c for c in game["seats"][pid]["hand"]
                        if E.has_type(game, c, "treasure")})
    if left <= 0 or not treasures:
        E.push_auto(game, pid, "Storyteller", "pay")
        return
    E.push_choose_option(game, pid, "Storyteller", "play", data={"left": left},
                         options=([{"id": c, "label": f"Play {c}"} for c in treasures]
                                  + [{"id": "done", "label": "Stop playing Treasures"}]))


def _storyteller_play(game, pid, frame, choice):
    pick = choice["ids"][0]
    if pick == "done":
        E.push_auto(game, pid, "Storyteller", "pay")
        return
    if pick in game["seats"][pid]["hand"]:
        E.play_treasure_card(game, pid, pick)
    _storyteller_offer(game, pid, frame["data"]["left"] - 1)


def _storyteller_pay(game, pid, frame, choice):
    """"Then pay all of your $, and draw a card per $1 you paid." The Potions
    are kept ("you will be left with $0 but will keep any Potions")."""
    n = game["coins"]
    if n:
        game["coins"] = 0
        E._log(game, pid, "minus", coins=n, why="Storyteller")
    E.draw(game, pid, n)


# --- Swamp Hag ---------------------------------------------------------------

def _swamp_hag(game, pid):
    E.add_duration_fx(game, pid, "Swamp Hag", "next")
    E.add_watcher(game, pid, "Swamp Hag", "gain", stage="hit")


def _swamp_hag_next(game, pid, frame, choice):
    E.add_coins(game, 3, pid)


def _swamp_hag_when(game, w, ctx):
    return bool(ctx.get("via_buy")) and ctx.get("actor") != w["owner"]


def _swamp_hag_hit(game, pid, frame, choice):
    E.gain(game, frame["data"]["actor"], "Curse")


# --- Treasure Trove ----------------------------------------------------------

def _treasure_trove(game, pid):
    E.gain(game, pid, "Gold")          # "if there are no Golds left you still
    E.gain(game, pid, "Copper")        #  gain a Copper, and vice versa"


# --- Wine Merchant -----------------------------------------------------------
# Never CALLED — discarded from the mat at the end of your Buy phase.

def _wine_merchant(game, pid):
    E.add_buys(game, 1)
    E.add_coins(game, 4)
    _to_tavern_if_in_play(game, pid, "Wine Merchant")


def _wine_merchant_when(game, pid, ctx):
    return game["coins"] >= 2


def _wine_merchant_end(game, pid, frame, choice):
    if choice["ids"][0] == "play":
        E.discard_from_tavern(game, pid, "Wine Merchant")


# ══ $6 ═══════════════════════════════════════════════════════════════════════

def _hireling(game, pid):
    E.add_duration_fx(game, pid, "Hireling", "each", forever=True)


def _hireling_each(game, pid, frame, choice):
    E.draw(game, pid, 1)


# ══ THE TRAVELLERS ═══════════════════════════════════════════════════════════
# "When you discard this from play, you may exchange it for X." That is the
# ph. 5H interruptible Clean-up: `cleanup_discard` fires while the card is
# still in in_play, so the exchange can take it from there.

def _traveller_when(card):
    """Does THIS Traveller's exchange offer belong to this occurrence?

    The spec is registered `from:"in_play"`, and that source asks only "is the
    card on the table" — so it is consulted on EVERY `cleanup_discard` the
    Clean-up emits, one per card in play, not just on this Traveller's own. The
    identity test is therefore load-bearing: without it a Soldier and a Fugitive
    on the table each collected BOTH offers from BOTH emits (N travellers in
    play ⇒ N² of them), and since `_traveller_offer` reads the EMIT's subject
    rather than the option that was picked, choosing "Fugitive" in the ordering
    prompt exchanged the Soldier. Reported from a real game.
    """
    def when(game, pid, ctx):
        if ctx.get("subject") != card:
            return False
        # no offer when the upgrade's pile is empty — "you may exchange it"
        # cannot be done at all then, and a prompt for an impossible choice is
        # noise
        return E.pile_top(game, TRAVELLERS[card]) is not None
    return when


def _traveller_offer(game, pid, ctx):
    card = ctx["subject"]
    E.push_choose_option(game, pid, card, "exchange", data={"card": card},
                         options=[{"id": "yes", "label": f"Exchange {card} for a {TRAVELLERS[card]}"},
                                  {"id": "no", "label": f"Keep {card}"}])


def _traveller_exchange(game, pid, frame, choice):
    if choice["ids"][0] != "yes":
        return
    card = frame["data"]["card"]
    if E.find_card_zone(game, pid, card, zones=("in_play",)) is None:
        E.lost_track(game, pid, card, "exchanged")
        return
    E.exchange(game, pid, card, TRAVELLERS[card], zone="in_play")


def _treasure_hunter(game, pid):
    E.add_actions(game, 1)
    E.add_coins(game, 1)
    order = game["players"]
    right = order[order.index(pid) - 1]      # the player to your RIGHT
    for _ in range(len(game["last_turn_gains"].get(right, []))):
        E.gain(game, pid, "Silver")


def _warrior(game, pid):
    E.draw(game, pid, 2)
    n = sum(1 for c in game["seats"][pid]["in_play"]
            if E.has_type(game, c, "traveller"))
    if n:
        E.attack_opponents(game, pid, "Warrior", "hit", data={"n": n})


def _warrior_hit(game, pid, frame, choice):
    for _ in range(frame["data"]["n"]):
        seen = E.look_top(game, pid, 1)
        if not seen:
            break
        card = seen[0]
        if E.cost_ge(game, card, 3) and E.cost_le(game, card, 4):
            E.trash(game, pid, [card], zone="aside")
        else:
            E.discard(game, pid, [card], zone="aside", public=True)


def _hero(game, pid):
    E.add_coins(game, 2)
    picks = _supply_names(game, lambda n: E.has_type(game, n, "treasure"))
    if picks:
        E.push_choose_pile(game, pid, "Hero", "gain", picks)


def _hero_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


def _champion(game, pid):
    E.add_actions(game, 1)
    # Two REST-OF-THE-GAME abilities. The immunity rides the kernel's existing
    # `protect` watcher (attack_protected consults it); the +1 Action is a
    # before-play watcher, which is the class the compendium puts it in.
    E.add_watcher(game, pid, "Champion", "protect", until="forever")
    E.add_watcher(game, pid, "Champion", "before_play", stage="bonus",
                  until="forever", commutes=True)


def _champion_when(game, w, ctx):
    # only for the OWNER's own Action plays ("when YOU play an Action card")
    return (ctx.get("actor") == w["owner"] and ctx.get("subject") in CARDS
            and E.has_type(game, ctx["subject"], "action"))


def _champion_bonus(game, pid, frame, choice):
    E.add_actions(game, 1, pid)


def _soldier(game, pid):
    E.add_coins(game, 2)
    # "+$1 per OTHER Attack card you have in play" — not itself, but it does
    # count other Soldiers
    in_play = list(game["seats"][pid]["in_play"])
    if "Soldier" in in_play:
        in_play.remove("Soldier")
    E.add_coins(game, sum(1 for c in in_play if E.has_type(game, c, "attack")))
    E.attack_opponents(game, pid, "Soldier", "hit")


def _soldier_hit(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    if len(hand) >= 4:
        E.push_choose_cards(game, pid, "Soldier", "discard", sorted(hand),
                            1, 1, "discard")


def _soldier_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


def _fugitive(game, pid):
    E.draw(game, pid, 2)
    E.add_actions(game, 1)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Fugitive", "discard", sorted(hand),
                            1, 1, "discard")


def _fugitive_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


def _disciple(game, pid):
    hand = game["seats"][pid]["hand"]
    actions = sorted({c for c in hand if E.has_type(game, c, "action")})
    if actions:
        E.push_choose_cards(game, pid, "Disciple", "pick", actions, 0, 1,
                            "play twice")


def _disciple_pick(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    E.push_auto(game, pid, "Disciple", "second", data={"card": card})
    E.play_action_card(game, pid, card, from_zone="hand")


def _disciple_second(game, pid, frame, choice):
    card = frame["data"]["card"]
    E.push_auto(game, pid, "Disciple", "copy", data={"card": card})
    E.play_action_card(game, pid, card, from_zone=None)
    if E.has_type(game, card, "duration"):
        E.mark_duration_rider(game, pid, card, "Disciple")


def _disciple_copy(game, pid, frame, choice):
    pile = E.pile_of(game, frame["data"]["card"])
    if pile is not None and E.is_supply_pile(game, pile):
        E.gain(game, pid, pile)


def _teacher(game, pid):
    _to_tavern_if_in_play(game, pid, "Teacher")


_TEACHER_TOKENS = [("+card", "+1 Card"), ("+action", "+1 Action"),
                   ("+buy", "+1 Buy"), ("+coin", "+$1")]


def _teacher_call(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if not E.call_card(game, pid, "Teacher"):
        E.lost_track(game, pid, "Teacher", "called")
        return
    # "an Action Supply pile you have NO tokens on" — any of yours, including
    # the -$2 Cost and Trashing tokens. Opponents' tokens don't hinder you.
    piles = [p for p in _action_supply_piles(game) if not E.pile_tokens(game, p, pid)]
    if not piles:
        return
    E.push_choose_option(game, pid, "Teacher", "token", data={"piles": piles},
                         options=[{"id": k, "label": f"Move your {lab} token"}
                                  for k, lab in _TEACHER_TOKENS])


def _teacher_token(game, pid, frame, choice):
    E.push_choose_pile(game, pid, "Teacher", "pile", frame["data"]["piles"],
                       data={"kind": choice["ids"][0]})


def _teacher_pile(game, pid, frame, choice):
    E.move_token(game, pid, frame["data"]["kind"], choice["pile"])


# ══ THE 20 EVENTS ════════════════════════════════════════════════════════════

def _ev_alms(game, pid):
    if any(E.has_type(game, c, "treasure") for c in game["seats"][pid]["in_play"]):
        return
    picks = _supply_names(game, lambda n: E.cost_le(game, n, 4))
    if picks:
        E.push_choose_pile(game, pid, "Alms", "gain", picks)


def _ev_alms_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


def _ev_borrow(game, pid):
    E.add_buys(game, 1)
    if E.take_seat_token(game, pid, "-card"):
        E.add_coins(game, 1, pid)


_QUEST_OPTS = [("attack", "Discard an Attack"), ("curses", "Discard 2 Curses"),
               ("six", "Discard 6 cards")]


def _ev_quest(game, pid):
    E.push_choose_option(game, pid, "Quest", "mode", options=(
        [{"id": k, "label": lab} for k, lab in _QUEST_OPTS]
        + [{"id": "decline", "label": "Discard nothing"}]))


def _ev_quest_mode(game, pid, frame, choice):
    pick = choice["ids"][0]
    if pick == "decline":
        return
    hand = sorted(game["seats"][pid]["hand"])
    if pick == "attack":
        opts = sorted({c for c in hand if E.has_type(game, c, "attack")})
        n = 1
    elif pick == "curses":
        opts = [c for c in hand if c == "Curse"]
        n = 2
    else:
        opts, n = hand, 6
    if len(opts) < n:
        return          # "you only gain a Gold if you discard all of them"
    E.push_choose_cards(game, pid, "Quest", "discard", opts, n, n, "discard")


def _ev_quest_discard(game, pid, frame, choice):
    E.push_auto(game, pid, "Quest", "gold")
    E.discard(game, pid, choice["cards"])


def _ev_quest_gold(game, pid, frame, choice):
    E.gain(game, pid, "Gold")


def _ev_save(game, pid):
    E.add_buys(game, 1)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Save", "aside", sorted(hand), 1, 1,
                            "set aside")


def _ev_save_aside(game, pid, frame, choice):
    cards = E.set_aside(game, pid, choice["cards"], zone="hand")
    game["turn_ctx"]["end_hand"].extend(cards)


def _ev_scouting_party(game, pid):
    E.add_buys(game, 1)
    seen = E.look_top(game, pid, 5)
    if not seen:
        return
    n = min(3, len(seen))
    E.push_choose_cards(game, pid, "Scouting Party", "discard", sorted(seen),
                        n, n, "discard")


def _ev_scouting_party_discard(game, pid, frame, choice):
    chosen = choice["cards"]
    rest = list(game["seats"][pid]["aside"])
    for c in chosen:
        rest.remove(c)
    E.discard_then_putback(game, pid, "Scouting Party", chosen, rest)


def _ev_travelling_fair(game, pid):
    E.add_buys(game, 2)
    E.add_watcher(game, pid, "Travelling Fair", "gain", stage="topdeck",
                  until="turn_end")


def _ev_travelling_fair_when(game, w, ctx):
    return ctx.get("actor") == w["owner"]


def _ev_travelling_fair_topdeck(game, pid, frame, choice):
    card = frame["data"].get("subject")
    zone = E.find_card_zone(game, pid, card, zones=("discard", "hand"))
    if zone is None:
        E.lost_track(game, pid, card, "topdecked")
        return
    E.push_choose_option(game, pid, "Travelling Fair", "put",
                         data={"card": card, "zone": zone},
                         options=[{"id": "yes", "label": f"Put {card} onto your deck"},
                                  {"id": "no", "label": "Leave it"}])


def _ev_travelling_fair_put(game, pid, frame, choice):
    if choice["ids"][0] != "yes":
        return
    d = frame["data"]
    zone = E.find_card_zone(game, pid, d["card"], zones=(d["zone"], "discard", "hand"))
    if zone is None:
        E.lost_track(game, pid, d["card"], "topdecked")
        return
    E.topdeck(game, pid, d["card"], zone=zone, public=True)


def _ev_bonfire(game, pid):
    # 2022: Coppers only
    coppers = [c for c in game["seats"][pid]["in_play"] if c == "Copper"]
    if not coppers:
        return
    E.push_choose_cards(game, pid, "Bonfire", "trash", coppers,
                        0, min(2, len(coppers)), "trash")


def _ev_bonfire_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, choice["cards"], zone="in_play")


def _ev_expedition(game, pid):
    game["turn_ctx"]["end_draw"] += 2


def _token_event(kind, label):
    """Ferry / Lost Arts / Training / Pathfinding / Plan — all "move your <x>
    token to an Action Supply pile", differing only in which token."""
    def fx(game, pid):
        piles = _action_supply_piles(game)
        if piles:
            E.push_choose_pile(game, pid, label, "pile", piles, data={"kind": kind})
    return fx


def _token_event_pile(game, pid, frame, choice):
    E.move_token(game, pid, frame["data"]["kind"], choice["pile"])


def _ev_mission(game, pid):
    # 2023: "no more than 2 turns in a row" — the kernel gate owns that
    E.request_extra_turn(game, pid, source="Mission", no_buy=True)


def _ev_pilgrimage(game, pid):
    if not E.flip_journey(game, pid):
        return
    names = sorted({c for c in game["seats"][pid]["in_play"]})
    if not names:
        return
    E.push_choose_cards(game, pid, "Pilgrimage", "pick", names, 0, min(3, len(names)),
                        "gain a copy of")


def _ev_pilgrimage_pick(game, pid, frame, choice):
    # "You first choose the three cards, then gain a copy of each" — and you
    # only gain one if it is available in the Supply.
    for card in choice["cards"]:
        pile = E.pile_of(game, card)
        if pile is not None and E.is_supply_pile(game, pile):
            E.gain(game, pid, pile)


def _ev_ball(game, pid):
    E.take_seat_token(game, pid, "-coin")
    E.push_auto(game, pid, "Ball", "gain", data={"left": 2})


def _ev_ball_gain(game, pid, frame, choice):
    left = frame["data"]["left"]
    if left <= 0:
        return
    picks = _supply_names(game, lambda n: E.cost_le(game, n, 4))
    if not picks:
        return
    E.push_auto(game, pid, "Ball", "gain", data={"left": left - 1})
    E.push_choose_pile(game, pid, "Ball", "take", picks)


def _ev_ball_take(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


def _ev_raid(game, pid):
    for _ in range(game["seats"][pid]["in_play"].count("Silver")):
        E.gain(game, pid, "Silver")
    # NOT an attack: "the other players can't use Reactions that trigger on an
    # Attack being played, since you didn't play an Attack"
    for o in E.opponents(game, pid):
        E.take_seat_token(game, o, "-card")


def _ev_seaway(game, pid):
    picks = _supply_names(game, lambda n: E.has_type(game, n, "action")
                          and E.cost_le(game, n, 4))
    if picks:
        E.push_choose_pile(game, pid, "Seaway", "gain", picks)


def _ev_seaway_gain(game, pid, frame, choice):
    pile = choice["pile"]
    if E.gain(game, pid, pile):        # "if you didn't gain it, no token moves"
        E.move_token(game, pid, "+buy", pile)


def _ev_trade(game, pid):
    hand = game["seats"][pid]["hand"]
    if not hand:
        return
    E.push_choose_cards(game, pid, "Trade", "trash", sorted(hand),
                        0, min(2, len(hand)), "trash")


def _ev_trade_trash(game, pid, frame, choice):
    cards = choice["cards"]
    if not cards:
        return
    E.push_auto(game, pid, "Trade", "silver", data={"n": len(cards)})
    E.trash(game, pid, cards)


def _ev_trade_silver(game, pid, frame, choice):
    for _ in range(frame["data"]["n"]):
        E.gain(game, pid, "Silver")


# --- Inheritance -------------------------------------------------------------
# The 2019/2022/2025 card. Not an identity system: your Estates become
# Action-Victory-COMMAND cards that PLAY the set-aside card and leave it there
# (`play_set_aside`), which is the same shape ph. 5H built for Band of Misfits.
# The type change is a game-wide injection in `types_of`, keyed on whose turn
# it is — every Estate in the game, including opponents' and the Supply's.

def _ev_inheritance(game, pid):
    picks = _supply_names(game, lambda n: E.has_type(game, n, "action")
                          and not E.has_type(game, n, "command")
                          and E.cost_le(game, n, 4))
    if picks:
        E.push_choose_pile(game, pid, "Inheritance", "set_aside", picks)


def _ev_inheritance_set_aside(game, pid, frame, choice):
    pile = choice["pile"]
    card = E.pile_top(game, pile)
    if card is None:
        return
    # "The Action card you set aside FROM THE SUPPLY is counted as one of your
    # cards at the end of the game. This is not considered gaining a card." —
    # so it comes off the pile without a gain event, and lands in the seat's
    # own set-aside zone, which `owned_cards` already counts.
    E.take_from_pile_aside(game, pid, pile)
    E.set_seat_token(game, pid, "estate", card)


def _estate(game, pid):
    """An Inherited Estate's play ability. The card it plays is the TURN
    PLAYER's — "if an opponent has bought Inheritance and you haven't, your
    Estates are Actions during their turn, but playing one does nothing"."""
    E.play_set_aside(game, pid, E.estate_token_card(game, game["turn"]),
                     count=False)     # play_action_card already counted this play


# ── registration ──────────────────────────────────────────────────────────────

EFFECTS.update({
    "Coin of the Realm": _coin_of_the_realm,
    "Page": _page,
    "Peasant": _peasant,
    "Ratcatcher": _ratcatcher,
    "Raze": _raze,
    "Amulet": _amulet,
    "Caravan Guard": _caravan_guard,
    "Dungeon": _dungeon,
    "Gear": _gear,
    "Guide": _guide,
    "Duplicate": _duplicate,
    "Magpie": _magpie,
    "Messenger": _messenger,
    "Miser": _miser,
    "Port": _port,
    "Ranger": _ranger,
    "Transmogrify": _transmogrify,
    "Artificer": _artificer,
    "Bridge Troll": _bridge_troll,
    "Distant Lands": _distant_lands,
    "Giant": _giant,
    "Haunted Woods": _haunted_woods,
    "Lost City": _lost_city,
    "Relic": _relic,
    "Royal Carriage": _royal_carriage,
    "Storyteller": _storyteller,
    "Swamp Hag": _swamp_hag,
    "Treasure Trove": _treasure_trove,
    "Wine Merchant": _wine_merchant,
    "Hireling": _hireling,
    # the Traveller upgrades
    "Treasure Hunter": _treasure_hunter,
    "Warrior": _warrior,
    "Hero": _hero,
    "Champion": _champion,
    "Soldier": _soldier,
    "Fugitive": _fugitive,
    "Disciple": _disciple,
    "Teacher": _teacher,
    # Inheritance gives the basic Estate a play ability. It lives here because
    # this is the set that grants it; no other module registers "Estate", so
    # the duplicate-registration guard still means what it says.
    "Estate": _estate,
})

STAGES.update({
    ("Coin of the Realm", "call"): _cotr_call,
    ("Ratcatcher", "call"): _ratcatcher_call,
    ("Ratcatcher", "trash"): _ratcatcher_trash,
    ("Raze", "pick"): _raze_pick,
    ("Raze", "trash"): _raze_trash,
    ("Raze", "look"): _raze_look,
    ("Raze", "keep"): _raze_keep,
    ("Amulet", "again"): _amulet_again,
    ("Amulet", "mode"): _amulet_mode,
    ("Amulet", "trash"): _amulet_trash,
    ("Caravan Guard", "next"): _caravan_guard_next,
    ("Caravan Guard", "react"): _caravan_guard_react,
    ("Dungeon", "again"): _dungeon_again,
    ("Dungeon", "discard"): _dungeon_discard,
    ("Gear", "aside"): _gear_aside,
    ("Gear", "back"): _gear_back,
    ("Guide", "call"): _guide_call,
    ("Duplicate", "call"): _duplicate_call,
    ("Messenger", "deck"): _messenger_deck,
    ("Messenger", "gain"): _messenger_gain,
    ("Messenger", "give"): _messenger_give,
    ("Messenger", "copy"): _messenger_copy,
    ("Miser", "mode"): _miser_mode,
    ("Port", "gain"): _port_gain,
    ("Transmogrify", "call"): _transmogrify_call,
    ("Transmogrify", "trash"): _transmogrify_trash,
    ("Transmogrify", "gain"): _transmogrify_gain,
    ("Transmogrify", "take"): _transmogrify_take,
    ("Artificer", "discard"): _artificer_discard,
    ("Artificer", "gain"): _artificer_gain,
    ("Artificer", "which"): _artificer_which,
    ("Bridge Troll", "next"): _bridge_troll_next,
    ("Giant", "hit"): _giant_hit,
    ("Haunted Woods", "next"): _haunted_woods_next,
    ("Haunted Woods", "hit"): _haunted_woods_hit,
    ("Haunted Woods", "order"): _haunted_woods_order,
    ("Lost City", "gain"): _lost_city_gain,
    ("Lost City", "draw"): _lost_city_draw,
    ("Relic", "hit"): _relic_hit,
    ("Royal Carriage", "call"): _royal_carriage_call,
    ("Storyteller", "play"): _storyteller_play,
    ("Storyteller", "pay"): _storyteller_pay,
    ("Swamp Hag", "next"): _swamp_hag_next,
    ("Swamp Hag", "hit"): _swamp_hag_hit,
    ("Wine Merchant", "end"): _wine_merchant_end,
    ("Hireling", "each"): _hireling_each,
    ("Treasure Hunter", "exchange"): _traveller_exchange,
    ("Warrior", "hit"): _warrior_hit,
    ("Warrior", "exchange"): _traveller_exchange,
    ("Hero", "gain"): _hero_gain,
    ("Hero", "exchange"): _traveller_exchange,
    ("Page", "exchange"): _traveller_exchange,
    ("Peasant", "exchange"): _traveller_exchange,
    ("Champion", "bonus"): _champion_bonus,
    ("Soldier", "hit"): _soldier_hit,
    ("Soldier", "discard"): _soldier_discard,
    ("Soldier", "exchange"): _traveller_exchange,
    ("Fugitive", "discard"): _fugitive_discard,
    ("Fugitive", "exchange"): _traveller_exchange,
    ("Disciple", "pick"): _disciple_pick,
    ("Disciple", "second"): _disciple_second,
    ("Disciple", "copy"): _disciple_copy,
    ("Disciple", "exchange"): _traveller_exchange,
    ("Teacher", "call"): _teacher_call,
    ("Teacher", "token"): _teacher_token,
    ("Teacher", "pile"): _teacher_pile,
    # Events
    ("Alms", "gain"): _ev_alms_gain,
    ("Quest", "mode"): _ev_quest_mode,
    ("Quest", "discard"): _ev_quest_discard,
    ("Quest", "gold"): _ev_quest_gold,
    ("Save", "aside"): _ev_save_aside,
    ("Scouting Party", "discard"): _ev_scouting_party_discard,
    ("Travelling Fair", "topdeck"): _ev_travelling_fair_topdeck,
    ("Travelling Fair", "put"): _ev_travelling_fair_put,
    ("Bonfire", "trash"): _ev_bonfire_trash,
    ("Ferry", "pile"): _token_event_pile,
    ("Plan", "pile"): _token_event_pile,
    ("Lost Arts", "pile"): _token_event_pile,
    ("Training", "pile"): _token_event_pile,
    ("Pathfinding", "pile"): _token_event_pile,
    ("Pilgrimage", "pick"): _ev_pilgrimage_pick,
    ("Ball", "gain"): _ev_ball_gain,
    ("Ball", "take"): _ev_ball_take,
    ("Seaway", "gain"): _ev_seaway_gain,
    ("Trade", "trash"): _ev_trade_trash,
    ("Trade", "silver"): _ev_trade_silver,
    ("Inheritance", "set_aside"): _ev_inheritance_set_aside,
})

TRIGGERS.update({
    # the RESERVE call windows (from:"tavern" — offered to the mat's owner)
    "Coin of the Realm": [{"on": "action_resolved", "from": "tavern",
                           "who": "actor", "stage": "call"}],
    "Ratcatcher": [{"on": "turn_start", "from": "tavern", "who": "actor",
                    "stage": "call"}],
    "Guide": [{"on": "turn_start", "from": "tavern", "who": "actor",
               "stage": "call"}],
    "Transmogrify": [{"on": "turn_start", "from": "tavern", "who": "actor",
                      "stage": "call"}],
    "Teacher": [{"on": "turn_start", "from": "tavern", "who": "actor",
                 "stage": "call"}],
    # Duplicate is called on ANY player's gain — including on their turn
    "Duplicate": [{"on": "gain", "from": "tavern", "who": "actor",
                   "stage": "call", "when": _duplicate_when}],
    "Royal Carriage": [{"on": "action_resolved", "from": "tavern", "who": "actor",
                        "stage": "call", "when": _royal_carriage_when}],
    "Wine Merchant": [{"on": "buy_phase_end", "from": "tavern", "who": "actor",
                       "stage": "end", "when": _wine_merchant_when}],
    # when-gain abilities
    "Lost City": [{"on": "gain", "from": "self", "stage": "gain"}],
    "Messenger": [{"on": "gain", "from": "self", "stage": "gain",
                   "when": _messenger_when}],
    "Port": [{"on": "gain", "from": "self", "stage": "gain",
              "when": _port_when}],
})

# "When you discard this from play, you may exchange it for X" — ONE registry
# row per Traveller, differing only in which card it names, riding ph. 5H's
# interruptible Clean-up (the emit fires while the card is still in in_play).
# Registered from `in_play` rather than `self` because the offer has to be
# pushed by a function that can read which card triggered it.
for _t in list(TRAVELLERS):
    TRIGGERS[_t] = [{"on": "cleanup_discard", "from": "in_play",
                     "push": _traveller_offer, "when": _traveller_when(_t)}]

# Caravan Guard is a REACTION THAT PLAYS ITSELF (p53): played from hand when
# another player plays an Attack, no Action spent, no immunity granted, and
# discarded in THAT turn's Clean-up.
ATTACK_REACTIONS = {
    "Caravan Guard": {"label": "Play Caravan Guard", "immunity": False,
                      "mode": "play", "stage": "react", "repeatable": True},
}

WATCHER_WHENS.update({
    ("Haunted Woods", "hit"): _haunted_woods_when,
    ("Swamp Hag", "hit"): _swamp_hag_when,
    ("Champion", "bonus"): _champion_when,
    ("Travelling Fair", "topdeck"): _ev_travelling_fair_when,
})

# Relic is an ATTACK Treasure: playing it opens a reaction window, which is a
# decision frame the bulk "Play all treasures" cannot answer mid-run.
MANUAL_TREASURES.add("Relic")

LANDSCAPE_FX.update({
    "Alms": _ev_alms,
    "Borrow": _ev_borrow,
    "Quest": _ev_quest,
    "Save": _ev_save,
    "Scouting Party": _ev_scouting_party,
    "Travelling Fair": _ev_travelling_fair,
    "Bonfire": _ev_bonfire,
    "Expedition": _ev_expedition,
    "Ferry": _token_event("-cost", "Ferry"),
    "Plan": _token_event("trashing", "Plan"),
    "Mission": _ev_mission,
    "Pilgrimage": _ev_pilgrimage,
    "Ball": _ev_ball,
    "Raid": _ev_raid,
    "Seaway": _ev_seaway,
    "Trade": _ev_trade,
    "Lost Arts": _token_event("+action", "Lost Arts"),
    "Training": _token_event("+coin", "Training"),
    "Pathfinding": _token_event("+card", "Pathfinding"),
    "Inheritance": _ev_inheritance,
})
