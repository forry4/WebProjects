//! Small fast PRNG (splitmix64) + the sampling primitives the search needs.
//!
//! This deliberately does NOT reproduce Python's Mersenne Twister stream, and it does not
//! have to: the two searches diverge by construction the moment they draw a different
//! number, so no amount of care would make `rng.choice` line up across languages. What IS
//! pinned is everything the stream feeds — the leaf value and the move lists it samples
//! from (see `bin/ai_parity.rs`) — leaving the stream itself as the only free variable,
//! whose effect is measured statistically by the cross-impl arena (`bin/move_server.rs`).
//!
//! Same generator as spender-core/src/rng.rs, for the same reason: it is fast, seedable,
//! and has no dependencies.

pub struct Rng {
    state: u64,
}

impl Rng {
    pub fn new(seed: u64) -> Self {
        Rng { state: seed }
    }

    #[inline]
    pub fn next_u64(&mut self) -> u64 {
        // splitmix64
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    /// Uniform-ish index in 0..n (modulo bias is negligible at our sizes: n <= ~160).
    #[inline]
    pub fn below(&mut self, n: usize) -> usize {
        debug_assert!(n > 0, "below(0): the caller must guarantee a non-empty range");
        (self.next_u64() % (n as u64)) as usize
    }

    /// Uniform in [0, 1) with 53 bits of mantissa — the same range and resolution as
    /// Python's `random.random()`, which is what `random.choices` samples against.
    #[inline]
    pub fn next_f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 * (1.0 / 9007199254740992.0)
    }

    /// In-place Fisher-Yates shuffle.
    pub fn shuffle<T>(&mut self, v: &mut [T]) {
        let n = v.len();
        if n <= 1 {
            return;
        }
        for i in (1..n).rev() {
            let j = (self.next_u64() % ((i + 1) as u64)) as usize;
            v.swap(i, j);
        }
    }

    /// Weighted pick over `weights`, mirroring `random.choices(..., k=1)`: accumulate,
    /// scale a uniform draw by the total, and bisect. Returns an index into `weights`.
    ///
    /// The `hi = n - 1` clamp is Python's, not a typo: `bisect` is called with `hi=n-1`,
    /// so a draw landing at/after the last boundary (possible with float rounding) yields
    /// the last index rather than running off the end.
    pub fn weighted(&mut self, weights: &[f64]) -> usize {
        debug_assert!(!weights.is_empty());
        let mut cum: Vec<f64> = Vec::with_capacity(weights.len());
        let mut acc = 0.0;
        for &w in weights {
            acc += w;
            cum.push(acc);
        }
        let x = self.next_f64() * acc;
        let hi = weights.len() - 1;
        for (i, &c) in cum.iter().enumerate().take(hi) {
            if x < c {
                return i;
            }
        }
        hi
    }
}
