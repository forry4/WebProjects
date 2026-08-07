"""Dissonance — the rules. Single source of truth; main.py delegates everything.

A two-player trick-taking game where taking tricks is not simply good.
Even-numbered tricks score +2 to whoever wins them, odd-numbered ones -1.
Six positive against seven negative, so both players' totals always sum to
exactly +5 and sweeping all thirteen tricks scores worse than taking the six
even ones. The game is about WHICH tricks you win.

Version 2 (the 2026-08-07 release, all four changes measured in
rust-cores/dissonance-core/CAMPAIGN.md): a 32-card deck with SIX cards out of
play (the hidden-information sweep's efficient point), ranked denominations
(C < D < H < S < NT < Null -- same-level overtakes in a higher rank), the Null
contract (win no +2 trick; fixed rung 6, pays 12 / set 10), and the declarer's
swap (shown 3 of the out-cards after the auction, may take one into hand).

Skat mode (2026-08-07) is a SECOND auction over that same card play, chosen per
room: you bid a bare NUMBER, and only after winning do you declare the game
(denomination + level) that satisfies it, optionally escalating against
yourself with Hand / Sharp / Open before the defender's Kontra. The deal, the
piles, the talon, follow-suit, the parity and the redaction machinery are
shared verbatim -- ``apply_move`` dispatches on ``g["mode"]`` and both paths
converge on ``_start_play``. See ``rust-cores/dissonance-core/SKAT_MODE.md``.

Ported from ``rust-cores/dissonance-core`` (``state.rs`` + ``auction.rs``),
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
# rust-cores/dissonance-core/CAMPAIGN.md.

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
#: NULL: "I won no +2 trick." A trick-COUNT condition, because the constant-sum
#: pool makes an inverse POINT contract identical to a normal one.
#:
#: IT IS NO LONGER A BID (2026-08-07). It used to be a single rung above
#: no-trump that you had to buy in the auction, and every measurement said the
#: same thing about that shape: at rung 3 it was overtaken away in 100% of
#: auctions, at rung 8 nobody could make it, raising the price SUPPRESSED it,
#: and all 18 contracts ever observed arrived by OVERTAKE rather than by anyone
#: opening it. A 33% gamble is only worth taking while losing is cheap, so as a
#: purchase it was either free or dead.
#:
#: So it is a CONSOLATION now, live under every contract at once: take no +2
#: trick as declarer and you score `NULL_MAKE` instead of being set. That makes
#: it what it always wanted to be -- the escape hatch from a contract going
#: wrong, available exactly when you are already losing, with no auction cost
#: and nothing to announce. `NULL_DENOM` survives only as the marker on
#: pre-change saved games; nothing can bid it.
NULL_DENOM = 5
NULL_MAKE = 12

#: Out-of-play cards the declarer is shown after the auction; they may swap
#: exactly one into hand (hand cards only -- the piles are the board, not the
#: holding).
N_OUT = 6
N_SHOWN = 3


# --- skat mode -------------------------------------------------------------
#
# A second way to arrive at a contract over the SAME card play. See
# rust-cores/dissonance-core/SKAT_MODE.md for the design argument; the one idea
# is that the shipped auction makes level N both the price and the task, so
# naming your bid tells the opponent what you intend to play. Skat mode splits
# them: you bid a NUMBER, and only after winning do you declare the game that
# satisfies it. Many games clear the same number, so the number cannot be read
# backwards into a denomination.
#
# Nothing below touches the deck, the piles, the talon, follow-suit or the
# parity. Only the phase machine between the deal and trick 1 changes.

MODES = ("classic", "skat")
DEFAULT_MODE = "classic"

#: value = base x level. Indexed by denomination (clubs..no-trump); the order
#: deliberately INVERTS the classic mode's C < D < H < S ranking -- diamonds
#: cheap, clubs dear -- matching real Skat and keeping the two modes' tables
#: from being mistaken for each other. Your ABILITY in a denomination is real
#: and varies by hand; only its PRICE is convention, and assigning one is what
#: manufactures an asymmetry the measured-symmetric suits do not otherwise have.
SKAT_BASE = [5, 2, 3, 4, 6]  # clubs, diamonds, hearts, spades, no-trump

#: What the Null consolation pays in skat mode. Flat, like classic's, and
#: deliberately NOT scaled by the announcements or by Kontra: Hand, Sharp and
#: Open are promises about the CONTRACT, and doubling a consolation would make
#: a defender's Kontra reward the very outcome it was betting against.
SKAT_NULL_VALUE = 20

#: Sharp promises the declared level plus this much.
#:
#: 2, not 3. The margin is measured against a scale where both players' totals
#: sum to +5 and one player's ceiling is 12, so every point of it is a large
#: ask: at 3, declaring level 4 Sharp promised 7 of a possible 12, i.e. holding
#: the opponent to -2. Sharp measured at 0% of contracts in every skatlab run
#: at that setting.
#:
#: The deeper reason it was mispriced is the additive multiplier. Hand and
#: Sharp each add exactly +1, but Hand costs one declined card swap and Sharp
#: costs points off a 12-point scale -- identical reward for wildly unequal
#: risk, which is most of why Hand ran at ~94% and Sharp at 0%. Lowering the
#: bar narrows that gap; it does not close it.
SHARP_BONUS = 2

#: The legal bid ladder: every product base x level.
#:
#: NOTE for anyone checking this against SKAT_MODE.md: that document's prose
#: enumerates "2,3,4,...,10,12,..." and counts 43 rungs. Both are wrong, and
#: the GENERATOR (base x level) is the rule -- 7 is not a multiple of any base,
#: so the real ladder is 36 rungs and has a single hole at 7 in the otherwise
#: dense 2..10 stretch. Derived here rather than typed out so the two can never
#: disagree.
SKAT_VALUES = sorted(
    {SKAT_BASE[d] * lvl for d in range(NOTRUMP + 1)
     for lvl in range(MIN_LEVEL, MAX_LEVEL + 1)}
)


def skat_min_level(denom: int, value: int) -> int:
    """Lowest level in `denom` whose value clears `value` (ceiling division)."""
    base = SKAT_BASE[denom]
    return max(MIN_LEVEL, -(-value // base))


def skat_declarable(value: int) -> list[dict]:
    """Every declaration that satisfies a winning bid of `value`.

    Because the level is the declarer's free choice from 1..12 and no-trump at
    12 is the ladder's top rung, EVERY legal bid is declarable -- Skat's
    "overbid loses at once" rule has nothing to fire on here. The punishment
    for stretching is structural instead: a big number forces you up the level
    ladder into a contract you cannot make.
    """
    out = []
    for d in range(NOTRUMP + 1):
        lo = skat_min_level(d, value)
        if lo <= MAX_LEVEL:
            out.append({"denom": d, "base": SKAT_BASE[d], "min_level": lo})
    return out


def skat_value_of(denom: int, level: int) -> int:
    return SKAT_BASE[denom] * level


def skat_multiplier(hand: bool, sharp: bool, open_: bool) -> int:
    """Announcements stack Skat-style by ADDITION, never multiplication.

    Base game x1; Hand, Sharp and Open each add one. Hand+Sharp = x3,
    Hand+Sharp+Open = x4, Sharp alone = x2.

    Why a multiplier rather than a flat bonus: the classic-mode campaign
    measured flat bonuses distorting the bottom of the ladder (a flat +1 RAISED
    the floor cluster, being proportionally biggest on the smallest contracts).
    A multiplier prices confidence identically at every level.
    """
    return 1 + int(bool(hand)) + int(bool(sharp)) + int(bool(open_))


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


def new_game(seats, rng=None, opener: int = 0, mode: str = DEFAULT_MODE) -> dict:
    """Deal a round. `seats` is [pid0, pid1]; `opener` names the first bidder.

    `mode` selects which auction runs on top of the identical deal: "classic"
    (level + denomination, the shipped v2 auction) or "skat" (a numeric ladder
    followed by a declaration). Everything from `_start_play` onwards is shared.
    """
    rng = rng or random.Random()
    mode = mode if mode in MODES else DEFAULT_MODE
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

    g = {
        "v": VERSION,
        "mode": mode,
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
        #
        # `level`/`denom` mean different things per mode and that is deliberate:
        # in classic they are the BID, in skat they are the DECLARATION and stay
        # unset (0 / -1) for the whole auction. Everything downstream --
        # `_start_play`'s trump, the result row, the lobby's contract line --
        # then reads the same two keys in both modes.
        "auction": {
            "level": 0,
            "denom": -1,
            "declarer": -1,
            "used": [0, 0],
            "to_act": opener,
            "log": [],
            # skat only: the standing numeric bid, and how many times the
            # auction has been passed out at zero.
            "value": 0,
            "passes": 0,
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
    if mode == "skat":
        # Whether the declarer LOOKED at the talon at all. Distinct from
        # `swapped`: looking and standing pat is still not a Hand game.
        g["looked"] = False
        g["redeals"] = 0
        g["contract"] = _new_contract()
    return g


def _new_contract() -> dict:
    """The skat declaration. Entirely public once made -- no redaction needed."""
    return {
        "value": 0,      # declared game value: base x level, or 20 for Null
        "hand": False,   # played without looking at the talon
        "sharp": False,  # promises level + SHARP_BONUS
        "open": False,   # declarer's hand face up from trick 1
        "kontra": False,
        "re": False,
        "mult": 1,       # from the announcements only
    }


def mode_of(g: dict) -> str:
    """A save written before skat mode existed has no `mode` key."""
    m = (g or {}).get("mode", DEFAULT_MODE)
    return m if m in MODES else DEFAULT_MODE


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
        return {"bids": [], "values": [], "standing": 0, "may_pass": False}
    if mode_of(g) == "skat":
        # Ascending numeric, alternating; either player may pass. Passing when
        # nothing stands is a genuine "you take it" that hands the opponent the
        # talon and the lead at THEIR price -- which is why an open pass is safe
        # here and was not in classic mode, where the opener is forced to name a
        # contract and passing would be strictly better than a bad one.
        return {
            "bids": [],
            "values": [v for v in SKAT_VALUES if v > a["value"]],
            "standing": a["value"],
            "may_pass": True,
        }
    me = a["to_act"]
    free = [d for d in range(NOTRUMP + 1) if not (a["used"][me] >> d) & 1]
    bids: list[list[int]] = []
    if a["level"] == 0:
        # The opener must bid; passing out is not offered.
        for d in free:
            bids.extend([lvl, d] for lvl in range(MIN_LEVEL, MAX_LEVEL + 1))
        return {"bids": bids, "may_pass": False}
    # Ranked denominations: an overtake stands at the SAME level in a
    # higher-ranked denomination, or raises by up to MAX_RAISE in any unused one.
    lo, hi = a["level"], min(MAX_LEVEL, a["level"] + MAX_RAISE)
    for d in free:
        for lvl in range(lo, hi + 1):
            if lvl == a["level"] and d <= a["denom"]:
                continue  # same level: only a higher-ranked denomination outranks
            bids.append([lvl, d])
    return {"bids": bids, "may_pass": True}


def can_bid(g: dict, seat: int, level: int, denom: int) -> tuple[bool, str]:
    if g["phase"] != "auction":
        return False, "not bidding"
    if mode_of(g) == "skat":
        return False, "this game bids a number, not a contract"
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


def apply_skat_bid(g: dict, seat: int, value: int) -> None:
    """Name a number strictly above the standing bid. Skat mode only."""
    if g["phase"] != "auction" or mode_of(g) != "skat":
        raise ValueError("not bidding a number")
    a = g["auction"]
    if seat != a["to_act"]:
        raise ValueError("not your turn")
    value = int(value)
    if value not in SKAT_VALUES:
        raise ValueError("not a value on the ladder")
    if value <= a["value"]:
        raise ValueError("that does not outbid the standing number")
    a["value"] = value
    a["declarer"] = seat
    a["to_act"] = 1 - seat
    a["log"].append({"seat": seat, "value": value})


def apply_pass(g: dict, seat: int) -> None:
    if g["phase"] != "auction":
        raise ValueError("not bidding")
    a = g["auction"]
    if seat != a["to_act"]:
        raise ValueError("not your turn")
    if mode_of(g) == "skat":
        a["log"].append({"seat": seat, "pass": True})
        if a["value"] == 0:
            # Nothing stands: this is a genuine "you take it", and both players
            # declining throws the hand in.
            a["passes"] += 1
            if a["passes"] >= 2:
                _redeal(g)
            else:
                a["to_act"] = 1 - seat
            return
        # A bid stands, so the last bidder has bought the declaration.
        g["phase"] = "talon"
        return
    if a["level"] == 0:
        raise ValueError("the opener must bid")
    a["log"].append({"seat": seat, "pass": True})
    # The declarer now sees `shown` and decides on the swap before play.
    g["phase"] = "swap"


def _redeal(g: dict) -> None:
    """Throw the hand in and deal again, in place.

    Mutating `g` rather than returning a fresh dict is load-bearing: the room
    server, the bot scheduler and every open socket all hold this exact object.
    The opener alternates so a player cannot pass out of a bad seat for free.
    """
    n = g.get("redeals", 0) + 1
    fresh = new_game(list(g["seats"]), None, opener=1 - g["opener"], mode="skat")
    fresh["redeals"] = n
    g.clear()
    g.update(fresh)


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
    skat = mode_of(g) == "skat"
    if g["phase"] != ("talon" if skat else "swap"):
        raise ValueError("not the swap phase")
    if skat and not g.get("looked"):
        raise ValueError("look at the talon first")
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
    if skat:
        # In skat mode the talon resolves BEFORE the game is named -- the whole
        # point of taking it is to see whether it fixes a denomination for you.
        g["phase"] = "declare"
    else:
        _start_play(g)


# --- skat: talon, declaration, announcements, Kontra ------------------------
#
# This is where the mode's interest lives. The auction ends with a number; the
# declarer then escalates AGAINST THEMSELVES (Hand / Sharp / Open) with the
# opponent already out of the loop, and the defender gets the last word
# (Kontra) at the moment they finally learn what game they are defending. A
# two-player auction otherwise has neither of those pressures.


def _skat_declarer(g: dict) -> int:
    return g["auction"]["declarer"]


def talon_options(g: dict) -> dict:
    """What the declarer may do in the talon phase.

    `shown` is empty until they choose to LOOK -- declining to look is what
    Hand means, so the cards cannot be handed over before the choice is made.
    """
    if g["phase"] != "talon":
        return {"looked": False, "shown": [], "hand": []}
    decl = _skat_declarer(g)
    return {
        "looked": bool(g.get("looked")),
        "shown": list(g["shown"]) if g.get("looked") else [],
        "hand": sorted(g["hands"][decl]),
    }


def apply_look(g: dict, seat: int) -> None:
    """Turn the three talon cards face up -- and give up the Hand multiplier."""
    if g["phase"] != "talon":
        raise ValueError("not the talon phase")
    if seat != _skat_declarer(g):
        raise ValueError("only the declarer sees the talon")
    if g.get("looked"):
        raise ValueError("already looking")
    g["looked"] = True


def apply_hand(g: dict, seat: int) -> None:
    """Decline to look at all: Hand, worth +1 to the multiplier."""
    if g["phase"] != "talon":
        raise ValueError("not the talon phase")
    if seat != _skat_declarer(g):
        raise ValueError("only the declarer plays Hand")
    if g.get("looked"):
        raise ValueError("you have already seen the talon")
    g["contract"]["hand"] = True
    g["swapped"] = False
    g["phase"] = "declare"


def declare_options(g: dict) -> dict:
    """The declarations that satisfy the winning bid, for the client to render."""
    if g["phase"] != "declare":
        return {"bid": 0, "denoms": []}
    ct = g["contract"]
    bid = g["auction"]["value"]
    return {
        "bid": bid,
        "denoms": skat_declarable(bid),
        "max_level": MAX_LEVEL,
        "sharp_bonus": SHARP_BONUS,
        "hand": ct["hand"],
    }


def apply_declare(g: dict, seat: int, denom: int, level: int,
                  sharp: bool = False, open_: bool = False) -> None:
    """Name the game, then optionally raise the stakes against yourself."""
    if g["phase"] != "declare":
        raise ValueError("not the declaration phase")
    if seat != _skat_declarer(g):
        raise ValueError("only the declarer declares")
    a, ct = g["auction"], g["contract"]
    denom, level = int(denom), int(level)
    sharp, open_ = bool(sharp), bool(open_)
    bid = a["value"]

    if not (0 <= denom <= NOTRUMP):
        raise ValueError("no such denomination")
    if not (MIN_LEVEL <= level <= MAX_LEVEL):
        raise ValueError("level out of range")
    value = skat_value_of(denom, level)
    if value < bid:
        raise ValueError(
            f"{SKAT_BASE[denom]} x {level} = {value} does not reach your bid of {bid}")
    if open_ and not sharp:
        raise ValueError("Open is played on top of Sharp")

    a["level"] = level
    a["denom"] = denom
    ct["value"] = value
    ct["sharp"] = sharp
    ct["open"] = open_
    ct["mult"] = skat_multiplier(ct["hand"], sharp, open_)
    g["phase"] = "kontra"


def apply_kontra(g: dict, seat: int, on: bool) -> None:
    """The defender's reply, priced at maximum information asymmetry."""
    if g["phase"] != "kontra":
        raise ValueError("not the Kontra phase")
    if seat == _skat_declarer(g):
        raise ValueError("only the defender may Kontra")
    if not on:
        _start_play(g)
        return
    g["contract"]["kontra"] = True
    g["phase"] = "re"


def apply_re(g: dict, seat: int, on: bool) -> None:
    if g["phase"] != "re":
        raise ValueError("not the Re phase")
    if seat != _skat_declarer(g):
        raise ValueError("only the declarer may Re")
    g["contract"]["re"] = bool(on)
    _start_play(g)


def skat_doubling(ct: dict) -> int:
    """Kontra doubles everything whichever way it falls; Re doubles it again."""
    if ct.get("re"):
        return 4
    return 2 if ct.get("kontra") else 1


def skat_target(g: dict) -> int:
    """Trick points the declarer promised, Sharp included."""
    return g["auction"]["level"] + (SHARP_BONUS if g["contract"]["sharp"] else 0)


def _start_play(g: dict) -> None:
    a = g["auction"]
    g["phase"] = "play"
    # `NULL_DENOM` is unreachable from the auction now; the branch survives so a
    # game SAVED before Null stopped being a bid still starts at no trump.
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
    if g["trick"] >= NTRICKS or _score_is_settled(g):
        _finish(g)


def _score_is_settled(g: dict) -> bool:
    """Can the remaining tricks still change the SCORE? If not, stop here.

    The bar is the score, not the outcome, and the difference is the whole
    reason only one direction of "decided" ends a round early:

    * **Cannot fail.** If the declarer clears the target even after losing every
      remaining +2 trick and being handed every remaining -1, the contract is
      made -- and a made contract pays a flat N squared (or the skat stake),
      which does not move with the final total. Settled.
    * **Cannot make.** Being mathematically set does NOT settle the score: the
      defender is paid `(N-1) + 4 x shortfall`, and every remaining trick still
      moves the shortfall. Holding a busted declarer down is a real contest --
      arguably the most interesting part of a lost hand -- so it plays on.
    Null gets NO early end of its own. It used to -- as a bid it was decided the
    moment the declarer took a scoring trick -- but as a consolation it is
    settled early only when no +2 trick remains, which by the parity of the
    trick values can only ever save the thirteenth. Not worth a branch, and a
    branch that fires on the last trick is one the Rust parity fixtures (which
    replay all thirteen) would have to be taught about.

    Ending here is score-identical to playing on. What it is NOT is
    pool-identical: `pts` sums to POOL only over a COMPLETED round, so anything
    asserting that invariant has to say "a round that ran to thirteen tricks".
    """
    decl = g["auction"]["declarer"]
    if decl is None or decl < 0:
        return False
    neg_left = sum(1 for t in range(g["trick"], NTRICKS) if trick_value(t) < 0)
    target = skat_target(g) if mode_of(g) == "skat" else g["auction"]["level"]
    # The declarer's floor from here: they win no more +2 tricks and are forced
    # to take every remaining -1.
    return g["pts"][decl] - neg_left >= target


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


def _finish_skat(g: dict) -> None:
    """Declared value x multiplier, to whichever side was right.

    Make everything you announced and the declarer takes it; miss ANY part of
    it -- the level, or the Sharp margin on top -- and the defender takes the
    same number, plus the classic mode's shortfall term so deep failures still
    hurt more than near misses.
    """
    a, ct = g["auction"], g["contract"]
    decl = a["declarer"]
    dpts = g["pts"][decl]
    stake = ct["value"] * ct["mult"] * skat_doubling(ct)
    target = skat_target(g)
    null = g["etricks"][decl] == 0
    made = (not null) and dpts >= target
    short = 0 if (null or made) else target - dpts
    scores = [0, 0]
    if null:
        # The consolation. A declarer who took no +2 trick cannot have reached
        # any target (only +2 tricks add points), so this always REPLACES a
        # set -- it is never a bonus on top of a made contract.
        scores[decl] = SKAT_NULL_VALUE
    else:
        scores[decl if made else 1 - decl] = (
            stake if made else stake + SHORT_PENALTY * short)
    g["phase"] = "over"
    g["result"] = {
        # A settled round can stop short of thirteen tricks; the UI says so
        # rather than leaving a half-played board looking like a bug.
        "ended_early": g["trick"] < NTRICKS,
        "mode": "skat",
        "declarer": decl,
        "bid": a["value"],
        "level": a["level"],
        "denom": a["denom"],
        # The base price of the declared denomination. It rides the result so
        # the review can show base x level = value -- the one step of the skat
        # arithmetic that used to be invisible, which left a made contract
        # printing a bare number where classic prints "3 x 3 = 9".
        "base": SKAT_BASE[a["denom"]] if 0 <= a["denom"] <= NOTRUMP else 0,
        "null": null,
        "null_value": SKAT_NULL_VALUE,
        "value": ct["value"],
        "mult": ct["mult"],
        "doubling": skat_doubling(ct),
        "stake": stake,
        "hand": ct["hand"], "sharp": ct["sharp"], "open": ct["open"],
        "kontra": ct["kontra"], "re": ct["re"],
        "target": target,
        "declarer_pts": dpts,
        "declarer_etricks": g["etricks"][decl],
        "made": made,
        "short": short,
        "scores": scores,
    }


def _finish(g: dict) -> None:
    if mode_of(g) == "skat":
        _finish_skat(g)
        return
    a = g["auction"]
    decl = a["declarer"]
    dpts = g["pts"][decl]
    # NULL IS CHECKED FIRST AND WINS. Taking no +2 trick is only reachable with
    # a non-positive total, so it can never coincide with a made contract -- it
    # always replaces being set, which is exactly the escape hatch it is for.
    null = g["etricks"][decl] == 0
    made = (not null) and dpts >= a["level"]
    scores = [0, 0]
    if null:
        scores[decl] = NULL_MAKE
        short = 0
    else:
        ds, fs = contract_score(a["level"], dpts)
        scores[decl], scores[1 - decl] = ds, fs
        short = max(0, a["level"] - dpts)
    g["phase"] = "over"
    g["result"] = {
        # A settled round can stop short of thirteen tricks; the UI says so
        # rather than leaving a half-played board looking like a bug.
        "ended_early": g["trick"] < NTRICKS,
        "mode": "classic",
        "declarer": decl,
        "level": a["level"],
        "denom": a["denom"],
        "null": null,
        "null_value": NULL_MAKE,
        "declarer_pts": dpts,
        "declarer_etricks": g["etricks"][decl],
        "made": made,
        "short": short,
        "scores": scores,
    }


def forfeit_value(g: dict) -> int:
    """What walking out of a live game hands the opponent.

    Whatever the contract was worth at that moment, in that mode's own
    currency, floored at 1 so abandoning before anything is agreed still costs.
    """
    if mode_of(g) == "skat":
        ct = g.get("contract") or {}
        # Before the declaration there is no game value; the standing bid is
        # the closest honest number.
        stake = (ct.get("value") or g["auction"].get("value") or 0)
        return max(1, stake * (ct.get("mult") or 1) * skat_doubling(ct))
    return max(1, g["auction"]["level"] ** 2)


def abandon_result(g: dict, seat: int) -> dict:
    """The result row for `seat` walking out of a live game.

    It has to satisfy the SAME readers as a played-out result -- the lobby's
    history row and the result panel -- or the round ends narrating a contract
    nobody ever agreed to. Skat mode makes that a live risk rather than a
    theoretical one: both players may pass, so a room can be abandoned with
    `declarer` still -1 and no declaration at all, and the skat result panel
    reads six keys that only `_finish_skat` would otherwise set.
    """
    a = g["auction"]
    decl = a["declarer"]
    scores = [0, 0]
    scores[1 - seat] = forfeit_value(g)
    res = {
        "mode": mode_of(g),
        "abandoned_by": seat,
        "declarer": decl,
        "level": a["level"],
        "denom": a["denom"],
        "declarer_pts": g["pts"][decl] if decl >= 0 else 0,
        "declarer_etricks": g["etricks"][decl] if decl >= 0 else 0,
        "made": False,
        "short": 0,
        "scores": scores,
    }
    if mode_of(g) == "skat":
        ct = g.get("contract") or {}
        res.update({
            "bid": a.get("value", 0),
            "value": ct.get("value", 0),
            "mult": ct.get("mult", 1),
            "doubling": skat_doubling(ct),
            "stake": scores[1 - seat],
            "target": skat_target(g) if a["level"] else 0,
            "hand": ct.get("hand", False),
            "sharp": ct.get("sharp", False),
            "open": ct.get("open", False),
            "kontra": ct.get("kontra", False),
            "re": ct.get("re", False),
        })
    return res


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
    skat = mode_of(g) == "skat"
    decl = g["auction"]["declarer"]
    ct = g.get("contract") or {}
    # The shown out-cards belong to the DECLARER's knowledge from the moment
    # the auction settles; the defender sees them only at the round-end reveal.
    # In skat mode the declarer earns them by CHOOSING to look -- a Hand game
    # never sees them either, or Hand would be free information.
    sees_shown = over or (decl == seat and (
        bool(g.get("looked")) if skat
        else g["phase"] in ("swap", "play")))
    # Open: the declarer's hand is face up from trick 1. This is the only path
    # by which one seat legitimately sees the other's cards, and it is bought
    # with a multiplier.
    open_now = bool(ct.get("open")) and g["phase"] in ("play", "over")
    v = {
        "mode": mode_of(g),
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
            # The bid ladder needs no redaction at all: a number is a price,
            # and it cannot be read backwards into a denomination.
            "value": g["auction"].get("value", 0),
        },
        # Public from the moment it is made -- and only made after the auction.
        "contract": dict(ct) if skat else None,
        "looked": bool(g.get("looked")) if skat else None,
        "redeals": g.get("redeals", 0) if skat else 0,
        # Face-up only under an Open announcement; None every other time.
        "opp_hand": sorted(g["hands"][opp]) if (open_now and opp == decl) else None,
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
        # Skat's post-auction prompts, each to exactly one seat.
        "talon": talon_options(g) if g["phase"] == "talon" and seat == decl else None,
        "declare": declare_options(g) if g["phase"] == "declare" and seat == decl else None,
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
    if g["phase"] in ("swap", "talon", "declare", "re"):
        return g["auction"]["declarer"]
    if g["phase"] == "kontra":
        return 1 - g["auction"]["declarer"]
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
        v["talon"] = None
        v["declare"] = None
        if g["phase"] != "over":
            v["shown"] = None
        # An Open hand is face up at the table, so a spectator keeps it -- but
        # it is the DECLARER's, which may be the seat this view was built from.
        ct = g.get("contract") or {}
        v["opp_hand"] = (sorted(g["hands"][g["auction"]["declarer"]])
                         if ct.get("open") and g["phase"] in ("play", "over")
                         else None)
        return v
    return view_for(g, s)


def apply_move(g, pid, move: dict) -> None:
    """Single entry point for main.py. Raises ValueError on anything illegal."""
    seat = seat_of(g, pid)
    if seat is None:
        raise ValueError("not a player in this game")
    kind = (move or {}).get("kind")
    if kind == "bid":
        if mode_of(g) == "skat":
            apply_skat_bid(g, seat, int(move["value"]))
        else:
            apply_bid(g, seat, int(move["level"]), int(move["denom"]))
    elif kind == "pass":
        apply_pass(g, seat)
    elif kind == "swap":
        apply_swap(g, seat, move.get("take"), move.get("give"))
    elif kind == "look":
        apply_look(g, seat)
    elif kind == "hand":
        apply_hand(g, seat)
    elif kind == "declare":
        apply_declare(g, seat, int(move["denom"]), int(move.get("level") or 0),
                      move.get("sharp"), move.get("open"))
    elif kind == "kontra":
        apply_kontra(g, seat, bool(move.get("on")))
    elif kind == "re":
        apply_re(g, seat, bool(move.get("on")))
    elif kind == "play":
        apply_play(g, seat, int(move["card"]))
    else:
        raise ValueError("unknown move")
