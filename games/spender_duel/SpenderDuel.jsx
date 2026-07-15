import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { baseCss } from "../../shared/theme.js";

// ─── Config ────────────────────────────────────────────────────────────────
const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const DUEL_WS = WS_RAW.replace(/\/ws$/, "/duel/ws");
const DUEL_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/duel");

const COLORS = ["white", "blue", "green", "red", "black"];
const TOKENS = [...COLORS, "pearl", "gold"];
const GEM_HEX = {
  white: "#ddd4be", blue: "#4257ff", green: "#3f9c2e", red: "#dc4040",
  black: "#15151a", pearl: "#e8c0d4", gold: "#f5c842",
};
const GEM_LABELS = {
  white: "Diamond", blue: "Sapphire", green: "Emerald", red: "Ruby",
  black: "Onyx", pearl: "Pearl", gold: "Gold",
};
const ABILITY_GLYPH = { again: "↻", take_same: "+◆", privilege: "⚜", steal: "✋" };
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
// Bot tiers (wire ids match main.AI_DIFFICULTIES). Easy = the trivial random-legal
// bot; Normal/Hard = determinized MCTS at different budgets.
const BOT_TIERS = [
  { id: "easy", name: "Easy", desc: "Plays legally, barely plans" },
  { id: "normal", name: "Normal", desc: "Thinks a little, makes mistakes" },
  { id: "hard", name: "Hard", desc: "Searches properly — a real fight" },
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

// ─── Small components ───────────────────────────────────────────────────────
// `size` omitted => the token is sized by CSS instead of inline styles. The board
// needs that: inline width/height would beat the stylesheet and freeze the tokens
// while their cells scale with the column.
function Token({ color, size, onClick, className = "", dataCell, title }) {
  const dark = color === "white" || color === "gold" || color === "pearl";
  const style = { background: GEM_HEX[color], color: dark ? "#333" : "#fff" };
  if (size) { style.width = size; style.height = size; style.fontSize = size * 0.42; }
  return (
    <div className={`duel-token ${className}`} data-cell={dataCell} title={title || GEM_LABELS[color]}
      onClick={onClick} style={style}>
      {color === "gold" ? "★" : color === "pearl" ? "●" : color[0].toUpperCase()}
    </div>
  );
}

function BonusSwatch({ card, asColor }) {
  if (card.bonus === "wild") {
    const bg = asColor ? GEM_HEX[asColor] : "linear-gradient(135deg,#999 0%,#ddd 50%,#888 100%)";
    return <div className="duel-bonus wild" style={{ background: bg }} title={asColor ? `Wild bonus (as ${asColor})` : "Wild bonus — attaches to one of your colors"} />;
  }
  if (!card.bonus) return null;
  return (
    <div className="duel-bonus-wrap" title={`+${card.bonus_count} ${card.bonus} bonus`}>
      <div className="duel-bonus" style={{ background: GEM_HEX[card.bonus] }} />
      {card.bonus_count === 2 && <div className="duel-bonus dbl" style={{ background: GEM_HEX[card.bonus] }} />}
    </div>
  );
}

function DuelCard({ card, asColor, selected, affordable, needsGold, dim, onClick, small }) {
  if (!card) return <div className={`duel-card empty${small ? " small" : ""}`} />;
  return (
    <div className={`duel-card${small ? " small" : ""}${selected ? " selected" : ""}${affordable ? (needsGold ? " affordable-gold" : " affordable") : ""}${dim ? " dim" : ""}`}
      onClick={onClick}>
      <div className="duel-card-top">
        <span className={`duel-card-pts${card.points ? "" : " zero"}`}>{card.points || ""}</span>
        {card.crowns > 0 && <span className="duel-card-crowns" title={`${card.crowns} crown${card.crowns > 1 ? "s" : ""}`}>{"♛".repeat(card.crowns)}</span>}
        <BonusSwatch card={card} asColor={asColor} />
      </div>
      {card.ability && (
        <div className="duel-card-abil" title={ABILITY_DESC[card.ability]}>{ABILITY_GLYPH[card.ability]}</div>
      )}
      {/* Cost is TWO explicit columns: gems stack in the first, the pearl always sits
          in the second. (It used to be one wrapping column, so the pearl only landed
          in column 2 when 3+ gems happened to overflow it — its position moved from
          card to card.) */}
      <div className="duel-card-cost">
        <div className="duel-cost-col">
          {Object.entries(card.cost).map(([c, n]) => c !== "pearl" && n > 0 && (
            <div key={c} className="duel-cost-row">
              <div className="duel-cost-gem" style={{ background: GEM_HEX[c] }} />
              <span>{n}</span>
            </div>
          ))}
        </div>
        {card.cost.pearl > 0 && (
          <div className="duel-cost-col">
            <div className="duel-cost-row">
              <div className="duel-cost-gem pearl" style={{ background: GEM_HEX.pearl }} />
              <span>{card.cost.pearl}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function CardBack({ level }) {
  return (
    <div className="duel-card small back">
      <span className="duel-back-lvl">{["I", "II", "III"][(level || 1) - 1]}</span>
      <span className="duel-back-label">Reserved</span>
    </div>
  );
}

function RoyalCard({ royal, dim, onClick, selected }) {
  return (
    <div className={`duel-royal${dim ? " dim" : ""}${selected ? " selected" : ""}`} onClick={onClick}
      title={royal.ability ? ABILITY_DESC[royal.ability] : "No ability"}>
      <span className="duel-royal-crown">{"♛"}</span>
      <span className="duel-royal-pts">{royal.points}</span>
      {royal.ability && <span className="duel-royal-abil">{ABILITY_GLYPH[royal.ability]}</span>}
    </div>
  );
}

function Scroll({ n, armed, onClick, title }) {
  return (
    <div className={`duel-scrolls${armed ? " armed" : ""}${onClick ? " clickable" : ""}`} onClick={onClick} title={title}>
      {Array.from({ length: 3 }, (_, i) => (
        <span key={i} className={`duel-scroll${i < n ? " full" : ""}`}>{"⚜"}</span>
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
.duel{margin:0 auto;padding:0 14px 24px;font-family:'Crimson Pro','Crimson Fallback',serif}
.duel h1,.duel h2,.duel h3{font-family:'Cinzel','Cinzel Fallback',serif}
.duel-topbar{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--line,#3a332a);margin-bottom:14px}
.duel-topbar .spacer{flex:1}
.duel-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.5rem;letter-spacing:.06em;margin:0}
.duel-muted{opacity:.65;font-size:.95rem}
.duel-toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#2b2117;color:#f4e9d4;border:1px solid #6b5836;padding:10px 18px;border-radius:8px;z-index:200;box-shadow:0 6px 18px rgba(0,0,0,.5)}
.duel-reconnbar{position:fixed;top:0;left:0;right:0;background:#6b3320;color:#ffe;text-align:center;padding:5px;z-index:210;font-size:.9rem}

/* lobby */
.duel-lobby-cols{display:grid;grid-template-columns:1fr 1fr 320px;gap:18px;align-items:start}
.duel-section h3{margin:4px 0 10px;font-size:1.05rem;opacity:.9}
.duel-gamecard{border:1px solid var(--line,#3a332a);border-radius:10px;padding:10px 14px;margin-bottom:10px;display:flex;align-items:center;gap:10px;background:var(--surface,#1b1712)}
.duel-gamecard .grow{flex:1;min-width:0}
.duel-create-row{display:flex;gap:10px;align-items:center;justify-content:center;margin:6px 0 20px;flex-wrap:wrap}
/* The bot-tier picker FLOATS (position:absolute) rather than revealing inline —
   an inline reveal shifts the whole lobby down when it opens (Spender's lesson). */
.duel-pick-wrap{position:relative}
.duel-picker{position:absolute;top:calc(100% + 6px);left:50%;transform:translateX(-50%);z-index:60;background:#241d13;border:1px solid #6b5836;border-radius:10px;padding:6px;display:flex;flex-direction:column;gap:4px;min-width:190px;box-shadow:0 8px 24px rgba(0,0,0,.5)}
.duel-picker button{white-space:nowrap;text-align:left}
.duel-picker .sub{display:block;font-size:.72rem;opacity:.6}
.duel-turnbadge{font-size:.78rem;padding:2px 8px;border-radius:999px;background:#3f5f33;color:#dfeecf;white-space:nowrap}
.duel-theirbadge{font-size:.78rem;padding:2px 8px;border-radius:999px;background:#4a4136;color:#d8ccb8;white-space:nowrap}

/* game columns: the CARDS column is the only 1fr, so all spare width goes to it —
   the board is a fixed 5x5 grid and the player/moves rail is capped, neither needs
   the room. (Previously the rail was the 1fr and swallowed everything.) */
.duel-cols{display:grid;grid-template-columns:minmax(420px,1.5fr) minmax(360px,1fr) minmax(260px,380px);gap:18px;align-items:start}
.duel-panel{background:var(--surface,#1b1712);border:1px solid var(--line,#3a332a);border-radius:12px;padding:12px}

/* pyramid */
/* Left-aligned, NOT centered: the rows hold different card counts (5/4/3), so centering
   staggers the deck stubs instead of keeping them in one tidy column. The cards scale to
   fill the box anyway, so there's little slack left to distribute. */
.duel-pyr-row{display:flex;gap:6px;margin-bottom:8px;align-items:stretch}
.duel-deck{width:64px;min-height:92px;border:2px dashed #57493a;border-radius:8px;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#a08d6e;flex:0 0 auto}
.duel-deck.clickable{cursor:pointer;border-color:#f5c842}
.duel-deck.clickable:hover{background:#2a2318}
.duel-deck .lvl{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.05rem}
.duel-deck .cnt{font-size:.8rem;opacity:.8}

/* cards */
/* Pyramid cards GROW into the cards column's spare width. The column is a container,
   so each card sizes off the real column width: subtract the deck (64) + the 5 flex
   gaps (30) + the panel padding (24) = 118, then split across the widest row's 5
   cards. All three rows therefore share ONE card size (sizing per-row with flex:1
   would make L3's 3 cards wider than L1's 5). Inner text scales off --dcw with the
   ratios measured from the 66px baseline, so a bigger card isn't just empty space. */
.duel-col-cards{container-type:inline-size}
.duel-col-cards .duel-card{
  /* Floor 44, not 58: on a ~390px phone the widest row (deck + 5 cards + gaps) must
     still fit, and a 58 floor forced a horizontal overflow of the whole page. */
  --dcw:clamp(44px, calc((100cqw - 118px) / 5), 200px);
  width:var(--dcw);height:calc(var(--dcw) * 1.424);      /* the 66x94 aspect */
  padding:calc(var(--dcw) * 0.076);
}
.duel-col-cards .duel-card-pts{font-size:calc(var(--dcw) * 0.279)}
.duel-col-cards .duel-card-crowns{font-size:calc(var(--dcw) * 0.174)}
.duel-col-cards .duel-bonus{width:calc(var(--dcw) * 0.212);height:calc(var(--dcw) * 0.212)}
.duel-col-cards .duel-card-abil{font-size:calc(var(--dcw) * 0.174);top:calc(var(--dcw) * 0.39);right:calc(var(--dcw) * 0.076)}
.duel-col-cards .duel-card-cost{bottom:calc(var(--dcw) * 0.076);left:calc(var(--dcw) * 0.076)}
.duel-col-cards .duel-cost-row{font-size:calc(var(--dcw) * 0.179)}
.duel-col-cards .duel-cost-gem{width:calc(var(--dcw) * 0.167);height:calc(var(--dcw) * 0.167)}
.duel-col-cards .duel-deck{min-height:calc(var(--dcw, 66px) * 1.424)}
.duel-card{position:relative;width:66px;height:94px;background:linear-gradient(160deg,#2e2417,#241c12);border:1px solid #57493a;border-radius:8px;padding:5px;cursor:pointer;flex:0 0 auto;transition:transform .12s, box-shadow .12s}
.duel-card:hover{transform:translateY(-2px)}
.duel-card.small{width:58px;height:82px}
.duel-card.empty{background:none;border:2px dashed #3a3128;cursor:default}
.duel-card.empty:hover{transform:none}
.duel-card.dim{opacity:.45;cursor:default}
.duel-card.selected{box-shadow:0 0 0 2px #f5c842, 0 4px 14px rgba(245,200,66,.35)}
.duel-card.affordable{box-shadow:0 0 0 1px #7dc36b}
.duel-card.affordable-gold{box-shadow:0 0 0 1px #c9a53f}
.duel-card.selected.affordable,.duel-card.selected.affordable-gold{box-shadow:0 0 0 2px #f5c842, 0 4px 14px rgba(245,200,66,.35)}
.duel-card.back{background:repeating-linear-gradient(45deg,#31261a,#31261a 6px,#2a2016 6px,#2a2016 12px);display:flex;flex-direction:column;align-items:center;justify-content:center;cursor:default}
.duel-card.back:hover{transform:none}
.duel-back-lvl{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.1rem;color:#c9b088}
.duel-back-label{font-size:.6rem;opacity:.6;letter-spacing:.08em;text-transform:uppercase}
.duel-card-top{display:flex;align-items:flex-start;gap:3px}
.duel-card-pts{font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;font-size:1.15rem;color:#f4e9d4;line-height:1}
.duel-card-pts.zero{visibility:hidden}
.duel-card-crowns{color:#f5c842;font-size:.72rem;letter-spacing:-2px;margin-top:1px}
.duel-bonus-wrap{margin-left:auto;display:flex;gap:2px}
.duel-bonus{width:14px;height:14px;border-radius:4px;border:1px solid rgba(255,255,255,.35);margin-left:auto}
.duel-bonus.dbl{margin-left:0}
.duel-bonus.wild{border-style:dashed}
.duel-card-abil{position:absolute;top:26px;right:5px;font-size:.72rem;color:#e8d9b8;background:#4a3b26;border-radius:4px;padding:0 3px;line-height:1.35}
/* Two fixed columns bottom-left: gems | pearl. Column 2 exists only when the card
   costs a pearl, and the pearl is ALWAYS there — never mixed into the gem stack. */
.duel-card-cost{position:absolute;bottom:5px;left:5px;right:5px;display:flex;flex-direction:row;align-items:flex-end;gap:6px}
.duel-cost-col{display:flex;flex-direction:column-reverse;gap:1px}
.duel-cost-row{display:flex;align-items:center;gap:3px;font-size:.74rem;color:#efe6d2}
.duel-cost-gem{width:11px;height:11px;border:1px solid rgba(255,255,255,.3);border-radius:3px;flex:0 0 auto}
.duel-cost-gem.pearl{border-radius:50%}

/* board */
/* The board is the other place spare width should go (it's the focal point), so its
   cells + tokens scale with the column: cqw minus the board padding (24), the panel
   padding (24) and the 4 gaps (28), split 5 ways. Tokens are CSS-sized here — see
   the note on Token — and sit at ~79% of their cell, matching the original 46/58. */
.duel-col-board{container-type:inline-size}
.duel-col-board .duel-board{--dcell:clamp(50px, calc((100cqw - 76px) / 5), 104px)}
.duel-board-wrap{display:flex;flex-direction:column;align-items:center;gap:10px}
.duel-board{--dcell:58px;display:grid;grid-template-columns:repeat(5,var(--dcell));grid-auto-rows:var(--dcell);gap:7px;padding:12px;background:#241d13;border:1px solid #57493a;border-radius:14px}
.duel-cell{display:flex;align-items:center;justify-content:center;border-radius:50%;border:2px dashed #3c3227}
.duel-cell .duel-token{width:calc(var(--dcell) * 0.79);height:calc(var(--dcell) * 0.79);font-size:calc(var(--dcell) * 0.33)}
.duel-cell .duel-token{cursor:pointer;transition:transform .1s, box-shadow .1s}
.duel-cell .duel-token:hover{transform:scale(1.08)}
.duel-cell .duel-token.sel{box-shadow:0 0 0 3px #f5c842}
.duel-cell .duel-token.goldarm{box-shadow:0 0 0 3px #f5c842;animation:duelPulse 1.1s infinite}
.duel-cell .duel-token.matchable{box-shadow:0 0 0 3px #7dc36b;animation:duelPulse 1.1s infinite}
.duel-cell .duel-token.inert{cursor:default}
@keyframes duelPulse{0%,100%{filter:brightness(1)}50%{filter:brightness(1.35)}}
.duel-token{display:flex;align-items:center;justify-content:center;border-radius:50%;font-weight:700;border:2px solid rgba(255,255,255,.25);box-shadow:inset 0 -3px 6px rgba(0,0,0,.35);user-select:none}
.duel-token.pearl-shape{border-radius:50%}
.duel-board-meta{display:flex;align-items:center;gap:16px;flex-wrap:wrap;justify-content:center}
.duel-actionrow{display:flex;gap:10px;align-items:center;min-height:40px;flex-wrap:wrap;justify-content:center}
.duel-royals-row{display:flex;gap:10px;justify-content:center}
.duel-royal{position:relative;width:66px;height:46px;background:linear-gradient(160deg,#3a2c45,#2c2135);border:1px solid #6b5a80;border-radius:8px;display:flex;align-items:center;justify-content:center;gap:6px}
.duel-royal.dim{opacity:.35}
.duel-royal.selected{box-shadow:0 0 0 2px #f5c842;cursor:pointer}
.duel-royal-crown{color:#f5c842;font-size:.85rem}
.duel-royal-pts{font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;color:#f4e9d4}
.duel-royal-abil{font-size:.8rem;color:#d9c8f0}
.duel-scrolls{display:inline-flex;gap:3px}
.duel-scroll{opacity:.22;font-size:1.15rem;color:#e8c86a}
.duel-scroll.full{opacity:1}
.duel-scrolls.clickable{cursor:pointer}
.duel-scrolls.armed .duel-scroll.full{animation:duelPulse 1.1s infinite}
.duel-victory-chip{font-size:.8rem;opacity:.75;border:1px solid #3a332a;border-radius:999px;padding:3px 10px}

/* player panels */
.duel-player{margin-bottom:14px}
.duel-player .hd{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.duel-player .hd .nm{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.02rem}
.duel-player.active{outline:2px solid #7a5f33;outline-offset:2px;border-radius:12px}
.duel-stat{font-size:.92rem;margin-left:auto;display:flex;gap:10px;align-items:center}
.duel-tokrow{display:flex;gap:5px;flex-wrap:wrap;margin:6px 0;min-height:34px}
.duel-tok{position:relative}
.duel-tok .n{position:absolute;bottom:-4px;right:-4px;background:#111;border:1px solid #555;color:#eee;border-radius:999px;font-size:.62rem;min-width:15px;height:15px;display:flex;align-items:center;justify-content:center;padding:0 2px}
.duel-bonusrow{display:flex;gap:5px;flex-wrap:wrap;margin:4px 0}
.duel-bonchip{display:flex;align-items:center;gap:4px;border:1px solid #3a332a;border-radius:6px;padding:2px 6px;font-size:.78rem}
.duel-bonchip .sw{width:11px;height:11px;border-radius:3px}
.duel-reserved-row{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap}
.duel-minis{display:flex;gap:4px;flex-wrap:wrap}

/* log */
.duel-log{max-height:340px;overflow-y:auto;scrollbar-gutter:stable;font-size:.88rem}
.duel-log-entry{padding:4px 2px;opacity:.9}
.duel-log-entry+.duel-log-entry{border-top:1px solid #2c261e}
.duel-log-entry.clickable{cursor:pointer}
.duel-log-entry.clickable:hover{background:#2c2418;color:#f5c842}
.duel-log-entry.future{opacity:.35}

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

/* flyers */
.duel-fly-layer{position:fixed;inset:0;pointer-events:none;z-index:180}
.duel-flyer{position:absolute;animation:duelFly .55s cubic-bezier(.3,.7,.4,1) forwards}
@keyframes duelFly{from{transform:translate(0,0) scale(var(--s0,1));opacity:1}to{transform:translate(var(--dx),var(--dy)) scale(var(--s1,.6));opacity:.15}}

/* waiting screen */
.duel-waiting{max-width:520px;margin:40px auto;text-align:center}
.duel-code{font-family:'Cinzel','Cinzel Fallback',serif;font-size:2.2rem;letter-spacing:.35em;margin:14px 0;color:#f5c842}

.duel-gameover-badge{font-size:1.05rem;margin:6px 0 2px;color:#f5c842}

@media(max-width:1120px){
  .duel-cols{grid-template-columns:1fr 1fr}
  .duel .duel-col-side{grid-column:1 / -1}
  .duel-lobby-cols{grid-template-columns:1fr}
}
@media(max-width:720px){
  .duel-cols{grid-template-columns:1fr}
  /* Menu + title + Rules + Abandon can't share one row on a phone — they used to run
     ~95px past the viewport and give the whole page a horizontal scrollbar. Wrap them
     and drop the flex spacers (which only exist to center the title on wide screens). */
  .duel-topbar{flex-wrap:wrap;justify-content:center;gap:8px}
  .duel-topbar .spacer{display:none}
  .duel-title{flex:1 0 100%;text-align:center;font-size:1.25rem}
  /* Cards + board cells size themselves from their column (container queries above),
     so phones need no explicit sizes — only a tighter board gap and a smaller deck
     stub. Hard-coding widths here would fight those clamps, not help them. */
  .duel .duel-board{gap:5px}
  .duel .duel-deck{width:52px;min-height:80px}
}
`;

// ─── Log formatting ─────────────────────────────────────────────────────────
function fmtLog(e, names, cardsById, royals) {
  const who = names[e.pid] || e.pid || "";
  const card = e.card_id ? cardsById[e.card_id] : null;
  const cardName = card
    ? `a level-${card.level}${card.bonus && card.bonus !== "wild" ? " " + card.bonus : card.bonus === "wild" ? " wild" : ""} card${card.points ? ` (${card.points} pts)` : ""}`
    : "a card";
  switch (e.type) {
    case "take": {
      const counts = {};
      (e.colors || []).forEach((c) => { counts[c] = (counts[c] || 0) + 1; });
      const s = Object.entries(counts).map(([c, n]) => (n > 1 ? `${n} ${c}` : c)).join(", ");
      return `${who} took ${s}${e.opp_privilege ? " (opponent gains a Privilege)" : ""}`;
    }
    case "use_privilege": return `${who} spent a Privilege for a ${e.color} token`;
    case "replenish": return `${who} replenished the board (${e.count})${e.opp_privilege ? " — opponent gains a Privilege" : ""}`;
    case "reserve": return e.from_deck
      ? `${who} took gold and reserved from the level-${e.level} deck`
      : `${who} took gold and reserved ${cardName}`;
    case "buy": return `${who} purchased ${cardName}${e.as_color ? ` (wild as ${e.as_color})` : ""}`;
    case "take_same": return `${who} took a bonus ${e.color} token`;
    case "steal": return `${who} stole a ${e.color} token`;
    case "privilege_gain": return `${who} gained a Privilege`;
    case "again": return `${who} earns another turn`;
    case "extra_turn": return `${who} takes an extra turn`;
    case "royal": return `${who} claimed a Royal (${e.points} pts)`;
    case "discard": return `${who} discarded a ${e.color} token`;
    case "skip_pending": return `${who} skipped (${e.kind})`;
    case "pass": return `${who} passed`;
    case "game_over": return `♛ ${who} wins — ${WIN_DESC[e.condition] || e.condition}${e.color ? ` (${e.color})` : ""}`;
    default: return `${who} ${e.type}`;
  }
}

// ─── Main component ─────────────────────────────────────────────────────────
export default function SpenderDuel({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");     // lobby | waiting | game
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [catalog, setCatalog] = useState(null);      // {cards, royals, colors}
  const [openGames, setOpenGames] = useState([]);
  const [myGames, setMyGames] = useState([]);
  const [history, setHistory] = useState([]);
  const [loadingGames, setLoadingGames] = useState(false);
  const [toast, setToast] = useState("");
  const [reconnecting, setReconnecting] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [showBotPicker, setShowBotPicker] = useState(false);
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
  const [flyers, setFlyers] = useState([]);
  const flyerSeq = useRef(0);
  const prevLogLen = useRef(0);
  const reconnTimer = useRef(null);
  const reconnTries = useRef(0);

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
  const boardHasEmpty = !!game && game.board.some((t) => t === null);
  const canReplenish = myTurn && !pendingMine && (game?.bag_count || 0) > 0 && boardHasEmpty && !replenished;
  const canUsePrivilege = myTurn && !pendingMine && (me?.privileges || 0) > 0 && !replenished
    && !!game && game.board.some((t) => t && t !== "gold");
  const pendKind = game?.pending_kind;
  const pendCtx = game?.pending?.ctx || {};

  // ── socket ──
  const handleMessage = useCallback((msg) => {
    if (msg.type === "error") { setToast(msg.message || "error"); return; }
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
      setScreen(inGame ? "game" : "waiting");
    } else if (msg.type === "room_update" && inGame && screen !== "game") {
      setScreen("game");
    }
  }, [myId, roomId, screen]);

  const { connected, connect, send, disconnect, socketReady } = useSocket(handleMessage);

  // static catalog (card data) once
  useEffect(() => {
    fetch(`${DUEL_HTTP}/catalog`).then((r) => r.json()).then((d) => { if (d.ok) setCatalog(d); }).catch(() => {});
  }, []);

  const fetchGames = useCallback(() => {
    setLoadingGames(true);
    fetch(`${DUEL_HTTP}/games`).then((r) => r.json()).then((d) => setOpenGames(d.games || []))
      .catch(() => {}).finally(() => setLoadingGames(false));
    if (authUser?.session_token) {
      const headers = { Authorization: `Bearer ${authUser.session_token}` };
      fetch(`${DUEL_HTTP}/games/mine`, { headers }).then((r) => r.json()).then((d) => setMyGames(d.games || [])).catch(() => {});
      fetch(`${DUEL_HTTP}/games/history`, { headers }).then((r) => r.json()).then((d) => setHistory(d.games || [])).catch(() => {});
    } else { setMyGames([]); setHistory([]); }
  }, [authUser]);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);

  // auto-resume a saved room on mount
  useEffect(() => {
    try {
      const rid = localStorage.getItem("duel_roomId");
      const tok = rid ? localStorage.getItem(`duel_token_${rid}_${myId}`) : null;
      if (rid && tok) {
        setRoomId(rid);
        connect(`${DUEL_WS}/${rid}/${myId}`, { action: "reconnect", token: tok });
      }
    } catch {}
    return () => disconnect();
  }, []); // eslint-disable-line

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
    if (!log) { prevLogLen.current = 0; return; }
    const prev = prevLogLen.current;
    prevLogLen.current = log.length;
    if (prev === 0 || log.length <= prev || log.length - prev > 6) return;  // initial load / reconnect catch-up
    const fresh = log.slice(prev);
    const rect = (sel) => { const el = document.querySelector(sel); return el ? el.getBoundingClientRect() : null; };
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
      const panel = rect(`[data-tokens="${e.pid}"]`);
      if (e.type === "take" && e.cells) {
        e.cells.forEach((cell, i) => mkTok(e.colors?.[i], rect(`[data-cell="${cell}"]`), panel));
      } else if ((e.type === "use_privilege" || e.type === "take_same") && e.cell != null) {
        mkTok(e.color, rect(`[data-cell="${e.cell}"]`), panel);
      } else if (e.type === "reserve" && e.gold_cell != null) {
        mkTok("gold", rect(`[data-cell="${e.gold_cell}"]`), panel);
      } else if (e.type === "steal") {
        const other = (liveGame.order || []).find((p) => p !== e.pid);
        mkTok(e.color, rect(`[data-tokens="${other}"]`), panel);
      } else if (e.type === "buy") {
        mkTok(null, rect("[data-pyramid]"), panel, 44);
      }
    }
    if (!add.length) return;
    setFlyers((f) => [...f, ...add]);
    const ids = new Set(add.map((a) => a.id));
    setTimeout(() => setFlyers((f) => f.filter((x) => !ids.has(x.id))), 620);
  }, [liveGame?.log?.length]); // eslint-disable-line

  // ── actions ──
  const mv = (move) => send({ action: "move", move });

  const createGame = (vsAi, difficulty) => {
    const rid = roomCode();
    setRoomId(rid);
    setRoomData(null);
    setShowBotPicker(false);
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
  const renderTokens = (p, pid) => (
    <div className="duel-tokrow" data-tokens={pid}>
      {TOKENS.map((t) => (p?.tokens?.[t] || 0) > 0 && (
        <div key={t} className="duel-tok">
          <Token color={t} size={30} />
          <span className="n">{p.tokens[t]}</span>
        </div>
      ))}
      {TOKENS.every((t) => !(p?.tokens?.[t])) && <span className="duel-muted">no tokens</span>}
    </div>
  );

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
          <span className="duel-stat">
            <span title="Prestige points">★ {pts}</span>
            <span title="Crowns" style={{ color: "#f5c842" }}>{"♛"} {crowns}</span>
          </span>
        </div>
        <Scroll n={p.privileges}
          armed={isMe && privArmed}
          onClick={isMe && canUsePrivilege ? () => { setPrivArmed(!privArmed); setGoldCell(null); setSelCells([]); setSelCard(null); } : undefined}
          title={isMe
            ? (canUsePrivilege ? "Use a Privilege: click here, then click a gem or pearl on the board" : `${p.privileges} Privilege${p.privileges === 1 ? "" : "s"}`)
            : `${p.privileges} Privilege${p.privileges === 1 ? "" : "s"}`} />
        {renderTokens(p, pid)}
        <div className="duel-bonusrow">
          {COLORS.map((c) => (bon[c] > 0 || cpts[c] > 0) && (
            <div key={c} className="duel-bonchip" title={`${bon[c]} ${c} bonus${bon[c] === 1 ? "" : "es"} · ${cpts[c]} pts in ${c} (win at 10)`}>
              <span className="sw" style={{ background: GEM_HEX[c] }} />
              <span>{bon[c]}</span>
              {cpts[c] > 0 && <span style={{ opacity: .7 }}>{"★"}{cpts[c]}</span>}
            </div>
          ))}
        </div>
        {(p.royals || []).length > 0 && (
          <div className="duel-minis">
            {p.royals.map((rid) => <RoyalCard key={rid} royal={royals[rid] || { points: "?" }} />)}
          </div>
        )}
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

  const renderPyramid = () => (
    <div className="duel-panel" data-pyramid>
      {[3, 2, 1].map((lvl) => (
        <div className="duel-pyr-row" key={lvl}>
          <div className={`duel-deck${goldCell != null && (game.deck_counts?.[String(lvl)] || 0) > 0 ? " clickable" : ""}`}
            onClick={() => deckClick(lvl)}
            title={goldCell != null ? "Reserve the top card of this deck (blind)" : `${game.deck_counts?.[String(lvl)] || 0} cards left`}>
            <span className="lvl">{["I", "II", "III"][lvl - 1]}</span>
            <span className="cnt">{game.deck_counts?.[String(lvl)] || 0}</span>
          </div>
          {game.pyramid[String(lvl)].map((cid, slot) => (
            <DuelCard key={slot} card={cid ? cardsById[cid] : null}
              selected={!!cid && selCard?.id === cid}
              affordable={!!cid && canAffordCard(cardsById[cid], me, cardsById)}
              needsGold={!!cid && goldNeeded(cardsById[cid]?.cost || {}, me?.tokens, myBonuses) > 0}
              onClick={cid ? () => pyramidCardClick(cid, lvl, slot) : undefined} />
          ))}
        </div>
      ))}
    </div>
  );

  const renderBoard = () => (
    <div className="duel-panel duel-board-wrap">
      <div className="duel-board-meta">
        <Scroll n={game.privileges_board} title="Privileges available above the board" />
        <span className="duel-muted" title="Tokens waiting in the bag">Bag: {game.bag_count}</span>
        <span className="duel-victory-chip" title="Win by any: 20 points · 10 crowns · 10 points in one color">
          20 ★ &nbsp;|&nbsp; 10 ♛ &nbsp;|&nbsp; 10 ★ one color
        </span>
      </div>
      <div className="duel-board">
        {game.board.map((tok, i) => {
          const sel = selCells.includes(i);
          const isMatch = pendingMine && pendKind === "take_same" && tok === pendCtx.color && (pendCtx.cells || []).includes(i);
          const cls = tok === "gold"
            ? (goldCell === i ? "goldarm" : myTurn && !pendingMine ? "" : "inert")
            : sel ? "sel" : isMatch ? "matchable" : "";
          return (
            <div key={i} className="duel-cell">
              {/* no `size`: the board's tokens scale with their cells via CSS */}
              {tok && <Token color={tok} dataCell={i} className={cls} onClick={() => cellClick(i)} />}
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
            {privArmed && <span className="duel-muted">Pick a gem or pearl to take with your Privilege…</span>}
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

  const renderLog = () => {
    const log = liveGame?.log || [];
    const shownLen = reviewing ? replaySnapshots[replayTurn].log_len : log.length;
    return (
      <div className="duel-panel">
        <h3 style={{ margin: "0 0 8px" }}>Moves</h3>
        <div className="duel-log">
          {log.map((e, r) => ({ e, r })).reverse().slice(0, 120).map(({ e, r }) => {
            const target = snapForLogIndex(r);
            const clickable = target >= 0;
            // dim the moves that hadn't happened yet on the board being shown
            const future = r >= shownLen;
            return (
              <div key={r}
                className={`duel-log-entry${clickable ? " clickable" : ""}${future ? " future" : ""}`}
                onClick={clickable ? () => goToTurn(target) : undefined}
                title={clickable ? "Jump to this move" : undefined}>
                {fmtLog(e, names, cardsById, royals)}
              </div>
            );
          })}
          {replaySnapshots && (
            <div className="duel-log-entry clickable" onClick={() => goToTurn(0)}
              title="Jump to the starting board">▶ Game started</div>
          )}
        </div>
      </div>
    );
  };

  // Describes the move that PRODUCED the board on screen (snapshot k came from move k).
  const renderReplayBar = () => {
    if (!replaySnapshots) return null;
    const n = replaySnapshots.length - 1;
    const s = replaySnapshots[replayTurn];
    const label = replayTurn === 0
      ? "Game start"
      : `Move ${replayTurn} / ${n} · ${names[s.pid] || s.pid} · ${fmtLog(
          liveGame.log[s.log_len - 1] || {}, names, cardsById, royals).replace(/^\S+\s/, "")}`;
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
                  <Token color={c} size={44} />
                </div>
              ))}
            </div>
            <div className="duel-overlay-note"><button className="btn btn-outline" onClick={() => mv({ type: "skip_pending" })}>Skip</button></div>
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
                <div key={t} className="duel-tok" style={{ cursor: "pointer" }} onClick={() => mv({ type: "discard", color: t })}>
                  <Token color={t} size={44} />
                  <span className="n">{me.tokens[t]}</span>
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
                  <Token color={c} size={44} />
                  <div className="duel-muted">{myBonuses[c]} bonus{myBonuses[c] === 1 ? "" : "es"}</div>
                </div>
              ))}
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
              <button className="btn btn-outline" onClick={() => setGameOverDismissed(true)}>View board</button>
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
            <p><b>Cards</b> give permanent bonuses (discounts), points, crowns, and abilities: {ABILITY_GLYPH.again} another turn, {ABILITY_GLYPH.take_same} take a matching token, {ABILITY_GLYPH.privilege} take a Privilege, {ABILITY_GLYPH.steal} steal a token. Grey (wild) cards attach to a color you own.</p>
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
      <div className="app duel">
        <style>{baseCss + css}</style>
        <div className="duel-topbar">
          <button className="btn btn-outline" onClick={onExit}>{"←"} Back</button>
          <div className="spacer" />
          <h1 className="duel-title">Spender Duel</h1>
          <div className="spacer" />
          <button className="btn btn-outline" onClick={() => setShowRules(true)}>How to Play</button>
        </div>
        <div className="duel-create-row">
          <button className="btn btn-gold" onClick={() => createGame(false)}>+ Create Game</button>
          <div className="duel-pick-wrap">
            <button className="btn btn-gold" onClick={() => setShowBotPicker((v) => !v)}>Play vs Bot ▾</button>
            {showBotPicker && (
              <div className="duel-picker">
                {BOT_TIERS.map((t) => (
                  <button key={t.id} className="btn btn-outline" onClick={() => createGame(true, t.id)}>
                    {t.name}<span className="sub">{t.desc}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <button className="btn btn-outline" onClick={fetchGames}>{loadingGames ? "…" : "↻"}</button>
        </div>
        <div className="duel-lobby-cols">
          <div className="duel-section">
            <h3>Open Games</h3>
            {openGames.length === 0 && <div className="duel-muted">No open games. Create one!</div>}
            {openGames.map((g) => (
              <div className="duel-gamecard" key={g.id}>
                <div className="grow">
                  <div>{g.host_name || "Player"}'s game</div>
                  <div className="duel-muted">{g.id} · {timeAgo(g.created_at)}</div>
                </div>
                {g.host_id === myId
                  ? (<>
                      <button className="btn btn-outline" onClick={() => resumeGame(g.id)}>Return</button>
                      <button className="btn btn-outline" onClick={() => cancelGame(g.id)}>Cancel</button>
                    </>)
                  : <button className="btn btn-gold" onClick={() => joinGame(g.id)}>Join</button>}
              </div>
            ))}
          </div>
          <div className="duel-section">
            <h3>Active Games</h3>
            {savedRid && savedTok && !savedListed && activeMine.length === 0 && (
              <div className="duel-gamecard">
                <div className="grow">
                  <div>Game {savedRid}</div>
                  <div className="duel-muted">saved on this device</div>
                </div>
                <button className="btn btn-gold" onClick={() => resumeGame(savedRid)}>Resume</button>
              </div>
            )}
            {activeMine.length === 0 && !(savedRid && savedTok && !savedListed) && <div className="duel-muted">No games in progress.</div>}
            {activeMine.map((g) => (
              <div className="duel-gamecard" key={g.id}>
                <div className="grow">
                  <div>{g.player1_name || "?"} vs {g.player2_name || "?"}</div>
                  <div className="duel-muted">{timeAgo(g.updated_at)}</div>
                </div>
                {g.your_turn ? <span className="duel-turnbadge">Your turn</span> : <span className="duel-theirbadge">Their turn</span>}
                <button className="btn btn-gold" onClick={() => resumeGame(g.id)}>Resume</button>
              </div>
            ))}
          </div>
          <div className="duel-section">
            <h3>History</h3>
            {history.length === 0 && <div className="duel-muted">{authUser ? "No finished games yet." : "Log in to keep game history."}</div>}
            {history.map((g) => (
              <div className="duel-gamecard" key={g.id}>
                <div className="grow">
                  <div>{g.you_won ? "Won" : "Lost"} vs {g.opp_name}</div>
                  <div className="duel-muted">{g.your_score ?? "?"}–{g.opp_score ?? "?"} · {WIN_DESC[g.win_condition] || ""} · {timeAgo(g.updated_at)}</div>
                </div>
                <button className="btn btn-outline" onClick={() => enterReview(g.id)}>Review</button>
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
        <style>{baseCss + css}</style>
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
        <style>{baseCss + css}</style>
        <div className="duel-waiting"><p className="duel-muted">Loading game…</p></div>
      </div>
    );
  }

  return (
    <div className="app duel">
      <style>{baseCss + css}</style>
      {reconnecting && !connected && !reviewOnly && <div className="duel-reconnbar">Reconnecting…</div>}
      <div className="duel-topbar">
        <button className="btn btn-outline" onClick={leaveToLobby}>{"←"} Menu</button>
        <div className="spacer" />
        <h1 className="duel-title">Spender Duel</h1>
        {replaySnapshots && <span className="duel-review-badge">Review</span>}
        <div className="spacer" />
        <button className="btn btn-outline" onClick={() => setShowRules(true)}>Rules</button>
        {/* Abandon only exists for a LIVE game you're still playing. */}
        {!over && !reviewOnly && !replaySnapshots && (
          <button className="btn btn-outline" onClick={() => setConfirmAbandon(true)}>Abandon</button>
        )}
        {replaySnapshots && !reviewOnly && (
          <button className="btn btn-outline" onClick={exitReview}>Exit review</button>
        )}
      </div>
      {renderReplayBar()}
      <div className="duel-cols">
        <div className="duel-col-cards">{renderPyramid()}</div>
        <div className="duel-col-board">{renderBoard()}</div>
        <div className="duel-col-side">
          {oppId && renderPlayer(oppId, false)}
          {me && renderPlayer(myId, true)}
          {renderLog()}
        </div>
      </div>
      <div className="duel-fly-layer">
        {flyers.map((f) => (
          <div key={f.id} className="duel-flyer"
            style={{ left: f.left, top: f.top, "--dx": `${f.dx}px`, "--dy": `${f.dy}px`, "--s0": 1, "--s1": 0.55 }}>
            {f.color
              ? <Token color={f.color} size={f.size} />
              : <div className="duel-card small" style={{ cursor: "default" }} />}
          </div>
        ))}
      </div>
      {toast && <div className="duel-toast">{toast}</div>}
      {renderModals()}
    </div>
  );
}
