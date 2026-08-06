"""Heuristic answers to decision frames — shared by every tier above `random`.

Both shipped bots answer EVERY prompt with `engine.sample_decision` (uniform
over valid payloads), which is why Big Money discards its Gold to a Militia
half the time and takes a Curse from a Torturer as often as not. This module
replaces that with policy, and it is the cheapest strength gain in the ladder:
no search, no state, O(hand).

**Contract: `decide` must return a VALID payload for any frame.** Every branch
falls through to `engine.sample_decision`, and the answers built here are
re-validated (`_clamp`) before they are returned, so a policy bug degrades to a
legal-but-silly move rather than a rejected one — the scheduler's guaranteed
turn-finisher depends on it.

Two value scales, deliberately separate (conflating them is the classic bug —
a Province is the best card you can own and the most useless one in hand):

* `hand_value`  — worth of holding this card for the COMING turn. Green is 0.
* `deck_value`  — worth of OWNING it at all. This is what trashing reads, and
  it flips for green cards once the game starts ending.
"""

import re as _re

from . import cards, engine
from .bot_traits import traits
from .cards import CARDS

# ── value scales ─────────────────────────────────────────────────────────────

_ACTION_HAND_VALUE = 12.0       # a plain Action we can play this turn


def hand_value(game, pid, card):
    """Worth of holding `card` for the coming turn. Victory/Curse are DEAD."""
    tr = traits(card)
    if tr["treasure"]:
        return 10.0 * engine.coins_of(game, card) + 1.0
    if tr["action"]:
        if tr["terminal_draw"]:
            return 25.0
        if tr["village"]:
            return 18.0
        if tr["cantrip"]:
            return 16.0
        if tr["plus_coins"] >= 2:
            return 10.0 + 5.0 * tr["plus_coins"]
        return _ACTION_HAND_VALUE
    return 0.0                  # victory, curse — nothing to do with them now


def _ending(game):
    """Is the game close enough to over that green stops being junk?

    The Colony clause MUST be guarded on the pile existing: `.get("Colony", 0)
    <= 3` reads True in every non-Prosperity game, which flips Estates from
    junk to treasure on turn one — the bot then refuses to Chapel them and
    happily Workshops more.
    """
    sup = game["supply"]
    if sup.get("Province", 0) <= 4:
        return True
    if "Colony" in sup and sup["Colony"] <= 3:
        return True
    return engine.count_empty_piles(game) >= 2


def deck_value(game, pid, card):
    """Worth of OWNING `card`. Lower = trash it sooner.

    Green flips: an Estate is a dead card while you are building and a point
    once the game is ending, so trashing reads the clock (the Level-10 rule
    "trash early — the value of trashing decays", and its endgame corollary).
    """
    tr = traits(card)
    if tr["curse"]:
        return -30.0            # always the first thing to go
    if tr["victory"] and not tr["action"] and not tr["treasure"]:
        vp = tr["cost"]         # proxy: Estate 2, Duchy 5, Province 8
        return 20.0 + vp if _ending(game) else -5.0 + vp * 0.5
    if tr["treasure"]:
        coins = engine.coins_of(game, card)
        return -2.0 if coins <= 1 else 10.0 * coins
    if tr["action"]:
        if tr["terminal_draw"]:
            return 25.0
        if tr["cantrip"]:
            return 22.0
        if tr["village"]:
            return 18.0
        if tr["plus_coins"] >= 2:
            return 20.0
        return 15.0
    return 0.0


def gain_value(game, pid, card):
    """How much we want to GAIN `card` (Workshop/Remodel/Ironworks targets)."""
    tr = traits(card)
    if tr["curse"]:
        return -30.0
    if tr["victory"] and not tr["action"] and not tr["treasure"]:
        # Green is only worth gaining once the game is ending; before that it
        # is the thing that makes your deck worse.
        return (30.0 + tr["cost"]) if _ending(game) else -3.0
    return 10.0 + tr["cost"] * 2.0 + tr["bm_terminal_rank"] * 0.05


def _junk(game, pid, card):
    """Would we happily see the back of this card?"""
    return deck_value(game, pid, card) < 5.0


# ── selection helpers ────────────────────────────────────────────────────────

_TERMINAL_COLLISION = 20.0      # what a second unplayable terminal is worth


def _keep_best(game, pid, hand, k):
    """The k cards to KEEP from `hand` (a multiset), greedily by hand_value.

    The collision discount is the point: a second terminal in a 3-card Militia
    hand is a dead card, and a per-card ranking without it happily keeps two
    Smithies over a Gold.
    """
    pool = list(hand)
    out = []
    while len(out) < k and pool:
        blocked = any(traits(x)["terminal"] for x in out)

        def score(c):
            v = hand_value(game, pid, c)
            if blocked and traits(c)["terminal"]:
                v -= _TERMINAL_COLLISION
            return v

        best = max(pool, key=score)
        pool.remove(best)
        out.append(best)
    return out


def _worst(game, pid, cards, n, key=None):
    """The n worst cards of `cards` (a multiset) by `key` (default deck_value)."""
    key = key or (lambda c: deck_value(game, pid, c))
    return sorted(cards, key=key)[:n]


def _clamp(frame, cards):
    """Force `cards` to be a valid answer: a sub-multiset of the frame's pool
    with a count inside [min, max]. The last line of defence — a policy that
    returns something impossible degrades to legal, never to rejected."""
    c = frame["constraint"]
    pool = list(c["cards"])
    out = []
    for card in cards:
        if card in pool:
            pool.remove(card)
            out.append(card)
    out = out[:c["max"]]
    while len(out) < c["min"] and pool:
        out.append(pool.pop(0))
    return {"cards": out}


# ── per-card option policy ───────────────────────────────────────────────────
#
# Every entry answers ONE choose_option frame. A card missing from here falls
# through to the first option, which is the historical default ordering (the
# ability pool documents that the first option is always the pre-pool
# behaviour) — never to a random pick.

def _opt_ids(frame):
    return [o["id"] for o in frame["constraint"]["options"]]


def _pick(frame, *preferred):
    """First preferred id that this frame actually offers, else the first."""
    ids = _opt_ids(frame)
    for want in preferred:
        if want in ids:
            return {"ids": [want]}
    return {"ids": ids[:frame["constraint"]["pick"]]}


# Ways whose whole text is printed bonuses, so their value is fully readable
# off the card. Everything else (Butterfly's return-and-upgrade, Goat's trash,
# Mouse's borrowed card, Rat, Seal, Turtle, Squirrel, Camel, Worm, Chameleon,
# Frog, Owl, Mole) is deliberately absent: we take it never rather than model
# it badly, because DECLINING is always a legal, sane answer and playing the
# printed card is what the buy ladder was built around.
_VANILLA_LINE = _re.compile(r"^\+\d+ (Card|Action|Buy)s?$|^\+\$\d+$")


def _readable_bonus(text):
    """(cards, actions, buys, coins) if `text` is NOTHING BUT printed bonuses,
    else None. The None is the whole point: a card or Way whose value lives in
    prose is one this policy refuses to price."""
    cards_ = actions = buys = coins = 0
    for line in (l.strip() for l in text.split("\n")):
        if not line:
            continue
        if not _VANILLA_LINE.match(line):
            return None
        if line.startswith("+$"):
            coins += int(line[2:])
        else:
            n, word = int(line[1:].split()[0]), line.split()[1].rstrip("s")
            if word == "Card":
                cards_ += n
            elif word == "Action":
                actions += n
            else:
                buys += n
    return (cards_, actions, buys, coins)


def _way_choice(game, pid, frame):
    """"normally" or "as the Way?" — and the DEFAULT IS NORMALLY.

    This is a floor, not a strategy. A Way replaces the played card's whole
    ability, so taking one is a deviation from the plan the bot bought its deck
    for; the only case we take is the one that can be priced with certainty —
    a VANILLA card against a VANILLA Way, where both sides are nothing but
    printed bonuses and the comparison is arithmetic rather than judgement.
    A Chapel, a Militia or a Remodel is therefore never Way'd, whatever the
    Way offers, because its value is not on the +lines.

    Weights are the usual BM-ish read (a card is worth a bit more than a coin,
    an Action only matters when you have none left, a Buy is worth little to a
    deck that buys once a turn). NOT MEASURED — `tools/bot_arena.py` is where a
    real Way policy would be gated, and this exists so the bot is never WORSE
    than a Menagerie-blind one in the meantime."""
    played = (frame.get("data") or {}).get("card")
    way = frame["card"]
    if not played:
        return "normal"
    card_text = CARDS.get(played, {}).get("text", "")
    way_text = cards.LANDSCAPES.get(way, {}).get("text", "")
    mine, theirs = _readable_bonus(card_text), _readable_bonus(way_text)
    if mine is None or theirs is None:
        return "normal"

    def score(b):
        c, a, bu, co = b
        # +Actions are worth nothing once we already have some to spare, which
        # is what makes a Village-vs-Way-of-the-Sheep comparison honest.
        return 1.4 * c + co + 0.3 * bu + (0.7 * a if game["actions"] <= 1 else 0.1 * a)
    return "way" if score(theirs) > score(mine) else "normal"


def _choose_option(game, pid, frame, rng):
    card = frame["card"]
    hand = list(game["seats"][pid]["hand"])
    ids = _opt_ids(frame)
    pick = frame["constraint"]["pick"]

    # The attack reaction window: react whenever we can. Immunity or a free
    # play is strictly better than declining for every reaction we ship.
    if card == "__attack":
        for i in ids:
            if i.startswith("react:"):
                return {"ids": [i]}
        return _pick(frame, "decline")

    # A parked ability pool: the first option is the historical default, and
    # ordering rarely changes the outcome — take it deterministically.
    if card == "__abilities":
        return {"ids": ids[:pick]}

    # THE WAY OFFER (ph. 10). Once a Way is dealt, EVERY Action play stops to
    # ask "normally, or as the Way?" — so a bot that falls through to
    # `sample_decision` plays about half its Actions as whatever Way the board
    # happens to have. That is the ph.-8 Debt shape exactly: no error, no
    # stall, just a bot quietly throwing away the card its whole buy ladder
    # was built around. The floor matters more than the ceiling here.
    if frame["stage"] == "__way_offer":
        return _pick(frame, _way_choice(game, pid, frame), "normal")

    # "You may play/reveal this" reactions — always yes: each is free value
    # (Trail/Weaver replay, Tunnel's Gold, Pirate's Treasure, Clerk's +$2,
    # Sailor's Duration, Fool's Gold's Gold-onto-deck).
    if "decline" in ids and len(ids) == 2:
        other = [i for i in ids if i != "decline"][0]
        if card == "Fool's Gold":
            # trading a $1-$4 Treasure for a Gold on deck: right once the
            # Provinces are actually going, wrong while it is still paying $4s
            return _pick(frame, other if _ending(game) else "decline")
        return {"ids": [other]}

    if card == "Vassal":
        return _pick(frame, "play")             # a free Action off the deck
    if card == "Library":
        # skip a terminal we could never play; keep villages and cantrips
        skip = traits(frame["data"].get("card", "")) if frame.get("data") else None
        if skip and skip["terminal"] and game["actions"] <= 0:
            return _pick(frame, "aside")
        return _pick(frame, "hand", "aside")
    if card == "Steward":
        junk = [c for c in hand if _junk(game, pid, c)]
        if len(junk) >= 2:
            return _pick(frame, "trash")
        return _pick(frame, "coins", "cards")
    if card == "Baron":
        return _pick(frame, "discard" if "Estate" in hand else "gain")
    if card == "Mill":
        junk = [c for c in hand if hand_value(game, pid, c) <= 0.0]
        return _pick(frame, "discard" if len(junk) >= 2 else "keep")
    if card == "Mining Village":
        # cash it in only when the $2 actually buys a better rung
        reach = game["coins"] + 2
        return _pick(frame, "trash" if game["coins"] < 8 <= reach else "keep")
    if card == "Nobles":
        others = [c for c in hand if traits(c)["action"] and c != "Nobles"]
        return _pick(frame, "actions" if others and game["actions"] <= 0 else "cards")
    if card == "Lurker":
        return _pick(frame, "gain" if any(traits(c)["action"] for c in game["trash"])
                     else "trash")
    if card == "Minion":
        # discard-and-redraw when the hand left behind is weak; the attack is
        # a bonus either way
        rest = sum(hand_value(game, pid, c) for c in hand)
        return _pick(frame, "discard" if rest < 40.0 else "coins")
    if card == "Torturer":
        # the victim's choice. The Level-10 rule: two discards cost less than
        # a Curse (worth ~4-5 future draws), unless we can trash it cheaply.
        return _pick(frame, "discard")
    if card == "Vault":
        junk = [c for c in hand if hand_value(game, pid, c) <= 0.0]
        return _pick(frame, "discard" if len(junk) >= 2 else "decline")
    if card == "Spice Merchant":
        return _pick(frame, "cards", "coins")
    if card == "Develop":
        return _pick(frame, "lo_first", "hi_first")
    if card == "Weaver":
        return _pick(frame, "silvers", "card")
    if card == "Jack of All Trades":
        top = (frame.get("data") or {}).get("card")
        keep = top is not None and not _junk(game, pid, top)
        return _pick(frame, "keep" if keep else "discard")
    if card == "Investment":
        return _pick(frame, "coin", "vp")
    if card == "Native Village":
        mat = len(game["seats"][pid]["village_mat"])
        return _pick(frame, "take" if mat >= 2 else "mat")
    if card == "Tiara":
        got = (frame.get("data") or {}).get("card")
        good = got is not None and gain_value(game, pid, got) > 0
        return _pick(frame, "topdeck" if good else "keep")
    if card == "Watchtower":
        got = (frame.get("data") or {}).get("card")
        if got is None:
            return _pick(frame, "keep")
        if "trash" in ids or "topdeck" in ids:      # the act frame
            if _junk(game, pid, got):
                return _pick(frame, "trash", "keep")
            return _pick(frame, "topdeck", "keep")
        return _pick(frame, "play")                 # the react window

    return {"ids": ids[:pick]}


# ── per-purpose card policy ──────────────────────────────────────────────────

# Trashing here is a CONVERSION, not thinning: the card is exchanged for
# something better, so the pick reads "what upgrades best", not "what is worst".
_TRASH_TO_GAIN = {"Remodel", "Upgrade", "Expand", "Replace", "Develop", "Mine",
                  "Salvager", "Bishop", "Trader", "Investment", "Farmland",
                  "Forge", "Moneylender", "Spice Merchant", "Souk"}
# How much more the gained card may cost (used for the Gold->Province check).
_UPGRADE_REACH = {"Remodel": 2, "Replace": 2, "Expand": 3, "Farmland": 2,
                  "Mine": 3, "Upgrade": 1}

# Topdecking is usually "get rid of a dead card", but for these the card is
# going on top BECAUSE we want to draw it next turn.
_TOPDECK_BEST = {"Harbinger", "Artisan", "Treasury", "Sea Chart"}


def _choose_cards(game, pid, frame, rng):
    c = frame["constraint"]
    card = frame["card"]
    purpose = c.get("purpose")
    pool = list(c["cards"])
    lo, hi = c["min"], c["max"]

    if purpose == "trash":
        if card in _TRASH_TO_GAIN:
            return _clamp(frame, _trash_to_gain(game, pid, card, pool, lo, hi))
        # pure thinning: junk only, never more than the frame demands
        junk = sorted([x for x in pool if _junk(game, pid, x)],
                      key=lambda x: deck_value(game, pid, x))
        junk = _protect_economy(game, pid, junk)
        if len(junk) >= lo:
            return _clamp(frame, junk[:hi])
        # A MANDATORY trash with no junk to give (Apprentice, Transmute). The
        # fallback used to hand over the cheapest card in hand, which on a
        # money deck means Coppers, then Silvers, then everything: MEASURED,
        # two bmplus bots ground each other down to a single Apprentice apiece
        # and then played 9908 turns without either being able to buy anything
        # — a game that literally cannot end. Protect the economy here too.
        return _clamp(frame, _worst(game, pid,
                                    _protect_economy(game, pid, pool, hard=True)
                                    or pool, lo))

    if purpose == "discard":
        # Witch's Hut curses the table only if BOTH discards are Actions —
        # that is the card, not a tie-break.
        if card == "Witch's Hut":
            actions = [x for x in pool if traits(x)["action"]]
            if len(actions) >= hi:
                return _clamp(frame, sorted(
                    actions, key=lambda x: hand_value(game, pid, x))[:hi])
        n = _discard_count(game, pid, frame, pool, lo, hi)
        keep = _keep_best(game, pid, pool, len(pool) - n)
        rest = list(pool)
        for k in keep:
            rest.remove(k)
        return _clamp(frame, rest)

    if purpose == "topdeck":
        best = card in _TOPDECK_BEST
        key = (lambda x: -hand_value(game, pid, x)) if best \
            else (lambda x: hand_value(game, pid, x))
        n = hi if best else lo
        return _clamp(frame, sorted(pool, key=key)[:max(n, lo)])

    if purpose == "pass":                       # Masquerade: give the worst
        return _clamp(frame, _worst(game, pid, pool, max(lo, 1)))

    if purpose == "reveal":
        if card == "Courtier":                  # paid per TYPE — reveal the
            return _clamp(frame, sorted(        # card with the most types
                pool, key=lambda x: -len(traits(x)["types"]))[:max(lo, 1)])
        return _clamp(frame, sorted(            # Mint: copy the best Treasure
            pool, key=lambda x: -deck_value(game, pid, x))[:max(lo, 1)])

    if purpose == "gain":
        return _clamp(frame, sorted(
            pool, key=lambda x: -gain_value(game, pid, x))[:max(lo, 1)])

    return _clamp(frame, _worst(game, pid, pool, lo))


def _protect_economy(game, pid, junk, hard=False):
    """Drop Treasures out of a trash list while the deck still needs them.

    The Level-10 rule with its brake on: thinning is the strongest early play,
    but a deck trashed below its money can no longer reach $8, and "The
    Trasher" is a named losing archetype. Coppers stay until there are real
    Treasures behind them.

    `hard=True` is for a MANDATORY trash, where the choice is only ever which
    card to give up: it protects EVERY Treasure while the deck is still thin,
    not just the Coppers. Without it a repeatable mandatory trasher eats the
    whole deck one card at a time, and the game stops being able to end.
    """
    owned = engine.owned_cards(game, pid)
    money = [c for c in owned if traits(c)["treasure"]]
    real_money = sum(1 for c in money if engine.coins_of(game, c) >= 2)
    if hard:
        # keep enough Treasure to still reach a Province-ish hand
        if sum(engine.coins_of(game, c) for c in money) > 12:
            return junk
        return [c for c in junk if not traits(c)["treasure"]]
    if real_money >= 3:
        return junk
    return [c for c in junk if not (traits(c)["treasure"]
                                    and engine.coins_of(game, c) <= 1)]


def _trash_to_gain(game, pid, card, pool, lo, hi):
    """Which card to feed a Remodel-class trasher.

    Junk-into-anything is the free play and the default. The exception worth
    coding is the endgame one: a Gold in hand is a Province when the reach
    covers it (Remodel/Expand/Replace/Farmland), which is how these cards
    actually close games.
    """
    reach = _UPGRADE_REACH.get(card)
    if reach is not None and _ending(game):
        target = game["supply"].get("Colony", 0) and "Colony" or "Province"
        want = engine.cost(game, target) if target in game["supply"] else 99
        best = [x for x in pool
                if game["supply"].get(target, 0) > 0
                and engine.cost(game, x) + reach >= want
                and not traits(x)["victory"]]
        if best:
            return sorted(best, key=lambda x: engine.cost(game, x))[:max(lo, 1)]
    junk = sorted([x for x in pool if _junk(game, pid, x)],
                  key=lambda x: deck_value(game, pid, x))
    junk = _protect_economy(game, pid, junk)
    n = max(lo, 1) if junk else lo
    return (junk or _worst(game, pid, pool, max(lo, 1)))[:max(n, lo)]


def _discard_count(game, pid, frame, pool, lo, hi):
    """How many to discard when the frame lets us choose (Cellar, Vault...).

    Discard every dead card and no live one — that IS the Cellar/Vault play.
    Forced discards (min == max) are unaffected.
    """
    if lo == hi:
        return lo
    dead = sum(1 for c in pool if hand_value(game, pid, c) <= 0.0)
    return max(lo, min(hi, dead))


# ── entry point ──────────────────────────────────────────────────────────────

def decide(game, pid, rng):
    """A payload for the top pending frame — the `sample_decision` replacement.

    Returns the same shape (`{"cards": ...}` / `{"ids": ...}` / ...), so callers
    wrap it as `{"type": "decision", **decide(...)}` exactly as before.
    """
    frame = game["pending"][-1]
    kind = frame["kind"]
    try:
        if kind == "choose_cards":
            return _choose_cards(game, pid, frame, rng)
        if kind == "choose_option":
            return _choose_option(game, pid, frame, rng)
        if kind == "order_cards":
            # order[0] ends up on top of the deck = drawn first
            cards = list(frame["constraint"]["cards"])
            return {"order": sorted(cards, key=lambda c: -hand_value(game, pid, c))}
        if kind == "place_in_deck":
            c = frame["constraint"]
            good = hand_value(game, pid, c["card"]) > 0.0
            return {"position": 0 if good else c["deck_len"]}
        if kind == "name_card":
            return {"card": _name_card(game, pid, frame)}
        if kind == "choose_pile":
            piles = list(frame["constraint"]["piles"])
            return {"pile": max(piles, key=lambda p: gain_value(game, pid, p))}
    except Exception:                       # noqa: BLE001 - policy must never
        pass                                # break the turn-finisher contract
    return engine.sample_decision(game, pid, rng)


def _name_card(game, pid, frame):
    """Naming: to HIT (Wishing Well — guess our own deck) or to DENY (War Chest
    — the player to our left names what we may not gain)."""
    pool = list(frame["constraint"]["cards"])
    if frame["card"] == "War Chest":
        # naming for someone ELSE's War Chest: DENY the best thing they could
        # actually gain with it — a card costing <= $5, in supply, not already
        # named this turn. Naming a Platinum they can't take (it costs $9) is a
        # wasted name; restrict to what the owner could really gain.
        owner = frame["data"].get("owner", pid)
        named = game["turn_ctx"].get("war_chest_names", [])
        gainable = [c for c in pool if game["supply"].get(c, 0) > 0
                    and engine.cost_le(game, c, 5) and c not in named]
        pick_from = gainable or pool
        return max(pick_from, key=lambda c: gain_value(game, owner, c))
    seat = game["seats"][pid]
    unseen = list(seat["deck"])
    if not unseen:
        unseen = list(seat["discard"])
    counts = {}
    for c in unseen:
        if c in pool:
            counts[c] = counts.get(c, 0) + 1
    if counts:
        return max(counts, key=lambda c: counts[c])
    return max(pool, key=lambda c: gain_value(game, pid, c))
