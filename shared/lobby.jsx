// Shared lobby kit for the Forrest Games site — the single source of truth for every
// game's lobby CHROME (top header bar, section headers, game-card rows, empty states,
// turn/status badges). Extracted so the four games (Spender, Castles of Crimson, Where
// Wolf?, Spender Duel) share one layout grammar instead of drifting apart.
//
// Everything here is TOKEN-DRIVEN (var(--surface) / var(--gold) / var(--border) / …), so
// each game keeps its OWN palette — Spender's neutral gold, CoC's crimson tint — while the
// structure, type scale, and spacing stay identical. CoC scopes its tokens to `.coc{…}`;
// its lobby renders inside a `.coc` element, so the tokens resolve there too.
//
// Prepend `lobbyCss` to a screen's own CSS, same as baseCss:  <style>{baseCss + lobbyCss + myCss}</style>
// (CoC has no baseCss — it prepends lobbyCss to its self-contained `css`.)
//
// The components are SLOT-based (the game passes its own back button / user chrome as
// nodes) so the kit never depends on a game-specific button class.
import React from "react";

export const lobbyCss = `
/* ─── Shared lobby chrome (.lby-*) ─────────────────────────────────────────── */
/* Full-width flush top bar: back (left) · title (center) · user/actions (right).
   Render it as a direct child of the app root (OUTSIDE the centered content) so its
   bottom border spans the whole screen. The left/right rails are flex:1 so the title
   sits truly centered regardless of how wide each side's content is. */
.lby-header{display:flex;align-items:center;gap:12px;padding:12px 24px;padding-top:calc(env(safe-area-inset-top,0px) + 12px);border-bottom:1px solid var(--border);background:var(--surface)}
.lby-head-left{flex:1 1 0;display:flex;align-items:center;justify-content:flex-start;gap:8px;min-width:0}
.lby-title{flex:0 0 auto;text-align:center;font-family:'Cinzel','Cinzel Fallback',serif;font-size:clamp(1.15rem,4vw,2rem);font-weight:700;color:var(--gold);letter-spacing:.04em;white-space:nowrap}
.lby-head-right{flex:1 1 0;display:flex;align-items:center;justify-content:flex-end;gap:10px;min-width:0}
.lby-head-name{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.8rem;color:var(--text-dim);letter-spacing:.06em;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lby-head-tag{font-size:.65rem;letter-spacing:.1em;color:var(--text-dim);border:1px solid var(--border);padding:2px 7px;border-radius:10px;font-family:'Cinzel','Cinzel Fallback',serif;text-transform:uppercase;white-space:nowrap}

/* Section header: a micro uppercase Cinzel label + an optional muted note, underlined. */
.lby-section-hd{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.lby-section-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.7rem;letter-spacing:.18em;color:var(--gold);text-transform:uppercase}
.lby-muted{font-size:.74rem;color:var(--text-dim)}

/* Game-card row: info block (title + meta) on the left, actions on the right. */
.lby-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px 16px;display:flex;align-items:center;gap:14px;margin-bottom:8px;transition:border-color .15s}
.lby-card:hover{border-color:color-mix(in srgb,var(--gold) 45%,transparent)}
.lby-card-info{flex:1;min-width:0}
.lby-card-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.88rem;letter-spacing:.04em;margin-bottom:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lby-card-meta{font-size:.78rem;color:var(--text-dim)}
.lby-card-actions{display:flex;align-items:center;gap:8px;flex-shrink:0}

/* Empty state (dashed placeholder card). */
.lby-empty{text-align:center;padding:28px 16px;color:var(--text-dim);font-style:italic;font-size:.9rem;background:var(--surface2);border-radius:var(--radius);border:1px dashed var(--border)}

/* Turn / status pill: "-turn" = it's you (gold), "-wait" = someone else (muted). The
   text color on the gold badge is each game's own darkest bg token, so it reads on both
   the neutral and the crimson palette. */
.lby-badge{padding:3px 10px;border-radius:12px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.63rem;letter-spacing:.1em;text-transform:uppercase;white-space:nowrap}
.lby-badge-turn{background:var(--gold);color:var(--bg);font-weight:700}
.lby-badge-wait{background:var(--surface2);color:var(--text-dim);border:1px solid var(--border)}

/* On phones the centered title can crowd the back button; trim the header's side padding
   (the title itself already shrinks via its clamp()). */
@media(max-width:600px){.lby-header{padding-left:14px;padding-right:14px}}
`;

// Full-width flush top bar. `left`/`right` are slots (pass your own back button + user
// chrome), `title` is the centered game name.
export function LobbyHeader({ left, title, right }) {
	return (
		<div className="lby-header">
			<div className="lby-head-left">{left}</div>
			<div className="lby-title">{title}</div>
			<div className="lby-head-right">{right}</div>
		</div>
	);
}

// Section header row: a micro uppercase label + an optional muted note on the right.
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

// Turn/status pill. mine=true → gold "your turn"; else the muted "their turn / waiting".
export function TurnBadge({ mine, children }) {
	return <span className={`lby-badge ${mine ? "lby-badge-turn" : "lby-badge-wait"}`}>{children}</span>;
}
