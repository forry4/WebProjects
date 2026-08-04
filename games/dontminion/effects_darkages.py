"""Dark Ages card effects — 34 kingdom cards, the 10 Knights, the 5 Ruins, the
3 Shelters and the 3 non-Supply cards (Spoils, Madman, Mercenary).

Sources: names/costs/types from the wiki chart (Wayback capture of
`List_of_cards`), behaviour and every edge case from the Knutsen compendium
v11.1 ch. VII. The set's spec is `.claude-plans/dontminion-phase6-dark-ages.md`.

The set's three THEMES, and how each lands on the existing kernel:

  * **ON-TRASH** is the whole flavour, and it needs no new mechanism: `trash()`
    already `emit_batch`es a `trash` event, so every "when you trash this" is a
    `{"on": "trash", "from": "self"}` registry row (Catacombs, Cultist, Feodum,
    Fortress, Hunting Grounds, Overgrown Estate, Rats, Sir Vander, Squire).
    Market Square is the same event read from HAND, and Hovel is its when-gain
    twin. Trashing a card from the SUPPLY does not emit, which is exactly the
    compendium's Market Square ruling ("trashing a card from the Supply doesn't
    trigger Market Square").
  * **SHUFFLED PILES** (Ruins, Knights) are ph. 3H ordered piles: only the top
    card is ever visible, the wire never ships `contents`, and the pile's cost
    and types are its TOP CARD's. Card code therefore always names the PILE to
    gain from and asks `pile_top` for what it will actually get.
  * **NON-SUPPLY PILES** (Spoils, Madman, Mercenary) are ph. 3H too. They are
    reached with `gain_from`, and they return home with `return_to_pile` — so
    "gain a card from the Supply" excludes them by construction.

Rulings that changed an implementation (each verified in ch. VII, not recalled):

  * **Band of Misfits is the CURRENT (2019/2025) card** — it does not become
    another card, it PLAYS one from the Supply and leaves it there. That is
    `play_from_supply` (ph. 5H); `command_may_play` already encodes both
    exclusions (no Command, no Duration).
  * **A Knight that trashes a Knight is trashed itself**, and "if you play a
    Knight without moving it into play, you still do everything except trashing
    the Knight" — so the self-trash is guarded on the card still being in play.
    The victim picks which of two eligible cards is trashed (like Bandit).
  * **Sir Michael's discard-down-to-3 happens BEFORE they all reveal cards**,
    so it is a second `attack_opponents` pass pushed on top of the Knight one.
  * **Death Cart, Pillage and the Knights all read "if you play this without
    moving it into play"** (the 2019 rewrite for Band of Misfits/Overlord):
    each guards on its own presence in `in_play` and logs `lost_track`.
  * **Hermit EXCHANGES itself for a Madman** (2022) at the end of the Buy phase
    if you gained nothing in it — a per-play `buy_phase_end` watcher, the
    Scheme shape, with the "if it is not in play you can't exchange it" guard.
  * **Urchin's is a BEFORE-play ability**: it resolves before the Attack that
    triggered it, which is why the kernel emits `before_play` AFTER opening the
    reaction window (pushes are LIFO). It does not fire for a throne-room
    replay of the same Urchin, nor for a non-Attack play (ph. 6H widened the
    event to every Action play, so the attack-ness is read off the ctx).
  * **Counterfeit and Procession cannot play Durations** (2022/2019), and both
    may fail to trash what they played ("lost track of it") while still doing
    the rest — Procession still gains.
  * **Poor House can deduct more than it gave you**: two `add_coins` calls, the
    second negative, and the kernel's $0 floor applies after both (Souk's
    precedent).
  * **Scavenger's deck-into-discard is not a discard** ("this doesn't trigger
    cards that say WHEN YOU DISCARD THIS") — `deck_to_discard`, never
    `discard`.
  * **Rogue gains from the trash if it can, and only otherwise attacks**; the
    gained card is a real gain, so when-gain abilities trigger.

Card code touches the game ONLY through the engine kernel helpers.
"""

from . import engine as E
from .cards import KNIGHTS, RUINS


# --- shared helpers ----------------------------------------------------------

def _piles(game, pred=None):
    """Non-empty SUPPLY piles, deterministically ordered, filtered by `pred`.

    Every cost/type question is asked of the PILE, not of its name: an ordered
    pile is priced and typed by its top card, which is what a gain would give
    you (a Knights pile with a Sir Martin on top costs $4)."""
    out = []
    for p in sorted(game["supply"]):
        if E.pile_count(game, p) <= 0:
            continue
        if pred is not None and not pred(p):
            continue
        out.append(p)
    return out


def _in_3_to_6(game, name):
    """'costing from $3 to $6' — the Knights/Rogue/Graverobber band. The UPPER
    half is what excludes a Potion-costed card (cost_le's rule); the lower half
    reads the coin component alone. See engine.cost_ge."""
    return E.cost_ge(game, name, 3) and E.cost_le(game, name, 6)


def _in_play(game, pid, card):
    return card in game["seats"][pid]["in_play"]


# --- Altar -------------------------------------------------------------------
# Trash a card from your hand. Gain a card costing up to $5.
# "If you have no cards in your hand to trash, you still gain a card", and the
# order is fixed: first trash, then gain — so the gain is PARKED BELOW the
# trash prompt rather than run after it inline.

def _altar(game, pid):
    hand = game["seats"][pid]["hand"]
    E.push_auto(game, pid, "Altar", "gain")
    if hand:
        E.push_choose_cards(game, pid, "Altar", "trash", sorted(set(hand)),
                            1, 1, "trash")


def _altar_trash(game, pid, frame, choice):
    E.trash(game, pid, choice["cards"])


def _altar_gain(game, pid, frame, choice):
    piles = _piles(game, lambda p: E.cost_le(game, p, 5))
    if piles:
        E.push_choose_pile(game, pid, "Altar", "gain_pile", piles)


def _altar_gain_pile(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Armory ------------------------------------------------------------------
# Gain a card onto your deck costing up to $4.

def _armory(game, pid):
    piles = _piles(game, lambda p: E.cost_le(game, p, 4))
    if piles:
        E.push_choose_pile(game, pid, "Armory", "gain", piles)


def _armory_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"], dest="deck")


# --- Band of Misfits ---------------------------------------------------------
# "Play a non-Command non-Duration Action card from the Supply that costs less
# than this, leaving it there." The CURRENT card: it does not change itself
# into anything (ph. 5H's play_from_supply). Only the TOP card of a pile is
# choosable, which playable_from_supply already enforces via pile_top.

def _band_of_misfits(game, pid):
    piles = E.playable_from_supply(
        game, pid,
        pred=lambda p: E.cost_lt_card(game, E.pile_top(game, p), "Band of Misfits"))
    if piles:
        E.push_choose_pile(game, pid, "Band of Misfits", "play", piles)


def _band_of_misfits_play(game, pid, frame, choice):
    E.play_from_supply(game, pid, choice["pile"])


# --- Bandit Camp -------------------------------------------------------------

def _bandit_camp(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 2)
    E.gain_from(game, pid, "Spoils")


# --- Beggar ------------------------------------------------------------------
# Gain 3 Coppers TO YOUR HAND. The Reaction discards the Beggar (mode
# "discard") to gain 2 Silvers, "the first onto your deck, the second to your
# discard pile". It grants no immunity and several Beggars may react to one
# attack — a second copy is offered because the first has left the hand.

def _beggar(game, pid):
    for _ in range(3):
        E.gain(game, pid, "Copper", dest="hand")


def _beggar_react(game, pid, frame, choice):
    E.gain(game, pid, "Silver", dest="deck")
    E.gain(game, pid, "Silver")
    E.reopen_attack_window(game, pid)


# --- Catacombs ---------------------------------------------------------------
# Look at the top 3: put them into your hand, or discard them and +3 Cards.
# When you trash this, gain a CHEAPER card (strictly — cost_lt_card).

def _catacombs(game, pid):
    looked = E.look_top(game, pid, 3)
    if not looked:
        return
    E.push_choose_option(game, pid, "Catacombs", "mode", options=[
        {"id": "hand", "label": f"Put the {len(looked)} cards into your hand"},
        {"id": "draw", "label": "Discard them and +3 Cards"}],
        data={"looked": list(looked)})


def _catacombs_mode(game, pid, frame, choice):
    looked = frame["data"]["looked"]
    if choice["ids"][0] == "hand":
        E.take_aside(game, pid, looked, dest="hand")
        return
    E.discard(game, pid, looked, zone="aside", public=True)
    E.draw(game, pid, 3)


def _catacombs_on_trash(game, pid, frame, choice):
    piles = _piles(game, lambda p: E.cost_lt_card(game, p, "Catacombs"))
    if piles:
        E.push_choose_pile(game, pid, "Catacombs", "trash_gain", piles)


def _catacombs_trash_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Count -------------------------------------------------------------------
# Two "choose one"s, resolved IN ORDER — so the second is parked below the
# first's prompt rather than pushed alongside it (a constraint is a snapshot:
# the C&G lesson from Hamlet and Coronet).
# "If you choose to discard but don't have 2 cards in hand, you still get the
# second effect of your choice."

def _count(game, pid):
    E.push_choose_option(game, pid, "Count", "first", options=[
        {"id": "discard", "label": "Discard 2 cards"},
        {"id": "topdeck", "label": "Put a card from your hand onto your deck"},
        {"id": "copper", "label": "Gain a Copper"}])


def _count_first(game, pid, frame, choice):
    cid = choice["ids"][0]
    E.push_auto(game, pid, "Count", "second")
    hand = game["seats"][pid]["hand"]
    if cid == "discard":
        if hand:
            n = min(2, len(hand))
            E.push_choose_cards(game, pid, "Count", "discard", list(hand),
                                n, n, "discard")
    elif cid == "topdeck":
        if hand:
            E.push_choose_cards(game, pid, "Count", "topdeck",
                                sorted(set(hand)), 1, 1, "put onto your deck")
    else:
        E.gain(game, pid, "Copper")


def _count_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


def _count_topdeck(game, pid, frame, choice):
    E.topdeck(game, pid, choice["cards"][0], zone="hand")


def _count_second(game, pid, frame, choice):
    E.push_choose_option(game, pid, "Count", "payoff", options=[
        {"id": "coins", "label": "+$3"},
        {"id": "trash", "label": "Trash your hand"},
        {"id": "duchy", "label": "Gain a Duchy"}])


def _count_payoff(game, pid, frame, choice):
    cid = choice["ids"][0]
    if cid == "coins":
        E.add_coins(game, 3)
    elif cid == "trash":
        hand = list(game["seats"][pid]["hand"])
        if hand:
            E.trash(game, pid, hand)
    else:
        E.gain(game, pid, "Duchy")


# --- Counterfeit -------------------------------------------------------------
# $1, +1 Buy, then "you may play a non-Duration Treasure from your hand twice.
# Trash it." A MANUAL_TREASURE: playing it pushes a decision, so the bulk
# play-all button must skip it. If the played Treasure leaves play on its own
# (a Spoils returns to its pile) Counterfeit plays it twice but cannot trash
# it — it has lost track of it.

def _counterfeit(game, pid):
    E.add_buys(game, 1)
    hand = game["seats"][pid]["hand"]
    cands = sorted({c for c in hand if E.has_type(game, c, "treasure")
                    and not E.has_type(game, c, "duration")})
    if cands:
        E.push_choose_cards(game, pid, "Counterfeit", "pick", cands, 0, 1,
                            "play twice and trash")


def _counterfeit_pick(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    # the replay is parked BELOW the first play's frames, so the first play
    # fully resolves before the second (the throne-room rule)
    E.push_auto(game, pid, "Counterfeit", "second", data={"card": card})
    E.play_treasure_card(game, pid, card, from_zone="hand")


def _counterfeit_second(game, pid, frame, choice):
    card = frame["data"]["card"]
    E.play_treasure_card(game, pid, card, from_zone=None)
    if _in_play(game, pid, card):
        E.trash(game, pid, [card], zone="in_play")
    else:
        E.lost_track(game, pid, card, "trashed")


# --- Cultist -----------------------------------------------------------------
# +2 Cards; each other player gains a Ruins; you may play a Cultist from your
# hand. Order per the compendium: "first each opponent gains Ruins, THEN you
# play another Cultist" — so the chain offer is pushed first and sits below.
# "As the Ruins are different, it's important that players gain them in turn
# order", which attack_opponents already guarantees.

def _cultist(game, pid):
    E.draw(game, pid, 2)
    E.push_auto(game, pid, "Cultist", "chain")
    E.attack_opponents(game, pid, "Cultist", "hit")


def _cultist_hit(game, pid, frame, choice):
    E.gain(game, pid, "Ruins")


def _cultist_chain(game, pid, frame, choice):
    if "Cultist" not in game["seats"][pid]["hand"]:
        return
    E.push_choose_option(game, pid, "Cultist", "chain_pick", options=[
        {"id": "play", "label": "Play a Cultist from your hand"},
        {"id": "decline", "label": "Don't play another Cultist"}])


def _cultist_chain_pick(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if "Cultist" not in game["seats"][pid]["hand"]:
        E.lost_track(game, pid, "Cultist", "played")
        return
    # a free play: it uses no Action from the pool, but it IS a played Action
    E.play_action_card(game, pid, "Cultist", from_zone="hand")


def _cultist_on_trash(game, pid, frame, choice):
    E.draw(game, pid, 3)


# --- Death Cart --------------------------------------------------------------
# "You may trash this or an Action card from your hand, for +$5." The 2019
# card: played without moving into play (a throne-roomed Death Cart trashed the
# first time), it can only pay by trashing an Action from your hand.
# When you gain this, gain 2 Ruins — each in turn.

def _death_cart(game, pid):
    opts = []
    if _in_play(game, pid, "Death Cart"):
        opts.append({"id": "self", "label": "Trash this Death Cart, for +$5"})
    opts.append({"id": "hand", "label": "Trash an Action card from your hand, for +$5"})
    opts.append({"id": "none", "label": "Don't trash anything"})
    E.push_choose_option(game, pid, "Death Cart", "mode", options=opts)


def _death_cart_mode(game, pid, frame, choice):
    cid = choice["ids"][0]
    if cid == "none":
        return
    if cid == "self":
        if not _in_play(game, pid, "Death Cart"):
            E.lost_track(game, pid, "Death Cart", "trashed")
            return
        E.trash(game, pid, ["Death Cart"], zone="in_play")
        E.add_coins(game, 5)
        return
    actions = sorted({c for c in game["seats"][pid]["hand"]
                      if E.has_type(game, c, "action")})
    if actions:
        E.push_choose_cards(game, pid, "Death Cart", "trash", actions, 1, 1,
                            "trash for +$5")


def _death_cart_trash(game, pid, frame, choice):
    E.trash(game, pid, choice["cards"])
    E.add_coins(game, 5)


def _death_cart_on_gain(game, pid, frame, choice):
    for _ in range(2):
        E.gain(game, pid, "Ruins")


# --- Feodum ------------------------------------------------------------------
# 1 VP per 3 Silvers (engine._vp_of, kind "feodum"); on trash, gain 3 Silvers.

def _feodum_on_trash(game, pid, frame, choice):
    for _ in range(3):
        E.gain(game, pid, "Silver")


# --- Forager -----------------------------------------------------------------
# +1 Action, +1 Buy, trash a card, then +$1 per differently named Treasure in
# the trash. "If you have no cards in your hand to trash, you still get +1
# Action and +1 Buy, and also +$" — VARIABLE PRODUCTION counted right when it
# resolves, AFTER the trash (so trashing a Treasure can pay you for it).

def _forager(game, pid):
    E.add_actions(game, 1)
    E.add_buys(game, 1)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Forager", "trash", sorted(set(hand)),
                            1, 1, "trash")
        return
    _forager_pay(game, pid)


def _forager_trash(game, pid, frame, choice):
    E.trash(game, pid, choice["cards"])
    _forager_pay(game, pid)


def _forager_pay(game, pid):
    names = {c for c in game["trash"] if E.has_type(game, c, "treasure")}
    if names:
        E.add_coins(game, len(names))


# --- Fortress ----------------------------------------------------------------
# "WHEN YOU TRASH THIS, you take it from the trash and put it into your hand.
# This is not gaining it. It was still trashed."

def _fortress(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 2)


def _fortress_on_trash(game, pid, frame, choice):
    if E.find_card_zone(game, pid, "Fortress", zones=("trash",)) is None:
        E.lost_track(game, pid, "Fortress", why="it left the trash")
        return
    E.from_trash(game, pid, "Fortress", dest="hand")


# --- Graverobber -------------------------------------------------------------
# Choose one: gain a card from the trash costing from $3 to $6, ONTO YOUR DECK;
# or "remodel" an Action from your hand into a card costing up to $3 more.

def _graverobber(game, pid):
    E.push_choose_option(game, pid, "Graverobber", "mode", options=[
        {"id": "trash", "label": "Gain a card costing from $3 to $6 from the trash, onto your deck"},
        {"id": "remodel", "label": "Trash an Action from your hand, gain a card costing up to $3 more"}])


def _graverobber_mode(game, pid, frame, choice):
    if choice["ids"][0] == "trash":
        cands = sorted({c for c in game["trash"] if _in_3_to_6(game, c)})
        if cands:
            E.push_choose_cards(game, pid, "Graverobber", "take", cands, 1, 1,
                                "gain from the trash")
        return
    actions = sorted({c for c in game["seats"][pid]["hand"]
                      if E.has_type(game, c, "action")})
    if actions:
        E.push_choose_cards(game, pid, "Graverobber", "remodel", actions, 1, 1,
                            "trash")


def _graverobber_take(game, pid, frame, choice):
    E.gain_from_trash(game, pid, choice["cards"][0], dest="deck")


def _graverobber_remodel(game, pid, frame, choice):
    card = choice["cards"][0]
    # the gain is parked below the trash — the trashed card's when-trash
    # ability resolves first (the remodel family's order)
    E.push_auto(game, pid, "Graverobber", "gain_step", data={"card": card})
    E.trash(game, pid, [card])


def _graverobber_gain_step(game, pid, frame, choice):
    card = frame["data"]["card"]
    piles = _piles(game, lambda p: E.cost_le_card(game, p, card, 3))
    if piles:
        E.push_choose_pile(game, pid, "Graverobber", "gain", piles)


def _graverobber_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Hermit ------------------------------------------------------------------
# Look through your discard pile; you MAY trash a non-Treasure from it or from
# your hand; then gain a card costing up to $3. At the end of your Buy phase,
# if you gained no cards in it, EXCHANGE this for a Madman (the 2022 card: it
# is an exchange, not a trash-and-gain, and it is set up when you PLAY it).

def _hermit(game, pid):
    seat = game["seats"][pid]
    cands = sorted({c for c in seat["discard"] + seat["hand"]
                    if not E.has_type(game, c, "treasure")})
    E.push_auto(game, pid, "Hermit", "gain")
    if cands:
        E.push_choose_cards(game, pid, "Hermit", "trash", cands, 0, 1, "trash")
    # the Scheme shape: a per-play watcher, so it is cumulative, it survives the
    # Hermit being trashed from play, and it dies with the turn
    E.add_watcher(game, pid, "Hermit", "buy_phase_end", stage="exchange",
                  until="turn_end")


def _hermit_trash(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    zone = E.find_card_zone(game, pid, card, zones=("hand", "discard"))
    if zone is None:
        E.lost_track(game, pid, card, "trashed")
        return
    E.trash(game, pid, [card], zone=zone)


def _hermit_gain(game, pid, frame, choice):
    piles = _piles(game, lambda p: E.cost_le(game, p, 3))
    if piles:
        E.push_choose_pile(game, pid, "Hermit", "gain_pile", piles)


def _hermit_gain_pile(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


def _hermit_can_exchange(game, pid):
    return (not game["turn_ctx"]["buy_gains"]) and _in_play(game, pid, "Hermit")


def _hermit_exchange(game, pid, frame, choice):
    if frame["data"].get("actor") != pid:
        return
    if game["turn_ctx"]["buy_gains"]:
        return
    if not _in_play(game, pid, "Hermit"):
        # "If the Hermit is not in play (for instance if it was trashed by
        # Procession or set aside by Royal Galley), you can't exchange it."
        E.lost_track(game, pid, "Hermit", why="it is no longer in play")
        return
    E.exchange(game, pid, "Hermit", "Madman", zone="in_play")


def _hermit_when(game, watcher, ctx):
    """Join-time filter: a Hermit that cannot exchange never enters the ability
    pool, so it can't ask the player to order a no-op against a real ability."""
    return (ctx.get("actor") == watcher["owner"]
            and _hermit_can_exchange(game, watcher["owner"]))


# --- Hunting Grounds ---------------------------------------------------------

def _hunting_grounds(game, pid):
    E.draw(game, pid, 4)


def _hunting_grounds_on_trash(game, pid, frame, choice):
    E.push_choose_option(game, pid, "Hunting Grounds", "pick", options=[
        {"id": "duchy", "label": "Gain a Duchy"},
        {"id": "estates", "label": "Gain 3 Estates"}])


def _hunting_grounds_pick(game, pid, frame, choice):
    if choice["ids"][0] == "duchy":
        E.gain(game, pid, "Duchy")
        return
    for _ in range(3):
        E.gain(game, pid, "Estate")


# --- Ironmonger --------------------------------------------------------------
# Reveal the top card; you may discard it. EITHER WAY the bonuses apply, and a
# card with several of the types gets all of them.

def _ironmonger(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    looked = E.look_top(game, pid, 1)
    if not looked:
        return
    card = looked[0]
    E.reveal(game, pid, [card], "deck")
    E.push_choose_option(game, pid, "Ironmonger", "mode", options=[
        {"id": "discard", "label": f"Discard the {card}"},
        {"id": "keep", "label": f"Put the {card} back on your deck"}],
        data={"card": card})


def _ironmonger_mode(game, pid, frame, choice):
    card = frame["data"]["card"]
    if choice["ids"][0] == "discard":
        E.discard(game, pid, [card], zone="aside", public=True)
    else:
        E.deck_from_aside(game, pid, [card])
    if E.has_type(game, card, "action"):
        E.add_actions(game, 1)
    if E.has_type(game, card, "treasure"):
        E.add_coins(game, 1)
    if E.has_type(game, card, "victory"):
        E.draw(game, pid, 1)


# --- Junk Dealer -------------------------------------------------------------
# "You get +1 Action and +$1 even if you don't have a card in your hand to trash."

def _junk_dealer(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_coins(game, 1)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Junk Dealer", "trash",
                            sorted(set(hand)), 1, 1, "trash")


def _junk_dealer_trash(game, pid, frame, choice):
    E.trash(game, pid, choice["cards"])


# --- Marauder ----------------------------------------------------------------
# "The other players gain a Ruins even if you can't gain a Spoils", and the
# order is you first, then each opponent in turn order.

def _marauder(game, pid):
    E.gain_from(game, pid, "Spoils")
    E.attack_opponents(game, pid, "Marauder", "hit")


def _marauder_hit(game, pid, frame, choice):
    E.gain(game, pid, "Ruins")


# --- Market Square -----------------------------------------------------------
# "When one of YOUR cards is trashed, you may discard this from your hand to
# gain a Gold." A when-trash hand reaction (who="actor"), and several Market
# Squares may react to the SAME trashing — so a successful reaction re-offers
# itself while another copy is in hand.

def _market_square(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_buys(game, 1)


def _market_square_offer(game, pid, data):
    E.push_choose_option(game, pid, "Market Square", "react", options=[
        {"id": "play", "label": "Discard Market Square to gain a Gold"},
        {"id": "decline", "label": "Don't react"}], data=dict(data))


def _market_square_react(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if "Market Square" not in game["seats"][pid]["hand"]:
        E.lost_track(game, pid, "Market Square", "discarded")
        return
    E.discard(game, pid, ["Market Square"])
    E.gain(game, pid, "Gold")
    if "Market Square" in game["seats"][pid]["hand"]:
        _market_square_offer(game, pid, frame["data"])


# --- Mystic ------------------------------------------------------------------

def _mystic(game, pid):
    E.add_actions(game, 1)
    E.add_coins(game, 2)
    E.push_name_card(game, pid, "Mystic", "name")


def _mystic_name(game, pid, frame, choice):
    named = choice["card"]
    looked = E.look_top(game, pid, 1)
    if not looked:
        return
    card = looked[0]
    E.reveal(game, pid, [card], "deck")
    if card == named:
        E.take_aside(game, pid, [card], dest="hand")
    else:
        E.deck_from_aside(game, pid, [card])


# --- Pillage -----------------------------------------------------------------
# "Trash this. If you did, gain 2 Spoils, and each other player with 5 or more
# cards in hand reveals their hand and discards a card THAT YOU CHOOSE."
# The 2019 card: played without moving into play, nothing happens at all.

def _pillage(game, pid):
    if not _in_play(game, pid, "Pillage"):
        E.lost_track(game, pid, "Pillage", "trashed",
                     why="it is not in play, so nothing happens")
        return
    E.trash(game, pid, ["Pillage"], zone="in_play")
    E.gain_from(game, pid, "Spoils")
    E.gain_from(game, pid, "Spoils")
    E.attack_opponents(game, pid, "Pillage", "hit", data={"attacker": pid})


def _pillage_hit(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    if len(hand) < 5:
        return
    E.reveal(game, pid, list(hand), "hand")
    # the ATTACKER picks, so the frame belongs to them, not to the victim
    E.push_choose_cards(game, frame["data"]["attacker"], "Pillage", "pick",
                        sorted(set(hand)), 1, 1, "make them discard",
                        data={"opp": pid})


def _pillage_pick(game, pid, frame, choice):
    E.discard(game, frame["data"]["opp"], [choice["cards"][0]])


# --- Poor House --------------------------------------------------------------
# VARIABLE PRODUCTION: +$4, then -$1 per Treasure in your revealed hand. "Your
# money pool can never go below $0, but if you had any $ before playing Poor
# House, you might lose more than $4" — which the kernel's clamped negative
# add_coins does exactly (Souk's precedent).

def _poor_house(game, pid):
    E.add_coins(game, 4)
    hand = game["seats"][pid]["hand"]
    E.reveal(game, pid, list(hand), "hand")
    treasures = sum(1 for c in hand if E.has_type(game, c, "treasure"))
    if treasures:
        E.add_coins(game, -treasures)


# --- Procession --------------------------------------------------------------
# Play a non-Duration Action twice, trash it, then gain an Action costing
# EXACTLY $1 more than it. "Even if you are not able to trash the played
# Action, you gain a card", and the cost is checked after it has left play.

def _procession(game, pid):
    hand = game["seats"][pid]["hand"]
    cands = sorted({c for c in hand if E.has_type(game, c, "action")
                    and not E.has_type(game, c, "duration")})
    if cands:
        E.push_choose_cards(game, pid, "Procession", "pick", cands, 0, 1,
                            "play twice, then trash")


def _procession_pick(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    E.push_auto(game, pid, "Procession", "second", data={"card": card})
    E.play_action_card(game, pid, card, from_zone="hand")


def _procession_second(game, pid, frame, choice):
    card = frame["data"]["card"]
    E.push_auto(game, pid, "Procession", "finish", data={"card": card})
    E.play_action_card(game, pid, card, from_zone=None)


def _procession_finish(game, pid, frame, choice):
    card = frame["data"]["card"]
    # "first play twice, then trash, THEN check cost, then gain": the gain is
    # parked BELOW the trash, so the trashed card's own when-trash ability (a
    # Fortress going back to your hand) resolves before the gain is offered.
    E.push_auto(game, pid, "Procession", "gain_step", data={"card": card})
    if _in_play(game, pid, card):
        E.trash(game, pid, [card], zone="in_play")
    else:
        E.lost_track(game, pid, card, "trashed")


def _procession_gain_step(game, pid, frame, choice):
    card = frame["data"]["card"]
    piles = _piles(game, lambda p: E.has_type(game, p, "action")
                   and E.cost_eq_card(game, p, card, 1))
    if piles:
        E.push_choose_pile(game, pid, "Procession", "gain", piles)


def _procession_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Rats --------------------------------------------------------------------
# +1 Card, +1 Action, gain a Rats, then trash a card other than a Rats (or
# reveal a hand of all Rats). First gain, THEN trash. Its pile is 20 cards.

def _rats(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.gain(game, pid, "Rats")
    hand = game["seats"][pid]["hand"]
    cands = sorted({c for c in hand if c != "Rats"})
    if cands:
        E.push_choose_cards(game, pid, "Rats", "trash", cands, 1, 1, "trash")
    elif hand:
        E.reveal(game, pid, list(hand), "hand")


def _rats_trash(game, pid, frame, choice):
    E.trash(game, pid, choice["cards"])


def _rats_on_trash(game, pid, frame, choice):
    E.draw(game, pid, 1)


# --- Rebuild -----------------------------------------------------------------
# Name a card (any name), dig for a Victory card you did not name, discard the
# rest, trash it, and gain a Victory card costing up to $3 more.

def _rebuild(game, pid):
    E.add_actions(game, 1)
    E.push_name_card(game, pid, "Rebuild", "name")


def _rebuild_name(game, pid, frame, choice):
    named = choice["card"]
    found = None
    while True:
        got = E.look_top(game, pid, 1)
        if not got:
            break
        E.reveal(game, pid, got, "deck")
        if E.has_type(game, got[0], "victory") and got[0] != named:
            found = got[0]
            break
    aside = list(game["seats"][pid]["aside"])
    rest = aside[:-1] if found is not None else aside
    if rest:
        E.discard(game, pid, rest, zone="aside", public=True)
    if found is None:
        return
    # "first discard, then trash, then gain" — the gain sits BELOW the trash so
    # the trashed Victory card's own when-trash ability resolves first
    E.push_auto(game, pid, "Rebuild", "gain_step", data={"card": found})
    E.trash(game, pid, [found], zone="aside")


def _rebuild_gain_step(game, pid, frame, choice):
    found = frame["data"]["card"]
    piles = _piles(game, lambda p: E.has_type(game, p, "victory")
                   and E.cost_le_card(game, p, found, 3))
    if piles:
        E.push_choose_pile(game, pid, "Rebuild", "gain", piles)


def _rebuild_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Rogue -------------------------------------------------------------------
# "If there are any cards of the appropriate cost in the trash, you HAVE TO
# gain one of them ... Otherwise, each other player reveals cards and possibly
# trashes one."

def _rogue(game, pid):
    E.add_coins(game, 2)
    cands = sorted({c for c in game["trash"] if _in_3_to_6(game, c)})
    if cands:
        E.push_choose_cards(game, pid, "Rogue", "take", cands, 1, 1,
                            "gain from the trash")
        return
    E.attack_opponents(game, pid, "Rogue", "hit")


def _rogue_take(game, pid, frame, choice):
    E.gain_from_trash(game, pid, choice["cards"][0])


def _rogue_hit(game, pid, frame, choice):
    _reveal_two_and_trash(game, pid, "Rogue", "trash")


def _rogue_trash(game, pid, frame, choice):
    _trash_one_of_the_revealed(game, pid, choice["cards"][0])


# --- Sage --------------------------------------------------------------------
# DIG FOR a card costing $3 or more; it goes to your hand, the rest is discarded.

def _sage(game, pid):
    E.add_actions(game, 1)
    found = None
    while True:
        got = E.look_top(game, pid, 1)
        if not got:
            break
        E.reveal(game, pid, got, "deck")
        if E.cost_ge(game, got[0], 3):
            found = got[0]
            break
    aside = list(game["seats"][pid]["aside"])
    rest = aside[:-1] if found is not None else aside
    if rest:
        E.discard(game, pid, rest, zone="aside", public=True)
    if found is not None:
        E.take_aside(game, pid, [found], dest="hand")


# --- Scavenger ---------------------------------------------------------------
# +$2, you MAY put your deck into your discard pile, then you MUST put a card
# from your discard pile onto your deck. Putting the deck down is not a discard
# for trigger purposes, so it never goes through discard().

def _scavenger(game, pid):
    E.add_coins(game, 2)
    E.push_auto(game, pid, "Scavenger", "topdeck")
    E.push_choose_option(game, pid, "Scavenger", "deck", options=[
        {"id": "yes", "label": "Put your deck into your discard pile"},
        {"id": "no", "label": "Keep your deck"}])


def _scavenger_deck(game, pid, frame, choice):
    if choice["ids"][0] == "yes":
        E.deck_to_discard(game, pid)


def _scavenger_topdeck(game, pid, frame, choice):
    discard = game["seats"][pid]["discard"]
    if not discard:
        return
    E.push_choose_cards(game, pid, "Scavenger", "put", sorted(set(discard)),
                        1, 1, "put onto your deck")


def _scavenger_put(game, pid, frame, choice):
    E.topdeck(game, pid, choice["cards"][0], zone="discard", public=True)


# --- Squire ------------------------------------------------------------------
# When you trash this, gain an Attack card "of your choice if there is one in
# the Supply (even one with a Potion in its cost)" — so no cost filter at all.

def _squire(game, pid):
    E.add_coins(game, 1)
    E.push_choose_option(game, pid, "Squire", "mode", options=[
        {"id": "actions", "label": "+2 Actions"},
        {"id": "buys", "label": "+2 Buys"},
        {"id": "silver", "label": "Gain a Silver"}])


def _squire_mode(game, pid, frame, choice):
    cid = choice["ids"][0]
    if cid == "actions":
        E.add_actions(game, 2)
    elif cid == "buys":
        E.add_buys(game, 2)
    else:
        E.gain(game, pid, "Silver")


def _squire_on_trash(game, pid, frame, choice):
    piles = _piles(game, lambda p: E.has_type(game, p, "attack"))
    if piles:
        E.push_choose_pile(game, pid, "Squire", "trash_gain", piles)


def _squire_trash_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Storeroom ---------------------------------------------------------------
# "+1 Buy. Discard any number of cards, then draw that many. THEN discard any
# number of cards for +$1 each." You may discard zero first. The draw is parked
# below the first discard so the when-discard triggers resolve before it.

def _storeroom(game, pid):
    E.add_buys(game, 1)
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Storeroom", "sift", list(hand), 0,
                            len(hand), "discard, then draw that many")


def _storeroom_sift(game, pid, frame, choice):
    cards = list(choice["cards"])
    E.push_auto(game, pid, "Storeroom", "refill", data={"n": len(cards)})
    if cards:
        E.discard(game, pid, cards)


def _storeroom_refill(game, pid, frame, choice):
    E.draw(game, pid, frame["data"]["n"])
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Storeroom", "paid", list(hand), 0,
                            len(hand), "discard for +$1 each")


def _storeroom_paid(game, pid, frame, choice):
    cards = list(choice["cards"])
    if not cards:
        return
    E.discard(game, pid, cards)
    E.add_coins(game, len(cards))


# --- Urchin ------------------------------------------------------------------
# +1 Card, +1 Action, each other player discards down to 4. The BEFORE-PLAY
# ability triggers when you play ANOTHER Attack card while this is in play —
# not on a throne-room replay of the same Urchin. It resolves before the
# played Attack does anything (engine._emit_play_attack).

def _urchin(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.attack_opponents(game, pid, "Urchin", "hit")


def _urchin_hit(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    if len(hand) > 4:
        n = len(hand) - 4
        E.push_choose_cards(game, pid, "Urchin", "discard", list(hand), n, n,
                            "discard")


def _urchin_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


def _urchin_when(game, pid, ctx):
    # ph. 6H generalized the kernel's `play_attack` emit into `before_play`,
    # fired for EVERY Action play (Adventures' "+" tokens are the same timing
    # class). Urchin's ability is attack-only — "when you play another ATTACK
    # card" — so the attack-ness that used to be implicit in the event's name
    # is now an explicit read off the ctx.
    if not ctx.get("attack"):
        return False
    if ctx.get("replay"):
        return False        # "not if you play the same Urchin twice"
    if ctx.get("subject") != "Urchin":
        return True
    # a SECOND Urchin is "another Attack card"; the one being played is not
    return game["seats"][pid]["in_play"].count("Urchin") >= 2


def _urchin_before(game, pid, ctx):
    E.push_choose_option(game, pid, "Urchin", "mercenary", options=[
        {"id": "trash", "label": "Trash Urchin to gain a Mercenary"},
        {"id": "decline", "label": "Keep Urchin in play"}])


def _urchin_mercenary(game, pid, frame, choice):
    if choice["ids"][0] != "trash":
        return
    if not _in_play(game, pid, "Urchin"):
        E.lost_track(game, pid, "Urchin", "trashed")
        return
    E.trash(game, pid, ["Urchin"], zone="in_play")
    E.gain_from(game, pid, "Mercenary")


# --- Vagrant -----------------------------------------------------------------

_VAGRANT_TYPES = ("curse", "ruins", "shelter", "victory")


def _vagrant(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    looked = E.look_top(game, pid, 1)
    if not looked:
        return
    card = looked[0]
    E.reveal(game, pid, [card], "deck")
    if any(E.has_type(game, card, t) for t in _VAGRANT_TYPES):
        E.take_aside(game, pid, [card], dest="hand")
    else:
        E.deck_from_aside(game, pid, [card])


# --- Wandering Minstrel ------------------------------------------------------

def _wandering_minstrel(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 2)
    looked = E.look_top(game, pid, 3)
    if not looked:
        return
    E.reveal(game, pid, list(looked), "deck")
    actions = [c for c in looked if E.has_type(game, c, "action")]
    rest = [c for c in looked if not E.has_type(game, c, "action")]
    # "first discard, THEN put cards back" — the kernel helper owns that order
    E.discard_then_putback(game, pid, "Wandering Minstrel", rest, actions)


# --- THE KNIGHTS -------------------------------------------------------------
# Ten differently named cards in ONE shuffled pile; only the top one is ever
# buyable. They share one attack: each other player reveals their top 2, trashes
# one of them costing from $3 to $6 (THEY choose if both qualify), and discards
# the rest. "If a Knight trashes another Knight, the played Knight is also
# trashed" — and only an opponent's Knight counts, never one you trashed from
# your own hand with Dame Anna.

def _knight_attack(game, pid, card):
    E.attack_opponents(game, pid, card, "knight_hit",
                       data={"attacker": pid, "knight": card})


def _reveal_two_and_trash(game, pid, card, stage, data=None):
    """The Bandit/Knights/Rogue shape: reveal the victim's top 2, and let the
    VICTIM pick when both revealed cards qualify (their card, their choice)."""
    moved = E.look_top(game, pid, 2)
    if not moved:
        return
    E.reveal(game, pid, list(moved), "deck")
    eligible = sorted({c for c in moved if _in_3_to_6(game, c)})
    if len(eligible) >= 2:
        E.push_choose_cards(game, pid, card, stage, eligible, 1, 1, "trash",
                            data=dict(data or {}))
        return
    _trash_one_of_the_revealed(game, pid, eligible[0] if eligible else None,
                               data)


def _trash_one_of_the_revealed(game, pid, card, data=None):
    """Trash the chosen card, then discard the rest of the revealed ones. The
    aside zone holds exactly this victim's two cards — each opponent's chain
    fully resolves before the next one starts."""
    if card is not None:
        E.trash(game, pid, [card], zone="aside")
    rest = list(game["seats"][pid]["aside"])
    if rest:
        E.discard(game, pid, rest, zone="aside", public=True)
    if card is None or not data:
        return
    if not E.has_type(game, card, "knight"):
        return
    attacker, knight = data["attacker"], data["knight"]
    if _in_play(game, attacker, knight):
        E.trash(game, attacker, [knight], zone="in_play")
    else:
        # "If you play a Knight without moving it into play, you still do
        # everything except trashing the Knight."
        E.lost_track(game, attacker, knight, "trashed")


def _knight_hit(game, pid, frame, choice):
    d = frame["data"]
    _reveal_two_and_trash(game, pid, d["knight"], "knight_trash", d)


def _knight_trash(game, pid, frame, choice):
    _trash_one_of_the_revealed(game, pid, choice["cards"][0], frame["data"])


def _dame_anna(game, pid):
    _knight_attack(game, pid, "Dame Anna")
    hand = game["seats"][pid]["hand"]
    if hand:
        # pushed AFTER the attack, so it resolves FIRST (LIFO) — "You may
        # choose to not trash any cards."
        E.push_choose_cards(game, pid, "Dame Anna", "trash", list(hand), 0,
                            min(2, len(hand)), "trash")


def _dame_anna_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, choice["cards"])


def _dame_josephine(game, pid):
    _knight_attack(game, pid, "Dame Josephine")


def _dame_molly(game, pid):
    _knight_attack(game, pid, "Dame Molly")
    E.add_actions(game, 2)


def _dame_natalie(game, pid):
    _knight_attack(game, pid, "Dame Natalie")
    piles = _piles(game, lambda p: E.cost_le(game, p, 3))
    if piles:
        # "You MAY gain a card costing up to $3" — 0-or-1 over the pile names,
        # since a choose_pile has no way to decline (the University pattern).
        E.push_choose_cards(game, pid, "Dame Natalie", "gain", piles, 0, 1,
                            "gain a card costing up to $3")


def _dame_natalie_gain(game, pid, frame, choice):
    if choice["cards"]:
        E.gain(game, pid, choice["cards"][0])


def _dame_sylvia(game, pid):
    _knight_attack(game, pid, "Dame Sylvia")
    E.add_coins(game, 2)


def _sir_bailey(game, pid):
    _knight_attack(game, pid, "Sir Bailey")
    E.draw(game, pid, 1)
    E.add_actions(game, 1)


def _sir_destry(game, pid):
    _knight_attack(game, pid, "Sir Destry")
    E.draw(game, pid, 2)


def _sir_martin(game, pid):
    _knight_attack(game, pid, "Sir Martin")
    E.add_buys(game, 2)


def _sir_michael(game, pid):
    # "Each other player discards down to 3 cards in hand. THIS HAPPENS BEFORE
    # they all reveal cards from their deck" — pushed last, so it resolves first.
    _knight_attack(game, pid, "Sir Michael")
    E.attack_opponents(game, pid, "Sir Michael", "militia_hit")


def _sir_michael_hit(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    if len(hand) > 3:
        n = len(hand) - 3
        E.push_choose_cards(game, pid, "Sir Michael", "militia_discard",
                            list(hand), n, n, "discard")


def _sir_michael_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


def _sir_vander(game, pid):
    _knight_attack(game, pid, "Sir Vander")


def _sir_vander_on_trash(game, pid, frame, choice):
    E.gain(game, pid, "Gold")


# --- THE RUINS ---------------------------------------------------------------
# One shuffled Supply pile, included whenever a Looter is in the kingdom.

def _abandoned_mine(game, pid):
    E.add_coins(game, 1)


def _ruined_library(game, pid):
    E.draw(game, pid, 1)


def _ruined_market(game, pid):
    E.add_buys(game, 1)


def _ruined_village(game, pid):
    E.add_actions(game, 1)


def _survivors(game, pid):
    looked = E.look_top(game, pid, 2)
    if not looked:
        return
    E.push_choose_option(game, pid, "Survivors", "mode", options=[
        {"id": "discard", "label": "Discard both cards"},
        {"id": "keep", "label": "Put them back on your deck"}],
        data={"looked": list(looked)})


def _survivors_mode(game, pid, frame, choice):
    looked = frame["data"]["looked"]
    if choice["ids"][0] == "discard":
        E.discard(game, pid, looked, zone="aside", public=True)
    elif len(looked) >= 2:
        E.push_order_cards(game, pid, "Survivors", "order", cards=looked)
    else:
        E.deck_from_aside(game, pid, looked)


def _survivors_order(game, pid, frame, choice):
    E.deck_from_aside(game, pid, choice["order"])


# --- THE SHELTERS ------------------------------------------------------------
# They replace the 3 starting Estates and belong to no pile. Necropolis is a
# plain village; Overgrown Estate is a 0 VP card with a when-trash draw; Hovel
# is a when-gain reaction that trashes ITSELF (the 2022 retiming — a when-gain
# ability, so it can trigger on an opponent's turn).

def _necropolis(game, pid):
    E.add_actions(game, 2)


def _overgrown_estate_on_trash(game, pid, frame, choice):
    E.draw(game, pid, 1)


def _hovel_when(game, pid, ctx):
    return E.has_type(game, ctx.get("subject"), "victory")


def _hovel_react(game, pid, frame, choice):
    if choice["ids"][0] != "play":
        return
    if "Hovel" not in game["seats"][pid]["hand"]:
        E.lost_track(game, pid, "Hovel", "trashed")
        return
    E.trash(game, pid, ["Hovel"])


# --- SPOILS / MADMAN / MERCENARY (the non-Supply piles) ----------------------

def _spoils(game, pid):
    # "When you play this, return it to the Spoils pile" — the $3 is produced
    # by the ordinary treasure path before this runs, and it is REMOVED FROM
    # PLAY, so a Counterfeit that played it can no longer trash it.
    E.return_to_pile(game, pid, "Spoils", zone="in_play")


def _madman(game, pid):
    E.add_actions(game, 2)
    # NOT OPTIONAL "IF YOU DO": the draw happens only if the return succeeded
    # (a Madman played without moving into play draws nothing).
    if E.return_to_pile(game, pid, "Madman", zone="in_play"):
        E.draw(game, pid, len(game["seats"][pid]["hand"]))


def _mercenary(game, pid):
    hand = game["seats"][pid]["hand"]
    if not hand:
        return
    # its attack half runs in a LATER stage, so this play's immunity set has to
    # be captured now (the Minion/Replace rule)
    E.push_choose_cards(game, pid, "Mercenary", "trash", list(hand), 0,
                        min(2, len(hand)), "trash",
                        data={"immune": list(game.get("_atk_immune", []))})


def _mercenary_trash(game, pid, frame, choice):
    cards = list(choice["cards"])
    if cards:
        E.trash(game, pid, cards)
    if len(cards) < 2:
        # "With one card in hand you can choose to trash that card, but then
        # Mercenary would do nothing further."
        return
    E.draw(game, pid, 2)
    E.add_coins(game, 2)
    E.attack_opponents(game, pid, "Mercenary", "hit",
                       immune=frame["data"].get("immune", []))


def _mercenary_hit(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    if len(hand) > 3:
        n = len(hand) - 3
        E.push_choose_cards(game, pid, "Mercenary", "discard", list(hand), n,
                            n, "discard")


def _mercenary_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


# ── registries ───────────────────────────────────────────────────────────────

EFFECTS = {
    "Altar": _altar,
    "Armory": _armory,
    "Band of Misfits": _band_of_misfits,
    "Bandit Camp": _bandit_camp,
    "Beggar": _beggar,
    "Catacombs": _catacombs,
    "Count": _count,
    "Counterfeit": _counterfeit,
    "Cultist": _cultist,
    "Death Cart": _death_cart,
    "Forager": _forager,
    "Fortress": _fortress,
    "Graverobber": _graverobber,
    "Hermit": _hermit,
    "Hunting Grounds": _hunting_grounds,
    "Ironmonger": _ironmonger,
    "Junk Dealer": _junk_dealer,
    "Marauder": _marauder,
    "Market Square": _market_square,
    "Mystic": _mystic,
    "Pillage": _pillage,
    "Poor House": _poor_house,
    "Procession": _procession,
    "Rats": _rats,
    "Rebuild": _rebuild,
    "Rogue": _rogue,
    "Sage": _sage,
    "Scavenger": _scavenger,
    "Squire": _squire,
    "Storeroom": _storeroom,
    "Urchin": _urchin,
    "Vagrant": _vagrant,
    "Wandering Minstrel": _wandering_minstrel,
    # Knights
    "Dame Anna": _dame_anna,
    "Dame Josephine": _dame_josephine,
    "Dame Molly": _dame_molly,
    "Dame Natalie": _dame_natalie,
    "Dame Sylvia": _dame_sylvia,
    "Sir Bailey": _sir_bailey,
    "Sir Destry": _sir_destry,
    "Sir Martin": _sir_martin,
    "Sir Michael": _sir_michael,
    "Sir Vander": _sir_vander,
    # Ruins
    "Abandoned Mine": _abandoned_mine,
    "Ruined Library": _ruined_library,
    "Ruined Market": _ruined_market,
    "Ruined Village": _ruined_village,
    "Survivors": _survivors,
    # Shelters + the non-Supply cards
    "Necropolis": _necropolis,
    "Spoils": _spoils,
    "Madman": _madman,
    "Mercenary": _mercenary,
    # Feodum and Overgrown Estate are Victory cards with only a when-trash
    # ability, and Hovel is a pure Reaction — none of them has a play ability.
}

STAGES = {
    ("Altar", "trash"): _altar_trash,
    ("Altar", "gain"): _altar_gain,
    ("Altar", "gain_pile"): _altar_gain_pile,
    ("Armory", "gain"): _armory_gain,
    ("Band of Misfits", "play"): _band_of_misfits_play,
    ("Beggar", "react"): _beggar_react,
    ("Catacombs", "mode"): _catacombs_mode,
    ("Catacombs", "on_trash"): _catacombs_on_trash,
    ("Catacombs", "trash_gain"): _catacombs_trash_gain,
    ("Count", "first"): _count_first,
    ("Count", "discard"): _count_discard,
    ("Count", "topdeck"): _count_topdeck,
    ("Count", "second"): _count_second,
    ("Count", "payoff"): _count_payoff,
    ("Counterfeit", "pick"): _counterfeit_pick,
    ("Counterfeit", "second"): _counterfeit_second,
    ("Cultist", "hit"): _cultist_hit,
    ("Cultist", "chain"): _cultist_chain,
    ("Cultist", "chain_pick"): _cultist_chain_pick,
    ("Cultist", "on_trash"): _cultist_on_trash,
    ("Death Cart", "mode"): _death_cart_mode,
    ("Death Cart", "trash"): _death_cart_trash,
    ("Death Cart", "on_gain"): _death_cart_on_gain,
    ("Feodum", "on_trash"): _feodum_on_trash,
    ("Forager", "trash"): _forager_trash,
    ("Fortress", "on_trash"): _fortress_on_trash,
    ("Graverobber", "mode"): _graverobber_mode,
    ("Graverobber", "take"): _graverobber_take,
    ("Graverobber", "remodel"): _graverobber_remodel,
    ("Graverobber", "gain_step"): _graverobber_gain_step,
    ("Graverobber", "gain"): _graverobber_gain,
    ("Hermit", "trash"): _hermit_trash,
    ("Hermit", "gain"): _hermit_gain,
    ("Hermit", "gain_pile"): _hermit_gain_pile,
    ("Hermit", "exchange"): _hermit_exchange,
    ("Hunting Grounds", "on_trash"): _hunting_grounds_on_trash,
    ("Hunting Grounds", "pick"): _hunting_grounds_pick,
    ("Ironmonger", "mode"): _ironmonger_mode,
    ("Junk Dealer", "trash"): _junk_dealer_trash,
    ("Marauder", "hit"): _marauder_hit,
    ("Market Square", "react"): _market_square_react,
    ("Mystic", "name"): _mystic_name,
    ("Pillage", "hit"): _pillage_hit,
    ("Pillage", "pick"): _pillage_pick,
    ("Procession", "pick"): _procession_pick,
    ("Procession", "second"): _procession_second,
    ("Procession", "finish"): _procession_finish,
    ("Procession", "gain_step"): _procession_gain_step,
    ("Procession", "gain"): _procession_gain,
    ("Rats", "trash"): _rats_trash,
    ("Rats", "on_trash"): _rats_on_trash,
    ("Rebuild", "name"): _rebuild_name,
    ("Rebuild", "gain_step"): _rebuild_gain_step,
    ("Rebuild", "gain"): _rebuild_gain,
    ("Rogue", "take"): _rogue_take,
    ("Rogue", "hit"): _rogue_hit,
    ("Rogue", "trash"): _rogue_trash,
    ("Scavenger", "deck"): _scavenger_deck,
    ("Scavenger", "topdeck"): _scavenger_topdeck,
    ("Scavenger", "put"): _scavenger_put,
    ("Squire", "mode"): _squire_mode,
    ("Squire", "on_trash"): _squire_on_trash,
    ("Squire", "trash_gain"): _squire_trash_gain,
    ("Storeroom", "sift"): _storeroom_sift,
    ("Storeroom", "refill"): _storeroom_refill,
    ("Storeroom", "paid"): _storeroom_paid,
    ("Urchin", "hit"): _urchin_hit,
    ("Urchin", "discard"): _urchin_discard,
    ("Urchin", "mercenary"): _urchin_mercenary,
    # Knights: the shared attack, plus each one's own extra
    ("Dame Anna", "trash"): _dame_anna_trash,
    ("Dame Natalie", "gain"): _dame_natalie_gain,
    ("Sir Michael", "militia_hit"): _sir_michael_hit,
    ("Sir Michael", "militia_discard"): _sir_michael_discard,
    ("Sir Vander", "on_trash"): _sir_vander_on_trash,
    # Ruins
    ("Survivors", "mode"): _survivors_mode,
    ("Survivors", "order"): _survivors_order,
    # Shelters + non-Supply
    ("Overgrown Estate", "on_trash"): _overgrown_estate_on_trash,
    ("Hovel", "react"): _hovel_react,
    ("Mercenary", "trash"): _mercenary_trash,
    ("Mercenary", "hit"): _mercenary_hit,
    ("Mercenary", "discard"): _mercenary_discard,
}

# every Knight shares the one attack, keyed on its own name so the prompt reads
# "Sir Destry" rather than a generic label
for _knight in KNIGHTS:
    STAGES[(_knight, "knight_hit")] = _knight_hit
    STAGES[(_knight, "knight_trash")] = _knight_trash

TRIGGERS = {
    # THE ON-TRASH THEME — "when you trash this", the trash emit's self source
    "Catacombs": [{"on": "trash", "from": "self", "stage": "on_trash"}],
    "Cultist": [{"on": "trash", "from": "self", "stage": "on_trash"}],
    "Feodum": [{"on": "trash", "from": "self", "stage": "on_trash"}],
    "Fortress": [{"on": "trash", "from": "self", "stage": "on_trash"}],
    "Hunting Grounds": [{"on": "trash", "from": "self", "stage": "on_trash"}],
    "Overgrown Estate": [{"on": "trash", "from": "self", "stage": "on_trash"}],
    "Rats": [{"on": "trash", "from": "self", "stage": "on_trash"}],
    "Sir Vander": [{"on": "trash", "from": "self", "stage": "on_trash"}],
    "Squire": [{"on": "trash", "from": "self", "stage": "on_trash"}],
    # when you GAIN this
    "Death Cart": [{"on": "gain", "from": "self", "stage": "on_gain"}],
    # the two hand reactions. Both name their own cost in the prompt via the
    # spec's `mode` (Market Square discards itself, Hovel trashes itself), and
    # both are who="actor" — they are about YOUR cards.
    "Market Square": [{"on": "trash", "from": "hand", "who": "actor",
                       "mode": "discard", "stage": "react"}],
    "Hovel": [{"on": "gain", "from": "hand", "who": "actor", "mode": "trash",
               "stage": "react", "when": _hovel_when}],
    # the BEFORE-play ability: an in_play trigger on the kernel's before_play
    "Urchin": [{"on": "before_play", "from": "in_play", "push": _urchin_before,
                "when": _urchin_when}],
}

ATTACK_REACTIONS = {
    # mode "discard": reacting COSTS the card — it leaves the hand, which is
    # also why a second Beggar is offered again afterwards. It grants no
    # immunity ("you may react with several Beggars to the same played Attack").
    "Beggar": {"label": "Discard Beggar to gain 2 Silvers (one onto your deck)",
               "immunity": False, "mode": "discard", "stage": "react",
               "repeatable": True},
}

WATCHER_WHENS = {
    ("Hermit", "exchange"): _hermit_when,
}

# Counterfeit pushes a decision frame, so the bulk play-all button must skip
# it (bucket 1). Spoils is plain autoplay: it pushes nothing, draws nothing and
# reveals nothing, so the bulk play stays undoable.
MANUAL_TREASURES = {"Counterfeit"}
