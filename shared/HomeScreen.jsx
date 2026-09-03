/* The site landing menu — pick a game.
 *
 * Second piece of the shell/game split (see AuthScreen.jsx). Purely presentational:
 * no state of its own, no data fetching. The shell still owns identity and routing
 * and passes them in, so the eventual inversion has one less screen to untangle.
 *
 * The game catalogue lives here rather than in games/spender/Spender.jsx because it
 * describes the SITE, not the Spender game — Spender is just one of its entries.
 */
const SITE_NAME = "Forrest Games";
// ONE footer line for the whole shell. The menu and the front door had two
// different strings saying the same thing, which is the sort of thing nobody
// notices individually and everybody feels.
const SITE_FOOT = "Play in the browser — no download, no ads";

// `screen` is the shell's SITE-LEVEL screen id for each game (Spender's own
// browser/waiting/game live in its `spenderScreen`); `accent` drives the card's
// --accent custom property.
//
// THE ACCENTS ARE A SPACED HUE WHEEL, NOT SEVEN COLOURS PICKED BY EYE, and they are
// contrast-bound. Two rules, both of which the original palette broke:
//   1. Every accent is the card TITLE's ink on --surface, so it must clear 4.5:1
//      there. The titles are ~1.2rem — under the large-text exemption — and four of
//      the originals sat at 3.0–4.4:1: fine on a bright monitor, genuinely hard on a
//      phone outdoors. Same hues, lifted in value.
//   2. The accents have to be TELLABLE APART at pill size, which is the whole point
//      of having them. Spender and Dontminion were both gold and read as the same
//      game at a glance; Dontminion is now verdigris — the last free arc of the
//      wheel, and the one colour on it that cannot be confused with the periwinkle
//      or the green either. Castles' crimson and Rag Tag's orange were also close,
//      so they are pushed apart in hue rather than merely in value.
//   3. They have to sit in one LUMINANCE band, or the titles stop reading as one
//      family: the green measured .50 and the crimson .29 — nearly a 2x spread — so
//      Dissonance's title glared while Castles' looked half-off, and the same spread
//      ran down the accent stripes, where the warm ones stayed visible for their full
//      height and the cool ones faded out at their midpoint. All seven are now inside
//      .364-.404 relative luminance, i.e. within about 4 L* of each other.
// The wheel as shipped, measured: crimson 352, orange 20, gold 43, green 152,
//   verdigris 185, periwinkle 226, violet 290 — no two closer than 23deg. The three
//   WARM ones share only a 51deg arc, so they are the trio that actually needs the
//   arithmetic: Rag Tag first landed 21deg off Spender, which looked fine to me and
//   failed the gate. That is the entire reason the gate measures rather than asks. `webapp/test/screens.mjs` re-measures BOTH properties off the live
// page, so a new game whose brand colour is too dark, or too near a neighbour, fails
// the gate instead of shipping.
const GAMES = [
	{ id: "spender", name: "Spender", tagline: "A gem merchant's game of prestige", status: "ready", screen: "spender", accent: "#cba33c", players: "1–4 players" },
	{ id: "coc", name: "Castles of Crimson", tagline: "A realm of conquest and intrigue", status: "ready", screen: "coc", accent: "#ef8290", players: "1–4 players" },
	{ id: "wherewolf", name: "Where Wolf", tagline: "A village of secrets and lies", status: "ready", screen: "werewolf", accent: "#8ca5f2", players: "3–10 players" },
	{ id: "duel", name: "Spender Duel", tagline: "A two-player battle of gems and crowns", status: "ready", screen: "duel", accent: "#d18ede", players: "1–2 players" },
	// APPEND new games only — webapp/test/screens.mjs clicks .home-game-card by INDEX.
	{ id: "dontminion", name: "Dontminion", tagline: "A kingdom built one card at a time", status: "ready", screen: "dontminion", accent: "#45b3bd", players: "1–4 players" },
	{ id: "dissonance", name: "Dissonance", tagline: "Winning every trick is a losing plan", status: "ready", screen: "dissonance", accent: "#4fbe8b", players: "2 players" },
	{ id: "ragtag", name: "Rag Tag", tagline: "Two fighters, one deck you never shuffle", status: "ready", screen: "ragtag", accent: "#f68a54", players: "2 players" },
];
// Local vs AI (the offline hub) is deliberately NOT in the catalogue: with a connection the
// home menu's real games supersede it, and without one you never get past the loading screen —
// so its only entries are the loading screen's "Play offline vs AI" escape hatch and the
// /offline URL itself (games/spender/offline.js).

/* ── THE EMBLEMS ARE ONE FAMILY, AND THAT IS A CONSTRAINT, NOT A DESCRIPTION ──
 * Inline SVG rather than an icon font or an image set: they inherit currentColor for
 * the per-card accent, and cost no extra request.
 *
 * Every glyph in this file — game emblems, side-feature icons, the card chevron — is
 * drawn to the SAME three rules, because the first set was not and it showed:
 *   • one 24x24 grid, with the ink inside roughly x,y in [4,20], so no glyph reads
 *     visibly bigger or smaller than its neighbours in an identical 48px plate;
 *   • one stroke width (1.5) — the old set mixed 1.4 strokes with solid fills, so the
 *     castle looked finer than the gem sitting next to it;
 *   • one join/cap (round), and no detail finer than ~1.5 units, because these render
 *     at 27px on a card and at 20px in the side-feature row, and anything denser than
 *     that turns to mush. The old Rag Tag glyph — three fingers and a chevron — was
 *     illegible at both sizes.
 * Two emblems were also re-CONCEIVED rather than redrawn: Dontminion and Dissonance
 * were both "some playing cards" and were confusable in a list of seven, so
 * Dontminion is now its economy (a stack of coins) and Dissonance keeps the cards.
 */
const GAME_EMBLEM = {
	// A brilliant-cut gem, table and facets.
	spender: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M8 4.6h8l3 4.9-7 10.5-7-10.5Z" /><path d="M5 9.5h14M10 9.5 12 20M14 9.5 12 20" /></svg>),
	// A keep with a raised gate.
	coc: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M4.5 19.6V9.4h2.7V6.6h2.7v2.8h4.2V6.6h2.7v2.8h2.7v10.2Z" /><path d="M10 19.6v-4.4h4v4.4" /></svg>),
	// The night. Grown ~15% on the old one, which read a size smaller than the rest.
	wherewolf: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M20.1 14.9A8.4 8.4 0 1 1 10.4 4.1 6.8 6.8 0 0 0 20.1 14.9Z" /><path d="M17.3 4.4v2.6M16 5.7h2.6" /></svg>),
	// The crown the duel is played for.
	duel: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M4.2 9 7.1 16.3h9.8L19.8 9l-4.4 3.6L12 5.5 8.6 12.6Z" /><path d="M7.4 19.2h9.2" /></svg>),
	// A treasure chest — Dontminion IS its economy, and a chest cannot be mistaken for
	// "some cards" the way the old fanned deck could. It replaced a stack of coins that
	// was drawn as three stacked ellipses and therefore read, unmistakably, as a
	// DATABASE CYLINDER: the one glyph in the set naming a technology instead of a
	// subject. The domed lid is what keeps it apart from the Castles keep at 27px.
	dontminion: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M4.6 10.8c0-3.3 3.3-5.6 7.4-5.6s7.4 2.3 7.4 5.6v7.4a.9.9 0 0 1-.9.9H5.5a.9.9 0 0 1-.9-.9Z" /><path d="M4.6 10.8h14.8" /><path d="M10.6 10.8h2.8v3.3h-2.8Z" /></svg>),
	// Two cards, the near one pipped — the trick.
	dissonance: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><rect x="3.9" y="6.4" width="8.6" height="12.2" rx="1.7" transform="rotate(-11 8.2 12.5)" /><rect x="11.5" y="4.9" width="8.6" height="12.2" rx="1.7" transform="rotate(9 15.8 11)" /><path d="M15.8 8.6 17.4 10.6 15.8 12.6 14.2 10.6Z" /></svg>),
	// Crossed blades. The first attempt at "the tag" was a two-headed swap arrow, which
	// is legible at any size and is also the glyph every UI in the world uses for
	// transfer/sync — a generic affordance sitting in a row with a castle, a moon and a
	// crown. Six strokes is more than the rest of the set carries, and it is affordable
	// because a GAME emblem never renders below 27px; the side-feature icons, which do
	// go to 20px, are held to two.
	ragtag: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M19.4 4.6 9.6 14.4M7.2 13.4l3.4 3.4M7.4 16.6 5.2 18.8" /><path d="M4.6 4.6 14.4 14.4M16.8 13.4l-3.4 3.4M16.6 16.6l2.2 2.2" /></svg>),
};

// The three side features, drawn to the same three rules. Emoji were the old labels,
// and an emoji is the one glyph a hand-set page cannot absorb: it arrives as a
// different typeface, a different weight and often a different COLOUR SCHEME on every
// OS, so the row read as three stickers pasted onto the page.
const EXTRA_ICON = {
	// A planted flag, not a jigsaw piece: the puzzle piece needed two knobs and an
	// interior contour to read as one, and at the 20px these render at, that collapsed
	// into a cluster of corner brackets. A flag is two strokes and says "solved".
	puzzles: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M6.4 20.2V4" /><path d="M6.4 5.2h11.4l-2.5 3.5 2.5 3.5H6.4" /></svg>),
	books: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M12 7.3C10.6 6 8.7 5.3 6.6 5.3H4.4v12.3h2.2c2.1 0 4 .7 5.4 2" /><path d="M12 7.3c1.4-1.3 3.3-2 5.4-2h2.2v12.3h-2.2c-2.1 0-4 .7-5.4 2" /><path d="M12 7.3v12.3" /></svg>),
	// A funnel, which is what the page DOES, and which survives 20px. The die it
	// replaced was a rounded square of five pips drawn inside a rounded-square plate —
	// three nested squares at 20px, i.e. mush.
	bgg: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M4.4 5.2h15.2l-5.9 7v6.4l-3.4-2.1v-4.3Z" /></svg>),
};

// A ruled line broken by a lozenge — the page's one piece of ornament, and the
// reason the hero reads as a title plate rather than as two stacked paragraphs.
// It carries its own gradients so the rule FADES into the ground at both ends
// instead of stopping at a hard edge in the middle of empty space. It is drawn at
// 1.4 units on a 13-unit-tall box and scaled up in CSS, because at the size it was
// first set it read as a stray pair of hyphens rather than as a mark.
const HERO_RULE = (
	<svg className="home-rule" viewBox="0 0 240 14" aria-hidden="true" focusable="false" preserveAspectRatio="xMidYMid meet">
		<defs>
			<linearGradient id="fg-rule-l" x1="0" x2="1"><stop offset="0" stopColor="currentColor" stopOpacity="0" /><stop offset="1" stopColor="currentColor" stopOpacity="1" /></linearGradient>
			<linearGradient id="fg-rule-r" x1="0" x2="1"><stop offset="0" stopColor="currentColor" stopOpacity="1" /><stop offset="1" stopColor="currentColor" stopOpacity="0" /></linearGradient>
		</defs>
		<path d="M2 7h100" stroke="url(#fg-rule-l)" strokeWidth="1.4" />
		<path d="M138 7h100" stroke="url(#fg-rule-r)" strokeWidth="1.4" />
		<path d="M120 1.2 125.8 7 120 12.8 114.2 7Z" fill="currentColor" />
		<path d="M105 7h4.6M130.4 7h4.6" stroke="currentColor" strokeOpacity=".75" strokeWidth="1.4" />
	</svg>
);

const GO_CHEVRON = (
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round"><path d="M9.5 5.5 16 12l-6.5 6.5" /></svg>
);

export { SITE_NAME, SITE_FOOT, GAMES, GAME_EMBLEM, HERO_RULE };

export default function HomeScreen({ authUser, css, toast, onPickGame, onPuzzles, onBooks, onBggFilter, onLogout }) {
	// Built here rather than at module scope because each entry closes over a prop.
	const extras = [
		{ id: "puzzles", label: "Spender Puzzles", note: "Endgames with one forced win", onClick: onPuzzles },
		{ id: "books", label: "Books", note: "A reading list that ranks itself", onClick: onBooks },
		{ id: "bgg", label: "BGG Filter", note: "Sift the BoardGameGeek shelf", onClick: onBggFilter },
	];
	return (
		<>
			<style>{css}</style>
			<div className="app">
				{/* The ambient ground (warm top light, vignette, grain) is painted by
				    .home::before/::after as two fixed layers, so it does not scroll away
				    under a long catalogue and costs no extra element. */}
				<div className="home">
					{/* ONE unboxed identity string and ONE chip. It used to be a bordered
					    "Guest" pill, then a bare username, then a bordered button — three
					    items where the MIDDLE one had no frame, which does not read as a
					    hierarchy, it reads as a style rule that failed to apply. */}
					<header className="home-header">
						<div className="browser-user">
							<span className="home-ident">
								{authUser?.guest && <span className="home-ident-kind">Guest</span>}
								<span className="browser-username">{authUser?.name}</span>
							</span>
							<button className="btn btn-ghost btn-sm" onClick={onLogout}>
								{authUser?.guest ? "Exit" : "Logout"}
							</button>
						</div>
					</header>

					<div className="home-hero">
						<h1 className="home-logo">{SITE_NAME}</h1>
						{HERO_RULE}
						<p className="home-tagline">Choose a game</p>
					</div>

					<nav className="home-games" aria-label="Games">
						{GAMES.map(gm => (
							<button key={gm.id} className={`home-game-card ${gm.status}`}
								style={{ "--accent": gm.accent }}
								onClick={() => onPickGame(gm.screen)}>
								{/* FOUR FLAT CHILDREN, PLACED BY grid-template-areas, because the
								    card is two different objects at two sizes and they must not
								    be two different DOMs. In a single column it is a LIST ROW —
								    emblem rail on the left, everything else in one text column
								    beside it. From two columns up it is a POSTER — emblem on its
								    own line, then title, tagline and the player pill down the
								    same left edge. Nesting the text inside a head element made
								    the row layout easy and the poster impossible; areas make
								    both a four-line change of one rule.
								    Spans, not divs: the card is a <button>, and a <div> inside
								    phrasing content is invalid HTML that Safari has historically
								    reflowed differently from Chrome. */}
								<span className="home-game-emblem" aria-hidden="true">{GAME_EMBLEM[gm.id]}</span>
								<span className="home-game-text">
									<span className="home-game-name">{gm.name}</span>
									<span className="home-game-desc">{gm.tagline}</span>
								</span>
								<span className="home-game-players">{gm.players}</span>
								<span className="home-game-go" aria-hidden="true">{GO_CHEVRON}</span>
							</button>
						))}
					</nav>

					<section className="home-more" aria-labelledby="home-more-hd">
						<h2 className="home-more-hd" id="home-more-hd"><span>Also here</span></h2>
						<div className="home-extras">
							{extras.map(x => (
								<button key={x.id} type="button" className="home-extra" onClick={x.onClick}>
									<span className="home-extra-icon" aria-hidden="true">{EXTRA_ICON[x.id]}</span>
									<span className="home-extra-text">
										<span className="home-extra-label">{x.label}</span>
										<span className="home-extra-note">{x.note}</span>
									</span>
								</button>
							))}
						</div>
					</section>

					<footer className="home-foot">{SITE_FOOT}</footer>
				</div>
				{toast && <div className="toast">{toast}</div>}
			</div>
		</>
	);
}
