"""Oddtrick bots — the Easy tier, server-side.

The card-play policy is a direct port of ``policy.rs`` from the Rust core: one
trick deep, take the +2 tricks as cheaply as possible and shed the -1 tricks as
expensively as possible. It is the floor the searching bot has to clear, and
the reference measured it at 69.8% behind ``pimc:8`` -- so this is a genuine
beginner opponent, not a placeholder.

The Hard tier is the Rust core itself compiled to WASM and run client-side;
nothing here is on that path.
"""

from __future__ import annotations

import random

from . import engine as E

# --- card play -------------------------------------------------------------


def policy_score(g: dict, c: int) -> float:
    """Higher is more attractive for the player to move."""
    want_win = E.trick_value(g["trick"]) > 0
    r = E.rank(c) / 6.0
    led = g["led"]
    if led is not None:
        w = E.beats(led, c, g["trump"])
        if want_win:
            return 3.0 - r if w else 1.0 - r
        return 0.6 - r if w else 3.0 + r
    trumpish = 1.0 if g["trump"] < E.NOTRUMP and E.suit(c) == g["trump"] else 0.0
    if want_win:
        return 1.0 + r + trumpish
    # Lead low: under mandatory follow-suit this is how a -1 trick gets forced
    # onto the opponent.
    return 1.0 + (1.0 - r) - trumpish


def choose_card(g: dict, seat: int) -> int:
    moves = E.legal_moves(g, seat)
    if not moves:
        raise ValueError("no legal move")
    return max(moves, key=lambda c: (policy_score(g, c), -c))


# --- bidding ---------------------------------------------------------------

#: Rough worth of each rank as a trick-winner. The game needs LOW cards too
#: (to force the -1 tricks onto the opponent), so the curve is deliberately
#: shallower than a normal high-card-point count.
_RANK_VALUE = [0.0, 0.0, 0.2, 0.5, 1.0, 1.6, 2.4]


def hand_strength(g: dict, seat: int, denom: int) -> float:
    """Cheap estimate of the points this seat could take in `denom`."""
    cards = E.playable(g, seat) + [p[0] for p in g["piles"][seat] if len(p) == 2]
    total = sum(_RANK_VALUE[E.rank(c)] for c in cards)
    if denom < E.NOTRUMP:
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
    if not opt["denoms"]:
        return {"pass": True}

    best_d = max(opt["denoms"], key=lambda d: hand_strength(g, seat, d))
    want = _level_for(hand_strength(g, seat, best_d))

    if not opt["levels"]:
        return {"pass": True}
    lo = opt["levels"][0]
    if g["auction"]["level"] == 0:
        # Opening: name what the hand is worth, floored at the minimum.
        return {"level": max(lo, min(want, opt["levels"][-1])), "denom": best_d}
    # Overtaking costs at least one level, so only do it when the hand
    # genuinely supports the higher contract.
    if want >= lo:
        return {"level": lo, "denom": best_d}
    return {"pass": True}


def act(g: dict, seat: int, rng=None):
    """One bot action for whichever phase the game is in."""
    if g["phase"] == "auction":
        return ("bid", choose_bid(g, seat, rng))
    if g["phase"] == "play":
        return ("play", choose_card(g, seat))
    return (None, None)
