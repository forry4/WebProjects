import { useState, useEffect, useLayoutEffect, useRef, useCallback, useMemo } from "react";
import { baseCss } from "../../shared/theme.js";
import {
  lobbyCss, LobbyHeader, LobbySectionHd, TurnBadge, GameMenu, gameMenuCss,
  readLobbyCache, writeLobbyCache, createModalCss, CreateModal, CmRow, CmSeg,
  LobbyCreateRow, lobbyCreateRowCss,
} from "../../shared/lobby.jsx";
// Only the shared CARD FRAME (sizing vars + .card chrome). Dontminion's card face
// is its own markup — no gems here, but the frame keeps all five games' cards the
// same physical object on screen.
import { splendorCardCss } from "../../shared/splendor.jsx";
import { parsePath, buildPath, pushPath, replacePath, subscribe } from "../../shared/router.js";

// CSS lives in the sibling .css file, imported `?inline` (a string injected by this
// component's own <style> tag) — NEVER a JS template literal (the documented
// stray-backtick blank-page footgun).
import _cssText from "./Dontminion.css?inline";

// ─── Config ────────────────────────────────────────────────────────────────
const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const DM_WS = WS_RAW.replace(/\/ws$/, "/dontminion/ws");
const DM_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/dontminion");

// The bot tiers OFFERED in the picker. The server still distinguishes more
// (main.AI_DIFFICULTIES also has plain `bigmoney`), but only two are worth
// surfacing: a barely-playing Random and the real opponent, Big Money+. Plain
// Big Money was dropped from the UI — it is a strictly weaker bmplus, so it
// only added a choice that no one should pick. A saved game still on `bigmoney`
// keeps working; the server just no longer offers it here.
//
// LABELS ARE SHORT ON PURPOSE. These render as a `cm-seg` sharing one row with
// the Bots counter (the side-by-side layout is what keeps the create modal
// inside its 148px budget), and `.cm-seg-btn` is `white-space:nowrap` inside an
// `overflow:hidden` track — a label too wide for its half of the track is
// CLIPPED, not wrapped. The full name rides along as the button's title.
const BOTS = [
  { id: "easy", name: "Random", title: "Random legal moves — barely plays" },
  { id: "bmplus", name: "Money+", title: "Big Money+ — reads the board for a terminal, knows how the game ends" },
];
// Display NAMES only. The SERVER decides which expansions exist (/catalog
// "expansions", from main.KNOWN_EXPANSIONS) and the picker is built from that,
// so a set the server ships without a label here still appears (under a
// title-cased id) instead of being silently unpickable.
const EXPANSIONS = [
  { id: "base", name: "Base Set" },
  { id: "intrigue", name: "Intrigue" },
  { id: "seaside", name: "Seaside" },
  { id: "prosperity", name: "Prosperity" },
  { id: "hinterlands", name: "Hinterlands" },
];
// Platinum/Colony slot into the basics row when the Prosperity setup rule
// put them in this game's supply
const basicsRowFor = (supply) => {
  const row = ["Copper", "Silver", "Gold"];
  if (supply && supply.Platinum != null) row.push("Platinum");
  row.push("Estate", "Duchy", "Province");
  if (supply && supply.Colony != null) row.push("Colony");
  row.push("Curse");
  return row;
};
const BASIC_ROW = ["Copper", "Silver", "Gold", "Estate", "Duchy", "Province", "Curse"];

// Kernel pseudo-card names (frames the engine owns, not real cards) → what the
// player reads. "__abilities" is the p23 §2 concurrency prompt: several of your
// own abilities triggered at once and YOU pick what resolves first.
const PSEUDO_CARDS = { __attack: "Attack", __abilities: "Choose what resolves first" };
const displayCard = (name) => PSEUDO_CARDS[name] || name;

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

// Card-face tinting by primary type (dual types show a split banner).
const TYPE_LABEL = {
  action: "Action", treasure: "Treasure", victory: "Victory", curse: "Curse",
  attack: "Attack", reaction: "Reaction", duration: "Duration",
};
const faceClass = (types) => {
  if (!types) return "";
  if (types.includes("curse")) return "dm-f-curse";
  if (types.includes("treasure")) return "dm-f-treasure";
  if (types.includes("victory")) return "dm-f-victory";
  return "dm-f-action";
};

// Right-click (desktop) / press-and-hold (touch) opens the card's detail modal,
// WHATEVER the plain click is wired to do — a card you can buy, play or pick is
// exactly the card you most want to read first, and its click is already taken.
//
// Android fires `contextmenu` on a long press, but iOS Safari does not (it runs
// its own selection callout instead), so touch gets a real timer rather than
// relying on the event. Both paths funnel through one `fired` flag: whichever
// wins, the other is a no-op and the tap that follows is swallowed, so holding a
// card can never also play it.
const LONG_PRESS_MS = 450;
const LONG_PRESS_SLOP = 10;      // finger drift still counted as a hold, not a scroll
function useCardInfoGesture(onInfo) {
  const timer = useRef(null);
  const fired = useRef(false);
  const from = useRef(null);
  const clear = useCallback(() => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
  }, []);
  useEffect(() => clear, [clear]);          // never leave a timer behind on unmount
  if (!onInfo) return {};
  const open = () => { clear(); fired.current = true; onInfo(); };
  return {
    onContextMenu: (e) => {
      e.preventDefault(); e.stopPropagation();   // no browser menu on a card
      if (!fired.current) open();
    },
    onPointerDown: (e) => {
      fired.current = false;                     // a fresh press re-arms the click
      if (e.pointerType === "mouse") return;     // right-click already covers a mouse
      from.current = { x: e.clientX, y: e.clientY };
      clear();
      timer.current = setTimeout(open, LONG_PRESS_MS);
    },
    onPointerMove: (e) => {
      if (!timer.current || !from.current) return;
      if (Math.abs(e.clientX - from.current.x) > LONG_PRESS_SLOP
        || Math.abs(e.clientY - from.current.y) > LONG_PRESS_SLOP) clear();   // they're scrolling
    },
    onPointerUp: clear,
    onPointerCancel: clear,
    onPointerLeave: clear,
    onClickCapture: (e) => {
      // the hold already answered — don't let the release ALSO play the card
      if (fired.current) { e.preventDefault(); e.stopPropagation(); fired.current = false; }
    },
  };
}

function DmCardFace({ name, card, onClick, onInfo, selected, disabled, highlight, small, badge }) {
  const types = card?.types || [];
  const infoGesture = useCardInfoGesture(onInfo);
  // A card that isn't actionable right now still answers a click with its
  // detail modal (onInfo) — nothing on the board is a dead click.
  const click = (!disabled && onClick) ? onClick : onInfo;
  const cls = ["card", "dm-card", faceClass(types),
    small ? "dm-card-small" : "",
    selected ? "dm-sel" : "", highlight ? "dm-hl" : "",
    disabled ? "dm-dis" : "", click ? "dm-clickable" : ""].filter(Boolean).join(" ");
  // long rules text shrinks to fit — the card itself NEVER grows
  const text = card?.text || "";
  const textCls = text.length > 200 ? " dm-text-xxl" : text.length > 130 ? " dm-text-xl"
    : text.length > 80 ? " dm-text-l" : "";
  return (
    <div className={cls} onClick={click} {...infoGesture}
      title={card ? `${name} (${card.cost}) — ${card.text}` : name}>
      {types.includes("attack") && <span className="dm-edge dm-edge-atk" />}
      {types.includes("reaction") && <span className="dm-edge dm-edge-rx" />}
      {types.includes("duration") && !types.includes("attack") && <span className="dm-edge dm-edge-dur" />}
      <FitText text={name} className="dm-card-name" />
      {!small && <div className={"dm-card-text" + textCls}>{text}</div>}
      {/* foot row: type lines bottom-LEFT, the cost coin bottom-RIGHT */}
      <div className="dm-card-foot">
        <div className="dm-types">
          {types.map((t) => <span key={t} className="dm-type">{TYPE_LABEL[t] || t}</span>)}
        </div>
        <span className="dm-cost">{card ? card.cost : ""}</span>
      </div>
      {badge != null && <span className="dm-card-badge">{badge}</span>}
    </div>
  );
}

// Button label that fits itself to the button's width (buttons themselves are
// capped at 100% of their box — never overflow it). One line if it fits; if it
// doesn't, the label WRAPS to a second row and the button grows to two rows
// rather than shrinking the text into illegibility or clipping it. Minion's
// "discard your hand, +4 Cards, …" option is the case that forced this: no font
// size makes that fit one row of a prompt button.
const FIT_MIN_PX = 9;
function FitLabel({ children }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.fontSize = "";
    el.classList.remove("dm-fitlabel-wrap");
    if (el.scrollWidth <= el.clientWidth + 1) return;      // fits on one row
    // Two rows. Shrink only as far as two rows actually need — most labels
    // wrap at full size and never lose a pixel of type.
    el.classList.add("dm-fitlabel-wrap");
    const base = parseFloat(getComputedStyle(el).fontSize) || 15;
    for (let size = base; size >= FIT_MIN_PX; size -= 0.5) {
      el.style.fontSize = size + "px";
      const lh = parseFloat(getComputedStyle(el).lineHeight) || size * 1.2;
      if (el.scrollHeight <= lh * 2 + 1) return;
    }
  }, [children]);
  return <span ref={ref} className="dm-fitlabel">{children}</span>;
}

// Text that shrinks ONLY as far as it must to fit its box's full width (and
// never below `min`). Replaces the old length-tiered name classes, which were
// compensation for a layout where the cost coin shared the name's row — the
// coin moved to the foot, so "Tide Pools" was rendering at ~60% of the width
// it had available. Re-fits when the box's WIDTH changes (container queries,
// rotation); height changes are ignored so shrinking can't feed itself.
function FitText({ text, className, min = 8 }) {
  const box = useRef(null);
  const span = useRef(null);
  useLayoutEffect(() => {
    const b = box.current, s = span.current;
    if (!b || !s) return;
    let lastW = -1;
    const fit = () => {
      b.style.fontSize = "";
      // clientWidth is the PADDING box, so measuring against it let the name
      // grow into (and past) its own right inset — the title sat visibly
      // closer to the right edge than the left, on every card. Fit to the
      // CONTENT box instead, and the two insets match by construction.
      const cs0 = getComputedStyle(b);
      const avail = b.clientWidth - parseFloat(cs0.paddingLeft)
        - parseFloat(cs0.paddingRight) - 1;
      if (avail <= 0) return;
      const natural = s.scrollWidth;
      if (natural > avail) {
        const base = parseFloat(getComputedStyle(b).fontSize) || 12;
        b.style.fontSize = Math.max(min, base * (avail / natural)) + "px";
      }
    };
    fit();
    let ro;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver((entries) => {
        const w = entries[0].contentRect.width;
        if (Math.abs(w - lastW) < 0.5) return;   // width only — never height
        lastW = w;
        fit();
      });
      ro.observe(b);
    }
    return () => { if (ro) ro.disconnect(); };
  }, [text, min]);
  return (
    <div ref={box} className={className}>
      <span ref={span} className="dm-fitspan">{text}</span>
    </div>
  );
}

// Keys that stay stable as a zone changes: the Nth copy of a card keeps its
// key when other cards leave, so only genuinely NEW cards mount (and animate).
// The turn prefix makes a fresh hand at turn start count as new.
function zoneKeys(list, prefix) {
  const seen = {};
  return list.map((name) => {
    seen[name] = (seen[name] || 0) + 1;
    return `${prefix}:${name}#${seen[name]}`;
  });
}

// Selection toggle for the pick-N prompts. Clicking a NEW item when the quota
// is full swaps rather than doing nothing: with max 1 it replaces outright,
// otherwise the oldest pick makes room. (Having to deselect first was a
// reported annoyance — every click should change something.)
function pickToggle(sel, item, max) {
  if (sel.includes(item)) return sel.filter((x) => x !== item);
  if (sel.length < max) return [...sel, item];
  if (max === 1) return [item];
  return [...sel.slice(1), item];
}

function DmCardBack() {
  return (
    <div className="card dm-card dm-card-small dm-card-back">
      <span className="dm-back-emblem">D</span>
    </div>
  );
}

// A real pile: deck = face-down back with a count badge; discard = its top card
// face up. Sizing rides the surrounding container's --card-w-s.
function DmPile({ kind, label, count, top, card, onInfo }) {
  const stacked = count > 1 ? " dm-pile-stacked" : "";
  return (
    <div className="dm-pile-slot dm-zpile">
      {kind === "deck"
        ? (count > 0
          ? <div className={"dm-pilewrap" + stacked}><DmCardBack /></div>
          : <div className="dm-empty-slot" />)
        : (top
          // keyed on the face + depth: a new top card remounts and flips over
          ? <div key={top + ":" + count} className={"dm-pilewrap" + stacked}>
              <DmCardFace name={top} card={card} small onInfo={onInfo} />
            </div>
          : <div className="dm-empty-slot" />)}
      <span className="dm-pile-count">{label} <Pop n={count} /></span>
    </div>
  );
}

// A number that pops when it changes: the key remount is what replays the
// CSS animation (a re-render alone would not).
function Pop({ n }) {
  return <span key={n} className="dm-count-pop">{n}</span>;
}

// A mat chip (Island / Native Village / Set-aside). When the cards on it are
// KNOWN — your own mats, or any public one (Island) — it's tappable to open a
// viewer; a hover title alone is invisible on touch, which is what hid the
// Native Village contents on a phone. A face-down mat (an opponent's Native
// Village / set-aside) shows the count only and isn't tappable.
function DmMatChip({ emoji, count, label, cards, onView }) {
  const canView = Array.isArray(cards) && cards.length > 0;
  return (
    <span className={"dm-mat-chip" + (canView ? " dm-mat-chip-view" : "")}
      title={label + ": " + (canView ? cards.join(", ") : "face down")}
      role={canView ? "button" : undefined} tabIndex={canView ? 0 : undefined}
      onClick={canView ? () => onView({ label, cards }) : undefined}
      onKeyDown={canView ? (e) => { if (e.key === "Enter" || e.key === " ") onView({ label, cards }); } : undefined}>
      {emoji} {count}{canView ? " 👁" : ""}
    </span>
  );
}

// ─── Log formatting (the Dominion-online look: full sentences, articles,
//     grouped card lists, sub-effects indented under the play that caused them) ──
const art = (name) => (/^[AEIOU]/.test(name) ? "an" : "a") + " " + name;
function pluralCard(name, k) {
  if (k === 1) return art(name);
  if (name.endsWith("s")) return `${k} ${name}`;
  if (name.endsWith("y")) return `${k} ${name.slice(0, -1)}ies`;
  return `${k} ${name}s`;
}
function listCards(cards) {
  const counts = [];
  for (const c of cards) {
    const hit = counts.find((x) => x[0] === c);
    if (hit) hit[1] += 1; else counts.push([c, 1]);
  }
  const parts = counts.map(([c, k]) => pluralCard(c, k));
  if (parts.length <= 1) return parts.join("");
  return parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1];
}
function fmtLog(e, names) {
  const who = e.pid ? (names[e.pid] || e.pid) : "";
  switch (e.event) {
    case "turn_start": return `— ${who}'s turn (${e.turn}) —`;
    case "phase": return null;                       // pure plumbing, not an event
    case "play": return `${who} plays ${art(e.card)}${e.coins != null ? ` (+$${e.coins})` : ""}`;
    case "plus": {
      const bits = [];
      if (e.coins) bits.push(`+$${e.coins}`);
      if (e.actions) bits.push(`+${e.actions} Action${e.actions > 1 ? "s" : ""}`);
      if (e.buys) bits.push(`+${e.buys} Buy${e.buys > 1 ? "s" : ""}`);
      if (!bits.length) return null;
      return `${who} gets ${bits.join(", ")}${e.why ? ` (${e.why})` : ""}`;
    }
    case "minus": {
      if (!e.coins) return null;
      return `${who} loses $${e.coins}`;
    }
    case "off_turn_bonus": {
      // earned on someone else's turn, so there is no pool to put it in and it
      // is LOST. Without this case the generic fallback rendered it as
      // "bob off turn bonus: coins 2", which reads as though he got it.
      const bits = [];
      if (e.coins) bits.push(`$${e.coins}`);
      if (e.actions) bits.push(`${e.actions} Action${e.actions > 1 ? "s" : ""}`);
      if (e.buys) bits.push(`${e.buys} Buy${e.buys > 1 ? "s" : ""}`);
      if (!bits.length) return null;
      return `${who} can't use ${bits.join(", ")} — not their turn`;
    }
    case "cleanup_off_turn":
      return `${who} discards ${listCards(e.cards)} (played on another turn)`;
    // Seaside/Prosperity events that had been falling through to the generic
    // fallback since their phases shipped
    case "lighthouse": return `${who} is protected by Lighthouse`;
    case "vp_tokens": return `${who} takes ${e.count} VP token${e.count === 1 ? "" : "s"}`;
    case "island": return `${who} sets ${listCards(e.cards)} aside on their Island mat`;
    case "village_mat":
      return `${who} sets ${e.count} card${e.count === 1 ? "" : "s"} aside on their Native Village mat`;
    case "village_take":
      return `${who} takes ${e.count} card${e.count === 1 ? "" : "s"} from their Native Village mat`;
    case "exchange":
      return `${who} exchanges ${art(e.card)} for ${art(e.into)}`;
    case "shuffle_into_deck":
      return `${who} shuffles ${e.count || 0} card${e.count === 1 ? "" : "s"} into their deck`;
    case "buy": return `${who} buys and gains ${art(e.card)}`;
    case "gain": return e.dest && e.dest !== "discard"
      ? `${who} gains ${art(e.card)} (to ${e.dest === "deck" ? "their deck" : e.dest})`
      : `${who} gains ${art(e.card)}`;
    case "gain_from_trash": return `${who} gains ${art(e.card)} from the trash`;
    case "trash": return `${who} trashes ${listCards(e.cards || [])}`;
    case "supply_trash": return `${who} trashes ${art(e.card)} from the Supply`;
    case "discard": {
      if (e.cards) return `${who} discards ${listCards(e.cards)}`;
      const k = e.count ?? e.n;                    // pre-fix entries kept it in n
      return `${who} discards ${k} card${k === 1 ? "" : "s"}`;
    }
    case "draw": {
      if (e.cards) return `${who} draws ${listCards(e.cards)}`;
      const k = e.count ?? e.n;
      return `${who} draws ${k} card${k === 1 ? "" : "s"}`;
    }
    case "shuffle": return `${who} shuffles their deck`;
    case "reveal": return `${who} reveals ${listCards(e.cards || [])}`;
    case "topdeck": return e.card ? `${who} puts ${art(e.card)} onto their deck`
      : `${who} puts a card onto their deck`;
    case "deck_insert": return `${who} slips a card into their deck`;
    case "secret_passage": return `${who} places it ${e.position === 0 ? "on top" : e.position >= (e.depth - 1) ? "on the bottom" : `${e.position} deep`}`;
    case "named": return `${who} names ${e.card}`;
    case "pass": return `${who} passes ${art(e.card)} to ${names[e.to] || e.to}`;
    case "pass_public": return `${who} passes a card to ${names[e.to] || e.to}`;
    // An ability skipped because its card moved (the lose-track rule) — most
    // often a second discarded Trail that the first one's draw shuffled back
    // into the deck. Without this line the prompt simply never appears, which
    // is indistinguishable from a broken trigger. `verb` is absent for
    // abilities that aren't one word (Watchtower's trash-or-topdeck).
    case "lost_track": return `${who} loses track of ${art(e.card)} — ${e.why || "it moved"}, so `
      + (e.verb ? `it can't be ${e.verb}` : "the ability is skipped");
    case "undo": return `${who} takes back a move`;
    case "abandon": return `${who} abandoned the game`;
    case "game_over": return `Game over — ${(e.winners || []).map((w) => names[w] || w).join(" & ")} win${(e.winners || []).length > 1 ? "" : "s"}!`;
    default: {
      // An engine event this client doesn't know yet (every expansion adds
      // some) must never be SILENT — a missing line reads as "the game did
      // nothing". Render a plain readable fallback until it gets a case above.
      if (!e.event) return null;
      const skip = ["n", "pid", "event", "d", "private_to"];
      const bits = Object.entries(e)
        .filter(([k, v]) => !skip.includes(k) && (typeof v === "string" || typeof v === "number"))
        .map(([k, v]) => (k === "card" || k === "count" ? String(v) : `${k} ${v}`));
      const cards = Array.isArray(e.cards) ? listCards(e.cards) : "";
      const detail = [cards, ...bits].filter(Boolean).join(", ");
      const verb = e.event.replace(/_/g, " ");
      return `${who ? who + " " : ""}${verb}${detail ? ": " + detail : ""}`.trim();
    }
  }
}

// Every card a seat owns at game over, folded to name→count — the player's
// FINAL DECK. Mirrors engine.owned_cards: all zones reveal at over, so this
// needs no new wire field (duration cards ride duration_view, since the raw
// duration list is popped by player_view).
function deckCensus(seat) {
  if (!seat) return {};
  const all = [
    ...(seat.deck || []), ...(seat.hand || []), ...(seat.discard || []),
    ...(seat.in_play || []), ...(seat.aside || []), ...(seat.dur_aside || []),
    ...(seat.island || []), ...(seat.village_mat || []),
    ...((seat.duration_view || []).flatMap((e) => [e.card, ...(e.riders || [])])),
  ];
  const counts = {};
  for (const c of all) counts[c] = (counts[c] || 0) + 1;
  return counts;
}

// "12–9" for a finished game (yours first, then each opponent), the way CoC's
// history reads. Prefers the server's ordered `standings`, which survives two
// players sharing a display name; falls back to the name-keyed `scores` for a
// response cached before standings shipped. Renders nothing unless EVERY score
// is present — a half-filled line reads as a wrong score.
function historyScores(g) {
  const vps = Array.isArray(g.standings) && g.standings.length
    ? g.standings.map((s) => s.vp)
    : [g.your_vp, ...(g.opponents || []).map((n) => (g.scores || {})[n])];
  if (vps.length < 2 || vps.some((v) => v == null)) return "";
  return vps.join("–");
}

// The buy handler logs "buy" and the gain it causes logs "gain" back-to-back —
// fold the pair into the single "buys and gains" line.
function buildLogLines(log, names) {
  const out = [];
  for (let i = 0; i < log.length; i++) {
    const e = log[i];
    if (e.event === "gain" && i > 0) {
      const p = log[i - 1];
      if (p.event === "buy" && p.pid === e.pid && p.card === e.card) continue;
    }
    const text = fmtLog(e, names);
    // key = position in the (append-only) view log — e.n is NOT safe as a React
    // key: entries written before the count/sequence fix share n values, and
    // duplicate keys made React visibly scramble the list.
    if (text) out.push({ key: i, d: Math.min(e.d || 0, 3), turn: e.event === "turn_start", text });
  }
  return out;
}

// ─── Socket hook ─────────────────────────────────────────────────────────────
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

// ─── Styles (no backticks anywhere in the css string) ───────────────────────
const dmStyles = baseCss + lobbyCss + splendorCardCss + _cssText
  + gameMenuCss + createModalCss + lobbyCreateRowCss;

// ─── Main component ─────────────────────────────────────────────────────────
export default function Dontminion({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");     // lobby | waiting | game
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [catalog, setCatalog] = useState(null);      // {cards, kingdom, expansions}
  const [openGames, setOpenGames] = useState(() => readLobbyCache("dontminion", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("dontminion", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("dontminion", myId, "history", []));
  const [loadingGames, setLoadingGames] = useState(false);
  const [toast, setToast] = useState("");
  const [reconnecting, setReconnecting] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createOpp, setCreateOpp] = useState("ai");
  const [createBots, setCreateBots] = useState(1);
  // Big Money+ by default: the strongest tier that still answers instantly,
  // and the one that plays a recognisable game of Dominion (it reads the
  // board for a terminal and knows how the game ends).
  const [createBotKind, setCreateBotKind] = useState("bmplus");
  // Kingdom requirements — none by default, so a plain Create still deals the
  // fully random 10 the game has always dealt.
  const [createReqs, setCreateReqs] = useState([]);
  const [createPlayers, setCreatePlayers] = useState(4);
  // Base Set only by default — the newcomer's game, and the set every Dominion
  // player knows. Everything else is opt-in through the picker.
  const [createExps, setCreateExps] = useState(["base"]);
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  const [gameOverDismissed, setGameOverDismissed] = useState(false);
  const [showTrash, setShowTrash] = useState(false);
  const [showKingdom, setShowKingdom] = useState(false);
  const [cardInfo, setCardInfo] = useState(null);    // card name → detail modal
  const [deckView, setDeckView] = useState(null);    // game-over: whose final deck to show
  const [matView, setMatView] = useState(null);      // {label, cards} for a mat viewer modal
  const [lobbyTab, setLobbyTab] = useState("open");  // mobile-only Open/Active/History selector
  // decision-prompt interaction state (generic across all frame kinds)
  const [pickIdx, setPickIdx] = useState([]);        // choose_cards: selected INDICES (dups!)
  const [pickOpts, setPickOpts] = useState([]);      // choose_option pick>1: selected ids
  const [orderIdx, setOrderIdx] = useState([]);      // order_cards: click sequence of indices
  const [promptMin, setPromptMin] = useState(false); // decision modal minimized (peek at board)

  // ── URL routing refs (segment 2 = room id; the shell owns "/dontminion") ──
  const screenRef = useRef(screen);
  screenRef.current = screen;
  const roomIdRef = useRef(roomId);
  roomIdRef.current = roomId;
  const urlAttemptRef = useRef(null);
  const didInitRef = useRef(false);
  const popHandlerRef = useRef(() => {});
  const reconnTimer = useRef(null);
  const reconnTries = useRef(0);
  const logRef = useRef(null);

  const playerName = authUser?.name || "Player";

  // ── derived (keep ABOVE all effects — TDZ rule) ──
  const game = roomData?.game;
  const names = roomData?.players || {};
  const cards = catalog?.cards || {};
  const seats = game?.seats || {};
  const mySeat = seats[myId];
  const over = !!game?.over;
  const pv = game?.pending_view || null;
  const iAmActor = !!pv && !over && game?.pending_pid === myId && !!pv.constraint;
  const waitingOn = pv && !iAmActor ? pv.waiting_on : null;
  const botActing = !!game && !over && (roomData?.ai_players || []).includes(game.pending_pid || game.turn);
  const bridges = game?.turn_ctx?.bridges || 0;
  // Prices come from the SERVER (engine.cost): Bridge, Quarry, Peddler's
  // dynamic self-cost and anything a future set adds. The bridges-only
  // fallback covers a pre-costs save being replayed by a cached client.
  const effCost = (name) => game?.costs?.[name]
    ?? Math.max(0, (cards[name]?.cost ?? 0) - bridges);
  const printedCost = (name) => cards[name]?.cost ?? 0;
  const inBuy = !!game && game.phase === "buy" && game.turn === myId && !game.pending_pid && !over;
  const inAction = !!game && game.phase === "action" && game.turn === myId && !game.pending_pid && !over;
  const bought = !!game?.turn_ctx?.bought;
  // "Play all treasures" SKIPS the interactive ones (War Chest/Anvil), so a
  // hand holding only those must not offer the button — it would do nothing.
  // built from what the SERVER offers, so shipping a set needs no frontend edit
  const expansionOptions = (catalog?.expansions?.length
    ? catalog.expansions
    : EXPANSIONS.map((e) => e.id)
  ).map((id) => ({
    id,
    name: EXPANSIONS.find((e) => e.id === id)?.name
      || id.charAt(0).toUpperCase() + id.slice(1),
  }));
  const allExpsOn = expansionOptions.length > 0
    && expansionOptions.every((e) => createExps.includes(e.id));
  // Kingdom requirements, from the server too (main.REQUIREMENT_ORDER) — the
  // bar for each ("+2 Actions") is the SERVER's label, so the picker can never
  // promise a threshold the dealer doesn't use.
  const requireOptions = catalog?.requirements || [];
  const manualTreasures = catalog?.manual_treasures || [];
  const handTreasures = (mySeat?.hand || []).some((c) => (cards[c]?.types?.includes("treasure")
    || (c === "Curse" && game?.curse_is_treasure)) && !manualTreasures.includes(c));
  const constraint = iAmActor ? pv.constraint : null;
  const kingdomPiles = game?.kingdom || [];
  const kingdomByCost = [...kingdomPiles].sort((a, b) =>
    ((cards[a]?.cost ?? 0) - (cards[b]?.cost ?? 0)) || a.localeCompare(b));
  const seatOrder = game?.players || Object.keys(names);
  // The single opponent play box tracks the ACTION: the opponent whose turn it
  // is — or, on your turn, whoever plays next. (2p: always the one opponent.)
  const focusOpp = !game ? null
    : game.turn !== myId ? game.turn
    : seatOrder[(seatOrder.indexOf(myId) + 1) % Math.max(seatOrder.length, 1)];
  // Undo walks back ONE move per press. undo_depth (how many snapshots the
  // server holds) is the WHOLE gate: a reveal empties the server's stack, so
  // depth 0 means "nothing reversible since the last new information" — and
  // moves made after a reveal are undoable again.
  const canUndo = !!game && !over && game.turn === myId
    && (game.undo_depth || 0) > 0;
  // Stable per-card keys so ONLY genuinely new cards mount — that mount is
  // what plays the entrance animation (drawn, played, gained).
  const handKeys = zoneKeys(mySeat?.hand || [], "h" + (game?.turn_number || 0));
  const inPlayKeys = zoneKeys(mySeat?.in_play || [], "p" + (game?.turn_number || 0));
  // What-you-can-do hint, shown at the right of the resource bar. Board-driven
  // prompts (choose_pile) live HERE instead of in their own prompt box.
  const promptCardName = displayCard(pv?.card);
  // A pile prompt describes what the CARD does ("gain a card costing up to
  // $4") rather than the mechanically obvious "pick a highlighted pile". The
  // text comes from the catalog, minus its vanilla +Card/+Action/+Buy/+$ lines;
  // when every eligible pile shares one cost (Upgrade, Swindler) the exact
  // target cost is appended, since the card text can't name it.
  const VANILLA_LINE = /^\+(\d+\s*(Cards?|Actions?|Buys?)|\$\d+)$/i;
  const effectText = (name) => (cards[name]?.text || "")
    .split("\n").map((s) => s.trim())
    .filter((s) => s && !VANILLA_LINE.test(s)).join(" ");
  const pileHint = (name, piles) => {
    const body = effectText(name);
    const parts = body.split(/\.\s+/).map((s, i, a) => (i < a.length - 1 ? s + "." : s));
    const clause = parts.find((s) => /gain|trash|name/i.test(s)) || body;
    const costs = (piles || []).map(effCost);
    const band = costs.length && Math.min(...costs) === Math.max(...costs)
      ? ` (piles costing $${costs[0]})` : "";
    return `${name}: ${clause || "pick a highlighted Supply pile"}${band}`;
  };
  const resHint = (() => {
    if (!game || over || game.turn !== myId) return "";
    if (iAmActor) {
      return pv.kind === "choose_pile" ? pileHint(promptCardName, pv.constraint?.piles) : "";
    }
    if (game.pending_pid) return "";               // waiting bar covers it
    if (game.phase === "action") return "you may play Action cards";
    if (game.buys > 0) return bought ? "you may buy cards" : "you may play Treasures and buy cards";
    return "no buys left — end your turn";
  })();

  // ── socket plumbing ──
  const handleMessage = useCallback((msg) => {
    if (msg.type === "error") {
      const ua = urlAttemptRef.current;
      if (ua) {
        if (msg.message === "invalid token" && !ua.retried) {
          ua.retried = true;
          try { localStorage.removeItem(`dm_token_${ua.rid}_${myId}`); } catch {}
          resumeGame(ua.rid);
          return;
        }
        urlAttemptRef.current = null;
        try {
          if (localStorage.getItem("dm_roomId") === ua.rid) localStorage.removeItem("dm_roomId");
          localStorage.removeItem(`dm_token_${ua.rid}_${myId}`);
        } catch {}
        setRoomId(""); setRoomData(null); setScreen("lobby");
        replacePath(buildPath("dontminion"));
      }
      setToast(msg.message || "error"); return;
    }
    const room = msg.room;
    if (!room) return;
    const rid = room.room_id || roomId;
    const tok = room.reconnect_tokens?.[myId];
    if (tok) {
      try {
        localStorage.setItem(`dm_token_${rid}_${myId}`, tok);
        localStorage.setItem("dm_roomId", rid);
      } catch {}
    }
    setRoomData(room);
    const inGame = room.status === "playing" || room.status === "over";
    if (msg.type === "created" || msg.type === "joined" || msg.type === "reconnected") {
      if (rid) pushPath(buildPath("dontminion", rid));
      urlAttemptRef.current = null;
      setScreen(inGame ? "game" : "waiting");
    } else if (msg.type === "room_update" && inGame && screenRef.current !== "game") {
      setScreen("game");
    }
  }, [myId, roomId]); // eslint-disable-line react-hooks/exhaustive-deps

  const { connected, connect, send, disconnect, socketReady } = useSocket(handleMessage);

  useEffect(() => {
    fetch(`${DM_HTTP}/catalog`).then((r) => r.json()).then((d) => { if (d.ok) setCatalog(d); }).catch(() => {});
  }, []);

  const fetchGames = useCallback(() => {
    setLoadingGames(true);
    fetch(`${DM_HTTP}/games`).then((r) => r.json()).then((d) => { const g = d.games || []; setOpenGames(g); writeLobbyCache("dontminion", myId, "open", g); })
      .catch(() => {}).finally(() => setLoadingGames(false));
    if (authUser?.session_token) {
      const headers = { Authorization: `Bearer ${authUser.session_token}` };
      fetch(`${DM_HTTP}/games/mine`, { headers }).then((r) => r.json()).then((d) => { const g = d.games || []; setMyGames(g); writeLobbyCache("dontminion", myId, "mine", g); }).catch(() => {});
      fetch(`${DM_HTTP}/games/history`, { headers }).then((r) => r.json()).then((d) => { const g = d.games || []; setHistory(g); writeLobbyCache("dontminion", myId, "history", g); }).catch(() => {});
    } else { setMyGames([]); setHistory([]); writeLobbyCache("dontminion", myId, "mine", []); writeLobbyCache("dontminion", myId, "history", []); }
  }, [authUser, myId]);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);
  useEffect(() => { return () => disconnect(); }, []); // eslint-disable-line

  // ── URL deep entry + popstate ──
  const urlResume = (rid) => {
    urlAttemptRef.current = { rid, retried: false };
    resumeGame(rid);
  };
  useEffect(() => {
    if (didInitRef.current) return;
    didInitRef.current = true;
    const r = parsePath();
    if (r.game === "dontminion" && r.room) urlResume(r.room);
  }, []); // eslint-disable-line
  popHandlerRef.current = (r) => {
    if (r.game !== "dontminion") return;
    if (r.room && r.room !== roomIdRef.current) {
      urlResume(r.room);
    } else if (!r.room && (roomIdRef.current || urlAttemptRef.current)) {
      urlAttemptRef.current = null;
      leaveToLobby();
    }
  };
  useEffect(() => subscribe((r) => popHandlerRef.current(r)), []); // eslint-disable-line

  // ── auto-reconnect while in a live game (re-kicks the bot scheduler server-side) ──
  const inLiveGame = !!roomId && (screen === "game" || screen === "waiting") && roomData?.status !== "over";
  const attemptReconnect = useCallback(() => {
    if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; }
    const rs = socketReady();
    if (rs === 0 || rs === 1) { reconnTimer.current = setTimeout(attemptReconnect, 3000); return; }
    let tok = null;
    try { tok = localStorage.getItem(`dm_token_${roomId}_${myId}`); } catch {}
    if (tok) { setReconnecting(true); connect(`${DM_WS}/${roomId}/${myId}`, { action: "reconnect", token: tok }); }
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

  // The log reads oldest-at-top, so the newest line is at the BOTTOM and the
  // view has to follow it. Only when the reader is already parked at the bottom
  // though — scrolling up to re-read a turn must not be yanked away by the
  // opponent's next move. Measured against the live scroll position, not a
  // "user scrolled" flag, so it self-heals when they scroll back down.
  const logLen = (game?.log || []).length;
  const logPinRef = useRef("");
  useEffect(() => {
    const el = logRef.current;
    if (!el) return;
    const key = `${roomId}:${screen}`;
    if (logPinRef.current !== key) {     // just opened this game: start at the newest
      logPinRef.current = key;
      el.scrollTop = el.scrollHeight;
      return;
    }
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom < 80) el.scrollTop = el.scrollHeight;
  }, [logLen, screen, roomId]);

  // clear decision-prompt state whenever the decision context changes
  useEffect(() => {
    setPickIdx([]); setPickOpts([]); setOrderIdx([]); setPromptMin(false);
  }, [game?.turn, game?.turn_number, game?.pending_kind, game?.pending_pid, (game?.log || []).length]);
  useEffect(() => { setGameOverDismissed(false); setDeckView(null); setMatView(null); }, [roomId]);

  // The engine auto-advances action->buy after moves and at turn hand-offs, but
  // deliberately not at game CREATION (test fixtures stage hands post-deal). The
  // client covers that one case: an action phase with no Action card in hand is
  // skipped, once per turn (never re-fired after an undo).
  const autoSkipRef = useRef("");
  useEffect(() => {
    if (!game || over || game.turn !== myId || game.phase !== "action" || game.pending_pid) return;
    const hand = mySeat?.hand || [];
    if (hand.some((c) => cards[c]?.types?.includes("action"))) return;
    const key = `${roomId}:${game.turn_number || 0}`;
    if (autoSkipRef.current === key) return;
    autoSkipRef.current = key;
    send({ action: "move", move: { type: "end_phase" } });
  }, [game, roomId, myId, over, mySeat, cards, send]);

  // ── actions ──
  const mv = (move) => send({ action: "move", move });

  const createGame = () => {
    // The server rejects an empty expansion set; the Create button is disabled
    // for it, and this is the belt to that suspenders (a stale click, a keyboard
    // submit) so the failure can never be an opaque socket error.
    if (!createExps.length) { setToast("Pick at least one expansion."); return; }
    const rid = roomCode();
    setRoomId(rid);
    setRoomData(null);
    setShowCreateModal(false);
    const msg = {
      action: "create", name: playerName, expansions: createExps,
      requires: createReqs, vs_ai: createOpp === "ai",
    };
    if (createOpp === "ai") {
      msg.num_bots = createBots;
      msg.ai_difficulty = createBotKind;
    } else {
      msg.max_players = createPlayers;
    }
    connect(`${DM_WS}/${rid}/${myId}`, msg);
  };
  const joinGame = (rid) => {
    rid = (rid || "").toUpperCase().trim();
    if (!rid) return;
    setRoomId(rid);
    connect(`${DM_WS}/${rid}/${myId}`, { action: "join", name: playerName, session_token: authUser?.session_token });
  };
  const resumeGame = (rid) => {
    let tok = null;
    try { tok = localStorage.getItem(`dm_token_${rid}_${myId}`); } catch {}
    setRoomId(rid);
    connect(`${DM_WS}/${rid}/${myId}`, tok ? { action: "reconnect", token: tok } : { action: "join", name: playerName, session_token: authUser?.session_token });
  };
  const cancelGame = (rid) => {
    const headers = { "Content-Type": "application/json" };
    if (authUser?.session_token) headers.Authorization = `Bearer ${authUser.session_token}`;
    fetch(`${DM_HTTP}/games/${rid}/cancel?player_id=${encodeURIComponent(myId)}`, { method: "POST", headers })
      .then((r) => r.json()).then((d) => {
        if (!d.ok) { setToast(d.message || "Could not cancel"); return; }
        try {
          if (localStorage.getItem("dm_roomId") === rid) localStorage.removeItem("dm_roomId");
          localStorage.removeItem(`dm_token_${rid}_${myId}`);
        } catch {}
        fetchGames();
      }).catch(() => setToast("Could not cancel"));
  };
  const leaveToLobby = () => {
    disconnect();
    pushPath(buildPath("dontminion"));
    setScreen("lobby");
    setRoomData(null);
    setRoomId("");
  };
  const abandonGame = () => { send({ action: "abandon" }); setConfirmAbandon(false); };

  // Charlatan's game rule: Curse is also a Treasure (playable for $1)
  const typesFor = (c) => {
    const t = cards[c]?.types || [];
    return c === "Curse" && game?.curse_is_treasure ? [...t, "treasure"] : t;
  };

  // Every click lands somewhere: playable → play, buyable → buy, anything
  // else → the card-detail modal (never a dead click).
  const handClick = (card) => {
    const t = typesFor(card);
    if (!iAmActor && inAction && t.includes("action") && game.actions > 0) mv({ type: "play_action", card });
    else if (!iAmActor && inBuy && t.includes("treasure") && !bought) mv({ type: "play_treasure", card });
    else setCardInfo(card);
  };
  const pileClick = (pile) => {
    if (iAmActor && constraint?.piles) {
      if (constraint.piles.includes(pile)) { mv({ type: "decision", pile }); return; }
      setCardInfo(pile); return;
    }
    if (inBuy && game.buys > 0 && (game.supply[pile] || 0) > 0 && effCost(pile) <= game.coins) {
      mv({ type: "buy", card: pile }); return;
    }
    setCardInfo(pile);
  };

  // ── render helpers ──
  const kindOfPrompt = iAmActor ? pv.kind : null;
  // These decision kinds open as a minimizable MODAL; choose_pile stays a
  // board hint, waiting-on stays an inline bar.
  const hasModalPrompt = iAmActor
    && ["choose_cards", "choose_option", "order_cards", "place_in_deck", "name_card"].includes(pv.kind);

  const promptTitle = () => {
    const c = constraint;
    const promptCard = displayCard(pv.card);
    switch (kindOfPrompt) {
      case "choose_cards": {
        const label = c.min === c.max ? `${c.purpose} ${c.min}` : c.min === 0 ? `${c.purpose} up to ${c.max}` : `${c.purpose} ${c.min}–${c.max}`;
        return `${promptCard}: ${label}${pickIdx.length ? ` (${pickIdx.length} picked)` : ""}`;
      }
      case "choose_option": {
        const pick = c.pick || 1;
        return pick === 1 ? promptCard : `${promptCard}: choose ${pick} (different)`;
      }
      case "order_cards": return `${promptCard}: click cards in order (first = top of deck)`;
      case "place_in_deck": return `Secret Passage: where in your deck? (${c.card})`;
      case "name_card": return `${promptCard}: name a card`;
      default: return promptCard;
    }
  };

  const promptBody = () => {
    const c = constraint;
    if (kindOfPrompt === "choose_cards") {
      const need = pickIdx.length;
      const okPick = need >= c.min && need <= c.max;
      return (
        <>
          <div className="dm-prompt-cards">
            {c.cards.map((n, i) => (
              <DmCardFace key={i} name={n} card={cards[n]} small
                selected={pickIdx.includes(i)}
                onClick={() => setPickIdx((s) => pickToggle(s, i, c.max))}
                onInfo={() => setCardInfo(n)} />
            ))}
          </div>
          <div className="dm-prompt-actions">
            <button className="btn btn-gold" disabled={!okPick}
              onClick={() => { mv({ type: "decision", cards: pickIdx.map((i) => c.cards[i]) }); }}>
              Confirm{c.purpose === "pass" ? " (kept secret)" : ""}
            </button>
            {c.min === 0 && <button className="btn btn-outline" onClick={() => mv({ type: "decision", cards: [] })}>None</button>}
          </div>
        </>
      );
    }
    if (kindOfPrompt === "choose_option") {
      const pick = c.pick || 1;
      if (pick === 1) {
        return (
          <div className="dm-prompt-actions">
            {c.options.map((o) => (
              <button key={o.id} className="btn btn-gold" onClick={() => mv({ type: "decision", ids: [o.id] })}>
                <FitLabel>{o.label}</FitLabel>
              </button>
            ))}
          </div>
        );
      }
      return (
        <div className="dm-prompt-actions">
          {c.options.map((o) => (
            <button key={o.id}
              className={"btn " + (pickOpts.includes(o.id) ? "btn-gold" : "btn-outline")}
              onClick={() => setPickOpts((s) => pickToggle(s, o.id, pick))}>
              <FitLabel>{o.label}</FitLabel>
            </button>
          ))}
          <button className="btn btn-gold" disabled={pickOpts.length !== pick}
            onClick={() => mv({ type: "decision", ids: pickOpts })}>Confirm</button>
        </div>
      );
    }
    if (kindOfPrompt === "order_cards") {
      const remaining = c.cards.map((n, i) => i).filter((i) => !orderIdx.includes(i));
      return (
        <>
          <div className="dm-prompt-cards">
            {c.cards.map((n, i) => (
              <DmCardFace key={i} name={n} card={cards[n]} small
                selected={orderIdx.includes(i)}
                badge={orderIdx.includes(i) ? orderIdx.indexOf(i) + 1 : null}
                onClick={() => setOrderIdx((s) => s.includes(i) ? s.filter((x) => x !== i) : [...s, i])}
                onInfo={() => setCardInfo(n)} />
            ))}
          </div>
          <div className="dm-prompt-actions">
            <button className="btn btn-gold" disabled={remaining.length > 0}
              onClick={() => mv({ type: "decision", order: orderIdx.map((i) => c.cards[i]) })}>Confirm order</button>
            <button className="btn btn-outline" onClick={() => setOrderIdx([])}>Reset</button>
          </div>
        </>
      );
    }
    if (kindOfPrompt === "place_in_deck") {
      return (
        <div className="dm-prompt-actions dm-slots">
          {Array.from({ length: c.deck_len + 1 }, (_, p) => (
            <button key={p} className="btn btn-outline"
              onClick={() => mv({ type: "decision", position: p })}>
              {p === 0 ? "Top" : p === c.deck_len ? "Bottom" : p}
            </button>
          ))}
        </div>
      );
    }
    if (kindOfPrompt === "name_card") {
      return (
        <div className="dm-prompt-actions dm-names">
          {c.cards.map((n) => (
            <button key={n} className="btn btn-outline" onClick={() => mv({ type: "decision", card: n })}>
              <FitLabel>{n}</FitLabel>
            </button>
          ))}
        </div>
      );
    }
    return null;
  };

  // inline slot above the supply: only the waiting bar and the rare
  // off-turn choose_pile keep living here
  const renderPrompt = () => {
    if (!game || over) return null;
    if (waitingOn) {
      return (
        <div className="dm-waitbar">
          Waiting for <b>{names[waitingOn] || waitingOn}</b>
          {pv?.card && pv.card !== "__attack" ? <> — {displayCard(pv.card)}</> : null}
          {botActing ? <span className="dm-dots">…</span> : null}
        </div>
      );
    }
    if (iAmActor && kindOfPrompt === "choose_pile" && game.turn !== myId) {
      return (
        <div className="dm-prompt">
          <div className="dm-prompt-hd">{pileHint(promptCardName, constraint?.piles)}</div>
        </div>
      );
    }
    return null;
  };

  // decision MODAL — minimize to study the board; the restore button takes the
  // hint slot in the resource bar
  const renderPromptModal = () => {
    if (!hasModalPrompt || promptMin || over) return null;
    return (
      <div className="dm-backdrop dm-backdrop-top" onClick={() => setPromptMin(true)}>
        <div className="dm-modal dm-prompt dm-prompt-modal" onClick={(e) => e.stopPropagation()}>
          <div className="dm-prompt-hdrow">
            <div className="dm-prompt-hd">{promptTitle()}</div>
            <button className="btn btn-ghost btn-sm" onClick={() => setPromptMin(true)}>▾ Look at the board</button>
          </div>
          {promptBody()}
        </div>
      </div>
    );
  };

  const renderPile = (name, idx = 0) => {
    const cardData = cards[name];
    const count = game.supply[name] ?? 0;
    const promptPiles = iAmActor && constraint?.piles ? constraint.piles : null;
    const highlight = promptPiles ? promptPiles.includes(name)
      : (inBuy && game.buys > 0 && count > 0 && effCost(name) <= game.coins);
    const disabled = promptPiles ? !promptPiles.includes(name) : count === 0;
    return (
      <div key={name} className="dm-pile-slot"
        style={{ animationDelay: Math.min(idx * 16, 260) + "ms" }}>
        <DmCardFace name={name} card={cardData} small
          highlight={highlight} disabled={disabled && !highlight}
          onClick={() => pileClick(name)} onInfo={() => setCardInfo(name)} />
        {/* the count sits OUTSIDE the card (the card clips its overflow) */}
        <span className="dm-pile-count"><Pop n={count} /></span>
        {/* any active discount (Bridge, Quarry, Peddler's own rule) */}
        {cardData && effCost(name) !== printedCost(name)
          && <span className="dm-disc">now {effCost(name)}</span>}
      </div>
    );
  };

  // Sidebar player box (one per seat, above the Trash): identity + score only —
  // name, VP, turns taken, and whose turn it is. Card zones live in play boxes.
  const renderPlayerBox = (pid) => {
    const s = seats[pid] || {};
    const isBot = (roomData?.ai_players || []).includes(pid);
    const acting = !over && (game.pending_pid || game.turn) === pid;
    return (
      <div key={pid} className={"dm-pbox" + (acting ? " dm-pbox-acting" : "")}>
        <span className="dm-pbox-name">
          {names[pid] || pid}{isBot ? " 🤖" : ""}{pid === myId ? " (you)" : ""}
        </span>
        {acting && (
          <TurnBadge mine={pid === myId}>
            {game.pending_pid === pid ? "deciding" : pid === myId ? "your turn" : "their turn"}
          </TurnBadge>
        )}
        <span className="dm-vp" title="victory points">🛡 <Pop n={game.vp?.[pid] ?? 0} /> VP</span>
        {(game.vp_tokens?.[pid] || 0) > 0 && (
          <span className="dm-opp-turns" title="VP tokens (included in the total)">⭐ <Pop n={game.vp_tokens[pid]} /></span>
        )}
        <span className="dm-opp-turns" title="turns taken">⏱ {s.turns_taken ?? 0}</span>
      </div>
    );
  };

  // Opponent PLAY box (center column, same width as mine): face-DOWN backs for
  // the hand, face-UP cards for what they've played, real deck/discard piles.
  const renderOppPlay = (pid) => {
    const s = seats[pid] || {};
    const acting = !over && (game.pending_pid || game.turn) === pid;
    const handN = Math.min(s.hand_count ?? 0, 12);
    return (
      <div key={pid} className={"dm-opp" + (acting ? " dm-opp-acting" : "")}>
        <div className="dm-opp-zones">
          <DmPile kind="deck" label="deck" count={s.deck_count ?? 0} />
          <DmPile kind="discard" label="discard" count={s.discard_view?.count ?? 0}
            top={s.discard_view?.top} card={cards[s.discard_view?.top]}
            onInfo={() => setCardInfo(s.discard_view?.top)} />
          <div className="dm-opp-hand dm-pile-slot" title={`${s.hand_count ?? 0} cards in hand`}>
            <div className="dm-fan">
              {handN > 0
                ? Array.from({ length: handN }, (_, i) => <DmCardBack key={i} />)
                : <div className="dm-empty-slot" />}
            </div>
            <span className="dm-pile-count">hand <Pop n={s.hand_count ?? 0} /></span>
          </div>
          <div className="dm-opp-inplay">
            {(s.duration_view || []).flatMap((e, i) => [
              <div key={"d" + i} className="dm-durwrap" title="Duration — stays in play">
                <DmCardFace name={e.card} card={cards[e.card]} small onInfo={() => setCardInfo(e.card)} />
              </div>,
              ...(e.riders || []).map((r, j) => (
                <div key={"d" + i + "r" + j} className="dm-durwrap">
                  <DmCardFace name={r} card={cards[r]} small onInfo={() => setCardInfo(r)} />
                </div>
              )),
            ])}
            {(() => {
              const ip = s.in_play || [];
              const ks = zoneKeys(ip, "o" + pid + (game.turn_number || 0));
              return ip.map((c, i) => (
                <DmCardFace key={ks[i]} name={c} card={cards[c]} small onInfo={() => setCardInfo(c)} />
              ));
            })()}
            {(s.in_play || []).length === 0 && (s.duration_view || []).length === 0
              && <span className="dm-zone-hint">nothing in play</span>}
            {(s.island || []).length > 0 && (
              <DmMatChip emoji="🏝" count={s.island.length} label="Island mat"
                cards={s.island} onView={setMatView} />
            )}
            {(s.village_count || 0) > 0 && (
              /* face down — the opponent's mat contents are hidden, count only */
              <DmMatChip emoji="🏕" count={s.village_count} label="Native Village mat"
                cards={null} onView={setMatView} />
            )}
          </div>
        </div>
      </div>
    );
  };

  const renderGameOver = () => {
    if (!over || gameOverDismissed) return null;
    const scores = game.scores || {};
    const ranked = [...seatOrder].sort((a, b) => (scores[b]?.vp ?? 0) - (scores[a]?.vp ?? 0));
    const winners = game.winners || [];
    // Drilldown: one player's full final deck (every zone folded to counts),
    // sorted by cost then name like the supply. Rows show how many of each.
    if (deckView) {
      const counts = deckCensus(seats[deckView]);
      const entries = Object.entries(counts).sort((a, b) =>
        ((cards[a[0]]?.cost ?? 0) - (cards[b[0]]?.cost ?? 0)) || a[0].localeCompare(b[0]));
      const total = entries.reduce((n, [, k]) => n + k, 0);
      return (
        <div className="dm-backdrop" onClick={() => setDeckView(null)}>
          <div className="dm-modal dm-deckview" onClick={(e) => e.stopPropagation()}>
            <h2>{names[deckView] || deckView}{deckView === myId ? " (you)" : ""}</h2>
            <p className="dm-wait-note">Final deck — {total} cards · {scores[deckView]?.vp ?? "?"} VP</p>
            <div className="dm-deck-list">
              {entries.map(([name, k]) => (
                <div key={name} className={"dm-deck-row " + faceClass(cards[name]?.types)}>
                  <span className="dm-deck-count">{k}&times;</span>
                  <span className="dm-deck-name">{name}</span>
                  <span className="dm-deck-cost">${cards[name]?.cost ?? "?"}</span>
                </div>
              ))}
            </div>
            <div className="dm-prompt-actions">
              <button className="btn btn-gold" onClick={() => setDeckView(null)}>&larr; Back</button>
            </div>
          </div>
        </div>
      );
    }
    return (
      <div className="dm-backdrop">
        <div className="dm-modal">
          <h2>{winners.includes(myId) ? "Victory!" : "Game over"}</h2>
          <p className="dm-winline">
            {winners.length > 1 ? "Shared victory: " : "Winner: "}
            {winners.map((w) => names[w] || w).join(" & ")}
          </p>
          <table className="dm-scores">
            <thead><tr><th></th><th>VP</th><th>Turns</th><th></th></tr></thead>
            <tbody>
              {ranked.map((p) => (
                <tr key={p} className={"dm-score-row" + (winners.includes(p) ? " dm-win" : "")}
                  onClick={() => setDeckView(p)} title="See this player's final deck">
                  <td>{names[p] || p}{p === myId ? " (you)" : ""}</td>
                  <td>{scores[p]?.vp ?? "?"}</td>
                  <td>{scores[p]?.turns ?? "?"}</td>
                  <td className="dm-score-deck">deck &rsaquo;</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="dm-prompt-actions">
            <button className="btn btn-gold" onClick={leaveToLobby}>Back to lobby</button>
            <button className="btn btn-outline" onClick={() => setGameOverDismissed(true)}>View board</button>
          </div>
        </div>
      </div>
    );
  };

  const renderRules = () => (
    <CreateModal title="How to play" onClose={() => setShowRules(false)}>
      <div className="dm-rules">
        <p>Build the best deck. Each turn: play one Action (A), then buy a card (B), then everything you played and held is discarded and you draw 5 (C).</p>
        <p><b>Action phase</b> — play Action cards from your hand (you start with 1 Action; cards can grant more).</p>
        <p><b>Buy phase</b> — play Treasures for coins, then buy cards from the Supply into your discard pile. No Treasures after you buy.</p>
        <p>The game ends when the Province pile — or any three piles — empty. Most victory points in your whole deck wins.</p>
        <p>Attack cards hit the other players; a Moat (revealed from hand) blocks an attack against you.</p>
        <p><b>Reading a card</b> — right-click it (or press and hold on a touch screen) to see its full text, any time, anywhere on the board. A plain click does whatever the card is for right now: play it, buy it, or pick it.</p>
      </div>
    </CreateModal>
  );

  // ─── screens ───────────────────────────────────────────────────────────────
  if (screen === "lobby") {
    return (
      <div className="app dm" style={{ "--lby-accent": "#b08d57" }}>
        <style>{dmStyles}</style>
        {/* No Rules button in the lobby — the how-to-play is reachable from the
            in-game Menu (☰), where a player who's actually at a table needs it. */}
        <LobbyHeader onBack={onExit} title="Dontminion" user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : "Guest"} />
        <LobbyCreateRow onCreate={() => setShowCreateModal(true)} onJoin={joinGame}
          onRefresh={fetchGames} refreshing={loadingGames} />
        {showCreateModal && (
          <CreateModal title="New Game" onClose={() => setShowCreateModal(false)}>
            <CmRow label="Opponent">
              <CmSeg options={[{ value: "ai", label: "vs AI" }, { value: "friend", label: "vs Friends" }]}
                value={createOpp} onChange={setCreateOpp} />
            </CmRow>
            {createOpp === "ai" ? (
              /* Two labelled segments on ONE line. Stacked they cost 126px of a
                 modal that must not itself scroll, and the bot count is three
                 single digits — it never needed a full row. The 1:2 split is
                 what keeps "Big Money" on one line at phone width. */
              <div className="cm-row dm-cm-two">
                <div className="dm-cm-col">
                  <span className="cm-label">Bots</span>
                  <CmSeg options={[1, 2, 3].map((n) => ({ value: n, label: String(n) }))}
                    value={createBots} onChange={setCreateBots} />
                </div>
                <div className="dm-cm-col dm-cm-botstyle">
                  <span className="cm-label">Bot style</span>
                  <CmSeg options={BOTS.map((b) => ({ value: b.id, label: b.name, title: b.title }))}
                    value={createBotKind} onChange={setCreateBotKind} />
                </div>
              </div>
            ) : (
              <CmRow label="Players">
                <CmSeg options={[2, 3, 4].map((n) => ({ value: n, label: String(n) }))}
                  value={createPlayers} onChange={setCreatePlayers} />
              </CmRow>
            )}
            <CmRow label="Expansions">
              {/* The LIST scrolls, not the modal — the set count grows every
                  phase, and a picker that pushes Create below the fold is the
                  thing that breaks first. Select all is a plain toggle. */}
              <div className="dm-checks">
                {expansionOptions.map((ex) => {
                  const on = createExps.includes(ex.id);
                  return (
                    <button key={ex.id} type="button"
                      className={"dm-check" + (on ? " dm-check-on" : "")}
                      onClick={() => setCreateExps((s) => on
                        ? s.filter((x) => x !== ex.id)
                        : [...s, ex.id])}>
                      {on ? "☑" : "☐"} {ex.name}
                    </button>
                  );
                })}
              </div>
              <button type="button"
                className={"dm-check dm-check-all" + (allExpsOn ? " dm-check-on" : "")}
                onClick={() => setCreateExps(allExpsOn ? [] : expansionOptions.map((e) => e.id))}>
                {allExpsOn ? "☑" : "☐"} Select all
              </button>
            </CmRow>
            {requireOptions.length > 0 && (
              /* Not a plain CmRow: the label sits INLINE with the chips (see
                 .dm-req-row) because the modal has no vertical budget for
                 another stacked row. */
              <div className="cm-row dm-req-row">
                <span className="cm-label">Require</span>
                {/* Guarantee the random 10 contains at least one card giving
                    each checked bonus. Multi-select, none checked by default —
                    an unchecked list deals exactly the board it always did. */}
                <div className="dm-checks-req">
                  {requireOptions.map((rq) => {
                    const on = createReqs.includes(rq.id);
                    return (
                      <button key={rq.id} type="button"
                        className={"dm-check" + (on ? " dm-check-on" : "")}
                        onClick={() => setCreateReqs((s) => on
                          ? s.filter((x) => x !== rq.id)
                          : [...s, rq.id])}>
                        {on ? "☑" : "☐"} {rq.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="cm-hint">
              {!createExps.length
                ? "Pick at least one expansion to deal a Kingdom from."
                : createReqs.length
                  ? `10 kingdom piles are dealt at random from the enabled expansions, always including a card that gives ${createReqs
                      .map((r) => requireOptions.find((x) => x.id === r)?.label || r)
                      .join(", ")}.`
                  : "10 kingdom piles are dealt at random from the enabled expansions."}
            </div>
            <div className="cm-footer">
              <span className="cm-summary">
                {createOpp === "ai"
                  ? `You + ${createBots} ${BOTS.find((b) => b.id === createBotKind)?.name || "bot"} bot${createBots > 1 ? "s" : ""}`
                  : `Up to ${createPlayers} players`}
                {createExps.length
                  ? " · " + createExps.map((e) => expansionOptions.find((x) => x.id === e)?.name || e).join(" + ")
                  : ""}
              </span>
              <button className="btn btn-gold cm-create" disabled={!createExps.length}
                onClick={createGame}>Create</button>
            </div>
          </CreateModal>
        )}
        {/* Mobile-only tab bar (mirrors Spender Duel): the three columns can't
            sit side by side on a phone, so pick ONE section to show. Hidden on
            wide screens (CSS) where all three columns render at once. */}
        <div className="dm-lobby-tabs" role="tablist">
          {[
            ["open", "Open", openGames.length],
            ["active", "Active", myGames.length],
            ["history", "History", history.length],
          ].map(([key, label, count]) => (
            <button key={key} type="button" role="tab" aria-selected={lobbyTab === key}
              className={"dm-lobby-tab" + (lobbyTab === key ? " sel" : "")}
              onClick={() => setLobbyTab(key)}>
              {label}{count > 0 ? <span className="dm-lobby-tab-count">{count}</span> : null}
            </button>
          ))}
        </div>
        <div className={"dm-lobby-cols tab-" + lobbyTab}>
          <div className="dm-section open-section">
            <LobbySectionHd title="Open Games" note="join a table" />
            {openGames.length === 0 && <div className="lby-empty">No open games — create one!</div>}
            {openGames.map((g) => (
              <div key={g.id} className="lby-card">
                <div className="lby-card-info">
                  <div className="lby-card-title">{g.host_name || "?"}'s table</div>
                  <div className="lby-card-meta">
                    {g.player_count}/{g.max_players} players · {(g.expansions || []).join(" + ")} · {timeAgo(g.created_at)}
                  </div>
                </div>
                <div className="lby-card-actions">
                  {g.host_id === myId
                    ? <>
                        <button className="btn btn-gold" onClick={() => resumeGame(g.id)}>Return</button>
                        <button className="btn btn-outline" onClick={() => cancelGame(g.id)}>Cancel</button>
                      </>
                    : <button className="btn btn-gold" onClick={() => joinGame(g.id)}>Join</button>}
                </div>
              </div>
            ))}
          </div>
          <div className="dm-section active-section">
            <LobbySectionHd title="My Games" note={authUser?.session_token ? "in progress" : "sign in to track games"} />
            {myGames.map((g) => (
              <div key={g.id} className="lby-card">
                <div className="lby-card-info">
                  <div className="lby-card-title">vs {(g.opponents || []).join(", ") || "…"}</div>
                  <div className="lby-card-meta">
                    {g.your_turn ? <TurnBadge mine>your turn</TurnBadge> : g.status}
                    {" · "}{timeAgo(g.updated_at)}
                  </div>
                </div>
                <div className="lby-card-actions">
                  <button className="btn btn-gold" onClick={() => resumeGame(g.id)}>Resume</button>
                </div>
              </div>
            ))}
            {myGames.length === 0 && <div className="lby-empty">Nothing in progress.</div>}
          </div>
          <div className="dm-section history-section">
            <LobbySectionHd title="History" note="finished games" />
            {history.map((g) => {
              const line = historyScores(g);
              // Dominion breaks a VP tie on fewer turns taken, so a shared win
              // is rare but real — CoC's history has the same three states.
              const tie = g.you_won && (g.winners || []).length > 1;
              return (
                <div key={g.id} className="lby-card">
                  <div className="lby-card-info">
                    <div className="lby-card-title">
                      <span className={"hist-result " + (tie ? "tie" : g.you_won ? "won" : "lost")}>
                        {tie ? "Tie" : g.you_won ? "Won" : "Lost"}
                      </span>
                      <span className="hist-scores"> vs {(g.opponents || []).join(", ")}
                        {line ? <> <span className="hist-score-num">{line}</span></> : null}
                      </span>
                    </div>
                    <div className="lby-card-meta">{timeAgo(g.updated_at)}</div>
                  </div>
                </div>
              );
            })}
            {history.length === 0 && <div className="lby-empty">No finished games yet.</div>}
          </div>
        </div>
        {toast && <div className="dm-toast">{toast}</div>}
      </div>
    );
  }

  if (screen === "waiting") {
    const count = Object.keys(names).length;
    const cap = roomData?.max_players || 4;
    const isHost = roomData?.host === myId;
    return (
      <div className="app dm" style={{ "--lby-accent": "#b08d57" }}>
        <style>{dmStyles}</style>
        <LobbyHeader onBack={leaveToLobby} backLabel="← Leave" title="Dontminion" user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : "Guest"} />
        <div className="dm-wait">
          <h2>Room {roomId}</h2>
          <p className="dm-wait-note">Share this code — friends join with it from the lobby.</p>
          <p className="dm-wait-note">{(roomData?.expansions || []).map((e) => EXPANSIONS.find((x) => x.id === e)?.name || e).join(" + ")}</p>
          <div className="dm-wait-players">
            Players ({count}/{cap})
            <ul>
              {Object.entries(names).map(([p, n]) => (
                <li key={p}>{n}{p === roomData?.host ? " ♛" : ""}{p === myId ? " (you)" : ""}</li>
              ))}
            </ul>
          </div>
          {isHost
            ? <button className="btn btn-gold btn-full" disabled={count < 2}
                onClick={() => send({ action: "start" })}>
                {count < 2 ? "Waiting for players…" : `Deal & Start (${count} players)`}
              </button>
            : <div className="lby-loading"><span className="lby-spinner" /> Waiting for the host to start…</div>}
        </div>
        {toast && <div className="dm-toast">{toast}</div>}
      </div>
    );
  }

  if (!game) {
    return (
      <div className="app dm" style={{ "--lby-accent": "#b08d57" }}>
        <style>{dmStyles}</style>
        <div className="lby-loading dm-center"><span className="lby-spinner" /> Loading game…</div>
      </div>
    );
  }

  // ── game screen ──
  return (
    <div className="app dm dm-gamescreen" style={{ "--lby-accent": "#b08d57" }}>
      <style>{dmStyles}</style>
      {/* Title bar only — the game's NAME, centred, like every other game on the
          site. Whose turn it is and which phase you're in are already carried by
          the seat boxes (acting badge) and the resource bar's hint. The two side
          slots are equal-flex so the title centres on the PAGE, not merely in
          the gap left over by the menu. */}
      <div className="dm-top">
        <div className="dm-top-side">
          <GameMenu items={[
            { label: "Back to lobby", onClick: leaveToLobby },
            !over && { label: "Abandon game", onClick: () => setConfirmAbandon(true), danger: true },
            { label: "Rules", onClick: () => setShowRules(true) },
          ].filter(Boolean)} label="Menu" />
        </div>
        <h1 className="dm-title">Dontminion</h1>
        <div className="dm-top-side dm-top-right">
          {reconnecting && !connected && <span className="dm-reconn">reconnecting…</span>}
        </div>
      </div>

      <div className="dm-main">
        <div className="dm-side">
          <button className="btn btn-ghost dm-kingdom-btn" onClick={() => setShowKingdom(true)}>🃏 Kingdom</button>
          <div className="dm-pboxes">{seatOrder.map(renderPlayerBox)}</div>
          <div className="dm-trash" onClick={() => setShowTrash((s) => !s)}>
            Trash ({(game.trash || []).length}) {showTrash ? "▾" : "▸"}
            {showTrash && (
              <div className="dm-trash-list">
                {(game.trash || []).length ? game.trash.join(", ") : "empty"}
              </div>
            )}
          </div>
          <div className="dm-log" ref={logRef}>
            {/* CHRONOLOGICAL: oldest at the top, newest appended at the bottom,
                and the view auto-scrolls to keep the newest line visible. Reads
                the way the turn actually happened, which matters here because
                sub-effects INDENT under the play that caused them — newest-first
                showed every effect above its own cause. Capped to the most
                recent 200 lines. */}
            {buildLogLines(game.log || [], names).slice(-200).map((l) => (
              <div key={l.key}
                className={"dm-log-line" + (l.d ? ` dm-log-d${l.d}` : "") + (l.turn ? " dm-log-turn" : "")}>
                {l.text}
              </div>
            ))}
          </div>
        </div>

        <div className="dm-center-col">
          {focusOpp && renderOppPlay(focusOpp)}
          {renderPrompt()}
          <div className="dm-supply">
            <div className="dm-supply-row dm-basics">{basicsRowFor(game.supply).map(renderPile)}</div>
            <div className="dm-supply-row dm-kingdom">{kingdomByCost.map(renderPile)}</div>
          </div>
          <div className="dm-me">
            {!over && game.turn === myId && (
              <div className="dm-resbar">
                <span>Actions <b><Pop n={game.actions} /></b></span>
                <span>Buys <b><Pop n={game.buys} /></b></span>
                <span>Money <b>$<Pop n={game.coins} /></b></span>
                {bridges > 0 && <span>Cards cost <b>−<Pop n={bridges} /></b></span>}
                {hasModalPrompt && promptMin
                  ? <button className="btn btn-gold btn-sm dm-reshint-btn"
                      onClick={() => setPromptMin(false)}><FitLabel>{promptCardName}: make your choice ▸</FitLabel></button>
                  : resHint ? <span className="dm-reshint">{resHint}</span> : null}
              </div>
            )}
            {!over && game.turn !== myId && hasModalPrompt && promptMin && (
              <div className="dm-resbar">
                <button className="btn btn-gold btn-sm dm-reshint-btn"
                  onClick={() => setPromptMin(false)}><FitLabel>{promptCardName}: make your choice ▸</FitLabel></button>
              </div>
            )}
            <div className="dm-inplay">
              {(mySeat?.duration_view || []).flatMap((e, i) => [
                <div key={"d" + i} className="dm-durwrap" title="Duration — stays in play">
                  <DmCardFace name={e.card} card={cards[e.card]} small onInfo={() => setCardInfo(e.card)} />
                </div>,
                ...(e.riders || []).map((r, j) => (
                  <div key={"d" + i + "r" + j} className="dm-durwrap">
                    <DmCardFace name={r} card={cards[r]} small onInfo={() => setCardInfo(r)} />
                  </div>
                )),
              ])}
              {(mySeat?.in_play || []).map((c, i) => (
                <DmCardFace key={inPlayKeys[i]} name={c} card={cards[c]} small onInfo={() => setCardInfo(c)} />
              ))}
              {(mySeat?.in_play || []).length === 0 && (mySeat?.duration_view || []).length === 0
                && <span className="dm-zone-hint">in play</span>}
              {(mySeat?.island || []).length > 0 && (
                <DmMatChip emoji="🏝" count={mySeat.island.length} label="Island mat"
                  cards={mySeat.island} onView={setMatView} />
              )}
              {(mySeat?.village_count || 0) > 0 && (
                <DmMatChip emoji="🏕" count={mySeat.village_count} label="Native Village mat"
                  cards={mySeat.village_mat} onView={setMatView} />
              )}
              {(mySeat?.dur_aside_count || 0) > 0 && (
                <DmMatChip emoji="⏳" count={mySeat.dur_aside_count} label="Set aside"
                  cards={mySeat.dur_aside} onView={setMatView} />
              )}
            </div>
            <div className="dm-handrow">
              <div className="dm-mypiles">
                <DmPile kind="deck" label="deck" count={mySeat?.deck_count ?? 0} />
                <DmPile kind="discard" label="discard" count={mySeat?.discard_view?.count ?? 0}
                  top={mySeat?.discard_view?.top} card={cards[mySeat?.discard_view?.top]}
                  onInfo={() => setCardInfo(mySeat?.discard_view?.top)} />
              </div>
              <div className="dm-pile-slot dm-myhand">
                <div className="dm-hand">
                  {(mySeat?.hand || []).map((c, i) => {
                    const t = typesFor(c);
                    const playable = !iAmActor && ((inAction && t.includes("action") && game.actions > 0)
                      || (inBuy && t.includes("treasure") && !bought));
                    return <DmCardFace key={handKeys[i]} name={c} card={cards[c]}
                      highlight={playable} disabled={!playable && !over}
                      onClick={() => handClick(c)} onInfo={() => setCardInfo(c)} />;
                  })}
                  {(mySeat?.hand || []).length === 0 && <span className="dm-zone-hint">hand empty</span>}
                </div>
                <span className="dm-pile-count">hand <Pop n={(mySeat?.hand || []).length} /></span>
              </div>
              <div className="dm-turnbtns">
                {!over && (
                  <button className="btn btn-outline dm-undo" disabled={!canUndo}
                    title={canUndo
                      ? "Take back your last action — press again to keep stepping back (until the turn started or new information was revealed)"
                      : "Nothing to undo — undo unlocks after a move of yours that revealed no new information"}
                    onClick={() => canUndo && mv({ type: "undo_turn" })}>↩ Undo{(game.undo_depth || 0) > 1 ? ` (${game.undo_depth})` : ""}</button>
                )}
                {inBuy && handTreasures && !bought && (
                  <button className="btn btn-gold" onClick={() => mv({ type: "play_all_treasures" })}>Play all treasures</button>
                )}
                {(inAction || inBuy) && (
                  <button className="btn btn-outline" onClick={() => mv({ type: "end_phase" })}>
                    {inAction ? "To buy phase →" : "End turn"}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {confirmAbandon && (
        <div className="dm-backdrop" onClick={() => setConfirmAbandon(false)}>
          <div className="dm-modal" onClick={(e) => e.stopPropagation()}>
            <h2>Abandon this game?</h2>
            <div className="dm-prompt-actions">
              <button className="btn btn-danger" onClick={abandonGame}>Abandon</button>
              <button className="btn btn-outline" onClick={() => setConfirmAbandon(false)}>Keep playing</button>
            </div>
          </div>
        </div>
      )}
      {showKingdom && (
        <div className="dm-backdrop" onClick={() => setShowKingdom(false)}>
          <div className="dm-modal dm-kingdom-modal" onClick={(e) => e.stopPropagation()}>
            <h2>This game's Kingdom</h2>
            <p className="dm-wait-note">{(roomData?.expansions || []).map((e) => EXPANSIONS.find((x) => x.id === e)?.name || e).join(" + ")}</p>
            <div className="dm-kgrid">
              {kingdomByCost.map((n) => (
                <div key={n} className="dm-pile-slot">
                  <DmCardFace name={n} card={cards[n]} onInfo={() => setCardInfo(n)} />
                  <span className="dm-pile-count">{game.supply[n] ?? 0} left</span>
                </div>
              ))}
            </div>
            <h3>Basic supply</h3>
            <div className="dm-kgrid">
              {basicsRowFor(game.supply).map((n) => (
                <div key={n} className="dm-pile-slot">
                  <DmCardFace name={n} card={cards[n]} onInfo={() => setCardInfo(n)} />
                  <span className="dm-pile-count">{game.supply[n] ?? 0} left</span>
                </div>
              ))}
            </div>
            <div className="dm-prompt-actions">
              <button className="btn btn-gold" onClick={() => setShowKingdom(false)}>Close</button>
            </div>
          </div>
        </div>
      )}
      {renderPromptModal()}
      {matView && (
        <div className="dm-backdrop" onClick={() => setMatView(null)}>
          <div className="dm-modal dm-kingdom-modal dm-matview" onClick={(e) => e.stopPropagation()}>
            <h2>{matView.label}</h2>
            <p className="dm-wait-note">{matView.cards.length} card{matView.cards.length === 1 ? "" : "s"}</p>
            <div className="dm-kgrid">
              {matView.cards.map((n, i) => (
                <div key={n + "#" + i} className="dm-pile-slot">
                  <DmCardFace name={n} card={cards[n]} onInfo={() => setCardInfo(n)} />
                </div>
              ))}
            </div>
            <div className="dm-prompt-actions">
              <button className="btn btn-gold" onClick={() => setMatView(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
      {cardInfo && cards[cardInfo] && (
        <div className="dm-backdrop" onClick={() => setCardInfo(null)}>
          <div className={"dm-modal dm-cardinfo " + faceClass(cards[cardInfo].types)} onClick={(e) => e.stopPropagation()}>
            <div className="dm-cardinfo-cols">
              <div className="dm-cardinfo-face">
                <DmCardFace name={cardInfo} card={cards[cardInfo]} />
              </div>
              <div className="dm-cardinfo-detail">
                <h2>{cardInfo}</h2>
                <p className="dm-cardinfo-meta">
                  Cost ${cards[cardInfo].cost}
                  {effCost(cardInfo) !== printedCost(cardInfo) ? ` (now $${effCost(cardInfo)})` : ""}
                  {" · "}{(cards[cardInfo].types || []).map((t) => TYPE_LABEL[t] || t).join(" – ")}
                  {game.supply?.[cardInfo] != null ? ` · ${game.supply[cardInfo]} left in the Supply` : ""}
                </p>
                <p className="dm-cardinfo-text">{cards[cardInfo].text}</p>
              </div>
            </div>
            <div className="dm-prompt-actions">
              <button className="btn btn-gold" onClick={() => setCardInfo(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
      {showRules && renderRules()}
      {renderGameOver()}
      {toast && <div className="dm-toast">{toast}</div>}
    </div>
  );
}
