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
/// Sentinel denomination meaning GRAND: the four tens are trump and belong to
/// NO suit — Skat's jack rule, transplanted onto the ten.
///
/// 6, NOT 5. 5 is `auction::NULL_DENOM`, the marker left on games saved before
/// Null stopped being a bid; reusing it would silently re-read one of those as
/// a Grand contract, which is a different trump AND a different follow-suit
/// rule. Nothing else about the number matters — it is never arithmetic.
pub const GRAND: u8 = 6;
/// A card slot whose identity is hidden from the observer.
pub const UNKNOWN: u8 = 255;

/// The rank that becomes trump under Grand. DERIVED: `RANK_CH` always ends
/// `T J Q K A`, so the ten sits five from the top on every deck width, and a
/// literal 3 would be wrong under three of the four `rank*` builds.
pub const TEN: u8 = NRANK - 5;

/// Follow-suit classes: the four real suits plus one for Grand's trump. A
/// card's class is its suit under every contract but Grand, so everything
/// below collapses to plain `suit` the moment `trump != GRAND`.
pub const TRUMP_CLASS: u8 = 4;
pub const NFOLLOW: usize = 5;

/// The playable denominations, in ladder order — the values `State::trump` can
/// legitimately take. Note `NULL_DENOM` is absent: it is a scoring outcome,
/// never a trump.
pub const DENOMS: [u8; 6] = [0, 1, 2, 3, NOTRUMP, GRAND];
/// Width of an array indexed by a wire denomination.
pub const NDENOM_SLOTS: usize = GRAND as usize + 1;

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

const fn ten_mask() -> Mask {
    let mut m: Mask = 0;
    let mut s = 0u8;
    while s < NSUIT {
        m |= (1 as Mask) << (s * NRANK + TEN);
        s += 1;
    }
    m
}
/// The four tens — Grand's entire trump suit.
pub const TEN_MASK: Mask = ten_mask();

#[inline(always)]
pub fn suit(c: u8) -> u8 {
    c / NRANK
}

/// The suit a card belongs to FOR FOLLOWING, under this contract.
///
/// Identical to `suit` under every contract but Grand, where the four tens
/// leave their suits entirely and become a fifth one. That is the whole of the
/// rules change: holding only the ten of diamonds when diamonds are led makes
/// you VOID in diamonds, and leading a ten obliges the opponent to follow with
/// a ten if they hold one.
#[inline(always)]
pub fn esuit(c: u8, trump: u8) -> u8 {
    if trump == GRAND && rank(c) == TEN {
        TRUMP_CLASS
    } else {
        c / NRANK
    }
}

/// Which follow-suit class ruffs, or 255 when none does (no-trump).
#[inline(always)]
pub fn trump_class(trump: u8) -> u8 {
    if trump == GRAND {
        TRUMP_CLASS
    } else if trump < NOTRUMP {
        trump
    } else {
        255
    }
}

/// Every card in a follow-suit class. Under Grand a suit is its eight cards
/// MINUS its ten, and the trump class is the four tens.
#[inline(always)]
pub fn follow_mask(cls: u8, trump: u8) -> Mask {
    if trump != GRAND {
        return SUIT_MASK[cls as usize];
    }
    if cls == TRUMP_CLASS {
        TEN_MASK
    } else {
        SUIT_MASK[cls as usize] & !TEN_MASK
    }
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
