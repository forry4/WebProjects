"""A FAIR engine bot — builds and pilots a draw-your-deck engine using only
information a human legitimately has: its own HAND, its own DECK COMPOSITION
(the multiset of cards it owns — you always know your own deck list), and the
PUBLIC pile counts. It NEVER reads the order or contents of the face-down draw
pile (`seat["deck"]` as an ordered list) — that would be the bot cheating by
seeing its next draw, which is exactly the thing we refuse to do.

Why a separate module from the strategist: the measured strategist engine lost
0.20 vs Big Money+ even on ideal engine boards, and the diagnostic said why —
its deck never "went off" (max hand ~8, not 15+), it durdled to turn 25+, and
it over-bought pieces. That is a BUILD + PILOT problem, not a board-read one, so
this is a clean re-attempt at the two things that actually make an engine win:

  1. BUILD a deck that can draw itself — trash hard first, then buy draw and
     villages in ratio until the composition can chain, then payload + a Buy.
  2. GREEN explosively once it is online — multiple Provinces a turn on the +Buy,
     never the slow one-a-turn money clock.

Everything here is measured in `tools/bot_arena.py`; nothing ships until it
beats Big Money+ with the mirror reading exactly 0.5000.
"""

import collections

from . import bot_endgame, engine
from .bot_traits import quality, traits

# Rough "+cards" credit for a variable drawer that prints no number (Library,
# Minion, ...). It draws toward a hand size, so ~3 net cards is a fair estimate
# for capacity math — deliberately conservative so we don't over-count draw.
_DRAW_TO_X_CREDIT = 3

# Junk a thinning deck wants gone: starting Estates and Coppers, plus any Curse.
_JUNK = {"Estate", "Copper", "Curse"}

# SIFTERS that print "+N Cards" but discard them back (net ~0 card advantage) —
# they are selection, not draw, and counting them as draw is what let the engine
# think a Cellar/Warehouse pile could draw the deck. A REAL drawer grows the
# hand. This is REVIEWED knowledge (text can't tell "+3 Cards, discard 3" from
# "+3 Cards"): the subset of the trait `SIFTERS` that yields no card advantage.
_FAKE_DRAW = {"Cellar", "Warehouse", "Oasis", "Vault", "Tide Pools", "Harbinger",
              "Courtyard", "Crossroads", "Haven", "Cartographer", "Lookout",
              "Sentry", "Wishing Well", "Sea Chart", "Scheme", "Crystal Ball",
              "Native Village", "Secret Passage", "Patrol", "Stables"}


def real_drawer(name):
    """A card that grows the hand (true card advantage), not a sifter. Terminal
    draw (Smithy) and self-replacing draw (Laboratory), minus the discard-back
    sifters. This is the distinction the engine lives or dies on."""
    t = traits(name)
    if name in _FAKE_DRAW:
        return False
    return t["terminal_draw"] or (t["plus_cards"] >= 2 and t["plus_actions"] >= 1) \
        or (t["draw_to_x"] and name in ("Library", "Magnate", "Minion"))


def card_power(name):
    """A GENERAL card-strength prior, higher = stronger, used to break ties in
    piece selection (favor the stronger, usually pricier card).

    The backbone is the ThunderDominion 2022 within-expansion ranking
    (`bot_traits.quality`, 0..1) mapped to 40..100; cards the list doesn't cover
    fall back to a COST estimate on the same scale (cost is Dominion's own power
    signal), so ranked and unranked cards stay comparable across sets. Small
    engine-role bonuses tilt ties toward what an engine specifically needs (the
    ranking is general; a great money card can be a poor engine piece)."""
    t = traits(name)
    q = quality(name)
    if q is None:                             # Hinterlands-style fallback: cost proxy
        q = min(1.0, max(0.0, (t["cost"] - 2) / 5.0))
    p = 40.0 + 60.0 * q                       # 40..100 by general strength
    if real_drawer(name):
        p += 8                                # real draw is the scarcest piece
    if t["village"]:
        p += 6
    if t["plus_buy"]:
        p += 3
    if t["trasher"] == "mass":
        p += 4
    return p


def owned_counts(game, pid):
    """The multiset of cards pid owns, across every zone. FAIR: this is the
    player's own deck list, which a human always knows; it is NOT the hidden
    draw ORDER."""
    return collections.Counter(engine.owned_cards(game, pid))


def _sum(counts, key, pred=None):
    return sum(n * traits(c)[key] for c, n in counts.items()
               if pred is None or pred(c))


# ── board read: is an engine even worth attempting here? ─────────────────────

def engine_viable(game):
    """A STRICT gate — an engine needs all four legs or it is a durdle:
    real trashing (mass/multi), a village (net +Actions), a drawer, and a way to
    turn the draw into points (payload or +Buy). Boards missing any leg go to
    Big Money+, where they belong. Deliberately stricter than the old selector,
    which fired on 66% of boards (cantrips counted as trashing) and lost."""
    k = game["kingdom"]
    trash = any(traits(c)["trasher"] in ("mass", "multi") for c in k)
    village = any(traits(c)["village"] for c in k)
    draw = any(real_drawer(c) for c in k)     # a genuine drawer, not a sifter
    payload = any(traits(c)["plus_coins"] >= 2 or traits(c)["plus_buy"]
                  or (traits(c)["treasure"] and traits(c)["coins"] >= 2)
                  for c in k)
    return trash and village and draw and payload


def _best(names, key, default=None):
    names = [n for n in names if n is not None]
    return max(names, key=key) if names else default


def board_pieces(game):
    """Pick the one best card for each engine role on this board (by trait
    quality, cheapest on ties). Pure function of the kingdom."""
    k = game["kingdom"]
    trashers = [c for c in k if traits(c)["trasher"] in ("mass", "multi")]
    villages = [c for c in k if traits(c)["village"]]
    # a REAL drawer if the board has one, else fall back to any nominal draw
    real = [c for c in k if real_drawer(c)]
    drawers = real or [c for c in k if traits(c)["draw"] or traits(c)["draw_to_x"]]
    buys = [c for c in k if traits(c)["plus_buy"]]
    payloads = [c for c in k if traits(c)["plus_coins"] >= 2]
    # Ties break toward the STRONGER (usually pricier) card via card_power — the
    # opposite of the old "-cost" that reached for the cheapest piece.
    return {
        "trasher": _best(trashers, lambda c: (traits(c)["trasher"] == "mass",
                                              card_power(c))),
        "village": _best(villages, lambda c: (traits(c)["plus_actions"],
                                             card_power(c))),
        "drawer": _best(drawers, card_power),
        "buy": _best(buys, card_power),
        "payload": _best(payloads, lambda c: (traits(c)["plus_coins"], card_power(c))),
    }


# ── deck read: is the engine we've built actually online? ────────────────────

def deck_metrics(game, pid):
    """FAIR composition metrics. `draw_capacity` = how many cards this deck can
    expect to draw in a turn (5 opener + every drawer's +cards); `net_actions`
    = whether the terminals can all be played (>=0 means the villages cover
    them). All from the owned multiset — never the draw order."""
    counts = owned_counts(game, pid)
    size = sum(counts.values())
    actions = {c: n for c, n in counts.items() if traits(c)["action"]}
    n_actions = sum(actions.values())
    terminals = sum(n for c, n in actions.items() if traits(c)["terminal"])
    # net actions after playing every action: start with 1, each action spends
    # one and gives back its +Actions.
    net_actions = 1 + sum(n * traits(c)["plus_actions"] for c, n in actions.items()) - n_actions
    # Only REAL drawers add to capacity — a sifter's "+3 Cards, discard 3" nets
    # zero, so counting it is what made the deck think it could draw itself.
    draw_capacity = 5 + sum(
        n * (traits(c)["plus_cards"] + (_DRAW_TO_X_CREDIT if traits(c)["draw_to_x"] else 0))
        for c, n in actions.items() if real_drawer(c))
    payload = _sum(counts, "plus_coins", lambda c: traits(c)["action"]) \
        + sum(n * traits(c)["coins"] for c, n in counts.items() if traits(c)["treasure"])
    junk = sum(n for c, n in counts.items() if c in _JUNK)
    # REAL card advantage: a card that nets more than it replaces (terminal draw
    # like Smithy, a self-replacing drawer). Villages, +1-Card cantrips, and
    # sifters do NOT grow the hand, so a deck of only those can never draw
    # itself no matter how many you own — the durdle trap.
    real_draw = sum(n for c, n in actions.items() if real_drawer(c))
    plus_buys = sum(n * traits(c)["plus_buys"] for c, n in actions.items())
    return {
        "size": size, "terminals": terminals, "net_actions": net_actions,
        "draw_capacity": draw_capacity, "payload": payload, "junk": junk,
        "real_draw": real_draw, "plus_buys": plus_buys,
        "villages": sum(n for c, n in actions.items() if traits(c)["village"]),
        "drawers": sum(n for c, n in actions.items()
                       if traits(c)["draw"] or traits(c)["draw_to_x"]),
    }


# A payoff turn must beat Big Money's ~1 Province/turn to be worth the build —
# so the target is TWO Provinces: ~$16 of payload and a +Buy. An engine that
# draws its deck but only makes $8 just ties money, ten turns later.
_ONLINE_PAYLOAD = 15


def is_online(game, pid):
    """Can this deck draw itself AND out-buy Big Money on a payoff turn? Requires
    real card advantage, enough to draw ~the whole deck, non-negative actions,
    a +Buy, and ~$16 of payload (two Provinces) — not just $8 (which only ties
    money, having spent ten turns building)."""
    m = deck_metrics(game, pid)
    return (m["real_draw"] >= 1 and m["draw_capacity"] >= m["size"] - 2
            and m["net_actions"] >= 0 and m["payload"] >= _ONLINE_PAYLOAD
            and m["plus_buys"] >= 1)


def _colony_green(game):
    """Colony is the engine's green in a colony game; Platinum is economy (bought
    while building, in _economy below)."""
    if game.get("colony") and game["coins"] >= 11 \
            and game["supply"].get("Colony", 0) > 0:
        return "Colony"
    return None


# Build caps — bound every piece so the build ALWAYS terminates. A deck that
# blows past _ABANDON_SIZE without coming online is a durdle: stop building and
# play it out as money (return None -> the caller's Big Money+ ladder).
_MAX_DRAWERS = 5
_MAX_PAYLOAD = 3
_MAX_VILLAGE_OVER = 1       # villages up to terminals + this
_ABANDON_SIZE = 26


def engine_buy(game, pid):
    """The card to buy this turn, or None to defer to the money ladder. Order:
    green once online, then trash, +Buy, draw, villages, payload, economy —
    every piece capped, and the whole thing abandoned to money if it bloats
    without coming online."""
    counts = owned_counts(game, pid)
    coins = game["coins"]
    sup = game["supply"]
    m = deck_metrics(game, pid)
    pieces = board_pieces(game)
    online = is_online(game, pid)

    def own(card):
        return counts.get(card, 0)

    def can(card):
        return (card and sup.get(card, 0) > 0
                and engine.cost(game, card) <= coins
                and engine.buy_gate(game, pid, card) is None)

    # 1. GREEN once the engine is online. The scheduler re-enters `choose`, so a
    #    +Buy turn with $16 buys two Provinces across two calls. Once online we
    #    STOP buying pieces — a green card added now is drawn every turn.
    if online:
        col = _colony_green(game)
        if col:
            return col
        if coins >= 8 and sup.get("Province", 0) > 0:
            return "Province"
        # short of $8 this turn: fall to economy below, never green under the line.
        if game.get("colony") and 9 <= coins <= 10 \
                and sup.get("Platinum", 0) > 0 and can("Platinum"):
            return "Platinum"
        return "Gold" if can("Gold") else None

    # ANTI-DURDLE: bloated and still not online -> the engine failed to come
    # together on this board; hand the rest of the game to the money ladder
    # rather than buying a 12th cantrip.
    if m["size"] >= _ABANDON_SIZE:
        return None

    # 2. TRASH early, while there is junk to remove — the #1 engine enabler.
    tr = pieces["trasher"]
    if tr and m["junk"] > 2 and can(tr) \
            and own(tr) < (1 if traits(tr)["trasher"] == "mass" else 2):
        return tr

    # 3. Exactly one +Buy — "the most overlooked ingredient".
    bu = pieces["buy"]
    if bu and own(bu) < 1 and can(bu):
        return bu

    dr = pieces["drawer"]
    vi = pieces["village"]
    pl = pieces["payload"]
    draws_itself = m["real_draw"] >= 1 and m["draw_capacity"] >= m["size"] - 2

    # 4. Build DRAW until the deck can draw itself (capped), keeping villages
    #    ahead of terminal drawers so the terminals actually connect.
    if not draws_itself and dr and own(dr) < _MAX_DRAWERS \
            and m["draw_capacity"] < m["size"] and can(dr):
        if traits(dr)["terminal"] and vi and m["villages"] <= m["terminals"] \
                and can(vi) and own(vi) < m["terminals"] + _MAX_VILLAGE_OVER:
            return vi
        return dr

    # 5. Villages to cover the terminals we already hold (capped).
    if vi and m["net_actions"] < 1 and can(vi) \
            and own(vi) < m["terminals"] + _MAX_VILLAGE_OVER:
        return vi

    # 6. Once the deck DRAWS itself, the binding constraint is PAYLOAD — an
    #    engine that draws but makes only $8 just ties money. Build toward the
    #    two-Province threshold: +coin payload cards first, then Gold. And make
    #    sure we actually own a +Buy (is_online requires one).
    if draws_itself:
        if pl and own(pl) < _MAX_PAYLOAD and can(pl):
            return pl
        if m["plus_buys"] < 1:
            bu2 = pieces["buy"]
            if bu2 and can(bu2):
                return bu2
        if m["payload"] < _ONLINE_PAYLOAD:
            if game.get("colony") and 9 <= coins <= 10 \
                    and sup.get("Platinum", 0) > 0 and can("Platinum"):
                return "Platinum"
            if can("Gold"):
                return "Gold"

    # 7. ECONOMY while still building: Platinum in a colony game, else Gold.
    if game.get("colony") and 9 <= coins <= 10 \
            and sup.get("Platinum", 0) > 0 and can("Platinum"):
        return "Platinum"
    if can("Gold"):
        return "Gold"

    return None      # nothing to build — the caller drops to the money ladder


# ── piloting the turn (fair — greedy over the HAND, no draw-order peeking) ────

def _play_key(card):
    """Play order: +Action cards first (villages/cantrips never strand a
    terminal), then draw (drawing finds more to play), then payload terminals.
    A pure function of the card, so it peeks at nothing."""
    t = traits(card)
    return (
        0 if t["plus_actions"] >= 1 else 1,   # keep the action chain alive first
        -t["plus_cards"],                     # then the most draw
        -t["plus_coins"],                     # then payload
        t["cost"],
    )


def engine_action(game, pid, moves):
    """The best Action to play now, or None if there is nothing to play. Greedy
    and re-entrant: the scheduler calls again after each play."""
    plays = [m for m in moves if m["type"] == "play_action"]
    if not plays:
        return None
    plays.sort(key=lambda m: _play_key(m["card"]))
    return plays[0]
