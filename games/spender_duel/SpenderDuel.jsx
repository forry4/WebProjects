import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { baseCss } from "../../shared/theme.js";
import { lobbyCss, LobbyHeader, LobbySectionHd, TurnBadge, GameMenu, gameMenuCss, readLobbyCache, writeLobbyCache,
  createModalCss, CreateModal, CmRow, CmSeg, LobbyCreateRow, lobbyCreateRowCss } from "../../shared/lobby.jsx";
// The gems, jewel cards and move log are SHARED with Spender (same game family, so
// they must look the same). Duel adds only what Splendor Duel needs on top: pearls,
// crowns, wild bonuses and ability glyphs — all optional props on the same CardView.
import {
  GemToken, CardView, LogEntry, TokenPill, BonusPill, GEM_COLORS, GEM_HEX,
  splendorPanelCss, splendorCardCss, splendorCardExtraCss, splendorPillCss,
  splendorLogCss,
} from "../../shared/splendor.jsx";
import { parsePath, buildPath, pushPath, replacePath, subscribe } from "../../shared/router.js";

// ─── Config ────────────────────────────────────────────────────────────────
const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const DUEL_WS = WS_RAW.replace(/\/ws$/, "/duel/ws");
const DUEL_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/duel");

// Palette + labels come from shared/splendor.jsx — one source for both games, so the
// gems here are literally Spender's gems.
const COLORS = GEM_COLORS;
const TOKENS = [...COLORS, "pearl", "gold"];

// Flat pace for the client-side bot: each move takes at least this long, so it reads as
// deliberating instead of snapping instantly. The search itself finishes in ~270ms (Duel
// strength plateaus ~700 sims and it runs ~60k), so extra thinking buys NO strength — we
// PAD to this floor rather than burn CPU/battery searching longer.
const CLIENT_AI_MIN_MS = 1500;
// take_same has no text glyph: it's drawn as a CIRCLE in the colour of the gem you may
// take (which is the card's own bonus colour — cards.py guarantees take_same cards carry
// a concrete colour), so the ability tells you WHICH gem at a glance. See abilityGlyph().
const ABILITY_GLYPH = { again: "↻", privilege: "⚜", steal: "✋" };
const abilityGlyph = (card) =>
  card.ability === "take_same" ? (
    <>+<span className="card-ability-gem" style={{ background: GEM_HEX[card.bonus] }} /></>
  ) : (
    ABILITY_GLYPH[card.ability]
  );
const ABILITY_DESC = {
  again: "Take another turn after this one.",
  take_same: "Take 1 token of this card's color from the board.",
  privilege: "Take 1 Privilege.",
  steal: "Take 1 gem or pearl from your opponent.",
};
const WIN_DESC = {
  points: "20 prestige points",
  crowns: "10 crowns",
  color: "10 points in one color",
};
// Board geometry in CELL units — mirrors the CSS (gap 0.12, padding 0.2 of a cell), so
// the refill path lands on cell centres at any board size.
const CELL_GAP = 0.12, CELL_PAD = 0.2;
const BOARD_SPAN = 5 + 4 * CELL_GAP + 2 * CELL_PAD;     // 5.88
const cellCentre = (i) => [
  CELL_PAD + (i % 5) * (1 + CELL_GAP) + 0.5,
  CELL_PAD + Math.floor(i / 5) * (1 + CELL_GAP) + 0.5,
];

// Bot tiers (wire ids match main.AI_DIFFICULTIES). Easy = the trivial random-legal
// bot; Normal/Hard = determinized MCTS at different budgets.
const BOT_TIERS = [
  { id: "easy", name: "Easy", desc: "Plays legally, barely plans" },
  { id: "normal", name: "Normal", desc: "Thinks a little, makes mistakes" },
  { id: "hard", name: "Hard", desc: "Searches properly — a real fight" },
  { id: "expert", name: "Expert", desc: "Hard, retrained to punish impatience" },
];
const TIER_NAME = { easy: "Easy", normal: "Normal", hard: "Hard" };

function uid() { return Math.random().toString(36).slice(2, 10); }
function roomCode() { return Array.from({ length: 6 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join(""); }
function timeAgo(ts) {
  if (!ts) return "";
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ─── Rules mirrors (client-side previews; server stays authoritative) ───────
// Contiguous straight line of 1-3 cells on the 5x5 board (engine._valid_line).
function lineOk(cells, board) {
  if (!cells.length || cells.length > 3) return false;
  if (new Set(cells).size !== cells.length) return false;
  for (const i of cells) {
    const t = board[i];
    if (!t || t === "gold") return false;
  }
  if (cells.length === 1) return true;
  const pts = cells.map((i) => [Math.floor(i / 5), i % 5]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const d = [pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]];
  if (Math.max(Math.abs(d[0]), Math.abs(d[1])) !== 1) return false;
  if (cells.length === 3) {
    const d2 = [pts[2][0] - pts[1][0], pts[2][1] - pts[1][1]];
    if (d2[0] !== d[0] || d2[1] !== d[1]) return false;
  }
  return true;
}

function bonusesOf(player, cardsById) {
  const b = { white: 0, blue: 0, green: 0, red: 0, black: 0 };
  for (const pc of player?.purchased || []) {
    const card = cardsById[pc.id];
    if (!card) continue;
    const col = card.bonus === "wild" ? pc.as_color : card.bonus;
    if (col in b) b[col] += card.bonus_count;
  }
  return b;
}
function colorPointsOf(player, cardsById) {
  const cp = { white: 0, blue: 0, green: 0, red: 0, black: 0 };
  for (const pc of player?.purchased || []) {
    const card = cardsById[pc.id];
    if (!card) continue;
    const col = card.bonus === "wild" ? pc.as_color : card.bonus;
    if (col in cp) cp[col] += card.points;
  }
  return cp;
}
function crownsOf(player, cardsById) {
  return (player?.purchased || []).reduce((a, pc) => a + (cardsById[pc.id]?.crowns || 0), 0);
}
function pointsOf(player, cardsById, royals) {
  let pts = (player?.purchased || []).reduce((a, pc) => a + (cardsById[pc.id]?.points || 0), 0);
  pts += (player?.royals || []).reduce((a, rid) => a + (royals[rid]?.points || 0), 0);
  return pts;
}
function effectiveCost(cost, bonuses) {
  const out = {};
  for (const [col, n] of Object.entries(cost || {})) {
    const need = col in bonuses ? Math.max(0, n - bonuses[col]) : n;
    if (need > 0) out[col] = need;
  }
  return out;
}
function goldNeeded(cost, tokens, bonuses) {
  let gold = 0;
  for (const [col, need] of Object.entries(effectiveCost(cost, bonuses))) {
    gold += Math.max(0, need - (tokens?.[col] || 0));
  }
  return gold;
}
function canAffordCard(card, player, cardsById) {
  if (!card || !player) return false;
  const b = bonusesOf(player, cardsById);
  return goldNeeded(card.cost, player.tokens, b) <= (player.tokens?.gold || 0);
}

// The three victory conditions with progress meters (any one wins): 20 total prestige,
// 10 prestige in a single colour (the player's best colour), 10 crowns. Replaces the bare
// "★ pts ♛ crowns" so the player board reads as a race toward each finish line.
function WinMeters({ pts, crowns, cpts }) {
  const best = COLORS.reduce((a, c) => ((cpts[c] || 0) > (cpts[a] || 0) ? c : a), COLORS[0]);
  const meters = [
    { key: "pts", n: pts, t: 20, label: `${pts} / 20 total prestige points`,
      ico: <span className="duel-wm-ico" style={{ color: "#e8c96a" }}>★</span> },
    { key: "color", n: cpts[best] || 0, t: 10, label: `${cpts[best] || 0} / 10 prestige in one colour (best: ${best})`,
      ico: <span className="duel-wm-ico duel-wm-dot"
        style={{ background: GEM_HEX[best], borderColor: best === "black" ? "rgba(255,255,255,.45)" : "rgba(255,255,255,.28)" }} /> },
    { key: "crowns", n: crowns, t: 10, label: `${crowns} / 10 crowns`,
      ico: <span className="duel-wm-ico" style={{ color: "#f5c842" }}>♛</span> },
  ];
  return (
    <div className="duel-winmeters">
      {meters.map((m) => {
        const done = m.n >= m.t;
        const pct = Math.max(0, Math.min(100, (m.n / m.t) * 100));
        return (
          <div key={m.key} className={`duel-wm${done ? " done" : ""}`} title={m.label}>
            {m.ico}
            <span className="duel-wm-bar"><span className="duel-wm-fill" style={{ width: pct + "%" }} /></span>
            <span className="duel-wm-txt">{m.n}<span className="duel-wm-t">/{m.t}</span></span>
          </div>
        );
      })}
    </div>
  );
}

// The bag of tokens waiting to be drawn: a cinched drawstring pouch with the remaining
// count in its belly. `.duel-bag` is also the ORIGIN anchor for the refill animation
// (tokens fly from here to the board), so it must stay a stable, measurable element.
// The token bag: a white drawstring pouch with a blue drawstring and the remaining count on its
// body. Shape adapted from game-icons.net "swap-bag" by Lorc (CC BY 3.0); two-toned by clipping a
// blue fill to the gathered top. `.duel-bag` is also the ORIGIN anchor for the refill animation.
const BAG_PATH = "M363.783 23.545c-9.782.057-16.583 3.047-20.744 10.22-17.51 30.18-38.432 61.645-48.552 97.245 2.836.83 5.635 1.787 8.373 2.853 7.353 2.863 14.38 6.482 20.542 10.858 27.534-25.542 58.165-45.21 87.45-65.462 11.356-7.854 12.273-13.584 10.183-20.83-2.09-7.246-9.868-16.365-20.525-23.176-10.658-6.81-23.87-11.33-34.73-11.68-.68-.022-1.345-.03-1.997-.027zm-68.998.746c-10.02-.182-17.792 6.393-23.924 20.24-8.94 20.194-10.212 53.436-1.446 83.185.156-.008.31-.023.467-.03 1.99-.087 3.99-.072 6 .03 9.436-34.822 27.966-64.72 44.013-91.528-10.31-8.496-18.874-11.782-25.108-11.896zM197.5 82.5L187 97.97c14.82 10.04 29.056 19.725 39.813 31.374 3.916 4.24 7.37 8.722 10.31 13.607 3.77-4.73 8.51-8.378 13.69-10.792.407-.188.82-.355 1.228-.53-3.423-5.44-7.304-10.418-11.51-14.972C227.765 102.83 212.29 92.52 197.5 82.5zm223.77 12.27c-29.255 20.228-58.575 39.152-84.348 62.78.438.576.848 1.168 1.258 1.76 20.68-6.75 49.486-15.333 73.916-19.41 11.484-1.916 15.66-6.552 17.574-13.228 1.914-6.676.447-16.71-5.316-26.983-.924-1.647-1.96-3.29-3.083-4.92zm-223.938 47.87c-14.95.2-29.732 4.3-43.957 12.766l9.563 16.03c21.657-12.89 42.626-14.133 65.232-4.563.52-5.592 1.765-10.66 3.728-15.21.35-.806.73-1.586 1.123-2.354-11.87-4.52-23.83-6.827-35.688-6.67zm75.8 3.934c-5.578-.083-10.597.742-14.427 2.526-4.377 2.038-7.466 4.914-9.648 9.97-.884 2.047-1.572 4.54-1.985 7.494.456-.007.91-.03 1.365-.033 16.053-.084 32.587 2.77 49.313 9.19 7.714 2.96 15.062 7.453 22.047 13.184 3.217-2.445 4.99-4.72 5.773-6.535 1.21-2.798 1.095-5.184-.634-8.82-3.46-7.275-15.207-16.955-28.856-22.27-6.824-2.658-13.98-4.224-20.523-4.614-.818-.05-1.627-.08-2.424-.092zm-24.757 38.457c-22.982.075-44.722 7.386-65 19.782-32.445 19.835-60.565 53.124-80.344 90.032-19.777 36.908-31.133 77.41-31.186 110.53-.053 33.06 10.26 57.27 32.812 67.782.043.02.082.043.125.063h.032c24.872 11.51 65.616 19.337 108.407 20.092 42.79.756 87.79-5.457 121.874-20.187 21.96-9.49 34.545-28.452 40.5-54.156 5.954-25.705 4.518-57.657-2.375-89.314-6.894-31.657-19.2-63.06-34.095-87.875-14.894-24.814-32.614-42.664-48.063-48.593-14.664-5.627-28.898-8.2-42.687-8.156z";
function DuelBag({ count }) {
  return (
    <span className="duel-bag" title={`${count} token${count === 1 ? "" : "s"} waiting in the bag`}>
      <svg className="duel-bag-svg" viewBox="64 16 384 484" aria-hidden="true">
        <clipPath id="dbTop"><rect x="0" y="0" width="512" height="200" /></clipPath>
        <path d={BAG_PATH} fill="#eef1f6" stroke="#4a5a78" strokeWidth="7" strokeLinejoin="round" />
        <path d={BAG_PATH} fill="#4a86e0" clipPath="url(#dbTop)" />
        <path d={BAG_PATH} fill="none" stroke="#22417a" strokeWidth="7" strokeLinejoin="round" clipPath="url(#dbTop)" />
      </svg>
      <span className="duel-bag-num">{count}</span>
    </span>
  );
}

// ─── Small components ───────────────────────────────────────────────────────
// GemToken / CardView / LogEntry come from shared/splendor.jsx — Spender's ACTUAL
// gems, jewel cards and log. Only what Splendor Duel adds on top lives here.

// A Duel card = Spender's CardView with the extras Duel needs passed in (crowns and
// pearl costs live on the card data; the ability glyph/tooltip are supplied here so
// the shared component stays free of game rules).
function DuelCard({ card, asColor, selected, affordable, needsGold, dim, onClick, small }) {
  if (!card) return <div className="card card-empty" />;
  return (
    <CardView card={card} asColor={asColor} selected={selected} affordable={affordable}
      needsGold={needsGold} disabled={dim} onClick={onClick} small={small}
      abilityGlyph={abilityGlyph(card)} abilityTitle={ABILITY_DESC[card.ability]} />
  );
}

// An opponent's face-down reserve — Spender's card back, via the shared CardView.
function CardBack({ level }) {
  return <CardView card={{ hidden: true, level }} small />;
}

function RoyalCard({ royal, dim, onClick, selected }) {
  return (
    <div className={`duel-royal${dim ? " dim" : ""}${selected ? " selected" : ""}`} onClick={onClick}
      title={royal.ability ? ABILITY_DESC[royal.ability] : "No ability"}>
      <span className="duel-royal-pts">{"★"}{royal.points}</span>
      {royal.ability && <span className="duel-royal-abil">{ABILITY_GLYPH[royal.ability]}</span>}
    </div>
  );
}

// Privilege fleur-de-lis — a solid heraldic fleur (Noto glyph outlines), recoloured gold, drawn
// as a centred inline SVG instead of the ⚜ TEXT glyph. A glyph's horizontal side-bearings vary
// by platform font, so flexbox centres its ADVANCE box while the ink drifts (right, on mobile);
// an SVG centres identically on every device. The paths carry NO fill, so they inherit
// `.duel-scroll svg{fill:currentColor}` — a full coin is gold, an empty one transparent (the
// :not(.full) rule) — exactly the old colour logic.
const FLEUR = (
  <svg viewBox="0 0 128 128" aria-hidden="true">
    <path d="M47.31,31.05c-1.5,3.85-3.17,14.51,1.72,24.42c3.99,8.11,7.36,9.1,8.81,13.94 c0.76,2.53,0.27,13.77-0.34,15.83c-0.61,2.06-3.73,8.2-3.87,17.75c-0.13,8.56,4.69,15.56,6.29,17.46c1.94,2.3,2.66,2.9,4.11,2.9 c0.85,0,4.36-6.66,4.24-7.14c-0.12-0.48-2.54-50.71-2.54-50.71l5.45-37.15L47.31,31.05z"/>
    <path d="M65.48,4.88c-3.14-0.09-16.26,16.63-18.17,26.17c-1.91,9.53,1.76,20.21,6.36,26.51 S64.1,68.17,64.22,68.89c0.12,0.73-0.18,54.47-0.18,54.47s0.72,0.09,1.33-0.34c0.51-0.36,2.17-2.09,4.35-5.73 c2.36-3.94,4.59-9.27,4.6-15.2c0-9.94-4.23-15.65-4.47-18.68c-0.24-3.03,0.15-12.57,0.51-14.14c0.96-4.18,8.08-8.13,10.99-15.51 c2.16-5.49,4.72-15.13-1.57-29.05C73.47,10.81,68.09,4.96,65.48,4.88z"/>
    <path d="M63.79,11.31c-1.71,0.31-14.73,14.71-13.23,27.99C51.82,50.4,61,62.03,63.61,61.29 c1.4-0.4,1-12.63,1.12-24.6C64.85,24.08,64.98,11.09,63.79,11.31z"/>
    <path d="M79.97,31.55c-1.27-0.29-0.73,8.01-4.2,16.02c-4.03,9.28-9.89,11.82-7.7,13.92 c2.19,2.1,9.19-1.84,11.99-11.12C82.23,43.16,82.25,32.07,79.97,31.55z"/>
    <path d="M95.33,86.64c0,0,3.28,0,4.69,3.04c1.66,3.59-0.53,13.92-12.08,13.39 c-11.38-0.52-14.63-12.67-14.63-17.32c0-3,5.79-9.55,5.79-9.55l13.66-13.74l8.14-3.33l21.53,7.35c0,0-12.73,19.9-13.37,19.61 c-0.42-0.2-2.26-0.78-2.39-2.8c-0.17-2.62,1.93-4.55,1.05-9.45c-0.53-2.96-3.94-7.35-11.29-5.69s-12.52,7.56-13.39,14.71 c-1.31,10.77,4.51,11.03,4.51,11.03s5.82,1.31,5.91,1.05C93.54,94.66,95.33,86.64,95.33,86.64z"/>
    <path d="M17.2,86.39c0,0,3.33-0.22,3.33-3.37c0-2.72-3.33-11.47,2.45-14.09c5.78-2.63,13.83-0.35,18.82,6.3 c4.39,5.86,3.94,16.98-0.79,18.12s-7.79-1.31-7.79-1.31l-1.66-5.66c0,0-4.98,1.19-4.38,6.8c0.53,4.9,4.41,10.27,12.96,9.89 c9.89-0.44,14.92-11.11,14.44-19.78C54.17,75.67,40.82,64.32,40.4,64.2c-1.58-0.44-19.35-4.73-20.13-3.85S8.98,75.14,8.98,75.14 L17.2,86.39z"/>
    <path d="M108.33,85.73c-0.27-0.2,5.57-6.77,4.9-13.92c-0.7-7.53-10.24-11.64-21.8-6.22 c-11.27,5.29-14.2,23.84-6.74,27.22c7.53,3.41,8.93-6.04,10.59-6.22c1.54-0.16,5.75,6.3-0.35,11.03 c-8.48,6.58-21.26-1.91-21.8-13.39c-0.44-9.28,2.19-22.11,17.49-30.04c9.63-4.99,18.72-3.68,24.79-0.51 c4.73,2.47,7.52,6.7,8.4,11.03c1.36,6.67-1.03,12.18-3.15,15.58C116.04,87.75,109.74,86.76,108.33,85.73z"/>
    <path d="M17.64,86.26c-0.56,0.51-5.72,0.44-9.89-4.55c-5.34-6.39-6.41-19.79,2.36-26.35 c10.12-7.56,26.15-5.09,37.29,7.62c8.05,9.19,8.82,19.47,5.25,27.92c-2.24,5.3-6.55,8.97-12.26,9.1c-7.23,0.17-10.42-4.2-10.76-8.08 c-0.25-2.79,0.72-5.34,2.01-5.57c1.99-0.36,1.14,7.97,9.37,7c7.17-0.84,12.08-13.92-0.7-25.04c-12.94-11.25-24.6-4.64-25.82,3.76 C13.14,81.35,18.69,85.3,17.64,86.26z"/>
    <path d="M76.91,75.58c0.73,0.46,2.87-4.08,6.04-7.62c3.76-4.2,7.39-5.97,11.47-8.05 c8.58-4.38,13.92-1.14,14.01-4.64c0.07-2.89-9.72-2.98-17.07,0.96C79.1,62.8,75.94,74.97,76.91,75.58z"/>
    <path d="M43.47,78.12c-1.84-0.09-2.98,1.66-2.98,3.59c0,2.1,1.66,3.68,4.29,3.76c2.63,0.09,35.98,0,38.17,0 c2.19,0,3.06-2.01,3.15-3.76c0.09-1.75-1.31-3.24-3.06-3.33S43.47,78.12,43.47,78.12z"/>
    <path d="M43.82,81.27c1.75,0,37.47,0.18,38.87,0.09c1.4-0.09,1.93-1.23,1.84-2.01 c-0.09-0.79-1.31-1.05-2.63-1.05c-1.31,0-37.47-0.35-38.43-0.18c-0.96,0.18-1.49,0.88-1.4,1.58C42.15,80.39,42.59,81.27,43.82,81.27 z"/>
    <path d="M8.64,71.31c1.32,0.09,3.02-7.79,8.14-11.05c4.37-2.78,8.53-3.11,13.83-2.18s8.04,2.67,8.47,1.85 c0.66-1.26-10.78-9.92-22.76-5.69S6.79,71.18,8.64,71.31z"/>
  </svg>
);

function Scroll({ n, armed, onClick, title }) {
  return (
    <div className={`duel-scrolls${armed ? " armed" : ""}${onClick ? " clickable" : ""}`} onClick={onClick} title={title}>
      {Array.from({ length: 3 }, (_, i) => (
        <span key={i} className={`duel-scroll${i < n ? " full" : ""}`}>{FLEUR}</span>
      ))}
    </div>
  );
}

function useSocket(onMessage) {
  const wsRef = useRef(null);
  const [connected, setConnected] = useState(false);
  const onMsg = useRef(onMessage);
  onMsg.current = onMessage;
  const connect = useCallback((url, firstMsg) => {
    try { wsRef.current?.close(); } catch {}
    const ws = new WebSocket(url);
    wsRef.current = ws;
    ws.onopen = () => { setConnected(true); if (firstMsg) ws.send(JSON.stringify(firstMsg)); };
    ws.onclose = () => setConnected(false);
    ws.onmessage = (e) => { try { onMsg.current(JSON.parse(e.data)); } catch {} };
  }, []);
  const send = useCallback((obj) => { try { wsRef.current?.send(JSON.stringify(obj)); } catch {} }, []);
  const disconnect = useCallback(() => { try { wsRef.current?.close(); } catch {} wsRef.current = null; setConnected(false); }, []);
  const socketReady = useCallback(() => wsRef.current?.readyState, []);
  return { connected, connect, send, disconnect, socketReady };
}

// ─── Styles ─────────────────────────────────────────────────────────────────
// NOTE: no backticks anywhere inside this string (documented smoke-test footgun).
const css = `
/* Full-bleed: no max-width cap — the game fills the browser, with only a small gutter.
   (A 1500px cap left big dead margins on a wide monitor.) */
/* No font-family here: baseCss's body already sets the site stack (and this override
   was silently dropping Georgia from the fallback, so the log rendered differently
   from Spender's). */
.duel{margin:0 auto;padding:0 14px 24px}
.duel h1,.duel h2,.duel h3{font-family:'Cinzel','Cinzel Fallback',serif}
.duel-topbar{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--line,#3a332a);margin-bottom:14px}
.duel-topbar .spacer{flex:1}
.duel-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.5rem;letter-spacing:.06em;margin:0}
.duel-muted{opacity:.65;font-size:.95rem}
.duel-toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#2b2117;color:#f4e9d4;border:1px solid #6b5836;padding:10px 18px;border-radius:8px;z-index:200;box-shadow:0 6px 18px rgba(0,0,0,.5)}
.duel-reconnbar{position:fixed;top:0;left:0;right:0;background:#6b3320;color:#ffe;text-align:center;padding:5px;z-index:210;font-size:.9rem}

/* lobby — cards/sections/badges are the shared lobby kit (.lby-*, shared/lobby.jsx). */
/* Full-bleed the shared lobby header past .duel's 14px side padding (matches Spender/CoC). */
.duel > .lby-header{margin:0 -14px 18px}
.duel-lobby-cols{display:grid;grid-template-columns:2fr 2fr 1fr;gap:18px;align-items:start}
/* Mobile Open/Active/History tab bar (mirrors Spender's .lobby-tabs). Hidden on wide
   screens; shown (and made to hide the other two sections) in the max-width:720 block. */
.duel-lobby-tabs{display:none;gap:6px;margin-bottom:16px;background:var(--surface2,#241d16);border:1px solid var(--line,#3a332a);border-radius:12px;padding:4px}
.duel-lobby-tab{flex:1;display:inline-flex;align-items:center;justify-content:center;gap:7px;background:transparent;border:none;color:var(--text-dim,#a89a82);cursor:pointer;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.82rem;letter-spacing:.04em;padding:9px 4px;border-radius:9px;transition:background .15s,color .15s}
.duel-lobby-tab.sel{background:var(--lby-accent,#bf6fd0);color:#160f18;font-weight:700}
.duel-lobby-tab-count{display:inline-flex;align-items:center;justify-content:center;min-width:18px;height:18px;padding:0 5px;border-radius:9px;background:rgba(0,0,0,.22);color:inherit;font-family:'Crimson Pro','Crimson Fallback',Georgia,serif;font-size:.72rem;font-weight:600;letter-spacing:0}
.duel-lobby-tab:not(.sel) .duel-lobby-tab-count{background:var(--surface,#1b1712);color:var(--text-dim,#a89a82)}
.duel-turnbadge{font-size:.78rem;padding:2px 8px;border-radius:999px;background:#3f5f33;color:#dfeecf;white-space:nowrap}
.duel-theirbadge{font-size:.78rem;padding:2px 8px;border-radius:999px;background:#4a4136;color:#d8ccb8;white-space:nowrap}

/* game columns (named areas): the LOG sits UNDER the cards on the left, while the
   board + player rail stay full-height on the right. The board stays a fixed 5x5 grid
   that centers any slack; the log stretches to fill the left column down to the board's
   foot (scrolling internally past its cap) so no gap opens under the pyramid early game.
   Track widths: the side rail was cut 25% (min + fr, 320->240 / 1.1->0.825fr) and that
   exact width handed to the CARDS column (400->480 / 1.2->1.475fr) — the board's 1fr is
   untouched — so the pyramid's width-driven --card-w clamp renders BIGGER cards. */
.duel-cols{
  display:grid;
  grid-template-columns:minmax(480px,1.475fr) minmax(340px,1fr) minmax(240px,0.825fr);
  grid-template-areas:"cards board side" "log board side";
  grid-template-rows:auto 1fr;
  gap:18px;align-items:start}
.duel-col-cards{grid-area:cards}
.duel-col-board{grid-area:board}
.duel-col-side{grid-area:side}
.duel-col-log{grid-area:log;align-self:stretch;min-height:0;display:flex}
.duel-col-log .log-panel{flex:1;display:flex;flex-direction:column;min-height:0}
/* .duel-prefixed so this fill beats the later, equal-specificity .duel-panel .move-log
   cap (0,3,0 > 0,2,0) — otherwise the fixed max-height wins and the log won't fill. */
.duel .duel-col-log .move-log{flex:1;min-height:0;max-height:none}
.duel-panel{background:linear-gradient(180deg,rgba(255,255,255,.03),transparent 46%),var(--surface,#1b1712);border:1px solid var(--line,#3a332a);border-radius:12px;padding:12px;box-shadow:inset 0 1px 0 rgba(255,255,255,.05),0 2px 10px -4px rgba(0,0,0,.5)}

/* pyramid */
/* Left-aligned, NOT centered: the rows hold different card counts (5/4/3), so centering
   staggers the deck stubs instead of keeping them in one tidy column. The cards scale to
   fill the box anyway, so there's little slack left to distribute. */
/* (pyramid + deck styling now come from Spender via .level-row / .deck-pile) */

/* cards + pyramid: SPENDER's .level-row / .deck-pile / .card (shared/splendor.jsx).
   Spender's card is width:var(--card-w)/min-height:var(--card-h) and its level-row
   already fits "deck + N cards" via flex:1 1 0 + max-width:var(--card-w) — so Duel
   only has to SET those two vars per column width and the whole row scales itself.
   (This replaces a hand-rolled container-query card that had drifted into square
   swatches and its own palette.) */
.duel-col-cards{container-type:inline-size}
.duel-col-cards .level-row{
  /* the widest row is deck + 5 cards = 6 cells, 5 gaps of 8 (=40) + the panel's 24px
     padding = 64px of true overhead. We subtract 68 (not the old 80) so the cards are ~2px
     bigger and the trailing buffer on the right of the level-I row is only ~4px instead of
     ~16 — still enough slack to absorb sub-pixel rounding so all 6 cells stay on one row.
     The MIN must stay LOW (40, not 52): on a narrow phone (<~385px) a 52px floor forces
     the 6-cell level-I row WIDER than the column, so it overflows and the flex shrinks the
     items UNEVENLY — the deck (less content) shrinks more than the cards, and the roomier
     3/4-card rows don't shrink at all, so decks came out different sizes per row. A 40 floor
     lets --card-w track the true 6-cell fit at any width, so every cell (deck AND card) is
     the SAME size in every row. */
  --card-w:clamp(40px, calc((100cqw - 68px) / 6), 190px);
  --card-h:calc(var(--card-w) * 1.364);   /* Spender's 88x120 aspect */
  margin-bottom:8px;
}
/* --card-w is container-query-derived, so it settles a frame AFTER the game data lays out.
   The shared .card / .deck-pile use transition:all, which ANIMATES that width change into a
   jarring shrink on load. Transition only the hover/state props here (never width/height/
   padding) so the cards land at their final size instantly. Spender's .card is untouched. */
.duel-col-cards .level-row .card,.duel-col-cards .level-row .deck-pile{transition:border-color .15s,transform .15s,box-shadow .15s,opacity .15s}
/* Scale the card internals off --card-h using the SAME ratios as Spender's desktop
   rules (its .level-row .card-* block) — so a Duel card is a Spender card at another
   size, not a different card. Those ratios live inside Spender's own min-width:901px
   query, which we deliberately did not move; these mirror them for Duel's sizes. */
.duel-col-cards .level-row .card{padding:calc(var(--card-h) * 0.049) calc(var(--card-h) * 0.043) calc(var(--card-h) * 0.043);justify-content:space-between}
.duel-col-cards .level-row .card-header{margin-bottom:calc(var(--card-h) * 0.043)}
/* min-width:0 (the shared base pins points to 16px): on a narrow Duel card the fixed 16px
   left the points + crowns + bonus too wide for the header, pushing the gem-type disc off
   the card's right edge. Zeroing it (points are 1-2 chars anyway) keeps the header inside. */
.duel-col-cards .level-row .card-points{font-size:calc(var(--card-h) * 0.147);min-width:0}
.duel-col-cards .level-row .card-bonus{width:calc(var(--card-h) * 0.14);height:calc(var(--card-h) * 0.14)}
/* a double bonus overlaps by 40% of the (scaled) disc: 0.14 * 0.4 */
.duel-col-cards .level-row .card-bonus-pair .card-bonus+.card-bonus{margin-left:calc(var(--card-h) * -0.056)}
.duel-col-cards .level-row .card-crowns{font-size:calc(var(--card-h) * 0.12);margin-left:auto;margin-right:calc(var(--card-h) * 0.025)}
.duel-col-cards .level-row .card-header .card-crowns+.card-bonus{margin-left:calc(var(--card-h) * 0.03)}
.duel-col-cards .level-row .card-ability{font-size:calc(var(--card-h) * 0.082);top:calc(var(--card-h) * 0.24);right:calc(var(--card-h) * 0.05)}
.duel-col-cards .level-row .cost-gem{width:calc(var(--card-h) * 0.096);height:calc(var(--card-h) * 0.096)}
.duel-col-cards .level-row .cost-num{font-size:calc(var(--card-h) * 0.095)}
/* pip -> number gap: tighter so the count sits right next to its gem (was the base 4px). */
.duel-col-cards .level-row .cost-row{gap:calc(var(--card-h) * 0.02)}
.duel-col-cards .level-row .card-cost{gap:calc(var(--card-h) * 0.027)}
.duel-col-cards .level-row .card-cost .cost-col{gap:calc(var(--card-h) * 0.027)}
.duel-col-cards .level-row .deck-pile{font-size:calc(var(--card-h) * 0.068);gap:calc(var(--card-h) * 0.032)}
.duel-col-cards .level-row .deck-remaining{font-size:calc(var(--card-h) * 0.147)}
.card-empty{visibility:hidden}

/* board */
/* The board is the other place spare width should go (it's the focal point), so its
   cells + tokens scale with the column: cqw minus the board padding (24), the panel
   padding (24) and the 4 gaps (28), split 5 ways. Tokens are CSS-sized here — see
   the note on Token — and sit at ~79% of their cell, matching the original 46/58. */
.duel-col-board{container-type:inline-size}
/* The gap and padding scale WITH the cell (0.12 / 0.2 of it), so the board's geometry is
   proportional at every size: total span = 5 + 4*0.12 + 2*0.2 = 5.88 cells. That is what
   lets the refill path below be a fixed viewBox of cell units and still land exactly on
   every cell centre — with fixed 7px/12px, the ratios drift as the cell scales. */
.duel-col-board .duel-board{--dcell:clamp(50px, calc((100cqw - 24px) / 5.88), 104px)}
.duel-board-wrap{display:flex;flex-direction:column;align-items:center;gap:10px}
.duel-board{--dcell:58px;--dgap:calc(var(--dcell) * 0.12);position:relative;display:grid;grid-template-columns:repeat(5,var(--dcell));grid-auto-rows:var(--dcell);gap:var(--dgap);padding:calc(var(--dcell) * 0.2);background:linear-gradient(180deg,#1d160e,#2a2216);border:1px solid #5f4f3a;border-radius:14px;box-shadow:inset 0 3px 14px rgba(0,0,0,.55),inset 0 1px 0 rgba(255,255,255,.02),0 2px 6px -2px rgba(0,0,0,.4)}
.duel-cell{display:flex;align-items:center;justify-content:center;border-radius:50%;border:2px dashed #3c3227;position:relative;z-index:1}

/* The REFILL PATH: replenish fills empty spaces from the centre outward along a fixed
   spiral (cards.SPIRAL_ORDER, served in /duel/catalog), so tracing it tells you which
   spaces come back first — worth knowing before you take. Drawn under the tokens,
   inert, in cell units (see the proportional geometry above). */
.duel-spiral{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:0}
.duel-spiral .path{fill:none;stroke:var(--gold);stroke-opacity:.30;stroke-width:.055;stroke-linecap:round;stroke-linejoin:round}
.duel-spiral .start{fill:var(--gold);fill-opacity:.55}
.duel-spiral .head{fill:var(--gold);fill-opacity:.45}
/* Board tokens are SPENDER's .gem-token (shared) — Duel only adds the board-specific
   states + the scaling, since the shared token is a fixed 42px by default. */
.duel-cell .gem-token{width:calc(var(--dcell) * 0.79);height:calc(var(--dcell) * 0.79);font-size:calc(var(--dcell) * 0.30);cursor:pointer;transition:transform .1s, box-shadow .1s}
.duel-cell .gem-token:hover{transform:scale(1.08)}
.duel-cell .gem-token.sel{box-shadow:0 0 0 3px var(--gold-light)}
.duel-cell .gem-token.goldarm{box-shadow:0 0 0 3px var(--gold-light);animation:duelPulse 1.1s infinite}
.duel-cell .gem-token.matchable{box-shadow:0 0 0 3px var(--green-gem);animation:duelPulse 1.1s infinite}
.duel-cell .gem-token.inert{cursor:default}
@keyframes duelPulse{0%,100%{filter:brightness(1)}50%{filter:brightness(1.35)}}
.duel-board-meta{display:flex;align-items:center;gap:16px;flex-wrap:wrap;justify-content:center}
/* Token bag: white drawstring pouch (vector) with the remaining count on its body. */
.duel-bag{position:relative;display:inline-flex;align-items:center;justify-content:center;width:42px;height:52px;flex-shrink:0}
.duel-bag-svg{width:100%;height:100%;display:block}
.duel-bag-num{position:absolute;left:0;right:0;top:69%;transform:translateY(-50%);text-align:center;font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;font-size:.86rem;line-height:1;color:#2a3f6b;pointer-events:none;text-shadow:0 0 2px rgba(255,255,255,.9),0 1px 1px rgba(255,255,255,.7)}
.duel-actionrow{display:flex;gap:10px;align-items:center;min-height:40px;flex-wrap:wrap;justify-content:center}
/* Keep every action-row button the SAME height. Two mismatches to cancel: (1) btn-gold has
   no border while btn-outline adds 1px — with border-box + auto height a border still adds
   2px, so the gold Take/Buy came out 2px short; give gold a transparent border to match.
   (2) the ✕ glyph falls back to a font with taller line metrics (+2px); pin line-height so
   the glyph can't inflate its button past the text ones. */
.duel-actionrow .btn-gold{border:1px solid transparent}
.duel-actionrow .btn{line-height:1.2}
/* "Claim a Royal at 3 & 6 crowns" — the royal cards themselves no longer draw a crown
   (it read as if a Royal cost/gave crowns); this line is the only crown-threshold cue. */
.duel-royals-hint{font-size:.82rem;color:var(--gold,#e6c260);opacity:.9;text-align:center;letter-spacing:.02em}
.duel-royals-hint b{color:#f5c842;font-weight:700}
.duel-royals-row{display:flex;gap:10px;justify-content:center}
.duel-royal{position:relative;width:66px;height:46px;background:linear-gradient(160deg,#3a2c45,#2c2135);border:1px solid #6b5a80;border-radius:8px;display:flex;align-items:center;justify-content:center;gap:6px}
.duel-royal.dim{opacity:.35}
.duel-royal.selected{box-shadow:0 0 0 2px #f5c842;cursor:pointer}
.duel-royal-pts{font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;color:#f4e9d4}
.duel-royal-abil{font-size:.8rem;color:#d9c8f0}
/* Privilege tokens = dark coins with a big gold fleur (flat, high-contrast so the fleur
   reads at ~26px). HELD = a filled coin; EMPTY = a hollow dashed ring (no fleur) so you
   can see at a glance how many you own. When it's yours to spend (.clickable) the coins
   get a soft gold ring — a tap cue that works on TOUCH, where there's no hover. Tapping
   ARMS privilege mode (.armed) → a bright, persistent gold ring + glow + pulse, so
   "selected — now pick a gem" is unmistakable. Hover-lift is DESKTOP-ONLY: a stray
   tap-:hover otherwise stuck a ring on one coin on mobile (the reported confusion). */
.duel-scrolls{display:inline-flex;gap:7px}
.duel-scroll{
  display:inline-flex;align-items:center;justify-content:center;
  width:34px;height:34px;border-radius:50%;color:#e6c260;
  background:#241d14;border:1px solid #5a4a2c;
  box-shadow:0 1px 2px rgba(0,0,0,.4);
  transition:transform .1s ease,box-shadow .1s ease,border-color .1s ease,filter .1s ease;
}
.duel-scroll svg{width:21px;height:21px;fill:currentColor;display:block}
.duel-scroll:not(.full){color:transparent;background:transparent;border:2px dashed #4a4030;box-shadow:none}
.duel-scrolls.clickable{cursor:pointer}
.duel-scrolls.clickable .duel-scroll.full{border-color:#7a6330;box-shadow:0 1px 2px rgba(0,0,0,.4),0 0 0 1px rgba(232,201,106,.28)}
/* hover-lift + press only the LEFTMOST coin (the one a click spends), matching the armed
   glow — hovering anywhere on the row still lifts just that coin. */
@media (hover:hover){
  .duel-scrolls.clickable:hover .duel-scroll.full:first-child{transform:translateY(-1.5px);border-color:#8a6f34;box-shadow:0 4px 7px rgba(0,0,0,.5),0 0 0 2px rgba(232,201,106,.4);filter:brightness(1.12)}
}
.duel-scrolls.clickable:active .duel-scroll.full:first-child{transform:translateY(1px);filter:brightness(1)}
/* Only the LEFTMOST privilege coin lights up when armed (it's the one that gets spent) —
   :first-child is always a .full coin when armed, since arming needs >=1 privilege. */
.duel-scrolls.armed .duel-scroll.full:first-child{border-color:#e6c260;box-shadow:0 0 0 2px rgba(232,201,106,.6),0 0 9px rgba(232,201,106,.45);animation:duelPulse 1.1s infinite}
.duel-victory-chip{font-size:.8rem;opacity:.75;border:1px solid #3a332a;border-radius:999px;padding:3px 10px}

/* player panels */
/* Pills fill exactly ONE row of 7 — Duel has 7 token types (5 gems + pearl + gold), and
   the bonus row tops out at 7 too (5 colors + 2 royals). The rows use gap:4px, so 7 items
   leave 6 gaps = 24px; nowrap + min-width:0 + overflow:hidden lets a pill take exactly
   its share instead of wrapping or pushing the row wide — so all 7 stay on ONE row at any
   rail width, shrinking to fit rather than wrapping.

   SHAPE comes from Spender: it derives every pill dimension from --card-h (font x0.082,
   padding x0.018/x0.006, gap x0.014, dot x0.078, radius 999px), giving a 1.82 w:h
   capsule. Duel's rail has no card to anchor to, so we rebuild that anchor from the
   pill's OWN width and reuse Spender's formulas verbatim — a Duel pill is a Spender pill
   scaled, not a flattened one. (Measured: Spender's pill is 61.6 wide at --card-h 218.5,
   hence the 3.547 factor. Sizing the width alone gave a 2.48-ratio flat pill.) */
.duel-player{container-type:inline-size}
.duel-player .player-tokens,.duel-player .player-bonuses{
  flex-wrap:nowrap;min-width:0;
  /* 100cqw is the panel's CONTENT box (padding already excluded), so the row only loses
     its 6 gaps x 4px. Subtracting the padding again here under-sized the anchor and left
     the pill at a 2.0 ratio instead of Spender's 1.82. */
  --pill-anchor:calc(((100cqw - 24px) / 7) * 3.547);
}
.duel-player .token-pill,.duel-player .bonus-pill{
  flex:0 1 calc((100% - 24px) / 7);
  min-width:0;justify-content:center;overflow:hidden;white-space:nowrap;
  font-size:calc(var(--pill-anchor) * 0.082);
  padding:calc(var(--pill-anchor) * 0.018) calc(var(--pill-anchor) * 0.006);
  gap:calc(var(--pill-anchor) * 0.014);
  border-radius:999px;
  /* Pin the HEIGHT to Spender's (its pill is 33.8 tall at --card-h 218.5 => 0.1547), so
     both pills are the same capsule regardless of their text size — otherwise the
     bonus pill's smaller font shrinks its box and the two rows stop matching. */
  min-height:calc(var(--pill-anchor) * 0.1547);
  box-sizing:border-box;
}
.duel-player .player-tokens .token-pill>span{
  width:calc(var(--pill-anchor) * 0.078)!important;
  height:calc(var(--pill-anchor) * 0.078)!important;flex:0 0 auto;
}
/* Dropping the redundant color letter ("+3★3", not "+3 R★3" — the pill is already
   color-coded) freed enough room that the bonus pill can use Spender's own font ratio,
   identical to the token pill. */
.duel-player .bonus-pill{letter-spacing:-.02em}
/* Buffer between the privilege scrolls (⚜) and the token pills directly beneath them,
   plus a smaller one before the bought-card indicators. */
.duel-player .player-tokens{margin-top:13px}
.duel-player .player-bonuses{margin-top:9px}
/* The "N tokens" summary chip is Spender's shared inline-block .gem-total, but the player
   box is a flex COLUMN on desktop (the viewport-lock), whose default align-items:stretch
   was blowing it out to the FULL box width — that's the "way too long" pill. Pin it to its
   content width (align-self) and size it up a touch. Same align-self keeps the clickable
   privilege-scroll row content-width so its onClick has no full-width dead zone. */
.duel-player .gem-total{align-self:flex-start;font-size:.82rem;padding:3px 11px;border-radius:9px;margin-top:9px}
.duel-player .duel-scrolls{align-self:flex-start}
.duel-player{margin-bottom:14px}
.duel-player .hd{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.duel-player .hd .nm{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.02rem}
.duel-player.active{border-color:#e8c96a;box-shadow:inset 0 1px 0 rgba(255,255,255,.06),0 0 0 1px rgba(232,201,106,.3),0 3px 16px -4px rgba(201,168,76,.3),0 2px 10px -4px rgba(0,0,0,.5)}
.duel-stat{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.98rem;font-weight:700;margin-left:auto;display:flex;gap:10px;align-items:center}
/* The three victory-condition progress meters (top-right of a player board). Compact so
   name + turn badge + meters share the header row on both phone and desktop. */
.duel-winmeters{margin-left:auto;display:flex;flex-direction:column;gap:3px;align-items:stretch;min-width:104px;flex-shrink:0}
.duel-wm{display:flex;align-items:center;gap:5px}
.duel-wm-ico{font-size:.82rem;width:13px;text-align:center;flex-shrink:0;line-height:1}
.duel-wm-dot{width:11px;height:11px;border-radius:50%;border:1px solid rgba(255,255,255,.28);box-sizing:border-box}
.duel-wm-bar{flex:1;height:5px;border-radius:3px;background:rgba(255,255,255,.1);overflow:hidden;min-width:34px}
.duel-wm-fill{display:block;height:100%;border-radius:3px;background:linear-gradient(90deg,#b0862c,#e8c96a);transition:width .35s ease}
.duel-wm.done .duel-wm-fill{background:linear-gradient(90deg,#4e8f3a,#79d35c)}
.duel-wm-txt{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.74rem;font-weight:700;min-width:32px;text-align:right;white-space:nowrap;color:var(--text)}
.duel-wm.done .duel-wm-txt{color:#8fe07a}
.duel-wm-t{opacity:.5;font-weight:400}
.duel-reserved-row{display:flex;gap:10px;margin-top:6px;flex-wrap:wrap}
/* Reserved cards are sized so exactly THREE fit on ONE row of the player box: card width =
   (box content width − the two 10px row gaps, with a few px of slack) / 3, read off the
   .duel-player inline-size container (100cqw). Height keeps the 62:86 (=1.387) small-card
   aspect, and the internals scale off that derived height by the pyramid's ratios so they
   stay proportional as the box (and thus the card) grows/shrinks with the rail width.
   The .card.card-small prefix (0,4,0) is REQUIRED to out-specify the shared .card.card-small
   internals (0,3,0) — a bare .duel-reserved-row .card-* (0,2,0) silently loses to them. */
.duel-reserved-row{--card-w-small:calc((100cqw - 24px) / 3);--card-h-small:calc(var(--card-w-small) * 1.387)}
.duel-reserved-row .card.card-small{padding:calc(var(--card-h-small)*0.049) calc(var(--card-h-small)*0.043) calc(var(--card-h-small)*0.043)}
.duel-reserved-row .card.card-small .card-header{margin-bottom:calc(var(--card-h-small)*0.043)}
.duel-reserved-row .card.card-small .card-points{font-size:calc(var(--card-h-small)*0.147);min-width:0}
.duel-reserved-row .card.card-small .card-bonus{width:calc(var(--card-h-small)*0.14);height:calc(var(--card-h-small)*0.14)}
.duel-reserved-row .card.card-small .card-bonus-pair .card-bonus+.card-bonus{margin-left:calc(var(--card-h-small)*-0.056)}
.duel-reserved-row .card.card-small .card-crowns{font-size:calc(var(--card-h-small)*0.11)}
.duel-reserved-row .card.card-small .card-ability{font-size:calc(var(--card-h-small)*0.082);top:calc(var(--card-h-small)*0.24);right:calc(var(--card-h-small)*0.05)}
.duel-reserved-row .card.card-small .card-back-level{font-size:calc(var(--card-h-small)*0.17)}
.duel-reserved-row .card.card-small .cost-gem{width:calc(var(--card-h-small)*0.096);height:calc(var(--card-h-small)*0.096)}
.duel-reserved-row .card.card-small .cost-num{font-size:calc(var(--card-h-small)*0.095)}

/* log: SPENDER's .move-log / .log-entry (shared/splendor.jsx) — same rows, same
   review vocabulary (clickable / log-selected / log-win / log-start). The log now sits
   in its own column UNDER the cards (.duel-col-log), where it stretches to fill; this
   cap is the fallback (phones + any non-filling context). */
.duel-panel .move-log{max-height:min(46vh,420px)}
.log-entry.future{opacity:.35}

/* review / replay */
.duel-replaybar{display:flex;align-items:center;gap:10px;justify-content:center;flex-wrap:wrap;background:var(--surface,#1b1712);border:1px solid #6b5836;border-radius:10px;padding:8px 12px;margin:0 0 12px}
.duel-replay-label{font-size:.92rem;opacity:.85;min-width:260px;text-align:center}
.duel-review-badge{font-size:.78rem;padding:2px 9px;border-radius:999px;background:#3a2c45;color:#d9c8f0;border:1px solid #6b5a80}

/* modals */
.duel-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:150}
.duel-modal{background:#241d13;border:1px solid #6b5836;border-radius:14px;padding:20px 24px;max-width:520px;width:calc(100% - 40px);box-shadow:0 10px 40px rgba(0,0,0,.6)}
.duel-modal h3{margin-top:0}
.duel-modal-row{display:flex;gap:10px;flex-wrap:wrap;justify-content:center;margin:14px 0}
.duel-overlay-note{text-align:center;margin-top:8px;opacity:.75;font-size:.9rem}
/* Log-inspect card modal: snug width, and the card scaled up uniformly with zoom (the
   codebase's scale-with-reflow approach) so its shared internals stay proportional. */
.duel-cardmodal{max-width:280px}
.duel-cardmodal .card{zoom:1.7;cursor:default;margin:0 auto}

/* flyers */
.duel-fly-layer{position:fixed;inset:0;pointer-events:none;z-index:180}
.duel-flyer{position:absolute;animation:duelFly .55s cubic-bezier(.3,.7,.4,1) forwards}
@keyframes duelFly{from{transform:translate(0,0) scale(var(--s0,1));opacity:1}to{transform:translate(var(--dx),var(--dy)) scale(var(--s1,.6));opacity:.15}}
/* Refill flyers: fly bag->cell staying solid, landing at full size (the real token is hidden
   until then, so it reads as a draw from the bag). fill-mode both holds the start state through
   the per-token delay (queued in the bag) and the end state after it lands (until we remove it). */
.duel-flyer-in{position:absolute;animation-name:duelFlyIn;animation-timing-function:cubic-bezier(.3,.6,.4,1);animation-fill-mode:both}
@keyframes duelFlyIn{from{transform:translate(0,0) scale(.5);opacity:.35}60%{opacity:1}to{transform:translate(var(--dx),var(--dy)) scale(1);opacity:1}}
.gem-token.duel-refill-hidden{opacity:0}

/* waiting screen */
.duel-waiting{max-width:520px;margin:40px auto;text-align:center}
.duel-code{font-family:'Cinzel','Cinzel Fallback',serif;font-size:2.2rem;letter-spacing:.35em;margin:14px 0;color:#f5c842}

.duel-gameover-badge{font-size:1.05rem;margin:6px 0 2px;color:#f5c842}

@media(max-width:1120px){
  /* 2-col: cards+log stack on the left, board fills the right; the player rail drops
     to a full-width row beneath (areas replace the old grid-column:1/-1 span). */
  .duel-cols{grid-template-columns:1fr 1fr;grid-template-rows:auto;
    grid-template-areas:"cards board" "log board" "side side"}
  .duel-lobby-cols{grid-template-columns:1fr}
}
@media(max-width:720px){
  /* Phone single-column: cards, board, player boxes, then the log LAST (a big log
     shouldn't sit between the pyramid and the board on a small screen). */
  .duel-cols{grid-template-columns:1fr;grid-template-rows:auto;
    grid-template-areas:"cards" "board" "side" "log"}
  /* Restore the internal-scroll cap on phones (the log is last, so don't let it fill
     and stretch the page — cap it and scroll inside like before). */
  .duel .duel-col-log .move-log{flex:none;max-height:min(46vh,420px)}
  /* Trim the side buffer on phones so the board + cards get more width (matched header
     margin keeps the full-bleed header exactly at the screen edge — a wider -14px here
     would push it past an 8px padding and cause a horizontal scrollbar). */
  .duel{padding-left:8px;padding-right:8px}
  .duel > .lby-header{margin-left:-8px;margin-right:-8px}
  /* Lobby: show the Open/Active/History tab bar and let the selected tab pick which of
     the (now single-column) sections is visible — the others are hidden. */
  .duel-lobby-tabs{display:flex}
  .duel-lobby-cols{gap:0}
  .duel-lobby-cols.tab-open>.active-section,.duel-lobby-cols.tab-open>.history-section,
  .duel-lobby-cols.tab-active>.open-section,.duel-lobby-cols.tab-active>.history-section,
  .duel-lobby-cols.tab-history>.open-section,.duel-lobby-cols.tab-history>.active-section{display:none}
  /* Topbar: the options (☰) button stays on the LEFT with the title centered beside it —
     it used to wrap onto its own line ABOVE the title (a stale rule from when this row held
     three separate Menu/Rules/Abandon buttons; now it's one small ☰, so it fits). Drop the
     flex spacers and let the title flex to fill the middle (text-align:center) between the
     ☰ (left) and the right slot — no wrap, so it can never overflow. */
  .duel-topbar{gap:8px}
  .duel-topbar .spacer{display:none}
  .duel-title{flex:1;text-align:center;font-size:1.25rem;min-width:0}
  /* Board cells size themselves from their column (container query above), so the board
     needs no explicit sizes — hard-coding widths would fight those clamps. The board gap
     must NOT be overridden either: it scales with the cell to keep the board's geometry
     proportional, which is what the refill path relies on (a fixed 5px pushed the path
     ~6px off the cell centres at this width). */
  /* CARDS on phones: keep every card the SAME size (the shorter top rows just end early —
     the pyramid — NOT stretched to fill), but make them as BIG as the row allows. The
     level-I row is deck + 5 cards. Like SPENDER on mobile, the deck is a THINNER stub
     (0.75x a card) so the five face-up cards get the freed width — so the row is 5 + 0.75 =
     5.75 card-widths, not 6. Overhead is panel(24) + gaps(5x6=30) + ~3px slack = 57. The deck
     is an explicit 0.75x --card-w (a FIXED fraction, not flex) so every row's deck stub is the
     SAME width — the uneven-per-row shrink an earlier flex approach caused can't recur.
     --card-h ratio 1.71 (~0.58 w:h) keeps the compact-but-legible height. */
  .duel-col-cards .level-row{--card-w:clamp(40px, calc((100cqw - 57px) / 5.75), 190px);--card-h:calc(var(--card-w) * 1.71);gap:6px}
  /* The shared .level-row>* rule makes every cell flex-GROW (capped at --card-w). Pin the deck
     to a FIXED 0.75x stub (no grow/shrink) so it can't balloon to fill the slack on the shorter
     3/4-card rows — that flex-grow is exactly what made the deck a different width per row.
     The face-up cards still grow into the width the thinner deck frees. */
  .duel-col-cards .level-row .deck-pile{flex:0 0 calc(var(--card-w) * 0.75);max-width:calc(var(--card-w) * 0.75)}
  /* Mobile only: bump the card's info icons +20% for legibility at phone card sizes — the cost
     pips + their numbers, the card-type (bonus) disc, and the special-ability glyph. These are
     the base Duel ratios (the .card-* rules above) x1.2; overriding here keeps desktop as-is. */
  .duel-col-cards .level-row .cost-gem{width:calc(var(--card-h) * 0.1152);height:calc(var(--card-h) * 0.1152)}
  .duel-col-cards .level-row .cost-num{font-size:calc(var(--card-h) * 0.114)}
  .duel-col-cards .level-row .card-bonus{width:calc(var(--card-h) * 0.168);height:calc(var(--card-h) * 0.168)}
  .duel-col-cards .level-row .card-ability{font-size:calc(var(--card-h) * 0.0984)}
  .duel .duel-deck{width:52px;min-height:80px}
}
@media(max-width:600px){
  /* Lobby cards on phones: the shared .btn is big (11px 20px), so an Open card's
     Return + Cancel (two Cinzel buttons) ran past the right edge. Shrink the card buttons
     and let the actions WRAP below the info as a safety net, so nothing is ever clipped. */
  .duel .lby-card{flex-wrap:wrap;row-gap:10px}
  .duel .lby-card .btn{padding:8px 12px;font-size:.78rem}
  .duel .lby-card-actions{margin-left:auto}
}
@media(max-width:480px){
  /* Action row on phones: the take/buy + Replenish + close(X) trio is at most 3 buttons
     (selCells and selCard are mutually exclusive). The Cinzel buttons are wide (letter-spacing),
     so at full padding "Take 3 tokens" pushed the X onto its own line. Shrink padding/gap/spacing
     so all three stay on ONE row down to ~300px, while still wrapping gracefully if ever more. */
  .duel-actionrow{gap:6px}
  .duel-actionrow .btn{padding:8px 12px;font-size:.8rem;letter-spacing:.03em}
}
@media(min-width:1121px){
  /* Desktop game screen LOCKS to the viewport (the 3-col layout only): the columns fill
     the space under the topbar so the board, player rail, and log all reach the bottom of
     the screen, and the log scrolls INTERNALLY instead of growing the page. (.app is
     min-height:100vh + flex-column; we pin a definite height here so 1fr rows + flex kids
     resolve and overflow is contained. Fixed-position layers — modals/toast/flyers/reconn
     bar/menu — are out of flow, so overflow:hidden can't clip them.) */
  .duel-gamescreen{height:100dvh;overflow:hidden;padding-bottom:14px}
  .duel-gamescreen .duel-cols{flex:1;min-height:0;align-items:stretch}
  /* board fills its column; keep the 5x5 grid vertically centered in the tall panel */
  .duel-gamescreen .duel-col-board{min-height:0;display:flex;flex-direction:column}
  .duel-gamescreen .duel-board-wrap{flex:1;justify-content:center}
  /* the two player boxes split the rail and reach the bottom; each box is a flex column
     so its reserved cards anchor the box foot (rest of the content stays at the top). The
     rail scrolls if a short screen can't fit both boxes rather than clipping them. */
  .duel-gamescreen .duel-col-side{display:flex;flex-direction:column;gap:14px;min-height:0;overflow-y:auto}
  /* overflow-y:auto: each box is a fixed-height flex item, so when its content (esp. tall
     reserved cards) can't fit it SCROLLS inside its own bounds instead of the card spilling
     out past the box border. margin-top:auto still pins reserved to the foot when it fits
     (auto margins only eat POSITIVE free space; with overflow it resolves to 0). */
  .duel-gamescreen .duel-col-side .duel-player{flex:1 1 0;min-height:0;margin-bottom:0;display:flex;flex-direction:column;overflow-y:auto}
  .duel-gamescreen .duel-col-side .duel-reserved-row{margin-top:auto}
  /* the log fills its (viewport-bounded) column and scrolls inside — the row-2 1fr height
     caps it to the screen, min-height:0 lets the inner move-log overflow-scroll. */
  .duel-gamescreen .duel-col-log{min-height:0}
}
`;

// Spender's shared card/gem/log rules come FIRST, then Duel's own layout on top.
const duelStyles = baseCss + lobbyCss + splendorPanelCss + splendorCardCss + splendorCardExtraCss
  + splendorPillCss + splendorLogCss + css + gameMenuCss + createModalCss + lobbyCreateRowCss;

// ─── Log formatting ─────────────────────────────────────────────────────────
// One log record -> {name, action}, matching Spender's formatLogMove shape so the
// shared LogEntry renders both games' logs identically (turn | name | action).
function fmtLog(e, names, cardsById, royals) {
  const name = e.pid ? (names[e.pid] || e.pid) : "";
  const card = e.card_id ? cardsById[e.card_id] : null;
  const cardName = card
    ? `a level-${card.level}${card.bonus && card.bonus !== "wild" ? " " + card.bonus : card.bonus === "wild" ? " wild" : ""} card${card.points ? ` (${card.points} pts)` : ""}`
    : "a card";
  const act = (() => {
    switch (e.type) {
      case "take": {
        const counts = {};
        (e.colors || []).forEach((c) => { counts[c] = (counts[c] || 0) + 1; });
        const s = Object.entries(counts).map(([c, n]) => (n > 1 ? `${n} ${c}` : c)).join(", ");
        return `took ${s}${e.opp_privilege ? " (opponent gains a Privilege)" : ""}`;
      }
      case "use_privilege": return `spent a Privilege for a ${e.color} token`;
      case "replenish": return `replenished the board (${e.count})${e.opp_privilege ? " — opponent gains a Privilege" : ""}`;
      case "reserve": return e.from_deck
        ? `took gold and reserved from the level-${e.level} deck`
        : `took gold and reserved ${cardName}`;
      case "buy": return `purchased ${cardName}${e.as_color ? ` (wild as ${e.as_color})` : ""}`;
      case "take_same": return `took a bonus ${e.color} token`;
      case "steal": return `stole a ${e.color} token`;
      case "privilege_gain": return "gained a Privilege";
      case "again": return "earns another turn";
      case "extra_turn": return "takes an extra turn";
      case "royal": return `claimed a Royal (${e.points} pts)`;
      case "discard": return `discarded a ${e.color} token`;
      case "skip_pending": return `skipped (${e.kind})`;
      case "pass": return "passed";
      case "game_over": return `wins — ${WIN_DESC[e.condition] || e.condition}${e.color ? ` (${e.color})` : ""}`;
      default: return e.type;
    }
  })();
  return { name, action: act, card };
}

// ─── Main component ─────────────────────────────────────────────────────────
export default function SpenderDuel({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");     // lobby | waiting | game
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [catalog, setCatalog] = useState(null);      // {cards, royals, colors}
  const [openGames, setOpenGames] = useState(() => readLobbyCache("duel", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("duel", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("duel", myId, "history", []));
  const [lobbyTab, setLobbyTab] = useState("open");  // mobile-only Open/Active/History selector
  const [loadingGames, setLoadingGames] = useState(false);
  const [toast, setToast] = useState("");
  const [reconnecting, setReconnecting] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);  // the New Game options modal
  const [createOpp, setCreateOpp] = useState("ai");               // "friend" | "ai"
  const [createDiff, setCreateDiff] = useState("hard");           // AI difficulty (easy|normal|hard)
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  // review mode: an HTTP-loaded finished game (no WebSocket). replaySnapshots is the
  // per-move board list from /review; replayTurn is which one is on screen.
  const [reviewOnly, setReviewOnly] = useState(false);
  const [replaySnapshots, setReplaySnapshots] = useState(null);
  const [replayTurn, setReplayTurn] = useState(null);
  const [gameOverDismissed, setGameOverDismissed] = useState(false);

  // interaction state
  const [selCells, setSelCells] = useState([]);      // token line selection
  const [privArmed, setPrivArmed] = useState(false); // privilege mode (pick a token)
  const [goldCell, setGoldCell] = useState(null);    // armed gold cell (reserve mode)
  const [selCard, setSelCard] = useState(null);      // {id, from} buy candidate
  const [wildPick, setWildPick] = useState(false);   // wild as_color chooser open
  const [modalCard, setModalCard] = useState(null);  // a log entry's card, opened for inspection
  const [flyers, setFlyers] = useState([]);
  const flyerSeq = useRef(0);
  const prevLogLen = useRef(0);
  // Board REFILL animation: tokens fly from the bag to each newly-filled cell, one by one.
  const [refillFlyers, setRefillFlyers] = useState([]);
  const [hiddenCells, setHiddenCells] = useState(() => new Set());   // real tokens hidden until their flyer lands
  const refillSeq = useRef(0);
  const prevBoardRef = useRef(null);
  const refillRoomRef = useRef(null);
  const flyerRoomRef = useRef(null);   // which room prevLogLen is synced to (first-sight guard)
  const reconnTimer = useRef(null);
  const reconnTries = useRef(0);
  // client-side (WASM) bot search — see the effects below
  const wasmPoolRef = useRef(null);          // [{ ready, request, terminate }] — RPC-wrapped workers
  const [wasmReady, setWasmReady] = useState(false);
  const clientAiArmedRef = useRef(null);     // room we've announced capability for (cleared on disconnect)
  const aiDispatchRef = useRef(null);        // "room:decision" we have already dispatched a search for

  // ── URL routing (segment 2 = room id; the shell owns segment 1 = "/duel") ──
  const screenRef = useRef(screen);
  screenRef.current = screen;
  const roomIdRef = useRef(roomId);
  roomIdRef.current = roomId;
  const urlAttemptRef = useRef(null);     // {rid, retried} — a URL-driven room attempt in flight
  const didInitRef = useRef(false);       // StrictMode double-mount guard for the deep-entry effect
  const popHandlerRef = useRef(() => {}); // fresh-closure mirror for the mount-once popstate effect

  const playerName = authUser?.name || "Player";

  // ── derived (keep ABOVE all effects — TDZ rule) ──
  // `liveGame` is the authoritative game; `game` is what the BOARD shows — the rewound
  // snapshot while reviewing, else the live state. The move LOG always renders from
  // liveGame so every row stays visible/clickable no matter how far back you rewind.
  const liveGame = roomData?.game;
  const reviewing = replayTurn != null && Array.isArray(replaySnapshots) && !!replaySnapshots[replayTurn];
  const game = reviewing ? replaySnapshots[replayTurn].game : liveGame;
  const names = roomData?.players || {};
  const oppId = game ? game.order.find((p) => p !== myId) : Object.keys(names).find((p) => p !== myId);
  const me = game?.players?.[myId];
  const opp = oppId ? game?.players?.[oppId] : null;
  // `over` follows the LIVE game, not the rewound board: a historical "playing"
  // snapshot must not resurrect the in-game chrome of a finished game.
  const over = liveGame?.phase === "over";
  const cardsById = catalog?.cards || {};
  const royals = catalog?.royals || {};
  // Read-only while reviewing: no pendings, no turn, no interaction (below).
  const pendingMine = !reviewing && !!game && game.pending_pid === myId;
  const myTurn = !reviewing && !!game && !over
    && (game.pending_pid ? game.pending_pid === myId : game.turn === myId);
  const botThinking = !reviewing && !!game && roomData?.vs_ai && !over
    && (game.pending_pid || game.turn) === roomData?.ai_player;
  const replenished = !!game?.turn_flags?.replenished;
  const myBonuses = useMemo(() => bonusesOf(me, cardsById), [me, cardsById]);
  // The replenish spiral, as cell-centre points (the backend serves the real order).
  const spiralPts = useMemo(
    () => (catalog?.spiral || []).map(cellCentre), [catalog]);
  const boardHasEmpty = !!game && game.board.some((t) => t === null);
  const canReplenish = myTurn && !pendingMine && (game?.bag_count || 0) > 0 && boardHasEmpty && !replenished;
  const canUsePrivilege = myTurn && !pendingMine && (me?.privileges || 0) > 0 && !replenished
    && !!game && game.board.some((t) => t && t !== "gold");
  const pendKind = game?.pending_kind;
  const pendCtx = game?.pending?.ctx || {};

  // ── socket ──
  const handleMessage = useCallback((msg) => {
    if (msg.type === "error") {
      // A URL-driven room attempt (deep link / popstate) failed. A stale token gets ONE
      // retry as a plain join (invite-link case); anything else falls back to the lobby
      // and the dead room URL is replaced with /duel so a reload doesn't re-attempt it.
      const ua = urlAttemptRef.current;
      if (ua) {
        if (msg.message === "invalid token" && !ua.retried) {
          ua.retried = true;
          try { localStorage.removeItem(`duel_token_${ua.rid}_${myId}`); } catch {}
          resumeGame(ua.rid);   // token now gone → plain join
          return;
        }
        urlAttemptRef.current = null;
        try {
          if (localStorage.getItem("duel_roomId") === ua.rid) localStorage.removeItem("duel_roomId");
          localStorage.removeItem(`duel_token_${ua.rid}_${myId}`);
        } catch {}
        setRoomId(""); setRoomData(null); setScreen("lobby");
        replacePath(buildPath("duel"));
      }
      setToast(msg.message || "error"); return;
    }
    const room = msg.room;
    if (!room) return;
    const rid = room.room_id || roomId;
    const tok = room.reconnect_tokens?.[myId];
    if (tok) {
      try {
        localStorage.setItem(`duel_token_${rid}_${myId}`, tok);
        localStorage.setItem("duel_roomId", rid);
      } catch {}
    }
    setRoomData(room);
    const inGame = room.status === "playing" || room.status === "over";
    if (msg.type === "created" || msg.type === "joined" || msg.type === "reconnected") {
      // Entering the room gives it its URL (server-confirmed, never at click time;
      // waiting + game share it and pushPath's dedup makes repeats no-ops).
      if (rid) pushPath(buildPath("duel", rid));
      urlAttemptRef.current = null;
      setScreen(inGame ? "game" : "waiting");
    } else if (msg.type === "room_update" && inGame && screen !== "game") {
      setScreen("game");
    }
  }, [myId, roomId, screen]); // eslint-disable-line react-hooks/exhaustive-deps

  const { connected, connect, send, disconnect, socketReady } = useSocket(handleMessage);

  // static catalog (card data) once
  useEffect(() => {
    fetch(`${DUEL_HTTP}/catalog`).then((r) => r.json()).then((d) => { if (d.ok) setCatalog(d); }).catch(() => {});
  }, []);

  const fetchGames = useCallback(() => {
    setLoadingGames(true);
    fetch(`${DUEL_HTTP}/games`).then((r) => r.json()).then((d) => { const g = d.games || []; setOpenGames(g); writeLobbyCache("duel", myId, "open", g); })
      .catch(() => {}).finally(() => setLoadingGames(false));
    if (authUser?.session_token) {
      const headers = { Authorization: `Bearer ${authUser.session_token}` };
      fetch(`${DUEL_HTTP}/games/mine`, { headers }).then((r) => r.json()).then((d) => { const g = d.games || []; setMyGames(g); writeLobbyCache("duel", myId, "mine", g); }).catch(() => {});
      fetch(`${DUEL_HTTP}/games/history`, { headers }).then((r) => r.json()).then((d) => { const g = d.games || []; setHistory(g); writeLobbyCache("duel", myId, "history", g); }).catch(() => {});
    } else { setMyGames([]); setHistory([]); writeLobbyCache("duel", myId, "mine", []); writeLobbyCache("duel", myId, "history", []); }
  }, [authUser, myId]);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);

  // Mount: do NOT auto-resume a saved game — it snapped you from the lobby into the game
  // on load (jarring). Resume is EXPLICIT via the lobby's Resume button. Keep only the
  // disconnect cleanup so an explicit connection tears down on unmount. (A room id IN THE
  // URL is different — that's an explicit destination; see the deep-entry effect below.)
  useEffect(() => {
    return () => disconnect();
  }, []); // eslint-disable-line

  // ── URL deep entry + popstate (this component owns "/duel/<ROOMID>") ──
  // URL-driven room entry: clear any read-only review state first (a popstate Forward
  // can fire while reviewOnly is set), then run the existing resume semantics (saved
  // token → reconnect, else join — the invite-link behavior).
  const urlResume = (rid) => {
    setReviewOnly(false); setReplaySnapshots(null); setReplayTurn(null);
    urlAttemptRef.current = { rid, retried: false };
    resumeGame(rid);
  };
  useEffect(() => {
    if (didInitRef.current) return;
    didInitRef.current = true;
    const r = parsePath();
    if (r.game === "duel" && r.room) urlResume(r.room);
  }, []); // eslint-disable-line
  // Back/Forward while mounted: only our own segment 2 — mode changes unmount us via
  // the shell. Routed through a ref so the mount-once subscription never goes stale.
  popHandlerRef.current = (r) => {
    if (r.game !== "duel") return;
    if (r.room && r.room !== roomIdRef.current) {
      urlResume(r.room);
    } else if (!r.room && (roomIdRef.current || urlAttemptRef.current)) {
      // Back out of the room — INCLUDING out of a still-connecting attempt (popping
      // during the join's round trip would otherwise let the late "reconnected"
      // message push the room URL right back). leaveToLobby's disconnect kills the
      // in-flight socket; its pushPath dedups (URL is already /duel after the pop).
      urlAttemptRef.current = null;
      leaveToLobby();
    }
  };
  useEffect(() => subscribe((r) => popHandlerRef.current(r)), []); // eslint-disable-line

  // auto-reconnect while in a live game (load-bearing for vs-bot: the bot's turn is
  // re-driven on reconnect — the CoC "hung for minutes" lesson)
  // A review is HTTP-loaded and has no socket — never try to reconnect one.
  const inLiveGame = !!roomId && !reviewOnly
    && (screen === "game" || screen === "waiting") && roomData?.status !== "over";
  const attemptReconnect = useCallback(() => {
    if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; }
    const rs = socketReady();
    if (rs === 0 || rs === 1) { reconnTimer.current = setTimeout(attemptReconnect, 3000); return; }
    let tok = null;
    try { tok = localStorage.getItem(`duel_token_${roomId}_${myId}`); } catch {}
    if (tok) { setReconnecting(true); connect(`${DUEL_WS}/${roomId}/${myId}`, { action: "reconnect", token: tok }); }
    reconnTries.current += 1;
    reconnTimer.current = setTimeout(attemptReconnect, Math.min(2000 * reconnTries.current, 8000));
  }, [roomId, myId, connect, socketReady]);

  useEffect(() => {
    const clear = () => { if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; } };
    if (connected || !inLiveGame) {
      clear(); reconnTries.current = 0;
      if (connected) setReconnecting(false);
      return;
    }
    if (!reconnTimer.current) attemptReconnect();
    return clear;
  }, [connected, inLiveGame, attemptReconnect]);

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState !== "visible" || connected || !inLiveGame) return;
      reconnTries.current = 0;
      attemptReconnect();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [connected, inLiveGame, attemptReconnect]);

  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2600); return () => clearTimeout(t); } }, [toast]);

  // clear interaction state whenever the decision context changes
  useEffect(() => {
    setSelCells([]); setPrivArmed(false); setGoldCell(null); setSelCard(null); setWildPick(false);
  }, [game?.turn, game?.turn_number, game?.pending_kind]);
  useEffect(() => { setGameOverDismissed(false); }, [roomId]);

  // ── flyer animations: driven by NEW log entries (each carries pid + cells/colors) ──
  useEffect(() => {
    if (reviewing || reviewOnly) return;   // rewinding isn't a move: never animate history
    const log = liveGame?.log;
    if (!log) return;
    // First sight of THIS room's log — a fresh game (0 moves) or a resumed one (N moves):
    // sync the counter without animating whatever is already there. This replaces the old
    // `prev===0` guard, which also swallowed the FIRST move of a fresh game (0 -> 1).
    if (flyerRoomRef.current !== roomId) {
      flyerRoomRef.current = roomId;
      prevLogLen.current = log.length;
      return;
    }
    const prev = prevLogLen.current;
    prevLogLen.current = log.length;
    if (log.length <= prev || log.length - prev > 6) return;  // no new moves / reconnect catch-up
    const fresh = log.slice(prev);
    const rect = (sel) => { const el = document.querySelector(sel); return el ? el.getBoundingClientRect() : null; };
    // A token flies to the EXACT pill it lands in (that player's pill for that color),
    // not the middle of the whole tokens row; fall back to the row if the pill isn't there.
    const tokTarget = (pid, color) =>
      rect(`[data-tokens="${pid}"] [data-token="${color}"]`) || rect(`[data-tokens="${pid}"]`);
    const add = [];
    const mkTok = (color, from, to, size = 34) => {
      if (!from || !to) return;
      add.push({
        id: `f${flyerSeq.current++}`, color, size,
        left: from.left + from.width / 2 - size / 2, top: from.top + from.height / 2 - size / 2,
        dx: to.left + to.width / 2 - (from.left + from.width / 2), dy: to.top + to.height / 2 - (from.top + from.height / 2),
      });
    };
    for (const e of fresh) {
      if (e.type === "take" && e.cells) {
        e.cells.forEach((cell, i) => mkTok(e.colors?.[i], rect(`[data-cell="${cell}"]`), tokTarget(e.pid, e.colors?.[i])));
      } else if ((e.type === "use_privilege" || e.type === "take_same") && e.cell != null) {
        mkTok(e.color, rect(`[data-cell="${e.cell}"]`), tokTarget(e.pid, e.color));
      } else if (e.type === "reserve" && e.gold_cell != null) {
        mkTok("gold", rect(`[data-cell="${e.gold_cell}"]`), tokTarget(e.pid, "gold"));
      } else if (e.type === "steal") {
        const other = (liveGame.order || []).find((p) => p !== e.pid);
        mkTok(e.color, rect(`[data-tokens="${other}"]`), tokTarget(e.pid, e.color));
      } else if (e.type === "buy") {
        mkTok(null, rect("[data-pyramid]"), rect(`[data-tokens="${e.pid}"]`), 44);
      }
    }
    if (!add.length) return;
    setFlyers((f) => [...f, ...add]);
    const ids = new Set(add.map((a) => a.id));
    setTimeout(() => setFlyers((f) => f.filter((x) => !ids.has(x.id))), 620);
  }, [liveGame?.log?.length, roomId]); // eslint-disable-line

  // ── board REFILL animation: on a replenish, empty cells go null->token; fly each new
  //    token from the bag to its cell, staggered center-outward, and keep the real cell
  //    EMPTY (hidden) until its flyer lands — so it reads as tokens drawn from the bag. ──
  useEffect(() => {
    const board = liveGame?.board;
    if (!board) return;
    // Don't animate while rewinding, and re-baseline on first sight of a room / after review
    // so a resume or a review-exit never bursts the whole board.
    if (reviewing || reviewOnly || refillRoomRef.current !== roomId) {
      refillRoomRef.current = roomId; prevBoardRef.current = board; return;
    }
    const prev = prevBoardRef.current;
    prevBoardRef.current = board;
    if (!prev) return;
    // Newly-filled cells (null/absent -> a token). In Duel the board only GAINS tokens via a
    // bag refill, so this diff is exactly the replenish set.
    const filled = [];
    for (let i = 0; i < board.length; i++) if (board[i] && !prev[i]) filled.push({ cell: i, color: board[i] });
    if (!filled.length) return;
    const bag = document.querySelector(".duel-bag");
    if (!bag) return;                                  // no anchor -> skip (tokens just appear)
    const br = bag.getBoundingClientRect();
    const from = { x: br.left + br.width / 2, y: br.top + br.height / 2 };
    // Fill order: centre cell (2,2) outward, so it mirrors the printed refill spiral.
    const d2 = (i) => (Math.floor(i / 5) - 2) ** 2 + ((i % 5) - 2) ** 2;
    filled.sort((a, b) => d2(a.cell) - d2(b.cell));
    const STEP = 45, DUR = 300;
    const add = [];
    filled.forEach((f, k) => {
      const el = document.querySelector(`[data-cell="${f.cell}"]`);
      if (!el) return;
      const cr = el.getBoundingClientRect();
      const size = Math.max(18, Math.round(cr.width || 34));
      const to = { x: cr.left + cr.width / 2, y: cr.top + cr.height / 2 };
      add.push({
        id: `r${refillSeq.current++}`, cell: f.cell, color: f.color, size,
        left: from.x - size / 2, top: from.y - size / 2,
        dx: to.x - from.x, dy: to.y - from.y, delay: k * STEP, dur: DUR,
      });
    });
    if (!add.length) return;
    setHiddenCells((s) => new Set([...s, ...add.map((a) => a.cell)]));
    setRefillFlyers((fl) => [...fl, ...add]);
    // Each token is REVEALED (and its flyer removed) exactly when it lands.
    add.forEach((f) => setTimeout(() => {
      setHiddenCells((s) => { const n = new Set(s); n.delete(f.cell); return n; });
      setRefillFlyers((fl) => fl.filter((x) => x.id !== f.id));
    }, f.delay + f.dur));
  }, [liveGame?.board, roomId, reviewing]); // eslint-disable-line

  // ── client-side (WASM) bot search ───────────────────────────────────────────
  // The bot's search runs HERE, on the player's CPU, instead of on Render's free tier
  // where it gets ~5 sims per root move. Same bot (duel-core is a parity-gated port of
  // ai.py) — only the sim count changes.
  //
  // Root-parallel: each worker searches the SAME decision with its own seed and returns
  // ROOT STATISTICS; we SUM them by move index (the index space is a pure function of
  // the state, so every worker agrees) and hand the totals back to the wasm to pick.
  // The pick rule is NOT reimplemented here — see duel-worker.js.
  //
  // Every failure path is a no-op that leaves the server to play the move: no workers,
  // no wasm, a search error, a slow device. We only ever announce `client_ai_ready`
  // once at least one worker is alive.
  useEffect(() => {
    if (!roomData?.vs_ai || (roomData?.ai_difficulty !== "hard" && roomData?.ai_difficulty !== "expert")
      || wasmPoolRef.current || typeof Worker === "undefined") return;
    const url = `${import.meta.env.BASE_URL}wasm/duel-worker.js`;
    const cores = Math.max(1, Math.min(navigator.hardwareConcurrency || 4, 4));
    const makeWorker = () => {
      let w;
      try { w = new Worker(url, { type: "module" }); } catch { return null; }
      const pending = new Map();
      let resolveReady, nextId = 1;
      const ready = new Promise((res) => (resolveReady = res));
      w.onmessage = (e) => {
        const d = e.data || {};
        if (d.ready !== undefined) { resolveReady(!!d.ready); return; }
        if (d.id != null && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
      };
      w.onerror = () => resolveReady(false);
      return {
        ready,
        request(payload) {
          const id = nextId++;
          return new Promise((res) => { pending.set(id, res); w.postMessage({ ...payload, id }); });
        },
        terminate() { try { w.terminate(); } catch {} },
      };
    };
    const pool = Array.from({ length: cores }, makeWorker).filter(Boolean);
    wasmPoolRef.current = pool;
    Promise.all(pool.map((wk) => wk.ready)).then((flags) => {
      const live = pool.filter((_, i) => flags[i]);
      if (live.length > 0) {
        wasmPoolRef.current = live;
        setWasmReady(true);
        console.info(`[duel client-AI] ${live.length}/${cores} WASM search workers ready`);
      } else {
        console.warn("[duel client-AI] no WASM workers loaded -> server AI");
      }
    });
    return () => { pool.forEach((wk) => wk.terminate()); wasmPoolRef.current = null; setWasmReady(false); };
  }, [roomData?.vs_ai, roomData?.ai_difficulty]);

  // The server disarms the client when its socket drops, so a reconnect MUST re-announce
  // or the room silently serves the server bot for the rest of the game.
  useEffect(() => { if (!connected) clientAiArmedRef.current = null; }, [connected]);

  // Announce capability once per room/socket -> the server then ships `ai_search` on the
  // bot's decisions.
  useEffect(() => {
    if (wasmReady && connected && roomData?.room_id
      && clientAiArmedRef.current !== roomData.room_id) {
      clientAiArmedRef.current = roomData.room_id;
      send({ action: "client_ai_ready" });
    }
  }, [wasmReady, connected, roomData?.room_id, send]);

  // The server ships `ai_search` on each of the bot's decisions -> search it and answer.
  useEffect(() => {
    const as = roomData?.ai_search;
    const pool = wasmPoolRef.current;
    if (!as || !wasmReady || !pool || pool.length === 0) return;
    // One dispatch per decision. Keyed by ROOM too: the counter restarts at 1 in a new
    // room, so a bare decision number could collide with the last one we dispatched in
    // the previous game and silently skip the bot's first decision.
    const key = `${roomData.room_id}:${as.decision}`;
    if (aiDispatchRef.current === key) return;
    aiDispatchRef.current = key;
    const state = JSON.stringify(as.state);
    const t0 = performance.now();
    // The server's cap is an AGGREGATE across the pool (visits are summed), so split it.
    const perWorker = Math.max(1, Math.ceil((as.max_sims || 0) / pool.length));
    (async () => {
      try {
        const parts = await Promise.all(pool.map((wk, i) => wk.request({
          kind: "search", state, budget: as.budget_ms, maxSims: perWorker,
          seed: ((as.decision * 2654435761) ^ (i * 40503 + 1)) >>> 0,
          expert: roomData.ai_difficulty === "expert",
        }).catch(() => null)));
        const good = parts.filter((p) => p && p.visits && p.wins);
        if (!good.length) return;                 // every worker failed -> server fallback
        const k = good[0].visits.length;
        const visits = new Array(k).fill(0);
        const wins = new Array(k).fill(0);
        let sims = 0;
        for (const p of good) {
          // Same state in => same root move list, so a length mismatch means a stale
          // worker. Pooling it would add up DIFFERENT moves' stats — drop it instead.
          if (p.visits.length !== k || p.wins.length !== k) continue;
          for (let a = 0; a < k; a++) { visits[a] += p.visits[a]; wins[a] += p.wins[a]; sims += p.visits[a]; }
        }
        const res = await pool[0].request({ kind: "pick", state, visits, wins });
        const move = res?.move && JSON.parse(res.move);
        if (!move || move.error) return;
        console.info(`[duel client-AI] ${good.length} workers, ${sims} sims in `
          + `${Math.round(performance.now() - t0)}ms ->`, move);
        // Pad to a flat ~1.5s/move (device-independent: a fast client waits, a slow one
        // doesn't). A stale submit after the wait is harmless — the server drops any
        // ai_move whose decision has been superseded.
        const wait = CLIENT_AI_MIN_MS - (performance.now() - t0);
        if (wait > 0) await new Promise((r) => setTimeout(r, wait));
        send({ action: "ai_move", decision: as.decision, move });
      } catch {}
    })();
  }, [roomData, wasmReady, send]);

  // ── actions ──
  const mv = (move) => send({ action: "move", move });

  const createGame = (vsAi, difficulty) => {
    const rid = roomCode();
    setRoomId(rid);
    setRoomData(null);
    setShowCreateModal(false);
    const msg = { action: "create", name: playerName, vs_ai: vsAi };
    if (vsAi) msg.ai_difficulty = difficulty || "hard";
    connect(`${DUEL_WS}/${rid}/${myId}`, msg);
  };
  const joinGame = (rid) => {
    rid = (rid || "").toUpperCase().trim();
    if (!rid) return;
    setRoomId(rid);
    connect(`${DUEL_WS}/${rid}/${myId}`, { action: "join", name: playerName });
  };
  const resumeGame = (rid) => {
    let tok = null;
    try { tok = localStorage.getItem(`duel_token_${rid}_${myId}`); } catch {}
    setRoomId(rid);
    connect(`${DUEL_WS}/${rid}/${myId}`, tok ? { action: "reconnect", token: tok } : { action: "join", name: playerName });
  };
  const cancelGame = (rid) => {
    const headers = { "Content-Type": "application/json" };
    if (authUser?.session_token) headers.Authorization = `Bearer ${authUser.session_token}`;
    fetch(`${DUEL_HTTP}/games/${rid}/cancel?player_id=${encodeURIComponent(myId)}`, { method: "POST", headers })
      .then((r) => r.json()).then((d) => {
        if (!d.ok) { setToast(d.message || "Could not cancel"); return; }
        try {
          if (localStorage.getItem("duel_roomId") === rid) localStorage.removeItem("duel_roomId");
          localStorage.removeItem(`duel_token_${rid}_${myId}`);
        } catch {}
        fetchGames();
      }).catch(() => setToast("Could not cancel"));
  };
  // Load a FINISHED game read-only over HTTP (no WebSocket) and open it for review.
  // Also used by the end-of-game "Review game" button, which already has a live socket
  // — there we keep it and only attach the snapshots.
  const enterReview = (id, keepLive = false) => {
    const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
    fetch(`${DUEL_HTTP}/games/${id}/review?player_id=${encodeURIComponent(myId)}`, { headers })
      .then((r) => r.json()).then((d) => {
        if (!d.ok) { setToast(d.message || "Could not load review"); return; }
        if (!keepLive) {
          disconnect();
          setRoomData({
            game: d.game, players: d.players || {}, host: null, status: "over",
            vs_ai: false, ai_player: null,
          });
          setRoomId(id);
          setReviewOnly(true);
          setScreen("game");
        }
        setReplaySnapshots(d.snapshots || null);
        // Land on the FINAL board; the nav bar rewinds from there.
        setReplayTurn(d.snapshots ? d.snapshots.length - 1 : null);
        if (!d.snapshots) setToast("This game can't be replayed turn-by-turn");
      }).catch(() => setToast("Could not load review"));
  };
  const goToTurn = (idx) => {
    if (!replaySnapshots) return;
    setReplayTurn(Math.max(0, Math.min(replaySnapshots.length - 1, idx)));
  };
  const exitReview = () => { setReplaySnapshots(null); setReplayTurn(null); };

  const leaveToLobby = () => {
    disconnect();
    pushPath(buildPath("duel"));   // leave the room URL (dedup no-op when popstate-driven)
    setScreen("lobby");
    setRoomData(null);
    setRoomId("");
    setReviewOnly(false);
    exitReview();
  };
  const abandonGame = () => {
    send({ action: "abandon" });
    setConfirmAbandon(false);
  };

  // board cell click routing
  const cellClick = (i) => {
    if (!game || over) return;
    const tok = game.board[i];
    if (!tok) return;
    if (pendingMine && pendKind === "take_same") {
      if (tok === pendCtx.color && (pendCtx.cells || []).includes(i)) mv({ type: "take_same", cell: i });
      return;
    }
    if (!myTurn || pendingMine) return;
    if (privArmed) {
      if (tok !== "gold") { mv({ type: "use_privilege", cell: i }); setPrivArmed(false); }
      return;
    }
    if (tok === "gold") {
      if ((me?.reserved?.length || 0) >= 3) { setToast("You already have 3 reserved cards"); return; }
      setGoldCell(goldCell === i ? null : i);
      setSelCells([]); setSelCard(null);
      return;
    }
    setGoldCell(null); setSelCard(null);
    setSelCells((sel) => {
      if (sel.includes(i)) return sel.filter((x) => x !== i);
      const cand = [...sel, i];
      if (lineOk(cand, game.board)) return cand;
      return [i];  // start a fresh selection from this token
    });
  };


  const submitTake = () => {
    if (selCells.length && lineOk(selCells, game.board)) {
      mv({ type: "take", cells: selCells });
      setSelCells([]);
    }
  };

  const pyramidCardClick = (cid, lvl, slot) => {
    if (!myTurn || pendingMine || over) return;
    if (goldCell != null) {
      mv({ type: "reserve", gold_cell: goldCell, source: { kind: "pyramid", level: lvl, slot } });
      setGoldCell(null);
      return;
    }
    setSelCells([]);
    setSelCard((s) => (s && s.id === cid ? null : { id: cid, from: "pyramid" }));
  };
  const deckClick = (lvl) => {
    if (!myTurn || pendingMine || over || goldCell == null) return;
    if ((game.deck_counts?.[String(lvl)] || 0) < 1) return;
    mv({ type: "reserve", gold_cell: goldCell, source: { kind: "deck", level: lvl } });
    setGoldCell(null);
  };
  const reservedCardClick = (cid) => {
    if (!myTurn || pendingMine || over) return;
    setSelCells([]); setGoldCell(null);
    setSelCard((s) => (s && s.id === cid ? null : { id: cid, from: "reserve" }));
  };

  const selCardData = selCard ? cardsById[selCard.id] : null;
  const selAffordable = selCardData && canAffordCard(selCardData, me, cardsById);
  const wildEligible = COLORS.filter((c) => myBonuses[c] > 0);
  const submitBuy = (asColor) => {
    if (!selCard) return;
    const move = { type: "buy", card_id: selCard.id, from: selCard.from };
    if (asColor) move.as_color = asColor;
    mv(move);
    setSelCard(null); setWildPick(false);
  };
  const buyClicked = () => {
    if (!selCardData || !selAffordable) return;
    if (selCardData.bonus === "wild") {
      if (!wildEligible.length) { setToast("You need a bonus card before buying a wild card"); return; }
      setWildPick(true);
      return;
    }
    submitBuy(null);
  };

  // ── renders ──
  // Gems in hand: Spender's .token-pill row + its "N gems" total (was a bespoke
  // disc-and-badge). The row keeps its data-tokens anchor for the flyer animations.
  const renderTokens = (p, pid) => {
    const total = TOKENS.reduce((a, t) => a + (p?.tokens?.[t] || 0), 0);
    return (
      <>
        <div className="player-tokens" data-tokens={pid}>
          {TOKENS.map((t) => (p?.tokens?.[t] || 0) > 0 && (
            <TokenPill key={t} color={t} count={p.tokens[t]} />
          ))}
        </div>
        <div className="gem-total">{total} {total === 1 ? "token" : "tokens"}</div>
      </>
    );
  };

  const renderPlayer = (pid, isMe) => {
    const p = game.players[pid];
    const pts = pointsOf(p, cardsById, royals);
    const crowns = crownsOf(p, cardsById);
    const cpts = colorPointsOf(p, cardsById);
    const bon = bonusesOf(p, cardsById);
    const active = !over && (game.pending_pid || game.turn) === pid;
    return (
      <div className={`duel-panel duel-player${active ? " active" : ""}`} key={pid}>
        <div className="hd">
          <span className="nm">
            {names[pid] || pid}{isMe ? " (you)" : ""}
            {!isMe && roomData?.vs_ai && pid === roomData?.ai_player && roomData?.ai_difficulty && (
              <span className="duel-muted" style={{ fontSize: ".8rem", marginLeft: 6 }}>
                ({TIER_NAME[roomData.ai_difficulty] || roomData.ai_difficulty})
              </span>
            )}
          </span>
          {active && <span className="duel-turnbadge">{isMe ? "Your turn" : roomData?.vs_ai && pid === roomData?.ai_player ? "Bot is playing…" : "Their turn"}</span>}
          <WinMeters pts={pts} crowns={crowns} cpts={cpts} />
        </div>
        <Scroll n={p.privileges}
          armed={isMe && privArmed}
          onClick={isMe && canUsePrivilege ? () => { setPrivArmed(!privArmed); setGoldCell(null); setSelCells([]); setSelCard(null); } : undefined}
          title={isMe
            ? (canUsePrivilege ? "Use a Privilege: click here, then click a gem or pearl on the board" : `${p.privileges} Privilege${p.privileges === 1 ? "" : "s"}`)
            : `${p.privileges} Privilege${p.privileges === 1 ? "" : "s"}`} />
        {renderTokens(p, pid)}
        {/* The cards you've BOUGHT: Spender's .bonus-pill row ("+2 W"). Duel appends
            the color's prestige, since 10 points in ONE color is a win condition. */}
        <div className="player-bonuses">
          {COLORS.map((c) => (bon[c] > 0 || cpts[c] > 0) && (
            <BonusPill key={c} color={c} count={bon[c]} letter={false}
              extra={cpts[c] > 0 ? `★${cpts[c]}` : null}
              title={`${bon[c]} ${c} bonus${bon[c] === 1 ? "" : "es"} from cards · ${cpts[c]} prestige in ${c} (10 wins)`} />
          ))}
          {/* Royals ride in the same row, as Spender's nobles do */}
          {(p.royals || []).map((rid) => (
            <span key={rid} className="bonus-pill"
              title={royals[rid]?.ability ? ABILITY_DESC[royals[rid].ability] : "Royal card"}
              style={{ borderColor: "var(--gold)", color: "var(--gold)" }}>
              ♛★{royals[rid]?.points ?? "?"}
            </span>
          ))}
        </div>
        <div className="duel-reserved-row">
          {/* Render by SHAPE, not by whose seat it is: a card id (string) is a card we
              may see — our own, or ANY reserve once the game is over / in review, which
              player_view reveals. A {level, facedown} object is redacted, so show a back.
              (Keying off `isMe` instead would hide the revealed hand in a review — and
              read `r.level` off a string, printing the wrong level on the back.) */}
          {(p.reserved || []).map((r, i) =>
            typeof r === "string" ? (
              <DuelCard key={r} small card={cardsById[r]}
                selected={!reviewing && selCard?.id === r}
                affordable={isMe && !reviewing && canAffordCard(cardsById[r], p, cardsById)}
                needsGold={isMe && goldNeeded(cardsById[r]?.cost || {}, p.tokens, bon) > 0}
                onClick={isMe && !reviewing ? () => reservedCardClick(r) : undefined} />
            ) : (
              <CardBack key={i} level={r.level} />
            ))}
        </div>
      </div>
    );
  };

  // The pyramid uses SPENDER's level-row + deck-pile + card (shared/splendor.jsx), so
  // the rows fit and scale by the same proven mechanism Spender's board uses.
  const renderPyramid = () => (
    <div className="duel-panel" data-pyramid>
      {[3, 2, 1].map((lvl) => {
        const left = game.deck_counts?.[String(lvl)] || 0;
        const canDraw = goldCell != null && left > 0;
        return (
          <div className="level-row" key={lvl}>
            <div className={`deck-pile${canDraw ? "" : " disabled"}`}
              onClick={() => deckClick(lvl)}
              title={goldCell != null ? "Reserve the top card of this deck (blind)" : `${left} cards left`}>
              <span>{["I", "II", "III"][lvl - 1]}</span>
              <span className="deck-remaining">{left}</span>
            </div>
            {game.pyramid[String(lvl)].map((cid, slot) => (
              cid ? (
                <DuelCard key={slot} card={cardsById[cid]}
                  selected={selCard?.id === cid}
                  affordable={canAffordCard(cardsById[cid], me, cardsById)}
                  needsGold={goldNeeded(cardsById[cid]?.cost || {}, me?.tokens, myBonuses) > 0}
                  onClick={() => pyramidCardClick(cid, lvl, slot)} />
              ) : (
                <div key={slot} className="card-slot" />
              )
            ))}
          </div>
        );
      })}
    </div>
  );

  const renderBoard = () => (
    <div className="duel-panel duel-board-wrap">
      <div className="duel-board-meta">
        <Scroll n={game.privileges_board} title="Privileges available above the board" />
        <DuelBag count={game.bag_count} />
        <span className="duel-victory-chip" title="Win by any: 20 points · 10 crowns · 10 points in one color">
          20 ★ &nbsp;|&nbsp; 10 ♛ &nbsp;|&nbsp; 10 ★ one color
        </span>
      </div>
      <div className="duel-board">
        {/* Refill order: centre -> outward along the printed spiral */}
        {spiralPts.length > 1 && (
          <svg className="duel-spiral" viewBox={`0 0 ${BOARD_SPAN} ${BOARD_SPAN}`} aria-hidden="true">
            <polyline className="path" points={spiralPts.map((p) => p.join(",")).join(" ")} />
            <circle className="start" cx={spiralPts[0][0]} cy={spiralPts[0][1]} r=".11" />
            <circle className="head" cx={spiralPts[spiralPts.length - 1][0]}
              cy={spiralPts[spiralPts.length - 1][1]} r=".07" />
          </svg>
        )}
        {game.board.map((tok, i) => {
          const sel = selCells.includes(i);
          const isMatch = pendingMine && pendKind === "take_same" && tok === pendCtx.color && (pendCtx.cells || []).includes(i);
          const cls = tok === "gold"
            ? (goldCell === i ? "goldarm" : myTurn && !pendingMine ? "" : "inert")
            : sel ? "sel" : isMatch ? "matchable" : "";
          const hidden = hiddenCells.has(i);   // token in flight from the bag — keep the cell empty until it lands
          return (
            <div key={i} className="duel-cell">
              {/* no `size`: the board's tokens scale with their cells via CSS */}
              {tok && <GemToken color={tok} size={null} dataCell={i} className={`${cls}${hidden ? " duel-refill-hidden" : ""}`.trim()} onClick={() => cellClick(i)} />}
              {!tok && <div data-cell={i} style={{ width: 1, height: 1 }} />}
            </div>
          );
        })}
      </div>
      <div className="duel-actionrow">
        {myTurn && !pendingMine && (
          <>
            {selCells.length > 0 && (
              <button className="btn btn-gold" onClick={submitTake} disabled={!lineOk(selCells, game.board)}>
                Take {selCells.length} token{selCells.length > 1 ? "s" : ""}
              </button>
            )}
            {selCard && (
              <button className="btn btn-gold" onClick={buyClicked} disabled={!selAffordable}
                title={selAffordable ? "Purchase the selected card" : "You can't afford this card"}>
                Buy card
              </button>
            )}
            {goldCell != null && <span className="duel-muted">Now pick a card or a deck to reserve…</span>}
            <button className="btn btn-outline" onClick={() => mv({ type: "replenish" })} disabled={!canReplenish}
              title={canReplenish ? "Refill the board from the bag (your opponent gains a Privilege)" : "Replenish unavailable"}>
              Replenish
            </button>
            {(selCells.length > 0 || goldCell != null || privArmed || selCard) && (
              <button className="btn btn-outline" onClick={() => { setSelCells([]); setGoldCell(null); setPrivArmed(false); setSelCard(null); }}>
                ✕
              </button>
            )}
          </>
        )}
        {!myTurn && !over && (
          <span className="duel-muted">{botThinking ? "Bot is thinking…" : `Waiting for ${names[oppId] || "opponent"}…`}</span>
        )}
        {pendingMine && pendKind === "take_same" && (
          <span className="duel-muted">Ability: take a {pendCtx.color} token — click one on the board (or <a href="#" onClick={(ev) => { ev.preventDefault(); mv({ type: "skip_pending" }); }}>skip</a>)</span>
        )}
      </div>
      <div className="duel-royals-hint" title="When a player reaches 3 crowns they claim a Royal, and a second one at 6 crowns.">
        Claim a Royal at <b>3</b> &amp; <b>6</b> {"♛"}
      </div>
      <div className="duel-royals-row">
        {Object.values(royals).map((r) => {
          const available = (game.royals_available || []).includes(r.id);
          const choosable = pendingMine && pendKind === "choose_royal" && available;
          return <RoyalCard key={r.id} royal={r} dim={!available}
            selected={choosable}
            onClick={choosable ? () => mv({ type: "choose_royal", royal_id: r.id }) : undefined} />;
        })}
      </div>
    </div>
  );

  // The log always renders from the LIVE game (so every row stays visible however far
  // back you rewind). With snapshots loaded, a row jumps the board to just after it —
  // snapshot.log_len is the log length at that board, so the first snapshot with
  // log_len > r is the board produced by row r.
  const snapForLogIndex = (r) =>
    replaySnapshots ? replaySnapshots.findIndex((s) => s.log_len > r) : -1;

  // Spender's log panel: a .panel-title "Log" over its .move-log — same rows
  // (turn | name | action) and the same review vocabulary (clickable / log-selected /
  // log-win / log-start).
  const renderLog = () => {
    const log = liveGame?.log || [];
    const shownLen = reviewing ? replaySnapshots[replayTurn].log_len : log.length;
    return (
      <div className="duel-panel log-panel">
        <div className="panel-title">Log</div>
        <div className="move-log">
          {over && (
            <LogEntry kind="win"
              action={`🏆 ${names[liveGame.winner] || liveGame.winner} won the game`} />
          )}
          {log.map((e, r) => ({ e, r })).reverse().slice(0, 150).map(({ e, r }) => {
            const target = snapForLogIndex(r);
            const navigable = target >= 0;
            const { name, action, card } = fmtLog(e, names, cardsById, royals);
            // Click a reserve/buy row to inspect its card (Spender's log-inspect). A reserve
            // from the DECK TOP is hidden info — the log strips its card_id, so `card` is
            // null; show a face-down back instead of leaking it (and force it even if a
            // future card_id ever leaks through). In review the click navigates instead.
            const blindReserve = e.type === "reserve" && e.from_deck;
            const peekCard = blindReserve ? { hidden: true, level: e.level } : card;
            const clickable = navigable || !!peekCard;
            return (
              <LogEntry key={r} turn={e.t} name={name} action={action}
                clickable={clickable}
                selected={reviewing && target === replayTurn}
                future={r >= shownLen}   /* moves after the board being shown, dimmed */
                onClick={navigable ? () => goToTurn(target) : (peekCard ? () => setModalCard(peekCard) : undefined)} />
            );
          })}
          {replaySnapshots && (
            <LogEntry kind="start" action="▶ Game started" clickable
              onClick={() => goToTurn(0)} />
          )}
          {!log.length && <div className="log-empty">No moves yet.</div>}
        </div>
      </div>
    );
  };

  // Describes the move that PRODUCED the board on screen (snapshot k came from move k).
  const renderReplayBar = () => {
    if (!replaySnapshots) return null;
    const n = replaySnapshots.length - 1;
    const s = replaySnapshots[replayTurn];
    // fmtLog returns {name, action} (Spender's log shape) — destructure it. It used to
    // return a formatted STRING, and this line still called .replace() on it, which
    // crashed the whole app the moment a review opened.
    const { name, action } = fmtLog(liveGame.log[s.log_len - 1] || {}, names, cardsById, royals);
    const label = replayTurn === 0
      ? "Game start"
      : `Move ${replayTurn} / ${n} · ${name || s.pid} · ${action}`;
    return (
      <div className="duel-replaybar">
        <button className="btn btn-outline" onClick={() => goToTurn(replayTurn - 1)}
          disabled={replayTurn <= 0}>‹ Prev</button>
        <span className="duel-replay-label">{label}</span>
        <button className="btn btn-outline" onClick={() => goToTurn(replayTurn + 1)}
          disabled={replayTurn >= n}>Next ›</button>
        <button className="btn btn-outline" onClick={() => goToTurn(n)}
          disabled={replayTurn >= n}>Final</button>
      </div>
    );
  };

  // ── modals ──
  const renderModals = () => (
    <>
      {pendingMine && pendKind === "steal" && (
        <div className="duel-backdrop">
          <div className="duel-modal">
            <h3>Steal a token</h3>
            <p>Take 1 gem or pearl from {names[oppId] || "your opponent"}:</p>
            <div className="duel-modal-row">
              {(pendCtx.colors || []).map((c) => (
                <div key={c} style={{ cursor: "pointer" }} onClick={() => mv({ type: "steal", color: c })}>
                  <GemToken color={c} size={44} />
                </div>
              ))}
            </div>
            <div className="duel-overlay-note">
              <button className="btn btn-outline" onClick={() => mv({ type: "skip_pending" })}>Skip</button>
            </div>
          </div>
        </div>
      )}
      {pendingMine && pendKind === "choose_royal" && (
        <div className="duel-backdrop">
          <div className="duel-modal">
            <h3>Choose a Royal</h3>
            <p>Your crowns earn you a Royal card — pick one and resolve its ability:</p>
            <div className="duel-modal-row">
              {(game.royals_available || []).map((rid) => (
                <RoyalCard key={rid} royal={royals[rid]} selected onClick={() => mv({ type: "choose_royal", royal_id: rid })} />
              ))}
            </div>
          </div>
        </div>
      )}
      {pendingMine && pendKind === "discard" && (
        <div className="duel-backdrop">
          <div className="duel-modal">
            <h3>Too many tokens</h3>
            <p>You may keep at most 10 tokens — discard {pendCtx.excess || 1} (returned to the bag):</p>
            <div className="duel-modal-row">
              {TOKENS.map((t) => (me?.tokens?.[t] || 0) > 0 && (
                <div key={t} style={{ cursor: "pointer", textAlign: "center" }} onClick={() => mv({ type: "discard", color: t })}>
                  <GemToken color={t} size={44} />
                  <div className="duel-muted">{me.tokens[t]}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
      {wildPick && selCardData && (
        <div className="duel-backdrop" onClick={() => setWildPick(false)}>
          <div className="duel-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Attach the wild card</h3>
            <p>This card's bonus permanently becomes one of your colors (it counts toward that color's discounts and the 10-points-in-one-color win):</p>
            <div className="duel-modal-row">
              {wildEligible.map((c) => (
                <div key={c} style={{ cursor: "pointer", textAlign: "center" }} onClick={() => submitBuy(c)}>
                  <GemToken color={c} size={44} />
                  <div className="duel-muted">{myBonuses[c]} bonus{myBonuses[c] === 1 ? "" : "es"}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
      {/* Inspect a card from the log (a reserve/buy row). A deck-top reserve is shown
          face-down — its identity is hidden info. */}
      {modalCard && (
        <div className="duel-backdrop" onClick={() => setModalCard(null)}>
          <div className="duel-modal duel-cardmodal" onClick={(e) => e.stopPropagation()}>
            <div className="duel-modal-row">
              <DuelCard card={modalCard} />
            </div>
            {modalCard.hidden && <div className="duel-overlay-note">Reserved face-down from the deck — its card is hidden.</div>}
            <div className="duel-modal-row">
              <button className="btn btn-outline" onClick={() => setModalCard(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
      {confirmAbandon && (
        <div className="duel-backdrop" onClick={() => setConfirmAbandon(false)}>
          <div className="duel-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Abandon game?</h3>
            <p>Your opponent will be declared the winner.</p>
            <div className="duel-modal-row">
              <button className="btn btn-gold" onClick={abandonGame}>Abandon</button>
              <button className="btn btn-outline" onClick={() => setConfirmAbandon(false)}>Keep playing</button>
            </div>
          </div>
        </div>
      )}
      {/* The result popup is for a game you just FINISHED — not for one you opened
          from History (you already know how it ended; you came to inspect it). */}
      {over && !gameOverDismissed && !reviewOnly && (
        <div className="duel-backdrop">
          <div className="duel-modal" style={{ textAlign: "center" }}>
            <h3>{"♛"} {names[liveGame.winner] || liveGame.winner} wins!</h3>
            <div className="duel-gameover-badge">{WIN_DESC[liveGame.win_condition] || ""}{liveGame.win_color ? ` (${liveGame.win_color})` : ""}</div>
            <p className="duel-muted">Final score {pointsOf(liveGame.players[liveGame.order[0]], cardsById, royals)} – {pointsOf(liveGame.players[liveGame.order[1]], cardsById, royals)} ({names[liveGame.order[0]]} vs {names[liveGame.order[1]]})</p>
            <div className="duel-modal-row">
              <button className="btn btn-outline" onClick={() => { setGameOverDismissed(true); enterReview(roomId, true); }}>
                Review game
              </button>
              <button className="btn btn-gold" onClick={() => {
                try {
                  if (localStorage.getItem("duel_roomId") === roomId) localStorage.removeItem("duel_roomId");
                } catch {}
                leaveToLobby();
              }}>Back to lobby</button>
            </div>
          </div>
        </div>
      )}
      {showRules && (
        <div className="duel-backdrop" onClick={() => setShowRules(false)}>
          <div className="duel-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 640, maxHeight: "80vh", overflowY: "auto" }}>
            <h3>How to play</h3>
            <p><b>Win</b> by any of: <b>20 prestige points</b>, <b>10 crowns</b>, or <b>10 points on cards of one color</b>.</p>
            <p><b>On your turn</b> — optionally first (in this order): spend <b>Privileges</b> ({"⚜"}) to take 1 gem/pearl each, and/or <b>Replenish</b> the board from the bag (your opponent gains a Privilege). Then do ONE of:</p>
            <p>• <b>Take up to 3 tokens</b> in an unbroken straight line (any direction, no gold). Taking 3 of a color or 2 pearls hands your opponent a Privilege.<br />
              • <b>Take 1 gold + reserve a card</b> (click a gold token, then a face-up card or a deck). Reserves are secret; max 3.<br />
              • <b>Purchase a card</b> from the pyramid or your reserve. Gold is a wild. Spent tokens go back in the bag.</p>
            <p><b>Cards</b> give permanent bonuses (discounts), points, crowns, and abilities: {ABILITY_GLYPH.again} another turn,{" "}
              {/* take_same has no text glyph — it's a circle in the takeable gem's color */}
              <span className="card-ability" style={{ position: "static", display: "inline-flex" }}>
                +<span className="card-ability-gem" style={{ background: GEM_HEX.green }} />
              </span>{" "}
              take a token of that card's color, {ABILITY_GLYPH.privilege} take a Privilege, {ABILITY_GLYPH.steal} steal a token.
              Rainbow (wild) cards attach to a color you already own and count as it from then on.</p>
            <p><b>Crowns:</b> at 3 and again at 6 crowns, claim a Royal card. <b>Hand limit:</b> 10 tokens at end of turn.</p>
            <div className="duel-modal-row"><button className="btn btn-gold" onClick={() => setShowRules(false)}>Close</button></div>
          </div>
        </div>
      )}
    </>
  );

  // ── screens ──
  if (screen === "lobby") {
    const activeMine = myGames.filter((g) => g.status === "playing");
    const savedRid = (() => { try { return localStorage.getItem("duel_roomId"); } catch { return null; } })();
    const savedTok = (() => { try { return savedRid ? localStorage.getItem(`duel_token_${savedRid}_${myId}`) : null; } catch { return null; } })();
    const savedListed = savedRid && (openGames.some((g) => g.id === savedRid) || myGames.some((g) => g.id === savedRid));
    return (
      <div className="app duel" style={{ "--lby-accent": "#bf6fd0" }}>
        <style>{duelStyles}</style>
        <LobbyHeader
          onBack={onExit}
          title="Spender Duel"
          user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : null}
        />
        <LobbyCreateRow
          onCreate={() => setShowCreateModal(true)}
          onJoin={(code) => joinGame(code)}
          onRefresh={fetchGames}
          refreshing={loadingGames} />

        {showCreateModal && (
          <CreateModal title="New Game" onClose={() => setShowCreateModal(false)}>
            <CmRow label="Opponent">
              <CmSeg value={createOpp} onChange={setCreateOpp} options={[
                { value: "friend", label: "VS Friend", title: "Head-to-head — one friend joins from the lobby (or your room code)" },
                { value: "ai", label: "VS AI", title: "Starts instantly against the bot" },
              ]} />
            </CmRow>
            {createOpp === "ai" ? (
              <CmRow label="AI Difficulty">
                <CmSeg value={createDiff} onChange={setCreateDiff}
                  options={BOT_TIERS.map((t) => ({ value: t.id, label: t.name }))} />
              </CmRow>
            ) : (
              <span className="cm-hint">Duel is head-to-head — one friend joins from the lobby.</span>
            )}
            <div className="cm-footer">
              <span className="cm-summary">
                Creating: <b>{createOpp === "ai" ? `${TIER_NAME[createDiff] || createDiff} bot` : "vs Friend"}</b>
              </span>
              <button type="button" className="cm-create"
                onClick={() => createGame(createOpp === "ai", createDiff)}>
                Create Game
              </button>
            </div>
          </CreateModal>
        )}
        {/* Mobile-only tab bar (mirrors Spender): the three columns can't fit side by side
            on a phone, so pick ONE section to show. Hidden on wide screens (CSS). */}
        <div className="duel-lobby-tabs" role="tablist">
          {[
            ["open", "Open", openGames.length],
            ["active", "Active", activeMine.length],
            ["history", "History", history.length],
          ].map(([key, label, count]) => (
            <button key={key} type="button" role="tab" aria-selected={lobbyTab === key}
              className={`duel-lobby-tab${lobbyTab === key ? " sel" : ""}`}
              onClick={() => setLobbyTab(key)}>
              {label}{count > 0 ? <span className="duel-lobby-tab-count">{count}</span> : null}
            </button>
          ))}
        </div>
        <div className={`duel-lobby-cols tab-${lobbyTab}`}>
          <div className="duel-section open-section">
            <LobbySectionHd title="Open Games" />
            {openGames.length === 0 && <div className="lby-empty">No open games. Create one!</div>}
            {openGames.map((g) => (
              <div className="lby-card" key={g.id}>
                <div className="lby-card-info">
                  <div className="lby-card-title">{g.host_name || "Player"}'s game</div>
                  <div className="lby-card-meta">{g.id} · {timeAgo(g.created_at)}</div>
                </div>
                <div className="lby-card-actions">
                  {g.host_id === myId
                    ? (<>
                        <button className="btn btn-outline" onClick={() => resumeGame(g.id)}>Return</button>
                        <button className="btn btn-outline" onClick={() => cancelGame(g.id)}>Cancel</button>
                      </>)
                    : <button className="btn btn-gold" onClick={() => joinGame(g.id)}>Join</button>}
                </div>
              </div>
            ))}
          </div>
          <div className="duel-section active-section">
            <LobbySectionHd title="Active Games" />
            {savedRid && savedTok && !savedListed && activeMine.length === 0 && (
              <div className="lby-card">
                <div className="lby-card-info">
                  <div className="lby-card-title">Game {savedRid}</div>
                  <div className="lby-card-meta">saved on this device</div>
                </div>
                <div className="lby-card-actions"><button className="btn btn-gold" onClick={() => resumeGame(savedRid)}>Resume</button></div>
              </div>
            )}
            {activeMine.length === 0 && !(savedRid && savedTok && !savedListed) && <div className="lby-empty">No games in progress.</div>}
            {activeMine.map((g) => (
              <div className="lby-card" key={g.id}>
                <div className="lby-card-info">
                  <div className="lby-card-title">{g.player1_name || "?"} vs {g.player2_name || "?"}</div>
                  <div className="lby-card-meta">{timeAgo(g.updated_at)}</div>
                </div>
                <div className="lby-card-actions">
                  {g.your_turn ? <TurnBadge mine>Your turn</TurnBadge> : <TurnBadge>Their turn</TurnBadge>}
                  <button className="btn btn-gold" onClick={() => resumeGame(g.id)}>Resume</button>
                </div>
              </div>
            ))}
          </div>
          <div className="duel-section history-section">
            <LobbySectionHd title="History" />
            {history.length === 0 && <div className="lby-empty">{authUser ? "No finished games yet." : "Log in to keep game history."}</div>}
            {history.map((g) => (
              <div className="lby-card" key={g.id}>
                <div className="lby-card-info">
                  <div className="lby-card-title">
                    <span className={`hist-result ${g.you_won ? "won" : "lost"}`}>{g.you_won ? "Won" : "Lost"}</span>
                    <span className="hist-scores"> vs {g.opp_name} <span className="hist-score-num">{g.your_score ?? "?"}-{g.opp_score ?? "?"}</span></span>
                  </div>
                  <div className="lby-card-meta">{WIN_DESC[g.win_condition] ? WIN_DESC[g.win_condition] + " · " : ""}{timeAgo(g.updated_at)}</div>
                </div>
                <div className="lby-card-actions"><button className="btn btn-outline" onClick={() => enterReview(g.id)}>Review</button></div>
              </div>
            ))}
          </div>
        </div>
        {toast && <div className="duel-toast">{toast}</div>}
        {renderModals()}
      </div>
    );
  }

  if (screen === "waiting") {
    const isHost = roomData?.host === myId;
    const nPlayers = Object.keys(names).length;
    return (
      <div className="app duel">
        <style>{duelStyles}</style>
        <div className="duel-waiting">
          <h1 className="duel-title">Spender Duel</h1>
          <p>Share this code with a friend:</p>
          <div className="duel-code">{roomId}</div>
          <p className="duel-muted">{Object.values(names).join(" · ") || "…"}</p>
          {isHost && nPlayers >= 2 && <button className="btn btn-gold" onClick={() => send({ action: "start" })}>Start Game</button>}
          {isHost && nPlayers < 2 && <p className="duel-muted">Waiting for an opponent to join…</p>}
          <div style={{ marginTop: 18 }}>
            <button className="btn btn-outline" onClick={leaveToLobby}>{"←"} Back to lobby</button>
          </div>
        </div>
        {toast && <div className="duel-toast">{toast}</div>}
      </div>
    );
  }

  // game screen
  if (!game || !catalog) {
    return (
      <div className="app duel">
        <style>{duelStyles}</style>
        <div className="duel-waiting"><p className="duel-muted">Loading game…</p></div>
      </div>
    );
  }

  return (
    <div className="app duel duel-gamescreen" style={{ "--lby-accent": "#bf6fd0" }}>
      <style>{duelStyles}</style>
      {reconnecting && !connected && !reviewOnly && <div className="duel-reconnbar">Reconnecting…</div>}
      <div className="duel-topbar">
        <GameMenu items={[
          { label: "Return to menu", icon: "←", onClick: leaveToLobby },
          { label: "View rules", icon: "📖", onClick: () => setShowRules(true) },
          // Abandon only exists for a LIVE game you're still playing.
          (!over && !reviewOnly && !replaySnapshots) && { label: "Abandon game", icon: "⚑", danger: true, onClick: () => setConfirmAbandon(true) },
        ]} />
        <div className="spacer" />
        <h1 className="duel-title">Spender Duel</h1>
        {replaySnapshots && <span className="duel-review-badge">Review</span>}
        <div className="spacer" />
        {replaySnapshots && !reviewOnly
          ? <button className="btn btn-outline" onClick={exitReview}>Exit review</button>
          : <div style={{ width: 40 }} />}
      </div>
      {renderReplayBar()}
      <div className="duel-cols">
        <div className="duel-col-cards">{renderPyramid()}</div>
        <div className="duel-col-board">{renderBoard()}</div>
        <div className="duel-col-side">
          {oppId && renderPlayer(oppId, false)}
          {me && renderPlayer(myId, true)}
        </div>
        <div className="duel-col-log">{renderLog()}</div>
      </div>
      <div className="duel-fly-layer">
        {flyers.map((f) => (
          <div key={f.id} className="duel-flyer"
            style={{ left: f.left, top: f.top, "--dx": `${f.dx}px`, "--dy": `${f.dy}px`, "--s0": 1, "--s1": 0.55 }}>
            {f.color
              ? <GemToken color={f.color} size={f.size} />
              : <div className="card card-small" style={{ cursor: "default" }} />}
          </div>
        ))}
        {refillFlyers.map((f) => (
          <div key={f.id} className="duel-flyer-in"
            style={{ left: f.left, top: f.top, width: f.size, height: f.size,
              "--dx": `${f.dx}px`, "--dy": `${f.dy}px`,
              animationDelay: `${f.delay}ms`, animationDuration: `${f.dur}ms` }}>
            <GemToken color={f.color} size={f.size} />
          </div>
        ))}
      </div>
      {toast && <div className="duel-toast">{toast}</div>}
      {renderModals()}
    </div>
  );
}
