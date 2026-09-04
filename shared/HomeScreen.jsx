/* The site landing menu — pick a game.
 *
 * Second piece of the shell/game split (see AuthScreen.jsx). Purely presentational:
 * no state of its own, no data fetching. The shell still owns identity and routing
 * and passes them in, so the eventual inversion has one less screen to untangle.
 *
 * The game catalogue lives here rather than in games/spender/Spender.jsx because it
 * describes the SITE, not the Spender game — Spender is just one of its entries.
 */
import { GAME_CATALOG } from "./catalog.js";
// The emblems live in their own module: a game's LOBBY hero draws the same mark,
// and it must come from one source rather than a second hand-drawn copy.
import { GAME_EMBLEM } from "./emblems.jsx";

const SITE_NAME = "Forrest Games";

// THE CATALOGUE MOVED to shared/catalog.js. It is no longer only the menu's list:
// every lobby's identity band draws the same name, player range and emblem from it,
// and two copies that agree by habit is the drift this repo keeps paying for.
// `accent` (the card's --accent custom property) is merged in there from
// shared/accents.js, which stays the single source for the colour.
const GAMES = GAME_CATALOG;

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

export { SITE_NAME, GAMES, GAME_EMBLEM, HERO_RULE };

export default function HomeScreen({ authUser, css, toast, onPickGame, onPuzzles, onBooks, onBggFilter, onLogout }) {
	// Built here rather than at module scope because each entry closes over a prop.
	const extras = [
		{ id: "puzzles", label: "Spender Puzzles", onClick: onPuzzles },
		{ id: "books", label: "Books", onClick: onBooks },
		{ id: "bgg", label: "BGG Filter", onClick: onBggFilter },
	];
	return (
		<>
			<style>{css}</style>
			<div className="app">
				{/* The ambient ground (warm top light, vignette, grain) is painted by
				    .home::before/::after as two fixed layers, so it does not scroll away
				    under a long catalogue and costs no extra element. */}
				<div className="home">
					{/* Same main shell as the auth and loading screens, so the three read as
					    one page as the boot moves through them. */}
					<div className="home-main">
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
							<button key={gm.id} className={`home-game-card ${gm.status}`} data-game={gm.id}
								style={{ "--accent": gm.accent }}
								onClick={() => onPickGame(gm.screen)}>
								{/* FOUR FLAT CHILDREN, PLACED BY grid-template-areas, because the
								    card is two different objects at two sizes and they must not
								    be two different DOMs. In a single column it is a LIST ROW —
								    emblem rail on the left, everything else in one text column
								    beside it. From two columns up it is a POSTER — emblem on its
								    own line, then the title and the player pill down the
								    same left edge. Nesting the text inside a head element made
								    the row layout easy and the poster impossible; areas make
								    both a four-line change of one rule.
								    Spans, not divs: the card is a <button>, and a <div> inside
								    phrasing content is invalid HTML that Safari has historically
								    reflowed differently from Chrome. */}
								<span className="home-game-emblem" aria-hidden="true">{GAME_EMBLEM[gm.id]}</span>
								<span className="home-game-text">
									<span className="home-game-name">{gm.name}</span>
								</span>
								<span className="home-game-players">{gm.players}</span>
								<span className="home-game-go" aria-hidden="true">{GO_CHEVRON}</span>
							</button>
						))}
					</nav>

					<section className="home-more" aria-labelledby="home-more-hd">
						<h2 className="home-more-hd" id="home-more-hd"><span>Extras</span></h2>
						<div className="home-extras">
							{extras.map(x => (
								<button key={x.id} type="button" className="home-extra" onClick={x.onClick}>
									<span className="home-extra-icon" aria-hidden="true">{EXTRA_ICON[x.id]}</span>
									<span className="home-extra-label">{x.label}</span>
								</button>
							))}
						</div>
					</section>
					</div>
				</div>
				{toast && <div className="toast">{toast}</div>}
			</div>
		</>
	);
}
