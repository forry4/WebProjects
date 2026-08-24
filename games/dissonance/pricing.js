// Dissonance's price list, on the client — ONE mirror of `engine._terms_for`
// and `engine.payoff`, shared by the board and the paper scorecard.
//
// WHY IT IS A MODULE. The board prices contracts it is not scoring (a bid being
// chosen, the Kontra prompt's two columns) and the scorecard prices contracts
// the server never sees at all, so both need the arithmetic in JS. One copy is
// unavoidable; TWO would be the drift this file exists to prevent, and the
// scorecard is exactly the kind of screen that grows its own quietly.
//
// EVERY NUMBER COMES OFF `/catalog`, which serves the engine's own dicts. The
// fallbacks below are what renders when that fetch never landed — they mirror
// what classic ships, and they are the only literals in the file.
//
// `tests/test_bid_worth.py` is the gate: it asserts the catalog serves every
// term, that this file reads every one of them, and that a throwaway copy of
// the formulas reproduces `_terms_for` / `payoff` across the ladder, doubled
// and not. Nothing at runtime notices a drift — the server scores every settled
// round itself, so a wrong number here pays out correctly and simply LIES to
// the player, which is the worst place to be wrong and the least likely to be
// noticed.

//: The shipped classic values, for a catalog fetch that never landed.
const OFFLINE = {
	short: 5, nullMake: 20, flatMake: 4, flatSet: 2, setRate: 2, linMake: 0,
	jumpBonus: 6, over: 1, dblMake: 2, dblBase: 1, dblJump: 2, dblShort: 10,
};

/** This room's (or this scorecard's) price list, as plain numbers plus a
 *  `price(level, jump, doubled)`.
 *
 *  `mode` is the room's own — minor has its own two prices (set rate 2, Null 6,
 *  re-anchored to a scale whose payoffs run a quarter of classic's) and skat is
 *  priced elsewhere entirely; `undefined` outside a room, where nothing renders
 *  a number anyway.
 */
export function contractPrices(catalog, mode) {
	const isMinor = mode === "minor";
	const isClassic = mode === "classic";
	// CLASSIC READS ITS OWN RATE. `short_penalty` is `SHORT_PENALTY`, which
	// classic stopped using on 2026-08-16 when `CLASSIC_SHORT_PENALTY` was split
	// out so classic and skat could move independently. Both are 5 today, so
	// reading the wrong one was not visibly wrong -- it was wrong in waiting.
	const short = isMinor
		? (catalog?.minor_short_penalty ?? 2)
		: isClassic
			? (catalog?.classic_short_penalty ?? OFFLINE.short)
			: (catalog?.short_penalty ?? OFFLINE.short);
	const nullMake = isMinor
		? (catalog?.minor_null_make ?? 6)
		: (catalog?.null_make ?? OFFLINE.nullMake);
	// THE FLAT STAKE (2026-08-11, re-priced 2026-08-16 to +4 / +2): the fixed
	// amounts riding on classic's make and set bases, read off the catalog's
	// per-mode dicts so a re-priced stake needs no client change.
	const flatMake = catalog?.flat_make_bonus?.[mode] ?? (isClassic ? OFFLINE.flatMake : 0);
	const flatSet = catalog?.flat_set_penalty?.[mode] ?? (isClassic ? OFFLINE.flatSet : 0);
	// The rest of the curve, so a bid can be PRICED BEFORE IT IS MADE.
	const setRate = catalog?.set_level_rate?.[mode] ?? (isClassic ? OFFLINE.setRate : 1);
	const linMake = catalog?.linear_make_bonus?.[mode] ?? OFFLINE.linMake;
	const jumpBonus = catalog?.jump_set_bonus?.[mode] ?? (isClassic ? OFFLINE.jumpBonus : 0);
	const over = catalog?.over_bonus?.[mode] ?? OFFLINE.over;
	// THE DOUBLE'S DIALS (2026-08-16). TWO FALLBACKS, and they answer different
	// questions. `served` is what an absent MODE means -- `_terms_for` reads
	// these with `.get(mode, doubling)`, so a mode nobody named gets the plain
	// x2 -- while `offline` is what a catalog fetch that never landed should
	// render, which is whatever classic ships. Collapsing them into one `??`
	// would quietly turn classic's base x1 back into a x2 the moment the fetch
	// failed.
	const dialFor = (table, served, offline) => (table ? (table[mode] ?? served) : offline);
	const dblMake = dialFor(catalog?.double_make_mult, 2, OFFLINE.dblMake);
	const dblBase = dialFor(catalog?.double_base_mult, 2, isClassic ? OFFLINE.dblBase : 2);
	const dblJump = dialFor(catalog?.double_jump_mult,
		(catalog?.jump_doubled?.[mode] ?? true) ? dblBase : 1,
		isClassic ? OFFLINE.dblJump : dblBase);
	const dblShort = dialFor(catalog?.doubled_short_penalty, short,
		isClassic ? OFFLINE.dblShort : short);
	const dblRamp = catalog?.double_ramp ?? 0;

	/** What a contract at `level`, reached by a `jump`-rung rise, is worth --
	 *  undoubled, or with the Kontra on it.
	 *
	 *  `make` and `setBase` are exact. `down` is the CHEAPEST way to lose it --
	 *  the set base plus a single point short -- because how far short you finish
	 *  is not knowable at bid time; it is the floor of the loss, not the loss.
	 *  The auction panel says "down for" to keep that honest.
	 *
	 *  Mirrors `_terms_for`'s classic/minor branch, doubled arm included: the
	 *  fixed stake takes `DOUBLE_BASE_MULT`, the jump bonus takes its own
	 *  `DOUBLE_JUMP_MULT`, and a doubled shortfall charges
	 *  `DOUBLED_SHORT_PENALTY` a point. `setParts` is the stake taken apart, so
	 *  a panel can print the terms rather than one opaque number and still
	 *  provably reach the total.
	 */
	const price = (level, jump, doubled) => {
		const mm = doubled ? dblMake : 1;
		const bm = doubled ? dblBase : 1;
		const jm = doubled ? dblJump : 1;
		const stake = (setRate * level + flatSet) * bm;
		const leap = jumpBonus * Math.max(0, jump) * jm;
		const shortRate = doubled ? dblShort : short;
		return {
			make: (level * level + linMake * level + flatMake) * mm,
			over: over * mm,
			stake, leap, short: shortRate, ramp: doubled ? dblRamp : 0,
			setBase: stake + leap,
			// The two bases taken apart, so a panel can print the terms it
			// charged rather than one opaque number -- and still provably reach
			// the total, since these are the same factors the total is built
			// from rather than a second derivation of it.
			makeParts: { lin: linMake, flat: flatMake, mult: mm },
			setParts: { rate: setRate * bm, flat: flatSet * bm },
			down: stake + leap + shortRate,
		};
	};
	return { price, short, nullMake, dblShort, dblRamp, over };
}

/** A round's payoff, SIGNED FOR THE DECLARER — `engine.payoff`, mirrored.
 *
 *  Null is checked FIRST and wins: taking no scoring trick is only reachable
 *  with a non-positive total, so it can never collide with a make, and it
 *  always replaces being set. It is a flat amount the Double never touches.
 *
 *  `ramp` is the Double's retired escalator (0 as shipped, and kept because a
 *  round scored while it was live still has to add up): the first point short
 *  costs `short + ramp`, the second `short + 2 ramp`, summing to
 *  `short x s + ramp x s(s+1)/2`.
 */
export function payoffFor(prices, { level, jump = 0, doubled = false, pts, nullMade = false }) {
	if (nullMade) return prices.nullMake;
	const p = prices.price(level, jump, doubled);
	if (pts >= level) return p.make + p.over * (pts - level);
	const s = level - pts;
	return -(p.setBase + p.short * s + p.ramp * s * (s + 1) / 2);
}
