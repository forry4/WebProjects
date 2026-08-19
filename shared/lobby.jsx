// Shared lobby kit for the Forrest Games site — the single source of truth for every
// game's lobby CHROME (top header bar + its buttons, section headers, game-card rows,
// empty states, loading screen, turn/status badges). Extracted so the four games
// (Spender, Castles of Crimson, Where Wolf?, Spender Duel) share one layout grammar
// instead of drifting apart.
//
// TOKEN-DRIVEN: everything reads var(--surface)/var(--border)/… so a game keeps its base
// palette, and --lby-accent (per-game, falls back to --gold) threads the game's identity
// color through the title, section labels, badges, and hovers — matching the home cards.
// Set it on the lobby root:  style={{ "--lby-accent": "#d6454b" }}
//
// Prepend `lobbyCss` to a screen's own CSS, same as baseCss.
// Components are self-contained (the header renders its OWN back/rules buttons via
// .lby-back/.lby-headbtn) so the kit never depends on a game's button system.
import React, { useState, useRef, useEffect } from "react";

// CSS lives in the sibling .css file(s) imported below, NOT in a JS template
// literal. `?inline` hands us the stylesheet as a STRING, so it is still injected
// by this component's own <style> tag only while it is mounted — behaviour is
// unchanged. What goes away is the footgun: a single stray backtick inside a css
// template literal silently reparsed the rest of the file as a tagged template and
// blanked the whole page. A .css file cannot do that, and editors lint it properly.
import _lobbyCssText from "./lobby.lobby-css.css?inline";
import _createModalCssText from "./lobby.create-modal-css.css?inline";
import _lobbyCreateRowCssText from "./lobby.lobby-create-row-css.css?inline";
import _gameMenuCssText from "./lobby.game-menu-css.css?inline";
import _rulesModalCssText from "./lobby.rules-modal-css.css?inline";

export const lobbyCss = _lobbyCssText;

// Full-width flush top bar. Renders its own back + rules buttons (uniform across games);
// `user` is the right-side slot (name / guest badge). rulesLabel lets Duel say "How to Play".
// `menu` is the IN-GAME shape and takes precedence over the buttons: every game
// shows a single ☰ dropdown once you are at a board, never a row of Back/Rules
// buttons. Pass `menu={<GameMenu items={…} />}` there and `onBack`/`onRules` in
// the lobby, where a plain Back is right.
export function LobbyHeader({ onBack, backLabel = "← Back", title, onRules, rulesLabel = "📖 Rules", user, menu }) {
	return (
		<div className="lby-header">
			<div className="lby-head-left">
				{menu || <>
					{onBack && <button className="lby-back" onClick={onBack}>{backLabel}</button>}
					{onRules && <button className="lby-headbtn" onClick={onRules}>{rulesLabel}</button>}
				</>}
			</div>
			<div className="lby-title">{title}</div>
			<div className="lby-head-right">{user}</div>
		</div>
	);
}

// Section header row: a micro uppercase accent label + an optional muted note.
export function LobbySectionHd({ title, note }) {
	return (
		<div className="lby-section-hd">
			<div className="lby-section-title">{title}</div>
			{note != null && <span className="lby-muted">{note}</span>}
		</div>
	);
}

// A room you have joined but which has NOT started is waiting, not active. It
// already appears in Open — with a Cancel if you host it — so listing it again
// as in-progress offers a Resume that just drops you back in the waiting room.
// Only Duel filtered; Spender, CoC, Dontminion and Dissonance all showed waiting
// rooms as active, which is the kind of thing that stays wrong in four places
// at once precisely because each lobby built its own list.
export function notWaiting(games) {
	return (games || []).filter((g) => g.status !== "open");
}

// The one action button a lobby row gets. Extracted because the five lobbies had
// drifted to four different styles for the SAME Resume button (btn / btn-gold /
// btn-outline / btn-outline btn-sm), and a class name copied per game is a
// difference nobody chose.
export function LobbyAction({ kind = "primary", onClick, children, title }) {
	const cls = kind === "primary" ? "btn btn-gold"
		: kind === "danger" ? "btn btn-ghost"
			: "btn btn-outline";
	return (
		<button type="button" className={cls} onClick={onClick} title={title}>
			{children}
		</button>
	);
}

export function LobbyEmpty({ children }) {
	return <div className="lby-empty">{children}</div>;
}

// The mobile-only segmented bar that picks WHICH lobby column shows once the grid
// has collapsed to one. Spender, Duel and Dontminion each carried a near-verbatim
// copy of this (identical gap/radius/padding/flex/type scale — only the accent and
// a couple of alpha values differed), and CoC never got one at all despite having
// the same three columns.
//
// `tabs` = [{ key, label, count? }]; `key` must match the column's
// `lby-col-<key>` class, because the SHOW/HIDE is pure CSS off `tab-<key>` on the
// grid (see .lby-cols in the stylesheet) rather than conditional rendering — a
// hidden column stays mounted, so its scroll position and this list's paging
// survive tab switches.
export function LobbyTabs({ tabs, value, onChange }) {
	return (
		<div className="lby-tabs" role="tablist">
			{tabs.filter(Boolean).map((t) => (
				<button key={t.key} type="button" role="tab" aria-selected={value === t.key}
					className={`lby-tab${value === t.key ? " sel" : ""}`}
					onClick={() => onChange(t.key)}>
					{t.label}
					{t.count != null && <span className="lby-tab-count">{t.count}</span>}
				</button>
			))}
		</div>
	);
}

// Centered spinner + label — the shared game-entry loading screen.
export function LobbyLoading({ label = "Loading…" }) {
	return (
		<div className="lby-loading">
			<span className="lby-spinner" />
			<span>{label}</span>
		</div>
	);
}

// Turn/status pill. mine=true → accent "your turn"; else the muted "their turn / waiting".
export function TurnBadge({ mine, children }) {
	return <span className={`lby-badge ${mine ? "lby-badge-turn" : "lby-badge-wait"}`}>{children}</span>;
}

// Stale-while-revalidate cache for the lobby lists — render the last-known lists INSTANTLY
// on a repeat open, then let the fetch refresh them. localStorage + JSON, namespaced by
// game (ns) + user/guest id (scope) + list key, so different accounts on one device never
// see each other's lists (history is user-specific). All best-effort — any failure is a
// no-op fallback, never a throw.
export function readLobbyCache(ns, scope, key, fallback) {
	try {
		const v = localStorage.getItem(`lbyc.${ns}.${scope}.${key}`);
		return v ? JSON.parse(v) : fallback;
	} catch { return fallback; }
}
export function writeLobbyCache(ns, scope, key, val) {
	try { localStorage.setItem(`lbyc.${ns}.${scope}.${key}`, JSON.stringify(val)); } catch {}
}

// ─── Last-played AI difficulty (every game that has an AI opponent) ──────────
// The create modal's difficulty row starts on whatever this player last STARTED
// a game against — per game, per identity — instead of one hardcoded tier for
// everyone forever. Same storage discipline as the lobby cache above:
// localStorage, namespaced by game (ns) + user/guest id (scope), every access
// best-effort (a failure is a no-op fallback, never a throw).
//
// It is written when a vs-AI game is actually CREATED, not when the picker
// moves — "last PLAYED". Opening the modal, browsing the tiers and backing out,
// or creating a vs-Friend game, all leave the remembered tier alone.
//
// The stored id is validated against the tiers the game currently OFFERS, so a
// retired one (Spender's variant codes, Dontminion's plain Big Money) falls
// back to the game's own default instead of restoring a selection the server
// would silently coerce to a different bot than the label claims.
const lastDiffKey = (ns, scope) => `lastdiff.${ns}.${scope}`;

export function readLastDifficulty(ns, scope, offered, fallback) {
	try {
		const v = localStorage.getItem(lastDiffKey(ns, scope));
		return v !== null && offered.includes(v) ? v : fallback;
	} catch { return fallback; }
}
export function writeLastDifficulty(ns, scope, value) {
	try { localStorage.setItem(lastDiffKey(ns, scope), String(value)); } catch {}
}

// `[value, setValue, remember]` — a drop-in for the `useState` the create modal
// used to hold. `remember(v)` is what makes a tier stick, so call it where the
// vs-AI game is created, not from the picker's onChange.
export function useLastDifficulty(ns, scope, offered, fallback) {
	const [value, setValue] = useState(() => readLastDifficulty(ns, scope, offered, fallback));
	// Identity can change under a mounted lobby (log in / log out) and the
	// remembered tier is per-identity, so re-read when scope moves. Guarded by a
	// ref rather than by a dep list: `offered` is an array literal at every call
	// site, so a dep on it would re-run every render and clobber the pick the
	// player just made in the open modal.
	const scopeRef = useRef(scope);
	useEffect(() => {
		if (scopeRef.current === scope) return;
		scopeRef.current = scope;
		setValue(readLastDifficulty(ns, scope, offered, fallback));
	});
	return [value, setValue, (v) => writeLastDifficulty(ns, scope, v)];
}

// ─── Progressive History reveal (all four games' History lists) ──────────────
// Show the newest HISTORY_PAGE games, reveal another page when the reader
// scrolls the end of the list into view, and stop at HISTORY_MAX.
//
// HISTORY_MAX IS ALSO EVERY BACKEND'S `list_user_history` SQL LIMIT (they were
// 20/30/30/30 and are now 50 across the board), so the ceiling is enforced on
// both sides: the client can never ask for a page the server didn't send, and a
// cached old bundle against the new server simply renders all 50 at once.
//
// A SENTINEL + IntersectionObserver, not a scroll handler, because the four
// lobbies scroll differently and a handler would need to know which element
// moves: Spender's `.game-cards` is its own overflow container above 1281px and
// the PAGE scrolls below that, CoC/Duel/Dontminion have no scroller at all so
// only the page ever moves, and the mobile tab layouts move a third thing
// again. The sentinel is correct in all of them and needs no CSS. (An element
// clipped by an ancestor's `overflow` is reported as NOT intersecting, which is
// exactly what makes Spender's inner scroller work without a special case.)
export const HISTORY_PAGE = 10;
export const HISTORY_MAX = 50;

export function useProgressiveList(items, { page = HISTORY_PAGE, max = HISTORY_MAX } = {}) {
	const [shown, setShown] = useState(page);
	const sentinelRef = useRef(null);
	const visible = items.slice(0, Math.min(shown, max));
	const more = visible.length < Math.min(items.length, max);
	// `shown` is a dep on purpose: an observer only calls back when intersection
	// CHANGES, so a sentinel that is still on screen after a reveal would never
	// fire again and the list would strand at 20. Re-observing re-reports the
	// current state, which fills until the sentinel is off screen or max is hit
	// — the standard behaviour, and self-limiting at HISTORY_MAX / page steps.
	useEffect(() => {
		const el = sentinelRef.current;
		if (!el || !more) return;
		if (typeof IntersectionObserver !== "function") { setShown(max); return; }
		const io = new IntersectionObserver((entries) => {
			if (entries.some((e) => e.isIntersecting)) setShown((n) => Math.min(n + page, max));
		});
		io.observe(el);
		return () => io.disconnect();
	}, [more, shown, page, max]);
	// `shown` deliberately SURVIVES a refresh: the lobby re-fetches its lists on
	// a poll/refresh, and resetting here would yank a reader three pages in back
	// to the top every time one of their games ended.
	const sentinel = more
		? <div className="lby-more" ref={sentinelRef} aria-hidden="true" />
		: null;
	return [visible, sentinel];
}

// ─── Create-game modal kit (shared across all four games) ────────────────────
// One "+ Create Game" button per lobby opens a CreateModal holding every option
// (opponent, AI difficulty, seats, length, boards…) as labeled rows — replaces the
// per-game floating dropdown pickers. Token-driven with hard fallbacks (CoC's bare
// mount has no baseCss); --lby-accent threads each game's identity color through
// the selected states + Create button. Append `createModalCss` to the game's CSS.
export const createModalCss = _createModalCssText;

// The lobby create/join/refresh/rules row — one shared control bar across all six games:
//   [ + Create Game (gold) ]  [ CODE ] [ Join ]  [ ↻ ]  [ 📖 Rules ]
// The create button is ALWAYS gold (not the per-game accent), matching CoC; Rules carries
// the per-game accent. `onJoin` receives the trimmed, upper-cased code; `codeMaxLength` is
// 6 everywhere except Where Wolf (4). `onRules` is optional only so the component stays
// usable without one — every lobby passes it. Token-driven with hard fallbacks so it
// renders in CoC's bare mount too. On phones the row SCROLLS SIDEWAYS rather than wrapping
// (five controls stop fitting at ~430px) — see the stylesheet.
export const lobbyCreateRowCss = _lobbyCreateRowCssText;

export function LobbyCreateRow({ onCreate, onJoin, onRefresh, refreshing = false,
	onRules, rulesLabel = "Rules", createLabel = "+ Create Game", codeMaxLength = 6,
	extra = null }) {
	const [code, setCode] = useState("");
	const submit = () => { const c = code.trim().toUpperCase(); if (c) onJoin(c); };
	return (
		<div className="lby-create-row">
			<button type="button" className="lby-cta" onClick={onCreate}>{createLabel}</button>
			<div className="lby-join">
				<input className="lby-code" placeholder="CODE" value={code} maxLength={codeMaxLength}
					onChange={(e) => setCode(e.target.value)}
					onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
				<button type="button" className="lby-join-btn" onClick={submit}>Join</button>
			</div>
			<button type="button" className="lby-refresh" aria-label="Refresh" onClick={onRefresh}>
				{refreshing ? <span className="lby-spinner" /> : "↻"}
			</button>
			{onRules && (
				<button type="button" className="lby-rules" onClick={onRules}>
					<span className="lby-rules-ic" aria-hidden="true">📖</span>{rulesLabel}
				</button>
			)}
			{/* ONE OPTIONAL SLOT, after Rules, for a control only one game has —
			    today Dissonance's paper scorecard. A node rather than an
			    `onX`/`xLabel` pair, so the kit never learns what any single game
			    keeps there. Style its button `.lby-extra`, which the sheet gives
			    the Rules look: a SEPARATE class on purpose, because `.lby-rules`
			    is how the render gate counts Rules buttons and a second one
			    wearing that class reads as a duplicate. It is the SIXTH control
			    in a row that already stops fitting a phone at ~430px, which the
			    sideways scroll handles (`justify-content: safe center` — plain
			    `center` pushes the overflow off the unreachable LEFT edge). */}
			{extra}
		</div>
	);
}

// ─── Rules ("How to play") modal kit — shared by all six games ───────────────
// The CHROME is shared; the CONTENT stays per-game (each game has a rules.jsx
// next to it). One panel means one scrolling behaviour: the panel is capped to
// the viewport and `.rl-body` is the only scroller, so a ruleset can be as long
// as it needs to be without ever growing the page or clipping its own footer.
// Append `rulesModalCss` to the game's CSS (after `lobbyCreateRowCss`).
export const rulesModalCss = _rulesModalCssText;

export function RulesModal({ title = "How to play", onClose, closeLabel = "Got it",
	icon = "📖", children }) {
	useEffect(() => {
		const onKey = (e) => { if (e.key === "Escape") onClose(); };
		document.addEventListener("keydown", onKey);
		return () => document.removeEventListener("keydown", onKey);
	}, [onClose]);
	return (
		<div className="rl-backdrop" onClick={onClose}>
			<div className="rl-panel" role="dialog" aria-modal="true" aria-label={title}
				onClick={(e) => e.stopPropagation()}>
				<div className="rl-head">
					<div className="rl-title">{icon} {title}</div>
					<button type="button" className="rl-x" aria-label="Close" onClick={onClose}>✕</button>
				</div>
				<div className="rl-body">{children}</div>
				<div className="rl-foot">
					<button type="button" className="rl-done" onClick={onClose}>{closeLabel}</button>
				</div>
			</div>
		</div>
	);
}

// An accent-headed section of the rules.
export function RulesSection({ title, children }) {
	return (
		<section className="rl-sec">
			<h4>{title}</h4>
			{children}
		</section>
	);
}

// The "at a glance" strip at the top of every ruleset: players / length / goal.
// `items` = [{ k, v }] — k is the micro uppercase label, v the value.
export function RulesFacts({ items }) {
	return (
		<div className="rl-facts">
			{items.filter(Boolean).map((it, i) => (
				<div className="rl-fact" key={i}>
					<span className="rl-fact-k">{it.k}</span>
					<span className="rl-fact-v">{it.v}</span>
				</div>
			))}
		</div>
	);
}

// Term/definition grid — roles, tile types, card abilities, phases. `items` =
// [{ t, d }]. Two columns on desktop, stacked below 560px (see the stylesheet).
export function RulesDefs({ items }) {
	return (
		<dl className="rl-dl">
			{items.filter(Boolean).map((it, i) => (
				<React.Fragment key={i}>
					<dt>{it.t}</dt>
					<dd>{it.d}</dd>
				</React.Fragment>
			))}
		</dl>
	);
}

// A called-out aside inside a section ("the thing to notice").
export function RulesTip({ children }) {
	return <div className="rl-tip">{children}</div>;
}

// Backdrop + panel + titled header with a ✕. Backdrop click and Escape both close.
export function CreateModal({ title, onClose, children }) {
	useEffect(() => {
		const onKey = (e) => { if (e.key === "Escape") onClose(); };
		document.addEventListener("keydown", onKey);
		return () => document.removeEventListener("keydown", onKey);
	}, [onClose]);
	return (
		<div className="cm-backdrop" onClick={onClose}>
			<div className="cm-panel" onClick={(e) => e.stopPropagation()}>
				<div className="cm-head">
					<div className="cm-title">{title}</div>
					<button type="button" className="cm-x" aria-label="Close" onClick={onClose}>✕</button>
				</div>
				{children}
			</div>
		</div>
	);
}

// A labeled option row (micro uppercase label above the control).
export function CmRow({ label, children }) {
	return (
		<div className="cm-row">
			{label != null && <span className="cm-label">{label}</span>}
			{children}
		</div>
	);
}

/* Segmented control: options = [{ value, label, title? }].
 *
 * `wrap` turns the single clipped row into a WRAPPING chip group, and it exists
 * because the base control cannot hold four long labels on a phone: the buttons
 * are `white-space: nowrap` inside an `overflow: hidden` box, so anything past
 * the fold is not merely off-screen, it is UNREACHABLE — no scroll, no
 * affordance, nothing to swipe. Measured on the offline hub's game picker at a
 * 390px viewport: 485px of buttons in a 330px box, with the fourth option
 * ending 154px past the right edge. Opt in wherever the option count or the
 * label length can grow; the default stays exactly as it was for the five
 * modals that fit.
 */
export function CmSeg({ options, value, onChange, wrap = false }) {
	return (
		<div className={`cm-seg${wrap ? " cm-seg-wrap" : ""}`}>
			{options.map((o) => (
				<button key={String(o.value)} type="button" title={o.title}
					className={`cm-seg-btn${value === o.value ? " sel" : ""}`}
					onClick={() => onChange(o.value)}>{o.label}</button>
			))}
		</div>
	);
}

// ─── In-game options menu (shared across all four games) ─────────────────────
// A single hamburger button that opens a dropdown of game actions — replaces the
// per-game row of Menu / Rules / Abandon buttons in the in-game top bar. Pass an
// `items` array of { label, onClick, icon?, danger? }; falsy entries are skipped
// so a game can conditionally omit an action (e.g. Where Wolf has no Abandon).
// Token-driven with hard fallbacks so it renders correctly even in CoC's bare
// mount (no baseCss). Append `gameMenuCss` to the game's own <style>.
export const gameMenuCss = _gameMenuCssText;

export function GameMenu({ items, align = "left", label = "Menu" }) {
	const [open, setOpen] = useState(false);
	const ref = useRef(null);
	useEffect(() => {
		if (!open) return;
		const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
		const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
		document.addEventListener("mousedown", onDoc);
		document.addEventListener("keydown", onKey);
		return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
	}, [open]);
	return (
		<div className="gm-wrap" ref={ref}>
			<button type="button" className="gm-btn" aria-haspopup="menu" aria-expanded={open}
				aria-label={label} onClick={() => setOpen((o) => !o)}>
				<span /><span /><span />
			</button>
			{open && (
				<div className={`gm-menu gm-${align}`} role="menu">
					{items.filter(Boolean).map((it, i) => (
						<button type="button" key={i} role="menuitem"
							className={`gm-item${it.danger ? " gm-danger" : ""}`}
							onClick={() => { setOpen(false); it.onClick(); }}>
							{it.icon != null && <span className="gm-item-ic">{it.icon}</span>}
							{it.label}
						</button>
					))}
				</div>
			)}
		</div>
	);
}
