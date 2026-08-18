// Dissonance's PAPER SCORECARD — a keeper for a game played with real cards
// at a real table, where nothing about the round reaches the server.
//
// It asks for exactly what a classic round is scored FROM: who declared, the
// contract, how far the winning bid leapt, whether it was Kontra'd, and the
// declarer's final trick points. Everything else is arithmetic, and the
// arithmetic is `pricing.js` — the same mirror of `engine._terms_for` /
// `engine.payoff` the board's own panels price with, so a card kept here and a
// round played online can never disagree about what a contract is worth.
//
// THE ONE INPUT THE POINTS CANNOT GIVE US is Null. A declarer who won no +2
// trick scores the consolation instead of being set, and the point total does
// not settle it: 0 points is "no scoring trick at all" (Null) or "one even
// trick and two odd ones" (a set), and the difference is 20 to the declarer
// against a set to the defender. So the toggle appears exactly when the total
// makes it possible — at or below zero — and never otherwise.
//
// It lives entirely in `localStorage`: a real-life match runs an hour, the tab
// gets closed, and nothing here is worth an account or a room.
import { useEffect, useMemo, useState } from "react";
import { RulesModal } from "../../shared/lobby.jsx";
import { contractPrices, payoffFor } from "./pricing.js";

const KEY = "dis_scorecard_v1";
//: The five denominations, in rank order. Kept here rather than imported from
//: the board so the modal carries no dependency on a live room — the glyph is
//: the only thing the card needs, since a denomination is what makes a row
//: readable and never touches the score.
const DENOMS = [
	{ d: 0, glyph: "♣", red: false },
	{ d: 1, glyph: "♦", red: true },
	{ d: 2, glyph: "♥", red: true },
	{ d: 3, glyph: "♠", red: false },
	{ d: 4, glyph: "NT", red: false },
];

const EMPTY = { names: ["", ""], rounds: [] };

function loadCard() {
	try {
		const raw = JSON.parse(localStorage.getItem(KEY) || "null");
		if (!raw || !Array.isArray(raw.rounds)) return EMPTY;
		return { names: Array.isArray(raw.names) ? raw.names : ["", ""], rounds: raw.rounds };
	} catch { return EMPTY; }
}

/** The contract, as it reads on a card: "4♠", "2 NT". */
function Contract({ level, denom }) {
	const d = DENOMS[denom] || DENOMS[0];
	return <span className="dsc-ct"><b>{level}</b>
		<span className={d.red ? "dis-suit-r" : "dis-suit-b"}>{d.glyph}</span></span>;
}

/** The round's arithmetic, spelled out the way the board's result panel spells
 *  it — same shape, same terms, because it is the same scoring and a player who
 *  learns it in one place should recognise it in the other.
 *
 *  Every number comes out of `prices.price`, so the line cannot claim a term
 *  the payoff beside it did not charge.
 */
function maths(prices, r) {
	if (r.nul) return `flat ${prices.nullMake}`;
	const p = prices.price(r.level, r.jump, r.doubled);
	if (r.pts >= r.level) {
		const { lin, flat, mult } = p.makeParts;
		let head = `${r.level} × ${r.level}`;
		if (lin) head += ` + ${lin} × ${r.level}`;
		if (flat) head += ` + ${flat}`;
		head = flat || lin ? `(${head})` : head;
		if (mult > 1) head += ` × ${mult}`;
		const over = r.pts - r.level;
		if (!over) return head;
		return `${head} + ${p.over > 1 ? `(${p.over} × ${over})` : over}`;
	}
	const { rate, flat } = p.setParts;
	let head = rate > 1 ? `${rate} × ${r.level}` : `${r.level}`;
	if (flat) head += ` + ${flat}`;
	if (p.leap) head += ` + ${p.leap}`;
	const short = r.level - r.pts;
	const tail = p.ramp
		? Array.from({ length: short }, (_, i) => p.short + p.ramp * (i + 1)).join(" + ")
		: `${p.short} × ${short}`;
	return `(${head}) + (${tail})`;
}

/** −/+ around a number, for the two quantities that are not a keypad: the leap
 *  and the declarer's points. A stepper rather than a text field because this
 *  is filled in at a table on a phone, and a number input there is a keyboard
 *  covering the card you are reading. */
function Stepper({ value, min, max, onChange, placeholder }) {
	const at = value === null || value === undefined;
	const set = (v) => onChange(Math.max(min, Math.min(max, v)));
	return (
		<div className="dsc-step">
			<button type="button" onClick={() => set((at ? 0 : value) - 1)}
				disabled={!at && value <= min} aria-label="less">−</button>
			<span className={at ? "dsc-step-v dsc-step-empty" : "dsc-step-v"}>
				{at ? placeholder : value}
			</span>
			<button type="button" onClick={() => set((at ? 0 : value) + 1)}
				disabled={!at && value >= max} aria-label="more">+</button>
		</div>
	);
}

export default function DissonanceScorecard({ catalog, onClose }) {
	// CLASSIC, EXPLICITLY. The card is for the mode people play with real cards;
	// minor and skat price differently and dummy needs a third hand, so the mode
	// is named here rather than inferred from anything.
	const prices = useMemo(() => contractPrices(catalog, "classic"), [catalog]);
	const maxLevel = catalog?.max_levels?.classic ?? 10;
	const target = catalog?.match_targets?.classic ?? 200;
	// The points a declarer can reach, DERIVED from the parity rather than typed
	// beside it: six even tricks at +2 is the ceiling, the seven odd ones the
	// floor. A re-priced trick moves both without an edit here.
	const tricks = catalog?.tricks ?? 13;
	const evenVal = catalog?.even_value?.classic ?? 2;
	const evens = Math.floor(tricks / 2);
	const maxPts = evens * evenVal;
	const minPts = -(tricks - evens);

	const [card, setCard] = useState(loadCard);
	useEffect(() => {
		try { localStorage.setItem(KEY, JSON.stringify(card)); } catch { /* private mode */ }
	}, [card]);

	const [decl, setDecl] = useState(0);
	const [level, setLevel] = useState(null);
	const [denom, setDenom] = useState(null);
	const [jump, setJump] = useState(0);
	const [doubled, setDoubled] = useState(false);
	const [pts, setPts] = useState(null);
	const [nul, setNul] = useState(false);
	const [confirmClear, setConfirmClear] = useState(false);

	const nameOf = (i) => (card.names[i] || "").trim() || `Player ${i + 1}`;
	const setName = (i, v) => setCard((c) => {
		const names = [...c.names]; names[i] = v.slice(0, 16); return { ...c, names };
	});

	const totals = card.rounds.reduce((acc, r) => [acc[0] + r.scores[0], acc[1] + r.scores[1]], [0, 0]);
	const won = totals[0] >= target || totals[1] >= target
		? (totals[0] === totals[1] ? -1 : (totals[0] > totals[1] ? 0 : 1))
		: null;

	// NULL IS ONLY OFFERED WHERE IT IS REACHABLE. Winning no +2 trick means every
	// trick taken was a −1, so the total cannot be positive; above zero the
	// question is settled by the points themselves.
	const canNull = pts !== null && pts <= 0;
	const isNull = canNull && nul;
	const ready = level !== null && denom !== null && pts !== null;
	const entry = ready
		? { level, denom, jump, doubled, pts, nul: isNull } : null;
	const value = entry ? payoffFor(prices, { ...entry, nullMade: isNull }) : 0;
	const scorer = value >= 0 ? decl : 1 - decl;

	const addRound = () => {
		if (!ready) return;
		const scores = [0, 0];
		scores[scorer] = Math.abs(value);
		setCard((c) => ({ ...c, rounds: [...c.rounds, { decl, ...entry, scores }] }));
		setLevel(null); setDenom(null); setJump(0); setDoubled(false);
		setPts(null); setNul(false);
	};
	const dropRound = (i) => setCard((c) => ({
		...c, rounds: c.rounds.filter((_, j) => j !== i),
	}));

	return (
		<RulesModal title="Scorecard — Dissonance classic" icon="🧮"
			closeLabel="Done" onClose={onClose}>
			<p className="rl-lead">
				For a game played with real cards. Enter each round and it keeps the
				score — first past <b>{target}</b> wins the match.
			</p>

			<div className="dsc-players">
				{[0, 1].map((i) => (
					<label className="dsc-player" key={i}>
						<input value={card.names[i] || ""} placeholder={`Player ${i + 1}`}
							onChange={(e) => setName(i, e.target.value)} />
						<span className={won === i ? "dsc-total dsc-won" : "dsc-total"}>
							{totals[i]}
						</span>
					</label>
				))}
			</div>
			{won !== null && (
				<div className="dsc-winner">
					{won < 0
						? `Level pegging on ${totals[0]} — play another round.`
						: `${nameOf(won)} is past ${target} — match won.`}
				</div>
			)}

			{card.rounds.length > 0 && (
				<div className="dsc-table">
					<div className="dsc-row dsc-head">
						<span>#</span><span>Declarer</span><span>Contract</span>
						<span className="dsc-num">{nameOf(0)}</span>
						<span className="dsc-num">{nameOf(1)}</span>
						<span />
					</div>
					{card.rounds.map((r, i) => (
						<div className="dsc-row" key={i}>
							<span className="dsc-no">{i + 1}</span>
							<span className="dsc-who">{nameOf(r.decl)}</span>
							<span>
								<Contract level={r.level} denom={r.denom} />
								{r.doubled ? <span className="dsc-tag">K</span> : null}
								{r.jump ? <span className="dsc-tag">↑{r.jump}</span> : null}
								{r.nul ? <span className="dsc-tag">Null</span> : null}
								<span className="dsc-pts">{r.pts} {r.pts === 1 ? "pt" : "pts"}</span>
							</span>
							<span className="dsc-num">{r.scores[0] || "—"}</span>
							<span className="dsc-num">{r.scores[1] || "—"}</span>
							<button type="button" className="dsc-x" aria-label={`Delete round ${i + 1}`}
								onClick={() => dropRound(i)}>✕</button>
						</div>
					))}
				</div>
			)}

			<div className="dsc-entry">
				<div className="dsc-hd">Round {card.rounds.length + 1}</div>

				<div className="dsc-field">
					<span className="dsc-lbl">Declarer</span>
					<div className="dsc-seg">
						{[0, 1].map((i) => (
							<button type="button" key={i} className={decl === i ? "on" : ""}
								onClick={() => setDecl(i)}>{nameOf(i)}</button>
						))}
					</div>
				</div>

				<div className="dsc-field">
					<span className="dsc-lbl">Contract</span>
					{/* THE BOARD'S OWN KEYS, one pad above the other: five levels to a
					    row and five denominations under them, which is the layout the
					    auction panel uses and the reason both pads share a column
					    rather than sitting side by side in the field's flex. */}
					<div className="dsc-pads">
						<div className="dis-bidgrid">
							{Array.from({ length: maxLevel }, (_, i) => i + 1).map((l) => (
								<button type="button" key={l} className={level === l ? "on" : ""}
									onClick={() => { setLevel(l); if (jump > l) setJump(l); }}>{l}</button>
							))}
						</div>
						<div className="dis-denoms">
							{DENOMS.map((d) => (
								<button type="button" key={d.d} className={denom === d.d ? "on" : ""}
									onClick={() => setDenom(d.d)}>
									<span className={d.red ? "dis-suit-r" : "dis-suit-b"}>{d.glyph}</span>
								</button>
							))}
						</div>
					</div>
				</div>

				<div className="dsc-field">
					<span className="dsc-lbl">Final jump</span>
					<Stepper value={jump} min={0} max={level ?? maxLevel}
						onChange={setJump} placeholder="0" />
					{/* The one input nobody can guess from the table, so it says what
					    it means: levels the WINNING bid rose by, counting an opening
					    bid as a rise from 0. */}
					<span className="dsc-note">
						levels the winning bid rose by — 0 if it took over at the same
						level, and an opening bid that was passed out counts its whole
						level
					</span>
				</div>

				<div className="dsc-field">
					<span className="dsc-lbl">Kontra</span>
					<button type="button" className={doubled ? "dsc-toggle on" : "dsc-toggle"}
						onClick={() => setDoubled(!doubled)}>
						{doubled ? "Doubled" : "Not doubled"}
					</button>
				</div>

				<div className="dsc-field">
					<span className="dsc-lbl">Declarer's points</span>
					<Stepper value={pts} min={minPts} max={maxPts}
						onChange={(v) => { setPts(v); if (v > 0) setNul(false); }} placeholder="—" />
					{canNull && (
						<button type="button" className={isNull ? "dsc-toggle on" : "dsc-toggle"}
							onClick={() => setNul(!nul)}>
							Won no +{evenVal} trick (Null)
						</button>
					)}
				</div>

				{/* PRICED BEFORE IT IS ENTERED, and the arithmetic shown with it —
				    the card is also the only place a table of new players can see
				    where a number came from. */}
				<div className="dsc-preview">
					{ready ? (
						<>
							<div className="dsc-pre-line">
								<b>{nameOf(scorer)}</b> scores <b className="dsc-pre-n">{Math.abs(value)}</b>
							</div>
							<div className="dsc-pre-maths">{maths(prices, { ...entry, nul: isNull })}</div>
						</>
					) : (
						<div className="dsc-pre-line dsc-pre-wait">
							Pick a contract and the declarer's points.
						</div>
					)}
				</div>

				<div className="dsc-actions">
					<button type="button" className="dsc-add" disabled={!ready} onClick={addRound}>
						Add round
					</button>
					{card.rounds.length > 0 && (
						<button type="button" className="dsc-clear"
							onClick={() => {
								if (!confirmClear) { setConfirmClear(true); return; }
								setCard(EMPTY); setConfirmClear(false);
							}}
							onBlur={() => setConfirmClear(false)}>
							{confirmClear ? "Clear everything?" : "New card"}
						</button>
					)}
				</div>
			</div>
		</RulesModal>
	);
}
