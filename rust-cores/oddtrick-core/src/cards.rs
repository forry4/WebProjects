//! Four suits of `NRANK` cards each. Default 28: 8 9 T J Q K A in each suit.
//!
//! Card index = suit * NRANK + rank, so the deck fits a `u64` bitmask.
//! Rank order is ascending, ace high.
//!
//! `NRANK` is a compile-time knob because the whole point of varying it is to
//! vary how many cards sit OUT of play: both players always hold 13, so a
//! wider deck means more cards nobody was dealt. That count is the game's
//! entire permanent hidden-information budget — in a two-player trick-taker
//! every card you cannot see is your opponent's unless it is out of play, so
//! the out-pile is the only thing standing between the back half of a round
//! and a double-dummy problem. Features `rank8`/`rank9`/`rank10` give 6/10/14
//! cards out against the default's 2. Default build is untouched.

pub type Mask = u64;

#[cfg(feature = "rank10")]
pub const NRANK: u8 = 10;
#[cfg(all(feature = "rank9", not(feature = "rank10")))]
pub const NRANK: u8 = 9;
#[cfg(all(feature = "rank7", not(any(feature = "rank9", feature = "rank10"))))]
pub const NRANK: u8 = 7;
/// DEFAULT: 32 cards / 6 out — the shipped configuration since the 2026-08-07
/// hidden-information sweep. 6 out banks 74% of the secrecy available at any
/// width for the smallest deck change; the sweep saturates hard past it
/// (marginal value per card 0.065 → 0.029 → 0.007). `rank7` rebuilds the
/// original 28-card game the campaign's pre-sweep numbers were measured on.
#[cfg(not(any(feature = "rank7", feature = "rank9", feature = "rank10")))]
pub const NRANK: u8 = 8;

pub const NSUIT: u8 = 4;
pub const NCARD: u8 = NRANK * NSUIT;
/// Sentinel denomination meaning "no trump".
pub const NOTRUMP: u8 = 4;
/// A card slot whose identity is hidden from the observer.
pub const UNKNOWN: u8 = 255;

/// Cards dealt to each player: 7 in hand + three 2-card piles. Fixed, so that
/// widening the deck changes ONLY the out-of-play count and never the shape of
/// a holding or the number of tricks.
pub const NDEALT: u8 = 13;
/// Cards nobody is dealt.
pub const NOUT: u8 = NCARD - 2 * NDEALT;

pub const ALL: Mask = (1 << NCARD) - 1;

const fn suit_masks() -> [Mask; 4] {
    let one: Mask = (1 << NRANK) - 1;
    [
        one,
        one << NRANK,
        one << (2 * NRANK),
        one << (3 * NRANK),
    ]
}
pub const SUIT_MASK: [Mask; 4] = suit_masks();

#[inline(always)]
pub fn suit(c: u8) -> u8 {
    c / NRANK
}

#[inline(always)]
pub fn rank(c: u8) -> u8 {
    c % NRANK
}

#[inline(always)]
pub fn card(s: u8, r: u8) -> u8 {
    s * NRANK + r
}

/// Ace-high and always ending at A, so a wider deck extends DOWNWARD and the
/// top of every suit keeps the same name across configurations.
const RANK_CH_FULL: [&str; 10] = ["5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"];
/// Ascending, `RANK_CH[0]` = the lowest card in this deck.
pub const RANK_CH: &[&str] = RANK_CH_FULL.split_at(10 - NRANK as usize).1;
pub const SUIT_CH: [char; 4] = ['c', 'd', 'h', 's'];

pub fn card_name(c: u8) -> String {
    if c == UNKNOWN {
        return "??".into();
    }
    format!("{}{}", RANK_CH[rank(c) as usize], SUIT_CH[suit(c) as usize])
}

pub fn denom_name(d: u8) -> &'static str {
    match d {
        0 => "clubs",
        1 => "diamonds",
        2 => "hearts",
        3 => "spades",
        _ => "no-trump",
    }
}

pub fn mask_name(m: Mask) -> String {
    let mut v: Vec<String> = Vec::new();
    let mut m = m;
    while m != 0 {
        let c = m.trailing_zeros() as u8;
        m &= m - 1;
        v.push(card_name(c));
    }
    v.join(" ")
}
