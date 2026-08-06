use oddtrick::bots::*;
use oddtrick::cards::*;
use oddtrick::dd::Dd;
use oddtrick::game::{play_round, Bot, Game};
use oddtrick::rng::Rng;
use oddtrick::state::*;

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
        assert_eq!(v.len(), 28, "26 dealt + 2 out of play");
        v.dedup();
        assert_eq!(v.len(), 28, "no duplicated card");
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
    if oddtrick::state::POSITIVE_IS_ODD {
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
fn follow_suit_is_mandatory_and_pile_tops_count() {
    let mut rng = Rng::new(4242);
    for _ in 0..300 {
        let mut g = Game::deal(&mut rng, 2, 0);
        let mut r = Rng::new(7);
        while !g.over() {
            let p = g.s.to_play() as usize;
            let mut m = [0u8; 16];
            let n = g.s.legal(&mut m);
            assert!(n > 0 && n <= 10, "at most 7 hand + 3 pile tops");
            if g.s.led >= 0 {
                let ls = suit(g.s.led as u8);
                let have = g.s.playable(p) & SUIT_MASK[ls as usize];
                if have != 0 {
                    for &c in &m[..n] {
                        assert_eq!(suit(c), ls, "must follow when able, piles included");
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
    for seed in 0..40u64 {
        let mut g = Game::deal(&mut Rng::new(seed), (seed % 5) as u8, (seed % 2) as u8);
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
    assert_eq!(checked, 40);
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
            let mut covered = 0u32;
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
                oddtrick::infer::log_likelihood(&v, &g.s, 1.0).is_some(),
                "the true world must never be rejected"
            );
            for _ in 0..20 {
                let w = v.determinize(&mut rng, &mut buf);
                let (end, lw) = oddtrick::infer::replay(&v, &w, 1.0)
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
            let got = oddtrick::infer::log_likelihood(&v, &w, f32::INFINITY).unwrap();
            // Recompute independently by walking the replay ourselves.
            let (_, _) = oddtrick::infer::replay(&v, &w, f32::INFINITY).unwrap();
            let mut want = 0f32;
            let mut st = oddtrick::infer::rewind_for_test(&v, &w);
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
