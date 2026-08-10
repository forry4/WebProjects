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
piles, the talon, follow-suit and the redaction machinery are shared verbatim
-- ``apply_move`` dispatches on ``g["mode"]`` and both paths converge on
``_start_play``. See ``rust-cores/dissonance-core/SKAT_MODE.md``.

Since 2026-08-09 skat mode also scores DIFFERENTLY: the trick-number parity is
gone and the CARDS captured in a trick are what score -- 9/10/J/Q are worth +2
each, 7/8/K/A are worth -1 each (``CARD_VALUES``). A trick is worth the sum of
its two cards (-2, +1 or +4), the winner banks it, and the round's pool is
whatever the 26 dealt-in cards add up to (16 minus the out-cards' worth), so it
varies deal by deal. The tension the values buy: the ranks that WIN tricks
(K, A) are themselves liabilities, and the ranks worth capturing (9..Q) sit in
the middle where they rarely win a trick on their own.

Minor mode (2026-08-09) is the THIRD mode and the first to touch the trick
VALUES rather than the auction: even tricks pay +1 instead of +2 (odd tricks
stay -1), over the classic auction shape. The pool goes negative (-1), the
level ladder compresses to 1..6, and the scoring is re-anchored to the smaller
scale -- see ``EVEN_TRICK_VALUE`` for the map of what follows from the one
number.

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
#
# THE WIDE DECK (2026-08-10, dummy mode): three seats of thirteen is 39 cards
# and the deck holds 32, so dummy deals a FORTY-card deck -- the same 32 plus a
# 5 and a 6 in each suit. The eight new cards are ids 32..39 and NOT a
# renumbering, which is the whole of why this shape was chosen over the obvious
# `suit * 10 + rank`:
#
#   * every existing card id means exactly what it always did, so classic /
#     skat / minor saves, the committed Rust parity fixtures and the committed
#     wasm artifact are all untouched (the Rust core never sees a dummy game --
#     `client_searchable` says so -- so it never has to learn the wide deck);
#   * `suit(c)` and `rank(c)` stay TOTAL functions of the id. A per-mode
#     `suit * nrank + rank` would make a card id mean different cards in
#     different modes, and every one of the ~30 call sites would have to be
#     handed a mode to stay correct. Bolting the new ranks on the end costs one
#     branch in each of two functions instead.
#
# The cost, stated: the id's low bits are no longer the rank. `rank()` returns
# a STRENGTH-ordered index 0..9 (0 = the 5, 9 = the ace) in every mode, so
# `RANK_NAMES`, `CARD_VALUES` and every rank curve are indexed by strength and
# `beats` is still a plain `>`; the base deck simply never produces a 0 or 1.

VERSION = 2  # bumped by the 32-card / ranked / Null / swap release

NRANK = 8    # ranks per suit in the BASE deck
NSUIT = 4
NCARD = 32   # the base deck: ids 0..31, and they never move
NOTRUMP = 4

#: The wide deck's extra ranks per suit (the 5 and the 6), laid out as
#: `NCARD + suit * NEXTRA + k` so the base ids keep their meaning.
NEXTRA = 2
NCARD_WIDE = NCARD + NSUIT * NEXTRA   # 40
NRANKS = NRANK + NEXTRA               # rank slots, strength-ordered

RANK_NAMES = ["5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUIT_NAMES = ["clubs", "diamonds", "hearts", "spades"]
SUIT_CHARS = ["c", "d", "h", "s"]

#: GRAND: the four tens are trump and belong to NO suit -- Skat's jack rule,
#: transplanted onto the ten. Only reachable in skat mode (it is priced, and
#: classic's auction ranks denominations rather than pricing them).
#:
#: 6, NOT 5. 5 is NULL_DENOM, the marker left on saved games from before Null
#: stopped being a bid, and reusing the number would silently re-read one of
#: those as a Grand contract -- a different trump and different follow-suit.
#: Nothing else about the value 6 matters; it is never arithmetic.
GRAND = 6

#: The rank that becomes trump under Grand. DERIVED, because the deck's rank
#: list is what says which index is the ten.
TEN_RANK = RANK_NAMES.index("10")

#: Follow-suit classes: the four real suits, plus one for Grand's trump. A
#: card's class is its suit everywhere EXCEPT a ten in a Grand game, so under
#: any other contract this collapses back to `suit`.
TRUMP_CLASS = 4
NFOLLOW = 5

DENOM_NAMES = SUIT_NAMES + ["no-trump", "Null", "grand"]

NTRICKS = 13
POOL = 5  # both players' totals always sum to this (CLASSIC parity; minor is
#           -1 via pool_for, and skat scores CARDS so its pool is per-deal)

MIN_LEVEL = 1

#: SKAT'S CEILING, and the generator of its value ladder (base x level, 1..12,
#: 32 rungs topping out at 60). It is also the PARITY CEILING -- six +2 tricks
#: and none of the -1s is 12 points -- which is why the parity modes used it as
#: their bid ladder's top for a year. They no longer do; see below.
MAX_LEVEL = 12

#: THE PARITY MODES' BID LADDER TOPS OUT HERE, and this is a product cap rather
#: than an arithmetic one (2026-08-10). 11 and 12 are reachable -- 11 is six
#: even tricks plus one odd, 12 is a clean parity sweep -- but they are hands
#: nobody bids, and carrying them made the level grid twelve buttons wide.
#: Ten is two rows of five, and it is where the bots' own ladders already
#: stopped (classic's tops out at 6, dummy's at 10).
#:
#: SKAT IS DELIBERATELY UNTOUCHED. Its levels are a multiplier on a base, not a
#: points promise, so `SKAT_VALUES`, `skat_declarable` and `apply_declare` all
#: keep reading `MAX_LEVEL` -- capping them would move 8 rungs off the ladder
#: and re-price the whole mode.
PARITY_MAX_LEVEL = 10

#: MINOR MODE'S LEVEL CEILING. With even tricks at +1 a declarer's absolute
#: ceiling is sweeping the six even tricks for 6 points, so the classic 1..12
#: ladder would carry six rungs nobody can reach. DERIVED-in-spirit from the
#: parity (6 even tricks x +1); `test_minor.py` asserts the relationship so a
#: trick-value change cannot silently strand the ladder above the game.
MINOR_MAX_LEVEL = 6

#: What the Null consolation pays in minor mode. 6, for the same reason classic
#: pays 12: it is exactly a made level-1 contract's CEILING under the overtrick
#: bonus (1 + (max_pts - 1) x 1 = max_pts), so ducking to Null is never worth
#: more than the cheapest contract played out perfectly -- the relationship the
#: classic number already has, carried to the minor scale rather than copied as
#: a literal.
MINOR_NULL_MAKE = 6
#: An overtake must raise the contract by 1 or 2. Measured: a cap of exactly 2
#: relocates the punishment-landing pile from level 2 to level 3, which is
#: where the distribution had a hole. A cap of 3 empties level 3 again.
MAX_RAISE = 2

#: Set-score multiplier per point the declarer finished short.
#:
#: 5, not 4 (2026-08-08). Raised to make SACRIFICING dearer: once the Hard tier
#: started pricing the pass it began deliberately buying contracts it could not
#: make -- 38% of classic rounds -- because being set was cheaper than conceding
#: a made contract. The shortfall term is the whole cost of that play, so it is
#: the lever, and Double is not: Double only fires when a defender reads the
#: sacrifice correctly, while this prices every one of them.
#:
#: It applies to classic AND skat -- skat's set is `stake + SHORT_PENALTY x
#: short` too. Minor mode has its own rate below.
SHORT_PENALTY = 5

#: Minor mode's per-point set rate. 2, NOT the classic 5, and the argument is
#: scale, measured in self-play (tools/minor_calibration.py): minor's payoffs
#: run a quarter of classic's (make ceiling 36 vs 144) while its SHORTFALLS
#: keep the same magnitude (median 2 in both sweeps), so a per-point rate
#: carried over unscaled makes the set the biggest number on the table --
#: at 5, two-thirds of minor rounds ended in a set paying ~11 against made
#: contracts paying 1-6, i.e. every round read "whoever had to open loses".
#: 2 tracks the ceiling ratio and puts a typical set (~5) beside a typical
#: make instead of on top of it. The sacrifice still gets taxed: classic's
#: Double and its shortfall RAMP apply in minor unchanged.
MINOR_SHORT_PENALTY = 2

#: THE DOUBLE'S ESCALATOR. Doubled, the first point short costs
#: `SHORT_PENALTY + DOUBLE_RAMP`, the second `+ 2 x DOUBLE_RAMP`, and so on --
#: 6, 7, 8, 9 at the shipped values.
#:
#: WHY A RAMP RATHER THAN A BIGGER FLAT BASE. Doubling has to tell a SACRIFICE
#: from a near-miss, and what separates them is not the LEVEL -- both cases have
#: that -- but how far short the declarer finishes: ordinary failures come up a
#: median of 2 short with 48% of them by exactly 1, while sacrifices come up a
#: median of 4. Scaling the base by N taxes the level; ramping taxes the
#: shortfall, which only a sacrifice has.
#:
#: MEASURED: doubling a level-6 sacrifice goes from EV -0.24 (flat 2N) to +9.20
#: with this ramp, while an ordinary level-6 contract stays at -11.70 -- and the
#: worst single round is 93 rather than the 138 a +2 ramp allows, which matters
#: in a match to 100. A +2 ramp measured +18.64 but pushed the sacrifice RATE
#: from 36% to 7%, i.e. it removes the play rather than pricing it.
DOUBLE_RAMP = 1

#: What each trick point ABOVE the target adds to a MADE contract (2026-08-07).
#:
#: A per-mode dict like `MATCH_TARGET`, and like that one it currently reads the
#: same in both -- the two modes score on different scales and nothing requires
#: them to agree, so the shape stays even while the numbers match.
#:
#: WHY. Before this, a made contract paid a flat amount: N^2 in classic, the
#: stake in skat. So the moment the target was home the rest of the round was
#: worth nothing to the declarer, and in skat -- where the level is a free
#: choice made after the auction, and declaring the minimum that clears your bid
#: is normal -- that could be most of the hand. Every trick now moves the score.
#:
#: FLAT, and deliberately NOT scaled by skat's announcements or by Kontra, on the
#: same argument as `SKAT_NULL_VALUE`: Hand, Sharp and Open are promises about
#: the CONTRACT, and running a per-point bonus through a x4 would make one
#: overtrick worth more than the rungs the ladder is built out of.
#:
#: TWO CONSEQUENCES, both of which fall out rather than being designed:
#:  * NO ROUND STOPS EARLY ANY MORE. `_score_is_settled` asks whether the
#:    remaining tricks can still move the SCORE; with an overtrick bonus the
#:    answer is always yes. The predicate is SHELVED, not deleted -- it reads
#:    this table rather than the mode, so setting a bonus back to 0 restores the
#:    early end for that mode on its own, and a test drives it at 0 to keep the
#:    branch live. See the note on `_score_is_settled`.
#:  * IT NARROWS THE NULL CLIFF, which was measured and is documented as
#:    deliberate ("a cheap contract is a licence to duck"). A declarer's ceiling
#:    is 12 points, so a made level-1 classic contract goes from 1 to as much as
#:    12 against Null's flat 12, and a skat stake of 6 from 6 to 15 against 20.
#:    The cliff is narrowed, not removed, and the measurement behind it was taken
#:    on flat payouts -- so it is the number most worth re-running in `skatlab`.
OVER_BONUS = {"classic": 1, "skat": 1, "minor": 1, "dummy": 1}

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

MODES = ("classic", "skat", "minor", "dummy")
DEFAULT_MODE = "classic"

# --- dummy mode ------------------------------------------------------------
#
# THE FOURTH MODE (2026-08-10), and the first with a THIRD HAND on the table.
#
# WHY. Card scoring (skat) put the trick's value in the cards, which was the
# point -- and then measured as "random, no control", for a reason the shelved
# must-head experiment made precise: the player NOT taking a trick chooses its
# payload. You win with an ace, they slide a 7 under it, and the trick you
# fought for pays -2. Commanding a SECOND HAND is the direct answer, because
# it makes you the author of two of a trick's three cards.
#
# THE SHAPE:
#  * THREE seats of ten -- 4 in hand + three 2-card piles -- so 30 dealt, TWO
#    out, TEN tricks of three cards. Seats 0 and 1 are the players; seat 2 is
#    the dummy.
#  * The dummy's HAND IS FACE UP FROM THE DEAL, to both players. Shared
#    information advantages neither bidder, and it turns the auction into a
#    judgement about "my hand plus that one" against "theirs plus that one",
#    which is a better question than either hand alone. Its outer pile bottoms
#    stay hidden from EVERYONE, exactly like a player's -- a fully open dummy
#    would make the endgame a double-dummy problem for both seats.
#  * THE DECLARER PLAYS THE DUMMY. Winning the auction already bought the
#    lead; now it buys the control that was missing. The defender is
#    compensated by seeing the whole dummy.
#  * THE DUMMY PLAYS SECOND, ALWAYS -- and never leads: a trick the dummy
#    takes passes the lead to the DECLARER. Three reasons, in order: its card
#    is information in the middle of the trick that both players react to; the
#    third seat is therefore always the real player who did not lead, so the
#    duck-or-take decision stays a human one every single trick; and it gives
#    the declarer a genuinely new move -- lead low from hand, drop the dummy's
#    +2 on it, and dare the defender to take a fat trick they do not want.
#  * NO TALON. There are only two out-cards to hide behind, and the declarer's
#    prize is the dummy itself. That also removes skat's Hand/Sharp/Open, all
#    of which are announcements ABOUT the talon.
#
# So the mode is CLASSIC's auction (level + denomination, ranked, the opener
# must bid, the defender's Double) over CARD scoring, with a third hand. It is
# deliberately a new mode rather than a change to skat: skat keeps its solver,
# its fixtures and its round review, and this can be judged beside it.
DUMMY = "dummy"

#: The dummy's index into `hands` / `piles`. Seats 0 and 1 are the players, so
#: it is 2 -- and a POSITION is not a SEAT: `to_play` returns a position, while
#: `turn_seat` maps the dummy's back to the declarer, who actually acts.
DUMMY_POS = 2

#: (hands dealt, cards in hand, cards out of play, tricks, piles) per mode.
#:
#: THE PILE COUNT IS A DIAL, and it is the one that decides how much CHOICE a
#: player gets: only a pile's top is playable, so every card in a pile is a
#: card the deal chose for you. Measured (`tools/agency_probe.py`): classic's
#: 7 + three piles is 46% of a holding on rails and 4.07 legal cards at a
#: decision; dummy's FIRST layout (4 + three piles, out of the 32-card deck)
#: was 60% on rails and 2.89, with a third of all plies forced outright.
#:
#: DUMMY IS THIRTEEN A SEAT NOW (2026-08-10) -- the same 7 + three 2-card piles
#: every other mode deals, and therefore the same 13 tricks and the same 46% on
#: rails. Three thirteens is 39 cards, which is what the wide deck is for; ONE
#: card sits out (dummy has no talon, so the out-pile is only the round-end
#: reveal and its size is free).
_LAYOUT = {DUMMY: (3, 7, 1, 13, 3)}
_LAYOUT_DEFAULT = (2, 7, N_OUT, NTRICKS, 3)


def layout_for(mode: str):
    return _LAYOUT.get(mode, _LAYOUT_DEFAULT)


def has_dummy(mode: str) -> bool:
    return mode == DUMMY


def n_hands(g: dict) -> int:
    return layout_for(mode_of(g))[0]


def ntricks_in(g: dict) -> int:
    return layout_for(mode_of(g))[3]


def client_searchable(mode: str) -> bool:
    """Can `rust-cores/dissonance-core` search this mode at all?

    FALSE FOR DUMMY, and it is the honest half of shipping a third hand: the
    Rust core is two-seat to its bones -- `State.hand` is `[Mask; 2]`, the
    solver's minimax alternates between two players, the wire reader partitions
    a two-hand pool. A three-seat search is its own project, so until it exists
    a dummy room must never ARM the browser: an armed client would answer with
    a card for the wrong hand, the engine would refuse it, and the room would
    play the server bot at full speed while the label said Hard. `main.py`
    reads this to refuse arming, and the create modal reads it (via
    `/catalog`) to stop offering the tiers at all -- a tier that cannot run is
    worse than one that is not on the menu.
    """
    return not has_dummy(mode)

#: What an EVEN-numbered trick pays its winner, per mode. Odd tricks are -1
#: in the parity modes.
#:
#: SKAT'S ENTRY IS VESTIGIAL since card scoring (2026-08-09): its rounds score
#: captured cards (`CARD_VALUES`) and never read a trick's parity value. The
#: row stays at 2 so `even_val` on the wire keeps its historical value for any
#: old reader, and `uses_card_points` -- not this table -- is what says how a
#: mode scores.
#:
#: MINOR (2026-08-09): even tricks pay +1 instead of +2, over the classic
#: auction. The pool flips NEGATIVE (6 x 1 - 7 = -1): winning every trick now
#: scores -1, and even a perfect declarer tops out at 6, so ducking is worth
#: relatively more everywhere and the whole contract ladder compresses to 1..6
#: (`MINOR_MAX_LEVEL`). Everything downstream is re-anchored to that scale
#: rather than re-designed: make N^2 (1..36), set N + SHORT_PENALTY x short,
#: the Double and its ramp unchanged, Null at a made level-1's ceiling
#: (`MINOR_NULL_MAKE`), match to `MATCH_TARGET["minor"]`.
#:
#: The value threads to the solver AT RUNTIME: `view_for` ships `even_val`,
#: `wire.rs` reads it into `State.even`, and `_deal_snapshot` carries `even` so
#: the DD review replays the round under the right parity. A wasm too old to
#: read the field is refused per-decision by the worker (and the ready
#: handshake), so a minor room degrades to the server bot rather than being
#: searched under classic values.
EVEN_TRICK_VALUE = {"classic": 2, "skat": 2, "minor": 1, "dummy": 2}


def even_value(mode: str) -> int:
    return EVEN_TRICK_VALUE.get(mode, EVEN_TRICK_VALUE[DEFAULT_MODE])


#: SKAT MODE SCORES THE CARDS, NOT THE TRICK NUMBER (2026-08-09). Indexed by
#: rank (7 8 9 10 J Q K A): the four middle ranks are worth +2 each, the two
#: ends -1 each. A completed trick pays its winner the SUM of its two cards --
#: -2, +1 or +4 -- so "which tricks you win" becomes "which CARDS you win",
#: and the parity machinery (`trick_value`, `even_value`, `pool_for`) simply
#: does not apply to this mode any more.
#:
#: Why these signs: the ranks that WIN tricks (K, A) are liabilities worth -1,
#: so raw high-card power costs points to use -- the second player can duck a
#: 7 under your ace and hand you a -2 trick. The +2 cards sit in the middle
#: (9..Q), strong enough to take a trick only when the big cards are spent.
#: 16 cards at +2 against 16 at -1 puts the whole deck at +16; six cards sit
#: out, so a round's REAL pool is `played_pool` and varies with the deal
#: (4..22, mean 13).
#:
#: INDEXED BY `rank`, i.e. by STRENGTH, 5 first and ace last. The wide deck's
#: two extra ranks are worth ZERO, which is three things at once and all three
#: were measured before they were chosen (`tools/dummy_matrix.py`):
#:   * the deck total stays +16 -- 4 suits x (0 + 0 - 1 - 1 + 2 + 2 + 2 + 2
#:     - 1 - 1) -- so a wider deck does not silently re-scale the ladder;
#:   * it breaks the mod-3 granularity. Every value used to be 2 mod 3, so
#:     three of them always summed to a multiple of 3 and two thirds of dummy's
#:     contract ladder were literally duplicate rungs. With a 0 in the table
#:     the gcd of reachable trick sums is 1 and every rung is a real contract;
#:   * it gives the mode a genuinely SAFE discard, which is what free discard
#:     (no follow-suit, 2026-08-10) wants to feed on: a card that neither wins
#:     a trick you want to lose nor costs points when someone else takes it.
CARD_VALUES = [0, 0, -1, -1, 2, 2, 2, 2, -1, -1]


def card_points(c: int) -> int:
    """What capturing this card is worth, under card scoring."""
    return CARD_VALUES[rank(c)]


def deal_is_current(g: dict) -> bool:
    """Does this saved deal use the deck the mode deals TODAY?

    A round in progress carries its own hands, piles and out-pile, so it goes on
    being played under the shape it was DEALT with while `layout_for` and
    `deck_size` describe the shape a NEW deal gets. That is fine until the two
    disagree: a dummy round dealt at ten cards a seat resumed under the
    thirteen-card layout runs out of cards at trick 11 and jams with no legal
    move, which is a hung room rather than an error anyone can see.

    Counting is the whole test -- every card is in exactly one of hands, piles,
    the out-pile and the played list at every moment of a round, so the union is
    the deck. Voiding a stale round rather than migrating it is the same call
    `load_game_to_memory` already makes for pre-v2 saves.
    """
    seen = set(g.get("out") or [])
    seen |= {c for h in (g.get("hands") or []) for c in h}
    seen |= {c for pile in (g.get("piles") or []) for p in pile for c in p}
    seen |= set(g.get("played") or [])
    return len(seen) == deck_size(mode_of(g))


def wire_card_values(mode: str) -> list:
    """`CARD_VALUES` sliced to the ranks this mode's deck actually holds.

    A WIRE-COMPATIBILITY decision, not tidiness. A 32-card room still ships the
    same eight entries it always did, indexed 7..A, so a bundle cached from
    before the wide deck goes on labelling skat's corner chips correctly; a
    dummy room ships all ten. The client takes its offset from the LENGTH
    (`NRANKS - len`), which needs no new field and no version bump.
    """
    return list(CARD_VALUES) if wide_deck(mode) else list(CARD_VALUES[NEXTRA:])


def card_pool_for(mode: str) -> int:
    """What this mode's whole deck adds up to. The dealt-in pool is this minus
    the out-cards (`played_pool`). Computed rather than stored so a change to
    `CARD_VALUES` -- including a tool patching it to measure a candidate table
    -- cannot leave a stale constant behind it."""
    return sum(card_points(c) for c in range(deck_size(mode)))


def uses_card_points(mode: str) -> bool:
    """Does this mode score captured cards rather than the trick parity?

    Skat since 2026-08-09, and DUMMY from the day it shipped -- the third hand
    exists to give a player control over what a trick is WORTH, which is only
    a decision at all while the cards carry the points.
    """
    return mode in ("skat", DUMMY)


#: MUST HEAD THE TRICK (skat, 2026-08-10) -- when you CAN follow suit, you must
#: play a card that BEATS the led card if you hold one. Ducking under a winner
#: is only legal when you cannot beat it at all.
#:
#: WHY, and it is a fix for a specific complaint: under card scoring the FOLLOWER
#: set the trick's value. You led an ace, they slid a 7 under it, and the trick
#: you won paid -2 -- the player not taking the trick decided what it was worth,
#: which is what made the mode feel random. Must-head hands that decision back:
#: if they can beat you they must, so the lead now CHOOSES who takes the trick
#: against a read of their holding, and the follower's remaining choice is
#: WHICH winner to spend -- i.e. how much the trick they are taking is worth.
#: That choice only exists because the cards carry the points; under a parity
#: mode the same rule would collapse the follower to "cheapest winner" and
#: delete the duck, which is the whole parity game. Hence skat only.
#:
#: WHAT IT DOES NOT TOUCH: ruffing. Void in the led suit you may still play
#: anything, trump included, and are never forced to ruff -- must-head is a
#: filter on the FOLLOW set alone. Making the ruff compulsory too is a separate,
#: bigger change and is deliberately not in this one.
#:
#: TWO CONSEQUENCES worth knowing. High cards become a liability you can be
#: FORCED to spend: lead a K and the ace must answer it, eating a -2 trick. And
#: a pile TOP that beats forces itself out, uncovering the card beneath -- the
#: piles constrain you harder than they did.
#:
#: SHELVED 2026-08-10, THE DAY IT SHIPPED -- measured, and the measurement is
#: why. Kept whole and behind this flag rather than deleted, exactly as
#: `_score_is_settled` is: the rule works, the gates still drive it, and
#: turning it back on is this one line. What the measurement said:
#:
#:  * It changes the outcome of EXACTLY ONE trick shape -- lead a king into an
#:    unplayed ace and they must eat a -2 trick, where otherwise they duck a 9
#:    under it and the LEADER eats +1. Every other shape is unmoved.
#:  * It therefore does NOT fix the complaint it was built for ("you win with
#:    an ace and they slide a 7 under it"): nothing beats an ace, so the rule
#:    never fires in that position at all.
#:  * It bound on 6.2% of follows under the shipped policy, against 34.4% if
#:    the leader chose leads to force it -- a real lever, but a narrow one, and
#:    ~85% of the follows it bound left the follower no choice at all. So it
#:    mostly MOVES a decision from the follow to the lead rather than adding
#:    one.
#:
#: The verdict was that a narrow lever is not what the mode needs; the DUMMY
#: (see its own section) is the answer being tried instead. Do not re-measure
#: this from scratch -- the numbers above are from `tools/skat_calibration.py`
#: and a counterfactual sweep over real rounds.
#:
#: A PER-MODE DICT, like `OVER_BONUS` and `EVEN_TRICK_VALUE`, and deliberately
#: NOT folded into `uses_card_points`: a legality rule and a scoring rule are
#: different things, and everything downstream DERIVES from this dict -- the
#: bot's extraction lead self-disables, and the client-AI wire requirement
#: drops back a rung -- so flipping it is genuinely the only edit.
MUST_HEAD = {"classic": False, "skat": False, "minor": False, "dummy": False}

#: MUST YOU FOLLOW SUIT? True everywhere by default.
#:
#: THE REPO'S PRIOR, which this flag exists to re-test rather than repeat:
#: optional follow was rejected for CLASSIC because under parity scoring it
#: makes every -1 trick fall deterministically to whoever leads it -- nobody
#: ever has to take a trick they do not want, so 7 of 13 tricks lose all
#: decision content. That argument is about a currency where the trick's value
#: is known BEFORE the cards are chosen. Under card scoring the value is the
#: cards, so the same rule may read completely differently, and with three
#: seats the last player is choosing against two cards already on the table.
#: Measured per mode rather than assumed -- see `tools/agency_probe.py`.
#: DUMMY IS FREE DISCARD since 2026-08-10, and it is MEASURED -- the prior
#: above is real but belongs to the parity modes, so it stays True there.
#: With three seats and card scoring the rule reads the opposite way:
#:
#:   choices at a decision   2.88 -> 4.11   (classic's own figure is 4.07)
#:   plies with no choice    33%  -> 13%
#:   by seat in the trick    4.11/2.27/2.26 -> 4.11/4.11/4.10
#:   hand predicts points    +0.11 -> +0.21
#:
#: The followers were the ones with nothing to decide -- 2.27 legal cards
#: against the leader's 4.11 -- and free discard levels that exactly. The
#: collapse the classic prior warns about does NOT happen here: the leader
#: keeps the lead on 55% of tricks under follow-suit and 50% without it, so
#: unwanted tricks do not simply fall to whoever led. Ducking out does not
#: become free either (Null 3% -> 1%), because the value of a trick is its
#: CARDS and the other two seats choose those. What does move is trump: ruffs
#: run 0.37 -> 0.57 a trick, so which suit you name matters more, which is
#: the auction's side of the same brief.
FOLLOW_SUIT = {"classic": True, "skat": True, "minor": True, "dummy": False}


def follows_suit(mode: str) -> bool:
    return FOLLOW_SUIT.get(mode, True)


def must_head_mode(mode: str) -> bool:
    return bool(MUST_HEAD.get(mode, False))


def played_pool(g: dict) -> int:
    """Both players' totals over a COMPLETED skat round: the worth of the 26
    dealt-in cards. Deal-dependent -- `out` is the six cards nobody plays (the
    swap keeps it current), so the pool is everything minus those."""
    return card_pool_for(mode_of(g)) - sum(card_points(c) for c in g["out"])


def pool_for(mode: str):
    """Both players' totals over a completed round: six evens minus seven odds.

    PARITY MODES ONLY. Skat scores captured cards (2026-08-09), so its pool is
    a property of the DEAL (`played_pool`), not the mode -- None here, so a
    caller that assumed a constant fails loudly rather than reading 5."""
    if uses_card_points(mode):
        return None
    return 6 * even_value(mode) - 7


def max_level_for(mode: str) -> int:
    """The top of the BID LADDER for a mode -- not the same thing as the top of
    the scale it is denominated in.

    Skat's levels multiply a base, so its ladder is the whole 1..MAX_LEVEL
    range. The parity modes' levels are a promise in trick points, and both cap
    below their arithmetic ceiling on purpose: minor at its ceiling of 6 (there
    is nothing above it), classic and dummy at PARITY_MAX_LEVEL, which is a
    product cap two rungs under theirs."""
    if mode == "minor":
        return MINOR_MAX_LEVEL
    if uses_card_points(mode):
        return MAX_LEVEL
    return PARITY_MAX_LEVEL

#: A game is a MATCH of rounds, played until one side reaches this.
#:
#: STILL A DICT though both modes now read 100, because the two score on
#: different scales and there is no reason they must agree: a classic round pays
#: level^2 (1..144, flat 12 for Null), a skat one base x level x the
#: announcements (2..60, flat 20). They happen to land on the same match length
#: anyway -- MEASURED against the normal-tier bot on the colour-priced bases,
#: classic is a median of 10 rounds (range 6-16) and skat 11 (6-18).
#:
#: Re-measure if the bases or the payoff arithmetic move: the target is a
#: product decision, but the round count it buys is not a guess. Skat was a
#: median of 8 to 100 before the bases were re-priced by colour.
#:
#: WHY A MATCH AT ALL. One round is one deal, and a deal can simply be bad --
#: a hand with no contract in it loses to a hand with one, and the auction is
#: the only lever either player has. Over several rounds the deals average out
#: and what is left is the bidding judgement, which is the part worth playing.
#: (Minor's 25 is NOT the other modes' 100 rescaled by feel: its payoffs run
#: about a quarter of classic's -- make ceiling 36 vs 144, typical winning
#: round ~3.6 vs ~16 in the calibration sweep -- so 25 buys the same match
#: length classic's 100 does. Measured in tools/minor_calibration.py, ~7
#: bot-self-play rounds against classic's ~6 under the identical harness.)
#:
#: DUMMY's is the same arithmetic in the other direction, and it is NOT a round
#: number chosen by feel. IT MOVED 400 -> 200 when the mode went to thirteen
#: cards a seat, which is the whole reason this note keeps its history: at ten
#: cards the declarer commanded so much of the table that they took ~12 of a
#: ~15-point pool, contracts settled at levels 9-12, and N^2 made the mean
#: winning round ~61 -- 100 would have ended a match in 1.6 rounds. The wide
#: deck put every seat on 13 and the declarer's share fell to 48% (they now
#: take a mean of 7.7 against a pool of 15.6), so contracts settle at 2-10 with
#: a peak at 6 and the mean winning round is ~34. 200 buys ~5.9 rounds against
#: classic's ~6.2 at 100; 400 would now buy nearly twelve, which is a different
#: and much longer game than the other three modes offer. Measured in
#: tools/dummy_calibration.py.
MATCH_TARGET = {"classic": 100, "skat": 100, "minor": 25, "dummy": 200}

#: value = base x level. Indexed by denomination (clubs..no-trump).
#:
#: PRICED BY COLOUR since 2026-08-07: red 2, black 3, no-trump 5. It replaced a
#: four-tier table (D2 H3 S4 C5 NT6) that mirrored real Skat's 9/10/11/12, and
#: the reason for the change is that four tiers over four MEASURED-SYMMETRIC
#: suits was too much manufactured asymmetry -- a hand equally playable in
#: hearts and spades was priced a whole rung apart for no reason a player could
#: name, so the cheap suits swallowed the auction. Two tiers keep the part that
#: works (your ABILITY in a denomination is real and varies by hand; only its
#: PRICE is convention) and drop the part that only added noise: choosing
#: between the two reds is now purely a question about your cards.
#:
#: WHAT IT COSTS: the ladder loses nothing anyone bids. Dropping base 6 removes
#: only 42, 54, 66 and 72 -- every multiple of 6 at or below 36 is already a
#: multiple of 2 or 3 -- so the rungs are IDENTICAL through 40 and the ceiling
#: falls 72 -> 60. The playable range does not move at all.
#:
#: WHAT IT BUYS is AMBIGUOUS collisions, which is the mode's actual premise.
#: 12 used to clear four ways (D6 H4 S3 NT2) at four DISTINCT levels, so a bid
#: plus any tell about the level pinned the denomination exactly. It now clears
#: FIVE ways and they pair up -- D6/H6, C4/S4, and Grand alone at 3 -- so the
#: same information still leaves a choice, and the pairs are the two suits of a
#: colour, precisely the distinction the price table has stopped making.
#:
#: GRAND sits at 4, between the blacks and no-trump, and that is where it
#: belongs rather than at the top: with only four trumps (of which ~0.75 sit
#: out of play on an average deal) a Grand game is no-trump with a handful of
#: wild cards, not a suit game with a long trump.
#:
#: INDEXED BY DENOMINATION, including the two that cannot be bought: NULL_DENOM
#: at 5 carries a base of 0, which is the marker for "not on the ladder". Iterate
#: `SKAT_DENOMS`, never `range(len(SKAT_BASE))`.
SKAT_BASE = [3, 2, 2, 3, 5, 0, 4]
#             C  D  H  S  NT  -  G

#: The denominations a skat game can actually be played in, in ladder order.
SKAT_DENOMS = (0, 1, 2, 3, NOTRUMP, GRAND)

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
#: enumerates the rungs by hand and gets it wrong twice (it counts 43 and lists
#: a 7). The GENERATOR (base x level) is the rule -- 7 is a multiple of no base,
#: so it is a hole, and it remains the ONLY one in the otherwise dense 2..10
#: stretch under the colour-priced table too. That table gives 32 rungs topping
#: out at 60. Derived here rather than typed out so the two can never disagree.
SKAT_VALUES = sorted(
    {SKAT_BASE[d] * lvl for d in SKAT_DENOMS
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
    for d in SKAT_DENOMS:
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
    if c < NCARD:
        return c // NRANK
    return (c - NCARD) // NEXTRA


def rank(c: int) -> int:
    """The card's STRENGTH, 0 (the 5) to 9 (the ace) -- not its id's low bits.

    The base deck's ids are `suit * 8 + rank`, so a base card's own rank runs
    0..7 for 7..A and has to be lifted by `NEXTRA` to sit above the wide deck's
    two extra low ranks. Ordering is then a plain `>` everywhere, and every
    rank-indexed table (`RANK_NAMES`, `CARD_VALUES`, the bot's curves) reads in
    the order a player would say them.
    """
    if c < NCARD:
        return c % NRANK + NEXTRA
    return (c - NCARD) % NEXTRA


def card_of(s: int, r: int) -> int:
    """The card id for suit `s` at rank `r` -- `r` STRENGTH-ordered, i.e. the
    number `rank` returns, not the id's low bits.

    The inverse of (`suit`, `rank`), and the only correct way to write a card
    down from its name now that the wide deck's two ranks live at the end of
    the id space. `suit * NRANK + rank` is right for the base deck alone, and
    is wrong for it too if the rank came out of `rank()` or `TEN_RANK`.
    """
    if r < NEXTRA:
        return NCARD + s * NEXTRA + r
    return s * NRANK + (r - NEXTRA)


def wide_deck(mode: str) -> bool:
    """Does this mode deal the 40-card deck? Dummy alone -- three seats of
    thirteen do not come out of 32 cards."""
    return has_dummy(mode)


def deck_size(mode: str) -> int:
    return NCARD_WIDE if wide_deck(mode) else NCARD


def rank_bounds(mode: str) -> tuple:
    """(lowest, highest) rank this mode's deck actually contains. What a
    heuristic needs to normalise "how high is this card" without the base deck
    silently re-scaling when the wide one arrived."""
    return (0 if wide_deck(mode) else NEXTRA, NRANKS - 1)


def card_name(c: int) -> str:
    return f"{RANK_NAMES[rank(c)]}{SUIT_CHARS[suit(c)]}"


def trick_value(trick: int, even: int = 2) -> int:
    """Value of the 0-indexed trick. Trick index 0 is trick NUMBER 1 (odd).

    `even` is what an even-numbered trick pays in this room's mode
    (`EVEN_TRICK_VALUE`); the default keeps every classic-parity caller --
    including the Rust fixtures' replay -- exactly as it was.
    """
    return even if trick % 2 == 1 else -1


def trick_value_in(g: dict, trick: int) -> int:
    """`trick_value` under this game's mode."""
    return trick_value(trick, even_value(mode_of(g)))


def esuit(c: int, trump: int) -> int:
    """The suit a card belongs to FOR FOLLOWING, under this contract.

    Identical to `suit` under every contract but Grand, where the four tens
    leave their suits entirely and become a fifth one. That is the whole of
    the rules change: holding only the ten of diamonds when diamonds are led
    makes you VOID in diamonds, and leading a ten obliges the opponent to
    follow with a ten if they hold one.
    """
    if trump == GRAND and rank(c) == TEN_RANK:
        return TRUMP_CLASS
    return suit(c)


def trump_class(trump: int) -> int:
    """Which follow-suit class, if any, ruffs. -1 when nothing does."""
    if trump == GRAND:
        return TRUMP_CLASS
    return trump if trump < NOTRUMP else -1


def beats(led: int, follow: int, trump: int) -> bool:
    ls, fs = esuit(led, trump), esuit(follow, trump)
    if fs == ls:
        # Two Grand trumps cannot be ranked against each other -- they are all
        # tens -- so the SECOND one played takes the trick. Leading a ten is
        # therefore a way to LOSE a trick on purpose, which in a game where
        # seven of the thirteen are worth -1 is a tool rather than a penalty.
        if ls == TRUMP_CLASS:
            return True
        return rank(follow) > rank(led)
    t = trump_class(trump)
    # Off-suit only wins by ruffing, and only if the lead was not itself trump.
    # At no-trump `t` is -1, which no class equals, so nothing ruffs.
    return fs == t and ls != t


# --- dealing ---------------------------------------------------------------


def new_game(seats, rng=None, opener: int = 0, mode: str = DEFAULT_MODE,
             match: dict | None = None) -> dict:
    """Deal a round. `seats` is [pid0, pid1]; `opener` names the first bidder.

    `mode` selects which auction runs on top of the identical deal: "classic"
    (level + denomination, the shipped v2 auction), "skat" (a numeric ladder
    followed by a declaration), or "minor" (the classic auction with even
    tricks paying +1 -- the one mode whose difference is in the card play's
    VALUES, not its phases). Everything from `_start_play` onwards is shared,
    with `trick_value_in` reading the mode's even-trick value.

    `match` carries a running match in. Omit it for the first round of a new
    one; `next_round` passes the standing one back so the deal changes and the
    totals do not.
    """
    rng = rng or random.Random()
    mode = mode if mode in MODES else DEFAULT_MODE
    deck = list(range(deck_size(mode)))
    rng.shuffle(deck)

    # THREE hands in dummy mode, and the third is the dummy -- same shape as a
    # player's (some in hand, three 2-card piles), because the piles are what
    # keep even a face-up seat from being fully solved. Dummy also deals the
    # WIDE deck: 3 x 13 is 39 cards and the base deck holds 32.
    nhands, in_hand, n_out, _, npiles = layout_for(mode)
    hands, piles = [], []
    k = 0
    for _ in range(nhands):
        hands.append(sorted(deck[k:k + in_hand]))
        k += in_hand
        # Each pile is [bottom, top]; only the last element is playable.
        piles.append([[deck[k + 2 * i], deck[k + 2 * i + 1]]
                      for i in range(npiles)])
        k += 2 * npiles
    out = deck[k:k + n_out]

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
        #
        # THIS TRACKS WHAT IS CURRENTLY OUT OF PLAY, and a swap rewrites it --
        # see the note in `apply_swap`, which explains why the wire depends on
        # that and cannot be given the historical record instead.
        # DUMMY MODE HAS NO TALON: one card sits out, and the declarer's
        # prize is the third hand rather than a look at the out-pile. Empty
        # rather than absent, so every reader (`view_for`, the reveal, the
        # wire) keeps working without a mode test.
        "shown": [] if has_dummy(mode) else out[:N_SHOWN],
        # ...and this is the historical record: the three cards the declarer was
        # actually shown, never rewritten. Only the round-end reveal reads it,
        # and it exists because `shown` cannot answer that question after a swap.
        "shown_at_deal": [] if has_dummy(mode) else list(out[:N_SHOWN]),
        # None until the swap phase resolves; then True/False. WHICH cards
        # moved stays hidden -- the defender learns only that a swap happened.
        "swapped": None,
        # The two cards a swap moved: `swap_take` came out of the talon into
        # hand, `swap_give` went the other way. Both stay None on a decline or
        # a Hand game, and both are redacted until the round is over.
        "swap_take": None,
        "swap_give": None,
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
        # THE CARDS ALREADY DOWN IN THE TRICK BEING PLAYED, as [position,
        # card] in play order. Two-seat modes get by on `led` alone; a
        # three-card trick needs the list, and every mode maintains it so the
        # board, the winner fold and the history all read one shape. `led`
        # stays beside it as the FIRST card played -- what follow-suit is
        # measured against -- because the wire and the frontend already speak
        # it and it is what a follower actually needs.
        "plays": [],
        "pts": [0, 0],
        # +2 tricks won by each seat -- the Null contract's condition.
        "etricks": [0, 0],
        "history": [],
        "played": [],
        "result": None,
        # Classic's Double, set in its own phase between the swap and trick 1.
        # Skat doubles with Kontra/Re on `contract` instead.
        "doubled": False,
        # THE MATCH, which outlives this deal. `scores` is cumulative across
        # every scored round; `round` counts them; `over` is what ends the room.
        # A skat pass-out redeals without touching any of it -- an unplayed
        # deal is not a round.
        "match": dict(match) if match else {
            "target": MATCH_TARGET.get(mode, MATCH_TARGET[DEFAULT_MODE]),
            "scores": [0, 0],
            "round": 1,
            "over": False,
            # Who opened round 1. Every later round's opener is DERIVED from
            # this and the round number rather than flipped from the last deal
            # -- see `opener_for_round`.
            "first_opener": opener,
        },
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
    top = max_level_for(mode_of(g))
    free = [d for d in range(NOTRUMP + 1) if not (a["used"][me] >> d) & 1]
    bids: list[list[int]] = []
    if a["level"] == 0:
        # The opener must bid; passing out is not offered.
        for d in free:
            bids.extend([lvl, d] for lvl in range(MIN_LEVEL, top + 1))
        return {"bids": bids, "may_pass": False}
    # Ranked denominations: an overtake stands at the SAME level in a
    # higher-ranked denomination, or raises by up to MAX_RAISE in any unused one.
    lo, hi = a["level"], min(top, a["level"] + MAX_RAISE)
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
    # The declarer now sees `shown` and decides on the swap before play --
    # except in a dummy room, which has no talon at all (two out-cards, and
    # the prize is the third hand), so the defender's Double comes straight
    # after the auction.
    g["phase"] = "double" if has_dummy(mode_of(g)) else "swap"


def _redeal(g: dict) -> None:
    """Throw the hand in and deal again, in place.

    Mutating `g` rather than returning a fresh dict is load-bearing: the room
    server, the bot scheduler and every open socket all hold this exact object.

    The MATCH rides through untouched, `round` included: a deal both players
    passed out is not a round anybody played -- so the SAME seat opens the
    replacement deal. This used to flip the opener, on the reasoning that a
    player should not be able to pass out of a bad seat for free; but the
    replacement deal is fresh cards, so there was no bad seat left to escape,
    and the flip's real effect was to knock the round-by-round alternation out
    of phase.
    """
    n = g.get("redeals", 0) + 1
    m = _match_for_next_deal(g, advance=False)
    fresh = new_game(list(g["seats"]), None, opener=opener_for_round(m),
                     mode="skat", match=m)
    fresh["redeals"] = n
    g.clear()
    g.update(fresh)


def next_round(g: dict, seat: int, round_no=None) -> None:
    """Deal the next round of a match that is not decided yet, in place.

    EITHER seat may call it, which is why it carries `round_no`: the round the
    caller was LOOKING at when they asked. Two players clicking at the same
    moment is the normal case, not an error either of them should be shown, and
    without the token the second click arrives after the deal and either reads
    as "the round is still being played" or -- far worse -- deals a third round
    over the top of the second. A stale click from a round already finished
    no-ops for the same reason.

    In place for the same reason as `_redeal`: the room server and every open
    socket hold this exact dict.
    """
    if seat not in (0, 1):
        raise ValueError("not a player in this game")
    m = match_of(g)
    if not m:
        raise ValueError("this game is a single round")
    if round_no is not None and int(round_no) != m["round"]:
        return                      # already dealt, or a click from long ago
    if g["phase"] != "over":
        raise ValueError("the round is still being played")
    if m["over"]:
        raise ValueError("the match is over")
    # The opener alternates, round by round. Not for the LEAD -- the declarer
    # leads to trick 1, whoever opened -- but for the bidding: the opener names
    # a contract into no information at all, and in classic mode is not even
    # allowed to pass.
    nxt = _match_for_next_deal(g, advance=True)
    fresh = new_game(list(g["seats"]), None, opener=opener_for_round(nxt),
                     mode=mode_of(g), match=nxt)
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
        # `shown` MUST follow `out`. It is not a record of what was shown -- it
        # is "the out-of-play cards this seat can place", and the client-side
        # searcher does exact card-count arithmetic on it: `wire.rs` treats every
        # card here as out of play and returns "not a searchable position" if the
        # pool does not then partition into the opponent's hand, the covered pile
        # bottoms and the unplaced out-cards.
        #
        # Making this the historical record instead put the TAKEN card (which is
        # now in the declarer's hand) in the searcher's out-of-play set. The
        # arithmetic stopped balancing on every decision after a swap, so all
        # four workers errored, the main thread's filter dropped them silently,
        # and the room played out on the SERVER bot while still saying Hard --
        # no error anywhere, just a weaker opponent. It is deal-dependent, so it
        # passed locally and went red in CI.
        #
        # The wire shape is frozen by the COMMITTED wasm, which cannot be
        # rebuilt without wasm-pack, so this field's meaning is not ours to
        # change unilaterally. The reveal reads `shown_at_deal` instead.
        g["shown"][g["shown"].index(take)] = give
        g["swap_take"], g["swap_give"] = take, give
        g["swapped"] = True
    if skat:
        # In skat mode the talon resolves BEFORE the game is named -- the whole
        # point of taking it is to see whether it fixes a denomination for you.
        g["phase"] = "declare"
    else:
        # Classic offers the defender the Double here: the contract is settled
        # and the swap is done, so both seats know everything they are going to
        # know before trick 1.
        g["phase"] = "double"


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

    if denom not in SKAT_DENOMS:
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


def apply_double(g: dict, seat: int, on: bool) -> None:
    """Classic's Double: the defender raises the stakes, both ways at once.

    There is no redouble. Skat has Kontra -> Re because its contract carries a
    stack of announcements the declarer is already betting on; classic's is one
    number, and a second round would just be the same bet at four times the
    size with no new information between the two.

    THE CONSEQUENCE OF LEAVING NULL ALONE, stated because it limits what this
    mechanic can do: a declarer who sees a Double and knows the contract is
    gone can duck every +2 trick and take the flat Null instead, which Double
    does not touch. So Double cannot punish the CLEANEST sacrifice -- only one
    where the declarer has already won a scoring trick and can no longer reach
    Null. That is a rules consequence, not an implementation detail.
    """
    if g["phase"] != "double":
        raise ValueError("not the Double phase")
    if mode_of(g) == "skat":
        raise ValueError("skat mode doubles with Kontra, not Double")
    if seat == g["auction"]["declarer"]:
        raise ValueError("only the defender may Double")
    g["doubled"] = bool(on)
    _start_play(g)


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
    g["plays"] = []
    # The DECLARER leads to trick 1. Measured worth +0.93 pts under the
    # original parity, so this is a real part of the contract's value -- and
    # in a dummy room they lead into their OWN second hand, which is the whole
    # shape of the tier: lead low, drop the dummy's +2 on it, and dare the
    # defender to take a trick they do not want.
    g["leader"] = a["declarer"]
    # NO ROUND REVIEW WITH A DUMMY. The DD column is an exact solve, and the
    # solver is two-seat (`client_searchable`) -- a snapshot nothing can price
    # would be dead weight in every saved row and a column that never fills.
    if client_searchable(mode_of(g)):
        g["deal"] = _deal_snapshot(g)


def _deal_snapshot(g: dict) -> dict:
    """The position at the top of trick 1, kept so the round can be REVIEWED.

    The review answers "what was this deal worth to perfect card play", which
    is an exact double-dummy solve of the position play started from -- so it
    needs the cards as they stood the moment the auction stopped mattering.

    IT HAS TO BE SNAPSHOTTED RATHER THAN RECONSTRUCTED. By the end of the round
    every hand is empty and every pile is spent, and `history` records which
    card each seat played, never WHERE it came from -- a card played from a
    pile top and one played from hand are the same entry. So the split between
    hand and piles, which is exactly what makes the position, is gone. Taken
    here rather than at the deal because the talon swap happens in between and
    the review must price the hand actually played, not the one dealt.

    Small on purpose, and stored per round for the life of the match: 32 card
    ids and a handful of scalars. `terms` rides along because a review of round
    3 has to price round 3's contract, and `payoff_terms` can only read the
    contract the game is CURRENTLY on.
    """
    return {
        "hands": [sorted(g["hands"][0]), sorted(g["hands"][1])],
        # [bottom, top] per pile, the order the solver's own `Pile.c` uses.
        "piles": [[list(p) for p in g["piles"][q]] for q in (0, 1)],
        "out": sorted(g["out"]),
        "trump": g["trump"],
        "leader": g["leader"],
        # The parity the round was PLAYED under. The DD review rebuilds a State
        # from this snapshot (`wire.rs::deal_from_json`), and a minor round
        # replayed at classic trick values would be a confidently wrong number
        # in a column labelled a fact. Optional on the wire, defaulting to 2.
        "even": even_value(mode_of(g)),
        # CARD SCORING (skat, 2026-08-09). Explicit rather than inferred from
        # the terms, and defaulting to False on the wire: a skat round banked
        # BEFORE the change was played under the parity and must be reviewed
        # under it, which the absent key preserves for free.
        "cards": uses_card_points(mode_of(g)),
        # ...and the same for must-head (2026-08-10), which is a LEGALITY rule:
        # replaying an older round under it would explore lines that round's
        # players were allowed to take and this one is not. Absent = off.
        "head": must_head_mode(mode_of(g)),
        "terms": payoff_terms(g),
    }


# --- card play -------------------------------------------------------------


def pile_tops(g: dict, seat: int) -> list[int]:
    return [p[-1] for p in g["piles"][seat] if p]


def playable(g: dict, seat: int) -> list[int]:
    """Every card the seat could reach, ignoring follow-suit."""
    return sorted(g["hands"][seat] + pile_tops(g, seat))


def trick_size(g: dict) -> int:
    """Cards in a completed trick: three once there is a dummy."""
    return 3 if has_dummy(mode_of(g)) else 2


def trick_order(g: dict) -> list[int]:
    """The POSITIONS that play this trick, in order.

    THE DUMMY IS ALWAYS SECOND AND NEVER LEADS -- a trick it takes passes the
    lead to the declarer (see `apply_play`). So the third card is always the
    real player who did not lead, which is what keeps the duck-or-take
    decision a human one on every trick.
    """
    lead = g["leader"]
    if has_dummy(mode_of(g)):
        return [lead, DUMMY_POS, 1 - lead]
    return [lead, 1 - lead]


def to_play(g: dict) -> int:
    """The POSITION whose card comes next -- 0, 1, or the dummy's 2.

    NOT necessarily a player: `playing_seat` is who actually acts.
    """
    if has_dummy(mode_of(g)):
        order = trick_order(g)
        return order[min(len(g.get("plays") or []), len(order) - 1)]
    return g["leader"] if g["led"] is None else 1 - g["leader"]


#: WHO COMMANDS THE DUMMY -- "declarer" or "leader".
#:
#: `declarer` was the first shipped rule and it OVERSHOT, measured: holding two
#: of three hands banks the declarer **69% of the pool** before they decide
#: anything, and the outcome is then so nearly predetermined that the points
#: they take correlate **+0.06** with the hand they can see -- and +0.06 with a
#: CHEATING count of the cards actually in their two hands. An auction has
#: nothing left to be about.
#:
#: `leader` hands the dummy to whoever won the last trick instead, so the third
#: hand is a prize fought over rather than a gift. It also puts this game's own
#: tension on it: winning a trick can cost you points and still be worth it for
#: the command it buys. Stated as one rule -- WHOEVER LEADS THE TRICK PLAYS THE
#: DUMMY -- which is why it lives entirely in this function.
#:
#: SHIPPED AS `leader` since 2026-08-10, MEASURED (`tools/dummy_matrix.py`,
#: 300 rounds a cell): the declarer's slice of the pool falls **0.69 -> 0.57**,
#: i.e. the dummy stops being a gift and starts being contested. It roughly
#: doubles how well a hand predicts its result on the shipped value table
#: (+0.07 -> +0.15) -- but that is NOT the lever for predictability, and the
#: auction is still a lottery at 0.15. What fixes that is the CARD VALUES being
#: aligned with trick-winning power (+0.39); the two are orthogonal and this
#: one owns the share.
DUMMY_COMMAND = "leader"


def side_of(g: dict, pos: int) -> int:
    """Which PLAYER a position acts and scores for.

    The dummy's are whoever commands it, and that is the ONE place the two
    rules differ -- `playing_seat` (whose turn it is), the trick's winner and
    who leads next are all derived from this, so flipping `DUMMY_COMMAND`
    moves all three together and nothing else in the engine mentions it.
    """
    if pos == DUMMY_POS and has_dummy(mode_of(g)):
        if DUMMY_COMMAND == "leader":
            return g["leader"]
        return g["auction"]["declarer"]
    return pos


def playing_seat(g: dict) -> int:
    """The PLAYER who must choose the next card. Identical to `to_play` in
    every two-seat mode; the dummy's turn belongs to the declarer."""
    return side_of(g, to_play(g))


def legal_moves(g: dict, seat: int) -> list[int]:
    """The cards `seat` may play right now.

    Takes the PLAYER's seat, not a position -- so a dummy room asks the
    declarer the same question for both hands they command, and every existing
    caller (`main.py`, the bots, `view_for`) is unchanged. Handing it a bare
    position in a dummy room returns [] rather than a wrong answer.
    """
    if g["phase"] != "play" or seat != playing_seat(g):
        return []
    pos = to_play(g)
    cands = playable(g, pos)
    if g["led"] is not None:
        trump = g["trump"]
        ls = esuit(g["led"], trump)
        follow = [c for c in cands if esuit(c, trump) == ls]
        # Follow-suit is MANDATORY and a pile's exposed top counts as a card
        # you hold, so the piles can constrain you -- unless the mode says
        # otherwise (`FOLLOW_SUIT`), in which case every playable card is
        # legal and a seat can always refuse a trick.
        if follow and follows_suit(mode_of(g)):
            # MUST HEAD THE TRICK (see `MUST_HEAD`): if any card you could
            # follow with beats the lead, you must play one of them. Only the
            # FOLLOW set is filtered -- a void seat may still play anything and
            # is never forced to ruff.
            if must_head_mode(mode_of(g)):
                higher = [c for c in follow if beats(g["led"], c, trump)]
                if higher:
                    return higher
            return follow
    return cands


def must_head_binds(g: dict, seat: int) -> bool:
    """Is must-head REMOVING an option from this seat right now?

    For the board's hint, and derived by comparing the legal set against the
    plain follow set rather than by restating the rule -- a second copy of
    "which cards beat the lead" is exactly the drift `legal_moves` owns.
    False when the rule is not in play, when the seat is void (it never
    touches a ruff), and when every follow card beats anyway, since then it
    forbids nothing and a hint would be noise.
    """
    if g["phase"] != "play" or g["led"] is None or seat != playing_seat(g):
        return False
    if not must_head_mode(mode_of(g)):
        return False
    ls = esuit(g["led"], g["trump"])
    follow = [c for c in playable(g, to_play(g)) if esuit(c, g["trump"]) == ls]
    return bool(follow) and len(legal_moves(g, seat)) < len(follow)


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
    pos = to_play(g)
    source = _remove(g, pos, c)
    # THE HISTORY RECORDS A POSITION, not a player -- in a dummy room the
    # declarer plays two of the three hands, and which HAND a card came from
    # is the thing a replay, the board and the void inference all need. The
    # two are the same number in every two-seat mode, so nothing else moved.
    g["history"].append([pos, c, source])
    g["played"].append(c)
    plays = g.setdefault("plays", [])
    plays.append([pos, c])
    if g["led"] is None:
        g["led"] = c
    if len(plays) < trick_size(g):
        return

    # THE WINNER, folded over however many cards the trick holds. `beats` asks
    # "does this card beat that one", so carrying the best card forward is
    # exactly right for three: a plain card cannot beat a ruff (different
    # class, not trump), and a second ruff is compared on rank.
    win_pos, win_card = plays[0]
    for p, card in plays[1:]:
        if beats(win_card, card, g["trump"]):
            win_pos, win_card = p, card
    # CARD SCORING (2026-08-09): a trick is worth the sum of the cards in it,
    # whichever trick number it is -- two of them normally, three with a
    # dummy. The parity modes read the trick index as always. `etricks`
    # generalises for free: a "scoring trick" is one with positive value in
    # either currency, which is exactly what the Null consolation means.
    if uses_card_points(mode_of(g)):
        v = sum(card_points(card) for _, card in plays)
    else:
        v = trick_value_in(g, g["trick"])
    winner = side_of(g, win_pos)
    g["pts"][winner] += v
    if v > 0:
        g["etricks"][winner] += 1
    g["trick"] += 1
    # THE DUMMY NEVER LEADS: a trick it takes hands the lead to the declarer,
    # which is what keeps it second in every trick and the third card always a
    # real player's. `side_of` is that mapping and already knows it.
    g["leader"] = winner if win_pos == DUMMY_POS else win_pos
    g["led"] = None
    g["plays"] = []
    if g["trick"] >= ntricks_in(g) or _score_is_settled(g):
        _finish(g)


def _score_is_settled(g: dict) -> bool:
    """Can the remaining tricks still change the SCORE? If not, stop here.

    SHELVED AS OF THE OVERTRICK BONUS (2026-08-07), and deliberately not deleted.
    Both modes now pay 1 for every trick point past the target, so every trick
    moves the score and this returns False in the shipped configuration -- every
    round runs to thirteen. What is below is the rule as it stood, kept whole,
    because "every trick matters" is a product decision that could be revisited
    and the argument for the early end was measured rather than assumed.

    IT IS GATED ON THE TERMS, NOT ON THE MODE, which is what makes the shelf
    real: put a 0 back in `OVER_BONUS` for a mode and the early end returns for
    that mode alone, with no other edit. `test_no_round_ends_before_the_
    thirteenth_trick` drives both halves -- bonus on, nothing settles; bonus off,
    the old rule exactly, last-trick guard included -- so the branch below stays
    live and tested rather than rotting into something that no longer compiles
    against the state around it.

    The bar was the score, not the outcome, and the difference is the whole
    reason only one direction of "decided" ever ended a round early:

    * **Cannot fail.** If the declarer clears the target even after losing every
      remaining +2 trick and being handed every remaining -1, the contract is
      made -- and a made contract paid a FLAT amount, which did not move with the
      final total. Settled. It is precisely this premise the bonus removes.
    * **Cannot make.** Being mathematically set does NOT settle the score: the
      defender is paid `N + 4 x shortfall`, and every remaining trick still
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
    # THE SHELF. A made contract that keeps paying per overtrick is never
    # settled: every remaining trick still moves the declarer's total, and that
    # total is now part of the score rather than only the yardstick. Below the
    # declarer guard because `payoff_terms` reads a SETTLED contract.
    if payoff_terms(g).get("over"):
        return False
    # CARD SCORING (skat, 2026-08-09) never settles early, bonus or no bonus:
    # the floor arithmetic below counts -1 tricks off the trick INDEX, which is
    # a different game. If the shelf ever reopens for skat it needs its own
    # bound (worst case: forced to win every remaining trick at -2 each).
    if uses_card_points(mode_of(g)):
        return False
    # NEVER STOP WITH A SINGLE TRICK LEFT. Cutting the round one trick from home
    # saves nothing and costs the players the hand's last beat -- and that beat
    # is where the Null consolation and the shortfall are still live, so it is
    # the trick most worth seeing. Below two remaining, play it out.
    if NTRICKS - g["trick"] <= 1:
        return False
    neg_left = sum(1 for t in range(g["trick"], NTRICKS) if trick_value(t) < 0)
    target = skat_target(g) if mode_of(g) == "skat" else g["auction"]["level"]
    # The declarer's floor from here: they win no more +2 tricks and are forced
    # to take every remaining -1.
    return g["pts"][decl] - neg_left >= target


# --- scoring ---------------------------------------------------------------


def contract_score(level: int, declarer_pts: int) -> tuple[int, int]:
    """(declarer score, defender score) for a settled CLASSIC contract.

    Make it and the declarer scores N squared, plus 1 for every trick point past
    N. Fall short and the DEFENDER scores N plus 4 for every point the declarer
    finished below it. Only this scores -- the trick points are the yardstick,
    and now also the margin.

    DELEGATES rather than restating the arithmetic. It used to hold its own copy
    of the make/set rule, which was fine while that rule was two lines and never
    changed; the overtrick bonus is exactly the kind of change that lands in one
    copy and not the other, and this one is reachable from the tests only, so the
    drift would have shown up as a test agreeing with itself.
    """
    value = payoff(_terms_for("classic", 0, level), declarer_pts, True)
    return (value, 0) if value >= 0 else (0, -value)


def payoff_terms(g: dict) -> dict:
    """The scoring rule as NUMBERS, in whichever currency this room pays in.

    ONE SOURCE. `_finish` scores from these, and the Hard tier's armed decision
    ships them to the browser so the solver optimises the payoff the server will
    actually apply. The alternative -- a second copy of the scoring in Rust --
    is the drift the card-play parity gate exists to prevent, in a place where
    it would show up only as the bot playing slightly wrong.

    `declarer_score - defender_score` for a final total `p`, given whether the
    declarer ever won a +2 trick:

        no +2 trick  ->  +null
        p >= target  ->  +make + over x (p - target)
        otherwise    ->  -(set_base + short x (target - p))

    `over` is the overtrick bonus for this room's mode -- see `OVER_BONUS`.
    """
    a = g["auction"]
    if mode_of(g) == "skat":
        ct = g["contract"]
        terms = _terms_for("skat", a["denom"], a["level"], ct["sharp"],
                           ct["mult"], skat_doubling(ct))
    else:
        # `mode_of`, not a literal: minor mode runs the classic auction shape
        # in its own currency, and the terms are where the currency lives.
        terms = _terms_for(mode_of(g), a["denom"], a["level"],
                           doubling=classic_doubling(g))
    return terms | {"declarer": a["declarer"]}


def classic_doubling(g: dict) -> int:
    """2 once the defender has Doubled, 1 otherwise.

    `.get` because a classic game saved before Double existed has no such key
    and is, correctly, not doubled.
    """
    return 2 if g.get("doubled") else 1


def _terms_for(mode: str, denom: int, level: int, sharp: bool = False,
               mult: int = 1, doubling: int = 1) -> dict:
    """`payoff_terms` for a contract that has NOT been agreed yet.

    The auction has to price candidates, and `payoff_terms` can only read a
    settled one off the game. Same arithmetic, taken apart so both callers get
    their numbers from one place -- a second copy is how the bot ends up ranking
    options against a scoring rule the room does not use.
    """
    over = OVER_BONUS.get(mode, OVER_BONUS[DEFAULT_MODE])
    if mode == "skat":
        stake = SKAT_BASE[denom] * level * mult * doubling
        return {"denom": denom, "level": level,
                "target": level + (SHARP_BONUS if sharp else 0),
                "make": stake, "over": over, "set_base": stake,
                "short": SHORT_PENALTY, "null": SKAT_NULL_VALUE}
    # Classic's set base is N, not N-1 (2026-08-07): breaking a contract is
    # worth its level plus the margin, rather than one less than its level. At
    # level 1 the old base contributed nothing at all, so the cheapest contract
    # -- and ~42% of openings sit at the floor -- paid the defender by the
    # margin alone. Uniformly +1, so it never reorders two set results.
    #
    # DOUBLE (classic). The defender doubles both ends -- and since the base
    # became N, "double" is now literally that on both:
    #
    #   made    N^2  ->  2 N^2      (the overtrick rate doubles with it)
    #   set       N  ->  2N
    #   Null     12  ->  12         (untouched -- see below)
    #
    # Still deliberately high risk for low reward, because the reward is linear
    # in N and the risk quadratic: at level 3 doubling wins you 3 more when it
    # lands and costs 9 more when it does not, and the ratio worsens every
    # level. It is priced to be worth taking only against a contract you are
    # confident is going down -- see `apply_double`.
    #
    # NULL IS NOT DOUBLED, and that is the same argument skat's Kontra makes:
    # doubling a consolation would have the defender's own bet reward the very
    # outcome it was betting against.
    # MINOR shares every shape below -- N^2 make, set base N, the Double and its
    # ramp -- and differs in the two prices that are re-anchored to its smaller
    # scale rather than copied: the consolation (MINOR_NULL_MAKE) and the
    # per-point set rate (MINOR_SHORT_PENALTY).
    null = MINOR_NULL_MAKE if mode == "minor" else NULL_MAKE
    short = MINOR_SHORT_PENALTY if mode == "minor" else SHORT_PENALTY
    if doubling > 1:
        return {"denom": denom, "level": level, "target": level,
                "make": level * level * doubling, "over": over * doubling,
                "set_base": level * doubling, "short": short,
                "ramp": DOUBLE_RAMP, "null": null}
    return {"denom": denom, "level": level, "target": level,
            "make": level * level, "over": over, "set_base": level,
            "short": short, "ramp": 0, "null": null}


def pass_options(g: dict) -> list[dict]:
    """PASSING, PRICED -- the option both bots used to value at zero.

    A pass is not worth nothing. It hands the standing contract to the OPPONENT
    at their price, so it is worth exactly minus what that contract pays them.
    Valuing it at zero is why neither tier can SACRIFICE: a sacrifice is a
    contract that prices negative, bought because passing prices worse, and a
    bot comparing against zero can never reach that conclusion. It also makes
    the bot buy contracts it should decline, whenever the opponent's standing
    contract was worse for them than a bad one is for us.

    The option is priced from the OPPONENT's side and carries `opp: True`, which
    tells the search two things: solve this denomination with the OTHER seat
    declaring (they lead, which is worth ~0.93 points and cannot be reused from
    our own solve), and negate the result, because every option in the list is
    signed for the seat being asked.

    Passing out with nothing standing -- only skat allows it -- is a REDEAL, and
    a redeal is worth 0 by symmetry: a fresh deal neither seat has seen. Priced
    as such rather than omitted, so "pass" is always in the list when it is
    legal and the search never has to special-case its absence.
    """
    a = g["auction"]
    skat = mode_of(g) == "skat"
    mv = {"kind": "pass"}
    if a["declarer"] < 0:
        # Nothing standing. Skat throws the hand in; classic cannot get here.
        return [{"denom": 0, "level": 0, "target": 0, "make": 0, "over": 0,
                 "set_base": 0, "short": 0, "null": 0, "redeal": True,
                 "move": mv}]
    if not skat:
        return [_terms_for(mode_of(g), a["denom"], a["level"],
                           doubling=classic_doubling(g))
                | {"opp": True, "move": mv}]
    # Skat: the number is a price and the winner has not named a game yet, so
    # what passing concedes is the BEST declaration that number buys them. One
    # option per candidate, each priced for them -- the search takes the worst
    # for us, which is the same as assuming they declare well.
    return [_terms_for("skat", d["denom"], d["min_level"])
            | {"opp": True, "move": mv}
            for d in skat_declarable(a["value"])]


def auction_payoff_options(g: dict) -> list[dict]:
    """Every action open to the seat on turn, PRICED, each carrying ITS MOVE.

    The Hard tier's auction ranks these. The server owns which options exist,
    what each pays AND the move each one is, so the browser holds no rule at all
    -- it picks an index and sends back the move it was handed. That is the same
    discipline the card search follows (the server ships `payoff_terms` rather
    than the scoring being reimplemented in Rust), applied to a decision with
    four different move shapes across two auction modes.

    The list is POSITIONAL: its index is the pooling key across the worker pool
    and the answer that comes back, so it is built exactly once, here.
    """
    phase = g["phase"]
    skat = mode_of(g) == "skat"
    out = []
    if phase == "auction":
        opt = auction_options(g)
        if skat:
            # A number is only a price: what it is WORTH is the best game it
            # buys, so each rung is priced at its cheapest declaration in every
            # denomination that can still reach it.
            for v in opt["values"]:
                for d in skat_declarable(v):
                    out.append(_terms_for("skat", d["denom"], d["min_level"])
                               | {"move": {"kind": "bid", "value": v}})
        else:
            for lvl, d in opt["bids"]:
                out.append(_terms_for(mode_of(g), d, lvl)
                           | {"move": {"kind": "bid", "level": lvl, "denom": d}})
        if opt["may_pass"]:
            out.extend(pass_options(g))
    elif phase == "declare":
        for d in skat_declarable(g["auction"]["value"]):
            for lvl in range(d["min_level"], MAX_LEVEL + 1):
                for sharp in (False, True):
                    mult = skat_multiplier(g["contract"]["hand"], sharp, False)
                    out.append(_terms_for("skat", d["denom"], lvl, sharp, mult)
                               | {"move": {"kind": "declare", "denom": d["denom"],
                                           "level": lvl, "sharp": sharp, "open": False}})
    elif phase == "double":
        # TWO priced branches, not one option plus an implicit "declining is
        # worth zero". Skat's Kontra can get away with the latter because it
        # doubles both ways symmetrically, so only the SIGN of the standing
        # contract decides it. Classic's Double is deliberately lopsided --
        # a made contract doubles, a set one only steps N-1 -> 2N -- so the
        # decision is a comparison between two different payoffs and the search
        # has to see both. Priced from the DECLARER's side like every other
        # option; the asker is the defender and the client flips the sign.
        a = g["auction"]
        for on in (True, False):
            out.append(_terms_for(mode_of(g), a["denom"], a["level"],
                                  doubling=2 if on else 1)
                       | {"move": {"kind": "double", "on": on}})
    elif phase in ("kontra", "re"):
        # ONE option: the contract exactly as it stands. Its value signed for
        # the seat being asked is the whole decision -- a defender doubles a
        # contract that is bad for the declarer, and the `on: False` branch
        # needs no evaluation because declining is worth precisely zero.
        a, ct = g["auction"], g["contract"]
        kind = "re" if phase == "re" else "kontra"
        out.append(_terms_for("skat", a["denom"], a["level"], ct["sharp"],
                              ct["mult"], skat_doubling(ct))
                   | {"move": {"kind": kind, "on": True},
                      "decline": {"kind": kind, "on": False}})
    return out


#: The terms table's key for a settled classic contract. Mirrored by
#: `auc_search::Bid::key` in Rust; eight bits for the denomination because Grand
#: is 6 and skat's own key space is the bare ladder value, so the two modes
#: never share a table and the encoding only has to be unambiguous within one.
def _settlement_key(mode: str, denom: int, level: int, value: int) -> int:
    return value if mode == "skat" else (level << 8) | denom


def auction_search_payload(g: dict) -> dict | None:
    """THE EXPERT TIER'S AUCTION, as data: where the bidding stands, the
    legality knobs, and a priced row per settlement still reachable.

    Hard prices each option MYOPICALLY -- "if I end up declaring this contract,
    what does it pay" -- which cannot underbid to CAP an auction and cannot
    judge re-entering after being overtaken, because both of those are questions
    about the opponent's reply. Expert minimaxes the auction tree instead
    (`rust-cores/dissonance-core/src/auc_search.rs`), and this is everything it
    needs beyond the view it already gets.

    THE SPLIT IS THE SAME ONE `payoff_terms` MAKES. The search mirrors the
    auction's LEGALITY (which is a small, stable rule set, gated by
    `tests/test_expert.py` replaying `auction_options` against it) and mirrors
    none of its SCORING: every leaf price is a row built here by `_terms_for`,
    so changing a payoff still moves the bot with no bot code at all.

    Returns None outside the auction. The other client-searched phases --
    `declare`, `kontra`, `re`, `double` -- have no reply after them, so Hard's
    pricing is already exactly right there and Expert is deliberately identical.
    """
    if g["phase"] != "auction":
        return None
    a = g["auction"]
    skat = mode_of(g) == "skat"
    # `rules.mode` names the auction's SHAPE, which is what the search tree
    # branches on -- minor mode runs the classic auction and ships "classic"
    # with its own `max_level`, so the mirror needs no third arm and an older
    # wasm reads the payload without a new string to choke on. The CURRENCY
    # difference rides in the priced rows below, as always.
    rules = {"mode": "skat" if skat else "classic",
             "min_level": MIN_LEVEL, "max_level": max_level_for(mode_of(g)),
             "max_raise": MAX_RAISE, "top_denom": GRAND if skat else NOTRUMP,
             "ladder": [v for v in SKAT_VALUES if v > a["value"]] if skat else []}
    # Only settlements the auction can still REACH. The bidding only ever
    # ascends, so everything below the standing bid is unreachable and would be
    # ~60 rows of JSON re-broadcast on every room update for nothing. The
    # standing bid itself stays: that is what a pass settles on.
    terms = []
    if skat:
        state = {"level": 0, "denom": 0, "value": a["value"],
                 "declarer": a["declarer"], "used": [0, 0],
                 "passes": a.get("passes", 0), "to_act": a["to_act"]}
        for v in SKAT_VALUES:
            if v < a["value"]:
                continue
            # A number is a PRICE, not a shape -- the winner names their game
            # afterwards -- so a rung carries one row per declaration it buys
            # and the search takes the declarer's best. Same approximation
            # `pass_options` already makes: each denomination at its cheapest
            # level that clears the number.
            for d in skat_declarable(v):
                terms.append(_terms_for("skat", d["denom"], d["min_level"])
                             | {"key": _settlement_key("skat", d["denom"], 0, v)})
    else:
        # `denom` is -1 while nothing stands, which is a sentinel this side and
        # an unsigned field on the wire. It is unread when `level` is 0, so it
        # is normalised rather than encoded: a -1 read back as 255 would be a
        # denomination the rank comparison silently treats as the highest there
        # is.
        state = {"level": a["level"], "denom": max(a["denom"], 0), "value": 0,
                 "declarer": a["declarer"], "used": list(a["used"]),
                 "passes": 0, "to_act": a["to_act"]}
        for lvl in range(max(MIN_LEVEL, a["level"]), max_level_for(mode_of(g)) + 1):
            for d in range(NOTRUMP + 1):
                terms.append(_terms_for(mode_of(g), d, lvl)
                             | {"key": _settlement_key("classic", d, lvl, 0)})
    return {"state": state, "rules": rules, "terms": terms}


def payoff(terms: dict, declarer_pts: int, declarer_scored: bool) -> int:
    """Apply `payoff_terms`. Null is checked FIRST and wins -- it can never
    collide with a make, since only +2 tricks add points.

    `over` and `ramp` default to 0 so terms written before they existed -- a
    fixture, an armed decision replayed off an old save -- still price at the
    flat rates rather than raising a KeyError.

    `ramp` is the Double's escalator: the first point short costs
    `short + ramp`, the second `short + 2 ramp`, and so on, which sums to
    `short x s + ramp x s(s+1)/2`. Zero on every undoubled contract, so an
    undoubled set is the same flat arithmetic it always was.
    """
    if not declarer_scored:
        return terms["null"]
    if declarer_pts >= terms["target"]:
        return terms["make"] + terms.get("over", 0) * (declarer_pts - terms["target"])
    s = terms["target"] - declarer_pts
    return -(terms["set_base"] + terms["short"] * s
             + terms.get("ramp", 0) * s * (s + 1) // 2)


def _split(value: int, declarer: int) -> list[int]:
    """A signed payoff back into the two-sided score row. Exactly one side ever
    scores, which is what makes the difference a faithful single number."""
    scores = [0, 0]
    scores[declarer if value >= 0 else 1 - declarer] = abs(value)
    return scores


def match_of(g: dict) -> dict | None:
    """The running match, or None for a save written before matches existed.

    Every reader goes through this rather than `g["match"]`: a round already in
    progress when this shipped has no match dict, and it must finish the way it
    started -- as the whole game -- not crash and not silently acquire a target
    it was never being played to.
    """
    m = g.get("match")
    return m if isinstance(m, dict) else None


def opener_for_round(m: dict) -> int:
    """Who opens the bidding in round `m["round"]`. It simply alternates.

    DERIVED from the round number, never flipped from whatever the last deal
    happened to use -- because not every deal is a round. A skat hand both
    players pass out is thrown in and dealt again, and a redeal that flipped
    the opener would knock the alternation out of phase, so which seat opened
    round 4 would depend on how many hands got passed out along the way.
    Derived, it is the same answer no matter what the deal did.
    """
    return (int(m.get("first_opener", 0)) + int(m.get("round", 1)) - 1) % 2


def _match_for_next_deal(g: dict, advance: bool) -> dict:
    """The match dict the next deal should carry, and the seat that opens it.

    `advance` is what separates the two ways a new deal happens: `next_round`
    counts, a pass-out redeal does not.
    """
    m = dict(match_of(g) or {})
    if "first_opener" not in m:
        # A match saved before the opener was derived. Recover the phase from
        # where it actually is, rather than resetting it to seat 0 and skipping
        # or repeating a turn mid-match.
        m["first_opener"] = (int(g.get("opener", 0)) - int(m.get("round", 1)) + 1) % 2
    if advance:
        m["round"] = int(m.get("round", 1)) + 1
    return m


def _round_summary(g: dict, m: dict, res: dict) -> dict:
    """One line of the match's scorecard, off the result row that was just built.

    DERIVED from `res` rather than recomputed from `g`: made/null/target are
    rules, and a second reading of them here would be a second copy of the
    scoring -- the exact drift `payoff_terms` exists to prevent. This only
    reshapes what `_finish` already decided.

    Deliberately small, because it is stored per round for the life of the
    match: the contract, the declarer's trick points against what they
    promised, and who took the round.
    """
    row = {
        "round": int(m.get("round", 1)),
        "declarer": res.get("declarer", -1),
        "level": res.get("level", 0),
        "denom": res.get("denom", -1),
        # Trick points for BOTH seats -- they sum to POOL over a completed
        # round, but an abandoned one stops wherever it stopped.
        "pts": list(g["pts"]),
        # What the declarer had to score. Skat's Sharp announcement raises it
        # above the level, so it is the result row's number and not the level.
        "target": res.get("target", res.get("level", 0)),
        "made": bool(res.get("made")),
        "null": bool(res.get("null")),
        # THE DEFENDER'S BET, as the MULTIPLIER rather than either mode's word
        # for it: classic Doubles, skat Kontras and the declarer may Re on top,
        # and all three do the one thing the scorecard has to show -- this
        # round was played for 2x or 4x. Without it a doubled round sat in the
        # match box as an ordinary line with a surprising number beside it,
        # which is exactly the round a reader most wants explained.
        #
        # Read off `res`, which already carries skat's `doubling` (1/2/4) and
        # classic's `doubled` (a bool), so nothing re-derives the rule here.
        "doubling": int(res.get("doubling") or (2 if res.get("doubled") else 1)),
        "scores": [int(res["scores"][0]), int(res["scores"][1])],
    }
    if res.get("abandoned_by") is not None:
        row["abandoned"] = True
        # No deal snapshot on an abandoned round, deliberately. There is nothing
        # to review: the play did not happen, so "what perfect card play was
        # worth" has no actual result to sit beside, and a comparison against a
        # forfeit would read as a verdict on cards nobody played. It also keeps
        # the one case where a round is banked MID-PLAY from putting a live
        # hand anywhere near the wire.
        return row
    # The reviewable position. Only ever added HERE, at bank time, which is what
    # makes it safe: `g["deal"]` itself is internal and never leaves the server
    # (it holds BOTH hands, so shipping it during play would hand a seat the
    # opponent's cards), while a banked round is finished and wholly public --
    # the same reason `match` rides on the wire at all.
    deal = g.get("deal")
    if deal:
        row["deal"] = deal
    return row


def _bank_round(g: dict, res: dict) -> None:
    """Add a finished round to the match: its scores, and its scorecard line.

    Called by both `_finish` paths and by the abandon path, because all three
    produce a scored round and a match that has to notice.

    `rounds` is `setdefault`ed rather than created in `new_game` for the same
    reason `match_of` exists: a match already in progress when this shipped has
    no scorecard, and it must go on banking rounds rather than KeyError. Its
    earlier rounds are simply not in it -- there is nowhere to recover them
    from, and the running total was always the thing being played for.
    """
    m = match_of(g)
    if not m:
        return
    scores = res["scores"]
    for i in (0, 1):
        m["scores"][i] += int(scores[i])
    m["over"] = max(m["scores"]) >= m["target"]
    m.setdefault("rounds", []).append(_round_summary(g, m, res))


def _match_result_keys(g: dict) -> dict:
    """What every result row says about the match it sits in.

    On the row rather than only in `g["match"]` because the lobby history reads
    a STORED result and never the live game, so the final standing has to be
    written into the row that outlives the room.
    """
    m = match_of(g)
    if not m:
        return {}
    return {
        "match_scores": list(m["scores"]),
        "match_target": m["target"],
        "match_over": bool(m["over"]),
        "round": m["round"],
    }


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
    terms = payoff_terms(g)
    target = terms["target"]
    # The consolation. A declarer who took no positive trick cannot have
    # reached any target (only positive tricks add points -- under card scoring
    # every trick they DID win was worth -2), so it always REPLACES a set -- it
    # is never a bonus on top of a made contract.
    null = g["etricks"][decl] == 0
    made = (not null) and dpts >= target
    short = 0 if (null or made) else target - dpts
    # Points past the target, and what they were worth. On the row rather than
    # recomputed in the panel, because the panel prints the arithmetic and the
    # arithmetic has exactly one owner.
    over = (dpts - target) if made else 0
    scores = _split(payoff(terms, dpts, not null), decl)
    g["phase"] = "over"
    res = {
        # A settled round can stop short of thirteen tricks; the UI says so
        # rather than leaving a half-played board looking like a bug.
        "ended_early": g["trick"] < ntricks_in(g),
        "mode": "skat",
        "declarer": decl,
        "bid": a["value"],
        "level": a["level"],
        "denom": a["denom"],
        # The base price of the declared denomination. It rides the result so
        # the review can show base x level = value -- the one step of the skat
        # arithmetic that used to be invisible, which left a made contract
        # printing a bare number where classic prints "3 x 3 = 9".
        "base": SKAT_BASE[a["denom"]] if a["denom"] in SKAT_DENOMS else 0,
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
        # The per-point set rate, off the SAME terms this round was scored
        # with -- the result panel prints the arithmetic, and it had a literal
        # 4 in it that survived the 4 -> 5 move unnoticed.
        "short_rate": terms["short"],
        "over": over,
        "over_bonus": terms.get("over", 0),
        "scores": scores,
    }
    # Banked from the result row, so the match's scorecard says exactly what the
    # panel says -- then the match keys are merged back onto the row.
    _bank_round(g, res)
    g["result"] = _match_result_keys(g) | res


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
    short = 0 if (null or made) else a["level"] - dpts
    terms = payoff_terms(g)
    # Points past the target, and what each was worth. On the row rather than
    # recomputed in the panel, because the panel prints the arithmetic and the
    # arithmetic has exactly one owner.
    over = (dpts - a["level"]) if made else 0
    scores = _split(payoff(terms, dpts, not null), decl)
    g["phase"] = "over"
    res = {
        # A settled round can stop short of thirteen tricks; the UI says so
        # rather than leaving a half-played board looking like a bug. Always
        # False while overtricks pay -- see `_score_is_settled`, which is
        # shelved rather than removed, so the key and its reader stay.
        "ended_early": g["trick"] < ntricks_in(g),
        # The room's real mode ("classic" or "minor" -- skat has its own
        # finisher), so the history row and the result panel narrate the game
        # that was played rather than the shape it borrowed.
        "mode": mode_of(g),
        "declarer": decl,
        "level": a["level"],
        "denom": a["denom"],
        # What the declarer had to score. Identical to the level in classic
        # mode -- it is on the row so the scorecard and the panel can read one
        # key in both modes rather than knowing which mode hides it where.
        "target": terms["target"],
        "null": null,
        # Off the SAME terms `_finish` scored with (12 classic, 6 minor), so
        # the panel cannot narrate a consolation the room did not pay.
        "null_value": terms["null"],
        # The Double, and the two numbers the review needs to show its effect:
        # what a made contract paid and what a set one paid. Both come off the
        # SAME terms `_finish` scored with, so the panel cannot narrate an
        # arithmetic the room did not apply.
        "doubled": bool(g.get("doubled")),
        # WHAT THE DOUBLE WAS ACTUALLY WORTH: this same round, scored as if the
        # defender had let it stand. The panel used to narrate the Double by
        # its set BASE ("the set base went 4 -> 10"), which told a reader
        # nothing about the bet they had just watched -- and quoted the old
        # N-1 base at that, a number the game stopped charging in 2026-08.
        # The honest number is the difference the bet made, and it is one
        # `payoff` call against the undoubled terms rather than any new rule.
        #
        # Signed for the declarer, exactly like `payoff` itself. Doubling
        # scales both ends and the ramp only adds, so it can never flip WHO
        # won -- the panel compares magnitudes against the same seat.
        "undoubled": payoff(_terms_for(mode_of(g), a["denom"], a["level"]),
                            dpts, not null),
        "make_value": payoff_terms(g)["make"],
        "set_base": payoff_terms(g)["set_base"],
        # The two rates the review needs to spell the shortfall out as the sum
        # it actually is. Both off the SAME terms `_finish` scored with.
        "short_rate": payoff_terms(g)["short"],
        "ramp": payoff_terms(g).get("ramp", 0),
        "declarer_pts": dpts,
        "declarer_etricks": g["etricks"][decl],
        "made": made,
        "short": short,
        "over": over,
        "over_bonus": terms.get("over", 0),
        "scores": scores,
    }
    _bank_round(g, res)
    g["result"] = _match_result_keys(g) | res


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
        # Nobody played a contract out, so nothing was scored over one. Both
        # modes carry the pair now, so it sits here rather than in the skat block.
        "over": 0,
        "over_bonus": 0,
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
    # Walking out ends the MATCH, not just the round. The forfeit is banked so
    # the standing is honest, and then the match is closed regardless of the
    # target -- there is nobody left to play the rest of it.
    _bank_round(g, res)
    m = match_of(g)
    if m:
        m["over"] = True
    res.update(_match_result_keys(g))
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
        # "double" is in here with swap and play: the classic declarer has
        # already been shown the talon by then, and dropping it for one phase
        # would take back information it legitimately holds -- and hand the
        # Hard tier's Double decision a different out-of-play set than the
        # trick-1 decision immediately after it.
        else g["phase"] in ("swap", "double", "play")))
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
        "piles": [_pile_view(g, q, seat) for q in range(n_hands(g))],
        # THE DUMMY, wholly public from the deal -- its hand to both players,
        # since shared information advantages neither bidder and turns the
        # auction into a judgement about "my hand plus that one". Its PILES go
        # through the same redaction as anyone's (above), so its outer bottoms
        # are hidden from everyone including the declarer: a fully open dummy
        # would make the endgame a double-dummy problem for both seats.
        # None outside dummy mode, which is how the board knows to render two
        # seats rather than three.
        "dummy": (sorted(g["hands"][DUMMY_POS]) if has_dummy(mode_of(g))
                  else None),
        # Who is playing it. The declarer commands two of the three hands,
        # which is the whole mechanic, so the board says so out loud.
        # WHOEVER COMMANDS IT NOW, not the declarer: under `DUMMY_COMMAND =
        # "leader"` that changes hands with every trick, and the board's
        # "Dummy (X's)" label plus whether its cards are clickable both read
        # this one field.
        # ...and NOBODY commands it before the cards are out. During the
        # auction `leader` still holds the opener, which is meaningless there,
        # so a label built on it would claim an owner the rules have not
        # chosen yet. None until play starts.
        "dummy_seat": (side_of(g, DUMMY_POS)
                       if has_dummy(mode_of(g)) and g["phase"] == "play"
                       else None),
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
        # Classic's Double. Wholly public: it is a bet announced at the table,
        # and both seats have to know what the round is now worth.
        "doubled": bool(g.get("doubled")) if not skat else None,
        "looked": bool(g.get("looked")) if skat else None,
        "redeals": g.get("redeals", 0) if skat else 0,
        # The match this deal sits in. Wholly public -- both players' running
        # totals are on the table in any card game played to a target. None on
        # a save from before matches existed, which the UI reads as one round.
        "match": dict(match_of(g)) if match_of(g) else None,
        # Face-up only under an Open announcement; None every other time.
        "opp_hand": sorted(g["hands"][opp]) if (open_now and opp == decl) else None,
        "trump": g["trump"],
        "trick": g["trick"],
        # In card-scoring mode a trick has no value until both cards are down,
        # so this reads 0 there and the client labels the trick off the CARDS
        # (`card_values` below). Parity modes ship the trick's fixed value.
        "trick_value": (0 if uses_card_points(mode_of(g))
                        else trick_value_in(g, g["trick"])
                        if g["phase"] == "play" else 0),
        # What an even trick pays in this room -- the ONE number the classic
        # parity baked into every consumer. The client-side searcher reads it
        # into `State.even` (`wire.rs`, optional, defaulting to classic's 2),
        # and the board labels tricks with it instead of a hardcoded +2.
        "even_val": even_value(mode_of(g)),
        # CARD SCORING (2026-08-09). True in skat mode: captured cards score
        # (`CARD_VALUES`, shipped so the client renders the per-rank worth
        # rather than hardcoding it). The client-side searcher reads the flag
        # into `State.cards` -- a wasm too old for it (`wire < 3`) would search
        # the PARITY game with nothing red anywhere, which is why the server
        # refuses to arm a skat room for an older client
        # (`_handle_client_ai_ready`) and the worker refuses the payload.
        "card_pts": uses_card_points(mode_of(g)),
        # SLICED TO THE DECK THIS MODE DEALS, and that is a wire-compatibility
        # decision rather than tidiness. A 32-card room still ships the same
        # eight entries it always did, indexed 7..A, so a bundle cached from
        # before the wide deck goes on labelling skat's corner chips correctly;
        # a dummy room ships all ten. The client picks its offset off the LENGTH
        # (`10 - card_values.length`), which needs no new field and no version.
        "card_values": (wire_card_values(mode_of(g))
                        if uses_card_points(mode_of(g)) else None),
        # MUST HEAD THE TRICK. The flag is the ROOM's rule (so the board can
        # say so before a card is led); `must_head_now` is whether it is
        # actually taking an option off this seat this instant, which is what
        # the turn bar reads. Both are the engine's answers, not the client's
        # -- it holds no copy of what beats what (its `beats` is label-only and
        # does not know Grand). The searcher reads the room flag into
        # `State.head`; a wasm too old for it (`wire < 4`) would propose cards
        # this room refuses, so the server will not arm a skat room for one.
        "must_head": must_head_mode(mode_of(g)),
        "must_head_now": must_head_binds(g, seat),
        "leader": g["leader"],
        "led": g["led"],
        "pts": list(g["pts"]),
        "etricks": list(g["etricks"]),
        "history": [list(h) for h in g["history"]],
        "result": g["result"],
        # The out-of-play cards stay secret until the round is done.
        "out": list(g["out"]) if over else None,
        # `shown` is the out-of-play set the client searcher reads (see
        # `apply_swap`); `shown_at_deal` is what the declarer was actually shown,
        # which only the round-end reveal wants. Same redaction for both.
        "shown": list(g["shown"]) if sees_shown else None,
        "shown_at_deal": (list(g.get("shown_at_deal") or g["shown"])
                          if sees_shown else None),
        # Whether a swap happened is public; which cards moved is not -- until
        # the round is over, when everything opens up. `.get` because a save
        # written before these keys existed can still be mid-round on load.
        "swapped": g["swapped"],
        "swap_take": g.get("swap_take") if over else None,
        "swap_give": g.get("swap_give") if over else None,
        # The POSITION on turn (the dummy's is 2) and the PLAYER who acts for
        # it. Both, because the board points at a seat while the turn belongs
        # to a person, and conflating them is how a dummy room would tell the
        # defender it is their move.
        "to_play": to_play(g) if g["phase"] == "play" else None,
        "turn_seat": playing_seat(g) if g["phase"] == "play" else None,
        # The cards already down in this trick, [position, card] in play
        # order, so the board can lay out a three-card trick without
        # reconstructing it from `history`.
        "plays": [list(p) for p in (g.get("plays") or [])],
        "tricks": ntricks_in(g),
        "legal": legal_moves(g, seat) if g["phase"] == "play" else [],
        "options": auction_options(g) if g["phase"] == "auction" else None,
        "swap": swap_options(g) if g["phase"] == "swap" and seat == decl else None,
        # Skat's post-auction prompts, each to exactly one seat.
        "talon": talon_options(g) if g["phase"] == "talon" and seat == decl else None,
        "declare": declare_options(g) if g["phase"] == "declare" and seat == decl else None,
    }
    return v


# --- turn / seat helpers (used by main.py) ---------------------------------


def round_over(g) -> bool:
    """This DEAL is scored. There may well be another one coming."""
    return bool(g) and g.get("phase") == "over"


def is_over(g) -> bool:
    """The MATCH is decided -- which is what ends the room.

    `phase == "over"` is a round ending, and between rounds the room is still
    live: it keeps its socket, its history row stays out of the finished list,
    and either seat may deal the next one. A save from before matches existed
    has no match dict and ends where it always did, at the end of its round.
    """
    if not (g and g.get("phase") == "over"):
        return False
    m = match_of(g)
    return bool(m["over"]) if m else True


def may_act(g, pid) -> bool:
    """Is this player allowed to send a move right now?

    Between rounds the answer is EITHER seat, which the single-seat turn model
    cannot express -- so the question lives here rather than main.py comparing
    against `turn_pid` and rejecting a `next_round` that is perfectly legal.
    """
    if seat_of(g, pid) is None:
        return False
    if round_over(g):
        return not is_over(g)
    return turn_pid(g) == pid


def turn_seat(g) -> int | None:
    """Whichever seat must act next, in any phase."""
    if not g or g["phase"] == "over":
        return None
    if g["phase"] == "auction":
        return g["auction"]["to_act"]
    if g["phase"] in ("swap", "talon", "declare", "re"):
        return g["auction"]["declarer"]
    # Both of these belong to the DEFENDER: classic's Double and skat's Kontra
    # are the same decision under two names.
    if g["phase"] in ("kontra", "double"):
        return 1 - g["auction"]["declarer"]
    # `playing_seat`, not `to_play`: the two are the same number in every
    # two-seat mode, but the dummy's turn belongs to the declarer and the room
    # server reads THIS to decide whose move it is waiting for.
    return playing_seat(g)


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
    elif kind == "double":
        apply_double(g, seat, bool(move.get("on")))
    elif kind == "kontra":
        apply_kontra(g, seat, bool(move.get("on")))
    elif kind == "re":
        apply_re(g, seat, bool(move.get("on")))
    elif kind == "play":
        apply_play(g, seat, int(move["card"]))
    elif kind == "next_round":
        next_round(g, seat, move.get("round"))
    else:
        raise ValueError("unknown move")
