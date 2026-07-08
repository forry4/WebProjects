import { Fragment, useState, useEffect, useRef, useCallback } from "react";

// ─── Config ────────────────────────────────────────────────────────────────
const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const COC_WS = WS_RAW.replace(/\/ws$/, "/coc/ws");
const COC_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/coc");

const TILE_HEX = {
  burgundy: "#a3263a",   // castle  -> crimson (the "burgundy" key is the backend's castle color)
  blue: "#3d6ea5",       // ship
  gray: "#6b6f76",       // mine
  green: "#8cc873",      // livestock -> light green
  beige: "#7a5f33",      // building (darker tan — the colorful building icons sit on top)
  yellow: "#fdd520",     // monastery -> bright yellow
};
const GOODS_HEX = {
  amber: "#e0a526", rose: "#d6678b", jade: "#3fae8e",
  cobalt: "#3b6fd0", plum: "#8a5cc0", rust: "#c0552f",
};
// The 6 territory colors, in the backend's board.COLORS order (drives the bonus strip).
const BOARD_COLORS = ["burgundy", "blue", "gray", "green", "beige", "yellow"];
// Region-completion VP has two parts (mirrors tiles.PHASE_BONUS / AREA_SCORE):
//  • phase bonus — a time bonus that shrinks each phase (finish regions early!)
//  • size bonus  — fixed VP by the region's number of spaces (1–8)
const PHASE_BONUS = { A: 10, B: 8, C: 6, D: 4, E: 2 };
const AREA_SCORE = [1, 3, 6, 10, 15, 21, 28, 36];   // completing a size-n region (n=1..8)
const TYPE_LABEL = {
  castle: "Castle", ship: "Ship", mine: "Mine",
  livestock: "Livestock", building: "Building", monastery: "Monastery",
};
// Fixed per-phase depot layout — mirrors tiles.DEPOT_PLAN (a deliberate house
// variant: each numbered depot always refills with the SAME two tile types).
// We keep a faint colored hex outline ("ghost") in any planned slot whose tile
// has been taken, so players can remember what goes where across phases. Colors
// are the tile-type colors from TILE_HEX above.
const DEPOT_PLAN_COLORS = {
  1: ["blue", "beige"],       // ship + building
  2: ["burgundy", "yellow"],  // castle + monastery
  3: ["green", "beige"],      // livestock + building
  4: ["blue", "beige"],       // ship + building
  5: ["gray", "yellow"],      // mine + monastery
  6: ["green", "beige"],      // livestock + building
};
// Tile color -> its type label (inverse of TILE_HEX's type comments), for ghost tooltips.
const COLOR_TYPE_LABEL = {
  burgundy: "Castle", blue: "Ship", gray: "Mine",
  green: "Livestock", beige: "Building", yellow: "Monastery",
};
// Friendly display name for a space's color (the backend's castle color is "burgundy",
// but the castle tiles are crimson, so show "crimson" to the player).
const colorLabel = (c) => (c === "burgundy" ? "crimson" : c);
// Ordered render slots for a numbered depot, one per planned tile type: each slot
// is either the tile currently sitting there (matched by color) or a ghost outline
// (taken). Because the slots stay in the fixed plan order, taking the LEFT tile
// leaves a ghost in its place and does NOT shift the right tile left — slot
// identity is stable across takes. Any unexpected extra tile is appended.
function depotSlots(d, hexes) {
  const present = [...(hexes || [])];
  const slots = [];
  for (const c of DEPOT_PLAN_COLORS[d] || []) {
    const i = present.findIndex((t) => t.color === c);
    if (i >= 0) slots.push({ tile: present.splice(i, 1)[0] });  // matching tile present
    else slots.push({ ghost: c });                              // planned but taken → ghost
  }
  for (const t of present) slots.push({ tile: t });             // defensive: unexpected leftovers
  return slots;
}
// Two-letter building codes so tiles are identifiable without mousing over.
const BUILDING_ABBR = {
  market: "Mk", carpenter: "Cp", church: "Ch", warehouse: "Wh",
  boarding: "Bo", bank: "Bk", townhall: "TH", watchtower: "WT",
};
const BUILDING_DESC = {
  market: "Market — take a ship or livestock tile from a depot.",
  carpenter: "Carpenter's Workshop — take a building tile from a depot.",
  church: "Church — take a mine, monastery, or castle tile from a depot.",
  warehouse: "Warehouse — immediately sell a goods type.",
  boarding: "Boarding House — gain 4 workers.",
  bank: "Bank — gain 2 silver.",
  townhall: "Town Hall — immediately place an additional tile.",
  watchtower: "Watchtower — score 4 VP.",
};
// Short on-tile label: monastery number, building code, livestock animal+count.
function tileGlyph(t) {
  if (!t) return "";
  if (t.type === "monastery") return String(t.effect_id);
  if (t.type === "building") return BUILDING_ABBR[t.building] || "B";
  if (t.type === "livestock") return (t.animal?.[0]?.toUpperCase() || "L") + t.count;
  return "";
}
// Full mouse-over description of what a tile does.
function tileDesc(t, board) {
  if (!t) return "";
  if (t.kind === "goods") {
    const n = board ? board.goods_colors.indexOf(t.color) + 1 : "?";
    return `#${n} goods — sell with die ${n} to gain 1 silver and 2 VP per good (2-player).`;
  }
  switch (t.type) {
    case "castle": return "Castle — when placed, take an immediate bonus action (a die of your choice).";
    case "ship": return "Ship — when placed, take all goods from one depot and advance the turn order.";
    case "mine": return "Mine — gain 1 silver at the end of each phase.";
    case "livestock": return `Livestock (${t.animal} ×${t.count}) — score VP for the animals; same-type animals in a pasture re-score.`;
    case "building": return BUILDING_DESC[t.building] || "Building.";
    case "monastery": {
      const d = board?.monastery_meta?.[t.effect_id];
      return `Monastery #${t.effect_id}${d ? " — " + d : " — special effect."}`;
    }
    default: return TYPE_LABEL[t.type] || "Tile";
  }
}

// Full building name (for the move log).
const BUILDING_NAME = {
  market: "Market", carpenter: "Carpenter's Workshop", church: "Church",
  warehouse: "Warehouse", boarding: "Boarding House", bank: "Bank",
  townhall: "Town Hall", watchtower: "Watchtower",
};
// Short name for a tile in the move log, e.g. "a Ship", "Monastery #5", "Market".
function tileName(t) {
  if (!t) return "a tile";
  if (t.kind === "goods") return "goods";
  switch (t.type) {
    case "castle": return "a Castle";
    case "ship": return "a Ship";
    case "mine": return "a Mine";
    case "monastery": return `Monastery #${t.effect_id}`;
    case "building": return BUILDING_NAME[t.building] || "a Building";
    case "livestock": return `Livestock (${t.animal || "?"}${t.count ? " ×" + t.count : ""})`;
    default: return TYPE_LABEL[t.type] || "a tile";
  }
}
// Display name for a log record's source tile/ability (`via`), appended in parens so
// ability-driven actions read "took a Ship (Market)" / "gained 4 workers (Boarding House)".
function viaLabel(via) {
  if (!via) return "";
  if (via.slice(0, 10) === "monastery:") return `Monastery #${via.slice(10)}`;
  if (via === "ship") return "Ship";
  if (via === "castle") return "Castle";
  return BUILDING_NAME[via] || "a tile";
}
// Descriptive move-log line built from the data already in each record (tile, depot, …).
// `board` supplies the goods number (goods are named "#N goods", never by color). The
// source-tile parenthetical (`via`) + any VP are appended by the log renderer, NOT here.
function moveText(m, board) {
  const t = m.tile;
  const gnum = (c) => (board ? board.goods_colors.indexOf(c) + 1 : "?");
  switch (m.type) {
    case "take_hex": return `took ${tileName(t)} from depot ${m.depot}`;
    case "place_tile": return `placed ${tileName(t)}`;
    case "buy_black": return `bought ${tileName(t)} from the black depot`;
    case "monastery6_take": return `took ${tileName(t)}`;
    case "building_take": return `took ${tileName(t)}`;
    case "discard_storage": return `discarded ${tileName(t)}`;
    case "place_starting_castle": return "placed their starting castle";
    case "sell_goods": return `sold ${m.count} #${gnum(m.color)} goods`;
    case "take_workers": return "took 2 workers";
    case "adjust_die": return m.frm != null ? `adjusted a ${m.frm} to a ${m.to}` : `adjusted a die to a ${m.to}`;
    case "ship_take_goods": return `took goods from depot ${m.depot}`;
    case "ship_adjacent_take": return `took goods from depot ${m.depot}`;
    case "build_gain":                                   // immediate-gain building effect
      if (m.workers) return `gained ${m.workers} worker${m.workers === 1 ? "" : "s"}`;
      if (m.silver) return `gained ${m.silver} silver`;
      if (m.vp) return `gained ${m.vp} VP`;
      return "used a building";
    case "building_effect": return `used ${BUILDING_NAME[m.building] || "a building"}`;  // legacy saved games
    case "monastery_placed": return `placed Monastery #${m.effect_id}`;
    case "area_complete": return "completed a region";
    case "bonus_tile": return `earned a ${colorLabel(m.color)} bonus tile`;
    case "livestock_score": return `scored ${m.animal || "livestock"}`;
    case "track_advance": return `advanced ${m.spaces} on the turn track`;
    case "end_turn": return "ended their turn";
    case "undo_turn": return "undid their turn";
    case "skip_pending": return "skipped";
    case "roll": return `rolled a ${m.d0} and a ${m.d1}`;
    case "mine_income": return `gained ${m.silver} silver from ${m.mines} mine${m.mines === 1 ? "" : "s"}`;
    case "monastery_income": return `gained ${m.workers} worker${m.workers === 1 ? "" : "s"} from Monastery ${m.effect}`;
    case "phase_end": return `— Phase ${m.phase} ended —`;
    default: return m.type;
  }
}

// ─── Tile icons ──────────────────────────────────────────────────────────────
// Little monochrome SVG icons (drawn in a 0..24 box, single color `c`). ship /
// castle / mine sit on dark tiles, so they're drawn in a light glyph; livestock
// animals sit on the light-green pasture, so they're dark with small white facial
// details to keep cow / pig / sheep distinguishable at tiny sizes.
const ICON = {
  ship: (c) => (<>
    <path d="M11 2 L11 14 L3.5 14 Z" fill={c} />
    <path d="M12.7 5 L12.7 14 L19 14 Z" fill={c} />
    <path d="M2.5 15.5 H21.5 L18.5 21 H5.5 Z" fill={c} />
  </>),
  castle: (c) => (
    <path fill={c} d="M3 21 V8 H5 V11 H7 V8 H9 V11 H11 V8 H13 V11 H15 V8 H17 V11 H19 V8 H21 V21 Z" />
  ),
  mine: (c) => (<>
    <path d="M3 8 Q12 3 21 8 L20 10 Q12 5.5 4 10 Z" fill={c} />
    <path d="M11 8 H13 L12.4 21 H11.6 Z" fill={c} />
  </>),
  // Buildings — themed colors on the beige building tile; holes (doors/windows/
  // clock) use fillRule="evenodd" so the tan tile shows through.
  market: () => (<>
    <path fill="#7ec46a" d="M3 4 H6 V7 Q4.5 8.6 3 7 Z" />
    <path fill="#7ec46a" d="M6 4 H9 V7 Q7.5 8.6 6 7 Z" />
    <path fill="#7ec46a" d="M9 4 H12 V7 Q10.5 8.6 9 7 Z" />
    <path fill="#7ec46a" d="M12 4 H15 V7 Q13.5 8.6 12 7 Z" />
    <path fill="#7ec46a" d="M15 4 H18 V7 Q16.5 8.6 15 7 Z" />
    <path fill="#7ec46a" d="M18 4 H21 V7 Q19.5 8.6 18 7 Z" />
    <path fill="#2f6fb0" d="M5 8.2 H6.8 V20 H5 Z M17.2 8.2 H19 V20 H17.2 Z" />
    <path fill="#2f6fb0" d="M4.5 18 H19.5 V20 H4.5 Z" />
  </>),
  carpenter: () => (<>
    <rect x="4.5" y="3.6" width="15" height="4.6" rx="1.5" fill="#4a3526" />
    <path fill="#9a6b3a" d="M10.4 8.2 H13.6 L13 21 Q12.9 21.8 12 21.8 Q11.1 21.8 11 21 Z" />
  </>),
  church: () => (<>
    <path fill="#e6b41e" d="M11.2 1 H12.8 V2.4 H14.2 V3.8 H12.8 V5.2 H11.2 V3.8 H9.8 V2.4 H11.2 Z" />
    <path fill="#b23a3a" d="M12 5.4 L18.5 12.5 H5.5 Z" />
    <path fill="#9a9aa3" fillRule="evenodd" d="M6.5 12.5 H17.5 V21 H6.5 Z M10.3 21 V16.8 Q12 15.2 13.7 16.8 V21 Z" />
  </>),
  warehouse: () => (<>
    <path fill="#7e9abb" fillRule="evenodd" d="M3 11 L12 5 L21 11 V21 H3 Z M7 13 H17 V21 H7 Z" />
    <path fill="#56729a" d="M7 14.6 H17 V15.6 H7 Z M7 16.8 H17 V17.8 H7 Z M7 19 H17 V20 H7 Z" />
  </>),
  boarding: () => (<>
    <path fill="#9a6b3a" d="M2 7 H4.2 V13 H2 Z" />
    <path fill="#9a6b3a" d="M2 13 H22 V16.6 H2 Z" />
    <path fill="#9a6b3a" d="M19.8 11 H22 V16.6 H19.8 Z" />
    <path fill="#9a6b3a" d="M2 16.6 H3.9 V19 H2 Z M20.1 16.6 H22 V19 H20.1 Z" />
    <path fill="#9a6b3a" d="M4.6 11.2 H11 Q12 11.2 12 12.2 V13 H4.6 Z" />
  </>),
  bank: () => (<>
    <path fill="#c2c6d0" d="M2.5 8 L12 3 L21.5 8 Z" />
    <path fill="#b3b7c2" d="M3.5 8.4 H20.5 V10 H3.5 Z" />
    <path fill="#a6abb7" d="M4.5 10.2 H6.4 V18 H4.5 Z M8.7 10.2 H10.6 V18 H8.7 Z M13.4 10.2 H15.3 V18 H13.4 Z M17.6 10.2 H19.5 V18 H17.6 Z" />
    <path fill="#9498a4" d="M3 18 H21 V20.6 H3 Z" />
  </>),
  townhall: () => (<>
    <rect x="11.4" y="1.6" width="1" height="5" fill="#b23a3a" />
    <path fill="#b23a3a" d="M12.4 1.9 H16.2 L14.7 3.3 L16.2 4.7 H12.4 Z" />
    <path fill="#b23a3a" fillRule="evenodd" d="M9.3 6.6 H14.7 V12 H9.3 Z M10.5 9.5 A1.5 1.5 0 1 1 13.5 9.5 A1.5 1.5 0 1 1 10.5 9.5 Z" />
    <path fill="#b23a3a" fillRule="evenodd" d="M4 12 H20 V21 H4 Z M10.5 21 V15.6 Q12 14.2 13.5 15.6 V21 Z" />
  </>),
  watchtower: () => (<>
    <path fill="#356340" fillRule="evenodd" d="M8 6 H9.6 V4.4 H11.2 V6 H12.8 V4.4 H14.4 V6 H16 V21 H8 Z M10.4 13 V10.6 Q12 8.9 13.6 10.6 V13 Z" />
    <path fill="#284e30" d="M6.5 19 H17.5 V21 H6.5 Z" />
  </>),
  cow: () => (<>
    <path d="M6.5 6 Q4 3.5 2.6 5 Q4 6.2 6.5 7.4 Z" fill="#15100a" />
    <path d="M17.5 6 Q20 3.5 21.4 5 Q20 6.2 17.5 7.4 Z" fill="#15100a" />
    <ellipse cx="12" cy="13" rx="7.6" ry="6.6" fill="#15100a" />
    <ellipse cx="12" cy="16" rx="4.4" ry="2.9" fill="#fff" />
    <circle cx="10.4" cy="16" r="0.7" fill="#15100a" />
    <circle cx="13.6" cy="16" r="0.7" fill="#15100a" />
    <circle cx="9" cy="11" r="1" fill="#fff" />
    <circle cx="15" cy="11" r="1" fill="#fff" />
  </>),
  pig: () => (<>
    <path d="M6 5.5 L10.5 6 L8.5 11 Z" fill="#e493aa" />
    <path d="M18 5.5 L13.5 6 L15.5 11 Z" fill="#e493aa" />
    <ellipse cx="12" cy="13.5" rx="7.6" ry="6.6" fill="#e493aa" />
    <ellipse cx="12" cy="15" rx="3.9" ry="3" fill="#f3d0db" />
    <ellipse cx="10.6" cy="15" rx="0.7" ry="1" fill="#b05f78" />
    <ellipse cx="13.4" cy="15" rx="0.7" ry="1" fill="#b05f78" />
    <circle cx="9" cy="11" r="1" fill="#fff" />
    <circle cx="15" cy="11" r="1" fill="#fff" />
  </>),
  sheep: () => (<>
    {/* round fluffy wool body: solid core + a full ring of bumps */}
    <circle cx="12" cy="12" r="6.4" fill="#888a8f" />
    <circle cx="18.3" cy="12" r="2.6" fill="#888a8f" />
    <circle cx="17.5" cy="15.2" r="2.6" fill="#888a8f" />
    <circle cx="15.2" cy="17.5" r="2.6" fill="#888a8f" />
    <circle cx="12" cy="18.3" r="2.6" fill="#888a8f" />
    <circle cx="8.8" cy="17.5" r="2.6" fill="#888a8f" />
    <circle cx="6.5" cy="15.2" r="2.6" fill="#888a8f" />
    <circle cx="5.7" cy="12" r="2.6" fill="#888a8f" />
    <circle cx="6.5" cy="8.8" r="2.6" fill="#888a8f" />
    <circle cx="8.8" cy="6.5" r="2.6" fill="#888a8f" />
    <circle cx="12" cy="5.7" r="2.6" fill="#888a8f" />
    <circle cx="15.2" cy="6.5" r="2.6" fill="#888a8f" />
    <circle cx="17.5" cy="8.8" r="2.6" fill="#888a8f" />
    {/* white ears poking out of the white face */}
    <ellipse cx="8.7" cy="8.3" rx="1.7" ry="1.8" fill="#fff" transform="rotate(-28 8.7 8.3)" />
    <ellipse cx="15.3" cy="8.3" rx="1.7" ry="1.8" fill="#fff" transform="rotate(28 15.3 8.3)" />
    {/* white face + eyes */}
    <rect x="8.3" y="9.1" width="7.4" height="7.4" rx="3.2" fill="#fff" />
    <circle cx="10.5" cy="12.3" r="0.8" fill="#33312e" />
    <circle cx="13.5" cy="12.3" r="0.8" fill="#33312e" />
  </>),
};

function Icon({ kind, color, size }) {
  const draw = ICON[kind];
  if (!draw) return null;
  return (
    <svg viewBox="0 0 24 24" width={size} height={size}
      style={{ display: "block", filter: "drop-shadow(0 1px 1px rgba(0,0,0,.45))" }}>
      {draw(color)}
    </svg>
  );
}

// What to draw inside a hex tile: an icon for ship/castle/mine, `count`-many animal
// icons for livestock, or the text glyph for monastery (#) / building (code). `px`
// is the hex's pixel size so the icon/glyph scale to the depot, storage, and board.
function TileArt({ tile, px = 70 }) {
  if (!tile) return null;
  const t = tile;
  if (t.type === "ship") return <Icon kind="ship" color="#f3ead8" size={px * 0.56} />;
  if (t.type === "castle") return <Icon kind="castle" color="#f3ead8" size={px * 0.54} />;
  if (t.type === "mine") return <Icon kind="mine" color="#f3ead8" size={px * 0.56} />;
  if (t.type === "building" && ICON[t.building]) return <Icon kind={t.building} color="#15100a" size={px * 0.6} />;
  if (t.type === "livestock" && ICON[t.animal]) {
    const n = t.count || 1;
    const each = n >= 4 ? px * 0.34 : n === 3 ? px * 0.36 : px * 0.42;
    return (
      <div className="coc-animals" style={{ maxWidth: px * 0.92, maxHeight: px * 0.82 }}>
        {Array.from({ length: n }).map((_, i) => (
          <Icon key={i} kind={t.animal} color="#15100a" size={each} />
        ))}
      </div>
    );
  }
  const g = tileGlyph(t);
  return g ? <span className="coc-glyph" style={{ fontSize: px * 0.27 }}>{g}</span> : null;
}

// SVG-native tile art for the duchy board (drawn straight into the hex SVG, so it
// renders reliably — the old <foreignObject> wrapper silently failed to paint).
// `box` is the art-box side in SVG user units; the icon is centered on (cx, cy).
const _ART_SHADOW = { filter: "drop-shadow(0 0.6px 0.6px rgba(0,0,0,.45))" };
function _artIcon(kind, color, cx, cy, s, key) {
  return (
    <g key={key} transform={`translate(${(cx - s / 2).toFixed(2)} ${(cy - s / 2).toFixed(2)}) scale(${(s / 24).toFixed(4)})`}>
      {ICON[kind](color)}
    </g>
  );
}
function TileArtSvg({ tile, cx, cy, box }) {
  if (!tile) return null;
  const t = tile;
  if (t.type === "ship") return <g style={_ART_SHADOW}>{_artIcon("ship", "#f3ead8", cx, cy, box * 0.56)}</g>;
  if (t.type === "castle") return <g style={_ART_SHADOW}>{_artIcon("castle", "#f3ead8", cx, cy, box * 0.54)}</g>;
  if (t.type === "mine") return <g style={_ART_SHADOW}>{_artIcon("mine", "#f3ead8", cx, cy, box * 0.56)}</g>;
  if (t.type === "building" && ICON[t.building]) return <g style={_ART_SHADOW}>{_artIcon(t.building, "#15100a", cx, cy, box * 0.6)}</g>;
  if (t.type === "livestock" && ICON[t.animal]) {
    const n = Math.min(t.count || 1, 4);
    const L = {
      1: { s: 0.56, pos: [[0, 0]] },
      2: { s: 0.46, pos: [[-0.55, 0], [0.55, 0]] },
      3: { s: 0.40, pos: [[-0.56, -0.5], [0.56, -0.5], [0, 0.52]] },
      4: { s: 0.36, pos: [[-0.56, -0.55], [0.56, -0.55], [-0.56, 0.55], [0.56, 0.55]] },
    }[n];
    const e = box * L.s;
    return <g style={_ART_SHADOW}>{L.pos.map(([ox, oy], i) => _artIcon(t.animal, "#15100a", cx + ox * e, cy + oy * e, e, i))}</g>;
  }
  const g = tileGlyph(t);
  return g ? <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central"
    fontFamily="'Cinzel', serif" fontWeight="700" fontSize={(box * 0.42).toFixed(1)} fill="#15100a">{g}</text> : null;
}

function roomCode() { return Array.from({ length: 6 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join(""); }

// Hexagon-ring vertex positions (% of the board box) for the 6 numbered depots,
// depot 1 at top going clockwise; the black depot sits in the center.
const DEPOT_POS = [
  { left: 50, top: 13 },   // 1 top
  { left: 83, top: 35 },   // 2 top-right
  { left: 83, top: 65 },   // 3 bottom-right
  { left: 50, top: 87 },   // 4 bottom
  { left: 17, top: 65 },   // 5 bottom-left
  { left: 17, top: 35 },   // 6 top-left
];

// ─── Minimal WebSocket hook ──────────────────────────────────────────────────
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
  // readyState of the live socket (0 CONNECTING / 1 OPEN / 2 CLOSING / 3 CLOSED / undefined
  // if none) — lets auto-reconnect avoid aborting a still-pending connection (a cold-starting
  // Render can hold the WS in CONNECTING until the service is up).
  const socketReady = useCallback(() => wsRef.current?.readyState, []);
  return { connected, connect, send, disconnect, socketReady };
}

// Relative timestamp for the lobby game lists (mirrors Spender's timeAgo).
function timeAgo(ts) {
  if (!ts) return "";
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// Die faces as dots/pips (1-6) instead of a numeral. Cells of a 3x3 grid:
//   1 2 3 / 4 5 6 / 7 8 9 . Scales with the die via % sizing, so it works for the
// big rolled dice, the white die, and the small depot mini-dice alike.
const PIP_MAP = { 1: [5], 2: [1, 9], 3: [1, 5, 9], 4: [1, 3, 7, 9], 5: [1, 3, 5, 7, 9], 6: [1, 3, 4, 6, 7, 9] };
function Pips({ n }) {
  const on = PIP_MAP[n];
  if (!on) return n;   // non-1..6 (shouldn't happen) — fall back to the numeral
  const set = new Set(on);
  return (
    <span className="coc-pips" aria-label={`die showing ${n}`}>
      {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((i) => <span key={i} className={`coc-pip${set.has(i) ? " on" : ""}`} />)}
    </span>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────-
const css = `
/* Self-hosted fonts (CoC is mounted bare without baseCss, so it carries its own copy;
   the browser dedupes identical @font-face by src url). Metric-matched fallbacks keep
   the layout stable if the real font isn't loaded yet. */
@font-face{font-family:'Cinzel';font-style:normal;font-weight:400 700;font-display:optional;src:url(/fonts/cinzel.latin.woff2) format('woff2')}
@font-face{font-family:'Crimson Pro';font-style:normal;font-weight:300 400;font-display:optional;src:url(/fonts/crimsonpro.latin.woff2) format('woff2')}
@font-face{font-family:'Crimson Pro';font-style:italic;font-weight:300 400;font-display:optional;src:url(/fonts/crimsonpro-italic.latin.woff2) format('woff2')}
@font-face{font-family:'Cinzel Fallback';src:local('Georgia');size-adjust:111.8%}
@font-face{font-family:'Crimson Fallback';src:local('Georgia');size-adjust:87.9%}
/* CoC is mounted bare (the shell early-returns it without Spender's baseCss), so
   reset the body here too — otherwise the browser-default body margin shows an
   unstyled (white) frame around the dark .coc page. */
html,body{margin:0;padding:0;background:#120c0d}
.coc *,.coc *::before,.coc *::after{box-sizing:border-box;margin:0;padding:0}
.coc{--bg:#120c0d;--surface:#1d1416;--surface2:#281a1d;--border:#3e2a2e;--crimson:#a3263a;--crimson-l:#c8455a;
  --gold:#c9a84c;--gold-l:#e8c96a;--text:#ecdfd6;--text-dim:#9c8780;--radius:8px;--radius-lg:14px;
  font-family:'Crimson Pro','Crimson Fallback',Georgia,serif;color:var(--text);background:var(--bg);min-height:100vh}
.coc-wrap{max-width:1100px;margin:0 auto;padding:calc(env(safe-area-inset-top,0px) + 18px) 16px 48px}
.coc-top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:18px;padding-bottom:12px;border-bottom:1px solid var(--border)}
.coc-top-left{display:flex;align-items:center;gap:12px;min-width:0}
.coc-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.5rem;font-weight:700;color:var(--crimson-l);letter-spacing:.03em;white-space:nowrap}
.coc-user{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.78rem;color:var(--text-dim);letter-spacing:.05em}
/* Lobby banner: full-width (flush to screen edges — lives OUTSIDE the centered .coc-wrap),
   back button far left, game name centered (left/right flex:1 so it's truly centered),
   user far right. */
.coc-top.coc-top-lobby{margin-bottom:0;padding:12px 20px;padding-top:calc(env(safe-area-inset-top,0px) + 12px);background:var(--surface);border-bottom:1px solid var(--border)}
.coc-top-lobby .coc-top-left{flex:1 1 0;justify-content:flex-start}
.coc-top-lobby .coc-title{flex:0 0 auto;text-align:center}
.coc-top-lobby .coc-user{flex:1 1 0;text-align:right}
.coc-top-lobby + .coc-wrap{padding-top:18px}
.coc-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:9px 16px;border-radius:var(--radius);border:none;cursor:pointer;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.82rem;letter-spacing:.05em;font-weight:600;transition:all .15s;white-space:nowrap}
.coc-btn:disabled{opacity:.35;cursor:not-allowed}
.coc-btn.gold{background:var(--gold);color:#120c0d}.coc-btn.gold:hover:not(:disabled){background:var(--gold-l)}
.coc-btn.crimson{background:var(--crimson);color:#fff}.coc-btn.crimson:hover:not(:disabled){background:var(--crimson-l)}
.coc-btn.ghost{background:transparent;color:var(--text-dim);border:1px solid var(--border)}.coc-btn.ghost:hover:not(:disabled){color:var(--text);border-color:var(--text-dim)}
.coc-btn.tool{background:var(--surface2);color:var(--gold-l);border:1px solid var(--gold)}.coc-btn.tool:hover:not(:disabled){background:#3a2a18;color:var(--gold-l)}
.coc-btn.outline{background:transparent;color:var(--gold);border:1px solid var(--gold)}.coc-btn.outline:hover:not(:disabled){background:var(--gold);color:#120c0d}
.coc-btn.sm{padding:6px 11px;font-size:.74rem}
/* Lobby create row — a single "+ Create Game ▾" dropdown (vs Friend / vs Bot),
   Join code, and refresh, centered (mirrors Spender's browser-create). */
.coc-create{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:center;margin:6px 0 26px}
.coc-ai-picker-wrap{position:relative;display:inline-flex}
.coc-ai-picker-wrap>.coc-btn.active{background:var(--gold-l)}
.coc-ai-picker{position:absolute;top:calc(100% + 8px);left:50%;transform:translateX(-50%);z-index:30;display:flex;flex-direction:column;gap:6px;align-items:stretch;min-width:180px;max-width:min(92vw,280px);padding:10px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius-lg);box-shadow:0 10px 28px rgba(0,0,0,.5)}
.coc-ai-picker .coc-btn{white-space:nowrap}
.coc-ai-picker-label{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;letter-spacing:.1em;color:var(--text-dim);text-transform:uppercase;text-align:center;margin-top:4px;padding-top:8px;border-top:1px solid var(--border)}
/* Open Games | Active Games | History, side by side (mirrors Spender's lobby-grid). */
.coc-lobby-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px 24px;align-items:start}
.coc-lobby-col{min-width:0}
@media (max-width:1040px){.coc-lobby-grid{grid-template-columns:1fr 1fr}}
@media (max-width:760px){.coc-lobby-grid{grid-template-columns:1fr;gap:0}}
.coc-won{color:#7ec87e;font-weight:700}
.coc-lost{color:#d98a8a;font-weight:700}
.coc-join{display:flex;gap:8px}
.coc-input{padding:9px 12px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-family:'Cinzel','Cinzel Fallback',serif;letter-spacing:.12em;outline:none;width:130px;text-transform:uppercase}
.coc-input:focus{border-color:var(--gold)}
.coc-section-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.68rem;letter-spacing:.18em;color:var(--gold);text-transform:uppercase;margin:18px 0 8px;border-bottom:1px solid var(--border);padding-bottom:6px}
.coc-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:12px 14px;display:flex;align-items:center;gap:12px;margin-bottom:8px}
.coc-card-info{flex:1;min-width:0}
.coc-card-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.85rem}
.coc-card-meta{font-size:.78rem;color:var(--text-dim)}
.coc-empty{text-align:center;padding:28px 16px;color:var(--text-dim);font-style:italic;font-size:.9rem;background:var(--surface2);border-radius:var(--radius);border:1px dashed var(--border)}
.coc-section-hd{display:flex;justify-content:space-between;align-items:center;margin:18px 0 10px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.coc-section-hd .coc-section-title{margin:0;border:none;padding:0}
.coc-muted{font-size:.74rem;color:var(--text-dim)}
.coc-card-actions{display:flex;align-items:center;gap:8px;flex-shrink:0}
.coc-turn-badge{background:var(--gold);color:#120c0d;padding:3px 10px;border-radius:12px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;letter-spacing:.12em;font-weight:700;text-transform:uppercase;white-space:nowrap}
.coc-their-badge{background:var(--surface2);color:var(--text-dim);border:1px solid var(--border);padding:3px 10px;border-radius:12px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;letter-spacing:.1em;text-transform:uppercase;white-space:nowrap}
.coc-spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--gold);border-radius:50%;animation:coc-spin .7s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes coc-spin{to{transform:rotate(360deg)}}
.coc-waiting{max-width:420px;margin:60px auto;text-align:center;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:28px}
.coc-code{font-family:'Cinzel','Cinzel Fallback',serif;font-size:2rem;letter-spacing:.3em;color:var(--gold);background:var(--surface2);border:1px dashed var(--border);border-radius:var(--radius);padding:12px;margin:14px 0;cursor:pointer}
/* game */
.coc-game{display:grid;grid-template-columns:1fr;gap:16px}
.coc-statusbar{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:12px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:10px 14px}
.coc-status-left{display:flex;align-items:center;gap:14px;flex-wrap:wrap;min-width:0}
.coc-pill{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.72rem;letter-spacing:.06em;color:var(--text-dim)}
.coc-goods-left{display:inline-flex;align-items:center;gap:7px;flex-wrap:wrap}
.coc-goods-left-lbl{text-transform:uppercase;opacity:.7}
.coc-goods-mini{display:inline-flex;align-items:center;gap:3px}
.coc-pill b{color:var(--text)}
.coc-vp{display:flex;gap:14px;justify-self:center}
.coc-vp .v{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.8rem}
.coc-vp .v b{color:var(--gold);font-size:1.05rem}
/* Abandon / View Opponent + the opponent's dice, at the right end of the status bar. */
.coc-status-right{display:flex;align-items:center;gap:10px;justify-self:end;flex-wrap:wrap;justify-content:flex-end}
.coc-oppdice{display:inline-flex;gap:4px;align-items:center}
.coc-oppdie{width:26px;height:26px;border-radius:5px;background:#f3ead8;display:inline-flex;align-items:center;justify-content:center;box-shadow:inset 0 0 0 1px rgba(0,0,0,.3),0 1px 2px rgba(0,0,0,.5)}
.coc-oppdie.used{opacity:.4}
/* Workers / silver resources — a bit larger than the plain pills. */
.coc-res{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.92rem;letter-spacing:.04em;color:var(--text-dim);display:inline-flex;align-items:center;gap:5px}
.coc-res b{color:var(--text)}
.coc-res-ic{font-size:1.15rem;line-height:1}
.coc-panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px}
.coc-panel h3{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.68rem;letter-spacing:.16em;color:var(--gold);text-transform:uppercase;margin-bottom:10px}
.coc-depots{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}
.coc-depot{border:1px solid var(--border);border-radius:var(--radius);padding:6px;min-height:78px;background:var(--surface2)}
.coc-depot.match{border-color:var(--gold);box-shadow:0 0 0 1px var(--gold) inset}
/* A ship/monastery is asking which depot to drain — the eligible depots pulse and are clickable. */
.coc-depot-pick,.coc-depot-pick *{cursor:pointer}
.coc-depot-pick{animation:coc-pickpulse 1.1s ease-in-out infinite}
@keyframes coc-pickpulse{0%,100%{box-shadow:0 0 0 2px var(--gold-l) inset,0 0 8px rgba(232,201,106,.35)}50%{box-shadow:0 0 0 2px var(--gold-l) inset,0 0 18px rgba(232,201,106,.75)}}
/* A specific candidate tile in a depot (building-take): pulse its brightness so the
   pickable tile is obvious. A ring/glow would be clipped by the hex clip-path, but a
   brightness filter modifies the tile's own pixels, so it shows through the clip. */
.coc-tile-pick{cursor:pointer;animation:coc-tilepick 1.1s ease-in-out infinite}
@keyframes coc-tilepick{0%,100%{filter:brightness(1.05)}50%{filter:brightness(1.5)}}
/* hexagon board layout */
.coc-board-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
.coc-board-head h3{margin-bottom:0}
.coc-board-hex{position:relative;width:100%;max-width:640px;margin:6px auto 0;aspect-ratio:1/0.9}
.coc-board-hex .coc-depot{position:absolute;width:31%;min-height:96px;padding:6px;transform:translate(-50%,-50%);display:flex;flex-direction:column;justify-content:center}
/* central black depot: a dark box holding the kite of tiles (positioned absolutely) */
.coc-black-center{left:50%;top:50%;box-sizing:border-box;padding:0!important;border:1px solid var(--gold)!important;background:#0c0809!important;border-radius:8px;min-height:0!important;z-index:1}
.coc-blacklbl{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;letter-spacing:.08em;color:var(--gold);text-transform:uppercase}
/* The board panel is the positioning context for the turn-order track (pinned to its
   left gutter, beside the centered hexagon). */
.coc-board-panel{position:relative}
/* turn-order track — boxed, pinned flush to the panel's upper-left gutter */
.coc-track-block{position:absolute;left:14px;top:66px;z-index:3;max-width:340px;background:var(--surface2);border:1px solid var(--gold);border-radius:8px;padding:7px 9px;box-shadow:0 2px 8px rgba(0,0,0,.45)}
.coc-track{display:flex;flex-direction:column;align-items:flex-start;gap:3px;margin:0}
.coc-track-lbl{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;letter-spacing:.1em;color:var(--text-dim);text-transform:uppercase;white-space:nowrap}
.coc-track-spaces{display:flex;gap:3px;align-items:stretch}
.coc-track-space{position:relative;width:38px;min-height:56px;border:1px solid var(--border);border-radius:5px;background:var(--surface);display:flex;flex-direction:column;justify-content:flex-end;gap:2px;padding:18px 3px 5px}
.coc-track-snum{position:absolute;top:3px;left:0;right:0;text-align:center;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.64rem;color:var(--text-dim)}
.coc-track-stack{display:flex;flex-direction:column;gap:6px}
.coc-track-token{border-radius:3px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.56rem;font-weight:700;text-align:center;padding:2px 1px;line-height:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.coc-track-token.start{box-shadow:0 0 0 2px #fff}
.coc-track-cap{display:block;margin:3px 0 0;font-size:.58rem;color:var(--text-dim);font-style:italic}

/* duchy: controls on the left, board on the right */
.coc-duchy-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px}
.coc-duchy-head h3{margin-bottom:0}
.coc-duchy-layout{display:flex;gap:20px;align-items:flex-start}
.coc-duchy-controls{flex:1 1 0;min-width:240px;display:flex;flex-direction:column;gap:14px}
.coc-duchy-board{flex:0 0 auto;width:clamp(300px,50%,560px)}
.coc-duchy-board .coc-hexsvg{max-width:100%;margin:0}
@media (max-width:760px){.coc-duchy-layout{flex-direction:column}.coc-duchy-board{width:100%}}
.coc-depot-n{display:flex;justify-content:center;margin-bottom:5px}
.coc-minidie{position:absolute;transform:translate(-50%,-50%);z-index:3;pointer-events:none;display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;background:#f3ead8;color:#15100a;font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;font-size:.82rem;border-radius:5px;box-shadow:inset 0 0 0 1px rgba(0,0,0,.3),0 1px 3px rgba(0,0,0,.55)}
/* Phone: the hexagonal depot ring + absolutely-positioned turn-order track overflow
   on narrow screens (fixed 70px hex tiles can't fit a 31%-wide depot box). Reflow the
   shared board into a stack — turn order on top, the 6 numbered depots in a 2-col grid,
   the black depot centered below. !important beats the inline left/top/transform. */
@media (max-width:600px){
  .coc-board-hex{display:grid;grid-template-columns:1fr 1fr;gap:8px;justify-items:center;aspect-ratio:auto;max-width:none;margin-top:6px}
  /* track now lives OUTSIDE the board-hex (a panel child); reflow it to a plain block above the board */
  .coc-track-block{position:static;left:auto;top:auto;max-width:none;margin:0 0 8px;padding:6px 7px}
  /* shrink the 7 turn-order spaces so 0-6 fit on one row */
  .coc-track-spaces{flex-wrap:wrap;gap:2px}
  .coc-track-space{width:36px;min-height:50px;padding:16px 2px 4px}
  /* zoom shrinks each depot card AND the black depot's inline-px diamond consistently,
     and (unlike transform) reduces the layout footprint so the board is more compact */
  .coc-board-hex .coc-depot{zoom:.82}
  .coc-board-hex .coc-depot:not(.coc-black-center){position:relative;left:auto!important;top:auto!important;transform:none!important;width:auto!important;min-height:0}
  .coc-board-hex .coc-minidie{position:static!important;left:auto!important;top:auto!important;transform:none!important;margin:0 auto 6px}
  .coc-board-hex .coc-black-center{position:relative;grid-column:1/-1;justify-self:center;left:auto!important;top:auto!important;transform:none!important}
  /* status bar: the 3-zone grid is too tight on phones — stack the left group on its
     own row, then center the score + right group (Abandon/View Opp/opp dice) below */
  .coc-statusbar{display:flex;flex-wrap:wrap;justify-content:center}
  .coc-status-left{width:100%;justify-content:center}
  .coc-status-right{justify-content:center}
  /* lobby create row: let the dropdown + join controls wrap cleanly on phones */
  .coc-create{gap:8px}
  /* In-game "Your Duchy" controls sit in a narrow panel (viewport - wrap 32 - panel 28).
     Only MODESTLY reduce the dice + worker/silver tokens (42/40, vs the 46/44 desktop size)
     and tighten the row gaps, so the Dice row (dice + workers/silver) and the action buttons
     (Take/Sell/End Turn) each stay on ONE row from ~375px up (iPhone SE + all regular
     iPhones) without looking over-shrunk; the rare 360px mini gracefully wraps. NOTE: base
     component rules live LATER in this sheet, so the .coc prefix raises specificity to win. */
  .coc .coc-dicebar{gap:7px}
  .coc .coc-die{width:42px;height:42px;font-size:1.2rem}
  .coc .coc-resbar{gap:10px;margin-left:4px}
  .coc .coc-token{width:40px;height:40px;font-size:1.15rem}
  .coc .coc-token-chip{gap:5px}
  .coc .coc-actions{gap:6px}
  .coc .coc-actions .coc-btn.sm{padding:6px 9px}
  /* fit the "Color bonus" label + all 6 color chips on one phone row (down to ~360px) */
  .coc .coc-bonusbar{gap:4px;padding:7px 6px}
  .coc .coc-bonusbar-lbl{letter-spacing:.05em}
  .coc .coc-bonuschip{gap:2px}
  .coc .coc-bonuschip b{font-size:.8rem}
  .coc .coc-bonus-sw{width:12px;height:12px}
  /* force the color-bonus group onto its OWN fresh line (turn the 2nd divider into a
     full-width zero-height break) so the 6 chips never split depending on how the region
     labels above happen to wrap at a given width */
  .coc .coc-bonus-div ~ .coc-bonus-div{flex-basis:100%;width:auto;height:0;margin:0;background:none}
  /* lobby header: the big centered title overlapped the ← Back button on phones, making
     it un-tappable. Shrink the title and trim the header padding so Back stays clickable
     and the header isn't so tall. */
  .coc-top.coc-top-lobby{padding:9px 12px;padding-top:calc(env(safe-area-inset-top,0px) + 9px);gap:8px}
  .coc-top-lobby .coc-title{font-size:1.05rem}
  .coc-top-lobby .coc-user{font-size:.64rem}
}
.coc-tilewrap{display:flex;flex-wrap:wrap;gap:6px;justify-content:center}
.coc-animals{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:1px;line-height:0}
.coc-glyph{font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;color:#15100a;line-height:1}
.coc-fo{width:100%;height:100%;display:flex;align-items:center;justify-content:center}
.coc-tile{width:70px;height:81px;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:1.05rem;font-family:'Cinzel','Cinzel Fallback',serif;color:#15100a;font-weight:700;transition:transform .1s;line-height:1;clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%)}
.coc-tile:hover{transform:scale(1.1)}
.coc-tile.goods{width:34px;height:34px;border-radius:4px;clip-path:none;color:#fff;font-size:.82rem;text-shadow:0 1px 2px rgba(0,0,0,.7)}
/* Ghost: a taken tile leaves a colored hex OUTLINE (its type color) so the fixed
   per-phase depot layout stays memorable. The element is a full-color hex; the
   ::after carves the center back to the depot surface, leaving a colored rim. */
.coc-tile-ghost{cursor:default;position:relative;opacity:.7}
.coc-tile-ghost:hover{transform:none}
.coc-tile-ghost::after{content:"";position:absolute;inset:3px;background:var(--surface2);clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%)}
.coc-whitedie{display:flex;align-items:center;gap:6px;margin-left:auto}
.coc-whitedie .lbl{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.66rem;letter-spacing:.06em;color:var(--text-dim);text-transform:uppercase}
.coc-dicebar{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
.coc-die{width:46px;height:46px;border-radius:8px;background:#f3ead8;color:#1a1010;font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;font-size:1.3rem;display:flex;align-items:center;justify-content:center;cursor:pointer;border:2px solid transparent;position:relative}
.coc-die.sel{border-color:var(--gold);box-shadow:0 0 8px rgba(201,168,76,.6)}
.coc-die.used{opacity:.35;cursor:not-allowed}
.coc-die.white{background:#fff;cursor:default}
.coc-die-adj{display:flex;flex-direction:column;gap:2px}
.coc-die-adj button{width:20px;height:20px;font-size:.7rem;line-height:1;border:1px solid var(--border);background:var(--surface2);color:var(--text);border-radius:4px;cursor:pointer}
.coc-die-adj button:disabled{opacity:.3;cursor:not-allowed}
/* Die faces rendered as dots/pips (1-6) instead of a numeral; scales with the die. */
.coc-pips{display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(3,1fr);width:82%;height:82%}
.coc-pip{place-self:center;width:62%;height:62%;border-radius:50%}
.coc-pip.on{background:#15100a;box-shadow:inset 0 0 1px rgba(0,0,0,.35)}
/* Bordered hexes (depots + storage) for a bit of depth: a crisp ~1px edge all around
   the clip-path hex (separates adjacent tiles) + a soft drop shadow to lift them. */
.coc-tile,.coc-stt{position:relative;filter:drop-shadow(0 1.5px 1px rgba(0,0,0,.55))}
.coc-tile.goods{filter:none}     /* goods are small squares, not hexes */
.coc-tile-ghost{filter:none}     /* ghost placeholders stay subtle */
/* Glossy bevel along each hex's edges (light top-left -> dark bottom-right) so the
   flat single-color tiles read as raised/3D rather than dull. Clipped to the hex,
   inert to clicks; excludes goods squares, ghost placeholders, and empty slots. */
.coc-tile:not(.goods):not(.coc-tile-ghost)::after,.coc-stt:not(.empty)::after{content:"";position:absolute;inset:0;clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);background:linear-gradient(150deg,rgba(255,255,255,.62) 0%,rgba(255,255,255,.16) 16%,rgba(255,255,255,0) 34%,rgba(0,0,0,.06) 56%,rgba(0,0,0,.32) 84%,rgba(0,0,0,.6) 100%);pointer-events:none}
.coc-storage{display:flex;gap:6px;flex-wrap:wrap}
.coc-stt{width:70px;height:81px;clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:1.05rem;font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;color:#15100a;transition:transform .1s}
.coc-stt:hover{transform:scale(1.08)}
.coc-stt.empty{cursor:default}
/* Selected storage tile (ready to place): scale the hex and wrap it in a NON-clipped
   layer that carries the pulsing gold glow. The glow MUST live on the wrapper — a
   drop-shadow (or border/box-shadow) on the hex itself is clipped away by the hex's
   own clip-path. The wrapper has no clip-path, so its drop-shadow follows the child
   hex's outline and radiates outward, unclipped. */
.coc-stt-wrap{width:70px;height:81px;position:relative;display:flex}
.coc-stt.sel{transform:scale(1.12);z-index:3}
.coc-stt.sel:hover{transform:scale(1.15)}
.coc-stt-wrap.sel{z-index:3;animation:coc-stt-sel 1.2s ease-in-out infinite}
@keyframes coc-stt-sel{0%,100%{filter:drop-shadow(0 0 2px var(--gold))}50%{filter:drop-shadow(0 0 8px var(--gold-l)) drop-shadow(0 0 4px var(--gold-l))}}
/* Tile-move animation overlay (depot->storage, storage->duchy) */
.coc-fly-layer{position:fixed;inset:0;pointer-events:none;z-index:140}
.coc-flyer{position:fixed;display:flex;align-items:center;justify-content:center;clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);filter:drop-shadow(0 2px 4px rgba(0,0,0,.6));will-change:transform;animation:coc-fly .5s cubic-bezier(.4,.05,.25,1) forwards}
.coc-flyer::after{content:"";position:absolute;inset:0;clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);background:linear-gradient(150deg,rgba(255,255,255,.62) 0%,rgba(255,255,255,.16) 16%,rgba(255,255,255,0) 34%,rgba(0,0,0,.06) 56%,rgba(0,0,0,.32) 84%,rgba(0,0,0,.6) 100%);pointer-events:none}
.coc-flyer.goods{clip-path:none;border-radius:4px;color:#fff;font-weight:700;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.72rem;text-shadow:0 1px 2px rgba(0,0,0,.7)}
.coc-flyer.goods::after{display:none}
@keyframes coc-fly{from{transform:translate(0,0) scale(var(--s0,1))}to{transform:translate(var(--dx),var(--dy)) scale(var(--s1,1))}}
/* Worker / silver token flyers: pop OUT of the counter when spent, IN when gained. */
.coc-token-flyer{position:fixed;display:flex;align-items:center;justify-content:center;border-radius:50%;font-size:1rem;line-height:1;z-index:141;pointer-events:none;will-change:transform,opacity}
.coc-token-flyer.worker{background:radial-gradient(circle at 34% 28%,#c79a5c,#6f4a22);color:#f3ead8;box-shadow:0 1px 3px rgba(0,0,0,.6),inset 0 0 0 1px rgba(255,255,255,.18)}
.coc-token-flyer.silver{background:radial-gradient(circle at 34% 28%,#eef0f4,#9aa0ad);color:#2a2a2a;box-shadow:0 1px 3px rgba(0,0,0,.6),inset 0 0 0 1px rgba(255,255,255,.35)}
.coc-token-flyer.spent{animation:coc-tok-out .6s ease-in forwards}
.coc-token-flyer.gain{animation:coc-tok-in .6s ease-out forwards}
@keyframes coc-tok-out{from{transform:translate(0,0) scale(1);opacity:1}to{transform:translate(var(--dx),var(--dy)) scale(.55);opacity:0}}
@keyframes coc-tok-in{from{transform:translate(0,0) scale(.55);opacity:0}to{transform:translate(var(--dx),var(--dy)) scale(1);opacity:1}}
/* Resource token chips (workers / silver) in the dice bar + opponent modal. The
   .coc-resbar keeps workers+silver together as ONE wrap unit (so they never split);
   on mobile it takes its own full row below the dice. */
.coc-resbar{display:inline-flex;align-items:center;gap:14px;margin-left:8px}
.coc-token-chip{display:inline-flex;align-items:center;gap:7px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.05rem;color:var(--text)}
.coc-token-chip b{color:var(--text);font-size:1.35rem}
.coc-token{display:inline-flex;align-items:center;justify-content:center;width:44px;height:44px;border-radius:50%;font-size:1.3rem;line-height:1;box-shadow:0 1px 3px rgba(0,0,0,.55),inset 0 0 0 1px rgba(255,255,255,.15)}
.coc-token.worker{background:radial-gradient(circle at 34% 28%,#c79a5c,#6f4a22);color:#f3ead8}
.coc-token.silver{background:radial-gradient(circle at 34% 28%,#eef0f4,#9aa0ad);color:#2a2a2a}
/* Workers token as the Monastery #6 trigger: a gold rim invites the click; armed = pulse. */
.coc-token.coc-m6-arm{cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.55),inset 0 0 0 1px rgba(255,255,255,.15),0 0 0 2px var(--gold-l)}
.coc-token.coc-m6-on{cursor:pointer;animation:coc-goodspick 1.1s ease-in-out infinite}
/* Goods are shown in their own bordered box (empty box when you hold none — no "none" text). */
.coc-goods-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;min-height:44px;padding:7px 10px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius)}
.coc-goods-chip{display:flex;align-items:center;gap:4px;font-size:.78rem;color:var(--text-dim);cursor:pointer}
/* A goods chip you can click to sell during a Warehouse pending — pulses like the pick depots. */
.coc-goods-pick{color:var(--text);border-radius:6px;padding:1px 5px;margin:-1px -1px;animation:coc-goodspick 1.1s ease-in-out infinite}
@keyframes coc-goodspick{0%,100%{box-shadow:0 0 0 2px var(--gold-l),0 0 8px rgba(232,201,106,.4)}50%{box-shadow:0 0 0 2px var(--gold-l),0 0 16px rgba(232,201,106,.75)}}
.coc-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.coc-setup-banner{background:rgba(212,160,74,.14);border:1px solid var(--gold);border-radius:8px;padding:9px 12px;margin-bottom:12px;font-size:.85rem;line-height:1.35}
.coc-hexsvg{width:100%;max-width:520px;display:block;margin:0 auto}
.coc-hex{cursor:default;transition:opacity .12s}
.coc-hex.legal{cursor:pointer}
.coc-hex.legal:hover{opacity:.8}
.coc-modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:50;padding:16px}
.coc-modal{background:var(--surface);border:1px solid var(--gold);border-radius:var(--radius-lg);padding:20px;max-width:440px;width:100%}
.coc-modal h3{font-family:'Cinzel','Cinzel Fallback',serif;color:var(--gold);font-size:1rem;margin-bottom:6px}
.coc-modal p{color:var(--text-dim);font-size:.88rem;margin-bottom:14px}
.coc-modal-row{display:flex;flex-wrap:wrap;gap:8px}
/* non-blocking variant: clicks fall through to the board; panel pinned to the bottom */
.coc-modal-float{background:transparent;pointer-events:none;align-items:flex-end;padding-bottom:16px}
.coc-modal-float .coc-modal{pointer-events:auto;max-width:560px;box-shadow:0 8px 30px rgba(0,0,0,.7)}
.coc-toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--crimson);color:#fff;padding:10px 18px;border-radius:var(--radius);font-family:'Cinzel','Cinzel Fallback',serif;font-size:.82rem;z-index:60;box-shadow:0 6px 20px rgba(0,0,0,.5);max-width:min(92vw,460px);text-align:center;line-height:1.35}
.coc-reconnbar{position:fixed;top:0;left:0;right:0;display:flex;align-items:center;justify-content:center;gap:2px;background:var(--surface2);color:var(--gold-l);border-bottom:1px solid var(--gold);padding:7px 12px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.74rem;letter-spacing:.08em;z-index:130;box-shadow:0 2px 10px rgba(0,0,0,.5)}
/* Between-phase overlay: announces the new phase + the mine income you just collected.
   Sits below the flyer layer (z 140) so the silver tokens fly IN over it; pointer-events
   off so the board stays interactive underneath. Fades itself out (JS also dismisses). */
.coc-phase-pop{position:fixed;inset:0;z-index:120;display:flex;align-items:center;justify-content:center;pointer-events:none;padding:16px;animation:coc-phasepop-fade 3.3s ease-in-out forwards}
@keyframes coc-phasepop-fade{0%{opacity:0}7%{opacity:1}82%{opacity:1}100%{opacity:0}}
.coc-phase-pop-card{background:linear-gradient(160deg,rgba(34,20,22,.97),rgba(16,11,12,.97));border:1px solid var(--gold);border-radius:16px;padding:22px 44px;text-align:center;box-shadow:0 16px 54px rgba(0,0,0,.72);animation:coc-phasepop-scale .42s cubic-bezier(.2,.85,.3,1.25)}
@keyframes coc-phasepop-scale{from{transform:scale(.82)}to{transform:scale(1)}}
.coc-phase-pop-sub{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.66rem;letter-spacing:.2em;text-transform:uppercase;color:var(--text-dim)}
.coc-phase-pop-big{font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;font-size:2.5rem;color:var(--gold-l);letter-spacing:.05em;margin:2px 0 6px}
.coc-phase-pop-inc{display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:6px 12px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.1rem;color:var(--text)}
.coc-phase-pop-gain{display:inline-flex;align-items:center;gap:6px}
.coc-phase-pop-gain .coc-token{width:26px;height:26px;font-size:.9rem}
.coc-phase-pop-src{width:100%;font-size:.6rem;letter-spacing:.16em;text-transform:uppercase;color:var(--text-dim)}
.coc-winner{max-width:460px;margin:50px auto;text-align:center;background:var(--surface);border:1px solid var(--gold);border-radius:var(--radius-lg);padding:30px}
.coc-winner h2{font-family:'Cinzel','Cinzel Fallback',serif;font-size:2rem;color:var(--gold)}
/* End-of-game VP review: itemized breakdown per player (turn-stamped + end-of-game). */
.coc-review{max-width:820px;margin:34px auto;text-align:center;background:var(--surface);border:1px solid var(--gold);border-radius:var(--radius-lg);padding:24px}
.coc-review h2{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.9rem;color:var(--gold);margin-bottom:2px}
.coc-review-hint{color:var(--text-dim);font-size:.78rem;margin:0 0 14px}
.coc-review-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;text-align:left}
.coc-review-col{background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);padding:12px 14px}
.coc-review-col.win{border-color:var(--gold);box-shadow:0 0 0 1px var(--gold) inset}
.coc-review-hd{display:flex;justify-content:space-between;align-items:baseline;gap:8px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:1rem;color:var(--text);margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid var(--border)}
.coc-review-hd b{color:var(--gold);font-size:1.1rem}
.coc-review-list{font-size:.82rem}
.coc-review-sub{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.58rem;letter-spacing:.14em;text-transform:uppercase;color:var(--gold);opacity:.8;margin:8px 0 3px}
.coc-review-phase{text-align:center;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.58rem;letter-spacing:.14em;text-transform:uppercase;color:var(--gold);opacity:.6;padding:5px 0 2px}
.coc-review-row{display:flex;align-items:baseline;gap:8px;padding:2px 0;color:var(--text-dim)}
.coc-review-t{flex:0 0 34px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;font-weight:700;color:var(--gold);opacity:.75}
.coc-review-lbl{flex:1;color:var(--text)}
.coc-review-vp{flex:0 0 auto;color:var(--text);font-weight:700}
.coc-review-total{margin-top:6px;padding-top:6px;border-top:1px solid var(--border);color:var(--text)}
.coc-review-total .coc-review-lbl,.coc-review-total .coc-review-vp{font-family:'Cinzel','Cinzel Fallback',serif;color:var(--gold)}
.coc-review-empty{color:var(--text-dim);font-size:.78rem;padding:6px 0}
.coc-review-row.proj,.coc-review-sub.proj,.coc-review-total.proj,.coc-review-phase.proj{opacity:.4}
.coc-review-modal{max-width:760px;width:100%;max-height:88vh;overflow-y:auto}
/* Clickable score in the status bar -> opens the mid-game VP breakdown. */
.coc-vp-click{cursor:pointer;border-radius:var(--radius);transition:background .12s}
.coc-vp-click:hover{background:var(--surface2)}
.coc-vp-info{font-size:.7rem;color:var(--gold);opacity:.8;align-self:flex-start}
.coc-log{max-height:220px;overflow-y:auto;scrollbar-gutter:stable;font-size:.78rem;color:var(--text-dim)}
.coc-log div{padding:2px 0;border-bottom:1px solid rgba(62,42,46,.4)}
.coc-log-t{display:inline-block;min-width:26px;margin-right:6px;color:var(--gold);opacity:.75;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.68rem;font-weight:700}
.coc-log-phase{text-align:center;color:var(--gold);opacity:.85;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.66rem;letter-spacing:.12em;text-transform:uppercase;padding:4px 0!important}
/* Color-completion bonus strip (large = 1st to finish a color, small = 2nd). */
.coc-bonusbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 10px;padding:7px 12px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius)}
.coc-bonusbar-lbl{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.6rem;letter-spacing:.14em;text-transform:uppercase;color:var(--gold)}
.coc-regbonus-lbl{display:inline-flex;align-items:center;gap:6px;color:var(--text-dim)}
.coc-regbonus{font-size:.98rem;color:var(--gold-l);letter-spacing:.02em}
.coc-regsize{font-size:.74rem;color:var(--text-dim);letter-spacing:.01em}
.coc-bonus-div{width:1px;align-self:stretch;background:var(--border);margin:-2px 2px}
.coc-bonuschip{display:inline-flex;align-items:center;gap:4px;font-size:.82rem;color:var(--text)}
.coc-bonuschip.gone{opacity:.38}
.coc-bonus-sw{width:15px;height:15px;border-radius:3px;box-shadow:inset 0 0 0 1px rgba(0,0,0,.4)}
.coc-bonuschip b{color:var(--text);font-size:.86rem}
.coc-bonuschip i{font-style:normal;font-size:.58rem;letter-spacing:.04em;color:var(--text-dim);text-transform:uppercase}
.coc-turnbadge{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.74rem;padding:4px 10px;border-radius:12px;letter-spacing:.05em}
.coc-turnbadge.you{background:var(--gold);color:#120c0d}
.coc-turnbadge.them{background:var(--surface2);color:var(--text-dim);border:1px solid var(--border)}
.coc-board-pick{margin:4px 0 8px}
.coc-board-pick .coc-section-title{display:flex;align-items:center;gap:8px}
.coc-board-grid{display:flex;gap:8px;overflow-x:auto;padding:6px 2px 8px}
.coc-bthumb{flex:0 0 auto;width:86px;background:var(--surface2);border:2px solid var(--border);border-radius:10px;padding:5px 5px 4px;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:3px;transition:border-color .15s,transform .1s}
.coc-bthumb:hover{transform:translateY(-2px)}
.coc-bthumb.sel{border-color:var(--gold);box-shadow:0 0 0 1px var(--gold)}
.coc-bthumb-svg{width:72px;height:66px;display:block}
.coc-bthumb-name{font-size:.6rem;color:var(--text-dim);text-align:center;line-height:1.05;font-family:'Cinzel','Cinzel Fallback',serif}
.coc-bthumb.sel .coc-bthumb-name{color:var(--gold)}
`;

// ─── Hex geometry ─────────────────────────────────────────────────────────────
const HEX_S = 26;
// Side of the square foreignObject that holds a placed tile's TileArt on the duchy
// board — sized to fit inside the hex (which is ~2*HEX_S tall, ~√3*HEX_S wide).
const HEX_ART = HEX_S * 1.4;
function hexCenter(q, r) {
  return { x: HEX_S * Math.sqrt(3) * (q + r / 2), y: HEX_S * 1.5 * r };
}
function hexPoints(cx, cy, s) {
  const pts = [];
  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 180) * (60 * i - 90);
    pts.push(`${(cx + s * Math.cos(a)).toFixed(1)},${(cy + s * Math.sin(a)).toFixed(1)}`);
  }
  return pts.join(" ");
}

// A die value (1-6) as SVG pips centered in a duchy hex — replaces the numeral on
// empty spaces so the "die you need" reads as a die face (matches the dice + depot
// mini-dice). White dots with a thin dark rim so they show on any hex color.
function svgPips(cx, cy, n, key) {
  const on = PIP_MAP[n];
  if (!on) return null;
  const set = new Set(on);
  const g = HEX_S * 0.34, r = HEX_S * 0.12;
  const cell = { 1: [-g, -g], 2: [0, -g], 3: [g, -g], 4: [-g, 0], 5: [0, 0], 6: [g, 0], 7: [-g, g], 8: [0, g], 9: [g, g] };
  return [1, 2, 3, 4, 5, 6, 7, 8, 9].filter((i) => set.has(i)).map((i) => (
    <circle key={`${key}-p${i}`} cx={cx + cell[i][0]} cy={cy + cell[i][1]} r={r}
      fill="#fff" stroke="rgba(0,0,0,.55)" strokeWidth={0.7} />
  ));
}

// Fixed pixel size for the CSS clip-path hex tiles on the shared board (depots +
// black depot) and in the storage row, so they read at the same scale as the
// duchy hexes and stay constant across every board. KEEP IN SYNC with the
// `.coc-tile` / `.coc-stt` width/height in the stylesheet below.
// On-board / storage hex tiles. The box is NOT square: a regular pointy-top hex
// has width:height = √3:2, so height = width * 2/√3. With that ratio the
// clip-path renders a true (un-squished) hexagon matching the duchy hexes.
// KEEP IN SYNC with `.coc-tile` / `.coc-stt` width/height in the stylesheet.
const HEX_W = 70;
const HEX_H = 81;   // ≈ 70 * 2/√3
// Central black depot: its (up to 4) tiles sit in a kite — 1 top, 2 middle,
// 1 bottom. Horizontal offsets use HEX_W, vertical offsets use HEX_H so the
// hexes nest into a diamond. BLACK_GAP nudges them apart a touch so the four
// tiles read as separate hexes (edge-to-edge they looked like they overlapped).
const BLACK_GAP = 6;
const BLACK_KITE = [
  { left: 0.5 * HEX_W + 0.5 * BLACK_GAP, top: 0 },                         // top
  { left: 0,                             top: 0.75 * HEX_H + BLACK_GAP },  // middle-left
  { left: HEX_W + BLACK_GAP,             top: 0.75 * HEX_H + BLACK_GAP },  // middle-right
  { left: 0.5 * HEX_W + 0.5 * BLACK_GAP, top: 1.5 * HEX_H + 2 * BLACK_GAP }, // bottom
];
// Breathing room (px) between the kite and the black box border around it.
const BLACK_PAD = 9;

// A small selectable thumbnail of one board's hex layout (lobby board picker).
function BoardThumb({ spaces, name, selected, onClick }) {
  const sids = Object.keys(spaces || {});
  if (!sids.length) return null;
  let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
  const centers = {};
  for (const sid of sids) {
    const sp = spaces[sid];
    const c = hexCenter(sp.q, sp.r);
    centers[sid] = c;
    minX = Math.min(minX, c.x); maxX = Math.max(maxX, c.x);
    minY = Math.min(minY, c.y); maxY = Math.max(maxY, c.y);
  }
  const pad = HEX_S + 2;
  const vb = `${(minX - pad).toFixed(0)} ${(minY - pad).toFixed(0)} ${(maxX - minX + pad * 2).toFixed(0)} ${(maxY - minY + pad * 2).toFixed(0)}`;
  return (
    <button type="button" className={`coc-bthumb${selected ? " sel" : ""}`} onClick={onClick} title={name}>
      <svg viewBox={vb} className="coc-bthumb-svg" preserveAspectRatio="xMidYMid meet">
        {sids.map((sid) => {
          const sp = spaces[sid];
          const c = centers[sid];
          return <polygon key={sid} points={hexPoints(c.x, c.y, HEX_S - 1.2)}
            fill={TILE_HEX[sp.color] || "#444"} stroke="rgba(0,0,0,.45)" strokeWidth={0.8} />;
        })}
      </svg>
      <span className="coc-bthumb-name">{name}</span>
    </button>
  );
}

export default function CastlesOfCrimson({ myId, authUser, onExit }) {
  const [board, setBoard] = useState(null);            // {spaces, colors, castle, ...}
  const [screen, setScreen] = useState("lobby");        // lobby | waiting | game
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [openGames, setOpenGames] = useState([]);
  const [activeGames, setActiveGames] = useState([]);   // ALL in-progress games (yours + others')
  const [history, setHistory] = useState([]);           // your finished games (lobby History column)
  const [reviewOnly, setReviewOnly] = useState(false);  // HTTP-loaded finished-game review (no WS)
  const [loadingGames, setLoadingGames] = useState(false);
  const [joinCode, setJoinCode] = useState("");
  const [toast, setToast] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);   // socket dropped mid-game, retrying
  const [showCreateMenu, setShowCreateMenu] = useState(false);  // + Create Game dropdown (vs Friend / vs Bot)

  // interaction state
  const [selDie, setSelDie] = useState(null);
  const [selStorage, setSelStorage] = useState(null);
  const [m6Armed, setM6Armed] = useState(false);        // Monastery #6: armed via the workers token
  const [actedThisTurn, setActedThisTurn] = useState(false);  // did I take any action this turn? (gates Undo)
  const [extraValue, setExtraValue] = useState(null);
  const [viewOpp, setViewOpp] = useState(false);
  const [showScores, setShowScores] = useState(false);   // mid-game VP breakdown popup
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  const [myBoard, setMyBoard] = useState("1");          // board the local player picked
  const [oppBoard, setOppBoard] = useState("1");        // board chosen for the bot (vs-AI)
  const [flyers, setFlyers] = useState([]);             // tile-move animations (depot->storage, storage->duchy)
  const [phasePop, setPhasePop] = useState(null);       // {from,to,silver,workers} — the between-phase overlay
  const animSnap = useRef(null);                        // prev snapshot for diffing my tile moves
  const flyerSeq = useRef(0);
  const prevAiThinking = useRef(false);                 // edge-detect the bot's turn (auto-view)
  const aiThinkingRef = useRef(false);                  // latest aiThinking, read inside timeouts
  const revealHoldRef = useRef(false);                  // setup-castle reveal owns the modal (blocks the generic auto-close)
  const prevOppCastleRef = useRef(undefined);           // opp starting-castle presence last seen (undefined = no snapshot yet)
  const revealCloseTimer = useRef(null);                // auto-close timer for the setup-castle reveal
  const botViewTimer = useRef(null);                    // settle delay before the opponent board auto-opens
  const reconnTimer = useRef(null);                     // auto-reconnect backoff timer
  const reconnTries = useRef(0);
  const turnSimsRef = useRef(0);                         // client-AI sims accumulated across the bot's turn
  const prevAiSimRef = useRef(false);                    // edge-detect the bot turn for the per-turn sim log
  const prevPhaseRef = useRef(null);                    // last phase_letter seen (detect a phase advance)
  const phasePopTimer = useRef(null);                   // auto-dismiss timer for the phase overlay
  const viewOppRef = useRef(false);                     // current viewOpp, read inside the flyer effect

  const playerName = authUser?.name || "Player";
  // The die value needed to sell a goods color (its index in the goods order + 1).
  const goodsSellNum = (color) => (board ? board.goods_colors.indexOf(color) + 1 : 0);

  // ── derived ──
  const game = roomData?.game;
  const players = roomData?.players || {};
  const oppId = Object.keys(players).find((p) => p !== myId);
  const me = game?.players?.[myId];
  const opp = oppId ? game?.players?.[oppId] : null;
  const over = game?.phase === "over";
  const fscore = roomData?.final_scores;   // final VP incl. end-of-game bonuses (shown when over)
  const pendingMine = game && game.pending_pid === myId;
  const myTurnRaw = game && !over && (game.pending_pid ? game.pending_pid === myId : game.turn === myId);
  const aiThinking = game && roomData?.vs_ai && !over &&
    (game.pending_pid || game.turn) === roomData?.ai_player;
  // Setup phase: each player places a starting castle on a crimson (castle) space before
  // dice are rolled. `setupMine` = it's my turn to choose.
  const setupPhase = !!game && game.phase === "setup";
  const setupMine = setupPhase && !over && game.turn === myId;
  // Monastery #6: on your turn, spend 2 workers to take a building tile from a depot.
  // Usable when you own the effect, haven't used it this turn, have >=2 workers + a free
  // storage slot, and a building tile is actually sitting in a depot. Mirrors the engine
  // gate in legal_moves so the workers token only invites a click when it'll work.
  const canUseM6 = !!me && myTurnRaw && !pendingMine
    && (me.monastery_effects || []).includes(6)
    && !game.m6_used_this_turn && (me.workers || 0) >= 2 && (me.storage?.length || 0) < 3
    && [1, 2, 3, 4, 5, 6].some((d) => (game.depots?.[String(d)]?.hexes || []).some((t) => t.type === "building"));

  // ── socket ──
  const handleMessage = useCallback((msg) => {
    if (msg.type === "error") { setToast(msg.message || "error"); return; }
    const room = msg.room;
    if (!room) return;
    const tok = room.reconnect_tokens?.[myId];
    const rid = room.room_id || roomId;
    if (tok) { try { localStorage.setItem(`coc_token_${rid}_${myId}`, tok); localStorage.setItem("coc_roomId", rid); } catch {} }
    setRoomData(room);
    const inGame = room.status === "playing" || room.status === "over";
    if (msg.type === "created" || msg.type === "joined" || msg.type === "reconnected") {
      setScreen(inGame ? "game" : "waiting");
    } else if (msg.type === "room_update") {
      if (inGame && screen !== "game") setScreen("game");
    }
  }, [myId, roomId, screen]);

  const { connected, connect, send, disconnect, socketReady } = useSocket(handleMessage);

  // fetch every selectable board layout once (shared meta + per-board spaces)
  useEffect(() => {
    fetch(`${COC_HTTP}/boards`).then((r) => r.json()).then((d) => {
      if (!d.ok) return;
      const byId = {};
      (d.boards || []).forEach((b) => { byId[b.id] = b; });
      setBoard({ ...d, byId });
    }).catch(() => {});
  }, []);

  // Resolve the hex layout for a given board id (falls back to the default board).
  const boardSpaces = useCallback((boardId) => {
    const by = board?.byId || {};
    return (by[boardId] || by[board?.default_board] || {}).spaces || {};
  }, [board]);

  const fetchGames = useCallback(() => {
    setLoadingGames(true);
    fetch(`${COC_HTTP}/games`).then((r) => r.json()).then((d) => setOpenGames(d.games || []))
      .catch(() => {}).finally(() => setLoadingGames(false));
    // Active Games is PUBLIC: all in-progress games (yours + others', vs-bot or not).
    // The frontend pins yours to the top via myId. No auth needed.
    fetch(`${COC_HTTP}/games/active`).then((r) => r.json()).then((d) => setActiveGames(d.games || [])).catch(() => {});
    // History = your finished games (session-gated). Guests have none.
    if (authUser?.session_token) {
      fetch(`${COC_HTTP}/games/history`, { headers: { Authorization: `Bearer ${authUser.session_token}` } })
        .then((r) => r.json()).then((d) => setHistory(d.games || [])).catch(() => {});
    } else {
      setHistory([]);
    }
  }, [authUser]);

  // Load + show a finished game's board + results, read-only over HTTP (no WebSocket).
  const enterCocReview = (id) => {
    const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
    fetch(`${COC_HTTP}/games/${id}/review?player_id=${encodeURIComponent(myId)}`, { headers }).then((r) => r.json()).then((d) => {
      if (!d.ok) { setToast(d.message || "Could not load review"); return; }
      setRoomData({
        game: d.game, players: d.players || {}, host: null, status: "over",
        vs_ai: false, ai_player: null,
        final_scores: d.final_scores || {}, vp_breakdown: d.vp_breakdown || {},
      });
      setReviewOnly(true);
      setReviewing(false);   // land on the results page first (Review Board is one click away)
      setRoomId(id);
      setScreen("game");
    }).catch(() => setToast("Could not load review"));
  };

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);

  // auto-resume a saved room on mount
  useEffect(() => {
    try {
      const rid = localStorage.getItem("coc_roomId");
      const tok = rid ? localStorage.getItem(`coc_token_${rid}_${myId}`) : null;
      if (rid && tok) {
        setRoomId(rid);
        connect(`${COC_WS}/${rid}/${myId}`, { action: "reconnect", token: tok });
      }
    } catch {}
    return () => disconnect();
  }, []); // eslint-disable-line

  // Auto-reconnect: if the socket drops while in a LIVE game (Render cold start, a
  // network blip, or iOS killing a backgrounded WS), keep retrying with backoff —
  // through the ~30-50s a cold start takes — until we're back. This is load-bearing
  // for vs-bot games: a bot's turn is only re-driven when our client reconnects
  // (`_handle_reconnect` re-triggers the server scheduler), so WITHOUT this the bot's
  // turn freezes until a manual refresh (the "hung for minutes" bug). Reconnect uses
  // the `reconnect` action (NOT `join`) so the backend actually resumes the bot.
  const inLiveGame = !!roomId && !reviewOnly
    && (screen === "game" || screen === "waiting") && roomData?.status !== "over";
  // One reconnect attempt that reschedules itself — shared by the backoff loop AND the
  // tab-focus nudge, so neither can leave the loop dead by clearing the other's timer.
  const attemptReconnect = useCallback(() => {
    if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; }
    const rs = socketReady();
    if (rs === 0 || rs === 1) {                          // CONNECTING/OPEN — don't abort it, re-check
      reconnTimer.current = setTimeout(attemptReconnect, 3000);
      return;
    }
    let tok = null;
    try { tok = localStorage.getItem(`coc_token_${roomId}_${myId}`); } catch {}
    if (tok) { setReconnecting(true); connect(`${COC_WS}/${roomId}/${myId}`, { action: "reconnect", token: tok }); }
    reconnTries.current += 1;
    // 2s, 4s, 6s … capped at 8s — retries indefinitely until connected (or we leave).
    reconnTimer.current = setTimeout(attemptReconnect, Math.min(2000 * reconnTries.current, 8000));
  }, [roomId, myId, connect, socketReady]);

  useEffect(() => {
    const clear = () => { if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; } };
    if (connected || !inLiveGame) {
      clear();
      reconnTries.current = 0;
      if (connected) setReconnecting(false);             // no-op re-render if already false
      return;
    }
    if (!reconnTimer.current) attemptReconnect();        // start the loop if it isn't running
    return clear;
  }, [connected, inLiveGame, attemptReconnect]);

  // Tab back into focus (iOS often kills a backgrounded socket without firing onclose):
  // fire an immediate attempt instead of waiting out the backoff.
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState !== "visible" || connected || !inLiveGame) return;
      reconnTries.current = 0;
      attemptReconnect();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [connected, inLiveGame, attemptReconnect]);

  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2400); return () => clearTimeout(t); } }, [toast]);

  // clear selection at the start of a fresh decision
  useEffect(() => { setSelDie(null); setSelStorage(null); setExtraValue(null); }, [game?.turn, game?.round, game?.pending_kind]);
  // Disarm Monastery #6 the moment it's no longer usable (turn ended, used, storage full…).
  useEffect(() => { if (!canUseM6) setM6Armed(false); }, [canUseM6]);
  // "acted this turn" resets only when the turn itself changes (NOT on pending
  // open/close, since opening a pending means you already acted).
  useEffect(() => { setActedThisTurn(false); }, [game?.turn, game?.round, game?.phase_letter]);
  // Vs the bot: auto-open the opponent view when the bot's PLAYING turn begins (so you
  // can watch it build), and auto-close when your turn returns (the view is a blocking
  // modal). Edge-triggered on aiThinking, so a manual open/close mid-bot-turn stands.
  // Both transitions get a ~1s settle: the OPEN is delayed so finishing your own turn
  // isn't immediately steamrolled by the opponent board (matched by the backend's
  // _POST_TURN_PAUSE so the board is up before the bot's first move lands), and the
  // CLOSE lingers so you see the bot's finished board for a beat before it returns you
  // to your own. The SETUP starting-castle reveal is owned by its own effect below;
  // while it holds the modal (revealHoldRef), this generic handler must NOT touch it.
  useEffect(() => {
    aiThinkingRef.current = aiThinking;
    const wasAi = prevAiThinking.current;
    prevAiThinking.current = aiThinking;
    const clearTimer = () => { if (botViewTimer.current) { clearTimeout(botViewTimer.current); botViewTimer.current = null; } };
    if (revealHoldRef.current) return;                  // setup-castle reveal owns the modal
    if (aiThinking && !wasAi && !setupPhase) {           // bot's playing turn begins: open after a settle
      clearTimer();
      botViewTimer.current = setTimeout(() => {
        botViewTimer.current = null;
        if (aiThinkingRef.current && !revealHoldRef.current) setViewOpp(true);
      }, 1000);
    } else if (!aiThinking && wasAi) {                    // bot's turn ended: linger on their board, then return
      clearTimer();
      botViewTimer.current = setTimeout(() => {
        botViewTimer.current = null;
        if (!aiThinkingRef.current && !revealHoldRef.current) setViewOpp(false);
      }, 1000);
    }
  }, [aiThinking]);
  useEffect(() => { viewOppRef.current = viewOpp; }, [viewOpp]);   // latest value for the flyer effect

  // Setup starting-castle reveal (vs the bot). When the opponent's starting castle first
  // appears on their board, force their board OPEN, pop the castle in on it, hold it
  // visible long enough to watch, then close (unless it's already the bot's playing turn,
  // in which case the generic handler keeps it open for A-1). This is decoupled from
  // aiThinking because the bot's SECOND castle transitions the game straight to "playing"
  // in the same update — so the naive auto-close fired at the exact moment the castle
  // landed, closing the board just as the animation played (the reported bug).
  useEffect(() => {
    if (!game || !roomData?.vs_ai) { prevOppCastleRef.current = undefined; return; }
    const castle = opp && opp.castle_sid ? opp.duchy?.[opp.castle_sid] : null;
    const had = prevOppCastleRef.current;
    prevOppCastleRef.current = !!castle;
    // Reveal ONLY on a null->placed transition we actually witnessed (had === false).
    // `undefined` = first snapshot this mount (fresh create OR reconnect mid-game) —
    // never reveal then, so reconnecting to an in-progress game doesn't replay it.
    if (over || reviewing || !castle || had !== false) return;
    revealHoldRef.current = true;
    setViewOpp(true);                                            // show their board
    // Pop the castle in AFTER the modal mounts (two rAFs) so [data-oppsid] exists.
    const raf = requestAnimationFrame(() => requestAnimationFrame(() => {
      const el = document.querySelector(`[data-oppsid="${opp.castle_sid}"]`);
      if (el) {
        const d = el.getBoundingClientRect();
        const W = 58, H = 67;
        const dcx = d.left + d.width / 2, dcy = d.top + d.height / 2;
        const s1 = Math.max(0.5, Math.min(1, d.width / W));
        const f = { id: `f${flyerSeq.current++}`, tile: castle, left: dcx - W / 2, top: dcy - H / 2, w: W, h: H, dx: 0, dy: 0, s0: 0.2, s1 };
        setFlyers((fs) => [...fs, f]);
        setTimeout(() => setFlyers((fs) => fs.filter((x) => x.id !== f.id)), 640);
      }
    }));
    // Hold the board open so the pop-in is seen, then release the modal to the generic
    // handler: close it unless it's now the bot's playing turn (bot was start player).
    if (revealCloseTimer.current) clearTimeout(revealCloseTimer.current);
    revealCloseTimer.current = setTimeout(() => {
      revealCloseTimer.current = null;
      revealHoldRef.current = false;
      if (!aiThinkingRef.current) setViewOpp(false);
    }, 1900);
    return () => cancelAnimationFrame(raf);
  }, [game]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Tile-move animations: diff MY storage/duchy each update and fly the moved tile
  // from where it was (depot / black depot / storage) to its new home. Mirrors
  // Spender's flying overlay; uses persistent data-* anchors in the live DOM.
  useEffect(() => {
    if (!game || !me) { animSnap.current = null; return; }
    const loc = {};
    for (const d of [1, 2, 3, 4, 5, 6]) (game.depots?.[String(d)]?.hexes || []).forEach((t) => { loc[t.id] = { kind: "depot", d }; });
    (game.black_depot || []).forEach((t) => { loc[t.id] = { kind: "black" }; });
    (me.storage || []).forEach((t) => { loc[t.id] = { kind: "storage" }; });
    const storageIds = new Set((me.storage || []).map((t) => t.id));
    const duchyIds = new Set(Object.values(me.duchy || {}).filter(Boolean).map((t) => t.id));
    const depotGoods = [];
    for (const d of [1, 2, 3, 4, 5, 6]) (game.depots?.[String(d)]?.goods || []).forEach((g) => depotGoods.push({ id: g.id, color: g.color, d }));
    const myGoods = { ...(me.goods || {}) };
    // opponent's currently-held tiles (storage + duchy), keyed by id — to detect what
    // the bot/opponent just acquired (their board isn't rendered, so it flies toward
    // the View Opponent button instead of a hidden slot).
    const oId = game.players ? Object.keys(game.players).find((p) => p !== myId) : null;
    const oPlayer = oId ? game.players[oId] : null;
    const oppTiles = {};
    const oppLoc = {};   // opponent tile id -> where it sits on THEIR board (for in-modal anim)
    (oPlayer?.storage || []).forEach((t, i) => { if (t) { oppTiles[t.id] = t; oppLoc[t.id] = { kind: "oppslot", i }; } });
    Object.entries(oPlayer?.duchy || {}).forEach(([sid, t]) => { if (t) { oppTiles[t.id] = t; oppLoc[t.id] = { kind: "oppsid", sid }; } });
    const oppTileIds = new Set(Object.keys(oppTiles));
    const oppStorageIds = new Set((oPlayer?.storage || []).filter(Boolean).map((t) => t.id));
    const oppDuchyIds = new Set(Object.values(oPlayer?.duchy || {}).filter(Boolean).map((t) => t.id));
    const oppGoods = { ...(oPlayer?.goods || {}) };
    const prev = animSnap.current;
    animSnap.current = { loc, storageIds, duchyIds, depotGoods, myGoods, oppTileIds, oppLoc, oppStorageIds, oppDuchyIds, oppGoods,
      workers: me.workers, silver: me.silver, oppWorkers: oPlayer?.workers, oppSilver: oPlayer?.silver };
    if (!prev) return;                                  // first paint: nothing to animate
    const rectOf = (spec) => {
      if (!spec) return null;
      const sel = spec.kind === "depot" ? `[data-depot="${spec.d}"]`
        : spec.kind === "black" ? "[data-blackdepot]"
        : spec.kind === "storage" ? "[data-storage]"
        : spec.kind === "slot" ? `[data-storage-slot="${spec.i}"]`
        : spec.kind === "hex" ? `[data-sid="${spec.sid}"]`
        : spec.kind === "mygoods" ? "[data-mygoods]"
        : spec.kind === "goodchip" ? `[data-goodchip="${spec.c}"]`
        : spec.kind === "oppgoodchip" ? `[data-oppgoodchip="${spec.c}"]`
        : spec.kind === "viewopp" ? "[data-viewopp]"
        : spec.kind === "oppslot" ? `[data-oppstorage-slot="${spec.i}"]`
        : spec.kind === "oppsid" ? `[data-oppsid="${spec.sid}"]`
        : spec.kind === "oppgoods" ? "[data-oppgoods]" : null;
      const el = sel && document.querySelector(sel);
      return el ? el.getBoundingClientRect() : null;
    };
    const mk = (tile, src, dest) => {
      const s = rectOf(src), d = rectOf(dest);
      if (!s || !d) return null;
      const W = 58, H = 67;
      const scx = s.left + s.width / 2, scy = s.top + s.height / 2;
      const dcx = d.left + d.width / 2, dcy = d.top + d.height / 2;
      const s1 = (dest.kind === "hex" || dest.kind === "oppsid") ? Math.max(0.5, Math.min(1, d.width / W))
        : dest.kind === "viewopp" ? 0.4 : 1;
      return { id: `f${flyerSeq.current++}`, tile, left: scx - W / 2, top: scy - H / 2, w: W, h: H, dx: dcx - scx, dy: dcy - scy, s1 };
    };
    // A placement with no source (a starting castle isn't drawn from a depot/storage) —
    // "pop" it IN at the destination hex (scale up in place) so it still animates.
    const popIn = (tile, dest) => {
      const d = rectOf(dest);
      if (!d) return null;
      const W = 58, H = 67;
      const dcx = d.left + d.width / 2, dcy = d.top + d.height / 2;
      const s1 = (dest.kind === "hex" || dest.kind === "oppsid") ? Math.max(0.5, Math.min(1, d.width / W)) : 1;
      return { id: `f${flyerSeq.current++}`, tile, left: dcx - W / 2, top: dcy - H / 2, w: W, h: H, dx: 0, dy: 0, s0: 0.2, s1 };
    };
    const add = [];
    const storage = me.storage || [];
    for (let i = 0; i < storage.length; i++) {
      const t = storage[i];
      if (prev.storageIds.has(t.id)) continue;          // newly in storage = took / bought
      const f = mk(t, prev.loc[t.id], { kind: "slot", i });   // fly to the exact slot it landed in
      if (f) add.push(f);
    }
    for (const [sid, t] of Object.entries(me.duchy || {})) {
      if (!t || prev.duchyIds.has(t.id)) continue;      // newly in duchy = placed
      const f = mk(t, prev.loc[t.id], { kind: "hex", sid }) || popIn(t, { kind: "hex", sid });
      if (f) add.push(f);
    }
    // Goods I took from a depot (a ship action) -> fly each to my goods section.
    const goodsDelta = {};
    for (const c of new Set([...Object.keys(me.goods || {}), ...Object.keys(prev.myGoods || {})])) {
      goodsDelta[c] = (me.goods?.[c] || 0) - (prev.myGoods?.[c] || 0);
    }
    const curGoodIds = new Set();
    for (const d of [1, 2, 3, 4, 5, 6]) (game.depots?.[String(d)]?.goods || []).forEach((g) => curGoodIds.add(g.id));
    const gDest = rectOf({ kind: "mygoods" });
    for (const g of (prev.depotGoods || [])) {
      if (!gDest || curGoodIds.has(g.id) || (goodsDelta[g.color] || 0) <= 0) continue;   // still in a depot, or it went to the opponent
      goodsDelta[g.color] -= 1;
      const s = rectOf({ kind: "depot", d: g.d });
      if (!s) continue;
      const W = 26, H = 26;
      const scx = s.left + s.width / 2, scy = s.top + s.height / 2;
      // Land on the actual goods chip for this color; fall back to the row's left edge.
      const chip = rectOf({ kind: "goodchip", c: g.color });
      const dcx = chip ? chip.left + chip.width / 2 : gDest.left + 18;
      const dcy = chip ? chip.top + chip.height / 2 : gDest.top + gDest.height / 2;
      add.push({ id: `f${flyerSeq.current++}`, goods: true, color: g.color, left: scx - W / 2, top: scy - H / 2, w: W, h: H, dx: dcx - scx, dy: dcy - scy, s1: 1 });
    }
    // Opponent's moves. While you're VIEWING their board (auto-opens on the bot's
    // turn), animate their tiles ON the modal board: depot -> their storage slot, and
    // their storage/depot -> their duchy hex, plus goods they drain into their goods
    // row. Otherwise (board hidden) fly a single marker toward the View Opponent button.
    if (viewOppRef.current) {
      (oPlayer?.storage || []).forEach((t, i) => {
        if (!t || prev.oppStorageIds.has(t.id)) return;          // newly in their storage
        const f = mk(t, prev.loc[t.id] || prev.oppLoc[t.id], { kind: "oppslot", i });
        if (f) add.push(f);
      });
      for (const [sid, t] of Object.entries(oPlayer?.duchy || {})) {
        if (!t || prev.oppDuchyIds.has(t.id)) continue;          // newly in their duchy = placed
        const f = mk(t, prev.oppLoc[t.id] || prev.loc[t.id], { kind: "oppsid", sid }) || popIn(t, { kind: "oppsid", sid });
        if (f) add.push(f);
      }
      const oGoodsDest = rectOf({ kind: "oppgoods" });
      const oGoodsDelta = {};
      for (const c of new Set([...Object.keys(oppGoods), ...Object.keys(prev.oppGoods || {})])) {
        oGoodsDelta[c] = (oppGoods[c] || 0) - (prev.oppGoods?.[c] || 0);
      }
      if (oGoodsDest) for (const g of (prev.depotGoods || [])) {
        if (curGoodIds.has(g.id) || (oGoodsDelta[g.color] || 0) <= 0) continue;
        oGoodsDelta[g.color] -= 1;
        const s = rectOf({ kind: "depot", d: g.d });
        if (!s) continue;
        const scx = s.left + s.width / 2, scy = s.top + s.height / 2;
        const oChip = rectOf({ kind: "oppgoodchip", c: g.color });
        const dcx = oChip ? oChip.left + oChip.width / 2 : oGoodsDest.left + 14;
        const dcy = oChip ? oChip.top + oChip.height / 2 : oGoodsDest.top + oGoodsDest.height / 2;
        add.push({ id: `f${flyerSeq.current++}`, goods: true, color: g.color, left: scx - 13, top: scy - 13, w: 26, h: 26, dx: dcx - scx, dy: dcy - scy, s1: 1 });
      }
    } else {
      const oppDest = rectOf({ kind: "viewopp" });
      if (oppDest) {
        for (const [tid, t] of Object.entries(oppTiles)) {
          if (prev.oppTileIds.has(tid)) continue;              // opponent already had it
          const src = prev.loc[tid];                           // was it in a visible depot / black?
          if (!src) continue;                                  // internal (hidden) opp move -> skip
          const f = mk(t, src, { kind: "viewopp" });
          if (f) add.push(f);
        }
      }
    }
    // Skip a flood of TILE changes (reconnect / initial catch-up) so we animate only
    // normal, incremental updates. NB: we can't gate on the move-log length — engine.py
    // caps game["moves"], so its delta is 0 late-game, which once disabled ALL animation.
    if (add.length > 8) return;
    // Workers / silver token flyers: pop tokens OUT of the counter when spent (Δ<0),
    // fly them IN when gained (Δ>0). Diff-driven, so it covers every source/sink
    // (die-adjust, buy-black, sell, phase income) without knowing which move caused it.
    const resFly = (attr, kind, cur, prevV) => {
      const delta = (cur || 0) - (prevV || 0);
      if (!delta) return;
      const el = document.querySelector(`[data-${attr}]`);
      if (!el) return;
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const spent = delta < 0, n = Math.min(Math.abs(delta), 6);
      for (let k = 0; k < n; k++) {
        const ang = -Math.PI / 2 + (k - (n - 1) / 2) * 0.5;   // fan upward
        const dist = 28 + k * 4;
        const ox = Math.cos(ang) * dist, oy = Math.sin(ang) * dist;
        add.push({
          id: `f${flyerSeq.current++}`, token: kind, spent,
          left: (spent ? cx : cx + ox) - 16, top: (spent ? cy : cy + oy) - 16, w: 32, h: 32,
          dx: spent ? ox : -ox, dy: spent ? oy : -oy,
        });
      }
    };
    resFly("workers", "worker", me.workers, prev.workers);
    resFly("silver", "silver", me.silver, prev.silver);
    if (viewOppRef.current) {                              // opponent's spends, on the open modal
      resFly("opp-workers", "worker", oPlayer?.workers, prev.oppWorkers);
      resFly("opp-silver", "silver", oPlayer?.silver, prev.oppSilver);
    }
    if (!add.length) return;
    setFlyers((fs) => [...fs, ...add]);
    const ids = new Set(add.map((f) => f.id));
    setTimeout(() => setFlyers((fs) => fs.filter((f) => !ids.has(f.id))), 640);
  }, [game, me]);
  // Between-phase overlay: when the phase letter advances (A->B->C->D->E), pop a banner
  // announcing the new phase + the mine income you just collected, so the phase-end silver
  // (which flies to your counter on the same update) is never missed. Skipped while
  // reviewing and at game end (the results screen covers the final phase's income).
  useEffect(() => {
    const cur = game?.phase_letter;
    const prev = prevPhaseRef.current;
    prevPhaseRef.current = cur;
    if (reviewing || !cur || !prev || prev === cur || game?.phase === "over") return;
    const mines = me?.mines_count || 0;                 // mines held = silver gained this phase-end
    const workers = (me?.monastery_effects || []).includes(2) ? mines : 0;  // Monastery 2: +1 worker/mine
    setPhasePop({ from: prev, to: cur, silver: mines, workers });
    if (phasePopTimer.current) clearTimeout(phasePopTimer.current);
    phasePopTimer.current = setTimeout(() => { phasePopTimer.current = null; setPhasePop(null); }, 3300);
  }, [game?.phase_letter]);
  useEffect(() => () => { if (phasePopTimer.current) clearTimeout(phasePopTimer.current); }, []);  // tidy on unmount
  // Deselect a die once it's been used (its action applied) — adjust_die leaves
  // the die unused, so it stays selected.
  useEffect(() => {
    const d = game?.dice?.[myId];
    if (selDie != null && d && d.used[selDie]) setSelDie(null);
  }, [game, selDie, myId]);
  // Drop a stale storage selection so the "Click a glowing hex to place" hint never
  // lingers: clear it once the tile leaves storage (placed/discarded) or there's no
  // longer a way to place it (no die / extra-action value / town-hall placement).
  useEffect(() => {
    if (selStorage == null) return;
    const inStorage = (me?.storage || []).some((t) => t.id === selStorage);
    const placeCtx = pendingMine
      ? (game?.pending_kind === "townhall_place" || (game?.pending_kind === "extra_action" && extraValue != null))
      : (selDie != null);
    if (!inStorage || !placeCtx) setSelStorage(null);
  }, [me, selDie, selStorage, pendingMine, game?.pending_kind, extraValue]);

  // ── Expert tier: client-side WASM search (coc-core) ──
  // The server ships each bot ENGINE-MOVE decision via `ai_search` in room state;
  // this pool searches the decision's micro-actions one at a time (root-parallel:
  // every worker searches the same micro with a distinct seed, root visits are
  // SUMMED), builds the action chain, converts it to the compact dict-move and
  // submits it as `ai_move`. The server validates by legal-move membership and
  // applies; ANY failure here (worker crash, wasm blocked, tab lag) just times out
  // into the server's hard bot for that turn — never a stuck game.
  const COC_AI_SIMS_FALLBACK = 20000;      // aggregate per micro-decision if the server sends no cap
  const wasmPoolRef = useRef(null);        // [{ ready, request, terminate }]
  const [wasmReady, setWasmReady] = useState(false);
  const clientAiArmedRef = useRef(null);   // room we've announced capability for (reset per socket)
  const aiDecisionRef = useRef(-1);        // decision seq already dispatched

  useEffect(() => {
    if (roomData?.ai_difficulty !== "expert" || !roomData?.vs_ai || reviewOnly
        || wasmPoolRef.current || typeof Worker === "undefined") return;
    const url = `${import.meta.env.BASE_URL}wasm/coc-worker.js`;
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
        console.info(`[coc client-AI] ${live.length}/${cores} WASM workers ready`);
      } else {
        console.warn("[coc client-AI] no WASM workers loaded → server bot");
      }
    });
    return () => { pool.forEach((wk) => wk.terminate()); wasmPoolRef.current = null; setWasmReady(false); };
  }, [roomData?.ai_difficulty, roomData?.vs_ai, reviewOnly]);

  // Announce capability once per socket connection — the server disarms client_ai
  // on disconnect, so a reconnect must re-announce (hence the reset effect).
  useEffect(() => { if (!connected) clientAiArmedRef.current = null; }, [connected]);
  useEffect(() => {
    if (wasmReady && connected && roomData?.ai_difficulty === "expert" && roomData?.room_id
        && clientAiArmedRef.current !== roomData.room_id) {
      clientAiArmedRef.current = roomData.room_id;
      send({ action: "client_ai_ready" });
    }
  }, [wasmReady, connected, roomData?.room_id, roomData?.ai_difficulty, send]);

  // Drive one shipped decision: probe → (forced | fan-out search) → append → repeat
  // to the engine-move boundary → convert → submit. One dispatch per decision seq.
  useEffect(() => {
    const as = roomData?.ai_search;
    const pool = wasmPoolRef.current;
    if (!as || !wasmReady || !pool || pool.length === 0 || reviewOnly) return;
    if (aiDecisionRef.current === as.decision) return;
    aiDecisionRef.current = as.decision;
    const stateStr = JSON.stringify(as.state);
    const perWorkerSims = Math.max(1, Math.ceil((as.max_sims || COC_AI_SIMS_FALLBACK) / pool.length));
    let cancelled = false;
    (async () => {
      try {
        const prefix = [];
        for (let step = 0; step < 16 && !cancelled; step++) {
          const probe = await pool[0].request({ kind: "stepInfo", state: stateStr, prefix: JSON.stringify(prefix) });
          const info = probe?.info;
          if (!info || info.error) return;                    // server watchdog takes over
          if (info.boundary || (info.over && prefix.length)) {
            const conv = await pool[0].request({ kind: "chainMove", state: stateStr, prefix: JSON.stringify(prefix) });
            const mv = conv?.move;
            if (!cancelled && mv && !mv.includes('"error"')) {
              send({ action: "ai_move", decision: as.decision, move: JSON.parse(mv) });
            }
            return;
          }
          if (info.over) return;
          let action;
          if (info.forced >= 0) {
            action = info.forced;                             // single-legal: no search needed
          } else {
            const results = await Promise.all(pool.map((wk, i) => wk.request({
              kind: "searchCoC", state: stateStr, prefix: JSON.stringify(prefix),
              mode: as.mode || "hybrid", budget: as.budget_ms || 900, maxSims: perWorkerSims,
              seed: ((as.decision * 2654435761) ^ (step * 97 + i * 40503 + 1)) >>> 0,
            }).catch(() => null)));
            const total = new Int32Array(102);
            let got = 0;
            for (const r of results) {
              const v = r && r.visits;
              if (!v || v.length < 102) continue;
              got++;
              for (let a = 0; a < 102; a++) total[a] += v[a];
            }
            if (!got) return;
            action = 0;
            let stepSims = 0;                                // sum of root visits = sims this search ran
            for (let a = 0; a < 102; a++) { stepSims += total[a]; if (total[a] > total[action]) action = a; }
            turnSimsRef.current += stepSims;                 // accumulate across the whole bot turn
          }
          prefix.push(action);
        }
      } catch { /* watchdog fallback */ }
    })();
    return () => { cancelled = true; };
  }, [roomData?.ai_search?.decision, wasmReady, reviewOnly, send]); // eslint-disable-line react-hooks/exhaustive-deps

  // Print ONE line per bot turn with the total client-AI sims it searched (Expert tier).
  // Reset when the bot's turn begins; log the accumulated total when it hands back to you.
  useEffect(() => {
    const wasAi = prevAiSimRef.current;
    prevAiSimRef.current = aiThinking;
    if (aiThinking && !wasAi) turnSimsRef.current = 0;                 // bot's turn starting
    else if (!aiThinking && wasAi) {
      if (turnSimsRef.current > 0) console.info(`[coc client-AI] turn used ${turnSimsRef.current.toLocaleString()} sims`);
      turnSimsRef.current = 0;
    }
  }, [aiThinking]);

  // ── actions ──
  const startCreate = (vsAi, difficulty = "hard") => {
    const rid = roomCode();
    setRoomId(rid);
    try { localStorage.setItem("coc_roomId", rid); } catch {}
    connect(`${COC_WS}/${rid}/${myId}`, {
      action: "create", name: playerName, vs_ai: vsAi,
      board_id: myBoard, opp_board_id: oppBoard,
      ai_difficulty: difficulty,
    });
  };
  const startJoin = (rid) => {
    rid = (rid || "").toUpperCase();
    if (!rid) return;
    setRoomId(rid);
    try { localStorage.setItem("coc_roomId", rid); } catch {}
    connect(`${COC_WS}/${rid}/${myId}`, { action: "join", name: playerName, board_id: myBoard });
  };
  const resume = (rid) => {
    const tok = localStorage.getItem(`coc_token_${rid}_${myId}`);
    setRoomId(rid);
    try { localStorage.setItem("coc_roomId", rid); } catch {}
    connect(`${COC_WS}/${rid}/${myId}`, tok ? { action: "reconnect", token: tok } : { action: "join", name: playerName });
  };
  const leaveToLobby = () => {
    disconnect();
    // A read-only HTTP review has no WS and must NOT clear the resume pointer of a
    // real in-progress game the player also has.
    if (!reviewOnly) { try { localStorage.removeItem("coc_roomId"); } catch {} }
    setReviewOnly(false);
    setRoomData(null); setRoomId(""); setReviewing(false); setScreen("lobby"); fetchGames();
  };
  // Cancel an open game you created (host_id === myId). Mirrors Spender: authorize
  // by session token OR host player_id (so it still works after a session expires),
  // and only clear local resume state AFTER the server confirms the delete.
  const handleCancel = (id) => {
    const params = new URLSearchParams();
    params.set("player_id", myId);
    const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
    fetch(`${COC_HTTP}/games/${id}/cancel?${params.toString()}`, { method: "POST", headers })
      .then((r) => r.json())
      .then((d) => {
        if (!d.ok) { setToast(d.message || "Could not cancel"); return; }
        try {
          if (localStorage.getItem("coc_roomId") === id) localStorage.removeItem("coc_roomId");
          localStorage.removeItem(`coc_token_${id}_${myId}`);
        } catch {}
        setToast("Game canceled");
        fetchGames();
      })
      .catch(() => setToast("Could not cancel"));
  };
  const mv = (move) => {
    // Any action other than the undo itself means there's now something to undo.
    if (move?.type && move.type !== "undo_turn") setActedThisTurn(true);
    send({ action: "move", move });
  };

  // ── move helpers (respect extra_action mode) ──
  const inExtra = pendingMine && game?.pending_kind === "extra_action";
  const actionValue = inExtra ? extraValue : (selDie != null ? game?.dice?.[myId]?.values?.[selDie] : null);

  // Ship goods-depot pick: while a ship/monastery is asking which depot to drain, you
  // can click the depot directly on the board (in addition to the modal buttons).
  const shipPickMine = pendingMine && (game?.pending_kind === "ship_choose_depot" || game?.pending_kind === "ship_adjacent_depot");
  const shipCands = !shipPickMine ? []
    : (game.pending_kind === "ship_adjacent_depot" ? (game.pending?.ctx?.candidates || []) : [1, 2, 3, 4, 5, 6]);
  const shipPick = (d) => {
    if (game.pending_kind === "ship_choose_depot") { mv({ type: "ship_take_goods", depot: d }); return; }
    if (game.pending_kind === "ship_adjacent_depot" && shipCands.includes(d)) mv({ type: "ship_adjacent_take", depot: d });
  };

  // Building take-a-tile (carpenter/church/etc): same board-picking style as the ship —
  // click the depot holding the tile you want. A depot with exactly ONE candidate
  // (the carpenter's building case) takes on a depot click; a depot holding TWO
  // candidates (church: castle+monastery / mine+monastery) needs the specific tile
  // clicked to disambiguate (handled in clickDepotTile).
  const buildingPickMine = pendingMine && game?.pending_kind === "building_take_choice";
  const buildingCands = buildingPickMine ? (game.pending?.ctx?.candidates || []) : [];
  const buildingDepotCands = (d) => (game.depots[String(d)].hexes || []).filter((t) => buildingCands.includes(t.id)).map((t) => t.id);
  const buildingPick = (id) => mv({ type: "building_take_choice", tile_id: id });

  // Goods pick: the chosen depot had more new goods colors than free slots, so you
  // choose which type(s) to take. Click a goods token of an offered color in the
  // depot (that depot's tokens pulse), or a button in the floating modal.
  const goodsPickMine = pendingMine && game?.pending_kind === "goods_pick";
  const goodsPickColors = goodsPickMine ? (game.pending?.ctx?.colors || []) : [];
  const goodsPickDepot = goodsPickMine ? game.pending?.ctx?.depot : null;
  const goodsPick = (color) => { if (goodsPickColors.includes(color)) mv({ type: "goods_pick", color }); };

  // Warehouse: sell one goods type for silver. Optional — click one of YOUR goods
  // (they pulse), a button in the floating modal, or Skip. Mirrors the ship/goods picks.
  const warehouseMine = pendingMine && game?.pending_kind === "warehouse_sell";
  const warehouseSell = (color) => { if ((me?.goods?.[color] || 0) > 0) mv({ type: "warehouse_sell", color }); };

  // Click a goods chip in YOUR storage to sell it. Ability scenarios (a Warehouse
  // pending, the Castle bonus's chosen die) sell on click directly. Selling WITHOUT an
  // ability needs a die SELECTED first, and only the goods that die can sell (its value
  // == the goods' sell number) are clickable — otherwise a click just shows the goods
  // description, like before.
  const sellDieForGood = (color) => {
    const d = game?.dice?.[myId];
    if (!d || selDie == null || d.used[selDie]) return -1;
    return d.values[selDie] === goodsSellNum(color) ? selDie : -1;
  };
  const extraSellColor = (inExtra && extraValue != null) ? board?.goods_colors?.[extraValue - 1] : null;
  const canSellGood = (color) => (me?.goods?.[color] || 0) > 0 && (
    warehouseMine
    || extraSellColor === color
    || (myTurnRaw && !pendingMine && sellDieForGood(color) >= 0)
  );
  const sellGood = (color) => {
    if (!((me?.goods?.[color] || 0) > 0)) return;
    if (warehouseMine) { warehouseSell(color); return; }
    if (extraSellColor === color) { mv({ type: "extra_action", value: extraValue, sub: { type: "sell_goods" } }); return; }
    const i = sellDieForGood(color);
    if (myTurnRaw && !pendingMine && i >= 0) mv({ type: "sell_goods", die_index: i });
  };

  const doTakeWorkers = () => {
    if (inExtra) { if (extraValue == null) return; mv({ type: "extra_action", value: extraValue, sub: { type: "take_workers" } }); }
    else if (selDie != null) mv({ type: "take_workers", die_index: selDie });
  };
  const doSell = () => {
    if (inExtra) { if (extraValue == null) return; mv({ type: "extra_action", value: extraValue, sub: { type: "sell_goods" } }); }
    else if (selDie != null) mv({ type: "sell_goods", die_index: selDie });
  };
  // Tapping a tile you can't act on yet shows its description (mobile has no hover,
  // so this mirrors the PC title-tooltip — see also clickBlackTile).
  const clickDepotTile = (depot, tile, e) => {
    if (shipPickMine) return;   // clicking anywhere in a depot picks it (handled on the depot div)
    // Monastery #6 armed: click a BUILDING tile to take it for 2 workers.
    if (m6Armed) {
      if (tile.type === "building") { if (e) e.stopPropagation(); mv({ type: "monastery6_take", tile_id: tile.id }); setM6Armed(false); }
      else setToast(tileDesc(tile, board));
      return;
    }
    if (buildingPickMine) {
      // Take this exact tile if it's a candidate (disambiguates a 2-candidate depot);
      // stop the click from also hitting the depot's own pick handler.
      if (buildingCands.includes(tile.id)) { if (e) e.stopPropagation(); buildingPick(tile.id); }
      else setToast(tileDesc(tile, board));
      return;
    }
    if (!pendingMine && !myTurnRaw) { setToast(tileDesc(tile, board)); return; }
    if (inExtra) { if (extraValue == null) { setToast(tileDesc(tile, board)); return; } mv({ type: "extra_action", value: extraValue, sub: { type: "take_hex", depot, tile_id: tile.id } }); return; }
    if (selDie == null) { setToast(tileDesc(tile, board)); return; }
    mv({ type: "take_hex", die_index: selDie, depot, tile_id: tile.id });
  };
  const clickBlackTile = (tile) => {
    if (!myTurnRaw || pendingMine) { setToast(`${tileDesc(tile, board)}  ·  buy for 2 silver`); return; }
    mv({ type: "buy_black", tile_id: tile.id });
  };
  const clickHex = (sid, legal) => {
    if (!legal) return;
    if (setupPhase) { mv({ type: "place_starting_castle", space_id: sid }); return; }
    if (!selStorage) return;
    if (pendingMine && game.pending_kind === "townhall_place") { mv({ type: "townhall_place", tile_id: selStorage, space_id: sid }); return; }
    if (inExtra) { if (extraValue == null) { setToast("Pick a die value first"); return; } mv({ type: "extra_action", value: extraValue, sub: { type: "place_tile", tile_id: selStorage, space_id: sid } }); return; }
    if (selDie == null) { setToast("Select a die first"); return; }
    mv({ type: "place_tile", die_index: selDie, tile_id: selStorage, space_id: sid });
  };
  const adjustDie = (i, dir) => {
    const v = game.dice[myId].values[i];
    const to = ((v - 1 + dir + 6) % 6) + 1;
    mv({ type: "adjust_die", die_index: i, to });
  };
  // Net worker cost of nudging die `i` by `dir` (±1). Cost is distance-from-roll, so
  // moving back toward the rolled value REFUNDS (delta < 0). Mirrors engine _adjust_cost.
  const adjustDelta = (i, dir) => {
    const d = game?.dice?.[myId];
    if (!d) return 0;
    const cur = d.values[i];
    const to = ((cur - 1 + dir + 6) % 6) + 1;
    const orig = (d.orig || d.values)[i];
    const per = (me?.monastery_effects || []).includes(8) ? 2 : 1;
    const dist = (a, b) => { const s = Math.min(((b - a) % 6 + 6) % 6, ((a - b) % 6 + 6) % 6); return Math.ceil(s / per); };
    return dist(orig, to) - dist(orig, cur);
  };

  // ── placement legality (client-side highlight; server is authoritative) ──
  const placeValue = inExtra ? extraValue : (selDie != null ? game?.dice?.[myId]?.values?.[selDie] : null);
  const ignoreNumber = pendingMine && game?.pending_kind === "townhall_place";
  const legalTarget = (sid) => {
    if (!me) return false;
    // During setup any empty castle ("burgundy" backend color) space is a legal starting-castle spot.
    if (setupPhase) {
      if (game.turn !== myId) return false;
      const sp = boardSpaces(me.board_id)[sid];
      return !!sp && sp.color === "burgundy" && !me.duchy[sid];
    }
    if (!selStorage) return false;
    const sp = boardSpaces(me.board_id)[sid];
    if (!sp || me.duchy[sid]) return false;
    const tile = me.storage.find((t) => t.id === selStorage);
    if (!tile || tile.color !== sp.color) return false;
    if (!ignoreNumber) {
      if (placeValue == null) return false;
      // Match the engine's _free_shift_for_tile: the die's 1<->6-wrapping neighbors
      // are only legal when the player owns the free-shift monastery for THIS tile
      // type (9=building, 10=ship/livestock, 11=castle/mine/monastery). Otherwise
      // only the exact die value places (highlighting the ±1 spaces was misleading).
      const eff = me.monastery_effects || [];
      const freeShift = (tile.type === "building" && eff.includes(9))
        || ((tile.type === "ship" || tile.type === "livestock") && eff.includes(10))
        || ((tile.type === "castle" || tile.type === "mine" || tile.type === "monastery") && eff.includes(11));
      const allowed = freeShift
        ? new Set([placeValue, (placeValue % 6) + 1, ((placeValue - 2 + 6) % 6) + 1])
        : new Set([placeValue]);
      if (!allowed.has(sp.number)) return false;
    }
    // adjacency: any filled neighbor
    const [q, r] = sid.split(",").map(Number);
    const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, -1], [-1, 1]];
    return dirs.some(([dq, dr]) => me.duchy[`${q + dq},${r + dr}`]);
  };

  if (!board) {
    return (<div className="coc"><style>{css}</style><div className="coc-wrap"><p className="coc-empty">Loading…</p></div></div>);
  }

  // ─── Lobby ───────────────────────────────────────────────────────────────
  if (screen === "lobby") {
    return (
      <div className="coc"><style>{css}</style>
        <div className="coc-top coc-top-lobby">
          <div className="coc-top-left">
            <button className="coc-btn ghost sm" onClick={onExit}>← Back</button>
          </div>
          <span className="coc-title">Castles of Crimson</span>
          <span className="coc-user">{playerName}</span>
        </div>
        <div className="coc-wrap">
          <div className="coc-board-pick">
            <div className="coc-section-title">Your Board <span className="coc-card-meta">— {board.byId?.[myBoard]?.name}</span></div>
            <div className="coc-board-grid">
              {(board.boards || []).map((b) => (
                <BoardThumb key={b.id} spaces={b.spaces} name={b.name}
                  selected={myBoard === b.id} onClick={() => setMyBoard(b.id)} />
              ))}
            </div>
            <div className="coc-section-title">Bot's Board <span className="coc-card-meta">— {board.byId?.[oppBoard]?.name} (Play vs Bot only)</span></div>
            <div className="coc-board-grid">
              {(board.boards || []).map((b) => (
                <BoardThumb key={b.id} spaces={b.spaces} name={b.name}
                  selected={oppBoard === b.id} onClick={() => setOppBoard(b.id)} />
              ))}
            </div>
          </div>

          <div className="coc-create">
            <div className="coc-ai-picker-wrap">
              <button className={`coc-btn gold${showCreateMenu ? " active" : ""}`}
                title="Create a game — play a friend or the bot"
                onClick={() => setShowCreateMenu((v) => !v)}>
                + Create Game {showCreateMenu ? "▴" : "▾"}
              </button>
              {showCreateMenu && (
                <div className="coc-ai-picker">
                  <button className="coc-btn gold sm"
                    title="Create a game a friend can join from Open Games (or your room code)"
                    onClick={() => { setShowCreateMenu(false); startCreate(false); }}>
                    vs Friend
                  </button>
                  <span className="coc-ai-picker-label">vs Bot</span>
                  <button className="coc-btn outline sm" title="A capable opponent that makes the occasional mistake"
                    onClick={() => { setShowCreateMenu(false); startCreate(true, "normal"); }}>
                    Normal
                  </button>
                  <button className="coc-btn outline sm" title="Full-strength search — a real challenge"
                    onClick={() => { setShowCreateMenu(false); startCreate(true, "hard"); }}>
                    Hard
                  </button>
                  <button className="coc-btn outline sm" title="The learned neural net, searched in your browser — the strongest opponent"
                    onClick={() => { setShowCreateMenu(false); startCreate(true, "expert"); }}>
                    Expert
                  </button>
                </div>
              )}
            </div>
            <div className="coc-join">
              <input className="coc-input" placeholder="CODE" value={joinCode} maxLength={6}
                onChange={(e) => setJoinCode(e.target.value)} onKeyDown={(e) => e.key === "Enter" && startJoin(joinCode)} />
              <button className="coc-btn outline" onClick={() => startJoin(joinCode)}>Join</button>
            </div>
            <button className="coc-btn ghost sm" onClick={fetchGames}>↻</button>
          </div>

          <div className="coc-lobby-grid">
            <div className="coc-lobby-col">
              <div className="coc-section-hd">
                <div className="coc-section-title">Open Games</div>
                <span className="coc-muted">waiting for a second player</span>
              </div>
              {loadingGames && openGames.length === 0 ? (
                <div className="coc-empty"><span className="coc-spinner" />Loading…</div>
              ) : openGames.length === 0 ? (
                <div className="coc-empty">No open games. Create one!</div>
              ) : (
                openGames.map((g) => (
                  <div className="coc-card" key={g.id}>
                    <div className="coc-card-info">
                      <div className="coc-card-title">{g.host_id === myId ? "Your game" : `${g.host_name}'s game`}</div>
                      <div className="coc-card-meta">{g.id} · {timeAgo(g.created_at)}</div>
                    </div>
                    <div className="coc-card-actions">
                      {g.host_id === myId
                        ? <>
                            <button className="coc-btn outline sm" onClick={() => resume(g.id)}>Return</button>
                            <button className="coc-btn ghost sm" onClick={() => handleCancel(g.id)}>Cancel</button>
                          </>
                        : <button className="coc-btn gold sm" onClick={() => startJoin(g.id)}>Join</button>}
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="coc-lobby-col">
              <div className="coc-section-hd">
                <div className="coc-section-title">Active Games</div>
                <span className="coc-muted">{activeGames.length} in progress</span>
              </div>
              {activeGames.length === 0 ? (
                <div className="coc-empty">No games in progress.</div>
              ) : (() => {
                // All in-progress games (yours + others'). Yours pinned to the top;
                // each sub-list is already updated_at-desc from the backend.
                const mine = activeGames.filter((g) => g.player1_id === myId || g.player2_id === myId);
                const others = activeGames.filter((g) => g.player1_id !== myId && g.player2_id !== myId);
                const ordered = [...mine, ...others];
                return ordered.map((g) => {
                  const isMine = g.player1_id === myId || g.player2_id === myId;
                  const youP1 = g.player1_id === myId;
                  const turnName = g.turn === g.player1_id ? g.player1_name
                    : (g.turn === g.player2_id ? g.player2_name : null);
                  return (
                    <div className="coc-card" key={g.id}>
                      <div className="coc-card-info">
                        <div className="coc-card-title">
                          {isMine
                            ? <>{youP1 ? `${g.player1_name} (you)` : g.player1_name}{" vs "}{g.player2_name ? (youP1 ? g.player2_name : `${g.player2_name} (you)`) : "waiting…"}</>
                            : <>{g.player1_name} vs {g.player2_name || "waiting…"}</>}
                        </div>
                        <div className="coc-card-meta">{g.id} · {timeAgo(g.updated_at)}</div>
                      </div>
                      <div className="coc-card-actions">
                        {isMine ? (
                          <>
                            {g.turn === myId
                              ? <span className="coc-turn-badge">Your Turn</span>
                              : <span className="coc-their-badge">Their Turn</span>}
                            <button className="coc-btn outline sm" onClick={() => resume(g.id)}>Resume</button>
                          </>
                        ) : (
                          <span className="coc-their-badge">{turnName ? `${turnName}'s turn` : "In progress"}</span>
                        )}
                      </div>
                    </div>
                  );
                });
              })()}
            </div>

            <div className="coc-lobby-col">
              <div className="coc-section-hd">
                <div className="coc-section-title">History</div>
                <span className="coc-muted">{history.length ? `${history.length} finished` : ""}</span>
              </div>
              {!authUser ? (
                <div className="coc-empty">Log in to see your finished games.</div>
              ) : history.length === 0 ? (
                <div className="coc-empty">No finished games yet.</div>
              ) : (
                history.map((g) => (
                  <div className="coc-card" key={g.id}>
                    <div className="coc-card-info">
                      <div className="coc-card-title">
                        <span className={g.tie ? "" : (g.you_won ? "coc-won" : "coc-lost")}>{g.tie ? "Tie" : (g.you_won ? "Won" : "Lost")}</span>
                        {" vs "}{g.opp_name}
                      </div>
                      <div className="coc-card-meta">
                        {g.your_score != null && g.opp_score != null ? `${g.your_score}–${g.opp_score} · ` : ""}{timeAgo(g.updated_at)}
                      </div>
                    </div>
                    <div className="coc-card-actions">
                      <button className="coc-btn outline sm" onClick={() => enterCocReview(g.id)}>Review</button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
        {toast && <div className="coc-toast">{toast}</div>}
      </div>
    );
  }

  // ─── Waiting ─────────────────────────────────────────────────────────────
  if (screen === "waiting") {
    const isHost = roomData?.host === myId;
    const count = Object.keys(players).length;
    return (
      <div className="coc"><style>{css}</style>
        <div className="coc-wrap">
          <div className="coc-waiting">
            <div className="coc-section-title" style={{ border: "none" }}>Room Code</div>
            <div className="coc-code" onClick={() => { navigator.clipboard?.writeText(roomId); setToast("Copied!"); }}>{roomId}</div>
            <p className="coc-card-meta">{count}/2 players joined</p>
            <div style={{ marginTop: 18, display: "flex", gap: 10, justifyContent: "center" }}>
              {isHost
                ? <button className="coc-btn gold" disabled={count < 2} onClick={() => send({ action: "start" })}>Start Game</button>
                : <span className="coc-card-meta">Waiting for host…</span>}
              <button className="coc-btn ghost" onClick={leaveToLobby}>Leave</button>
            </div>
          </div>
        </div>
        {toast && <div className="coc-toast">{toast}</div>}
      </div>
    );
  }

  // ─── Winner ──────────────────────────────────────────────────────────────
  if (over && !reviewing) {
    const w = game.winner;
    const tie = Array.isArray(w);
    const isMe = !tie && w === myId;
    const winnerName = tie ? "Tie" : (players[w] || w);
    const order = game.order || Object.keys(players);
    const scores = roomData?.final_scores || {};
    const breakdowns = roomData?.vp_breakdown || {};
    return (
      <div className="coc"><style>{css}</style>
        <div className="coc-wrap">
          <div className="coc-review">
            <h2>{isMe ? "Victory!" : tie ? "It's a tie!" : "Defeat"}</h2>
            <p className="coc-card-meta" style={{ margin: "6px 0 4px" }}>
              {tie ? "The duchy is shared." : `${winnerName} has the greater duchy`}
            </p>
            <VpReview order={order} players={players} myId={myId} scores={scores}
              breakdowns={breakdowns} winnerPid={w} projected={false} />
            <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 18 }}>
              <button className="coc-btn outline" onClick={() => setReviewing(true)}>Review Board</button>
              <button className="coc-btn gold" onClick={leaveToLobby}>Back to Lobby</button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ─── Game ────────────────────────────────────────────────────────────────
  const dice = game.dice?.[myId];
  const oppDice = oppId ? game.dice?.[oppId] : null;
  // You must use BOTH dice before ending the turn (take-2-workers is always a
  // legal use for an otherwise-stuck die, so this can never soft-lock).
  const bothDiceUsed = !!dice && dice.used[0] && dice.used[1];
  // Something is undoable once you've spent a die / bought black / used monastery 6,
  // or this client recorded an action (covers worker-only die adjusts).
  const hasActed = actedThisTurn || (!!dice && (dice.used[0] || dice.used[1]))
    || !!game.black_depot_used_this_turn || !!game.m6_used_this_turn;
  const renderDuchy = (pdata, interactive, opp = false) => {
    const spaces = boardSpaces(pdata.board_id);
    const sids = Object.keys(spaces);
    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    const centers = {};
    for (const sid of sids) {
      const sp = spaces[sid];
      const c = hexCenter(sp.q, sp.r);
      centers[sid] = c;
      minX = Math.min(minX, c.x); maxX = Math.max(maxX, c.x);
      minY = Math.min(minY, c.y); maxY = Math.max(maxY, c.y);
    }
    const pad = HEX_S + 4;
    const vb = `${(minX - pad).toFixed(0)} ${(minY - pad).toFixed(0)} ${(maxX - minX + pad * 2).toFixed(0)} ${(maxY - minY + pad * 2).toFixed(0)}`;
    return (
      <svg className="coc-hexsvg" viewBox={vb}>
        <defs>
          {/* Empty spaces are SOCKETS the tiles drop into, so they read LOWERED: a
              strong dark band at the top (the socket lip's shadow) fading to a faint
              light rim at the bottom (the lit floor) — the inverse of a raised tile. */}
          <linearGradient id="coc-socket" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#000" stopOpacity="0.62" />
            <stop offset="42%" stopColor="#000" stopOpacity="0.16" />
            <stop offset="84%" stopColor="#000" stopOpacity="0" />
            <stop offset="100%" stopColor="#fff" stopOpacity="0.22" />
          </linearGradient>
          {/* A placed tile sits ON the board, so it gets the same raised bevel as
              the depot tiles (light top-left -> dark bottom) to pop out of its socket. */}
          <linearGradient id="coc-raise" x1="0" y1="0" x2="0.4" y2="1">
            <stop offset="0%" stopColor="#fff" stopOpacity="0.55" />
            <stop offset="26%" stopColor="#fff" stopOpacity="0.12" />
            <stop offset="60%" stopColor="#000" stopOpacity="0.06" />
            <stop offset="100%" stopColor="#000" stopOpacity="0.55" />
          </linearGradient>
        </defs>
        {sids.map((sid) => {
          const sp = spaces[sid];
          const c = centers[sid];
          const tile = pdata.duchy[sid];
          const legal = interactive && legalTarget(sid);
          const placed = !!tile;
          // Full colors for every hex (matching the depot tiles); placed tiles
          // are distinguished by a bright highlighted outline, not by dimming.
          const fill = placed ? (TILE_HEX[tile.color] || "#555") : (TILE_HEX[sp.color] || "#444");
          // Both the placed-tile gold rim AND the legal-target glow are drawn LAST
          // (stroke-only polygons over the bevel/socket gradient) so each stays uniform
          // all the way around — otherwise the gradient paints over the inner half of
          // the stroke (pale at the top, dark at the bottom) and the outline reads
          // asymmetrically.
          let stroke, strokeWidth;
          if (legal || placed) { stroke = "none"; strokeWidth = 0; }
          else { stroke = "rgba(0,0,0,.4)"; strokeWidth = 1; }
          return (
            <g key={sid} data-sid={opp ? undefined : sid} data-oppsid={opp ? sid : undefined} className={`coc-hex${legal ? " legal" : ""}`}
              onClick={() => { if (interactive && legal) clickHex(sid, legal); else if (tile) setToast(tileDesc(tile, board)); }}>
              <title>{tile ? tileDesc(tile, board)
                : setupPhase ? (sp.color === "burgundy" ? "Click to place your starting castle here." : `${colorLabel(sp.color)} space (die ${sp.number}).`)
                : `Empty ${colorLabel(sp.color)} space — place a matching tile using die ${sp.number}.`}</title>
              <polygon points={hexPoints(c.x, c.y, HEX_S - 1.5)} fill={fill} fillOpacity={placed ? 1 : 0.5}
                stroke={stroke} strokeWidth={strokeWidth} />
              <polygon points={hexPoints(c.x, c.y, HEX_S - 1.5)} fill={placed ? "url(#coc-raise)" : "url(#coc-socket)"}
                stroke="none" style={{ pointerEvents: "none" }} />
              {placed && <polygon points={hexPoints(c.x, c.y, HEX_S - 1.5)} fill="none"
                stroke="#fff2c0" strokeWidth={2.6} style={{ pointerEvents: "none" }} />}
              {legal && <polygon points={hexPoints(c.x, c.y, HEX_S - 1.5)} fill="none"
                stroke="var(--gold)" strokeWidth={3} style={{ pointerEvents: "none" }} />}
              {placed
                ? <TileArtSvg tile={tile} cx={c.x} cy={c.y} box={HEX_ART} />
                : svgPips(c.x, c.y, sp.number, sid)}
            </g>
          );
        })}
      </svg>
    );
  };

  const goodsForDie = actionValue != null ? board.goods_colors[actionValue - 1] : null;

  return (
    <div className="coc"><style>{css}</style>
      <div className="coc-wrap">
        <div className="coc-top">
          <div className="coc-top-left">
            <button className="coc-btn ghost sm" onClick={over ? () => setReviewing(false) : leaveToLobby}>← {over ? "Results" : "Menu"}</button>
            <span className="coc-title">Castles of Crimson</span>
          </div>
        </div>

        <div className="coc-statusbar">
          <div className="coc-status-left">
            <span className="coc-pill">Phase <b>{game.phase_letter}</b></span>
            <span className="coc-pill">Round <b>{game.round}/5</b></span>
            {(() => {
              // Goods still to be handed out THIS PHASE: the queued goods not yet placed
              // on a depot, shown in deal order (leftmost = next). One is dealt at the
              // start of each round, so this counts down 5 -> 0 across the phase.
              const q = game.goods_queue || [];
              return (
                <span className="coc-pill coc-goods-left" title="Goods still to be handed out this phase (next first)">
                  <span className="coc-goods-left-lbl">Goods left</span>
                  {q.length === 0
                    ? <span style={{ opacity: .6 }}>none</span>
                    : q.map((g, i) => (
                        <span key={g.id || i} className="coc-tile goods" title={tileDesc({ kind: "goods", color: g.color }, board)}
                          style={{ width: 15, height: 15, fontSize: ".52rem", background: GOODS_HEX[g.color] }}>{goodsSellNum(g.color)}</span>
                      ))}
                </span>
              );
            })()}
            <span className={`coc-turnbadge ${myTurnRaw ? "you" : "them"}`}>
              {over ? "Game over"
                : setupPhase ? (setupMine ? "Place your starting castle" : aiThinking ? "Bot is choosing…" : `${players[game.turn] || "Opponent"} is choosing…`)
                : aiThinking ? "Bot is playing…"
                : myTurnRaw ? (pendingMine ? "Your decision" : "Your turn")
                : `${players[game.turn] || "Opponent"}'s turn`}
            </span>
          </div>
          <div className="coc-vp coc-vp-click" onClick={() => over ? setReviewing(false) : setShowScores(true)}
            title={over ? "Final score (with end-of-game bonuses). Click for the full breakdown" : "Click for the full VP breakdown"}>
            {/* At game end show the FINAL score (leftover resources + monastery bonuses
                folded in); during play show the live placed-tile VP. */}
            <span className="v">{me ? "You" : ""} <b>{over && fscore?.[myId] != null ? fscore[myId] : (me?.vp ?? 0)}</b></span>
            {opp && <span className="v">{players[oppId]} <b>{over && fscore?.[oppId] != null ? fscore[oppId] : opp.vp}</b></span>}
            <span className="coc-vp-info">ⓘ</span>
          </div>
          <div className="coc-status-right">
            {!over && (confirmAbandon
              ? <>
                  <span className="coc-card-meta">Abandon game?</span>
                  <button className="coc-btn crimson sm" onClick={() => { send({ action: "abandon" }); setConfirmAbandon(false); }}>Yes, resign</button>
                  <button className="coc-btn ghost sm" onClick={() => setConfirmAbandon(false)}>No</button>
                </>
              : <button className="coc-btn ghost sm" onClick={() => setConfirmAbandon(true)}>Abandon</button>)}
            <button className="coc-btn outline sm" data-viewopp="1" onClick={() => setViewOpp(true)}>View Opponent</button>
            {oppDice && (
              <span className="coc-oppdice" title={`${players[oppId] || "Opponent"}'s dice`}>
                {[0, 1].map((i) => (
                  <span key={i} className={`coc-oppdie${oppDice.used?.[i] ? " used" : ""}`}><Pips n={oppDice.values[i]} /></span>
                ))}
              </span>
            )}
          </div>
        </div>

        {/* Region-completion VP (phase bonus + size bonus) + color-completion bonuses
            (which colors still award their large=1st / small=2nd VP bonus). */}
        <div className="coc-bonusbar" title="VP for being the 1st (large) / 2nd (small) player to fully complete every space of a color">
          <span className="coc-bonusbar-lbl coc-regbonus-lbl"
            title="Complete any region THIS phase for this many bonus VP, on top of its size bonus. It shrinks each phase: A +10 → B +8 → C +6 → D +4 → E +2.">
            Region phase bonus <b className="coc-regbonus">+{PHASE_BONUS[game.phase_letter] ?? 0}</b>
          </span>
          <span className="coc-bonus-div" />
          <span className="coc-bonusbar-lbl coc-regbonus-lbl"
            title="Fixed VP for completing a region, by its number of spaces (1–8). Added to the region phase bonus.">
            Region size bonus <b className="coc-regbonus coc-regsize">{AREA_SCORE.join("/")}</b>
          </span>
          <span className="coc-bonus-div" />
          <span className="coc-bonusbar-lbl">Color bonus</span>
          {BOARD_COLORS.map((c) => {
            const rem = game.bonus_tiles?.[c] || [];
            const size = rem.length >= 2 ? "large" : rem.length === 1 ? "small" : null;
            return (
              <span key={c} className={`coc-bonuschip${size ? "" : " gone"}`}
                title={`${colorLabel(c)}: ${size ? `${size} bonus available (+${rem[0]} VP)` : "both bonuses taken"}`}>
                <span className="coc-bonus-sw" style={{ background: TILE_HEX[c] }} />
                {size ? <b>+{rem[0]}</b> : <i>—</i>}
              </span>
            );
          })}
        </div>

        {/* Shared board: 6 numbered depots arranged as a hexagon, black depot centered */}
        <div className="coc-panel coc-board-panel">
          <div className="coc-board-head">
            <h3>The Board</h3>
            <div className="coc-whitedie">
              <span className="lbl">White die</span>
              <div className="coc-die white" title="white die (sets the goods depot)"><Pips n={game.white_die} /></div>
            </div>
          </div>

          {/* Turn-order track: pinned flush to the panel's upper-LEFT (it sits in the
              gutter beside the centered board — it used to overlap depot 1 after the
              board was narrowed). On mobile it reflows to a block above the board. */}
          <div className="coc-track-block">
            <div className="coc-track">
              <span className="coc-track-lbl">Turn order</span>
              <div className="coc-track-spaces">
                {(game.track || []).map((stack, s) => (
                  <div className="coc-track-space" key={s}>
                    <span className="coc-track-snum">{s}</span>
                    <div className="coc-track-stack">
                      {[...stack].reverse().map((pid) => (
                        <div key={pid} className={`coc-track-token${pid === game.start_player ? " start" : ""}`}
                          style={{ background: pid === myId ? "var(--gold)" : "#5a86c4", color: pid === myId ? "#15100a" : "#fff" }}
                          title={`${pid === myId ? "You" : (players[pid] || "Opp")}${pid === game.start_player ? " — goes first" : ""}`}>
                          {pid === myId ? "You" : (players[pid] || "Opp")}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="coc-track-cap">furthest right and furthest up goes first · each ship moves you 1 space right</div>
          </div>

          <div className="coc-board-hex">
            {[1, 2, 3, 4, 5, 6].map((d, idx) => {
              const depot = game.depots[String(d)];
              const match = dice && !pendingMine && [0, 1].some((i) => !dice.used[i] && dice.values[i] === d);
              const pos = DEPOT_POS[idx];
              // Put the number JUST OUTSIDE the box edge that faces the central
              // black depot. Pick the dominant axis of the vector toward center,
              // then sit the square a few px beyond that edge.
              const vx = 50 - pos.left, vy = 50 - pos.top, G = 6;
              let numStyle;
              if (Math.abs(vx) >= Math.abs(vy)) {
                numStyle = vx < 0
                  ? { left: 0, top: "50%", transform: `translate(calc(-100% - ${G}px), -50%)` }
                  : { left: "100%", top: "50%", transform: `translate(${G}px, -50%)` };
              } else {
                numStyle = vy < 0
                  ? { left: "50%", top: 0, transform: `translate(-50%, calc(-100% - ${G}px))` }
                  : { left: "50%", top: "100%", transform: `translate(-50%, ${G}px)` };
              }
              const bCands = buildingPickMine ? buildingDepotCands(d) : [];
              const pickable = shipPickMine ? shipCands.includes(d)
                : buildingPickMine ? bCands.length > 0
                : goodsPickMine ? d === goodsPickDepot     // pulse the pick depot; click its token
                : false;
              const depotPick = shipPickMine ? () => shipPick(d)
                : (buildingPickMine && bCands.length === 1 ? () => buildingPick(bCands[0]) : undefined);
              return (
                <div key={d} data-depot={d} className={`coc-depot${match ? " match" : ""}${pickable ? " coc-depot-pick" : ""}`}
                  style={{ left: `${pos.left}%`, top: `${pos.top}%` }}
                  onClick={depotPick}
                  title={pickable ? (shipPickMine ? `Take all goods from depot ${d}` : buildingPickMine ? `Take the highlighted tile from depot ${d}` : `Click a goods token to take that type`) : undefined}>
                  <span className="coc-minidie" style={numStyle} title={`Depot ${d} — take a tile here with a die showing ${d}`}><Pips n={d} /></span>
                  <div className="coc-tilewrap">
                    {depotSlots(d, depot.hexes).map((slot, i) => slot.tile ? (
                      <div key={slot.tile.id} className={`coc-tile${(buildingPickMine && buildingCands.includes(slot.tile.id)) || (m6Armed && slot.tile.type === "building") ? " coc-tile-pick" : ""}`} style={{ background: TILE_HEX[slot.tile.color] }}
                        title={m6Armed && slot.tile.type === "building" ? `Take ${tileName(slot.tile)} for 2 workers (Monastery #6)` : tileDesc(slot.tile, board)} onClick={(e) => clickDepotTile(d, slot.tile, e)}>
                        <TileArt tile={slot.tile} px={HEX_W} />
                      </div>
                    ) : (
                      <div key={`ghost-${i}`} className="coc-tile coc-tile-ghost"
                        style={{ background: TILE_HEX[slot.ghost] }}
                        title={`${COLOR_TYPE_LABEL[slot.ghost] || "Tile"} taken — this depot refills a ${COLOR_TYPE_LABEL[slot.ghost]?.toLowerCase() || ""} tile here each phase`}>
                      </div>
                    ))}
                    {depot.goods.map((gt) => {
                      const canPickGood = goodsPickMine && d === goodsPickDepot && goodsPickColors.includes(gt.color);
                      return (
                        <div key={gt.id} className={`coc-tile goods${canPickGood ? " coc-tile-pick" : ""}`} style={{ background: GOODS_HEX[gt.color] }}
                          title={canPickGood ? `Take all #${goodsSellNum(gt.color)} goods` : tileDesc(gt, board)}
                          onClick={(e) => { if (canPickGood) { e.stopPropagation(); goodsPick(gt.color); } else if (!shipPickMine) setToast(tileDesc(gt, board)); }}>{goodsSellNum(gt.color)}</div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
            <div data-blackdepot="1" className="coc-depot coc-black-center" style={{ width: 2 * HEX_W + BLACK_GAP + 2 * BLACK_PAD, height: 2.5 * HEX_H + 2 * BLACK_GAP + 2 * BLACK_PAD }}
              title="Central black depot — buy one tile per turn for 2 silver">
              {game.black_depot.map((t, i) => {
                const k = BLACK_KITE[i];
                if (!k) return null;   // the black depot holds at most 4 tiles
                return (
                  <div key={t.id} className="coc-tile" style={{ position: "absolute", left: `${k.left + BLACK_PAD}px`, top: `${k.top + BLACK_PAD}px`, background: TILE_HEX[t.color], opacity: .9 }}
                    title={`${tileDesc(t, board)}  (Black depot: buy for 2 silver.)`} onClick={() => clickBlackTile(t)}>
                    <TileArt tile={t} px={HEX_W} />
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Your area: controls on the left, duchy board on the right */}
        <div className="coc-panel">
          <div className="coc-duchy-head">
            <h3>Your Duchy — {me?.vp ?? 0} VP</h3>
            {game.turn === myId && !over && !setupPhase && (
              <button className="coc-btn ghost sm" disabled={!hasActed}
                title={hasActed ? "Undo everything you've done this turn" : "Nothing to undo yet"}
                onClick={() => { setSelDie(null); setSelStorage(null); setExtraValue(null); setActedThisTurn(false); mv({ type: "undo_turn" }); }}>↩ Undo Turn</button>
            )}
          </div>
          <div className="coc-duchy-layout">
            <div className="coc-duchy-controls">
              {setupPhase && (
                <div className="coc-setup-banner">
                  <b>Starting castle.</b>{" "}
                  {setupMine
                    ? "Click a glowing crimson space to place it — your duchy grows outward from here."
                    : `Waiting for ${players[game.turn] || "your opponent"} to choose…`}
                </div>
              )}
              {/* dice + resources */}
              <div className="coc-dicebar">
                <span className="coc-pill">Dice</span>
                {dice && [0, 1].map((i) => (
                  <div key={i} style={{ display: "flex", gap: 4, alignItems: "center" }}>
                    <div className={`coc-die${selDie === i ? " sel" : ""}${dice.used[i] ? " used" : ""}`}
                      onClick={() => { if (!dice.used[i] && !pendingMine) setSelDie(selDie === i ? null : i); }}><Pips n={dice.values[i]} /></div>
                    {!pendingMine && (
                      <div className="coc-die-adj">
                        <button disabled={dice.used[i] || !me || adjustDelta(i, +1) > (me.workers || 0)}
                          title={adjustDelta(i, +1) < 0 ? "Refunds a worker (back toward the roll)" : "Spend a worker to raise this die"}
                          onClick={() => adjustDie(i, +1)}>▲</button>
                        <button disabled={dice.used[i] || !me || adjustDelta(i, -1) > (me.workers || 0)}
                          title={adjustDelta(i, -1) < 0 ? "Refunds a worker (back toward the roll)" : "Spend a worker to lower this die"}
                          onClick={() => adjustDie(i, -1)}>▼</button>
                      </div>
                    )}
                  </div>
                ))}
                <div className="coc-resbar">
                  <span className="coc-token-chip"
                    title={canUseM6 ? (m6Armed ? "Monastery #6 armed — click a building tile in a depot (2 workers). Click again to cancel." : "Monastery #6: click, then a building tile in a depot to take it for 2 workers") : "Workers — spent to adjust dice"}>
                    <span className={`coc-token worker${canUseM6 ? " coc-m6-arm" : ""}${m6Armed ? " coc-m6-on" : ""}`} data-workers="1"
                      onClick={canUseM6 ? () => setM6Armed((a) => !a) : undefined}>⚒</span><b>{me?.workers ?? 0}</b>
                  </span>
                  <span className="coc-token-chip" title="Silver — spent to buy black-depot tiles">
                    <span className="coc-token silver" data-silver="1">⛃</span><b>{me?.silver ?? 0}</b>
                  </span>
                </div>
              </div>

              {/* storage + goods */}
              <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
                <div>
                  <div className="coc-pill" style={{ marginBottom: 4 }}>Storage</div>
                  <div className="coc-storage" data-storage="1">
                    {[0, 1, 2].map((i) => {
                      const t = me?.storage?.[i];
                      if (!t) return <div key={i} data-storage-slot={i} className="coc-stt empty" style={{ background: "var(--surface2)" }} />;
                      const isSel = selStorage === t.id;
                      return (
                        <div key={t.id} className={`coc-stt-wrap${isSel ? " sel" : ""}`}>
                          <div data-storage-slot={i} className={`coc-stt${isSel ? " sel" : ""}`} style={{ background: TILE_HEX[t.color] }}
                            title={tileDesc(t, board)}
                            onClick={() => {
                              // Only SELECT a storage tile when there's a way to place it
                              // (a die chosen, or an extra-action value, or a town-hall extra
                              // placement). Otherwise a tap just shows the description.
                              const canPlace = pendingMine
                                ? (game.pending_kind === "townhall_place" || (inExtra && extraValue != null))
                                : (selDie != null);
                              if (canPlace) setSelStorage(isSel ? null : t.id);
                              else setToast(tileDesc(t, board));
                            }}>
                            <TileArt tile={t} px={70} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
                <div>
                  <div className="coc-pill" style={{ marginBottom: 4 }}>Goods</div>
                  <div className="coc-goods-row" data-mygoods="1">
                    {me && Object.entries(me.goods).map(([c, n]) => {
                      const sellable = canSellGood(c);
                      return (
                        <span key={c} data-goodchip={c} className={`coc-goods-chip${sellable ? " coc-goods-pick" : ""}`}
                          title={sellable ? `Sell #${goodsSellNum(c)} goods for silver` : tileDesc({ kind: "goods", color: c }, board)}
                          onClick={() => sellable ? sellGood(c) : setToast(tileDesc({ kind: "goods", color: c }, board))}>
                          <span className="coc-tile goods" style={{ background: GOODS_HEX[c] }}>{goodsSellNum(c)}</span>×{n}
                        </span>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* action buttons */}
              {myTurnRaw && !pendingMine && !setupPhase && (
                <div className="coc-actions">
                  <button className="coc-btn tool sm" disabled={selDie == null} onClick={doTakeWorkers}>Take 2 Workers</button>
                  <button className="coc-btn tool sm" disabled={selDie == null || !(me?.goods?.[goodsForDie] > 0)} onClick={doSell}>
                    Sell{goodsForDie
                      ? <> <span className="coc-tile goods" style={{ display: "inline-flex", width: 15, height: 15, fontSize: ".55rem", background: GOODS_HEX[goodsForDie] }}>{actionValue}</span>{me?.goods?.[goodsForDie] ? ` ×${me.goods[goodsForDie]}` : ""}</>
                      : " goods"}
                  </button>
                  {me?.storage?.length >= 3 && (
                    <button className="coc-btn ghost sm" disabled={!selStorage}
                      title="Storage is full — discard a tile (back to the box) to make room"
                      onClick={() => { mv({ type: "discard_storage", tile_id: selStorage }); setSelStorage(null); }}>
                      Discard
                    </button>
                  )}
                  <button className="coc-btn crimson sm" disabled={!bothDiceUsed}
                    title={bothDiceUsed ? "End your turn" : "Use both dice before ending your turn"}
                    onClick={() => mv({ type: "end_turn" })}>End Turn</button>
                  <span className="coc-card-meta" style={{ alignSelf: "center" }}>
                    {me?.storage?.length >= 3 && selStorage ? "Storage full — Discard frees this slot."
                      : selStorage ? "Click a glowing hex to place."
                      : selDie != null ? "Click a depot tile to take, or a storage tile to place." : ""}
                  </span>
                </div>
              )}
            </div>
            <div className="coc-duchy-board">
              {renderDuchy(me, myTurnRaw)}
            </div>
          </div>
        </div>

        {/* move log */}
        <div className="coc-panel">
          <h3>Log</h3>
          <div className="coc-log">
            {(game.moves || []).map((m, i) => (
              m.type === "phase_end"
                ? <div key={i} className="coc-log-phase">{moveText(m, board)}</div>
                : <div key={i}>
                    {/* phase-round label ("A-1".."E-5"); T# fallback for pre-ph saved games */}
                    <span className="coc-log-t">{m.t ? (m.ph ? `${m.ph}-${m.rd}` : `T${m.t}`) : "·"}</span>
                    {/* base text, then VP (build_gain already states its VP), then the source
                        tile in parens so ability actions end with e.g. "(Market)". */}
                    {m.pid ? `${players[m.pid] || m.pid} ` : ""}{moveText(m, board)}{(m.type !== "build_gain" && m.vp) ? ` (+${m.vp} VP)` : ""}{m.via ? ` (${viaLabel(m.via)})` : ""}
                  </div>
            ))}
          </div>
        </div>
      </div>

      {/* pending decision modals */}
      {pendingMine && <PendingModal game={game} board={board} me={me} extraValue={extraValue}
        setExtraValue={setExtraValue} mv={mv} goodsForDie={goodsForDie} />}

      {/* opponent view */}
      {viewOpp && opp && (
        <div className="coc-modal-bg" onClick={() => setViewOpp(false)}>
          <div className="coc-modal" style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
            <h3>{players[oppId]} — {opp.vp} VP</h3>
            <div style={{ display: "flex", gap: 14, marginBottom: 10 }}>
              <span className="coc-token-chip"><span className="coc-token worker" data-opp-workers="1">⚒</span><b>{opp.workers}</b></span>
              <span className="coc-token-chip"><span className="coc-token silver" data-opp-silver="1">⛃</span><b>{opp.silver}</b></span>
            </div>
            <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "flex-start", marginBottom: 10 }}>
              <div>
                <div className="coc-pill" style={{ marginBottom: 4 }}>Dice</div>
                <div className="coc-dicebar">
                  {game.dice?.[oppId]?.values.map((v, i) => (
                    <div key={i} className={`coc-die${game.dice[oppId].used[i] ? " used" : ""}`} style={{ width: 34, height: 34, fontSize: "1rem" }}><Pips n={v} /></div>
                  ))}
                </div>
              </div>
              <div>
                <div className="coc-pill" style={{ marginBottom: 4 }}>Storage</div>
                <div className="coc-storage">
                  {[0, 1, 2].map((i) => {
                    const t = opp.storage?.[i];
                    if (!t) return <div key={i} data-oppstorage-slot={i} className="coc-stt empty" style={{ background: "var(--surface2)" }} />;
                    return <div key={t.id} data-oppstorage-slot={i} className="coc-stt" style={{ background: TILE_HEX[t.color] }} title={tileDesc(t, board)} onClick={() => setToast(tileDesc(t, board))}><TileArt tile={t} px={70} /></div>;
                  })}
                </div>
              </div>
              <div>
                <div className="coc-pill" style={{ marginBottom: 4 }}>Goods</div>
                <div className="coc-goods-row" data-oppgoods="1">
                  {Object.entries(opp.goods).map(([c, n]) => (
                    <span key={c} data-oppgoodchip={c} className="coc-goods-chip" title={tileDesc({ kind: "goods", color: c }, board)} onClick={() => setToast(tileDesc({ kind: "goods", color: c }, board))}><span className="coc-tile goods" style={{ background: GOODS_HEX[c] }}>{goodsSellNum(c)}</span>×{n}</span>
                  ))}
                </div>
              </div>
            </div>
            {renderDuchy(opp, false, true)}
            <div className="coc-modal-row" style={{ marginTop: 12, justifyContent: "flex-end" }}>
              <button className="coc-btn gold sm" onClick={() => setViewOpp(false)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {/* Mid-game VP breakdown (click the score). End-of-game bonuses are faded — a
          projection that only counts once the game ends. */}
      {showScores && !over && (
        <div className="coc-modal-bg" onClick={() => setShowScores(false)}>
          <div className="coc-modal coc-review-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Score breakdown</h3>
            <p className="coc-review-hint">End-of-game bonuses are faded — they're projected and only count once the game ends.</p>
            <VpReview order={game.order || Object.keys(players)} players={players} myId={myId}
              scores={roomData?.final_scores || {}} breakdowns={roomData?.vp_breakdown || {}}
              winnerPid={null} projected />
            <div className="coc-modal-row" style={{ marginTop: 12, justifyContent: "flex-end" }}>
              <button className="coc-btn gold sm" onClick={() => setShowScores(false)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {flyers.length > 0 && (
        <div className="coc-fly-layer">
          {flyers.map((f) => (
            f.token ? (
              <div key={f.id} className={`coc-token-flyer ${f.token} ${f.spent ? "spent" : "gain"}`}
                style={{ left: f.left, top: f.top, width: f.w, height: f.h, "--dx": `${f.dx}px`, "--dy": `${f.dy}px` }}>
                {f.token === "worker" ? "⚒" : "⛃"}
              </div>
            ) : f.goods ? (
              <div key={f.id} className="coc-flyer goods"
                style={{ left: f.left, top: f.top, width: f.w, height: f.h, background: GOODS_HEX[f.color] || "#555",
                  "--dx": `${f.dx}px`, "--dy": `${f.dy}px`, "--s0": 1, "--s1": f.s1 }}>
                {goodsSellNum(f.color)}
              </div>
            ) : (
              <div key={f.id} className="coc-flyer"
                style={{ left: f.left, top: f.top, width: f.w, height: f.h, background: TILE_HEX[f.tile.color] || "#555",
                  "--dx": `${f.dx}px`, "--dy": `${f.dy}px`, "--s0": f.s0 ?? 1, "--s1": f.s1 }}>
                <TileArt tile={f.tile} px={f.w} />
              </div>
            )
          ))}
        </div>
      )}

      {phasePop && (
        <div className="coc-phase-pop" key={`${phasePop.from}${phasePop.to}`}>
          <div className="coc-phase-pop-card">
            <div className="coc-phase-pop-sub">Phase {phasePop.from} complete</div>
            <div className="coc-phase-pop-big">Phase {phasePop.to}</div>
            {(phasePop.silver > 0 || phasePop.workers > 0) ? (
              <div className="coc-phase-pop-inc">
                {phasePop.silver > 0 && (
                  <span className="coc-phase-pop-gain"><span className="coc-token silver">⛃</span>+{phasePop.silver}</span>
                )}
                {phasePop.workers > 0 && (
                  <span className="coc-phase-pop-gain"><span className="coc-token worker">⚒</span>+{phasePop.workers}</span>
                )}
                <span className="coc-phase-pop-src">from your mines</span>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {reconnecting && !connected && inLiveGame && (
        <div className="coc-reconnbar"><span className="coc-spinner" /> Reconnecting…</div>
      )}
      {toast && <div className="coc-toast">{toast}</div>}
    </div>
  );
}

// ─── VP breakdown (shared by the end-game results + the mid-game score popup) ──
// `projected` = the game is still on, so the end-of-game items are a projection —
// fade them and show the header as the currently-realized VP (not the projected total).
function VpReview({ order, players, myId, scores, breakdowns, winnerPid, projected }) {
  const winners = Array.isArray(winnerPid) ? winnerPid : (winnerPid != null ? [winnerPid] : []);
  return (
    <div className="coc-review-grid">
      {order.map((pid) => {
        const bd = breakdowns[pid] || [];
        const during = bd.filter((i) => i.t != null).sort((a, b) => (a.t - b.t) || 0);
        const ends = bd.filter((i) => i.t == null);
        const total = scores[pid] != null ? scores[pid] : bd.reduce((s, i) => s + i.vp, 0);
        const realized = during.reduce((s, i) => s + i.vp, 0);   // officially-scored so far
        const won = winners.includes(pid);
        return (
          <div key={pid} className={`coc-review-col${won ? " win" : ""}`}>
            <div className="coc-review-hd">
              <span>{(players[pid] || pid)}{pid === myId ? " (you)" : ""}</span>
              <b>{projected ? realized : total} VP</b>
            </div>
            <div className="coc-review-list">
              {bd.length === 0 && <div className="coc-review-empty">No breakdown available for this game.</div>}
              {during.map((i, k) => (
                <Fragment key={`d${k}`}>
                  {/* segment by phase (like the log's phase dividers); items carry ph/rd
                      from the move log — absent on pre-ph saved games (no dividers, T# label) */}
                  {i.ph && i.ph !== during[k - 1]?.ph && (
                    <div className="coc-review-phase">— Phase {i.ph} —</div>
                  )}
                  <div className="coc-review-row">
                    <span className="coc-review-t">{i.ph ? `${i.ph}-${i.rd}` : `T${i.t}`}</span>
                    <span className="coc-review-lbl">{i.label}</span>
                    <span className="coc-review-vp">+{i.vp}</span>
                  </div>
                </Fragment>
              ))}
              {ends.length > 0 && <div className={`coc-review-phase${projected ? " proj" : ""}`}>— End of game{projected ? " (projected)" : ""} —</div>}
              {ends.map((i, k) => (
                <div key={`e${k}`} className={`coc-review-row${projected ? " proj" : ""}`}>
                  <span className="coc-review-t">end</span>
                  <span className="coc-review-lbl">{i.label}</span>
                  <span className="coc-review-vp">+{i.vp}</span>
                </div>
              ))}
              <div className={`coc-review-row coc-review-total${projected ? " proj" : ""}`}>
                <span className="coc-review-t" />
                <span className="coc-review-lbl">{projected ? "Projected total" : "Total"}</span>
                <span className="coc-review-vp">{total}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Pending decision modal ──────────────────────────────────────────────────
function PendingModal({ game, board, me, extraValue, setExtraValue, mv, goodsForDie }) {
  const kind = game.pending_kind;
  const skip = () => mv({ type: "skip_pending" });
  const sellNum = (c) => board.goods_colors.indexOf(c) + 1;

  if (kind === "ship_choose_depot") {
    return (
      <Modal title="Ship — take goods" desc="Click a highlighted depot on the board (or a button below) to take all its goods." interactive>
        <div className="coc-modal-row">
          {[1, 2, 3, 4, 5, 6].map((d) => {
            const n = game.depots[String(d)].goods.length;
            return <button key={d} className="coc-btn outline sm" onClick={() => mv({ type: "ship_take_goods", depot: d })}>◆{d} ({n})</button>;
          })}
          <button className="coc-btn ghost sm" onClick={skip}>Skip</button>
        </div>
      </Modal>
    );
  }
  if (kind === "ship_adjacent_depot") {
    const cands = game.pending?.ctx?.candidates || [];
    return (
      <Modal title="Monastery — adjacent depot" desc="Click a highlighted adjacent depot on the board (or a button below) to also take its goods." interactive>
        <div className="coc-modal-row">
          {cands.map((d) => {
            const n = game.depots[String(d)].goods.length;
            return <button key={d} className="coc-btn outline sm" onClick={() => mv({ type: "ship_adjacent_take", depot: d })}>◆{d} ({n})</button>;
          })}
          <button className="coc-btn ghost sm" onClick={skip}>Skip</button>
        </div>
      </Modal>
    );
  }
  if (kind === "goods_pick") {
    const colors = game.pending?.ctx?.colors || [];
    return (
      <Modal title="Choose goods to take" desc="This depot has more goods types than you have free slots. Click a highlighted goods token on the board (or a button below) to take that type; you may take more until your slots are full." interactive>
        <div className="coc-modal-row">
          {colors.map((c) => (
            <button key={c} className="coc-btn outline sm" onClick={() => mv({ type: "goods_pick", color: c })}>
              <span className="coc-tile goods" style={{ display: "inline-flex", width: 15, height: 15, fontSize: ".55rem", background: GOODS_HEX[c], marginRight: 5 }}>{sellNum(c)}</span>#{sellNum(c)} goods
            </button>
          ))}
          <button className="coc-btn ghost sm" onClick={skip}>Skip</button>
        </div>
      </Modal>
    );
  }
  if (kind === "building_take_choice") {
    const ids = game.pending?.ctx?.candidates || [];
    const find = (id) => {
      for (let d = 1; d <= 6; d++) { const t = game.depots[String(d)].hexes.find((x) => x.id === id); if (t) return t; }
      return null;
    };
    return (
      <Modal title="Take a tile" desc="Click a highlighted tile in a depot on the board (or a button below) to take it into storage." interactive>
        <div className="coc-modal-row">
          {ids.map((id) => { const t = find(id); if (!t) return null; return (
            <button key={id} className="coc-btn outline sm" onClick={() => mv({ type: "building_take_choice", tile_id: id })}>
              {TYPE_LABEL[t.type]}{t.type === "monastery" ? ` #${t.effect_id}` : t.type === "building" ? ` (${t.building})` : ""}
            </button>); })}
          <button className="coc-btn ghost sm" onClick={skip}>Skip</button>
        </div>
      </Modal>
    );
  }
  if (kind === "warehouse_sell") {
    return (
      <Modal title="Warehouse — sell goods" desc="Click one of your goods (or a button below) to sell it for silver — optional." interactive>
        <div className="coc-modal-row">
          {Object.keys(me.goods).filter((c) => me.goods[c] > 0).map((c) => (
            <button key={c} className="coc-btn outline sm" onClick={() => mv({ type: "warehouse_sell", color: c })}>
              <span className="coc-tile goods" style={{ display: "inline-flex", width: 15, height: 15, fontSize: ".55rem", background: GOODS_HEX[c], marginRight: 5 }}>{sellNum(c)}</span>#{sellNum(c)} goods ×{me.goods[c]}
            </button>
          ))}
          <button className="coc-btn ghost sm" onClick={skip}>Skip</button>
        </div>
      </Modal>
    );
  }
  if (kind === "townhall_place") {
    return (
      <Modal title="Town Hall — extra placement" desc="Select a storage tile, then click a glowing hex to place it (any number)." interactive>
        <div className="coc-modal-row"><button className="coc-btn ghost sm" onClick={skip}>Skip</button></div>
      </Modal>
    );
  }
  if (kind === "extra_action") {
    return (
      <Modal title="Castle — bonus action" desc={extraValue == null ? "Pick a die value, then take an action (depot/board/buttons)." : `Value ${extraValue}: take a hex, place a tile, sell, or take workers.`} interactive>
        <div className="coc-modal-row">
          {[1, 2, 3, 4, 5, 6].map((v) => (
            <button key={v} className={`coc-btn ${extraValue === v ? "gold" : "outline"} sm`} onClick={() => setExtraValue(v)}>{v}</button>
          ))}
        </div>
        {extraValue != null && (
          <div className="coc-modal-row" style={{ marginTop: 10 }}>
            <button className="coc-btn ghost sm" onClick={() => mv({ type: "extra_action", value: extraValue, sub: { type: "take_workers" } })}>Take 2 Workers</button>
            <button className="coc-btn ghost sm" disabled={!(me.goods[goodsForDie] > 0)} onClick={() => mv({ type: "extra_action", value: extraValue, sub: { type: "sell_goods" } })}>
              Sell{goodsForDie
                ? <> <span className="coc-tile goods" style={{ display: "inline-flex", width: 15, height: 15, fontSize: ".55rem", background: GOODS_HEX[goodsForDie] }}>{sellNum(goodsForDie)}</span> #{sellNum(goodsForDie)} goods{me.goods[goodsForDie] ? ` ×${me.goods[goodsForDie]}` : ""}</>
                : " goods"}</button>
          </div>
        )}
        <div className="coc-modal-row" style={{ marginTop: 10 }}><button className="coc-btn ghost sm" onClick={skip}>Skip bonus</button></div>
      </Modal>
    );
  }
  return null;
}

// `interactive` modals (Town Hall / Castle bonus) must NOT block the board behind
// them — the player resolves them by clicking storage tiles + glowing hexes. So the
// backdrop passes clicks through (pointer-events:none) and the panel is pinned to the
// bottom edge, clear of the depots/storage/duchy.
function Modal({ title, desc, children, interactive }) {
  return (
    <div className={`coc-modal-bg${interactive ? " coc-modal-float" : ""}`}>
      <div className="coc-modal">
        <h3>{title}</h3>
        <p>{desc}</p>
        {children}
      </div>
    </div>
  );
}
