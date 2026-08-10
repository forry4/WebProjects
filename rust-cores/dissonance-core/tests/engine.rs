use dissonance::bots::*;
use dissonance::cards::*;
use dissonance::dd::{Contract, Dd};
use dissonance::game::{play_round, Bot, Game};
use dissonance::rng::Rng;
use dissonance::state::*;
use dissonance::view::{Knowledge, View};

fn all_state_cards(s: &State) -> Vec<u8> {
    let mut v = Vec::new();
    for p in 0..2 {
        let mut m = s.hand[p];
        while m != 0 {
            v.push(m.trailing_zeros() as u8);
            m &= m - 1;
        }
        for i in 0..3 {
            for k in 0..s.pile[p][i].n as usize {
                v.push(s.pile[p][i].c[k]);
            }
        }
    }
    v
}

#[test]
fn deal_partitions_the_deck() {
    for seed in 0..200 {
        let g = Game::deal(&mut Rng::new(seed), 4, 0);
        let mut v = all_state_cards(&g.s);
        let mut m = g.out;
        while m != 0 {
            v.push(m.trailing_zeros() as u8);
            m &= m - 1;
        }
        v.sort_unstable();
        // DERIVED, never a literal. This said 28 ("26 dealt + 2 out of play")
        // from the 28-card era and was still saying it long after the deck went
        // to 32 — the target had stopped compiling, so nothing ever ran it. The
        // `rank7`/`rank9`/`rank10` features move NCARD too, and a literal is
        // wrong under three of the four builds.
        let dealt = 2 * usize::from(NDEALT);
        assert_eq!(
            v.len(),
            usize::from(NCARD),
            "{dealt} dealt + {} out of play",
            NOUT
        );
        v.dedup();
        assert_eq!(v.len(), usize::from(NCARD), "no duplicated card");
        assert_eq!(g.s.hand[0].count_ones(), 7);
        assert_eq!(g.s.hand[1].count_ones(), 7);
        for p in 0..2 {
            for i in 0..3 {
                assert_eq!(g.s.pile[p][i].n, 2);
            }
        }
    }
}

#[test]
fn scoring_is_constant_sum() {
    // POOL must be exactly the sum of the 13 trick values, whichever parity
    // is the scoring one -- +5 by default, +8 with `odd-positive`.
    let total: i32 = (0..NTRICKS).map(|t| trick_value(t) as i32).sum();
    assert_eq!(total, POOL as i32);
    let pos = (0..NTRICKS).filter(|&t| trick_value(t) == 2).count();
    let neg = (0..NTRICKS).filter(|&t| trick_value(t) == -1).count();
    assert_eq!(pos + neg, NTRICKS as usize);
    if dissonance::state::POSITIVE_IS_ODD {
        assert_eq!((pos, neg, POOL), (7, 6, 8));
        assert_eq!(trick_value(0), 2, "trick 1 is odd-numbered");
    } else {
        assert_eq!((pos, neg, POOL), (6, 7, 5));
        assert_eq!(trick_value(0), -1, "trick 1 is odd-numbered");
    }
}

#[test]
fn a_round_plays_every_card_and_scores_to_the_pool() {
    for seed in 0..300 {
        let mut a = RandomBot { rng: Rng::new(seed) };
        let mut b = GreedyBot;
        let mut g = Game::deal(&mut Rng::new(seed ^ 0x99), (seed % 5) as u8, (seed % 2) as u8);
        let pts = play_round(&mut g, &mut [&mut a, &mut b]);
        assert_eq!(g.s.trick, NTRICKS);
        assert_eq!(g.played.count_ones(), 26, "all 26 dealt cards get played");
        assert_eq!(g.played & g.out, 0, "the out-of-play pair never enters");
        assert_eq!(pts[0] + pts[1], POOL);
    }
}

#[test]
fn minor_parity_scores_plus_one_evens_and_pools_to_minus_one() {
    // The server's minor mode: `State.even == 1`. The parity itself does not
    // move -- only what an even trick PAYS -- so legality is untouched and the
    // pool follows the one number.
    assert_eq!(dissonance::state::trick_value_with(1, 1), 1);
    assert_eq!(dissonance::state::trick_value_with(0, 1), -1);
    for seed in 0..100 {
        let mut a = RandomBot { rng: Rng::new(seed) };
        let mut b = GreedyBot;
        let mut g = Game::deal(&mut Rng::new(seed ^ 0x77), (seed % 5) as u8, (seed % 2) as u8);
        g.s.even = 1;
        assert_eq!(g.s.pool(), 6 - 7, "six evens at +1 against seven -1s");
        let pts = play_round(&mut g, &mut [&mut a, &mut b]);
        assert_eq!(pts[0] + pts[1], -1);
        assert_eq!(g.s.trick, NTRICKS);
    }
}

#[test]
fn card_scoring_scores_the_cards_and_pools_to_the_deal() {
    // Skat mode's currency since 2026-08-09: a completed trick pays the sum
    // of its two cards (9/10/J/Q +2, 7/8/K/A -1), so the pool is whatever the
    // 26 dealt-in cards add up to -- deal-dependent, never the parity
    // constant by anything but coincidence.
    use dissonance::state::{card_points, CARD_POOL};
    let per_deck: i32 = (0..dissonance::cards::NCARD)
        .map(|c| card_points(c) as i32)
        .sum();
    assert_eq!(per_deck, CARD_POOL as i32);
    // The default deck: 16 cards at +2 against 16 at -1.
    assert_eq!(CARD_POOL, 16);
    let mut saw_off_constant = false;
    for seed in 0..100 {
        let mut a = RandomBot { rng: Rng::new(seed) };
        let mut b = GreedyBot;
        let mut g = Game::deal(&mut Rng::new(seed ^ 0x55), (seed % 5) as u8, (seed % 2) as u8);
        g.s.cards = true;
        let mut out_worth = 0i8;
        let mut m = g.out;
        while m != 0 {
            out_worth += card_points(m.trailing_zeros() as u8);
            m &= m - 1;
        }
        assert_eq!(g.s.pool(), CARD_POOL - out_worth, "the pool is the deal's");
        let pts = play_round(&mut g, &mut [&mut a, &mut b]);
        assert_eq!(pts[0] + pts[1], CARD_POOL - out_worth);
        assert_eq!(g.s.trick, NTRICKS);
        saw_off_constant |= pts[0] + pts[1] != POOL;
    }
    assert!(saw_off_constant, "every pool read the parity constant -- vacuous");
}

#[test]
fn a_card_scored_trick_is_worth_its_two_cards() {
    // Replay one round move by move and recount the score by hand: each
    // completed trick's delta must be card_points(led) + card_points(follow),
    // banked to the winner, with `escored` set exactly on positive tricks.
    use dissonance::state::card_points;
    for seed in 0..40u64 {
        let mut g = Game::deal(&mut Rng::new(seed + 300), (seed % 5) as u8, 0);
        g.s.cards = true;
        let mut r = Rng::new(seed ^ 0x1234);
        let mut pts = [0i8; 2];
        let mut escored = 0u8;
        while !g.over() {
            let mut m = [0u8; 16];
            let n = g.s.legal(&mut m);
            let c = m[r.below(n)];
            let led = g.s.led;
            g.apply(c);
            if led >= 0 {
                let tv = card_points(led as u8) + card_points(c);
                assert!([-2, 1, 4].contains(&tv), "impossible trick value {tv}");
                // The engine hands the winner the next lead, which is how a
                // recount identifies them without reimplementing `beats`.
                let winner = g.s.leader;
                pts[winner as usize] += tv;
                if tv > 0 {
                    escored |= 1 << winner;
                }
            }
        }
        assert_eq!(pts, g.s.pts, "seed {seed}: recount diverged");
        assert_eq!(escored, g.s.escored, "seed {seed}: escored diverged");
    }
}

#[test]
fn the_null_and_trick_searches_read_card_scoring_tricks() {
    // `null_no_even_makeable` (the duck the auction prices) means "no
    // POSITIVE trick" in whichever currency the game scores. Under card
    // scoring a positive trick is one whose two cards sum above zero, so a
    // declarer may freely win -2 tricks -- gate it against a naive recursion
    // that restates the rule from scratch.
    use dissonance::dd::Dd;
    use dissonance::state::card_points;
    fn naive_duck(s: &State, declarer: u8) -> bool {
        if s.done() {
            return true;
        }
        let mut m = [0u8; 16];
        let n = s.legal(&mut m);
        let maxing = s.to_play() == declarer;
        for i in 0..n {
            let mut t = *s;
            let completing = t.led >= 0;
            let tv = if completing {
                card_points(t.led as u8) + card_points(m[i])
            } else {
                0
            };
            t.play(m[i]);
            let fatal = completing && t.leader == declarer && tv > 0;
            let ok = !fatal && naive_duck(&t, declarer);
            if maxing && ok {
                return true;
            }
            if !maxing && !ok {
                return false;
            }
        }
        !maxing
    }
    let mut dd = Dd::new(14);
    let mut makeable = 0;
    for seed in 0..24u64 {
        let mut g = Game::deal(&mut Rng::new(seed + 700), (seed % 5) as u8, 0);
        g.s.cards = true;
        let mut r = Rng::new(seed ^ 0x77AA);
        while g.s.trick < 8 {
            let mut m = [0u8; 16];
            let n = g.s.legal(&mut m);
            g.apply(m[r.below(n)]);
        }
        for declarer in 0..2u8 {
            dd.clear();
            let fast = dd.null_no_even_makeable(&g.s, declarer as usize);
            assert_eq!(fast, naive_duck(&g.s, declarer), "seed {seed} decl {declarer}");
            makeable += fast as u32;
        }
    }
    assert!(makeable > 0, "no endgame duck was makeable -- the gate is vacuous");
}

#[test]
fn beats_mask_agrees_with_beats_over_the_whole_card_space() {
    // The mask form drives must-head's filter and sits on the solver's hottest
    // path, so it is swept exhaustively rather than sampled: within the led
    // card's own class, membership must equal `beats` exactly, and nothing
    // outside the class may ever appear (a ruff is not must-head's business).
    use dissonance::state::beats_mask;
    for trump in DENOMS {
        for led in 0..NCARD {
            let m = beats_mask(led, trump);
            let cls = esuit(led, trump);
            for follow in 0..NCARD {
                let in_mask = m & (1 << follow) != 0;
                if esuit(follow, trump) != cls {
                    assert!(!in_mask, "off-class card {follow} in the mask");
                } else {
                    assert_eq!(in_mask, beats(led, follow, trump),
                        "led {led} follow {follow} trump {trump}");
                }
            }
        }
    }
}

#[test]
fn must_head_forces_a_winner_when_one_can_follow() {
    // The rule, stated three ways over real deals: (1) with `head` off the
    // legal set is unchanged; (2) with it on, if any follow card beats then
    // EVERY legal card beats; (3) a seat that cannot follow is untouched --
    // ruffing stays optional, which is the half of the rule most easily lost.
    let mut touched = 0;
    let mut ruffs = 0;
    for seed in 0..60u64 {
        let mut g = Game::deal(&mut Rng::new(seed + 500), (seed % 5) as u8, (seed % 2) as u8);
        g.s.head = true;
        let mut r = Rng::new(seed ^ 0x5EED);
        while !g.over() {
            let mut plain = g.s;
            plain.head = false;
            let (mut a, mut b) = ([0u8; 16], [0u8; 16]);
            let na = plain.legal(&mut a);
            let nb = g.s.legal(&mut b);
            if g.s.led < 0 {
                assert_eq!(&a[..na], &b[..nb], "a lead is never constrained");
            } else {
                let led = g.s.led as u8;
                let cls = esuit(led, g.s.trump);
                let follows: Vec<u8> =
                    a[..na].iter().copied().filter(|&c| esuit(c, g.s.trump) == cls).collect();
                if follows.is_empty() {
                    assert_eq!(&a[..na], &b[..nb], "a void seat may still play anything");
                    ruffs += 1;
                } else if follows.iter().any(|&c| beats(led, c, g.s.trump)) {
                    assert!(b[..nb].iter().all(|&c| beats(led, c, g.s.trump)),
                        "seed {seed}: a non-beating card survived must-head");
                    if nb < follows.len() {
                        touched += 1;
                    }
                } else {
                    assert_eq!(follows.len(), nb, "nothing beats: the follow set stands");
                }
            }
            g.apply(b[r.below(nb)]);
        }
    }
    assert!(touched > 0, "must-head never removed an option -- the gate is vacuous");
    assert!(ruffs > 0, "no void seat arose -- the ruff half is untested");
}

#[test]
fn a_must_head_ceiling_is_inferred_and_respected_by_the_determinizer() {
    // The inference must-head buys: following without beating proves no higher
    // card of that suit is in hand. Same shape as the void gate next door, and
    // it matters for the same reason -- an unenforced ceiling has the
    // determinizer dealing back a card the opponent has already disproved.
    let mut rng = Rng::new(0xCA97);
    let mut checked = 0;
    for seed in 0..40u64 {
        let mut g = Game::deal(&mut Rng::new(seed + 800), (seed % 4) as u8, 0);
        g.s.head = true;
        let mut kn = Knowledge::default();
        let mut r = Rng::new(seed ^ 0x1CE);
        let mut capped: Option<(usize, usize, u8)> = None;
        while !g.over() && capped.is_none() {
            let p = g.s.to_play() as usize;
            let mut m = [0u8; 16];
            let n = g.s.legal(&mut m);
            let c = m[r.below(n)];
            kn.observe(&g.s, p, c);
            g.apply(c);
            for cls in 0..NFOLLOW {
                if kn.hand_cap[p][cls] < NRANK - 1 && !kn.hand_void[p][cls] {
                    capped = Some((p, cls, kn.hand_cap[p][cls]));
                }
            }
        }
        let (seat, cls, cap) = match capped {
            Some(x) => x,
            None => continue,
        };
        // The ceiling has to be TRUE of the real hand, or the inference is
        // simply wrong and every world built on it is a lie.
        let mut truth = g.s.hand[seat];
        while truth != 0 {
            let c = truth.trailing_zeros() as u8;
            truth &= truth - 1;
            if esuit(c, g.s.trump) as usize == cls {
                assert!(rank(c) <= cap,
                    "seed {seed}: inferred a ceiling the real hand breaks");
            }
        }
        let mut v = View::of(&g, 1 - seat);
        v.kn = kn;
        let mut buf = Vec::new();
        for _ in 0..16 {
            let d = v.determinize(&mut rng, &mut buf);
            let mut h = d.hand[seat];
            while h != 0 {
                let c = h.trailing_zeros() as u8;
                h &= h - 1;
                assert!(esuit(c, d.trump) as usize != cls || rank(c) <= cap,
                    "dealt a card above a ceiling the seat had proved");
            }
        }
        checked += 1;
    }
    assert!(checked > 0, "no ceiling was ever inferred -- the gate is vacuous");
}

#[test]
fn the_solver_agrees_with_itself_across_parities() {
    // The same deal solved under both parities: the minor value must equal a
    // brute recount of the minor-scored line, and the TT must not hand one
    // parity the other's answer -- the two solves share a `Dd` on purpose.
    use dissonance::dd::Dd;
    let mut dd = Dd::new(14);
    for seed in 0..20u64 {
        let g = Game::deal(&mut Rng::new(seed + 900), (seed % 5) as u8, 0);
        let classic = dd.solve(&g.s);
        let mut minor_s = g.s;
        minor_s.even = 1;
        let minor = dd.solve(&minor_s);
        // Re-ask classic AFTER the minor solve warmed the table: a poisoned
        // key would return the minor number here.
        assert_eq!(dd.solve(&g.s), classic, "seed {seed}: TT poisoned across parities");
        // Exhaustive check of the minor value on a small tail position is
        // covered by the parity fixtures; here pin the coarse invariant that
        // a minor differential is reachable by minor swings at all.
        assert!(minor.abs() <= 13, "seed {seed}: minor diff out of range");
        assert_eq!(
            (minor - minor_s.pool() as i16) % 2, 0,
            "seed {seed}: minor value off the reachable parity lattice"
        );
    }
}

#[test]
fn follow_suit_is_mandatory_and_pile_tops_count() {
    let mut rng = Rng::new(4242);
    for i in 0..300 {
        // Every trump, GRAND included -- it is the only one under which
        // following means something other than matching the suit, so a fixed
        // trump of 2 would have left the whole rule ungated here.
        let mut g = Game::deal(&mut rng, DENOMS[i % DENOMS.len()], 0);
        let mut r = Rng::new(7);
        while !g.over() {
            let p = g.s.to_play() as usize;
            let mut m = [0u8; 16];
            let n = g.s.legal(&mut m);
            assert!(n > 0 && n <= 10, "at most 7 hand + 3 pile tops");
            if g.s.led >= 0 {
                // esuit, not suit: under GRAND a ten discharges a TRUMP lead
                // and nothing else, so the raw suit would call a legal move
                // illegal on one deal in six.
                let ls = esuit(g.s.led as u8, g.s.trump);
                let have = g.s.playable(p) & follow_mask(ls, g.s.trump);
                if have != 0 {
                    for &c in &m[..n] {
                        assert_eq!(
                            esuit(c, g.s.trump),
                            ls,
                            "must follow when able, piles included"
                        );
                    }
                    assert_eq!(m[..n].len() as u32, have.count_ones());
                }
            }
            g.apply(m[r.below(n)]);
        }
    }
}

#[test]
fn trick_winner_rules() {
    // Same suit: rank decides.
    assert!(beats(card(0, 2), card(0, 5), 4));
    assert!(!beats(card(0, 5), card(0, 2), 4));
    // Off-suit at no-trump never wins.
    assert!(!beats(card(0, 0), card(1, 6), NOTRUMP));
    // A ruff wins; an off-suit non-trump does not.
    assert!(beats(card(0, 6), card(2, 0), 2));
    assert!(!beats(card(0, 6), card(1, 6), 2));
    // A trump lead is not beaten by a side suit.
    assert!(!beats(card(2, 0), card(0, 6), 2));
}

/// GRAND: the four tens are trump and belong to no suit, and the SECOND ten
/// played wins. Mirrors `test_skat.py`'s Grand block card for card — the two
/// implementations of this rule are exactly what drifts.
#[test]
fn grand_makes_the_tens_a_fifth_suit_and_the_second_one_played_wins() {
    let ten = |s: u8| card(s, TEN);
    assert_eq!(RANK_CH[TEN as usize], "T", "TEN is derived, not a literal");

    // Unrankable against each other, so the follower takes it -- both ways
    // round, for every pair.
    for a in 0..4u8 {
        for b in 0..4u8 {
            if a != b {
                assert!(beats(ten(a), ten(b), GRAND), "the second ten wins");
            }
        }
    }
    // A ten ruffs from anywhere; nothing over-ruffs a ten lead.
    assert!(beats(card(3, 7), ten(0), GRAND));
    assert!(!beats(ten(0), card(3, 7), GRAND));
    // A ten is NOT a card of its own suit: it ruffs a diamond lead rather than
    // following it, and a diamond cannot beat it.
    assert!(beats(card(1, 7), ten(1), GRAND));
    assert!(!beats(ten(1), card(1, 7), GRAND));
    // Side suits behave exactly as at no-trump.
    assert!(beats(card(1, 2), card(1, 5), GRAND));
    assert!(!beats(card(1, 5), card(0, 7), GRAND));

    // Classes, and the masks built from them.
    assert_eq!(esuit(ten(1), GRAND), TRUMP_CLASS);
    assert_eq!(esuit(card(1, 0), GRAND), 1);
    assert_eq!(esuit(ten(1), NOTRUMP), 1, "only GRAND moves a ten");
    assert_eq!(follow_mask(TRUMP_CLASS, GRAND), TEN_MASK);
    assert_eq!(follow_mask(1, GRAND).count_ones(), NRANK as u32 - 1);
    assert_eq!(follow_mask(1, NOTRUMP), SUIT_MASK[1]);
}

/// Every other contract plays EXACTLY as it did before Grand existed. Asserted
/// over the whole card space rather than sampled: `esuit` sits on the hottest
/// path in the solver, and a regression here is a different game, not a worse
/// bot.
#[test]
fn no_other_contract_moved_when_grand_arrived() {
    for &trump in &[0u8, 1, 2, 3, NOTRUMP] {
        for led in 0..NCARD {
            for follow in 0..NCARD {
                let (ls, fs) = (suit(led), suit(follow));
                let want = if fs == ls {
                    rank(follow) > rank(led)
                } else if trump < NOTRUMP {
                    fs == trump && ls != trump
                } else {
                    false
                };
                assert_eq!(beats(led, follow, trump), want, "{led} {follow} {trump}");
            }
        }
    }
}

/// A trump void in a Grand game is a real, recordable fact — and it was the
/// thing a `[bool; 4]` `hand_void` would have silently dropped, leaving the
/// determinizer dealing tens into a hand that had proved it held none.
#[test]
fn a_grand_trump_void_is_inferred_and_respected_by_the_determinizer() {
    let mut rng = Rng::new(0xB0A7);
    let mut g = Game::deal(&mut rng, GRAND, 0);
    let mut kn = Knowledge::default();

    // Drive to a position where someone showed out of trump, or ran out of deal.
    let mut r = Rng::new(11);
    let mut seen = false;
    while !g.over() {
        let p = g.s.to_play() as usize;
        let mut m = [0u8; 16];
        let n = g.s.legal(&mut m);
        let c = m[r.below(n)];
        kn.observe(&g.s, p, c);
        g.apply(c);
        if kn.hand_void[0][TRUMP_CLASS as usize] || kn.hand_void[1][TRUMP_CLASS as usize] {
            seen = true;
            break;
        }
    }
    assert!(
        seen,
        "no trump void arose -- with four tens against thirteen tricks one \
         always does, so this is the harness failing, not the rule"
    );

    let void_seat = if kn.hand_void[0][TRUMP_CLASS as usize] { 0 } else { 1 };
    let mut v = View::of(&g, 1 - void_seat);
    v.kn = kn;
    let mut buf = Vec::new();
    for _ in 0..16 {
        let d = v.determinize(&mut rng, &mut buf);
        assert_eq!(
            d.hand[void_seat] & TEN_MASK,
            0,
            "dealt a ten into a hand that showed out of trump"
        );
    }
}

/// Reference minimax with no table, no pruning, no move ordering.
fn naive(s: &State) -> i16 {
    if s.done() {
        return 0;
    }
    let mut m = [0u8; 16];
    let n = s.legal(&mut m);
    let maxing = s.to_play() == 0;
    let mut best: i16 = if maxing { -64 } else { 64 };
    for i in 0..n {
        let mut t = *s;
        let g = t.play(m[i]) as i16;
        let v = g + naive(&t);
        if maxing {
            best = best.max(v);
        } else {
            best = best.min(v);
        }
    }
    best
}

#[test]
fn solver_matches_brute_force() {
    // Alpha-beta + transposition table + equivalence pruning + move ordering
    // must all be value-preserving. Fast-forward into the endgame so the
    // reference search is affordable, then compare exactly.
    let mut dd = Dd::new(18);
    let mut checked = 0;
    let mut grand_seeds = 0;
    let mut minor_seeds = 0;
    let mut card_seeds = 0;
    for seed in 0..48u64 {
        // Over DENOMS, so GRAND is covered. It is not decoration here: the
        // equivalence collapse prunes on the follow-suit CLASS, and Grand is
        // the only trump where that is not the suit -- all four tens become
        // mutually interchangeable while a suit loses its ten. A collapse that
        // got either direction wrong would prune a move that was not really
        // equivalent, and the only symptom is a slightly wrong value.
        let trump = DENOMS[(seed % DENOMS.len() as u64) as usize];
        if trump == GRAND {
            grand_seeds += 1;
        }
        let mut g = Game::deal(&mut Rng::new(seed), trump, (seed % 2) as u8);
        // Every third seed solves under MINOR parity (+1 evens), and every
        // third under CARD SCORING (skat mode's currency since 2026-08-09).
        // `naive` goes through `State::play` and is correct in every currency
        // by construction, so this is an EXACT gate on the runtime solver --
        // including the MTD(f) ladder, whose stepping parity differs under
        // minor and does not EXIST under card scoring (trick values -2/+1/+4
        // mix both parities, so the ladder must step by 1), and the
        // equivalence collapse, which under card scoring may only merge
        // rank-adjacent cards of EQUAL worth (the 8/9 and Q/K boundaries are
        // where a wrong merge changes the value).
        if seed % 3 == 2 {
            g.s.even = 1;
            minor_seeds += 1;
        } else if seed % 3 == 1 {
            // The SHIPPED skat combination: card scoring AND must-head, since
            // the legality rule changes which lines exist and `naive` reads
            // `State::legal` too, so the brute-force gate covers both at once.
            g.s.cards = true;
            g.s.head = true;
            card_seeds += 1;
        }
        let mut r = Rng::new(seed ^ 0xABCD);
        while g.s.trick < 8 {
            let mut m = [0u8; 16];
            let n = g.s.legal(&mut m);
            g.apply(m[r.below(n)]);
        }
        dd.clear();
        assert_eq!(dd.solve(&g.s), naive(&g.s), "seed {seed}");
        checked += 1;
    }
    assert_eq!(checked, 48);
    assert!(grand_seeds > 0, "the trump sweep never reached Grand");
    assert!(minor_seeds > 0, "the parity sweep never reached minor");
    assert!(card_seeds > 0, "the sweep never reached card scoring");
}

#[test]
fn solver_is_insensitive_to_table_size() {
    // A hash collision or a mis-scoped key would show up as a value that moves
    // when the table does.
    for seed in 100..115u64 {
        let mut g = Game::deal(&mut Rng::new(seed), 4, 0);
        let mut r = Rng::new(seed);
        while g.s.trick < 4 {
            let mut m = [0u8; 16];
            let n = g.s.legal(&mut m);
            g.apply(m[r.below(n)]);
        }
        let a = Dd::new(12).solve(&g.s);
        let b = Dd::new(20).solve(&g.s);
        assert_eq!(a, b, "seed {seed}");
    }
}

#[test]
fn a_warm_contract_table_never_answers_for_a_different_contract() {
    // FOUND 2026-08-08, and it was live in the served card search. `csearch`
    // keyed on the position, the banked points and `escored` -- and on nothing
    // about the CONTRACT, which is precisely what decides what a leaf is worth.
    // So the second contract solved on a position got the first one's answer:
    // measured +9 on one deal where a cold table said -15, -8 and -20.
    //
    // It reached the browser because `wasm.rs` keeps one `Dd` per worker for
    // the life of the tab and never clears it, while the contract changes every
    // round. The three offline bins that sweep contracts on one deal all call
    // `Dd::clear` between them, which is exactly why nothing caught it.
    //
    // ONE `Dd` FOR EVERY CONTRACT, against one FRESH `Dd` each. Sharing is the
    // whole point; a version that made a new solver per contract would pass
    // against the bug.
    //
    // It runs from MID-ROUND positions, and that is a cost decision, not a
    // coverage one: from trick 0 the same 24 contracts took 112s -- two full
    // 13-trick contract solves apiece -- to catch a table bug that a
    // seven-trick position exposes just as well. The suite's own rule is to
    // profile the slow test before assuming it is doing real work.
    let mut shared = Dd::new(16);
    let (mut checked, mut differ) = (0, 0);
    for seed in 500..504u64 {
        let mut g = Game::deal(&mut Rng::new(seed), 2, 0);
        let mut r = Rng::new(seed);
        while g.s.trick < 6 {
            let mut m = [0u8; 16];
            let n = g.s.legal(&mut m);
            g.apply(m[r.below(n)]);
        }
        let mut first: Option<i32> = None;
        for declarer in 0..2usize {
            for level in [1i32, 4, 7] {
                let c = Contract {
                    level,
                    declarer,
                    make_base: level * level,
                    over: 1,
                    set_base: level,
                    short: 5,
                    ramp: 0,
                    null: Some(12),
                };
                let warm = shared.solve_contract(&g.s, &c);
                let cold = Dd::new(16).solve_contract(&g.s, &c);
                assert_eq!(warm, cold, "seed {seed} declarer {declarer} level {level}");
                checked += 1;
                match first {
                    None => first = Some(cold),
                    Some(f) => differ += (f != cold) as i32,
                }
            }
        }
    }
    assert!(checked >= 20, "only {checked} contracts");
    // ...and the contracts really do pay differently, or the assertion above is
    // satisfied by every answer being the same number for honest reasons.
    assert!(differ > 8, "only {differ} contracts differed from the first -- this \
                         test would pass against the bug it exists for");
}

#[test]
fn determinizations_are_consistent_with_what_the_player_knows() {
    let mut rng = Rng::new(31337);
    let mut buf = Vec::new();
    let mut saw_void = false;
    for _ in 0..60 {
        let mut g = Game::deal(&mut rng, 1, 0);
        let mut r = Rng::new(rng.next_u64());
        for _ in 0..14 {
            if g.over() {
                break;
            }
            let mut m = [0u8; 16];
            let n = g.s.legal(&mut m);
            g.apply(m[r.below(n)]);
        }
        for me in 0..2 {
            let opp = 1 - me;
            let v = g.view(me);
            // Everything the view claims is hidden really is hidden from `me`.
            assert_eq!(v.pool & g.played, 0);
            assert_eq!(v.pool & g.s.hand[me], 0);
            assert_eq!(
                v.pool & g.s.hand[opp],
                g.s.hand[opp],
                "the opponent's whole hand must sit in the pool"
            );
            if v.kn.hand_void[opp].iter().any(|&b| b) {
                saw_void = true;
            }
            for _ in 0..25 {
                let d = v.determinize(&mut rng, &mut buf);
                // No sentinel survives.
                for p in 0..2 {
                    for i in 0..3 {
                        for k in 0..d.pile[p][i].n as usize {
                            assert_ne!(d.pile[p][i].c[k], UNKNOWN);
                        }
                    }
                }
                // Structure and public cards preserved.
                assert_eq!(d.hand[me], g.s.hand[me]);
                assert_eq!(d.hand[opp].count_ones(), g.s.hand[opp].count_ones());
                assert_eq!(d.trick, g.s.trick);
                for p in 0..2 {
                    for i in 0..3 {
                        assert_eq!(d.pile[p][i].n, g.s.pile[p][i].n);
                        assert_eq!(d.pile[p][i].top(), g.s.pile[p][i].top());
                    }
                    // The middle pile's bottom is dealt face-up to everyone.
                    assert_eq!(d.pile[p][1].covered(), g.s.pile[p][1].covered());
                }
                // A legal 26-card layout drawn only from unplayed cards.
                let mut cs = all_state_cards(&d);
                assert_eq!(cs.len(), 26 - g.played.count_ones() as usize);
                cs.sort_unstable();
                let before = cs.len();
                cs.dedup();
                assert_eq!(cs.len(), before, "no card dealt twice");
                for c in cs {
                    assert_eq!(g.played & (1 << c), 0, "played cards never come back");
                }
                // Inferred voids are respected in the HAND (piles may hide the suit).
                for s in 0..4 {
                    if v.kn.hand_void[opp][s] {
                        assert_eq!(d.hand[opp] & SUIT_MASK[s], 0);
                    }
                }
            }
        }
    }
    assert!(saw_void, "the fixture must actually exercise void inference");
}

#[test]
fn the_true_deal_is_always_a_legal_determinization() {
    // If the sampler could not have produced the real world, the bot is
    // searching a space that excludes reality.
    let mut rng = Rng::new(555);
    for _ in 0..80 {
        let mut g = Game::deal(&mut rng, 3, 1);
        let mut r = Rng::new(rng.next_u64());
        for _ in 0..12 {
            if g.over() {
                break;
            }
            let mut m = [0u8; 16];
            let n = g.s.legal(&mut m);
            g.apply(m[r.below(n)]);
        }
        for me in 0..2 {
            let opp = 1 - me;
            let v = g.view(me);
            for s in 0..4 {
                if v.kn.hand_void[opp][s] {
                    assert_eq!(
                        g.s.hand[opp] & SUIT_MASK[s],
                        0,
                        "an inferred void must be true of the real hand"
                    );
                }
            }
            // `Mask`, not u32 — masks went 64-bit with the 32-card deck, and a
            // hardcoded width here stopped compiling the moment they did.
            let mut covered: Mask = 0;
            for q in 0..2 {
                for i in [0usize, 2] {
                    if let Some(c) = g.s.pile[q][i].covered() {
                        covered |= 1 << c;
                    }
                }
            }
            assert_eq!(
                v.pool,
                g.s.hand[opp] | covered | g.out,
                "the pool is exactly: their hand, the covered side bottoms, the out-of-play pair"
            );
        }
    }
}

#[test]
fn search_beats_the_heuristic_which_beats_random() {
    let mut ladder = Vec::new();
    for (a, b) in [("greedy", "random"), ("pimc", "greedy")] {
        let mut sum = 0f64;
        let mut n = 0f64;
        for seed in 0..16u64 {
            for swap in 0..2 {
                let mut ba: Box<dyn Bot> = match a {
                    "greedy" => Box::new(GreedyBot),
                    _ => Box::new(PimcBot::new(3, seed, 16)),
                };
                let mut bb: Box<dyn Bot> = match b {
                    "random" => Box::new(RandomBot { rng: Rng::new(seed) }),
                    _ => Box::new(GreedyBot),
                };
                let mut g = Game::deal(&mut Rng::new(seed), (seed % 5) as u8, 0);
                let pts = if swap == 0 {
                    play_round(&mut g, &mut [&mut *ba, &mut *bb])
                } else {
                    let p = play_round(&mut g, &mut [&mut *bb, &mut *ba]);
                    [p[1], p[0]]
                };
                sum += pts[0] as f64;
                n += 1.0;
            }
        }
        ladder.push(sum / n);
    }
    assert!(ladder[0] > 2.5, "greedy must beat random, got {:.3}", ladder[0]);
    assert!(ladder[1] > 2.5, "pimc must beat greedy, got {:.3}", ladder[1]);
}

#[test]
fn mirror_of_identical_deterministic_bots_reads_exactly_par() {
    // The paired-seating harness must cancel deal luck exactly, or every
    // number it reports is noise plus an unknown bias.
    let mut sum = 0f64;
    let mut n = 0f64;
    for seed in 0..60u64 {
        for swap in 0..2 {
            let (mut a, mut b) = (GreedyBot, GreedyBot);
            let mut g = Game::deal(&mut Rng::new(seed), (seed % 5) as u8, 0);
            let pts = if swap == 0 {
                play_round(&mut g, &mut [&mut a, &mut b])
            } else {
                let p = play_round(&mut g, &mut [&mut b, &mut a]);
                [p[1], p[0]]
            };
            sum += pts[0] as f64;
            n += 1.0;
        }
    }
    assert_eq!(sum / n, POOL as f64 / 2.0, "mirror must read exactly par");
}

#[test]
fn replay_lands_exactly_on_the_position_it_started_from() {
    // rewind() reconstructs the deal from the public record, then replay walks
    // it forward. If the round it reconstructs is not the round that actually
    // happened, every likelihood is computed for a different game and the
    // weighting is worse than useless.
    let mut rng = Rng::new(0xBEEF);
    let mut buf = Vec::new();
    let mut checked = 0;
    for _ in 0..40 {
        let mut g = Game::deal(&mut rng, 2, 0);
        let mut r = Rng::new(rng.next_u64());
        for _ in 0..17 {
            if g.over() {
                break;
            }
            let mut m = [0u8; 16];
            let n = g.s.legal(&mut m);
            g.apply(m[r.below(n)]);
        }
        for me in 0..2 {
            let v = g.view(me);
            // The real position is always a legal hypothesis.
            assert!(
                dissonance::infer::log_likelihood(&v, &g.s, 1.0).is_some(),
                "the true world must never be rejected"
            );
            for _ in 0..20 {
                let w = v.determinize(&mut rng, &mut buf);
                let (end, lw) = dissonance::infer::replay(&v, &w, 1.0)
                    .expect("a consistent world must replay legally");
                assert_eq!(end.hand, w.hand, "replay must land on the hypothesis");
                assert_eq!(end.pile, w.pile);
                assert_eq!(end.trick, w.trick);
                assert_eq!(end.led, w.led);
                assert_eq!(end.leader, w.leader);
                assert!(lw <= 0.0 && lw.is_finite(), "log-likelihood {lw}");
                checked += 1;
            }
        }
    }
    assert!(checked > 1000);
}

#[test]
fn infinite_temperature_is_exactly_restricted_choice() {
    // Flattening the policy does NOT make every world equally likely: the
    // likelihood keeps -sum(ln n_legal) over the opponent's decisions, so a
    // world where they were forced outscores one where they had options.
    // Assert that identity exactly -- it is the part of the inference that
    // needs no opponent model at all, and the A/B ladder separates it from the
    // policy-shaped part.
    let mut rng = Rng::new(99);
    let mut checked = 0;
    for seed in 0..25u64 {
        let mut g = Game::deal(&mut Rng::new(seed), 1, 0);
        let mut r = Rng::new(seed ^ 5);
        for _ in 0..11 {
            if g.over() {
                break;
            }
            let mut m = [0u8; 16];
            let n = g.s.legal(&mut m);
            g.apply(m[r.below(n)]);
        }
        let me = g.s.to_play() as usize;
        let v = g.view(me);
        for _ in 0..20 {
            let w = v.determinize(&mut rng, &mut Vec::new());
            let got = dissonance::infer::log_likelihood(&v, &w, f32::INFINITY).unwrap();
            // Recompute independently by walking the replay ourselves.
            let (_, _) = dissonance::infer::replay(&v, &w, f32::INFINITY).unwrap();
            let mut want = 0f32;
            let mut st = dissonance::infer::rewind_for_test(&v, &w);
            for &(mover, card, _) in v.history.iter() {
                let mut m = [0u8; 16];
                let n = st.legal(&mut m);
                if mover as usize == 1 - me {
                    want += (1.0f32 / n as f32).ln();
                }
                st.play(card);
            }
            assert!((got - want).abs() < 1e-3, "got {got} want {want}");
            checked += 1;
        }
    }
    assert!(checked >= 500);
}
