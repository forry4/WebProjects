"""The board read — which deck this kingdom wants, decided once per game.

This is the skill the level-30-to-45 threads keep circling: "identify the
strongest strategy for THIS board, then execute it". `bmplus` reads the board
for exactly one card (its terminal); the strategist reads it for a PLAN — an
archetype plus a priority menu of what to buy and how many.

The archetype selector is the Deck Archetypes taxonomy as an ordered rule
list, deliberately in the order the thread ranks them: a strategy that
auto-picks itself (Minion) first, then the engine check, then rushes, then
cursing money, then Big Money as the fallback that always works. Big Money is
the FALLBACK on purpose: the taxonomy's own advice is "default to BM+terminal,
upgrade to an engine only when villages + draw + trashing coexist", and the
named losing archetypes ("Durdle", "The Trasher") are all failed engines.

A plan is a pure function of (kingdom, colony, player count), so it is cached
and survives a reload — the bot stays stateless, which the room scheduler
requires (it re-enters `choose` per move).
"""

import functools

from .bot_traits import traits

# A menu entry: buy `card` while we own fewer than `count`, but only once the
# `after` prerequisites are satisfied (by count). Menus are read top-down.
#
# `count` is a CAP, not a target — the buy step takes the first entry it can
# afford whose cap is not reached, so ordering expresses priority.


def entry(card, count, after=None):
    return {"card": card, "count": count, "after": after or {}}


class Plan:
    """An archetype plus the menu that builds it."""

    def __init__(self, archetype, menu, green_at=None, notes=""):
        self.archetype = archetype
        self.menu = menu
        # Deck size at which this archetype starts buying points. Engines green
        # LATE (they want to draw themselves first); money decks green early.
        self.green_at = green_at or {}
        self.notes = notes

    def __repr__(self):                       # pragma: no cover - debugging
        return f"<Plan {self.archetype}: {[e['card'] for e in self.menu]}>"


# ── board features ───────────────────────────────────────────────────────────

def features(kingdom):
    """What the kingdom offers, as counts of each role."""
    f = {"villages": [], "draw": [], "trashers": [], "cursers": [],
         "payload": [], "buys": [], "gainers": [], "pile_gainers": [],
         "cantrips": [], "alt_vp": [], "attacks": [], "terminal_draw": []}
    for name in kingdom:
        t = traits(name)
        if t["village"]:
            f["villages"].append(name)
        if t["draw"] or t["draw_to_x"]:
            f["draw"].append(name)
        if t["terminal_draw"]:
            f["terminal_draw"].append(name)
        if t["trasher"] in ("mass", "multi"):
            f["trashers"].append(name)
        if t["curser"]:
            f["cursers"].append(name)
        if t["plus_coins"] >= 2 or (t["treasure"] and t["coins"] >= 2):
            f["payload"].append(name)
        if t["plus_buy"]:
            f["buys"].append(name)
        if t["gainer"]:
            f["gainers"].append(name)
        if t["pile_gainer"]:
            f["pile_gainers"].append(name)
        if t["cantrip"]:
            f["cantrips"].append(name)
        if t["alt_vp"]:
            f["alt_vp"].append(name)
        if t["attack_kind"]:
            f["attacks"].append(name)
    return f


def _best(names, key):
    return max(names, key=key) if names else None


def _rank(name):
    return traits(name)["bm_terminal_rank"]


def _cost(name):
    return traits(name)["cost"]


# ── the archetype selector ───────────────────────────────────────────────────

@functools.lru_cache(maxsize=2048)
def candidates(kingdom, colony=False, players=2):
    """EVERY plan this board can support, best-guess order.

    The champion tier plays these off against each other by self-play and
    keeps the winner, so a plan being wrong on a given board costs nothing —
    it simply loses its trials. That is the whole reason the selector below
    can afford to be a crude ordered rule list: it is a default, not a verdict.
    """
    k = list(kingdom)
    f = features(k)
    out = [_money_plan(f, colony)]
    second = _second_money_plan(f, colony)
    if second is not None:
        out.append(second)
    if f["cursers"]:
        out.append(_cursing_money_plan(f, colony))
    if f["villages"] and f["draw"] and (f["trashers"] or f["cantrips"]) \
            and (f["payload"] or f["buys"]):
        out.append(_engine_plan(f, colony))
    rush = _rush_target(f, k, players)
    if rush is not None:
        out.append(_rush_plan(f, rush, colony))
    if "Minion" in k:
        out.append(_minion_plan(f, colony))
    # de-duplicate by archetype, keeping the first of each
    seen, uniq = set(), []
    for p in out:
        if p.archetype not in seen:
            seen.add(p.archetype)
            uniq.append(p)
    return tuple(uniq)


def _second_money_plan(f, colony):
    """Big Money on the board's SECOND-best terminal — the cheap alternative
    when the top-ranked one is a $5 the deck may not reach reliably."""
    ranked = sorted([c for c in f["terminal_draw"] + f["cursers"]
                     if _rank(c) > 0], key=_rank, reverse=True)
    if len(ranked) < 2:
        return None
    return Plan("money-2", [entry(ranked[1], 2)], green_at={"deck": 0},
                notes=f"Big Money on {ranked[1]}")


@functools.lru_cache(maxsize=512)
def plan_for(kingdom, colony=False, players=2, force=None):
    """The plan for a kingdom. `kingdom` must be a TUPLE (hashable, cached).

    `force` names an archetype to take instead of the selector's answer — how
    the champion applies a tournament result, and how the arena measures one
    archetype at a time.
    """
    k = list(kingdom)
    f = features(k)

    if force is not None:
        for p in candidates(kingdom, colony, players):
            if p.archetype == force or p.archetype.split(":")[0] == force:
                return p
        return _money_plan(f, colony)

    # 1. Minion auto-picks itself — "the strongest strategy on a significant
    #    majority of boards containing it".
    if "Minion" in k:
        return _minion_plan(f, colony)

    # 2. The engine check. All four ingredients, or it is not an engine:
    #    draw, +Actions to chain it, payload to spend, and a way to thin.
    #    Missing any one is how the "Durdle" archetypes happen.
    if f["villages"] and f["draw"] and (f["trashers"] or f["cantrips"]) \
            and (f["payload"] or f["buys"]):
        return _engine_plan(f, colony)

    # 3. A rush: cheap alt-VP plus a way to drain piles faster than the
    #    opponent can build Provinces.
    rush = _rush_target(f, k, players)
    if rush is not None:
        return _rush_plan(f, rush, colony)

    # 4. Cursers with no engine to build: race the split, then play money.
    if f["cursers"]:
        return _cursing_money_plan(f, colony)

    # 5. Big Money + the best terminal. Always available, always sane.
    return _money_plan(f, colony)


def _money_plan(f, colony):
    terminal = _best(f["terminal_draw"] + f["cursers"], _rank)
    menu = []
    if terminal is not None and _rank(terminal) > 0:
        menu.append(entry(terminal, 1 if terminal in _SINGLE else 2))
    return Plan("money", menu, green_at={"deck": 0},
                notes="Big Money plus the board's best terminal")


def _cursing_money_plan(f, colony):
    curser = _best(f["cursers"], _rank)
    drawer = _best([c for c in f["terminal_draw"] if c != curser], _rank)
    menu = [entry(curser, 2)]
    if drawer is not None and _rank(drawer) > 0:
        menu.append(entry(drawer, 1))
    return Plan("cursing-money", menu, green_at={"deck": 0},
                notes="race the Curse split, then play money")


_DRAWERS = 3            # terminal drawers the engine aims for
_VILLAGES = _DRAWERS    # the ratio rule: never fewer villages than terminals


def _engine_plan(f, colony):
    """The published engine rules as a menu: trash early, +Buy before mass
    payload, villages >= terminals, and — the part a naive engine bot always
    omits — REAL ECONOMY interleaved with the pieces.

    An engine still has to buy Provinces, and every non-money buy costs a
    Silver. The first version of this menu had no money in it at all and
    bought five $6 Border Villages instead of Golds; it measured 0.131 against
    Big Money+, which is the classic "a simple engine loses to Big Money"
    result the corpus opens with.
    """
    village = _best(f["villages"], lambda n: (traits(n)["plus_actions"],
                                              -_cost(n)))
    drawer = _best(f["draw"], lambda n: (traits(n)["plus_cards"], _rank(n)))
    trasher = _best(f["trashers"],
                    lambda n: (traits(n)["trasher"] == "mass", -_cost(n)))
    buy = _best(f["buys"], lambda n: -_cost(n))
    payload = _best(f["payload"], lambda n: traits(n)["plus_coins"])
    curser = _best(f["cursers"], _rank)

    menu = []
    if trasher is not None:
        # trash EARLY: the value of thinning decays as the deck grows
        menu.append(entry(trasher, 1 if traits(trasher)["trasher"] == "mass"
                          else 2))
    if curser is not None:
        menu.append(entry(curser, 2))
    if buy is not None:
        # "+Buy is the most overlooked ingredient" — one copy, early
        menu.append(entry(buy, 1))
    if drawer is not None:
        menu.append(entry(drawer, 2))
    if village is not None:
        menu.append(entry(village, 2, after={drawer: 1} if drawer else None))
    # economy before the SECOND half of the engine — this is the interleave
    menu.append(entry("Gold", 2))
    if drawer is not None:
        menu.append(entry(drawer, _DRAWERS))
    if village is not None:
        menu.append(entry(village, _VILLAGES, after={drawer: 2} if drawer
                          else None))
    if payload is not None and payload != buy:
        menu.append(entry(payload, 2))
    return Plan("engine", menu, green_at={"deck": 16},
                notes="village/draw engine — green once it draws itself")


_SINGLE = {"Council Room", "Magnate", "Witch's Hut"}


def _minion_plan(f, colony):
    # "buy max Minions; no Festival until 6 Minions or the pile is gone"
    menu = [entry("Minion", 8)]
    village = _best(f["villages"], lambda n: -_cost(n))
    if village is not None:
        menu.append(entry(village, 3, after={"Minion": 6}))
    return Plan("minion", menu, green_at={"deck": 16},
                notes="mass Minion")


# The two genuine rush/slog targets in the shipped roster. Gardens rewards a
# flooded deck, Duke rewards mass Duchies. Deliberately NOT every alt-VP card:
# Mill and Tunnel are synergy cards, not pile-drain plans, and treating them as
# rush targets buys worse green for no speed (the "Durdle" failure mode).
_RUSH_VP = ("Gardens", "Duke")


def _rush_target(f, kingdom, players):
    """A rush target, if the board actually supports draining piles for it.

    Both conditions are required and both were learned the hard way: a
    PILE-gainer (something that can take a card off any pile repeatedly — not
    Bureaucrat, which gains one Silver) AND a +Buy to double up. Without them
    the "rush" is a money deck holding worse green, which measured at 0.165
    against Big Money+.
    """
    if not f["pile_gainers"] or not f["buys"]:
        return None
    for card in _RUSH_VP:
        if card in kingdom:
            return card
    return None


def _rush_plan(f, target, colony):
    gainer = _best(f["pile_gainers"], lambda n: -_cost(n))
    buy = _best(f["buys"], lambda n: -_cost(n))
    menu = []
    if gainer is not None:
        menu.append(entry(gainer, 2))
    if buy is not None:
        menu.append(entry(buy, 1))
    return Plan(f"rush:{target}", menu, green_at={"deck": 12},
                notes=f"drain piles into {target}")
