"""Dissonance bots — the Easy tier, server-side.

The card-play policy is a direct port of ``policy.rs`` from the Rust core: one
trick deep, take the +2 tricks as cheaply as possible and shed the -1 tricks as
expensively as possible. It is the floor the searching bot has to clear: a
CRN-paired arena on the v2 rules puts ``pimc:8`` **+1.10 +/- 0.10 trick points
per round** ahead of it, on a pool of 5.

THIS FILE IS ALSO WHAT HARD FALLS BACK TO. The Hard tier is the Rust core
compiled to WASM and run client-side, and when the browser does not answer a
decision ``_bot_move_sync`` lands here -- so a Hard room with no working WASM is
playing Normal. That is the whole reason the client tier exists; there is no
server-side search at any tier.
"""

from __future__ import annotations

import random

from . import engine as E

# --- card play -------------------------------------------------------------


def _want_win(g: dict, seat: int) -> bool:
    """Whether the mover wants THIS trick.

    Everyone wants the +2 tricks and nobody wants the -1s.

    IT DOES NOT CHASE THE NULL CONSOLATION, and that is a known gap rather than
    an oversight. Since 2026-08-07 a declarer who takes no +2 trick all round
    scores Null instead of being set, so a declarer whose contract has already
    gone wrong should switch to ducking EVERYTHING -- but "already gone wrong"
    is a lookahead judgement, and this tier is one trick deep. Reading it off
    the current total instead (duck once you are behind) would make the bot
    throw away contracts it was still winning. The Hard tier does not chase it
    either: its solver maximises trick POINTS, and Null is a discontinuous jump
    the double-dummy value function cannot see. Both want the contract-aware
    solve (`dd::solve_contract`) that already exists for the auction.
    """
    return E.trick_value(g["trick"]) > 0


def policy_score(g: dict, c: int, seat: int | None = None) -> float:
    """Higher is more attractive for the player to move."""
    if seat is None:
        seat = E.to_play(g)
    want_win = _want_win(g, seat)
    r = E.rank(c) / (E.NRANK - 1.0)
    led = g["led"]
    if led is not None:
        w = E.beats(led, c, g["trump"])
        if want_win:
            return 3.0 - r if w else 1.0 - r
        return 0.6 - r if w else 3.0 + r
    # Grand counts here too: its trump class is a real one, it is just made
    # of the four tens rather than a suit.
    trumpish = 1.0 if E.esuit(c, g["trump"]) == E.trump_class(g["trump"]) else 0.0
    if want_win:
        return 1.0 + r + trumpish
    # Lead low: under mandatory follow-suit this is how a -1 trick gets forced
    # onto the opponent.
    return 1.0 + (1.0 - r) - trumpish


def choose_card(g: dict, seat: int) -> int:
    moves = E.legal_moves(g, seat)
    if not moves:
        raise ValueError("no legal move")
    return max(moves, key=lambda c: (policy_score(g, c, seat), -c))


# --- bidding ---------------------------------------------------------------

#: Rough worth of each rank as a trick-winner (8 entries, rank 0 = the 7). The
#: game needs LOW cards too (to force the -1 tricks onto the opponent), so the
#: curve is deliberately shallower than a normal high-card-point count.
_RANK_VALUE = [0.0, 0.0, 0.0, 0.2, 0.5, 1.0, 1.6, 2.4]


#: What a card the seat cannot identify is worth: the mean of `_RANK_VALUE`.
#:
#: A seat holds thirteen cards but can only NAME eleven of them -- the two outer
#: pile bottoms are dealt face down to their owner as well as to the opponent.
#: Dropping them entirely would under-rate every hand by two cards and quietly
#: re-tune every threshold in `_level_for`; counting them at their expectation
#: keeps the scale where it was. It is the unconditional deck mean rather than
#: one conditioned on what the seat can see, which is the right refinement for a
#: tier that has any lookahead at all -- this one has none.
_UNKNOWN_RANK_VALUE = sum(_RANK_VALUE) / len(_RANK_VALUE)


def hand_strength(g: dict, seat: int, denom: int) -> float:
    """Cheap estimate of the points this seat could take in `denom`.

    ONLY THE CARDS THE SEAT MAY ACTUALLY NAME. This used to read every pile
    bottom it owned, and two of the three are face down to their owner too -- so
    the bot bid a hand it could see two cards more of than the player across the
    table could see of theirs. Not opponent knowledge, so it never played a card
    it could not have played; it simply valued its own hand with information the
    rules do not give it, in both auctions and in the talon swap.
    """
    cards = E.playable(g, seat) + [
        p[0] for i, p in enumerate(g["piles"][seat]) if len(p) == 2 and i == 1]
    unknown = sum(1 for i, p in enumerate(g["piles"][seat]) if len(p) == 2 and i != 1)
    total = sum(_RANK_VALUE[E.rank(c)] for c in cards)
    total += unknown * _UNKNOWN_RANK_VALUE
    if denom == E.GRAND:
        # There are only four trumps in a Grand game, so LENGTH is not the
        # question -- holding any of them at all is. Each is worth roughly a
        # stolen trick, and the rest of the hand is valued as if at no-trump.
        total += sum(1.4 for c in cards if E.rank(c) == E.TEN_RANK)
        longest = max(sum(1 for c in cards if E.suit(c) == s) for s in range(4))
        total -= max(0, longest - 5) * 0.8
    elif denom < E.NOTRUMP:
        n = sum(1 for c in cards if E.suit(c) == denom)
        total += max(0, n - 3) * 1.2  # length is worth something, shortage is not
    else:
        # No-trump rewards balance: penalise a long suit that would be trump.
        longest = max(sum(1 for c in cards if E.suit(c) == s) for s in range(4))
        total -= max(0, longest - 5) * 0.8
    return total


def _level_for(strength: float) -> int:
    """Map a strength estimate onto a contract level."""
    for lvl, need in ((6, 15.0), (5, 12.5), (4, 10.5), (3, 8.5), (2, 6.5)):
        if strength >= need:
            return lvl
    return E.MIN_LEVEL


def choose_bid(g: dict, seat: int, rng=None) -> dict:
    """Return {"pass": True} or {"level": n, "denom": d}."""
    rng = rng or random.Random()
    opt = E.auction_options(g)
    bids = list(opt["bids"])
    if not bids:
        return {"pass": True} if opt["may_pass"] else {"pass": True}

    denoms = sorted({d for _, d in bids})
    best_d = max(denoms, key=lambda d: hand_strength(g, seat, d))
    want = _level_for(hand_strength(g, seat, best_d))
    mine = [lvl for lvl, d in bids if d == best_d]
    if not mine:
        return {"pass": True}
    if g["auction"]["level"] == 0:
        # Opening: name what the hand is worth, floored at the minimum.
        return {"level": max(mine[0], min(want, mine[-1])), "denom": best_d}
    # Overtaking: take the cheapest rung in the best denomination, but only
    # when the hand genuinely supports that contract. A same-level overtake in
    # a higher rank is the cheapest of all and needs the same strength.
    if want >= mine[0]:
        return {"level": mine[0], "denom": best_d}
    return {"pass": True}


# --- skat mode: the number ladder, the declaration, Kontra ------------------
#
# All three reuse `hand_strength` / `_level_for` — the arithmetic the mode
# needs is exactly the arithmetic already here, pointed at a different question.
# A hand's BID CEILING is max over denominations of (base x the level that
# denomination is worth), because bidding a number V forces you to declare at
# ceil(V / base) in whichever denomination you pick.
#
# The thresholds below (`_KONTRA_TARGET`, `_KONTRA_STRENGTH`) are GUESSES, not
# measurements. SKAT_MODE.md's open question 4 — "Kontra should double
# 10–20% of contracts, correctly more often than not" — is a `skatlab`
# self-play sweep that has not been run; until it is, this tier is deliberately
# reluctant rather than tuned.

#: A defender only doubles a promise this greedy...
_KONTRA_TARGET = 8
#: ...and only when its own holding in the declared denomination backs the read.
_KONTRA_STRENGTH = 10.0


def skat_ceiling(g: dict, seat: int) -> int:
    """The largest number this hand can afford to be held to."""
    best = 0
    for d in E.SKAT_DENOMS:
        want = _level_for(hand_strength(g, seat, d))
        best = max(best, E.SKAT_BASE[d] * want)
    return best


def choose_skat_bid(g: dict, seat: int) -> dict:
    """Return {"pass": True} or {"value": v}: march up the ladder while the
    standing number is still below the ceiling."""
    # The ladder is ascending, so the first rung above the standing bid is the
    # cheapest way to stay in — there is never a reason to jump past it.
    above = E.auction_options(g)["values"]
    if above and above[0] <= skat_ceiling(g, seat):
        return {"value": above[0]}
    return {"pass": True}


def choose_declare(g: dict, seat: int) -> dict:
    """Name the game that satisfies the bid with the least stretch.

    Never announces: Hand, Sharp and Open all multiply a contract this bot is
    not confident enough to have bought in the first place.
    """
    bid = g["auction"]["value"]
    best, best_key = None, None
    for opt in E.skat_declarable(bid):
        d = opt["denom"]
        strength = hand_strength(g, seat, d)
        # How far past what the hand is worth this bid drags the level.
        stretch = opt["min_level"] - _level_for(strength)
        key = (max(0, stretch), -strength)
        if best_key is None or key < best_key:
            best, best_key = opt, key
    return {"denom": best["denom"], "level": best["min_level"],
            "sharp": False, "open": False}


def choose_kontra(g: dict, seat: int) -> bool:
    a = g["auction"]
    target = a["level"] + (E.SHARP_BONUS if g["contract"]["sharp"] else 0)
    return (target >= _KONTRA_TARGET
            and hand_strength(g, seat, a["denom"]) >= _KONTRA_STRENGTH)


def swap_denom(g: dict, seat: int) -> int:
    """Which denomination the talon exchange should be valued in.

    Classic mode swaps AFTER the auction, so the declared denomination is the
    right answer and is already sitting in `auction["denom"]`. Skat mode
    inverts the order -- the talon resolves BEFORE the game is named, so that
    key is still -1 and reading it silently disables both contract-aware terms
    in `worth()` below. Use the denomination this hand is actually worth most
    in; `choose_declare` picks from the post-swap hand on the same measure, so
    the two agree.
    """
    denom = g["auction"]["denom"]
    if denom >= 0:
        return denom
    # Only skat mode reaches here, and Grand is one of its games -- leaving it
    # out would value the talon as if the tens were ordinary cards.
    return max(E.SKAT_DENOMS, key=lambda d: hand_strength(g, seat, d))


def choose_swap(g: dict, seat: int, denom: int | None = None) -> dict:
    """Pick the exchange that most strengthens the intended contract.

    Value each candidate hand by rank-worth in `denom` (defaulting to whichever
    denomination this position implies); keep the swap only if it improves on
    standing pat.
    """
    if denom is None:
        denom = swap_denom(g, seat)
    hand = list(g["hands"][seat])

    def worth(c: int) -> float:
        v = _RANK_VALUE[E.rank(c)]
        if E.esuit(c, denom) == E.trump_class(denom):
            v += 0.8  # a trump is worth having -- a Grand ten most of all
        return v

    best = {"take": None, "give": None}
    best_gain = 0.0
    for t in g["shown"]:
        for h in hand:
            gain = worth(t) - worth(h)
            if gain > best_gain:
                best_gain = gain
                best = {"take": t, "give": h}
    return best


def act(g: dict, seat: int, rng=None):
    """One bot action for whichever phase the game is in.

    Returns ``(kind, payload)``. ``"move"`` means the payload is already a
    complete move dict — the skat phases have no shared shape worth flattening.
    """
    phase = g["phase"]
    skat = E.mode_of(g) == "skat"
    if phase == "auction":
        if skat:
            b = choose_skat_bid(g, seat)
            return ("move", {"kind": "pass"} if b.get("pass")
                    else {"kind": "bid", "value": b["value"]})
        return ("bid", choose_bid(g, seat, rng))
    if phase == "swap":
        return ("swap", choose_swap(g, seat))
    if phase == "talon":
        # Always look. Hand is worth x2, but a tier that cannot evaluate the
        # gamble should not take it — and looking is also how the bot finds out
        # whether the talon fixes a denomination for it.
        if not g.get("looked"):
            return ("move", {"kind": "look"})
        sw = choose_swap(g, seat)
        return ("move", {"kind": "swap", "take": sw["take"], "give": sw["give"]})
    if phase == "declare":
        return ("move", {"kind": "declare", **choose_declare(g, seat)})
    if phase == "kontra":
        return ("move", {"kind": "kontra", "on": choose_kontra(g, seat)})
    if phase == "re":
        # Doubling back is a read on the defender's read; not this tier.
        return ("move", {"kind": "re", "on": False})
    if phase == "play":
        return ("play", choose_card(g, seat))
    return (None, None)
