"""Oddtrick — the rules. Single source of truth; main.py delegates everything.

A two-player trick-taking game where taking tricks is not simply good.
Even-numbered tricks score +2 to whoever wins them, odd-numbered ones -1.
Six positive against seven negative, so both players' totals always sum to
exactly +5 and sweeping all thirteen tricks scores worse than taking the six
even ones. The game is about WHICH tricks you win.

Version 2 (the 2026-08-07 release, all four changes measured in
rust-cores/oddtrick-core/CAMPAIGN.md): a 32-card deck with SIX cards out of
play (the hidden-information sweep's efficient point), ranked denominations
(C < D < H < S < NT < Null -- same-level overtakes in a higher rank), the Null
contract (win no +2 trick; fixed rung 6, pays 12 / set 10), and the declarer's
swap (shown 3 of the out-cards after the auction, may take one into hand).

Ported from ``rust-cores/oddtrick-core`` (``state.rs`` + ``auction.rs``),
which is the solver-validated reference. ``tests/test_rust_parity.py`` replays
fixtures generated there and asserts identical states, so this file must not
drift from it.

The game dict is JSON-safe throughout (ints and lists only, no sets) so it
survives the state_json codec, saves and reconnects. There is deliberately no
``rng_state``: every random draw happens in the deal, nothing draws later, so
persisting a Mersenne state would be ~600 words that nothing ever reads (the
Where Wolf? lesson).
"""

from __future__ import annotations

import random

# --- cards -----------------------------------------------------------------
# card = suit * 8 + rank, 0..31. rank 0 = 7, rank 7 = A.
#
# 32 cards with 13 dealt to each player leaves SIX out of play instead of two.
# That count is the game's entire permanent hidden-information budget (every
# card you cannot see is your opponent's unless it is out of play), and the
# 2026-08-07 sweep measured it saturating hard past 6 -- see
# rust-cores/oddtrick-core/CAMPAIGN.md.

VERSION = 2  # bumped by the 32-card / ranked / Null / swap release

NRANK = 8
NSUIT = 4
NCARD = 32
NOTRUMP = 4

RANK_NAMES = ["7", "8", "9", "10", "J", "Q", "K", "A"]
SUIT_NAMES = ["clubs", "diamonds", "hearts", "spades"]
SUIT_CHARS = ["c", "d", "h", "s"]
DENOM_NAMES = SUIT_NAMES + ["no-trump", "Null"]

NTRICKS = 13
POOL = 5  # both players' point totals always sum to this

MIN_LEVEL = 1
MAX_LEVEL = 12
#: An overtake must raise the contract by 1 or 2. Measured: a cap of exactly 2
#: relocates the punishment-landing pile from level 2 to level 3, which is
#: where the distribution had a hole. A cap of 3 empties level 3 again.
MAX_RAISE = 2

#: Set-score multiplier per point the declarer finished short.
SHORT_PENALTY = 4

#: Denominations are RANKED by index (C < D < H < S < NT < Null), so an
#: overtake may also stand at the SAME level in a higher-ranked denomination.
#: Measured: the first change that SPREAD the settled-contract distribution
#: instead of translating its spike (level-4 hole 6.7% -> 14.2%), replicated
#: on both deck widths.
#:
#: NULL: "I will win no +2 trick." A trick-COUNT condition, because the
#: constant-sum pool makes an inverse POINT contract identical to a normal
#: one. It bids as a single fixed rung -- level 6, above no-trump -- and pays
#: a flat amount either way. Rung 6 is measured, not chosen: at rung 3 it was
#: overtaken away in 100% of auctions (0 contracts in 240 rounds), at rung 8
#: nobody could make it, and raising the price SUPPRESSES it (a 33% gamble is
#: only worth taking when losing is cheap).
NULL_DENOM = 5
NULL_LEVEL = 6
NULL_MAKE = 12
NULL_SET = 10

#: Out-of-play cards the declarer is shown after the auction; they may swap
#: exactly one into hand (hand cards only -- the piles are the board, not the
#: holding).
N_OUT = 6
N_SHOWN = 3


def suit(c: int) -> int:
    return c // NRANK


def rank(c: int) -> int:
    return c % NRANK


def card_name(c: int) -> str:
    return f"{RANK_NAMES[rank(c)]}{SUIT_CHARS[suit(c)]}"


def trick_value(trick: int) -> int:
    """Value of the 0-indexed trick. Trick index 0 is trick NUMBER 1 (odd)."""
    return 2 if trick % 2 == 1 else -1


def beats(led: int, follow: int, trump: int) -> bool:
    ls, fs = suit(led), suit(follow)
    if fs == ls:
        return rank(follow) > rank(led)
    if trump < NOTRUMP:
        # Off-suit only wins by ruffing, and only if the lead was not trump.
        return fs == trump and ls != trump
    return False


# --- dealing ---------------------------------------------------------------


def new_game(seats, rng=None, opener: int = 0) -> dict:
    """Deal a round. `seats` is [pid0, pid1]; `opener` names the first bidder."""
    rng = rng or random.Random()
    deck = list(range(NCARD))
    rng.shuffle(deck)

    hands, piles = [], []
    k = 0
    for _ in range(2):
        hands.append(sorted(deck[k:k + 7]))
        k += 7
        # Each pile is [bottom, top]; only the last element is playable.
        piles.append([[deck[k + 2 * i], deck[k + 2 * i + 1]] for i in range(3)])
        k += 6
    out = deck[26:26 + N_OUT]

    return {
        "v": VERSION,
        "seats": list(seats),
        "phase": "auction",
        "hands": hands,
        "piles": piles,
        "out": out,
        # The subset of `out` shown to whoever wins the auction. Fixed at the
        # deal so it does not depend on who wins; secret until then.
        "shown": out[:N_SHOWN],
        # None until the swap phase resolves; then True/False. WHICH cards
        # moved stays hidden -- the defender learns only that a swap happened.
        "swapped": None,
        "opener": opener,
        # The auction is real game state, not a transient message field, so it
        # survives saves and reconnects and stays server-enforced.
        "auction": {
            "level": 0,
            "denom": -1,
            "declarer": -1,
            "used": [0, 0],
            "to_act": opener,
            "log": [],
        },
        "trump": NOTRUMP,
        "trick": 0,
        "leader": opener,
        "led": None,
        "pts": [0, 0],
        # +2 tricks won by each seat -- the Null contract's condition.
        "etricks": [0, 0],
        "history": [],
        "played": [],
        "result": None,
    }


# --- auction ---------------------------------------------------------------


def auction_options(g: dict) -> dict:
    """Everything the player to act may legally do, for the client to render.

    ``bids`` is an explicit list of [level, denom] pairs, NOT a levels x denoms
    cross-product: under ranked denominations the legal set at the standing
    level depends on which denomination stands, and Null exists at exactly one
    rung. A client that reconstructs the set from two axes will get it wrong.
    """
    a = g["auction"]
    if g["phase"] != "auction":
        return {"bids": [], "may_pass": False}
    me = a["to_act"]
    free = [d for d in range(NULL_DENOM + 1) if not (a["used"][me] >> d) & 1]
    bids: list[list[int]] = []
    if a["level"] == 0:
        # The opener must bid; passing out is not offered.
        for d in free:
            if d == NULL_DENOM:
                bids.append([NULL_LEVEL, d])
            else:
                bids.extend([lvl, d] for lvl in range(MIN_LEVEL, MAX_LEVEL + 1))
        return {"bids": bids, "may_pass": False}
    # Ranked denominations: an overtake stands at the SAME level in a
    # higher-ranked denomination, or raises by up to MAX_RAISE in any unused
    # one. Null lives at its single rung and follows the same ordering.
    lo, hi = a["level"], min(MAX_LEVEL, a["level"] + MAX_RAISE)
    for d in free:
        if d == NULL_DENOM:
            if lo <= NULL_LEVEL <= hi and not (
                NULL_LEVEL == a["level"] and a["denom"] >= NULL_DENOM
            ):
                bids.append([NULL_LEVEL, d])
            continue
        for lvl in range(lo, hi + 1):
            if lvl == a["level"] and d <= a["denom"]:
                continue  # same level: only a higher-ranked denomination outranks
            bids.append([lvl, d])
    return {"bids": bids, "may_pass": True}


def can_bid(g: dict, seat: int, level: int, denom: int) -> tuple[bool, str]:
    if g["phase"] != "auction":
        return False, "not bidding"
    a = g["auction"]
    if seat != a["to_act"]:
        return False, "not your turn"
    if [level, denom] not in auction_options(g)["bids"]:
        return False, "that bid does not outrank the standing contract"
    return True, ""


def apply_bid(g: dict, seat: int, level: int, denom: int) -> None:
    ok, why = can_bid(g, seat, level, denom)
    if not ok:
        raise ValueError(why)
    a = g["auction"]
    a["level"] = level
    a["denom"] = denom
    a["declarer"] = seat
    a["used"][seat] |= 1 << denom
    a["to_act"] = 1 - seat
    a["log"].append({"seat": seat, "level": level, "denom": denom})


def apply_pass(g: dict, seat: int) -> None:
    if g["phase"] != "auction":
        raise ValueError("not bidding")
    a = g["auction"]
    if seat != a["to_act"]:
        raise ValueError("not your turn")
    if a["level"] == 0:
        raise ValueError("the opener must bid")
    a["log"].append({"seat": seat, "pass": True})
    # The declarer now sees `shown` and decides on the swap before play.
    g["phase"] = "swap"


def swap_options(g: dict) -> dict:
    """What the declarer may do in the swap phase."""
    if g["phase"] != "swap":
        return {"shown": [], "hand": []}
    decl = g["auction"]["declarer"]
    return {"shown": list(g["shown"]), "hand": sorted(g["hands"][decl])}


def apply_swap(g: dict, seat: int, take, give) -> None:
    """Take one shown out-card into hand, discarding a HAND card in its place.

    ``take is None`` declines the swap. The discarded card joins the out pile
    face-down, so the defender learns only that a swap happened -- the round-end
    reveal is what eventually shows which cards moved.
    """
    if g["phase"] != "swap":
        raise ValueError("not the swap phase")
    decl = g["auction"]["declarer"]
    if seat != decl:
        raise ValueError("only the declarer swaps")
    if take is None:
        g["swapped"] = False
    else:
        take, give = int(take), int(give)
        if take not in g["shown"]:
            raise ValueError("that card was not shown")
        if give not in g["hands"][decl]:
            raise ValueError("you may only swap a card from your hand")
        g["hands"][decl].remove(give)
        g["hands"][decl].append(take)
        g["hands"][decl].sort()
        g["out"][g["out"].index(take)] = give
        g["shown"][g["shown"].index(take)] = give
        g["swapped"] = True
    _start_play(g)


def _start_play(g: dict) -> None:
    a = g["auction"]
    g["phase"] = "play"
    # A Null contract is played at no trump: a trump suit would only add a
    # second way for the declarer to be forced to win a trick.
    g["trump"] = NOTRUMP if a["denom"] == NULL_DENOM else a["denom"]
    g["trick"] = 0
    g["led"] = None
    # The DECLARER leads to trick 1. Measured worth +0.93 pts under the
    # original parity, so this is a real part of the contract's value.
    g["leader"] = a["declarer"]


# --- card play -------------------------------------------------------------


def pile_tops(g: dict, seat: int) -> list[int]:
    return [p[-1] for p in g["piles"][seat] if p]


def playable(g: dict, seat: int) -> list[int]:
    """Every card the seat could reach, ignoring follow-suit."""
    return sorted(g["hands"][seat] + pile_tops(g, seat))


def legal_moves(g: dict, seat: int) -> list[int]:
    if g["phase"] != "play" or seat != to_play(g):
        return []
    cands = playable(g, seat)
    if g["led"] is not None:
        ls = suit(g["led"])
        follow = [c for c in cands if suit(c) == ls]
        # Follow-suit is MANDATORY and a pile's exposed top counts as a card
        # you hold, so the piles can constrain you.
        if follow:
            return follow
    return cands


def to_play(g: dict) -> int:
    return g["leader"] if g["led"] is None else 1 - g["leader"]


def _remove(g: dict, seat: int, c: int) -> int:
    """Take `c` out of the seat's holdings; returns the source (0=hand, 1..3=pile)."""
    if c in g["hands"][seat]:
        g["hands"][seat].remove(c)
        return 0
    for i, p in enumerate(g["piles"][seat]):
        if p and p[-1] == c:
            p.pop()
            return i + 1
    raise ValueError("card not held")


def apply_play(g: dict, seat: int, c: int) -> None:
    if c not in legal_moves(g, seat):
        raise ValueError("illegal card")
    source = _remove(g, seat, c)
    g["history"].append([seat, c, source])
    g["played"].append(c)

    if g["led"] is None:
        g["led"] = c
        return

    winner = seat if beats(g["led"], c, g["trump"]) else g["leader"]
    v = trick_value(g["trick"])
    g["pts"][winner] += v
    if v > 0:
        g["etricks"][winner] += 1
    g["trick"] += 1
    g["leader"] = winner
    g["led"] = None
    if g["trick"] >= NTRICKS:
        _finish(g)


# --- scoring ---------------------------------------------------------------


def contract_score(level: int, declarer_pts: int) -> tuple[int, int]:
    """(declarer score, defender score) for a settled contract.

    Make it and the declarer scores N squared. Fall short and the DEFENDER
    scores (N-1) plus 4 for every point the declarer finished below target.
    Only this scores -- the trick points are purely the yardstick.
    """
    if declarer_pts >= level:
        return level * level, 0
    return 0, (level - 1) + SHORT_PENALTY * (level - declarer_pts)


def _finish(g: dict) -> None:
    a = g["auction"]
    decl = a["declarer"]
    dpts = g["pts"][decl]
    if a["denom"] == NULL_DENOM:
        # Null: made iff the declarer won no +2 trick. Flat pay both ways --
        # it is not a level-N contract and the curves do not apply to it.
        made = g["etricks"][decl] == 0
        ds, fs = (NULL_MAKE, 0) if made else (0, NULL_SET)
        short = 0
    else:
        made = dpts >= a["level"]
        ds, fs = contract_score(a["level"], dpts)
        short = max(0, a["level"] - dpts)
    scores = [0, 0]
    scores[decl] = ds
    scores[1 - decl] = fs
    g["phase"] = "over"
    g["result"] = {
        "declarer": decl,
        "level": a["level"],
        "denom": a["denom"],
        "declarer_pts": dpts,
        "declarer_etricks": g["etricks"][decl],
        "made": made,
        "short": short,
        "scores": scores,
    }


def winner_seat(g: dict):
    """Seat with the higher score, or None on a tie."""
    if g["phase"] != "over":
        return None
    s = g["result"]["scores"]
    if s[0] == s[1]:
        return None
    return 0 if s[0] > s[1] else 1


# --- redaction -------------------------------------------------------------
#
# Lives here rather than in main.py so it is unit-testable against a real
# in-progress game. Any NEW field added to the game dict must be considered
# here explicitly -- "an honest client ignores it" is not security.

def _pile_view(g: dict, owner: int, viewer: int) -> list[dict]:
    """Piles as `viewer` may see them.

    Public: every top card, and the MIDDLE pile's bottom (dealt face-up).
    Hidden from everyone including the owner: the left/right bottoms, until
    the top above them is played.
    """
    out = []
    for i, p in enumerate(g["piles"][owner]):
        if not p:
            out.append({"n": 0, "top": None, "under": None})
            continue
        top = p[-1]
        under = None
        if len(p) == 2 and i == 1:
            under = p[0]  # middle pile bottom is face-up to both players
        out.append({"n": len(p), "top": top, "under": under})
    return out


def view_for(g: dict, seat: int) -> dict:
    """The game as one seat may see it. Never leaks a card they cannot know."""
    opp = 1 - seat
    over = g["phase"] == "over"
    decl = g["auction"]["declarer"]
    # The shown out-cards belong to the DECLARER's knowledge from the moment
    # the auction settles; the defender sees them only at the round-end reveal.
    sees_shown = over or (decl == seat and g["phase"] in ("swap", "play"))
    v = {
        "phase": g["phase"],
        "seats": g["seats"],
        "you": seat,
        "hand": sorted(g["hands"][seat]),
        "opp_hand_n": len(g["hands"][opp]),
        "piles": [_pile_view(g, 0, seat), _pile_view(g, 1, seat)],
        "auction": {
            "level": g["auction"]["level"],
            "denom": g["auction"]["denom"],
            "declarer": g["auction"]["declarer"],
            "to_act": g["auction"]["to_act"],
            "used": list(g["auction"]["used"]),
            "log": list(g["auction"]["log"]),
        },
        "trump": g["trump"],
        "trick": g["trick"],
        "trick_value": trick_value(g["trick"]) if g["phase"] == "play" else 0,
        "leader": g["leader"],
        "led": g["led"],
        "pts": list(g["pts"]),
        "etricks": list(g["etricks"]),
        "history": [list(h) for h in g["history"]],
        "result": g["result"],
        # The out-of-play cards stay secret until the round is done.
        "out": list(g["out"]) if over else None,
        "shown": list(g["shown"]) if sees_shown else None,
        # Whether a swap happened is public; which cards moved is not.
        "swapped": g["swapped"],
        "to_play": to_play(g) if g["phase"] == "play" else None,
        "legal": legal_moves(g, seat) if g["phase"] == "play" else [],
        "options": auction_options(g) if g["phase"] == "auction" else None,
        "swap": swap_options(g) if g["phase"] == "swap" and seat == decl else None,
    }
    return v


# --- turn / seat helpers (used by main.py) ---------------------------------


def is_over(g) -> bool:
    return bool(g) and g.get("phase") == "over"


def turn_seat(g) -> int | None:
    """Whichever seat must act next, in any phase."""
    if not g or g["phase"] == "over":
        return None
    if g["phase"] == "auction":
        return g["auction"]["to_act"]
    if g["phase"] == "swap":
        return g["auction"]["declarer"]
    return to_play(g)


def turn_pid(g):
    s = turn_seat(g)
    return None if s is None else g["seats"][s]


def seat_of(g, pid) -> int | None:
    try:
        return g["seats"].index(pid)
    except (ValueError, AttributeError, TypeError):
        return None


def player_view(g, pid):
    """Redacted view for a pid; spectators (pid not seated) see seat 0's public half."""
    if not g:
        return None
    s = seat_of(g, pid)
    if s is None:
        v = view_for(g, 0)
        # A spectator is not seat 0: strip everything private to that seat.
        v["hand"] = []
        v["you"] = None
        v["legal"] = []
        v["options"] = None
        v["swap"] = None
        if g["phase"] != "over":
            v["shown"] = None
        return v
    return view_for(g, s)


def apply_move(g, pid, move: dict) -> None:
    """Single entry point for main.py. Raises ValueError on anything illegal."""
    seat = seat_of(g, pid)
    if seat is None:
        raise ValueError("not a player in this game")
    kind = (move or {}).get("kind")
    if kind == "bid":
        apply_bid(g, seat, int(move["level"]), int(move["denom"]))
    elif kind == "pass":
        apply_pass(g, seat)
    elif kind == "swap":
        apply_swap(g, seat, move.get("take"), move.get("give"))
    elif kind == "play":
        apply_play(g, seat, int(move["card"]))
    else:
        raise ValueError("unknown move")
