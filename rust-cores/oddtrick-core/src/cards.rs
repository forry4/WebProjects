//! 28-card deck: 8 9 T J Q K A in each of four suits.
//!
//! Card index = suit * 7 + rank, so 0..27 fits a `u32` bitmask.
//! Rank order is ascending: 0 = 8, 6 = A.

pub type Mask = u32;

pub const NCARD: u8 = 28;
pub const NRANK: u8 = 7;
pub const NSUIT: u8 = 4;
/// Sentinel denomination meaning "no trump".
pub const NOTRUMP: u8 = 4;
/// A card slot whose identity is hidden from the observer.
pub const UNKNOWN: u8 = 255;

pub const ALL: Mask = (1 << 28) - 1;

pub const SUIT_MASK: [Mask; 4] = [0x7F, 0x7F << 7, 0x7F << 14, 0x7F << 21];

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

pub const RANK_CH: [&str; 7] = ["8", "9", "T", "J", "Q", "K", "A"];
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
