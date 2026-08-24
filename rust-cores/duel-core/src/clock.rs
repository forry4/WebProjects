//! Wall-clock timing that works on both targets.
//!
//! WHY THIS EXISTS: `std::time::Instant::now()` PANICS on `wasm32-unknown-unknown` —
//! there is no clock in the sandbox, so the std shim is `unreachable`. The search is
//! wall-clock-budgeted, so without this the very first `duel_search` call aborts the
//! worker. (That is exactly how it was found: the Node smoke died on `RuntimeError:
//! unreachable` before printing a single sim.)
//!
//! `js_sys::Date::now()` rather than `performance.now()`: the search runs in a WORKER,
//! which has no `window`, and `Date` is reachable from every JS context without a handle.
//! Its millisecond resolution (and any anti-timing-attack coarsening) is irrelevant
//! against a budget measured in hundreds of ms — and on a fast browser it is the sim CAP,
//! not the clock, that actually binds.

/// A monotonic-enough stopwatch. Started once, read many times.
pub struct Clock {
    #[cfg(not(target_arch = "wasm32"))]
    t0: std::time::Instant,
    #[cfg(target_arch = "wasm32")]
    t0: f64, // ms
}

impl Clock {
    pub fn start() -> Clock {
        #[cfg(not(target_arch = "wasm32"))]
        {
            Clock { t0: std::time::Instant::now() }
        }
        #[cfg(target_arch = "wasm32")]
        {
            Clock { t0: js_sys::Date::now() }
        }
    }

    pub fn elapsed_secs(&self) -> f64 {
        #[cfg(not(target_arch = "wasm32"))]
        {
            self.t0.elapsed().as_secs_f64()
        }
        #[cfg(target_arch = "wasm32")]
        {
            (js_sys::Date::now() - self.t0) / 1000.0
        }
    }
}

/// An optional wall-clock budget.
pub struct Deadline {
    clock: Clock,
    /// `None` = unbounded — the arena's fixed-sims mode, where the iteration count is the
    /// currency and a busy box must not be allowed to silently weaken one side.
    limit_s: Option<f64>,
}

impl Deadline {
    /// A non-finite limit means "no deadline" rather than a panic (the move server passes
    /// `f64::INFINITY` for exactly that).
    pub fn new(limit_s: f64) -> Deadline {
        Deadline {
            clock: Clock::start(),
            limit_s: if limit_s.is_finite() { Some(limit_s.max(0.0)) } else { None },
        }
    }

    pub fn expired(&self) -> bool {
        match self.limit_s {
            None => false,
            Some(l) => self.clock.elapsed_secs() >= l,
        }
    }
}
