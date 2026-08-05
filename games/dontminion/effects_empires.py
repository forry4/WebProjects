"""Empires card effects — 24 Supply piles (36 card definitions), 13 Events and
the 21 Landmarks, which are the first landscapes in the game that are never
bought.

Behaviour and every edge case from the Knutsen compendium v11.1 ch. VII; the
setup rules from ch. I SPECIAL SETUP: EMPIRES; the cost vector from ch. IV DEBT.
The Debt dimension and the scoring pipeline this set consumes were both built
and contract-tested one phase earlier (ph. 7H) — see `CLAUDE.md` "Kernel v7H".

**SIXTEEN OF THESE DIFFER FROM EVERY CARD-LIST SITE**, because the set straddles
three errata passes. `cards.py` carries the per-card list; the short version:

  * 2022 was the when-BUY → when-GAIN pass, and it hits Charm, Forum,
    Groundskeeper, Tax, Basilica, Colonnade and Defiled Shrine — half of this
    set's triggers. Four of them ALSO gained a phase test ("only if you gain it
    in your Buy phase"), which is not the same as "only if you bought it": a
    Workshop gain in the Buy phase counts, and a gain on an opponent's turn
    does not.
  * 2021 gave Farmers' Market and Temple the word SUPPLY, and 2025 gave it to
    Gladiator. That is not cosmetic here: all three cost $3 or $4, so any of
    them can be drawn as FERRYMAN's extra pile — in the game and NOT in the
    Supply — and then there is no Supply pile to gather onto or trash from.
    `_supply_pile_for` is the guard, and it is the only reason these three
    cards do not simply name their own pile.
  * 2025 made Chariot Race DRAW its card (so the -1 Card token can deny the
    bonuses), took the now-redundant "then pay off Debt" clause off Capital,
    made Ritual read the trashed card's cost AFTER trashing, and stopped
    Overlord playing Durations (which `command_may_play` already enforces).

The set's five THEMES, and how each lands on the kernel:

  * **DEBT** is ph. 7H's third cost dimension, and this is its first consumer:
    four Actions cost pure Debt, Fortune costs {$8,8D}, Capital hands you 6 of
    it, Tax puts it on the piles and Mountain Pass auctions it. Nothing here
    needed a line of kernel work — the comparators, the buy gate and the payoff
    move were all built and tested against synthetics a phase ago.
  * **SPLIT PILES** are ph. 3H ordered piles whose order is printed rather than
    shuffled. The one thing they DID need is `pile_types`: a pile follows its
    randomizer, so Catapult/Rocks is an Action pile even while the Rocks show.
  * **GATHERING** — VP tokens accumulating ON a pile (Farmers' Market, Temple,
    Wild Hunt gather onto their own pile; Aqueduct and Defiled Shrine seed
    other piles) — is ph. 7H's `add_pile_vp`/`take_pile_vp`.
  * **LANDMARKS** are `LANDSCAPE_SCORING` (11 of them are nothing else),
    `LANDSCAPE_SETUP` (9) and `from:"landscape"` triggers (8).
  * **REPLACING A PLAY** is the one genuinely new timing point: Enchantress
    gives the other players +1 Card +1 Action *instead of* what their card
    does, which is the ph.-8 `would_resolve` window and `cancel_pending_play`.
"""

from . import engine as E
from .cards import CARDS, CASTLES, EMPIRES_SPLITS

EFFECTS = {}
STAGES = {}
TRIGGERS = {}
WATCHER_WHENS = {}
MANUAL_TREASURES = set()
LANDSCAPE_FX = {}
LANDSCAPE_SCORING = {}
LANDSCAPE_SETUP = {}


# ══ shared helpers ═══════════════════════════════════════════════════════════

def _supply_names(game, pred=None):
    """Non-empty Supply piles, optionally filtered. The gain enumerations all
    start here, so "from the Supply" excludes the non-Supply piles (Spoils,
    Travellers, Ferryman's extra pile) by construction."""
    return sorted(n for n in game["supply"]
                  if E.pile_top(game, n) is not None and (pred is None or pred(n)))


def _supply_pile_for(game, card):
    """The SUPPLY pile `card` belongs to, or None.

    Farmers' Market, Temple and Gladiator were all reworded to say "the <name>
    SUPPLY pile" (2021/2025), and the wording earns its keep: each of them
    costs $3 or $4, so each can be drawn as Ferryman's extra pile, which is in
    the game and outside the Supply. Gathering onto it or trashing from it
    would then be gathering onto a pile no one can buy from."""
    pile = E.pile_of(game, card)
    return pile if pile is not None and E.is_supply_pile(game, pile) else None


def _left_of(game, pid):
    """"The player to your left" — the next player in turn order. Same seat as
    `opponents()[0]`, which is already ordered from the current player."""
    opps = E.opponents(game, pid)
    return opps[0] if opps else None


def _gained_in_buy_phase(game, pid, ctx):
    """The 2022 retiming's actual condition: "when you gain a card IN YOUR BUY
    PHASE". Not "when you buy a card" — a Workshop played in the Buy phase (via
    Villa, say) counts — and not "on your turn" either, since the Buy phase is
    the turn player's alone."""
    return pid == game["turn"] and game["phase"] == "buy"


def _turn_gains(game):
    """Cards the turn player has gained SO FAR this turn (Conquest, Triumph,
    Labyrinth). The kernel keeps this for Smugglers; it is emptied into
    `last_turn_gains` at Clean-up, so during a turn it is exactly "this turn"."""
    return game.get("_turn_gains", [])


def _in_play_all(game):
    """Every card in play at ANY seat — Grand Castle counts Victory cards "in
    play", and the compendium is explicit that this is not just your own play
    area: "If other players have Victory cards in play, they count too"."""
    out = []
    for s in game["seats"].values():
        out.extend(s["in_play"])
    return out


# ══ the four DEBT-COSTED Actions ═════════════════════════════════════════════

# --- Engineer ----------------------------------------------------------------
# "Gain a card costing up to $4. You may trash this. If you do, gain a card
# costing up to $4." The trash offer is parked FIRST so LIFO runs it AFTER the
# gain — the card text's order, and the order the compendium's "Gain a card;
# see CARD COSTS" entry assumes.

def _engineer(game, pid):
    E.push_auto(game, pid, "Engineer", "may_trash")
    _push_gain_up_to(game, pid, "Engineer", "gain", 4)


def _push_gain_up_to(game, pid, card, stage, coins, pred=None):
    def ok(n):
        return E.cost_le(game, n, coins) and (pred is None or pred(n))
    picks = _supply_names(game, ok)
    if picks:
        E.push_choose_pile(game, pid, card, stage, picks)


def _engineer_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


def _engineer_may_trash(game, pid, frame, choice):
    if "Engineer" not in game["seats"][pid]["in_play"]:
        return                      # a throne-room replay of a trashed Engineer
    E.push_choose_option(game, pid, "Engineer", "trash", options=[
        {"id": "yes", "label": "Trash Engineer to gain another card costing up to $4"},
        {"id": "no", "label": "Keep Engineer"}])


def _engineer_trash(game, pid, frame, choice):
    if choice["ids"][0] != "yes":
        return
    if "Engineer" not in game["seats"][pid]["in_play"]:
        E.lost_track(game, pid, "Engineer", "trashed")
        return
    E.trash(game, pid, ["Engineer"], zone="in_play")
    _push_gain_up_to(game, pid, "Engineer", "gain", 4)


# --- City Quarter ------------------------------------------------------------

def _city_quarter(game, pid):
    E.add_actions(game, 2)
    hand = list(game["seats"][pid]["hand"])
    E.reveal(game, pid, hand, "City Quarter")
    E.add_cards(game, sum(1 for c in hand if E.has_type(game, c, "action")), pid)


# --- Overlord ----------------------------------------------------------------
# A Command card: it plays a Supply pile's top card WITHOUT moving it, which is
# ph. 5H's `play_from_supply`. `command_may_play` owns the eligibility rule
# (an Action, not a Command "to prevent loops", and not a Duration since 2025).

def _overlord(game, pid):
    piles = E.playable_from_supply(game, pid, lambda n: E.cost_le(game, n, 5))
    if piles:
        E.push_choose_pile(game, pid, "Overlord", "play", piles)


def _overlord_play(game, pid, frame, choice):
    E.play_from_supply(game, pid, choice["pile"])


# --- Royal Blacksmith --------------------------------------------------------

def _royal_blacksmith(game, pid):
    E.add_cards(game, 5, pid)
    hand = list(game["seats"][pid]["hand"])
    E.reveal(game, pid, hand, "Royal Blacksmith")
    coppers = [c for c in hand if c == "Copper"]
    if coppers:
        E.discard(game, pid, coppers, public=True)


# ══ $3 ═══════════════════════════════════════════════════════════════════════

# --- Chariot Race ------------------------------------------------------------
# 2025: it DRAWS the card rather than revealing the top of the deck and putting
# it in hand. That is why the -1 Card token can deny the bonuses — "if Way of
# the Chameleon or your -1 Card token prevents you from drawing with Chariot
# Race, you don't get the bonuses" — and it falls out of `draw` returning [].

def _chariot_race(game, pid):
    E.add_actions(game, 1)
    drawn = E.draw(game, pid, 1)
    if not drawn:
        return
    mine = drawn[0]
    E.reveal(game, pid, [mine], "Chariot Race")
    left = _left_of(game, pid)
    if left is None:
        return
    theirs = E.look_top(game, left, 1)
    if not theirs:
        return                      # "if either player has no cards to reveal
                                    # (even after shuffling), you don't get the
                                    # bonuses"
    E.reveal(game, left, theirs, "Chariot Race")
    if E.cost(game, mine) > E.cost(game, theirs[0]):
        E.add_coins(game, 1)
        E.add_vp_tokens(game, pid, 1)
    # revealed from the top of the deck: it goes straight back on top
    E.deck_from_aside(game, left, list(theirs))


# --- Enchantress -------------------------------------------------------------
# THE ph.-8 KERNEL CONSUMER. "Until your next turn, the first time each other
# player plays an Action card on their turn, they get +1 Card and +1 Action
# INSTEAD OF following its instructions."
#
# It is not a before-play ability: the compendium puts it in its own timing
# class, after reactions and after before-play abilities — "Enchantress is
# triggered when you WOULD RESOLVE the played Action card. So if you play an
# Enchanted Attack card, Reactions are resolved first, as normal. Good Harvest,
# Kiln, Urchin and Adventures tokens are also resolved first." That timing point
# is the ph.-8 `would_resolve` emit, and replacing the play is
# `cancel_pending_play`.

def _enchantress(game, pid):
    E.add_watcher(game, pid, "Enchantress", "would_resolve", stage="hit")
    E.add_duration_fx(game, pid, "Enchantress", "draw")


def _enchantress_draw(game, pid, frame, choice):
    E.add_cards(game, 2, pid)


def _enchantress_when(game, w, ctx):
    """Does this Enchantress replace THIS play?

    Four conditions, each from the card or the compendium:
      * the played card is an ACTION — "the first Action card they play";
      * the player is not the Enchantress's owner — "each OTHER player";
      * it is that player's own turn — "on their turn", and "Enchantress
        doesn't apply if an opponent somehow plays a card during your turn or
        another player's turn";
      * nothing has been enchanted on this turn yet. That flag is per-TURN
        rather than per-watcher because two Enchantresses do not stack: "the
        first Enchantress replaces what the players do, and Enchantresses after
        that can't replace it again", and it also carries "only the first-played
        Action of each player is affected"."""
    actor = ctx["actor"]
    return (actor is not None and actor != w["owner"] and actor == game["turn"]
            and E.has_type(game, ctx["subject"], "action")
            and not game["turn_ctx"].get("enchanted"))


def _enchantress_hit(game, pid, frame, choice):
    actor = frame["data"]["actor"]
    if game["turn_ctx"].get("enchanted"):
        return                      # another Enchantress got there first
    if not E.cancel_pending_play(game):
        return                      # nothing left to replace
    game["turn_ctx"]["enchanted"] = True
    E._log(game, actor, "enchanted", card=frame["data"]["subject"])
    E.add_cards(game, 1, actor)
    E.add_actions(game, 1, actor)


# --- Farmers' Market ---------------------------------------------------------
# "+1 Buy. If there is 4 VP or more on the Farmers' Market Supply pile, take it
# and trash this. Otherwise, add 1 VP to the pile and then +$1 per 1 VP on it."
# So the first four plays give $1/$2/$3/$4 and the fifth cashes out.

def _farmers_market(game, pid):
    E.add_buys(game, 1)
    pile = _supply_pile_for(game, "Farmers' Market")
    if pile is None:
        return                      # not a Supply pile (Ferryman's extra pile)
    if E.pile_vp(game, pile) >= 4:
        E.take_pile_vp(game, pid, pile)
        # "You get +1 Buy even if you trash this" — and if the card is not on
        # the table (a throne-room replay after the first play trashed it)
        # "you take the tokens even though you can't trash the card".
        if "Farmers' Market" in game["seats"][pid]["in_play"]:
            E.trash(game, pid, ["Farmers' Market"], zone="in_play")
        return
    E.add_pile_vp(game, pile, 1)
    E.add_coins(game, E.pile_vp(game, pile))


# ══ $4 ═══════════════════════════════════════════════════════════════════════

# --- Sacrifice ---------------------------------------------------------------
# "If you trash a card that has several of the types, you get all relevant
# bonuses" — so this is three independent ifs, not a chain.

def _sacrifice(game, pid):
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Sacrifice", "trash", list(hand), 1, 1, "trash")


def _sacrifice_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    E.trash(game, pid, [card])
    if E.has_type(game, card, "action"):
        E.add_cards(game, 2, pid)
        E.add_actions(game, 2)
    if E.has_type(game, card, "treasure"):
        E.add_coins(game, 2)
    if E.has_type(game, card, "victory"):
        E.add_vp_tokens(game, pid, 2)


# --- Temple ------------------------------------------------------------------

def _temple(game, pid):
    E.add_vp_tokens(game, pid, 1)
    hand = game["seats"][pid]["hand"]
    names = sorted(set(hand))
    if names:
        # DIFFERENTLY NAMED, so the offer is one of each name and the count is
        # capped at 3. The engine never feasibility-filters a choice, but the
        # offer itself must not let the player pick two Coppers.
        E.push_choose_cards(game, pid, "Temple", "trash", names,
                            1, min(3, len(names)), "trash")
    _temple_gather(game, pid)


def _temple_gather(game, pid):
    pile = _supply_pile_for(game, "Temple")
    if pile is not None:
        # "Also add VP when the Temple pile is empty" — add_pile_vp works on an
        # empty pile, since a pile object outlives its contents.
        E.add_pile_vp(game, pile, 1)


def _temple_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, choice["cards"])


def _temple_gain(game, pid, frame, choice):
    pile = _supply_pile_for(game, "Temple")
    if pile is not None:
        E.take_pile_vp(game, frame["data"]["actor"], pile)


# --- Villa -------------------------------------------------------------------
# The when-gain is the interesting half: "put it into your hand, +1 Action, and
# if it's your Buy phase return to your Action phase".

def _villa(game, pid):
    E.add_actions(game, 2)
    E.add_buys(game, 1)
    E.add_coins(game, 1)


def _villa_gain(game, pid, frame, choice):
    actor = frame["data"]["actor"]
    # "When you put Villa into your hand, cards like Watchtower lose track of
    # it" — and the reverse: if a Watchtower already moved it, Villa fails to
    # move itself but you still get the +1 Action and the phase change.
    zone = E.find_card_zone(game, actor, "Villa", zones=("discard", "hand"))
    if zone is None:
        E.lost_track(game, actor, "Villa", "put into your hand")
    elif zone != "hand":
        E.to_hand(game, actor, "Villa", zone)
    E.add_actions(game, 1, actor)
    E.return_to_action_phase(game, actor)


# ══ $5 ═══════════════════════════════════════════════════════════════════════

# --- Archive -----------------------------------------------------------------
# "Now and at the start of your next two turns, put one into your hand." A
# repeat that ENDS, which is neither add_duration_fx's one-shot nor ph. 7's
# rest-of-the-game `forever`: the entry rides `forever` to survive the turn
# start and calls `finish_duration` when its own set-aside runs out ("Archive
# will only stay in play as long as it has cards set aside").
#
# The three cards live in `dur_aside` so the conservation census sees them, but
# their NAMES are also recorded on the fx so that two Archives keep SEPARATE
# SETS — "if you play multiple Archives, keep separate sets of cards and take
# one from each set each turn". Zones hold names, so the flat zone alone would
# pool them into one heap.

def _archive(game, pid):
    E.add_actions(game, 1)
    taken = E.look_top(game, pid, 3)
    if not taken:
        return
    E.set_aside_duration(game, pid, taken, zone="aside")
    E.add_duration_fx(game, pid, "Archive", "take", data={"set": list(taken)},
                      forever=True)
    _archive_offer(game, pid, list(taken))


def _archive_take(game, pid, frame, choice):
    _archive_offer(game, pid, list(frame["data"].get("set", [])))


def _archive_offer(game, pid, cards):
    have = game["seats"][pid]["dur_aside"]
    offer = []
    for c in cards:                 # only THIS Archive's set, and only what is
        if c in have and c not in offer:   # actually still set aside
            offer.append(c)
    if not offer:
        E.finish_duration(game, pid, "Archive")
        return
    E.push_choose_cards(game, pid, "Archive", "pick", sorted(offer), 1, 1, "hand")


def _archive_pick(game, pid, frame, choice):
    card = choice["cards"][0]
    E.take_dur_aside(game, pid, [card], dest="hand")
    entry = _archive_entry(game, pid, card)
    if entry is not None:
        entry["set"].remove(card)
        if not entry["set"]:
            E.finish_duration(game, pid, "Archive")


def _archive_entry(game, pid, card):
    """The fx whose recorded set still holds `card` — how two Archives stay
    apart when both are on the table."""
    seat = game["seats"][pid]
    for entry in list(seat["duration"]) + list(seat.get("dur_setup", [])):
        if entry["card"] != "Archive":
            continue
        for fx in entry["fx"]:
            if card in fx.get("data", {}).get("set", []):
                return fx["data"]
    return None


# --- Capital -----------------------------------------------------------------
# 2025: the "then you may pay off Debt" clause is GONE, because the 2024 rules
# change lets you pay off Debt at any time during your turn anyway. The
# compendium keeps the one consequence: "if you somehow play Capital during an
# opponent's turn, you cannot pay off Debt then" — which our `spend` move
# already refuses, being your-turn-only.

def _capital_discarded(game, pid, frame, choice):
    E.add_debt(game, frame["data"]["actor"], 6)


# --- Charm -------------------------------------------------------------------
# 2022: the rider fires on your next GAIN, not your next buy.

def _charm(game, pid):
    E.push_choose_option(game, pid, "Charm", "mode", options=[
        {"id": "coins", "label": "+1 Buy and +$2"},
        {"id": "gain", "label": "The next time you gain a card this turn, "
                                "gain a differently named card with the same cost"}])


def _charm_mode(game, pid, frame, choice):
    if choice["ids"][0] == "coins":
        E.add_buys(game, 1)
        E.add_coins(game, 2)
        return
    # one rider per play, so several Charms give several extra gains
    E.add_watcher(game, pid, "Charm", "gain", stage="rider", until="turn_end")


def _charm_rider_when(game, w, ctx):
    """Only the OWNER's own gains, and only while a rider is unspent. A gain
    with nothing to match (no differently named pile at that cost) still spends
    the rider — the offer is what the card gives you."""
    return ctx["actor"] == w["owner"] and not w["data"].get("spent")


def _charm_rider(game, pid, frame, choice):
    d = frame["data"]
    actor, gained = d["actor"], d["subject"]
    w = E.watcher_data(game, d["owner"], "Charm")
    if w is not None:
        w["spent"] = True
    E.remove_watcher(game, d["owner"], "Charm", n=1)
    if gained is None:
        return
    # "It must be a differently named card with the SAME COST" — the whole
    # vector, which is what cost_eq_card means (a {$5} card is not the same
    # cost as a {$5,P} one).
    picks = _supply_names(game, lambda n: n != gained
                          and E.cost_eq_card(game, n, gained))
    if picks:
        E.push_choose_pile(game, pid, "Charm", "gain", picks)


def _charm_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Crown -------------------------------------------------------------------
# "Crown always counts as both an Action and a Treasure, regardless of what
# phase it is" — what the phase decides is only WHAT it may play twice.

def _crown(game, pid):
    buy_phase = game["phase"] == "buy"
    want = "treasure" if buy_phase else "action"
    hand = game["seats"][pid]["hand"]
    picks = sorted({c for c in hand if E.has_type(game, c, want)})
    if picks:
        E.push_choose_cards(game, pid, "Crown", "play", picks, 0, 1, "play")


def _crown_play(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    if E.find_card_zone(game, pid, card, zones=("hand",)) is None:
        E.lost_track(game, pid, card, "played")
        return
    # THE SECOND PLAY IS PARKED BELOW THE FIRST (LIFO), so the first play
    # COMPLETELY resolves before the replay — "you must completely resolve the
    # play ability before playing it again" (p17), the same shape Throne Room
    # uses. Pushing it afterwards instead put a Crowned Oasis's two discard
    # prompts on the stack in the wrong order, and answering the second one
    # named a card the first had already discarded (found by the ph.-8 fuzz
    # census on an empires+hinterlands+intrigue board).
    kind = "treasure" if E.has_type(game, card, "treasure") \
        and game["phase"] == "buy" else "action"
    E.push_auto(game, pid, "Crown", "again", data={"card": card, "kind": kind})
    if kind == "treasure":
        E.play_treasure_card(game, pid, card)
    else:
        E.play_action_card(game, pid, card)


def _crown_again(game, pid, frame, choice):
    d = frame["data"]
    if d["kind"] == "treasure":
        E.play_treasure_card(game, pid, d["card"], from_zone=None)
    else:
        E.play_action_card(game, pid, d["card"], from_zone=None)
        # a Crown that played a persisting Duration stays on the table with it
        if E.has_type(game, d["card"], "duration"):
            E.mark_duration_rider(game, pid, d["card"], "Crown")


# --- Forum -------------------------------------------------------------------

def _forum(game, pid):
    E.add_cards(game, 3, pid)
    E.add_actions(game, 1)
    hand = game["seats"][pid]["hand"]
    if hand:
        n = min(2, len(hand))
        E.push_choose_cards(game, pid, "Forum", "discard", list(hand), n, n, "discard")


def _forum_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


def _forum_gain(game, pid, frame, choice):
    E.add_buys(game, 1, frame["data"]["actor"])


# --- Groundskeeper -----------------------------------------------------------
# 2022: an ability SET UP for the rest of the turn, not a while-in-play timer.
# "Only Victory cards gained AFTER playing Groundskeeper give you a VP", and it
# is cumulative with a throne-room, which is one watcher per play.

def _groundskeeper(game, pid):
    E.add_cards(game, 1, pid)
    E.add_actions(game, 1)
    E.add_watcher(game, pid, "Groundskeeper", "gain", stage="vp",
                  until="turn_end", commutes=True)


def _groundskeeper_when(game, w, ctx):
    return (ctx["actor"] == w["owner"] and ctx["subject"] is not None
            and E.has_type(game, ctx["subject"], "victory"))


def _groundskeeper_vp(game, pid, frame, choice):
    E.add_vp_tokens(game, frame["data"]["owner"], 1)


# --- Legionary ---------------------------------------------------------------
# "The other players have to resolve any Reactions before you decide whether to
# reveal a Gold" — which is the kernel's ordering already: the reaction windows
# resolve before the play ability, and the reveal choice is inside it.

def _legionary(game, pid):
    E.add_coins(game, 3)
    if "Gold" not in game["seats"][pid]["hand"]:
        return
    E.push_choose_option(game, pid, "Legionary", "reveal", options=[
        {"id": "yes", "label": "Reveal a Gold"},
        {"id": "no", "label": "Don't reveal"}],
        data={"immune": list(game.get("_atk_immune", []))})


def _legionary_reveal(game, pid, frame, choice):
    if choice["ids"][0] != "yes" or "Gold" not in game["seats"][pid]["hand"]:
        return
    E.reveal(game, pid, ["Gold"], "Legionary")
    E.attack_opponents(game, pid, "Legionary", "hit",
                       immune=frame["data"]["immune"])


def _legionary_hit(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    if len(hand) > 2:
        n = len(hand) - 2
        E.push_choose_cards(game, pid, "Legionary", "discard",
                            list(hand), n, n, "discard")
        E.push_auto(game, pid, "Legionary", "draw")
        return
    # "If a player already has 2 or less cards in hand, they still draw 1."
    E.draw(game, pid, 1)


def _legionary_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


def _legionary_draw(game, pid, frame, choice):
    E.draw(game, pid, 1)


# --- Wild Hunt ---------------------------------------------------------------

def _wild_hunt(game, pid):
    E.push_choose_option(game, pid, "Wild Hunt", "mode", options=[
        {"id": "draw", "label": "+3 Cards and add 1 VP to the Wild Hunt pile"},
        {"id": "estate", "label": "Gain an Estate, taking the VP from the pile"}])


def _wild_hunt_mode(game, pid, frame, choice):
    pile = _supply_pile_for(game, "Wild Hunt")
    if choice["ids"][0] == "draw":
        E.add_cards(game, 3, pid)
        # "you add 1 VP even if you can't draw any cards", and "this still
        # functions when the Wild Hunt pile is empty"
        if pile is not None:
            E.add_pile_vp(game, pile, 1)
        return
    # "NOT OPTIONAL IF YOU DO": the VP only come if the Estate is actually
    # gained, and gain() returns False on an empty pile.
    if E.gain(game, pid, "Estate") and pile is not None:
        E.take_pile_vp(game, pid, pile)


# ══ the five SPLIT piles ═════════════════════════════════════════════════════

# --- Encampment / Plunder ----------------------------------------------------

def _encampment(game, pid):
    E.add_cards(game, 2, pid)
    E.add_actions(game, 2)          # "you get +2 Actions even if you set this aside"
    hand = game["seats"][pid]["hand"]
    show = sorted({c for c in hand if c in ("Gold", "Plunder")})
    if not show:
        _encampment_set_aside(game, pid)
        return
    E.push_choose_cards(game, pid, "Encampment", "reveal", show, 0, 1, "reveal")


def _encampment_reveal(game, pid, frame, choice):
    if choice["cards"]:
        E.reveal(game, pid, choice["cards"], "Encampment")
        return
    _encampment_set_aside(game, pid)


def _encampment_set_aside(game, pid):
    # "If you play Encampment without moving it into play, you still get +2
    # Cards and +2 Actions" but "you won't be able to set it aside or return it
    # to its pile" — so this is guarded on the card actually being on the table.
    if "Encampment" in game["seats"][pid]["in_play"]:
        E.return_at_cleanup(game, pid, "Encampment")


def _plunder(game, pid):
    E.add_vp_tokens(game, pid, 1)


# --- Patrician / Emporium ----------------------------------------------------

def _patrician(game, pid):
    E.add_cards(game, 1, pid)
    E.add_actions(game, 1)
    top = E.look_top(game, pid, 1)
    if not top:
        return
    E.reveal(game, pid, top, "Patrician")
    if E.cost_ge(game, top[0], 5):
        E.take_aside(game, pid, top, dest="hand")
    else:
        E.deck_from_aside(game, pid, list(top))


def _emporium(game, pid):
    E.add_cards(game, 1, pid)
    E.add_actions(game, 1)
    E.add_coins(game, 1)


def _emporium_gain(game, pid, frame, choice):
    actor = frame["data"]["actor"]
    n = sum(1 for c in game["seats"][actor]["in_play"]
            if E.has_type(game, c, "action"))
    if n >= 5:
        E.add_vp_tokens(game, actor, 2)


# --- Settlers / Bustling Village ---------------------------------------------

def _from_discard(card, want):
    """Settlers and Bustling Village differ only in which card they fish for:
    "look through your discard pile; you may reveal a <X> from it and put it
    into your hand"."""
    def fx(game, pid):
        E.add_cards(game, 1, pid)
        E.add_actions(game, 1 if card == "Settlers" else 3)
        if want not in game["seats"][pid]["discard"]:
            return
        E.push_choose_option(game, pid, card, "take", options=[
            {"id": "yes", "label": f"Reveal a {want} and put it into your hand"},
            {"id": "no", "label": "Take nothing"}], data={"want": want})
    return fx


def _from_discard_take(game, pid, frame, choice):
    if choice["ids"][0] != "yes":
        return
    want = frame["data"]["want"]
    seat = game["seats"][pid]
    if want not in seat["discard"]:
        E.lost_track(game, pid, want, "revealed")
        return
    E.reveal(game, pid, [want], frame["card"])
    E.to_hand(game, pid, want, "discard")


# --- Catapult / Rocks --------------------------------------------------------

def _catapult(game, pid):
    E.add_coins(game, 1)            # "even if you have no cards in hand to trash"
    hand = game["seats"][pid]["hand"]
    if not hand:
        return
    E.push_choose_cards(game, pid, "Catapult", "trash", list(hand), 1, 1, "trash",
                        data={"immune": list(game.get("_atk_immune", []))})


def _catapult_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    # the cost is read BEFORE the trash, the same capture the remodel family
    # makes (deviation B3) — nothing in the pool changes cost on being trashed
    cheap = not E.cost_ge(game, card, 3)
    treasure = E.has_type(game, card, "treasure")
    E.trash(game, pid, [card])
    immune = frame["data"]["immune"]
    # Both halves can apply to one trashed card (a Gold is a $6 Treasure), and
    # each is its own pass over the opponents in turn order. Pushed in REVERSE
    # card order because the stack is LIFO: the Curse is the card's first
    # sentence, so it has to be queued last to resolve first.
    if treasure:
        E.attack_opponents(game, pid, "Catapult", "discard", immune=immune)
    if not cheap:
        E.attack_opponents(game, pid, "Catapult", "curse", immune=immune)


def _catapult_curse(game, pid, frame, choice):
    E.gain(game, pid, "Curse")


def _catapult_discard(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    if len(hand) > 3:
        n = len(hand) - 3
        E.push_choose_cards(game, pid, "Catapult", "down_to",
                            list(hand), n, n, "discard")


def _catapult_down_to(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])


def _rocks_silver(game, pid, frame, choice):
    """"Gain a Silver; put it onto your deck if it's your Buy phase, otherwise
    into your hand." Fires on BOTH gaining and trashing a Rocks — and "if you
    gain or trash Rocks on another player's turn, the Silver goes to your
    hand", which the phase test gives for free (it is never your Buy phase on
    someone else's turn)."""
    actor = frame["data"]["actor"]
    buy = actor == game["turn"] and game["phase"] == "buy"
    E.gain(game, actor, "Silver", dest="deck" if buy else "hand")


# --- Gladiator / Fortune -----------------------------------------------------

def _gladiator(game, pid):
    E.add_coins(game, 2)
    hand = game["seats"][pid]["hand"]
    if not hand:
        # "From rulebook: if either player has no card to reveal, you get +$1
        # and trash a Gladiator."
        _gladiator_score(game, pid)
        return
    E.push_choose_cards(game, pid, "Gladiator", "reveal",
                        sorted(set(hand)), 1, 1, "reveal")


def _gladiator_reveal(game, pid, frame, choice):
    card = choice["cards"][0]
    E.reveal(game, pid, [card], "Gladiator")
    left = _left_of(game, pid)
    if left is not None and card in game["seats"][left]["hand"]:
        # they must reveal a copy — no choice, so no frame
        E.reveal(game, left, [card], "Gladiator")
        return
    _gladiator_score(game, pid)


def _gladiator_score(game, pid):
    E.add_coins(game, 1)            # "you get +$1 even if there are no
                                    # Gladiators in the Supply to trash"
    pile = _supply_pile_for(game, "Gladiator")
    # "You can only trash a Gladiator if it's on top of the pile."
    if pile is not None and E.pile_top(game, pile) == "Gladiator":
        E.trash_from_supply(game, pile)


def _fortune(game, pid):
    E.add_buys(game, 1)
    # "Playing Fortune a second time in a turn only gives you +1 Buy" — the
    # doubling is once per turn, not once per copy.
    if game["turn_ctx"].get("fortune"):
        return
    game["turn_ctx"]["fortune"] = True
    E.add_coins(game, game["coins"])


def _fortune_gain(game, pid, frame, choice):
    actor = frame["data"]["actor"]
    for _ in range(game["seats"][actor]["in_play"].count("Gladiator")):
        E.gain(game, actor, "Gold")


# ══ the CASTLES ══════════════════════════════════════════════════════════════

def _castle_pile(game):
    """The Castles pile, if this game has one — every Castle that gains another
    Castle gains "a Castle" from the Supply, i.e. the top of that pile."""
    return _supply_pile_for(game, "Humble Castle")


def _crumbling_castle(game, pid, frame, choice):
    """"When you gain or trash this, +1 VP and gain a Silver." """
    actor = frame["data"]["actor"]
    E.add_vp_tokens(game, actor, 1)
    E.gain(game, actor, "Silver")   # "+1 VP even if there are no Silvers left"


def _small_castle(game, pid):
    hand = game["seats"][pid]["hand"]
    opts = []
    if "Small Castle" in game["seats"][pid]["in_play"]:
        opts.append({"id": "self", "label": "Trash this Small Castle"})
    castles = sorted({c for c in hand if E.has_type(game, c, "castle")})
    for c in castles:
        opts.append({"id": f"hand:{c}", "label": f"Trash {c} from your hand"})
    if not opts:
        return
    opts.append({"id": "no", "label": "Trash nothing"})
    E.push_choose_option(game, pid, "Small Castle", "trash", options=opts)


def _small_castle_trash(game, pid, frame, choice):
    pick = choice["ids"][0]
    if pick == "no":
        return
    if pick == "self":
        if "Small Castle" not in game["seats"][pid]["in_play"]:
            E.lost_track(game, pid, "Small Castle", "trashed")
            return
        E.trash(game, pid, ["Small Castle"], zone="in_play")
    else:
        card = pick.split(":", 1)[1]
        if card not in game["seats"][pid]["hand"]:
            E.lost_track(game, pid, card, "trashed")
            return
        E.trash(game, pid, [card])
    # "NOT OPTIONAL IF YOU DO" — the gain only follows a trash that happened
    pile = _castle_pile(game)
    if pile is not None:
        E.gain(game, pid, pile)


def _haunted_castle_gain(game, pid, frame, choice):
    """"When you gain this ON YOUR TURN, gain a Gold, and each other player with
    5 or more cards in hand puts 2 cards from their hand onto their deck."

    Not an attack: "the other players can't use Reactions that trigger on an
    Attack being played, since you didn't play an Attack"."""
    actor = frame["data"]["actor"]
    if actor != game["turn"]:
        return
    E.gain(game, actor, "Gold")     # "if there are no Golds left, the players
                                    # still put cards onto their deck"
    # compendium: first you gain the Gold, THEN the opponents put cards back
    for o in reversed(E.opponents(game, actor)):
        if len(game["seats"][o]["hand"]) >= 5:
            E.push_auto(game, o, "Haunted Castle", "topdeck")


def _haunted_castle_topdeck(game, pid, frame, choice):
    hand = game["seats"][pid]["hand"]
    if len(hand) < 5:
        return
    E.push_choose_cards(game, pid, "Haunted Castle", "put",
                        list(hand), 2, 2, "topdeck")


def _haunted_castle_put(game, pid, frame, choice):
    E.push_order_cards(game, pid, "Haunted Castle", "order", list(choice["cards"]))


def _haunted_castle_order(game, pid, frame, choice):
    for card in reversed(choice["order"]):
        E.topdeck(game, pid, card)


def _opulent_castle(game, pid):
    hand = game["seats"][pid]["hand"]
    vic = [c for c in hand if E.has_type(game, c, "victory")]
    if not vic:
        return
    E.push_choose_cards(game, pid, "Opulent Castle", "discard",
                        sorted(vic), 0, len(vic), "discard")


def _opulent_castle_discard(game, pid, frame, choice):
    cards = choice["cards"]
    if not cards:
        return
    # 2021: "you REVEAL the Victory cards as you discard them"
    E.reveal(game, pid, list(cards), "Opulent Castle")
    E.discard(game, pid, list(cards))
    E.add_coins(game, 2 * len(cards))


def _sprawling_castle_gain(game, pid, frame, choice):
    E.push_choose_option(game, pid, "Sprawling Castle", "pick",
                         options=[{"id": "duchy", "label": "Gain a Duchy"},
                                  {"id": "estates", "label": "Gain 3 Estates"}],
                         data={"actor": frame["data"]["actor"]})


def _sprawling_castle_pick(game, pid, frame, choice):
    actor = frame["data"]["actor"]
    if choice["ids"][0] == "duchy":
        E.gain(game, actor, "Duchy")
        return
    for _ in range(3):
        E.gain(game, actor, "Estate")


def _grand_castle_gain(game, pid, frame, choice):
    actor = frame["data"]["actor"]
    hand = list(game["seats"][actor]["hand"])
    E.reveal(game, actor, hand, "Grand Castle")
    n = sum(1 for c in hand if E.has_type(game, c, "victory"))
    # "This counts Victory cards IN PLAY, but not just in your play area. If
    # other players have Victory cards in play, they count too."
    n += sum(1 for c in _in_play_all(game) if E.has_type(game, c, "victory"))
    if n:
        E.add_vp_tokens(game, actor, n)


# ══ registration: the kingdom half ═══════════════════════════════════════════

EFFECTS.update({
    "Engineer": _engineer,
    "City Quarter": _city_quarter,
    "Overlord": _overlord,
    "Royal Blacksmith": _royal_blacksmith,
    "Chariot Race": _chariot_race,
    "Enchantress": _enchantress,
    "Farmers' Market": _farmers_market,
    "Sacrifice": _sacrifice,
    "Temple": _temple,
    "Villa": _villa,
    "Archive": _archive,
    "Charm": _charm,
    "Crown": _crown,
    "Forum": _forum,
    "Groundskeeper": _groundskeeper,
    "Legionary": _legionary,
    "Wild Hunt": _wild_hunt,
    # split piles
    "Encampment": _encampment,
    "Plunder": _plunder,
    "Patrician": _patrician,
    "Emporium": _emporium,
    "Settlers": _from_discard("Settlers", "Copper"),
    "Bustling Village": _from_discard("Bustling Village", "Settlers"),
    "Catapult": _catapult,
    "Gladiator": _gladiator,
    "Fortune": _fortune,
    # Castles (the four with a play ability; the rest are data only)
    "Small Castle": _small_castle,
    "Opulent Castle": _opulent_castle,
})

STAGES.update({
    ("Engineer", "gain"): _engineer_gain,
    ("Engineer", "may_trash"): _engineer_may_trash,
    ("Engineer", "trash"): _engineer_trash,
    ("Overlord", "play"): _overlord_play,
    ("Enchantress", "draw"): _enchantress_draw,
    ("Enchantress", "hit"): _enchantress_hit,
    ("Sacrifice", "trash"): _sacrifice_trash,
    ("Temple", "trash"): _temple_trash,
    ("Temple", "gain"): _temple_gain,
    ("Villa", "gain"): _villa_gain,
    ("Archive", "take"): _archive_take,
    ("Archive", "pick"): _archive_pick,
    ("Capital", "discarded"): _capital_discarded,
    ("Charm", "mode"): _charm_mode,
    ("Charm", "rider"): _charm_rider,
    ("Charm", "gain"): _charm_gain,
    ("Crown", "play"): _crown_play,
    ("Crown", "again"): _crown_again,
    ("Forum", "discard"): _forum_discard,
    ("Forum", "gain"): _forum_gain,
    ("Groundskeeper", "vp"): _groundskeeper_vp,
    ("Legionary", "reveal"): _legionary_reveal,
    ("Legionary", "hit"): _legionary_hit,
    ("Legionary", "discard"): _legionary_discard,
    ("Legionary", "draw"): _legionary_draw,
    ("Wild Hunt", "mode"): _wild_hunt_mode,
    ("Encampment", "reveal"): _encampment_reveal,
    ("Emporium", "gain"): _emporium_gain,
    ("Settlers", "take"): _from_discard_take,
    ("Bustling Village", "take"): _from_discard_take,
    ("Catapult", "trash"): _catapult_trash,
    ("Catapult", "curse"): _catapult_curse,
    ("Catapult", "discard"): _catapult_discard,
    ("Catapult", "down_to"): _catapult_down_to,
    ("Rocks", "silver"): _rocks_silver,
    ("Gladiator", "reveal"): _gladiator_reveal,
    ("Fortune", "gain"): _fortune_gain,
    ("Crumbling Castle", "both"): _crumbling_castle,
    ("Small Castle", "trash"): _small_castle_trash,
    ("Haunted Castle", "gain"): _haunted_castle_gain,
    ("Haunted Castle", "topdeck"): _haunted_castle_topdeck,
    ("Haunted Castle", "put"): _haunted_castle_put,
    ("Haunted Castle", "order"): _haunted_castle_order,
    ("Opulent Castle", "discard"): _opulent_castle_discard,
    ("Sprawling Castle", "gain"): _sprawling_castle_gain,
    ("Sprawling Castle", "pick"): _sprawling_castle_pick,
    ("Grand Castle", "gain"): _grand_castle_gain,
})

TRIGGERS.update({
    # when-GAIN abilities. Every one of these that also names the Buy phase is
    # a 2022 retiming, not the original card.
    "Temple": [{"on": "gain", "from": "self", "stage": "gain"}],
    "Villa": [{"on": "gain", "from": "self", "stage": "gain"}],
    "Forum": [{"on": "gain", "from": "self", "stage": "gain"}],
    "Emporium": [{"on": "gain", "from": "self", "stage": "gain"}],
    "Fortune": [{"on": "gain", "from": "self", "stage": "gain"}],
    "Crumbling Castle": [{"on": "gain", "from": "self", "stage": "both"},
                         {"on": "trash", "from": "self", "stage": "both"}],
    "Haunted Castle": [{"on": "gain", "from": "self", "stage": "gain"}],
    "Sprawling Castle": [{"on": "gain", "from": "self", "stage": "gain"}],
    "Grand Castle": [{"on": "gain", "from": "self", "stage": "gain"}],
    "Rocks": [{"on": "gain", "from": "self", "stage": "silver"},
              {"on": "trash", "from": "self", "stage": "silver"}],
    # "When you discard this from play, take 6 Debt" — ph. 5H's cleanup_discard,
    # which fires while the card is still in play, so "if you remove Capital
    # from play, preventing it from being discarded, you don't get the Debt"
    # falls out of the emit never happening.
    "Capital": [{"on": "cleanup_discard", "from": "self", "stage": "discarded"}],
})

WATCHER_WHENS.update({
    ("Enchantress", "hit"): _enchantress_when,
    ("Charm", "rider"): _charm_rider_when,
    ("Groundskeeper", "vp"): _groundskeeper_when,
})

# Charm and Crown both push a decision frame when played, so the bulk
# "Play all treasures" cannot answer them mid-run.
MANUAL_TREASURES.update({"Charm", "Crown"})


# ══ the 13 EVENTS ════════════════════════════════════════════════════════════
#
# Bought with `buy_landscape` (ph. 6H), which spends a Buy and the coins and
# emits nothing — no gain, no buy — so no Hoard/Haggler-class watcher sees an
# Event purchase. Four of them cost Debt, which is ph. 7H's dimension: the buy
# flow takes the Debt after the coins, and the buyer then cannot buy anything
# else at all until they have paid it off.

def _ev_advance(game, pid):
    hand = game["seats"][pid]["hand"]
    actions = sorted({c for c in hand if E.has_type(game, c, "action")})
    if actions:
        E.push_choose_cards(game, pid, "Advance", "trash", actions, 0, 1, "trash")


def _ev_advance_trash(game, pid, frame, choice):
    if not choice["cards"]:
        return                      # "you MAY trash" — no trash, no gain
    E.trash(game, pid, choice["cards"])
    picks = _supply_names(game, lambda n: E.cost_le(game, n, 6)
                          and E.has_type(game, n, "action"))
    if picks:
        E.push_choose_pile(game, pid, "Advance", "gain", picks)


def _ev_advance_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


def _ev_annex(game, pid):
    """"Look through your discard pile. Shuffle all but up to 5 cards from it
    into your deck. Gain a Duchy." The choice is which cards to KEEP out of the
    shuffle, and the Duchy is parked underneath so it lands afterwards."""
    E.push_auto(game, pid, "Annex", "duchy")
    discard = game["seats"][pid]["discard"]
    if not discard:
        return                      # "if you have no cards in your discard
                                    # pile, you still gain a Duchy"
    E.push_choose_cards(game, pid, "Annex", "keep", list(discard),
                        0, min(5, len(discard)), "keep")


def _ev_annex_keep(game, pid, frame, choice):
    kept = list(choice["cards"])
    rest = list(game["seats"][pid]["discard"])
    for c in kept:
        if c in rest:
            rest.remove(c)
    # "If you have 5 or less cards in your discard pile and choose to shuffle
    # ZERO cards into your deck, you still shuffle" — which shuffle_into_deck
    # does on an empty list by contract (ph. 3, Inn).
    E.shuffle_into_deck(game, pid, rest, zone="discard")


def _ev_annex_duchy(game, pid, frame, choice):
    E.gain(game, pid, "Duchy")


def _ev_banquet(game, pid):
    E.gain(game, pid, "Copper")
    E.gain(game, pid, "Copper")     # "if there are no Coppers left in the
                                    # Supply, you still gain the other card"
    picks = _supply_names(game, lambda n: E.cost_le(game, n, 5)
                          and not E.has_type(game, n, "victory"))
    if picks:
        E.push_choose_pile(game, pid, "Banquet", "gain", picks)


def _ev_banquet_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


def _ev_conquest(game, pid):
    E.gain(game, pid, "Silver")
    E.gain(game, pid, "Silver")
    # "+1 VP per Silver you've gained this turn" — counted AFTER these two, and
    # "only Silvers gained up to and including this Conquest are counted",
    # which is what reading the running list gives.
    n = _turn_gains(game).count("Silver")
    if n:
        E.add_vp_tokens(game, pid, n)


def _ev_delve(game, pid):
    E.add_buys(game, 1)
    E.gain(game, pid, "Silver")


def _ev_dominate(game, pid):
    if E.gain(game, pid, "Province"):    # NOT OPTIONAL "IF YOU DO"
        E.add_vp_tokens(game, pid, 9)


def _ev_donate(game, pid):
    """2021: Donate now triggers at the START OF YOUR NEXT TURN rather than
    after this one. `add_start_fx` is the seat-level start-of-turn hook (ph. 4)
    — there is no card on the table to hang a Duration entry off."""
    E.add_start_fx(game, pid, "Donate", "trash")


def _ev_donate_trash(game, pid, frame, choice):
    seat = game["seats"][pid]
    seat["hand"].extend(seat["deck"])
    seat["hand"].extend(seat["discard"])
    seat["deck"] = []
    seat["discard"] = []
    E._mark_revealed(game)          # the player now sees their whole deck
    hand = list(seat["hand"])
    E.push_auto(game, pid, "Donate", "reshuffle")
    if hand:
        E.push_choose_cards(game, pid, "Donate", "pick", hand, 0, len(hand), "trash")


def _ev_donate_pick(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, list(choice["cards"]))


def _ev_donate_reshuffle(game, pid, frame, choice):
    seat = game["seats"][pid]
    # The draw is a CONTINUATION pushed before the shuffle (ph. 9): a Star
    # Chart owner's pick frame parks inside shuffle_into_deck, and the draw
    # must resolve after the pick — push-the-continuation-FIRST, the standing
    # ordering rule.
    E.push_auto(game, pid, "Donate", "draw")
    # "At the end of Donate, you shuffle your HAND (not cards that might be in
    # your discard pile, such as due to Market Square)."
    E.shuffle_into_deck(game, pid, list(seat["hand"]), zone="hand")


def _ev_donate_draw(game, pid, frame, choice):
    E.draw(game, pid, 5)            # "you'll still have 5 cards after
                                    # resolving Donate"


def _ev_ritual(game, pid):
    if not E.gain(game, pid, "Curse"):
        return                      # NOT OPTIONAL "IF YOU DO"
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Ritual", "trash", list(hand), 1, 1, "trash")


def _ev_ritual_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    E.trash(game, pid, [card])
    # 2025: "Ritual now checks what the cost of the card is AFTER it's
    # trashed, just like Salvager" — so the cost is read HERE rather than
    # captured before the trash the way the remodel family does (B3).
    n = E.cost(game, card)
    if n:
        E.add_vp_tokens(game, pid, n)


def _ev_salt_the_earth(game, pid):
    E.add_vp_tokens(game, pid, 1)   # "you get the initial +1 VP even if there
                                    # are no Victory cards left in the Supply"
    # "You can only trash the TOP card of a pile", so the test is the top card
    picks = _supply_names(game, lambda n: E.has_type(game, E.pile_top(game, n),
                                                     "victory"))
    if picks:
        E.push_choose_pile(game, pid, "Salt the Earth", "trash", picks)


def _ev_salt_the_earth_trash(game, pid, frame, choice):
    E.trash_from_supply(game, choice["pile"], pid)


def _ev_tax(game, pid):
    piles = _supply_names(game) or sorted(game["supply"])
    if piles:
        E.push_choose_pile(game, pid, "Tax", "pile", piles)


def _ev_tax_pile(game, pid, frame, choice):
    E.add_pile_debt(game, choice["pile"], 2)


def _tax_setup(game, rng):
    """"Setup: Add 1 Debt to each Supply pile: THIS INCLUDES BASE CARDS." """
    for name in sorted(game["supply"]):
        E.add_pile_debt(game, name, 1)


def _tax_when(game, pid, ctx):
    return _gained_in_buy_phase(game, pid, ctx)


def _tax_take(game, pid, frame, choice):
    """"When a player gains a card in their Buy phase, they take the Debt from
    its pile." Taking Debt is a PENALTY — Tax is the one Event you buy to make
    the board worse, yourself included. 2022 retiming: it used to be when-buy,
    so a Workshop gain left the tokens alone; now any Buy-phase gain takes them,
    "wherever you gain the card from (e.g. the trash pile)"."""
    actor = frame["data"]["actor"]
    pile = E.pile_of(game, frame["data"]["subject"])
    if pile is not None:
        E.take_pile_debt(game, actor, pile)


def _ev_triumph(game, pid):
    if not E.gain(game, pid, "Estate"):
        return                      # NOT OPTIONAL "IF YOU DO"
    # "+1 VP per card you've gained this turn", counting the Estate itself:
    # "only the cards gained up to and including this Triumph are counted"
    n = len(_turn_gains(game))
    if n:
        E.add_vp_tokens(game, pid, n)


def _ev_wedding(game, pid):
    E.add_vp_tokens(game, pid, 1)   # "you get the initial +1 VP even if there
                                    # are no Golds left in the Supply"
    E.gain(game, pid, "Gold")


def _ev_windfall(game, pid):
    seat = game["seats"][pid]
    if seat["deck"] or seat["discard"]:
        return
    for _ in range(3):
        E.gain(game, pid, "Gold")


# ══ the 21 LANDMARKS ═════════════════════════════════════════════════════════
#
# A Landmark is never bought and never owned: "a Landmark's ability is always
# active for all players". Eleven are nothing but a `LANDSCAPE_SCORING`
# function; the rest trigger during the game through `from:"landscape"`, which
# hands the ability to the event's ACTOR.
#
# Nine have a setup rule. Six of those are the same one — "put 6 VP tokens
# multiplied by the number of players on this" — and the stores they seed are
# ph. 7H's `add_landscape_vp` / `take_landscape_vp`, which cap a take at what
# is actually there, so "if there are none left you get nothing" is free.

def _self_store(name):
    """"Setup: Put 6 VP per player on this" — Arena, Basilica, Baths,
    Battlefield, Colonnade, Labyrinth."""
    def setup(game, rng):
        E.add_landscape_vp(game, name, 6 * len(game["players"]))
    return setup


def _take_two(name, stage_name):
    """The five landmarks whose whole ability is "take 2 VP from this"."""
    def stage(game, pid, frame, choice):
        E.take_landscape_vp(game, name, frame["data"]["actor"], 2)
    stage.__name__ = stage_name
    return stage


# --- Aqueduct ----------------------------------------------------------------
# TWO when-gain abilities, and they are deliberately NOT `commutes`: "this has
# two different when-gain abilities; if you gain a card of BOTH types, you can
# resolve them in either order" — and the order is worth real VP, because a
# Humble Castle is a Treasure AND a Victory card, so moving a token onto
# Aqueduct first means taking that token too.

def _aqueduct_setup(game, rng):
    for name in ("Silver", "Gold"):
        if name in game["piles"]:
            E.add_pile_vp(game, name, 8)


def _aqueduct_treasure_when(game, pid, ctx):
    return ctx["subject"] is not None and E.has_type(game, ctx["subject"], "treasure")


def _aqueduct_treasure(game, pid, frame, choice):
    """"When you gain a Treasure, move 1 VP from its pile to this" — from the
    pile the card BELONGS to, "wherever you gain the card from (e.g. the trash
    pile)"."""
    pile = E.pile_of(game, frame["data"]["subject"])
    if pile is None or E.pile_vp(game, pile) <= 0:
        return
    E._pile_counter(game, pile, "vp", -1)
    E.add_landscape_vp(game, "Aqueduct", 1)


def _victory_gain_when(game, pid, ctx):
    return ctx["subject"] is not None and E.has_type(game, ctx["subject"], "victory")


def _aqueduct_victory(game, pid, frame, choice):
    E.take_landscape_vp(game, "Aqueduct", frame["data"]["actor"])


# --- Arena -------------------------------------------------------------------

def _arena_when(game, pid, ctx):
    """"At the start of your Buy phase, you may discard an Action card." The
    offer opens whenever you HAVE one — "you may discard an Action card even if
    there are no more tokens", so an empty Arena still asks."""
    return any(E.has_type(game, c, "action") for c in game["seats"][pid]["hand"])


def _arena(game, pid, frame, choice):
    actions = sorted({c for c in game["seats"][pid]["hand"]
                      if E.has_type(game, c, "action")})
    if actions:
        E.push_choose_cards(game, pid, "Arena", "discard", actions, 0, 1, "discard")


def _arena_discard(game, pid, frame, choice):
    if not choice["cards"]:
        return
    E.discard(game, pid, list(choice["cards"]), public=True)
    E.take_landscape_vp(game, "Arena", pid, 2)


# --- Basilica / Battlefield / Colonnade / Labyrinth / Baths -------------------

def _basilica_when(game, pid, ctx):
    """"When you gain a card in your Buy phase, if you have $2 or more, take 2
    VP." The money-pool test is at the moment of the gain — "if you buy several
    cards, then for each of them, check if you have $2 or more left AT THAT
    TIME"."""
    return _gained_in_buy_phase(game, pid, ctx) and game["coins"] >= 2


def _colonnade_when(game, pid, ctx):
    """"…if you have a COPY OF IT in play." One take per trigger even with two
    copies on the table, which is what a single pool entry gives."""
    return (_gained_in_buy_phase(game, pid, ctx)
            and ctx["subject"] is not None
            and E.has_type(game, ctx["subject"], "action")
            and ctx["subject"] in game["seats"][pid]["in_play"])


def _labyrinth_when(game, pid, ctx):
    """"When you gain a 2ND card in one of your turns" — the second, not every
    one after it, and "Labyrinth doesn't trigger if you gain cards during an
    opponent's turn"."""
    return pid == game["turn"] and len(_turn_gains(game)) == 2


def _baths_when(game, pid, ctx):
    """"When you end your turn without having gained a card." Clean-up starting
    is the turn ending, and `_turn_gains` is emptied only afterwards."""
    return pid == game["turn"] and not _turn_gains(game)


# --- Defiled Shrine ----------------------------------------------------------

def _defiled_shrine_setup(game, rng):
    """"Setup: Move 2 VP from here to each ACTION Supply pile."

    Reads the PILE's identity, not its face: "regarding Defiled Shrine and
    Obelisk identifying Action piles, see SPLIT PILES: PILE TYPE AND COST", so
    Catapult/Rocks counts and Castles does not. "Remember that Ruins is also an
    Action Supply pile." Gathering piles are excluded — the tokens they gather
    are their own, and there is currently no way to put Defiled Shrine's on
    them ("there is currently no way to put VP tokens on the Castle pile")."""
    for name in sorted(game["supply"]):
        if E.pile_has_type(game, name, "action") \
                and not E.pile_has_type(game, name, "gathering"):
            E.add_pile_vp(game, name, 2)


def _defiled_shrine_action_when(game, pid, ctx):
    return ctx["subject"] is not None and E.has_type(game, ctx["subject"], "action")


def _defiled_shrine_action(game, pid, frame, choice):
    pile = E.pile_of(game, frame["data"]["subject"])
    if pile is None or E.pile_vp(game, pile) <= 0:
        return
    E._pile_counter(game, pile, "vp", -1)
    E.add_landscape_vp(game, "Defiled Shrine", 1)


def _defiled_shrine_curse_when(game, pid, ctx):
    return _gained_in_buy_phase(game, pid, ctx) and ctx["subject"] == "Curse"


def _defiled_shrine_curse(game, pid, frame, choice):
    E.take_landscape_vp(game, "Defiled Shrine", frame["data"]["actor"])


# --- Tomb --------------------------------------------------------------------

def _tomb(game, pid, frame, choice):
    """"When you trash a card, +1 VP." One per card — a multi-card trash goes
    through emit_batch, which collects one pool entry per subject. "This might
    happen on your turn or on an opponent's turn", and it "triggers even when
    you trash a card from the Supply" (which is why `trash_from_supply` learned
    to emit). "If an effect tells you to trash a card but you fail to do so,
    Tomb doesn't trigger" — no trash, no emit."""
    E.add_vp_tokens(game, frame["data"]["actor"], 1)


# --- Mountain Pass -----------------------------------------------------------
# The only cross-player AUCTION in the game. 2022: "Mountain Pass is now
# resolved right when you gain the Province", so the winner "will possibly get
# the VP before buying other things, but might pay off some or all of the Debt
# this turn".

def _mountain_pass_when(game, pid, ctx):
    st = game["landscapes"].get("Mountain Pass") or {}
    return ctx["subject"] == "Province" and not st.get("done")


def _mountain_pass(game, pid, frame, choice):
    actor = frame["data"]["actor"]
    st = game["landscapes"]["Mountain Pass"]
    if st.get("done"):
        return
    st["done"] = True               # "this can only trigger once in the game"
    # "each player, STARTING WITH THE PLAYER TO YOUR LEFT, bids once, ending
    # with you" — opponents() is already in turn order from the actor
    queue = E.opponents(game, actor) + [actor]
    E.push_auto(game, actor, "Mountain Pass", "bid",
                data={"queue": queue, "high": 0, "high_pid": None})


_MAX_BID = 40                       # "up to 40 Debt"


def _mountain_pass_bid(game, pid, frame, choice):
    d = frame["data"]
    queue = list(d["queue"])
    if not queue:
        if d["high_pid"] is not None:
            E.add_vp_tokens(game, d["high_pid"], 8)
            E.add_debt(game, d["high_pid"], d["high"])
        return
    bidder, rest = queue[0], queue[1:]
    opts = [{"id": "pass", "label": "Pass"}]
    for n in range(d["high"] + 1, _MAX_BID + 1):
        opts.append({"id": str(n), "label": f"Bid {n} Debt"})
    E.push_choose_option(game, bidder, "Mountain Pass", "pick", options=opts,
                         data={**d, "queue": rest, "bidder": bidder})


def _mountain_pass_pick(game, pid, frame, choice):
    d = dict(frame["data"])
    pick = choice["ids"][0]
    if pick != "pass":
        d["high"] = int(pick)
        d["high_pid"] = d["bidder"]
    d.pop("bidder", None)
    E.push_auto(game, d["queue"][0] if d["queue"] else d.get("high_pid") or pid,
                "Mountain Pass", "bid", data=d)


# --- the eleven WHEN-SCORING landmarks ───────────────────────────────────────
#
# Pure functions of a final deck, which is exactly what ph. 7H's
# LANDSCAPE_SCORING hook takes. `_post_move` recomputes them after every move,
# so they also display live during the game for free.

def _counts(game, pid):
    out = {}
    for c in E.owned_cards(game, pid):
        out[c] = out.get(c, 0) + 1
    return out


def _sc_bandit_fort(game, pid):
    owned = E.owned_cards(game, pid)
    return -2 * (owned.count("Silver") + owned.count("Gold"))


def _sc_fountain(game, pid):
    return 15 if E.owned_cards(game, pid).count("Copper") >= 10 else 0


def _sc_keep(game, pid):
    """"5 VP per differently named Treasure you have, that you have more copies
    of than each other player. If there is a tie for a Treasure, ALL TIED
    PLAYERS get 5 VP." """
    mine = _counts(game, pid)
    others = [_counts(game, p) for p in game["players"] if p != pid]
    total = 0
    for card, n in mine.items():
        if not E.has_type(game, card, "treasure"):
            continue
        if all(n >= o.get(card, 0) for o in others):
            total += 5
    return total


def _sc_museum(game, pid):
    return 2 * len(set(E.owned_cards(game, pid)))


def _sc_obelisk(game, pid):
    """"2 VP per card you have from the chosen pile" — ALL cards from that pile,
    so a split pile scores for both halves ("if Gladiator/Fortune is chosen for
    Obelisk, both cards score at game end")."""
    pile = (game["landscapes"].get("Obelisk") or {}).get("pile")
    if pile is None:
        return 0
    return 2 * sum(1 for c in E.owned_cards(game, pid)
                   if E.pile_of(game, c) == pile)


def _obelisk_setup(game, rng):
    """"Setup: Choose a random ACTION Supply pile." Pile identity again, so a
    split pile can be chosen and both of its cards then score."""
    picks = [n for n in sorted(game["supply"])
             if E.pile_has_type(game, n, "action")]
    if picks:
        game["landscapes"]["Obelisk"]["pile"] = rng.choice(picks)


def _sc_orchard(game, pid):
    return 4 * sum(1 for c, n in _counts(game, pid).items()
                   if n >= 3 and E.has_type(game, c, "action"))


def _sc_palace(game, pid):
    """"3 VP per set of Copper-Silver-Gold you have. A card isn't counted in
    more than one set." """
    owned = E.owned_cards(game, pid)
    return 3 * min(owned.count("Copper"), owned.count("Silver"),
                   owned.count("Gold"))


def _sc_tower(game, pid):
    """"1 VP per non-Victory card you have from EMPTY Supply piles." """
    total = 0
    for c in E.owned_cards(game, pid):
        if E.has_type(game, c, "victory"):
            continue
        pile = E.pile_of(game, c)
        if pile is not None and E.is_supply_pile(game, pile) \
                and E.pile_count(game, pile) == 0:
            total += 1
    return total


def _sc_triumphal_arch(game, pid):
    """"3 VP per copy you have of the 2nd most common Action card among your
    differently named Action cards. If it's a tie for most copies or for second
    most copies, you score for one of the tied cards" — which is what taking
    the second entry of the sorted counts does."""
    counts = sorted((n for c, n in _counts(game, pid).items()
                     if E.has_type(game, c, "action")), reverse=True)
    return 3 * counts[1] if len(counts) >= 2 else 0


def _sc_wall(game, pid):
    """"-1 VP per card you have after the first 15." """
    return -max(0, len(E.owned_cards(game, pid)) - 15)


def _sc_wolf_den(game, pid):
    return -3 * sum(1 for c, n in _counts(game, pid).items() if n == 1)


# ══ registration: Events and Landmarks ═══════════════════════════════════════

LANDSCAPE_FX.update({
    "Advance": _ev_advance,
    "Annex": _ev_annex,
    "Banquet": _ev_banquet,
    "Conquest": _ev_conquest,
    "Delve": _ev_delve,
    "Dominate": _ev_dominate,
    "Donate": _ev_donate,
    "Ritual": _ev_ritual,
    "Salt the Earth": _ev_salt_the_earth,
    "Tax": _ev_tax,
    "Triumph": _ev_triumph,
    "Wedding": _ev_wedding,
    "Windfall": _ev_windfall,
})

LANDSCAPE_SCORING.update({
    "Bandit Fort": _sc_bandit_fort,
    "Fountain": _sc_fountain,
    "Keep": _sc_keep,
    "Museum": _sc_museum,
    "Obelisk": _sc_obelisk,
    "Orchard": _sc_orchard,
    "Palace": _sc_palace,
    "Tower": _sc_tower,
    "Triumphal Arch": _sc_triumphal_arch,
    "Wall": _sc_wall,
    "Wolf Den": _sc_wolf_den,
})

LANDSCAPE_SETUP.update({
    "Aqueduct": _aqueduct_setup,
    "Defiled Shrine": _defiled_shrine_setup,
    "Obelisk": _obelisk_setup,
    "Tax": _tax_setup,
    "Arena": _self_store("Arena"),
    "Basilica": _self_store("Basilica"),
    "Baths": _self_store("Baths"),
    "Battlefield": _self_store("Battlefield"),
    "Colonnade": _self_store("Colonnade"),
    "Labyrinth": _self_store("Labyrinth"),
})

STAGES.update({
    ("Advance", "trash"): _ev_advance_trash,
    ("Advance", "gain"): _ev_advance_gain,
    ("Annex", "keep"): _ev_annex_keep,
    ("Annex", "duchy"): _ev_annex_duchy,
    ("Banquet", "gain"): _ev_banquet_gain,
    ("Donate", "trash"): _ev_donate_trash,
    ("Donate", "pick"): _ev_donate_pick,
    ("Donate", "reshuffle"): _ev_donate_reshuffle,
    ("Donate", "draw"): _ev_donate_draw,
    ("Ritual", "trash"): _ev_ritual_trash,
    ("Salt the Earth", "trash"): _ev_salt_the_earth_trash,
    ("Tax", "pile"): _ev_tax_pile,
    ("Tax", "take"): _tax_take,
    # landmarks
    ("Aqueduct", "treasure"): _aqueduct_treasure,
    ("Aqueduct", "victory"): _aqueduct_victory,
    ("Arena", "offer"): _arena,
    ("Arena", "discard"): _arena_discard,
    ("Basilica", "take"): _take_two("Basilica", "_basilica_take"),
    ("Baths", "take"): _take_two("Baths", "_baths_take"),
    ("Battlefield", "take"): _take_two("Battlefield", "_battlefield_take"),
    ("Colonnade", "take"): _take_two("Colonnade", "_colonnade_take"),
    ("Labyrinth", "take"): _take_two("Labyrinth", "_labyrinth_take"),
    ("Defiled Shrine", "action"): _defiled_shrine_action,
    ("Defiled Shrine", "curse"): _defiled_shrine_curse,
    ("Tomb", "vp"): _tomb,
    ("Mountain Pass", "gain"): _mountain_pass,
    ("Mountain Pass", "bid"): _mountain_pass_bid,
    ("Mountain Pass", "pick"): _mountain_pass_pick,
})

# `from:"landscape"` — a landmark on the trigger bus (ph. 7H). The ability goes
# to the event's ACTOR, because every one of these reads "when YOU gain/trash".
# `commutes` marks the ones that are decision-free AND order-independent, so
# the pool auto-runs them instead of making the player order their own VP. The
# two that are NOT marked are Aqueduct's and Defiled Shrine's pairs, where the
# compendium explicitly gives the player the choice.
TRIGGERS.update({
    "Aqueduct": [{"on": "gain", "from": "landscape", "stage": "treasure",
                  "when": _aqueduct_treasure_when},
                 {"on": "gain", "from": "landscape", "stage": "victory",
                  "when": _victory_gain_when}],
    "Arena": [{"on": "buy_phase_start", "from": "landscape", "stage": "offer",
               "when": _arena_when}],
    "Basilica": [{"on": "gain", "from": "landscape", "stage": "take",
                  "when": _basilica_when, "commutes": True}],
    "Baths": [{"on": "cleanup_start", "from": "landscape", "stage": "take",
               "when": _baths_when, "commutes": True}],
    "Battlefield": [{"on": "gain", "from": "landscape", "stage": "take",
                     "when": _victory_gain_when, "commutes": True}],
    "Colonnade": [{"on": "gain", "from": "landscape", "stage": "take",
                   "when": _colonnade_when, "commutes": True}],
    "Defiled Shrine": [{"on": "gain", "from": "landscape", "stage": "action",
                        "when": _defiled_shrine_action_when},
                       {"on": "gain", "from": "landscape", "stage": "curse",
                        "when": _defiled_shrine_curse_when}],
    "Labyrinth": [{"on": "gain", "from": "landscape", "stage": "take",
                   "when": _labyrinth_when, "commutes": True}],
    "Tomb": [{"on": "trash", "from": "landscape", "stage": "vp",
              "commutes": True}],
    "Mountain Pass": [{"on": "gain", "from": "landscape", "stage": "gain",
                       "when": _mountain_pass_when}],
    "Tax": [{"on": "gain", "from": "landscape", "stage": "take",
             "when": _tax_when, "commutes": True}],
})
