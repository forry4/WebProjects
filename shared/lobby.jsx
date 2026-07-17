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

export const lobbyCss = `
/* ─── Shared lobby chrome (.lby-*) ─────────────────────────────────────────── */
/* Full-width flush top bar: back + rules (left) · title (center) · user (right). Render
   as a direct child of the app root (outside centered content) so the border spans the
   screen; left/right rails are flex:1 so the title stays truly centered. */
.lby-header{display:flex;align-items:center;gap:12px;padding:13px 24px;padding-top:calc(env(safe-area-inset-top,0px) + 13px);border-bottom:1px solid var(--border);background:var(--surface);box-shadow:0 1px 0 rgba(0,0,0,.28)}
.lby-head-left{flex:1 1 0;display:flex;align-items:center;justify-content:flex-start;gap:8px;min-width:0}
.lby-title{flex:0 0 auto;text-align:center;font-family:'Cinzel','Cinzel Fallback',serif;font-size:clamp(1.15rem,2.6vw,1.85rem);font-weight:700;color:var(--lby-accent,var(--gold));letter-spacing:.05em;white-space:nowrap}
.lby-head-right{flex:1 1 0;display:flex;align-items:center;justify-content:flex-end;gap:10px;min-width:0}
.lby-head-name{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.8rem;color:var(--text-dim);letter-spacing:.06em;max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lby-head-tag{font-size:.62rem;letter-spacing:.1em;color:var(--text-dim);border:1px solid var(--border);padding:2px 8px;border-radius:10px;font-family:'Cinzel','Cinzel Fallback',serif;text-transform:uppercase;white-space:nowrap}

/* One shared button style for the header (back + rules), identical across all games. */
.lby-back,.lby-headbtn{display:inline-flex;align-items:center;gap:6px;padding:8px 15px;border-radius:var(--radius,8px);border:1px solid var(--border);background:transparent;color:var(--text-dim);cursor:pointer;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.75rem;letter-spacing:.05em;font-weight:600;white-space:nowrap;transition:border-color .15s,color .15s}
.lby-back:hover,.lby-headbtn:hover{border-color:var(--lby-accent,var(--gold));color:var(--text)}

/* Section header: micro uppercase accent label + optional muted note, underlined. */
.lby-section-hd{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.lby-section-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.7rem;letter-spacing:.18em;color:var(--lby-accent,var(--gold));text-transform:uppercase}
.lby-muted{font-size:.74rem;color:var(--text-dim)}

/* Game-card row. */
.lby-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:13px 15px;display:flex;align-items:center;gap:14px;margin-bottom:9px;transition:border-color .15s,background .15s,transform .15s}
.lby-card:hover{border-color:var(--lby-accent,var(--gold));background:var(--surface2);transform:translateY(-1px)}
.lby-card-info{flex:1;min-width:0}
.lby-card-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.9rem;letter-spacing:.03em;margin-bottom:4px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lby-card-meta{font-size:.78rem;color:var(--text-dim)}
.lby-card-actions{display:flex;align-items:center;gap:8px;flex-shrink:0}
/* History rows (shared): a Won/Lost/Tie badge on the left + the final scores with YOUR
   number bold — matching Spender's history look. Put both inside a .lby-card-title. */
.hist-result{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.6rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:2px 8px;border-radius:10px;flex-shrink:0}
.hist-result.won{background:rgba(63,156,46,.18);color:var(--green-gem)}
.hist-result.lost,.hist-result.tie{background:var(--surface2);color:var(--text-dim);border:1px solid var(--border)}
.hist-scores{color:var(--text-dim);font-size:.84rem;font-family:'Crimson Pro','Crimson Fallback',Georgia,serif;letter-spacing:0}
.hist-score-num{color:var(--text);font-weight:600}

/* Empty state (dashed placeholder). */
.lby-empty{text-align:center;padding:26px 16px;color:var(--text-dim);font-style:italic;font-size:.9rem;background:var(--surface2);border-radius:var(--radius);border:1px dashed var(--border)}

/* Loading screen (shown while a game boots / fetches). */
.lby-loading{min-height:56vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;color:var(--text-dim);font-family:'Cinzel','Cinzel Fallback',serif;font-size:.82rem;letter-spacing:.12em;text-transform:uppercase}
.lby-spinner{width:30px;height:30px;border:3px solid var(--border);border-top-color:var(--lby-accent,var(--gold));border-radius:50%;animation:lby-spin .7s linear infinite}
@keyframes lby-spin{to{transform:rotate(360deg)}}

/* Turn / status pill: "-turn" = your turn (accent), "-wait" = someone else (muted). */
.lby-badge{padding:3px 10px;border-radius:12px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;letter-spacing:.1em;text-transform:uppercase;white-space:nowrap}
.lby-badge-turn{background:var(--lby-accent,var(--gold));color:var(--bg);font-weight:700}
.lby-badge-wait{background:var(--surface2);color:var(--text-dim);border:1px solid var(--border)}

@media(max-width:600px){.lby-header{padding-left:14px;padding-right:14px;gap:8px}}
`;

// Full-width flush top bar. Renders its own back + rules buttons (uniform across games);
// `user` is the right-side slot (name / guest badge). rulesLabel lets Duel say "How to Play".
export function LobbyHeader({ onBack, backLabel = "← Back", title, onRules, rulesLabel = "📖 Rules", user }) {
	return (
		<div className="lby-header">
			<div className="lby-head-left">
				{onBack && <button className="lby-back" onClick={onBack}>{backLabel}</button>}
				{onRules && <button className="lby-headbtn" onClick={onRules}>{rulesLabel}</button>}
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

export function LobbyEmpty({ children }) {
	return <div className="lby-empty">{children}</div>;
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

// ─── In-game options menu (shared across all four games) ─────────────────────
// A single hamburger button that opens a dropdown of game actions — replaces the
// per-game row of Menu / Rules / Abandon buttons in the in-game top bar. Pass an
// `items` array of { label, onClick, icon?, danger? }; falsy entries are skipped
// so a game can conditionally omit an action (e.g. Where Wolf has no Abandon).
// Token-driven with hard fallbacks so it renders correctly even in CoC's bare
// mount (no baseCss). Append `gameMenuCss` to the game's own <style>.
export const gameMenuCss = `
.gm-wrap{position:relative;display:inline-flex}
.gm-btn{display:inline-flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;width:40px;height:34px;padding:0;background:var(--surface2,#241d16);border:1px solid var(--border,#3a3226);border-radius:8px;cursor:pointer;transition:background .15s,border-color .15s}
.gm-btn:hover{background:var(--surface3,#2c241a);border-color:var(--lby-accent,var(--gold,#d4a84c))}
.gm-btn span{display:block;width:17px;height:2px;border-radius:2px;background:var(--text-dim,#b8ab90);transition:background .15s}
.gm-btn:hover span{background:var(--lby-accent,var(--gold,#d4a84c))}
.gm-menu{position:absolute;top:calc(100% + 6px);z-index:300;min-width:184px;background:var(--surface,#1b1712);border:1px solid var(--border,#3a3226);border-radius:10px;padding:6px;box-shadow:0 10px 28px -8px rgba(0,0,0,.7);display:flex;flex-direction:column;gap:2px}
.gm-menu.gm-left{left:0}
.gm-menu.gm-right{right:0}
.gm-item{display:flex;align-items:center;gap:10px;width:100%;text-align:left;padding:9px 11px;background:none;border:none;border-radius:6px;cursor:pointer;font-family:inherit;font-size:.9rem;color:var(--text,#e8dfce);white-space:nowrap;transition:background .12s}
.gm-item:hover{background:rgba(255,255,255,.07)}
.gm-item.gm-danger{color:var(--red-gem,#dc4d4d)}
.gm-item.gm-danger:hover{background:rgba(220,77,77,.14)}
.gm-item-ic{width:17px;text-align:center;font-size:.95rem;opacity:.9;flex:none}
`;

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
