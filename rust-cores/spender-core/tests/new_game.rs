//! `engine::new_game` deal invariants. There is deliberately NO cross-language seed parity
//! (`rng.rs` documents its RNG "does NOT need to bit-match" Python, and offline games are
//! purely local) — what matters is that every deal is a VALID Splendor start: a full deck
//! partition, a dealt board, the 2-player bank, and 3 distinct nobles. Determinism per seed
//! matters too: the offline driver stores the seed with the save.

use spender_core::cards::{LEVEL_OF, N_CARDS, N_NOBLES};
use spender_core::engine::{self, BANK_INIT, PLAY, WIN_NONE};

#[test]
fn new_game_deals_valid_starts() {
    for seed in 0..50u64 {
        let wp = if seed % 4 == 0 { 21 } else { 15 };
        let s = engine::new_game(seed, wp);

        assert_eq!(s.bank, BANK_INIT, "seed {seed}: bank");
        assert_eq!(s.tokens, [[0; 6]; 2], "seed {seed}: tokens start empty");
        assert_eq!(s.turn, 0, "seed {seed}: seat 0 opens");
        assert_eq!(s.phase, PLAY, "seed {seed}: phase");
        assert_eq!(s.winner, WIN_NONE, "seed {seed}: winner");
        assert_eq!(s.final_trigger, -1, "seed {seed}: final trigger");
        assert_eq!(s.win_points, wp, "seed {seed}: win_points passthrough");

        // Board fully dealt: 4 cards per level, each of the level's own cards.
        for slot in 0..12 {
            let ci = s.board[slot];
            assert!(ci >= 0, "seed {seed}: board slot {slot} empty at deal");
            assert_eq!(LEVEL_OF[ci as usize] as usize, slot / 4 + 1, "seed {seed}: slot {slot} level");
        }

        // decks + board partition the full card set exactly (no dupes, no losses).
        let mut seen = vec![false; N_CARDS];
        for &ci in s.decks.iter().flatten().chain(s.board.iter()) {
            assert!(!seen[ci as usize], "seed {seed}: card {ci} dealt twice");
            seen[ci as usize] = true;
        }
        assert!(seen.iter().all(|&x| x), "seed {seed}: card missing from deal");

        // 3 distinct nobles from the pool.
        for slot in 0..3 {
            let ni = s.nobles[slot];
            assert!((0..N_NOBLES as i32).contains(&ni), "seed {seed}: noble id {ni}");
        }
        assert!(
            s.nobles[0] != s.nobles[1] && s.nobles[1] != s.nobles[2] && s.nobles[0] != s.nobles[2],
            "seed {seed}: duplicate noble"
        );
    }
}

#[test]
fn new_game_is_seed_deterministic_and_seed_sensitive() {
    let a = engine::new_game(7, 15);
    let b = engine::new_game(7, 15);
    assert_eq!(a, b, "same seed must redeal the same game (offline saves store the seed)");
    let c = engine::new_game(8, 15);
    assert_ne!(
        (&a.board, &a.nobles),
        (&c.board, &c.nobles),
        "different seeds should deal different games"
    );
}

/// Drive full random games from `new_game` through `legal_actions`/`apply` to completion —
/// the exact loop the offline driver runs — asserting the token-conservation invariant and
/// that games actually END (the engine's finish/final-round machinery, not just the deal).
#[test]
fn new_game_random_playout_soak() {
    let mut finished = 0usize;
    for seed in 0..20u64 {
        let mut s = engine::new_game(seed, 15);
        let mut rng = spender_core::rng::Rng::new(1_000 + seed);
        for _ in 0..600 {
            if s.phase == spender_core::engine::OVER {
                finished += 1;
                break;
            }
            let legal = engine::legal_actions(&s);
            assert!(!legal.is_empty(), "seed {seed}: no legal actions while not OVER");
            let a = legal[rng.below(legal.len())];
            engine::apply(&mut s, a);
            // Tokens are conserved: bank + both players always sum to the initial supply.
            for c in 0..6 {
                let total = s.bank[c] + s.tokens[0][c] + s.tokens[1][c];
                assert_eq!(total, BANK_INIT[c], "seed {seed}: color {c} tokens not conserved");
            }
        }
    }
    // Random play finishes Splendor games well within 600 plies; zero finishes = machinery broke.
    assert!(finished >= 15, "only {finished}/20 random games finished");
}
