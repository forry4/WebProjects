"""Dissonance bots — the Easy tier, server-side.

The card-play policy is a direct port of ``policy.rs`` from the Rust core: one
trick deep, take the +2 tricks as cheaply as possible and shed the -1 tricks as
expensively as possible. It is the floor the searching bot has to clear: a
CRN-paired arena on the v2 rules puts ``pimc:8`` **+1.10 +/- 0.10 trick points
per round** ahead of it, on a pool of 5. (Skat mode scores CAPTURED CARDS since
2026-08-09 -- its branch of the policy reads the cards, its bidding runs a
card-currency curve and level map, and that arena figure describes the parity
modes only.)

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
    """Whether the mover wants THIS trick. PARITY MODES ONLY -- in skat's card
    scoring a trick has no value until the cards are in it, so `policy_score`
    reads the cards instead of calling this.

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
    return E.trick_value_in(g, g["trick"]) > 0


def policy_score(g: dict, c: int, seat: int | None = None) -> float:
    """Higher is more attractive for the player to move.

    CARD SCORING (skat, 2026-08-09) has its own branch, because "do I want this
    trick" stops being a property of the trick number: following, the trick's
    value IS the two cards (led + this candidate), so the score is the exact
    one-trick delta -- win it and bank the sum, duck and hand the sum over --
    with a small tie-break toward spending the lower rank either way. Leading,
    the reply is unknown; lead LOW (a low card usually loses the trick, and
    mandatory follow-suit makes the opponent capture it) and keep the +2 cards
    back rather than leading them into the opponent's ducking range. Kept in
    the same rough 0..4 range as the parity branch so `policy_probs`'
    temperature means the same thing in both currencies.
    """
    if seat is None:
        seat = E.to_play(g)
    r = E.rank(c) / (E.NRANK - 1.0)
    led = g["led"]
    trump = g["trump"]
    if E.uses_card_points(E.mode_of(g)):
        if led is not None:
            tv = E.card_points(led) + E.card_points(c)
            w = E.beats(led, c, trump)
            return 2.0 + 0.5 * (tv if w else -tv) - 0.05 * r
        trumpish = 1.0 if E.esuit(c, trump) == E.trump_class(trump) else 0.0
        return 1.0 + (1.0 - r) - 0.4 * max(0, E.card_points(c)) - trumpish
    want_win = _want_win(g, seat)
    if led is not None:
        w = E.beats(led, c, trump)
        if want_win:
            return 3.0 - r if w else 1.0 - r
        return 0.6 - r if w else 3.0 + r
    # Grand counts here too: its trump class is a real one, it is just made
    # of the four tens rather than a suit.
    trumpish = 1.0 if E.esuit(c, trump) == E.trump_class(trump) else 0.0
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


#: CARD-SCORING rank worth (skat mode since 2026-09 -- the mode scores captured
#: cards, 9/10/J/Q +2 and 7/8/K/A -1, so this curve answers a different
#: question than `_RANK_VALUE`: not "does this rank win tricks" but "how many
#: card points does holding it tend to bring home". The +2 ranks carry most of
#: it (a card you hold is a card you decide the timing of); the aces and kings
#: keep real worth as CONTROL (they decide who wins the tricks the +2s fall
#: into) despite being -1 themselves; the 7/8 are the ducking material that
#: refuses the -2 tricks. Shallow on purpose, like `_RANK_VALUE` -- the LEVEL
#: MAP below is what was calibrated, so only the curve's shape matters here.
_SKAT_RANK_VALUE = [0.6, 0.5, 0.8, 0.9, 1.1, 1.3, 1.0, 1.5]

_SKAT_UNKNOWN_RANK_VALUE = sum(_SKAT_RANK_VALUE) / len(_SKAT_RANK_VALUE)


def hand_strength(g: dict, seat: int, denom: int) -> float:
    """Cheap estimate of the points this seat could take in `denom`.

    ONLY THE CARDS THE SEAT MAY ACTUALLY NAME. This used to read every pile
    bottom it owned, and two of the three are face down to their owner too -- so
    the bot bid a hand it could see two cards more of than the player across the
    table could see of theirs. Not opponent knowledge, so it never played a card
    it could not have played; it simply valued its own hand with information the
    rules do not give it, in both auctions and in the talon swap.

    The rank curve is per CURRENCY: the parity modes rate ranks as
    trick-winners (`_RANK_VALUE`); card scoring rates them as points brought
    home (`_SKAT_RANK_VALUE`). Same shape, same unknown-card treatment, and
    `_level_for`'s per-mode maps absorb the different scales.
    """
    cards = E.playable(g, seat) + [
        p[0] for i, p in enumerate(g["piles"][seat]) if len(p) == 2 and i == 1]
    unknown = sum(1 for i, p in enumerate(g["piles"][seat]) if len(p) == 2 and i != 1)
    if E.uses_card_points(E.mode_of(g)):
        curve, mean = _SKAT_RANK_VALUE, _SKAT_UNKNOWN_RANK_VALUE
    else:
        curve, mean = _RANK_VALUE, _UNKNOWN_RANK_VALUE
    total = sum(curve[E.rank(c)] for c in cards)
    total += unknown * mean
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


#: Minor mode's strength -> level map, CALIBRATED BY SELF-PLAY (2026-08-09,
#: tools/minor_calibration.py). A minor level is far more than "half a classic
#: level": each even trick swung to the declarer moves the pts DIFFERENCE by 2
#: rather than classic's 4, so margins accumulate at half speed against the
#: same target spacing -- measured, a p90 hand overtaking to level 2 made it
#: only ~12-18% of the time, which is negative EV against every set price
#: tried. So the map is deliberately COMPRESSED against the strength scale
#: (best-denomination strength runs median 10.7 / p90 13.8 / p99 16.4): level
#: 2 fires around p96 and the rungs above 3 are effectively sacrifice space,
#: the same role classic's unused 7..12 play. The settled distribution this
#: yields is ~87% at level 1 -- an honest floor for a mode whose par is
#: NEGATIVE (-0.5), where even the floor contract is a real ask (~45% made
#: under greedy play; the searching tiers do better, and the Null consolation
#: is the declarer's escape).
_MINOR_LEVEL_NEEDS = ((6, 25.0), (5, 22.5), (4, 20.0), (3, 17.5), (2, 15.0))

_CLASSIC_LEVEL_NEEDS = ((6, 15.0), (5, 12.5), (4, 10.5), (3, 8.5), (2, 6.5))

#: CARD SCORING's strength -> level map (skat mode, 2026-08-09), CALIBRATED BY
#: SELF-PLAY (tools/skat_calibration.py -- see that file's header for the run).
#: The scale is nothing like classic's: the pool is ~13 rather than 5, the
#: declarer (lead + talon + free choice of game) banks well above half of it,
#: so mid levels are routine where classic's were a stretch. The map runs off
#: `_SKAT_RANK_VALUE` totals (median best-denomination strength ~11.5) and is
#: deliberately looser at the bottom: a level under the floor here is a bid
#: wasted, not a contract saved.
_SKAT_LEVEL_NEEDS = ((9, 18.6), (8, 17.2), (7, 16.2), (6, 15.5), (5, 14.9),
                     (4, 14.3), (3, 13.7), (2, 13.0))


def _level_for(strength: float, mode: str = "classic") -> int:
    """Map a strength estimate onto a contract level.

    `mode` picks the ladder scale: minor's rungs are dearer per level because
    even tricks pay half, and skat's run on the card-scoring currency (pool
    ~13, so the whole map sits higher and reaches deeper into the ladder).
    """
    if mode == "skat":
        needs = _SKAT_LEVEL_NEEDS
    elif mode == "minor":
        needs = _MINOR_LEVEL_NEEDS
    else:
        needs = _CLASSIC_LEVEL_NEEDS
    for lvl, need in needs:
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
    want = _level_for(hand_strength(g, seat, best_d), E.mode_of(g))
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

#: A defender only doubles a promise this greedy... Re-anchored for card
#: scoring (2026-08-09): the target is card points on a ~13-point pool, where a
#: mid hand banks 6-8, so "greedy" starts around 9 rather than the parity
#: game's 8-of-12 ceiling. Still guesses, not measurements, as before.
_KONTRA_TARGET = 9
#: ...and only when its own holding in the declared denomination backs the read
#: (a `_SKAT_RANK_VALUE` total; median best-denomination strength is ~11.5).
_KONTRA_STRENGTH = 12.5


def skat_ceiling(g: dict, seat: int) -> int:
    """The largest number this hand can afford to be held to."""
    best = 0
    for d in E.SKAT_DENOMS:
        want = _level_for(hand_strength(g, seat, d), "skat")
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
        stretch = opt["min_level"] - _level_for(strength, "skat")
        key = (max(0, stretch), -strength)
        if best_key is None or key < best_key:
            best, best_key = opt, key
    return {"denom": best["denom"], "level": best["min_level"],
            "sharp": False, "open": False}


#: THE SERVER TIER NEVER DOUBLES, and that is a measured decision rather than a
#: gap. Doubling wins N when the contract goes down and costs N^2 when it does
#: not, so break-even climbs 50/67/75/80/83/86% across levels 1-6 while
#: contracts bid NORMALLY fail only 4/9/18/24/37/56% (2000 rounds of self-play).
#: Against ordinary bidding no level is a profitable Double.
#:
#: BUT THE MECHANIC IS NOT FOR ORDINARY BIDDING. It is for the SACRIFICE: a
#: player about to concede a big made contract overtakes at a level they cannot
#: reach, purely to deny it -- 6C over 5S because 25 points is worse than being
#: set. Forced sacrifices measure completely differently: 78% set at level 6
#: against 56% for a genuine one. (EV -0.13 rather than -12.60 -- break-even, and
#: it was +0.97 before the set base moved N-1 -> N; see the note in CLAUDE.md.)
#:
#: THIS TIER STILL CANNOT DO IT, because it cannot TELL the two apart. The
#: obvious signal is the defender's own holding, and it does not work: within
#: normal play the set rate is 38-43% at every strength gate, and within
#: sacrifices 78% at every gate. A gate at strength 11 fires on 58% of
#: sacrifices but also 6% of genuine high contracts, which only pays if
#: sacrifices are about half as common as real contracts. They are not.
#:
#: What separates them is whether the contract is REACHABLE, which is a solve,
#: not a rank sum. So the HARD tier does this one: the server hands it both
#: branches priced (`auction_payoff_options`) and it compares them against its
#: own double-dummy solve, so it doubles exactly when the contract is dead.
def choose_double(g: dict, seat: int) -> bool:
    """Classic's Double, from the defender's seat. Measured: always decline."""
    return False


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


#: The CLASSIC swap policy's weights -- FITTED, not styled (2026-08-08).
#:
#: The policy this replaced took the highest card shown and threw the lowest
#: card held (its 3x7 "search" was separable, so that is all it could ever do),
#: and it measured **-0.477 +- 0.226 score/round against standing pat** over
#: 3000 paired deals, firing in 64% of rounds. Backwards by construction in a
#: game where 7 of 13 tricks are penalties and low cards are the tool for
#: forcing them onto the opponent -- the card play's own "lead low" branch
#: depends on exactly the cards it discarded.
#:
#: These weights are a ridge fit on 300 ORACLE-labelled decisions
#: (`tools/swaplab.py`: every candidate exchange resolved by an exact
#: double-dummy solve of the real deal), features restricted to what the seat
#: may legally see. The oracle's own take-histogram is U-SHAPED -- it takes 7s
#: almost as often as Aces -- and the fit found the same shape on its own:
#: rank weights below run +0.92 for a 7, negative through the middle, +2.05
#: for an Ace. Held-out (a second 300 decisions): regret vs the oracle 1.92
#: against the old policy's 2.50. Under greedy playout, paired over 3000
#: deals: **+1.500 +- 0.208 vs standing pat, +1.976 +- 0.194 vs the old
#: policy** -- a gain under BOTH resolutions, which matters because the swap's
#: value depends on who plays the cards afterwards (the old policy was +1.6 vs
#: pat under exact play and -0.48 under greedy).
#:
#: Indexed by rank (7 8 9 10 J Q K A). `_SWAP_GIVE_W`'s Ace entry is a bare
#: 0.0 because an Ace was never the best discard anywhere in the 6600
#: labelled candidates -- the weight is unlearnable there; the entry only
#: keeps the row indexable.
_SWAP_TAKE_W = (0.92, -1.36, -1.16, -1.33, -0.44, -0.57, 0.99, 2.05)
_SWAP_GIVE_W = (0.32, 0.10, 1.51, 0.88, 0.95, -0.10, -1.04, 0.0)
_SWAP_TAKE_TRUMP = 1.57
_SWAP_GIVE_TRUMP = -1.24
#: Discarding a suit's LAST card (a void beats a singleton, but both help --
#: shape is real value the old rank-only policy could not see).
_SWAP_VOID = 1.47
_SWAP_SINGLETON = 0.67
#: Lengthening the take-card's suit, per card of it already held / 7.
#:
#: There is deliberately NO level-scaled bar on top of these. The ridge fit
#: produced one (-1.89 x level/6, the oracle swaps less at high stakes), but a
#: per-decision constant cancels out of the argmax between swaps and, applied
#: as an explicit stand-pat threshold, it measured NO better on held-out
#: decisions (regret 2.03 vs 1.92 without). The policy the arenas actually
#: measured is this one: threshold zero, argmax over the score below.
_SWAP_LENGTH = 1.24


def swap_policy_terms() -> dict:
    """The fitted classic swap weights, AS DATA for the armed auction request.

    The Hard/Expert auction leaf models the talon (`bid::SwapPolicy` in the
    Rust core): each determinized world gives the prospective declarer its best
    exchange from that world's sampled talon before solving. The weights cross
    the wire from here so a re-fit moves the leaf with no Rust change and no
    wasm rebuild; only the feature arithmetic lives twice, and
    `tests/fixtures/swap_policy.jsonl` holds the two copies to one answer.
    """
    return {"take_w": list(_SWAP_TAKE_W), "give_w": list(_SWAP_GIVE_W),
            "take_trump": _SWAP_TAKE_TRUMP, "give_trump": _SWAP_GIVE_TRUMP,
            "void": _SWAP_VOID, "singleton": _SWAP_SINGLETON,
            "length": _SWAP_LENGTH}


def choose_swap(g: dict, seat: int, denom: int | None = None) -> dict:
    """Pick the talon exchange, or stand pat.

    CLASSIC (the contract is settled): the fitted policy above.

    SKAT (the talon resolves BEFORE the game is named): still the old
    rank-worth rule, DELIBERATELY. The fit was trained and gated on classic
    decisions, where the denomination and level are known; skat's swap has
    neither, and shipping the classic weights there would be a guess wearing a
    measurement's clothes. Fixing skat's swap is its own `swaplab` run.
    """
    if denom is None:
        denom = swap_denom(g, seat)
    hand = list(g["hands"][seat])

    if g["auction"]["denom"] >= 0:
        tc = E.trump_class(denom)
        best = {"take": None, "give": None}
        best_score = 0.0
        for t in g["shown"]:
            for h in hand:
                s = _SWAP_TAKE_W[E.rank(t)] + _SWAP_GIVE_W[E.rank(h)]
                if E.esuit(t, denom) == tc:
                    s += _SWAP_TAKE_TRUMP
                if E.esuit(h, denom) == tc:
                    s += _SWAP_GIVE_TRUMP
                give_suit = sum(1 for c in hand if E.esuit(c, denom) == E.esuit(h, denom))
                take_suit = sum(1 for c in hand if E.esuit(c, denom) == E.esuit(t, denom))
                if give_suit == 1:
                    s += _SWAP_VOID
                elif give_suit == 2:
                    s += _SWAP_SINGLETON
                s += _SWAP_LENGTH * take_suit / 7.0
                if s > best_score:
                    best_score = s
                    best = {"take": t, "give": h}
        return best

    def worth(c: int) -> float:
        # Card scoring rates the talon differently: a card TAKEN joins the
        # played pool (a +2 is points you now control the timing of) and the
        # discard leaves it entirely (shipping a -1 to the talon deletes the
        # liability from the round). The skat curve encodes exactly that
        # preference; still the old separable rule, per the swaplab note above.
        v = (_SKAT_RANK_VALUE if E.uses_card_points(E.mode_of(g))
             else _RANK_VALUE)[E.rank(c)]
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
    if phase == "double":
        return ("move", {"kind": "double", "on": choose_double(g, seat)})
    if phase == "kontra":
        return ("move", {"kind": "kontra", "on": choose_kontra(g, seat)})
    if phase == "re":
        # Doubling back is a read on the defender's read; not this tier.
        return ("move", {"kind": "re", "on": False})
    if phase == "play":
        return ("play", choose_card(g, seat))
    return (None, None)
