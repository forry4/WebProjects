# dissonance-core

Card-play engine, exact solver and bots for the parity trick-taking game.
Rust, dependency-free, `std::thread` for parallelism. Working name only.

```
cargo build --release
cargo test  --release          # 11 tests, ~27s
./target/release/bench         # solver speed
./target/release/arena pimc:8 greedy --games 200
./target/release/design 400    # contract calibration for the auction
./target/release/bisect        # isolates a solver value regression
```

## Rules as implemented

28-card deck (8 9 T J Q K A x4). Each player gets 13: **7 in hand** plus
**three piles of 2** on the table. Two cards are out of play, face down. 13
tricks. Even-numbered tricks score **+2** to the winner, odd-numbered **-1**,
so the two totals always sum to exactly **+5**.

Decisions taken while building this, each of which changes the game — flag any
you disagree with:

1. **Follow-suit is mandatory, and a pile top counts as a card you hold** for
   that purpose. (Optional-follow was rejected: with negative odd tricks it
   makes every odd trick fall deterministically to whoever leads it, killing
   7 of 13 tricks.)
2. **The trick winner leads the next trick.**
3. **The defender leads to trick 1.** Measured to be worth +0.93 pts — real
   compensation, see below.
4. Trump is standard: follow if you can; if void you may ruff or discard.
5. A pile's covered card becomes public the moment it is uncovered.
6. The **middle** pile's bottom card is face-up to both players from the deal.
   The left/right bottoms are hidden from everyone, owner included.
7. The two out-of-play cards are unknown to both players until the end.

## Hidden information

13 of 28 cards are unknown to a player at the deal: the opponent's 7 in hand,
four covered side-pile bottoms (two of them their own), and the two out of
play.

**Piles launder voids.** Failing to follow suit proves a player held none of
that suit *among hand + pile tops*. Hands only shrink, so the **hand** void is
permanent and safe to assert forever — but a covered pile bottom may still be
that suit and will become playable later. The inference is strictly weaker than
in a plain trick game, and `view.rs` asserts it only against the hand.

## Bots

| bot | what it is |
|---|---|
| `random` | uniform legal move |
| `greedy` | one-trick heuristic: take +2 tricks cheaply, shed -1 tricks expensively |
| `pimc:K` | K determinizations, each solved exactly, best average wins |
| `oracle` | cheats — solves the real deal. The strength ceiling. |

`oracle` is the only bot that touches `Bot::observe_truth`, so "does this bot
see hidden cards" is answerable by grep.

## Measured

Paired arenas: every deal is played twice with seats swapped, so deal luck
cancels. Two identical deterministic bots must read exactly 2.500 — that is
asserted as a test.

| matchup | mean pts | edge | wins |
|---|---|---|---|
| greedy vs random | 5.072 | +2.572 | 84.8% |
| pimc:8 vs greedy | 3.806 | +1.306 | 69.8% |
| pimc:24 vs pimc:8 | 2.486 | -0.014 | 50.0% |
| oracle vs pimc:8 | 3.293 | +0.793 | 63.6% |

* **Determinizations saturate at 8.** More sampling buys nothing.
* **The oracle gap is 0.79 pts/round.** That is the value of the hidden
  information and the whole remaining headroom. Since sampling is saturated,
  closing it needs *inference* (opponent modelling / ISMCTS), not more of the
  same — PIMC's strategy fusion is the binding constraint.

### Calibration for the auction (400 deals, double-dummy)

Double-dummy values are an **upper** bound: both sides play with perfect
information. Treat them as the ceiling of the live range, not its mean.

* **The opening lead is worth +0.93 pts** (defender 2.967 vs declarer 2.033).
  The forcing mechanism is real: on lead to a -1 trick you play your lowest
  card and mandatory follow-suit makes the opponent eat it.
* **No denomination is better a priori** — clubs 2.051, diamonds 2.038,
  hearts 2.050, spades 2.065, no-trump 1.961. The value of choosing trump is
  entirely about fit: the *best* of the five averages 3.494 against 2.033 for
  a denomination picked blind, so the auction's "name a new trump" prize is
  worth about **+1.46**.
* **Best makeable contract**: mean 3.49; >=4 is 53.8%, >=5 is 28.1%,
  >=6 is 11.0%, >=7 is 3.5%, >=8 is 0.6%. Nothing above 8 was seen.

## Solver notes

`dd.rs` is exact minimax over a known deal, returning player 0's *future*
differential so table entries do not depend on banked points. It does not
alternate strictly — the trick winner leads next, so the same player often
moves twice in a row, which rules out negamax.

Speed: ~430k nodes and ~77 ms for a full 13-trick solve from trick 1, at a
2^20 table. Bigger tables are slower, not faster (cache misses beat the extra
hits). Techniques: MTD(f) stepping by 2 (the value's parity is fixed by how
many -1 tricks remain), static reachable-differential bounds, a best-move hint
in the table, and equivalence pruning of interchangeable hand cards.

Three bugs found here were all invisible to a passing build and caught only by
the brute-force comparison test — worth knowing before touching this file:

* **The child's window must be shifted by the trick's points.** The parent adds
  `g` to the child's result, so it must pass `(alpha-g, beta-g)`. Wide windows
  hide this; the static bounds check made it wrong on 32/40 positions.
* **The led card must count in the equivalence test.** It has already left its
  owner's holding but still ranks between cards and still decides the trick —
  without it K and J look interchangeable while the led Q sits between them.
* **Hash components must be mixed separately.** XOR-folding the pile encoding
  with the trick/leader/led word let their overlapping bit ranges alias.

`bisect` exists to re-localise exactly this class of failure: it toggles each
technique independently against brute force.
