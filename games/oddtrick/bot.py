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


def _want_win(g: dict, seat: int) -> bool:
    """Whether the mover wants THIS trick, contract-aware.

    Normal contracts: everyone wants the +2 tricks and nobody wants the -1s.
    Null flips both seats: the declarer must never win a +2 trick (and winning
    a -1 means LEADING the +2 that follows -- the worst seat to duck from), so
    they duck everything; the defender wants the declarer to eat the +2s, so
    they duck those too and win the -1s to keep the lead.
    """
    ev = E.trick_value(g["trick"]) > 0
    if g["auction"]["denom"] == E.NULL_DENOM:
        decl = g["auction"]["declarer"]
        return not ev if seat != decl else False
    return ev


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
    return max(moves, key=lambda c: (policy_score(g, c, seat), -c))


# --- bidding ---------------------------------------------------------------

#: Rough worth of each rank as a trick-winner (8 entries, rank 0 = the 7). The
#: game needs LOW cards too (to force the -1 tricks onto the opponent), so the
#: curve is deliberately shallower than a normal high-card-point count.
_RANK_VALUE = [0.0, 0.0, 0.0, 0.2, 0.5, 1.0, 1.6, 2.4]


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
    """Return {"pass": True} or {"level": n, "denom": d}.

    The bot never bids Null: it is a 33%-make gamble under EXACT play, and a
    one-trick-deep policy has no business finding the other 67%.
    """
    rng = rng or random.Random()
    opt = E.auction_options(g)
    bids = [b for b in opt["bids"] if b[1] != E.NULL_DENOM]
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


def choose_swap(g: dict, seat: int) -> dict:
    """Pick the exchange that most strengthens the declared contract.

    Value each candidate hand by rank-worth in the contract denomination;
    keep the swap only if it improves on standing pat. Under Null the polarity
    flips -- LOW cards are the good ones, so swap out the biggest.
    """
    a = g["auction"]
    denom = a["denom"]
    hand = list(g["hands"][seat])
    is_null = denom == E.NULL_DENOM

    def worth(c: int) -> float:
        v = _RANK_VALUE[E.rank(c)]
        if is_null:
            return -E.rank(c)  # every high card is a liability
        if denom < E.NOTRUMP and E.suit(c) == denom:
            v += 0.8  # trump length is worth having
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
    """One bot action for whichever phase the game is in."""
    if g["phase"] == "auction":
        return ("bid", choose_bid(g, seat, rng))
    if g["phase"] == "swap":
        return ("swap", choose_swap(g, seat))
    if g["phase"] == "play":
        return ("play", choose_card(g, seat))
    return (None, None)
