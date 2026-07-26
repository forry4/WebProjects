/* The site landing menu — pick a game.
 *
 * Second piece of the shell/game split (see AuthScreen.jsx). Purely presentational:
 * no state of its own, no data fetching. The shell still owns identity and routing
 * and passes them in, so the eventual inversion has one less screen to untangle.
 *
 * The game catalogue lives here rather than in games/spender/Spender.jsx because it
 * describes the SITE, not the Spender game — Spender is just one of its four entries.
 */
const SITE_NAME = "Forrest Games";

// `screen` is the shell's SITE-LEVEL screen id for each game (Spender's own
// browser/waiting/game live in its `spenderScreen`); `accent` drives the card's
// --accent custom property.
const GAMES = [
	{ id: "spender", name: "Spender", tagline: "A gem merchant's game of prestige", status: "ready", screen: "spender", accent: "#d4a84c", players: "1–4 players" },
	{ id: "coc", name: "Castles of Crimson", tagline: "A realm of conquest and intrigue", status: "ready", screen: "coc", accent: "#d6454b", players: "1–4 players" },
	{ id: "wherewolf", name: "Where Wolf", tagline: "A village of secrets and lies", status: "ready", screen: "werewolf", accent: "#6f86d6", players: "3–10 players" },
	{ id: "duel", name: "Spender Duel", tagline: "A two-player battle of gems and crowns", status: "ready", screen: "duel", accent: "#bf6fd0", players: "1–2 players" },
];

// Inline SVG rather than an icon font or image set: they inherit currentColor for the
// per-card accent, and cost no extra request.
const GAME_EMBLEM = {
	spender: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round"><path d="M7 5H17L20 9L12 20L4 9Z" /><path d="M4 9H20M7 5L9 9M17 5L15 9M9 9L12 20M15 9L12 20M9 9H15" /></svg>),
	coc: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round"><path d="M4 20V10H7V7H10V10H14V7H17V10H20V20Z" /><path d="M10 20V15H14V20" /></svg>),
	wherewolf: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round"><path d="M20 15A8 8 0 1 1 11 4A6.5 6.5 0 0 0 20 15Z" /><circle cx="17.5" cy="6" r=".9" fill="currentColor" stroke="none" /></svg>),
	duel: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round"><path d="M4 9L7 16H17L20 9L15.5 12.5L12 6L8.5 12.5Z" /><path d="M7.5 19H16.5" /></svg>),
};

export { SITE_NAME, GAMES, GAME_EMBLEM };

export default function HomeScreen({ authUser, css, toast, onPickGame, onPuzzles, onBooks, onLogout }) {
	return (
		<>
			<style>{css}</style>
			<div className="app">
				<div className="home">
					<div className="home-header">
						<div className="browser-user">
							{authUser?.guest && <span className="browser-guest-badge">Guest</span>}
							<span className="browser-username">{authUser?.name}</span>
							<button className="btn btn-ghost btn-sm" onClick={onLogout}>
								{authUser?.guest ? "Exit" : "Logout"}
							</button>
						</div>
					</div>

					<div className="home-hero">
						<div className="home-logo">{SITE_NAME}</div>
						<p className="home-tagline">Choose a game</p>
					</div>

					<div className="home-games">
						{GAMES.map(gm => (
							<button key={gm.id} className={`home-game-card ${gm.status}`}
								style={{ "--accent": gm.accent }}
								onClick={() => onPickGame(gm.screen)}>
								<span className="home-game-emblem" aria-hidden="true">{GAME_EMBLEM[gm.id]}</span>
								<div className="home-game-text">
									<div className="home-game-name">{gm.name}</div>
									<div className="home-game-desc">{gm.tagline}</div>
									<span className="home-game-players">{gm.players}</span>
								</div>
							</button>
						))}
					</div>

					<div style={{ textAlign: "center", marginTop: 24, display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
						<button type="button" className="btn btn-ghost" onClick={onPuzzles}>
							🧩 Spender Puzzles
						</button>
						<button type="button" className="btn btn-ghost" onClick={onBooks}>
							📚 Books
						</button>
					</div>
				</div>
				{toast && <div className="toast">{toast}</div>}
			</div>
		</>
	);
}
