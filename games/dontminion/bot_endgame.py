"""Endgame technique — the skill that separates a ~level-25 player from a 30+.

Every tier from `bmplus` up consults `override` as the LAST step of its buy
decision, so there is one implementation of the rules the strategy corpus is
most emphatic about:

* **If a buy ends the game while you are ahead, take it.** The single most
  repeated rule in the level-30-to-40 threads ("no style points, no comeback
  window"). It is checked first because nothing else can be worth more.
* **The Penultimate Province Rule** and its exceptions. Buying the
  second-to-last Province while trailing hands the opponent the last one and
  the win; the exceptions are where most of the value is.
* **Pile control** — three-pile awareness, defensive greening, and the
  "two piles low makes Duchies strong" rule.
* **A greening clock** — don't buy points before the deck can afford them
  ("greened too early: both players stall").

Everything here is a pure function of the game dict, so tiers can call it
freely and the search tiers can call it inside rollouts.
"""

from . import engine
from .bot_traits import pile_traits, traits

# The classic ladder's thresholds, kept in one place so every tier greens on
# the same clock: Duchy once Provinces are short, Estate only at the death.
DUCHY_AT = 5            # Provinces remaining
ESTATE_AT = 2
LAST_PILE_WATCH = 3     # a pile this low counts as "running out"


def _vp(game, pid):
    return game["vp"].get(pid, 0)


def leader(game, pid):
    """(our score, the best opponent's score). Ties count as being level."""
    mine = _vp(game, pid)
    theirs = max((_vp(game, o) for o in engine.opponents(game, pid)),
                 default=0)
    return mine, theirs


def margin(game, pid):
    mine, theirs = leader(game, pid)
    return mine - theirs


def _turn_order_edge(game, pid):
    """Dominion breaks a VP tie in favour of whoever took FEWER turns. A tie on
    points is therefore a WIN for the player still behind on turns."""
    mine = game["seats"][pid]["turns_taken"]
    return all(mine <= game["seats"][o]["turns_taken"]
               for o in engine.opponents(game, pid))


def winning_on_tiebreak(game, pid):
    m = margin(game, pid)
    return m > 0 or (m == 0 and _turn_order_edge(game, pid))


def low_piles(game):
    """Supply piles at or below the watch threshold, empties included."""
    return sorted(p for p, n in game["supply"].items() if n <= LAST_PILE_WATCH)


def ends_the_game(game, card):
    """Would buying `card` right now end the game?

    The three conditions the engine itself checks: Provinces out, Colonies out
    (colony games), or a third empty pile.
    """
    sup = game["supply"]
    if card not in sup or sup[card] <= 0:
        return False
    after = sup[card] - 1
    if card == "Province" and after == 0:
        return True
    if card == "Colony" and after == 0:
        return True
    return after == 0 and engine.count_empty_piles(game) >= 2


def opponent_max_vp_swing(game, pid):
    """A conservative read of the most VP an opponent can add in ONE turn.

    The PPR's "+Buy exception": a bare lead is not enough when the opponent can
    take a Province AND something else. Read off what they actually own — extra
    buys and gainers — rather than assuming one buy.
    """
    best = 0
    for o in engine.opponents(game, pid):
        owned = engine.owned_cards(game, o)
        extra = sum(1 for c in owned
                    if traits(c)["plus_buy"] or traits(c)["gainer"])
        # one Province, plus a Duchy per extra buy source (capped: they still
        # have to draw and pay for them)
        best = max(best, 6 + 3 * min(extra, 2))
    return best


# ── the Penultimate Province Rule ────────────────────────────────────────────

def ppr_blocks(game, pid, card):
    """Should we NOT buy `card` because it is the penultimate Province?

    Wiki statement plus every exception it lists:
      * only bites when buying leaves exactly one of that pile;
      * only when TRAILING — a tie is a buy (and for the second player it is
        nearly a win, since the tie breaks on turn count);
      * not when a lesser green card cannot take the lead anyway;
      * not when taking both remaining cards is the only path left
        ("go for broke");
      * not when the opponent's one-turn swing beats any lead we could build,
        which is what +Buy and trash-for-benefit do to this rule.
    """
    if card not in ("Province", "Colony"):
        return False
    sup = game["supply"]
    if sup.get(card, 0) != 2:               # only the penultimate one
        return False
    if winning_on_tiebreak(game, pid):
        return False                        # ahead or tied: take it
    deficit = -margin(game, pid)
    lesser = _best_lesser_green(game, pid)
    if lesser is None:
        return False                        # nothing else to buy: take it
    if _vp_of(game, lesser) <= deficit:
        return False                        # a Duchy would not take the lead
    if deficit > opponent_max_vp_swing(game, pid):
        return False                        # go for broke — nothing else wins
    return True


def _vp_of(game, pile):
    """Plain VP of what a pile hands you. Every caller here starts from a
    Supply KEY, which is a pile name — and a pile is not always the card it is
    named after (see bot_traits.pile_traits)."""
    v = engine.CARDS[engine.pile_face(game, pile)]["vp"]
    return v if isinstance(v, int) else 0


def _best_lesser_green(game, pid):
    """The best plain-VP card we could buy instead, at the current coins."""
    best, score = None, 0
    for c, n in game["supply"].items():
        if n <= 0 or c in ("Province", "Colony"):
            continue
        if not pile_traits(game, c)["victory"] or engine.cost(game, c) > game["coins"]:
            continue
        if engine.buy_gate(game, pid, c) is not None:
            continue
        v = _vp_of(game, c)
        if v > score:
            best, score = c, v
    return best


# ── the override ─────────────────────────────────────────────────────────────

def override(game, pid, planned):
    """The endgame's answer, or `planned` unchanged.

    Called as the LAST step of a tier's buy decision, so a plan can be as naive
    as it likes about how the game finishes.
    """
    if game["phase"] != "buy" or game["buys"] <= 0:
        return planned
    affordable = _affordable(game, pid)

    # 1. Take a win that is on the table. Nothing outranks this.
    for c in affordable:
        if ends_the_game(game, c) and _wins_after_buying(game, pid, c):
            return c

    # 2. Never hand the win over: a buy that ends the game while we are behind
    #    is the worst move on the board.
    if planned is not None and ends_the_game(game, planned) \
            and not _wins_after_buying(game, pid, planned):
        alt = _best_non_ending(game, pid, affordable)
        if alt is not None:
            return alt
        return None                         # buying nothing beats losing now

    # 3. The Penultimate Province Rule.
    if planned is not None and ppr_blocks(game, pid, planned):
        lesser = _best_lesser_green(game, pid)
        if lesser is not None:
            return lesser

    # 4. Two piles low makes Duchies strong (the level-40 rule) — take the
    #    points while the game can end under us. An EMPTY pile counts here:
    #    it is a pile that has already run out, which is the strongest form of
    #    "running low" (filtering empties out was the first version, and it
    #    made the rule silently never fire on the boards that need it most).
    if planned is not None and not pile_traits(game, planned)["victory"]:
        if len(low_piles(game)) >= 2:
            duchy = _best_lesser_green(game, pid)
            if duchy is not None and _vp_of(game, duchy) >= 3:
                return duchy
    return planned


def _affordable(game, pid):
    return [c for c, n in game["supply"].items()
            if n > 0 and engine.cost(game, c) <= game["coins"]
            and engine.buy_gate(game, pid, c) is None]


def _wins_after_buying(game, pid, card):
    """Would we win (or tie-and-win-on-turns) with `card` added to our pile?"""
    mine = _vp(game, pid) + _vp_of(game, card)
    if engine.pile_face(game, card) == "Gardens":                   # its value depends on deck size
        mine = _vp(game, pid) + (len(engine.owned_cards(game, pid)) + 1) // 10
    theirs = max((_vp(game, o) for o in engine.opponents(game, pid)), default=0)
    return mine > theirs or (mine == theirs and _turn_order_edge(game, pid))


def _best_non_ending(game, pid, affordable):
    """The most valuable buy that does NOT end the game — what to take instead
    when we are behind and the obvious buy would finish it."""
    best, score = None, float("-inf")
    for c in affordable:
        if ends_the_game(game, c):
            continue
        s = _vp_of(game, c) * 10 + engine.cost(game, c)
        if s > score:
            best, score = c, s
    return best


# ── the greening clock ───────────────────────────────────────────────────────

def should_green(game, pid, min_golds=2):
    """Is the deck ready to start buying points?

    "Too early and both players stall; too late and the points gap is
    unwinnable." The published bar is >= 2 Golds (or the money density that
    implies) before the first Province.
    """
    if game["supply"].get("Province", 0) <= DUCHY_AT:
        return True                         # the clock has run out regardless
    owned = engine.owned_cards(game, pid)
    golds = sum(1 for c in owned if engine.coins_of(game, c) >= 3)
    return golds >= min_golds
