import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { baseCss } from "../../shared/theme.js";
import ragtagCssText from "./RagTag.css?inline";
import RagTagRules from "./rules.jsx";
import {
  lobbyCss, LobbyHeader, LobbySectionHd, TurnBadge, LobbyLoading, LobbyEmpty,
  LobbyAction, LobbyTabs, notWaiting, GameMenu, gameMenuCss,
  createModalCss, CreateModal, CmRow, CmSeg, LobbyCreateRow, lobbyCreateRowCss,
  RulesModal, rulesModalCss, useProgressiveList,
  readLobbyCache, writeLobbyCache,
} from "../../shared/lobby.jsx";
import { buildPath, pushPath, replacePath, subscribe } from "../../shared/router.js";
import { Sigil, Icon, sigilOf, iconForOp, FX_TEXT, OP_GLOSSARY } from "./art.jsx";
import { narrateBeat, narrateRound } from "./narrate.jsx";
import { useCardInfoGesture } from "../../shared/gestures.js";

/* Rag Tag — a two-player auto battler.
 *
 * The one thing that shapes this whole file: the game is SIMULTANEOUS. There is
 * no "your turn". Both players submit secretly and the round resolves when both
 * are in, so every prompt here is "you owe a submission" and every wait is
 * "waiting for them", never "waiting for the board".
 *
 * The FIGHT! step is resolved server-side in one go and arrives as `beats` — one
 * entry per turn with both revealed cards and every delta. This component plays
 * them back with a dwell so the fight reads as a fight rather than a diff. The
 * beats live in GAME STATE, so a reconnect mid-animation re-ships them.
 */

const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const WS_BASE = WS_RAW.replace(/\/ws$/, "");
const RT_WS = `${WS_BASE}/ragtag/ws`;
const RT_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/ragtag");

/* baseCss FIRST, and it is not optional: the shared lobby kit is written
 * against the site theme tokens (--surface, --border, --radius, --text...).
 * Without it every `border: 1px solid var(--border)` in that kit is invalid at
 * computed-value time and silently resolves to `0px none` — the lobby still
 * lays out, so it looks like a design choice rather than a missing import.
 * Rag Tag shipped without it; the other five games all have it. */
const ragtagStyles =
  baseCss + lobbyCss + gameMenuCss + createModalCss + lobbyCreateRowCss
  + rulesModalCss + ragtagCssText;

/* There is deliberately NO dwell timer. The fight used to play itself at a
 * fixed 900ms a turn, which meant the one thing worth watching — what the two
 * cards did to each other — was gone before it could be read. Every turn now
 * waits for a click, and the log keeps what has already gone past. */

function timeAgo(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
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
  const disconnect = useCallback(() => {
    try { wsRef.current?.close(); } catch {}
    wsRef.current = null; setConnected(false);
  }, []);
  return { connected, connect, send, disconnect };
}

/* ── Rendering the mechanics ──────────────────────────────────────────────
 * Cards arrive from /catalog as op lists rather than printed text, because the
 * generated data is mechanics only — no publisher wording, no art. So the UI
 * says what a card DOES in its own vocabulary. That is also why the same op list
 * can drive the board, the log and the tooltip without three transcriptions.
 */

const TARGET_WORD = {
  self: "you", partner: "your partner", opp: "the opponent",
  opp_partner: "their partner", both_opps: "both opponents",
  all_others: "everyone else", all: "everyone",
};

function valueWord(n) {
  if (typeof n === "number") return String(n);
  if (!n) return "?";
  if (n.kind === "power") return "your Power";
  if (n.kind === "attacking_opponents_power") return "the blocked Power";
  if (n.kind === "spirits") return n.times > 1 ? `${n.times} per Spirit` : "1 per Spirit";
  return "?";
}

function opWords(op) {
  if (!op) return "";
  switch (op.op) {
    case "attack": {
      const who = op.target && op.target !== "opp" ? ` ${TARGET_WORD[op.target]}` : "";
      const by = op.by === "partner" ? " (partner)" : "";
      return `Attack${who}${by}`;
    }
    case "block": return "Block";
    case "damage": return `${valueWord(op.n)} damage to ${TARGET_WORD[op.target || "opp"]}`;
    case "heal": return `Heal ${valueWord(op.n)} — ${TARGET_WORD[op.target || "self"]}`;
    case "power": {
      const n = valueWord(op.n);
      const sign = typeof op.n === "number" && op.n < 0 ? "" : "+";
      return `${sign}${n} Power — ${TARGET_WORD[op.target || "self"]}`;
    }
    case "transfer_power": return `Move ${valueWord(op.n)} Power to ${TARGET_WORD[op.to]}`;
    case "cancel": return "Cancel their card";
    case "track": return `+${valueWord(op.n)} ${op.track.replace(/_/g, " ")}`;
    case "ignite": return "Set them Aflame";
    case "plant_scheme": return "Plant a Scheme";
    case "unleash_scheme": return "Unleash a Scheme";
    case "give_token": return `Pass the ${op.token} token`;
    case "take_token": return `Take the ${op.token} token`;
    case "flip_card": return "Turn this card over";
    case "spirit": return "+1 Spirit";
    case "if": return `If ${condWords(op.cond)}: ${op.then.map(opWords).join(", ")}`
      + (op.else ? ` — else ${op.else.map(opWords).join(", ")}` : "");
    case "fx": return FX_TEXT[op.name] || "Special";
    default: return op.op;
  }
}

function condWords(cond) {
  if (!cond) return "?";
  switch (cond.kind) {
    case "power_at_least": return `you have ${cond.n}+ Power`;
    case "hp_equals": return `you are on ${cond.n} HP`;
    case "no_opponent_attacked": return "neither opponent attacks";
    case "self_attacked": return "you are attacked";
    case "own_attack_blocked": return "your attack is blocked";
    case "opponent_played_starting_card": return "they played their Starting Card";
    case "serpent": return `the ${cond.face} serpent shows`;
    case "face": return cond.face === "bodvar" ? "still human" : "transformed";
    case "ships": return `${cond.min}–${cond.max} Ships`;
    case "has_token": return `you hold the ${cond.token}`;
    case "token_on": return `${TARGET_WORD[cond.who]} holds the ${cond.token}`;
    default: return cond.kind;
  }
}

function cardText(card) {
  if (!card) return "";
  const main = (card.ops || []).map(opWords).filter(Boolean);
  const bonus = [];
  for (const op of card.ops || []) {
    if (op.success) bonus.push(`Success: ${op.success.map(opWords).join(", ")}`);
  }
  return [...main, ...bonus].join(" · ");
}

/* ── Board pieces ───────────────────────────────────────────────────────
 * There is no licensed art in this repo, so a fighter's identity is drawn:
 * an emblem and an accent colour from art.jsx, applied as CSS custom
 * properties so the whole board tints from one place.
 */

function trackFor(state, board) {
  if (state.face === "berserker_bear" && board.back) return board.back.hp_track || [];
  if (board.characters) {
    const ch = board.characters.find((c) => c.id === state.character);
    return ch ? ch.hp_track : [];
  }
  return board.hp_track || [];
}

/* The biggest number on a fighter's health track. The Fey Folk have no track of
   their own -- they have three Characters -- so theirs is the best of the three,
   which is what "how much can this survive" means for them. */
/* A round's beats include ones that are not TURNS: the instant-bonus beat at
   setup, and anything the engine records before the first card is flipped. They
   carry no revealed cards. Counting them made the stage read "Turn 1 of 1"
   before a single card had been played, over two empty card slots. */
function isTurnBeat(beat) {
  return !!beat && (beat.insts || []).some((x) => x != null);
}

/* The things about a board that are true but not printed anywhere the player
   can see them mid-fight. Derived from the track rather than written out, so a
   corrected import fixes the modal too. */
function boardFacts(board) {
  if (!board) return [];
  const out = [];
  const tr = board.hp_track || [];
  const kos = tr.filter((sp) => sp.kind === "ko").length;
  const stops = tr.filter((sp) => (sp.icons || []).includes("stop")).length;
  const iconed = tr.filter((sp) => sp.kind === "hp" && (sp.icons || []).length).length;

  if (board.characters) {
    out.push(`Three Characters, one at a time — ${board.characters
      .map((c) => c.id).join(", ")}. Each has its own health track.`);
    out.push("Losing the last health on a Character turns them into a Spirit and the next one steps in.");
  }
  if (board.back) {
    out.push("Double-sided: this fighter transforms, and the other side has its own health track.");
  }
  if (kos > 1) out.push(`${kos} KO spaces, so there is further to fall than the number suggests.`);
  if (tr.some((sp) => sp.kind === "revive")) {
    out.push("A revive space BELOW the KO spaces — pushed past both, they come back.");
  }
  if (stops > 0) {
    out.push(stops >= tr.length - 2
      ? "A STOP on almost every space: the marker moves at most one space a turn, whatever the total."
      : `${stops} STOP space${stops === 1 ? "" : "s"} — the marker halts the moment it lands on one.`);
  }
  if (iconed > 0) {
    out.push(iconed === 1
      ? "1 space carries an icon that fires when the marker passes it."
      : `${iconed} spaces carry an icon that fires when the marker passes them.`);
  }
  const st = board.special_track;
  if (st && st.id) {
    const label = String(st.id).replace(/_/g, " ");
    const spaces = (st.spaces || []).length;
    out.push(spaces ? `Has a ${label} track of ${spaces} spaces.`
      : st.max != null ? `Has a ${label} track running ${st.min ?? 0} to ${st.max}.`
        : `Has a ${label} track.`);
  }
  for (const [t, n] of Object.entries(board.tokens || {})) {
    if (n) out.push(`Starts with ${n} ${String(t).replace(/_/g, " ")}.`);
  }
  return out;
}

function maxHpOf(board) {
  if (!board) return null;
  const tracks = board.characters ? board.characters.map((c) => c.hp_track)
    : [board.hp_track, board.back && board.back.hp_track].filter(Boolean);
  let best = 0;
  for (const tr of tracks) {
    for (const sp of tr || []) if (sp.kind === "hp" && sp.hp > best) best = sp.hp;
  }
  return best || null;
}

function spaceValue(track, idx) {
  if (!track || idx == null || !track[idx]) return 0;
  return track[idx].kind === "hp" ? track[idx].hp : 0;
}

/* The health track.
 *
 * This was a row of one box per space, which is how the board is printed — and
 * it did not survive contact with the roster. Health ranges from 3 (a Fey Folk
 * Character) to 25 (the Golem), so the same component drew four fat slabs on one
 * board and twenty-five hairlines on the next, side by side in the same panel,
 * and the two could not be compared at a glance. Worse, colouring each space by
 * what it does made a FULL health bar render as a red-amber-green ramp, which
 * reads as a damaged bar or a rendering fault.
 *
 * So: one bar, filled in proportion, one colour chosen by how much health is
 * left, and its LENGTH scaled to how tough this fighter is against the toughest
 * in the game — otherwise a 5 HP fighter and a 25 HP fighter both draw a full
 * bar and relative durability, the thing a 2v2 brawler is read on, is invisible.
 *
 * The special spaces (KO, Stop, revive, Spirit) were drawn on it as notches and
 * that was WRONG, four review rounds running: they are per-fighter, so one bar
 * came out striped while the three beside it were smooth, and every reader
 * called it a rendering bug rather than information. A bar with no legend cannot
 * carry them. The marker halting on a Stop already shows the player what a Stop
 * does, at the moment it matters.
 */
function HealthTrack({ track, at, scale }) {
  if (!track || track.length < 2 || at == null) return null;
  const top = track.length - 1;
  const pct = Math.max(0, Math.min(100, (at / top) * 100));
  const hpMax = Math.max(0, ...track.filter((sp) => sp.kind === "hp").map((sp) => sp.hp));
  const hpNow = spaceValue(track, at);
  const frac = hpMax ? hpNow / hpMax : 0;
  const tone = frac >= 0.6 ? "hi" : frac >= 0.3 ? "mid" : "lo";
  // How long this fighter's bar is against the toughest fighter in the game.
  // Without it a 5 HP fighter at full health and a 25 HP fighter at full health
  // drew the identical full bar, so relative durability -- the thing a 2v2
  // brawler is read on -- was invisible.
  const cap = Math.max(18, Math.min(100, (hpMax / (scale || hpMax || 1)) * 100));

  return (
    <div className="rt-track" role="img" aria-label={`${hpNow} of ${hpMax} health`}>
      <span className={`rt-track-cap rt-track-${tone}`} style={{ width: `${cap}%` }}>
        <span className="rt-track-fill" style={{ width: `${pct}%` }} />
      </span>
    </div>
  );
}

function FighterCard({ fid, state, board, active, fx, beatKey, scale, onInfo }) {
  const gesture = useCardInfoGesture(board ? onInfo : null);
  if (!state || !board) return <div className="rt-fighter rt-fighter-ghost" />;
  const sig = sigilOf(fid);
  const track = trackFor(state, board);
  const hpNow = spaceValue(track, state.hp);
  const hpMax = Math.max(0, ...track.filter((s) => s.kind === "hp").map((s) => s.hp));
  const here = track[state.hp];
  const ko = !!here && here.kind === "ko";
  const spirit = !!here && here.kind === "spirit";
  // The Fey Folk with all three Characters gone have NO track at all: they are
  // still in the fight, but they cannot lose or recover health. Without this
  // they rendered as "0 /0" with the bar element missing entirely, still wearing
  // the active glow, and with their Character tag silently replaced by the
  // board's first trait -- three separate lies about the same fighter.
  const spent = board.characters && !state.character;

  const chips = [];
  const tok = state.tokens || {};
  for (const [name, n] of Object.entries(tok)) {
    // `serpent` and `serpent_face` are ONE physical token and which way up it
    // is, not two things to hold. Rendering both read as "1 serpent" beside
    // "black serpent" on the same board.
    if (name === "serpent_face") continue;
    if (name === "serpent") {
      if (n > 0) {
        chips.push(
          <span className="rt-chip" key={name}>
            {tok.serpent_face ? "black" : "white"} serpent
          </span>);
      }
      continue;
    }
    if (n > 0) {
      chips.push(
        <span className={`rt-chip${name === "aflame" ? " rt-chip-fire" : ""}`} key={name}>
          {name === "aflame" && <Icon name="ignite" />}
          {name.replace(/_/g, " ")} <b>{n}</b>
        </span>);
    }
  }
  if (state.planted > 0) {
    chips.push(
      <span className="rt-chip" key="planted">
        <Icon name="plant_scheme" />planted <b>{state.planted}</b>
      </span>);
  }
  // Name then value, everywhere, and never a chip whose whole message is that
  // the player has none of something.
  for (const [name, n] of Object.entries(state.tracks || {})) {
    const shown = name === "divine_voice" ? (n === 0 ? "halo" : n) : n;
    if (shown === 0) continue;
    chips.push(
      <span className="rt-chip" key={`t-${name}`}>
        {name.replace(/_/g, " ")} <b>{shown}</b>
      </span>);
  }

  const cls = ["rt-fighter"];
  if (active && !ko && !spirit && !spent) cls.push("rt-active");
  if (ko || spirit || spent) cls.push("rt-ko");
  if (fx?.hp < 0) cls.push("rt-struck");
  if (fx?.hp > 0) cls.push("rt-mended");

  return (
    <div className={cls.join(" ")} style={{ "--f-ink": sig.ink, "--f-deep": sig.deep }}
      {...gesture} title={`${board.name} — hold or right-click for details`}>
      <div className="rt-fighter-glow" aria-hidden="true" />
      <div className="rt-fhd">
        <span className="rt-crest"><Sigil fid={fid} /></span>
        <span className="rt-fname-wrap">
          <span className="rt-fname">{board.name}</span>
          <span className="rt-ftags">
            {state.face === "berserker_bear"
              ? <span className="rt-tag rt-tag-hot">Bear</span>
              : spent
                ? <span className="rt-tag rt-tag-cold">all Spirits</span>
                : state.character
                  ? <span className="rt-tag rt-cap">{state.character}</span>
                  : (board.tags || []).slice(0, 1).map((t) => <span className="rt-tag" key={t}>{t}</span>)}
          </span>
        </span>
      </div>

      <div className="rt-stats">
        <span className="rt-stat rt-hp">
          <Icon name="hp" />
          <b>
            {ko ? "KO" : spirit || spent ? "—" : hpNow}
            {!ko && !spirit && !spent && <small className="rt-den">{`/${hpMax}`}</small>}
          </b>
        </span>
        <span className="rt-stat rt-pw">
          <Icon name="power" /><b>{state.power}</b><small>Power</small>
        </span>
      </div>

      {spent
        ? <div className="rt-track rt-track-gone" role="img" aria-label="no health track" />
        : <HealthTrack track={track} at={state.hp} scale={scale} />}
      {/* Reserved so a chip appearing mid-round does not shift the whole
          column below it. */}
      <div className="rt-chips">{chips}</div>

      {/* The number that floats off a fighter when they are hit. Keyed on the
          beat so stepping back and forward replays it instead of showing a
          stale one frozen at the end of its animation. */}
      {!!fx?.hp && (
        <span className={`rt-pop ${fx.hp < 0 ? "rt-pop-hit" : "rt-pop-heal"}`} key={`hp${beatKey}`}>
          {fx.hp < 0 ? "" : "+"}{fx.hp}
        </span>
      )}
      {!!fx?.power && (
        <span className="rt-pop rt-pop-pw" key={`pw${beatKey}`}>
          {fx.power > 0 ? "+" : ""}{fx.power} pw
        </span>
      )}
      {(ko || spirit || spent) && (
        <span className="rt-kostamp">{spent ? "Spent" : spirit ? "Spirit" : "KO"}</span>
      )}
    </div>
  );
}

function TeamSide({ label, mine, team, fighters, catalog, activeSlot, fxSlots, beatKey, scale, onInfo }) {
  return (
    <div className={`rt-side${mine ? " rt-mine" : ""}`}>
      <div className="rt-side-hd">
        <span className="rt-side-name">{label}</span>
        <span className="rt-side-tag">{mine ? "your team" : "their team"}</span>
      </div>
      <div className="rt-fighters">
        {(team || []).map((fid, slot) => (
          <FighterCard
            key={`${fid}-${slot}`}
            fid={fid}
            state={fighters?.[slot]}
            board={catalog?.fighters?.[fid]}
            active={activeSlot === slot}
            fx={fxSlots?.[slot]}
            beatKey={beatKey}
            scale={scale}
            onInfo={onInfo ? () => onInfo({ kind: "fighter", fid }) : null}
          />
        ))}
      </div>
    </div>
  );
}

/* A card as it sits in the ring.
 *
 * Rendered from the op list, so the picture and the words come from the same
 * source and cannot drift. The emblem gets a proper ART WINDOW at the top rather
 * than being blown up as a watermark behind the text: as a watermark it was
 * clipped by whichever card edge it happened to reach, sat under the body copy
 * greying it out mid-sentence, and landed differently on every card — three
 * separate reviewers read it as a broken background image.
 */
function PlayCard({ card, catalog, flipKey, side, onInfo }) {
  const gesture = useCardInfoGesture(card ? onInfo : null);
  const fid = card?.fighter;
  const sig = sigilOf(fid);
  const board = catalog?.fighters?.[fid];

  if (!card) {
    return (
      <div className={`rt-card rt-card-empty rt-card-${side}`}>
        <div className="rt-card-art rt-card-art-empty" />
        <div className="rt-card-body">
          <span className="rt-card-none">No card</span>
        </div>
      </div>
    );
  }

  const ops = card.ops || [];
  const bonuses = ops.filter((op) => op.success);
  return (
    <div className={`rt-card rt-card-${side}`} key={flipKey}
      style={{ "--f-ink": sig.ink, "--f-deep": sig.deep }}
      {...gesture} title={`${card.name} — hold or right-click for details`}>
      <div className="rt-card-art">
        <Sigil fid={fid} />
        {card.instant_bonus && <span className="rt-card-flag">instant bonus</span>}
      </div>
      <div className="rt-card-body">
        <div className="rt-card-hd">
          <span className="rt-card-name">{card.name}</span>
          <span className="rt-card-by">{board?.name || ""}</span>
        </div>
        <ul className="rt-card-ops">
          {ops.map((op, i2) => (
            <li key={i2}><Icon name={iconForOp(op)} /><span>{opWords(op)}</span></li>
          ))}
          {bonuses.map((op, i2) => (
            <li className="rt-card-bonus" key={`b${i2}`}>
              <Icon name="fx" /><span>Success: {op.success.map(opWords).join(", ")}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* A board's health track, drawn rather than described.
 *
 * The facts below it were sentences about a spatial thing — "1 STOP space, the
 * marker halts the moment it lands on one", "4 spaces carry an icon" — which is
 * the hardest possible way to say where they are. The strip is generated from
 * the same data, so it cannot disagree with the prose it replaces.
 */
function TrackStrip({ track }) {
  if (!track || track.length < 2) return null;
  return (
    <div className="rt-strip" role="img" aria-label={`${track.length} spaces`}>
      {track.map((sp, i) => {
        const stop = (sp.icons || []).includes("stop");
        const cls = ["rt-cell"];
        if (sp.kind !== "hp") cls.push(`rt-cell-${sp.kind}`);
        else if (stop) cls.push("rt-cell-stop");
        else if ((sp.icons || []).length) cls.push("rt-cell-icon");
        return (
          <i key={i} className={cls.join(" ")}
            title={sp.kind !== "hp" ? sp.kind : stop ? "stop" : (sp.icons || []).length ? "icon" : String(sp.hp)} />
        );
      })}
    </div>
  );
}

function InfoTarget({ as: Tag = "div", onInfo, children, ...rest }) {
  const gesture = useCardInfoGesture(onInfo);
  return <Tag {...rest} {...gesture}>{children}</Tag>;
}

/* A fighter or a card, in full.
 *
 * Reached by right-click or press-and-hold on anything that represents one —
 * the same gesture everywhere, so it means one thing. This is where the rules
 * text lives that will not fit on a face: a fighter's board oddities, and the
 * per-card FAQ notes from the data, which settle exactly the interactions a
 * player stops and wonders about mid-fight.
 */
function InfoModal({ info, catalog, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const isCard = info.kind === "card";
  const card = isCard ? info.card : null;
  const fid = isCard ? card?.fighter : info.fid;
  const board = catalog?.fighters?.[fid];
  const sig = sigilOf(fid);
  if (isCard && !card) return null;
  if (!isCard && !board) return null;

  const deck = [];
  if (!isCard) {
    for (const [cid, c] of Object.entries(catalog?.cards || {})) {
      if (c.fighter === fid) deck.push({ cid, ...c });
    }
    deck.sort((a, b) => (b.starting ? 1 : 0) - (a.starting ? 1 : 0)
      || a.name.localeCompare(b.name));
  }

  const facts = isCard ? [] : boardFacts(board);
  const ops = isCard ? (card.ops || []) : [];
  const backOps = isCard && card.two_faced ? (card.ops_back || []) : [];

  return (
    <div className="rt-backdrop" onClick={onClose} role="presentation">
      <div className="rt-modal" style={{ "--f-ink": sig.ink, "--f-deep": sig.deep }}
        role="dialog" aria-modal="true" aria-label={isCard ? card.name : board.name}
        onClick={(e) => e.stopPropagation()}>
        <div className="rt-modal-art">
          <span className="rt-modal-medal"><Sigil fid={fid} /></span>
        </div>
        <div className="rt-modal-body">
          <h2>{isCard ? card.name : board.name}</h2>
          {/* Two tiers, not one dot-run: what KIND of thing this is, then the
              numbers, in the same chip vocabulary the board uses — those are
              what the modal was opened to check. */}
          <p className="rt-modal-tags">
            {isCard
              ? [board?.name, card.starting ? "Starting Card" : null,
                card.instant_bonus ? "instant bonus" : null].filter(Boolean).join(" · ")
              : (board.tags || []).join(" · ")}
          </p>
          <p className="rt-modal-stats">
            {isCard ? (
              <span className="rt-chip">
                {card.copies > 1 ? `${card.copies} copies` : "1 copy"} in the deck
              </span>
            ) : (
              <>
                <span className="rt-stat rt-hp">
                  <Icon name="hp" /><b>{maxHpOf(board) ?? "?"}</b><small>health</small>
                </span>
                <span className="rt-stat rt-pw">
                  <Icon name="power" /><b>{board.base_power}</b><small>Power</small>
                </span>
              </>
            )}
          </p>

          {isCard && (
            <ul className="rt-modal-ops">
              {ops.map((op, i) => (
                <li key={i}><Icon name={iconForOp(op)} /><span>{opWords(op)}</span></li>
              ))}
              {ops.filter((op) => op.success).map((op, i) => (
                <li className="rt-card-bonus" key={`s${i}`}>
                  <Icon name="fx" /><span>Success: {op.success.map(opWords).join(", ")}</span>
                </li>
              ))}
              {backOps.length > 0 && (
                <li className="rt-modal-sep"><Icon name="flip_card" /><span>Turned over:</span></li>
              )}
              {backOps.map((op, i) => (
                <li key={`b${i}`}><Icon name={iconForOp(op)} /><span>{opWords(op)}</span></li>
              ))}
            </ul>
          )}

          {isCard && card.note && <p className="rt-modal-note">{card.note}</p>}

          {isCard && (() => {
            // The non-obvious half of each mechanic this card uses. Without it a
            // one-op card's modal repeated its own face and taught nothing.
            const seen = [];
            const walk = (list) => {
              for (const op of list || []) {
                if (op.op && OP_GLOSSARY[op.op] && !seen.includes(op.op)) seen.push(op.op);
                walk(op.then); walk(op.else); walk(op.success);
              }
            };
            walk(ops); walk(backOps);
            if (!seen.length) return null;
            return (
              <>
                <h3 className="rt-modal-h3">How it works</h3>
                <ul className="rt-modal-facts">
                  {seen.map((k) => <li key={k}>{OP_GLOSSARY[k]}</li>)}
                </ul>
              </>
            );
          })()}

          {!isCard && (
            <>
              <h3 className="rt-modal-h3">Board</h3>
              {board.characters
                ? board.characters.map((c) => (
                  <div className="rt-modal-track" key={c.id}>
                    <span className="rt-modal-track-name rt-cap">{c.id}</span>
                    <TrackStrip track={c.hp_track} />
                  </div>))
                : <div className="rt-modal-track"><TrackStrip track={board.hp_track} /></div>}
              {board.back?.hp_track && (
                <div className="rt-modal-track">
                  <span className="rt-modal-track-name">transformed</span>
                  <TrackStrip track={board.back.hp_track} />
                </div>
              )}
              <p className="rt-modal-key">
                <span className="rt-cell rt-cell-ko" /> KO
                <span className="rt-cell rt-cell-stop" /> stop
                <span className="rt-cell rt-cell-icon" /> icon
                <span className="rt-cell rt-cell-revive" /> revive
              </p>
              {facts.length > 0 && (
                <ul className="rt-modal-facts">
                  {facts.map((f, i) => <li key={i}>{f}</li>)}
                </ul>
              )}
            </>
          )}

          {!isCard && deck.length > 0 && (
            <>
              <h3 className="rt-modal-h3">
                Deck — {deck.reduce((n, c) => n + (c.copies || 1), 0)} cards
                {deck.length !== deck.reduce((n, c) => n + (c.copies || 1), 0)
                  && <span className="rt-modal-h3-sub">{deck.length} different</span>}
              </h3>
              <div className="rt-modal-deck">
                {deck.map((c) => (
                  <span className={`rt-modal-chip${c.starting ? " rt-modal-chip-start" : ""}`} key={c.cid}>
                    {c.name}{c.copies > 1 ? ` ×${c.copies}` : ""}
                    {c.starting && <em className="rt-modal-start">start</em>}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
        <button type="button" className="rt-modal-close" onClick={onClose} aria-label="Close">×</button>
      </div>
    </div>
  );
}

/* ── The component ───────────────────────────────────────────────────────── */

export default function RagTag({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");
  const [connecting, setConnecting] = useState(false);
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [toast, setToast] = useState("");
  const [openGames, setOpenGames] = useState(() => readLobbyCache("ragtag", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("ragtag", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("ragtag", myId, "history", []));
  const [loadingGames, setLoadingGames] = useState(false);
  const [lobbyTab, setLobbyTab] = useState("open");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [createOpp, setCreateOpp] = useState("ai");

  // Local build-step selection, before it is submitted.
  const [buildPick, setBuildPick] = useState(null);
  const [buildPos, setBuildPos] = useState(null);
  // Playback cursor through this round's beats, advanced by hand.
  const [beatIdx, setBeatIdx] = useState(0);
  // Rounds already fought, kept so the log is the whole fight and not just now.
  const [pastRounds, setPastRounds] = useState([]);
  // The fighter or card being read in full (press-and-hold / right-click).
  const [info, setInfo] = useState(null);

  const [historyShown, historyMore] = useProgressiveList(history);
  const urlAttemptRef = useRef(null);

  const game = roomData?.game;
  const names = roomData?.players || {};
  const mySeat = game?.seats?.indexOf(myId) ?? -1;
  const theirSeat = mySeat >= 0 ? 1 - mySeat : -1;
  const over = !!game && game.winner !== null && game.winner !== undefined;

  /* ── socket ── */
  const handleMessage = useCallback((msg) => {
    setConnecting(false);
    if (msg.type === "error") {
      const ua = urlAttemptRef.current;
      if (ua) {
        urlAttemptRef.current = null;
        try {
          if (localStorage.getItem("ragtag_roomId") === ua.rid) localStorage.removeItem("ragtag_roomId");
          localStorage.removeItem(`ragtag_token_${ua.rid}_${myId}`);
        } catch {}
        setRoomId(""); setRoomData(null); setScreen("lobby");
        replacePath(buildPath("ragtag"));
      }
      setToast(msg.message || "error");
      return;
    }
    const room = msg.room;
    if (!room) return;
    const rid = room.room_id || roomId;
    const tok = room.reconnect_tokens?.[myId];
    if (tok) {
      try {
        localStorage.setItem(`ragtag_token_${rid}_${myId}`, tok);
        localStorage.setItem("ragtag_roomId", rid);
      } catch {}
    }
    setRoomData(room);
    const inGame = room.status === "playing" || room.status === "over";
    if (msg.type === "created" || msg.type === "joined") {
      if (rid) pushPath(buildPath("ragtag", rid));
      urlAttemptRef.current = null;
      setRoomId(rid);
      setScreen(inGame ? "game" : "waiting");
    } else if (inGame && screen !== "game") {
      setScreen("game");
    }
  }, [myId, roomId, screen]);

  const { connected, connect, send, disconnect } = useSocket(handleMessage);

  /* Static card + board tables, once. Cached so a reconnect renders instantly. */
  useEffect(() => {
    try {
      const cached = localStorage.getItem("ragtag_catalog");
      if (cached) setCatalog(JSON.parse(cached));
    } catch {}
    fetch(`${RT_HTTP}/catalog`).then((r) => r.json()).then((d) => {
      if (d.roster) {
        setCatalog(d);
        try { localStorage.setItem("ragtag_catalog", JSON.stringify(d)); } catch {}
      }
    }).catch(() => {});
  }, []);

  const fetchGames = useCallback(() => {
    setLoadingGames(true);
    fetch(`${RT_HTTP}/games`).then((r) => r.json()).then((d) => {
      const g = d.games || []; setOpenGames(g); writeLobbyCache("ragtag", myId, "open", g);
    }).catch(() => {}).finally(() => setLoadingGames(false));
    if (authUser?.session_token) {
      const headers = { Authorization: `Bearer ${authUser.session_token}` };
      fetch(`${RT_HTTP}/games/mine`, { headers }).then((r) => r.json()).then((d) => {
        const g = d.games || []; setMyGames(g); writeLobbyCache("ragtag", myId, "mine", g);
      }).catch(() => {});
      fetch(`${RT_HTTP}/games/history`, { headers }).then((r) => r.json()).then((d) => {
        const g = d.games || []; setHistory(g); writeLobbyCache("ragtag", myId, "history", g);
      }).catch(() => {});
    } else {
      setMyGames([]); setHistory([]);
      writeLobbyCache("ragtag", myId, "mine", []);
      writeLobbyCache("ragtag", myId, "history", []);
    }
  }, [authUser, myId]);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);
  useEffect(() => () => disconnect(), []); // eslint-disable-line
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(""), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  const newRoomId = () => Math.random().toString(36).slice(2, 7).toUpperCase();

  const createGame = useCallback((vsAi) => {
    const rid = newRoomId();
    setConnecting(true); setRoomId(rid); setShowCreateModal(false);
    connect(`${RT_WS}/${rid}/${myId}`, {
      action: "create", name: authUser?.name || "Player", vs_ai: vsAi,
    });
  }, [connect, myId, authUser]);

  const joinGame = useCallback((rid) => {
    if (!rid) return;
    const code = String(rid).trim().toUpperCase();
    setConnecting(true); setRoomId(code);
    connect(`${RT_WS}/${code}/${myId}`, {
      action: "join", name: authUser?.name || "Player",
      session_token: authUser?.session_token || null,
    });
  }, [connect, myId, authUser]);

  const resumeGame = useCallback((rid) => {
    let tok = null;
    try { tok = localStorage.getItem(`ragtag_token_${rid}_${myId}`); } catch {}
    setConnecting(true); setRoomId(rid);
    connect(`${RT_WS}/${rid}/${myId}`, tok
      ? { action: "reconnect", token: tok }
      : { action: "join", name: authUser?.name || "Player",
          session_token: authUser?.session_token || null });
  }, [connect, myId, authUser]);

  const cancelGame = useCallback((gid) => {
    if (!authUser?.session_token) return;
    fetch(`${RT_HTTP}/games/${gid}`, {
      method: "DELETE", headers: { Authorization: `Bearer ${authUser.session_token}` },
    }).then(() => fetchGames()).catch(() => {});
  }, [authUser, fetchGames]);

  const leaveToLobby = useCallback(() => {
    disconnect(); setRoomId(""); setRoomData(null); setScreen("lobby");
    replacePath(buildPath("ragtag"));
  }, [disconnect]);

  /* ── URL deep entry + Back/Forward ── */
  useEffect(() => {
    const path = window.location.pathname;
    const m = /\/ragtag\/([A-Za-z0-9_-]{1,24})\/?$/.exec(path);
    if (m) { urlAttemptRef.current = { rid: m[1].toUpperCase() }; resumeGame(m[1].toUpperCase()); }
  }, []); // eslint-disable-line

  useEffect(() => subscribe((r) => {
    if (r.game !== "ragtag") return;
    if (r.room) { urlAttemptRef.current = { rid: r.room }; resumeGame(r.room); }
    else { disconnect(); setRoomId(""); setRoomData(null); setScreen("lobby"); }
  }), [resumeGame, disconnect]);

  /* ── Beat playback ──
   * `beats` is replaced wholesale each round, so the cursor resets when the
   * round does. Nothing here drives the SERVER: the fight is already resolved
   * and saved by the time the first card is shown, so stepping through it is
   * pure replay and a reconnect mid-round simply starts the replay again.
   *
   * The prompt for the next decision is held back until the last turn is on
   * screen. Otherwise the round's outcome arrives as a question before the
   * player has seen what happened, which is the exact thing being fixed.
   */
  const beats = game?.beats || [];
  const teams = game?.teams || [[], []];
  const cards = catalog?.cards || {};
  const instances = game?.instances || [];
  const cardOf = useCallback(
    (inst) => (inst == null ? null : cards[String(instances[inst]?.cid)] || null),
    [cards, instances]);

  useEffect(() => { setBeatIdx(0); }, [game?.round]);
  useEffect(() => { setPastRounds([]); setBeatIdx(0); }, [roomId]);

  /* The cursor walks the TURNS, not the beats. A round's beats also include
     setup and instant-bonus entries with no revealed cards, and stepping onto
     one showed the stage as "No card VS No card" -- an empty duel that the
     player had to click past before the fight started. Those events are not
     lost: they go straight into the log, which walks the full beat list. */
  const turnBeats = useMemo(() => beats.filter(isTurnBeat), [beats]);
  const lastIdx = Math.max(0, turnBeats.length - 1);
  const shownBeat = turnBeats.length ? turnBeats[Math.min(beatIdx, lastIdx)] : null;
  const atEnd = turnBeats.length === 0 || beatIdx >= lastIdx;

  /* Where turn `n` sits in the full beat list, so the log can include whatever
     preceded it. */
  const beatPosOf = useCallback((n) => {
    let seen = -1;
    for (let k = 0; k < beats.length; k++) {
      if (isTurnBeat(beats[k]) && ++seen === n) return k;
    }
    return beats.length - 1;
  }, [beats]);

  /* Everything narration cannot work out for itself. The track comes from the
     BEAT's own snapshot when it has one, because it CHANGES within a round:
     Bödvar flips onto a second board and a Fey Folk Character brings their own,
     so reading an early turn's indices off the round's final track reports the
     wrong numbers. Falling back to live state covers beats saved before the
     snapshot existed. */
  const narrCtx = useMemo(() => ({
    name: (seat, slot) => catalog?.fighters?.[teams?.[seat]?.[slot]]?.name || "",
    track: (seat, slot, beat) => {
      const st = beat?.state?.[seat]?.[slot] || game?.fighters?.[seat]?.[slot];
      const bd = catalog?.fighters?.[teams?.[seat]?.[slot]];
      return st && bd ? trackFor(st, bd) : [];
    },
    mine: (seat) => seat === mySeat,
    cardName: (inst) => cardOf(inst)?.name || null,
  }), [catalog, teams, game?.fighters, mySeat, cardOf]);

  const beatLines = useMemo(() => narrateBeat(shownBeat, narrCtx), [shownBeat, narrCtx]);

  /* THE FIGHTER BOARDS STEP WITH THE CURSOR. A round is resolved server-side in one
     go, so `game.fighters` is the state after the LAST turn of it: reading the boards
     off that made every health bar, Power total and token jump to its end-of-round
     value the moment the round landed, while the cards and the log walked through it
     turn by turn. Each beat now carries the state as it stood when that turn finished.
     Outside a fight -- draft, build, a reconnect before the first beat -- there is no
     beat to read, and the live state is the right answer. */
  const boardState = shownBeat?.state || game?.fighters;

  /* The log runs UP TO AND INCLUDING the turn on the stage. It used to stop one
     short, to avoid printing the same sentences in the ribbon and the log at
     once -- but "the log is always one turn behind" is how that reads while you
     are playing, and a log that omits what is on screen is not a record of the
     fight. The duplication is handled by marking the live turn instead (`live`
     below), so the log says "you are here" rather than repeating itself. */
  const livePos = useMemo(
    () => (over && atEnd ? beats.length - 1 : beatPosOf(beatIdx)),
    [over, atEnd, beats.length, beatPosOf, beatIdx]);
  const roundRows = useMemo(
    () => narrateRound(beats, livePos, narrCtx, beatPosOf(beatIdx)),
    [beats, livePos, beatPosOf, beatIdx, narrCtx]);
  const fullRows = useMemo(() => narrateRound(beats, beats.length - 1, narrCtx), [beats, narrCtx]);

  /* Finished rounds are kept as their NARRATED rows rather than as beats: the
     text depends on board state that has since moved on, so re-narrating an old
     round later would quietly retell it wrong. */
  const carryRef = useRef({ round: null, rows: [] });
  useEffect(() => {
    const prev = carryRef.current;
    if (prev.round != null && prev.round !== game?.round && prev.rows.length) {
      setPastRounds((old) => [...old, { round: prev.round, rows: prev.rows }]);
    }
    carryRef.current = { round: game?.round, rows: [] };
  }, [game?.round]);
  useEffect(() => {
    if (carryRef.current.round === game?.round) carryRef.current.rows = fullRows;
  }, [fullRows, game?.round]);

  /* Which card each fighter opens with. "Who leads?" turns on exactly this and
     used to render "leads the round" under BOTH options -- a template string
     with the variable left out. */
  /* The toughest fighter in the game, so every health bar can be drawn to the
     same scale. Derived from the catalog rather than hardcoded so the next
     expansion's fighters rescale the bars instead of overflowing them. */
  const hpScale = useMemo(() => Math.max(1, ...Object.values(catalog?.fighters || {})
    .map(maxHpOf).filter(Boolean)), [catalog]);

  const startingCards = useMemo(() => {
    const out = {};
    for (const c of Object.values(catalog?.cards || {})) {
      if (c.starting && !out[c.fighter]) out[c.fighter] = c;
    }
    return out;
  }, [catalog]);

  const logRef = useRef(null);
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [roundRows.length, pastRounds.length]);

  /* What each fighter should show for THIS beat: the number that floats off
     them, and whether the board shakes. Summed per fighter, because two
     sources hitting one marker is one movement. */
  const fxSlots = useMemo(() => {
    const out = { 0: {}, 1: {} };
    for (const ev of shownBeat?.events || []) {
      const bucket = out[ev.seat];
      if (!bucket || ev.slot == null) continue;
      const cur = bucket[ev.slot] || {};
      if (ev.kind === "hp") {
        const st = shownBeat?.state?.[ev.seat]?.[ev.slot]
          || game?.fighters?.[ev.seat]?.[ev.slot];
        const bd = catalog?.fighters?.[teams?.[ev.seat]?.[ev.slot]];
        const tr = st && bd ? trackFor(st, bd) : [];
        const a = tr[ev.from], b = tr[ev.to];
        const d = a && b && a.kind === "hp" && b.kind === "hp"
          ? b.hp - a.hp : ev.to - ev.from;
        bucket[ev.slot] = { ...cur, hp: (cur.hp || 0) + d };
      } else if (ev.kind === "power") {
        bucket[ev.slot] = { ...cur, power: (cur.power || 0) + (ev.to - ev.from) };
      }
    }
    return out;
  }, [shownBeat, catalog, teams, game?.fighters]);

  /* What the round actually cost, totalled across every turn in it. The fight
     used to just stop -- the only sign it had ended was a button going grey. */
  const roundTally = useMemo(() => {
    const byWho = new Map();
    for (const beat of beats) {
      for (const ev of beat.events || []) {
        if (ev.kind !== "hp" || ev.slot == null) continue;
        const bd = catalog?.fighters?.[teams?.[ev.seat]?.[ev.slot]];
        const st = game?.fighters?.[ev.seat]?.[ev.slot];
        const tr = st && bd ? trackFor(st, bd) : [];
        const a = tr[ev.from], b = tr[ev.to];
        const d = a && b && a.kind === "hp" && b.kind === "hp"
          ? b.hp - a.hp : ev.to - ev.from;
        const key = `${ev.seat}-${ev.slot}`;
        byWho.set(key, (byWho.get(key) || 0) + d);
      }
    }
    return [...byWho.entries()]
      .filter(([, n]) => n !== 0)
      .map(([key, n]) => {
        const [seat, slot] = key.split("-").map(Number);
        return { key, n, dir: n < 0 ? "down" : "up", name: narrCtx.name(seat, slot) };
      });
  }, [beats, catalog, teams, game?.fighters, narrCtx]);

  /* ── Moves ── */
  const sendMove = useCallback((move) => send({ action: "move", move }), [send]);

  // WHAT DO I OWE? The server answers this (`you_owe`), because a simultaneous
  // game has no "your turn" to read off the phase and a client that re-derives it
  // shows the wrong prompt the moment the two disagree.
  const owes = useMemo(() => {
    if (!game || over || mySeat < 0 || !game.you_owe) return null;
    if (!atEnd) return null;           // let them finish watching the fight
    if (game.pending_is_yours) return "pending";
    return game.phase;                 // draft | order | build
  }, [game, over, mySeat, atEnd]);

  useEffect(() => { setBuildPick(null); setBuildPos(null); }, [game?.round, game?.phase]);

  /* ── Screens ── */
  if (connecting && screen === "lobby") {
    return (
      <div className="app ragtag">
        <style>{ragtagStyles}</style>
        <LobbyLoading label="Connecting…" />
      </div>
    );
  }

  if (screen === "lobby") {
    const activeMine = notWaiting(myGames);
    return (
      <div className="app ragtag">
        <style>{ragtagStyles}</style>
        <LobbyHeader
          onBack={onExit}
          title="Rag Tag"
          user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : null}
        />
        <LobbyCreateRow
          onCreate={() => setShowCreateModal(true)}
          onJoin={(code) => joinGame(code)}
          onRefresh={fetchGames}
          onRules={() => setShowRules(true)}
          refreshing={loadingGames} />

        {showCreateModal && (
          <CreateModal title="New Fight" onClose={() => setShowCreateModal(false)}>
            <CmRow label="Opponent">
              <CmSeg value={createOpp} onChange={setCreateOpp} options={[
                { value: "friend", label: "VS Friend", title: "One friend joins from the lobby or your room code" },
                { value: "ai", label: "VS Bot", title: "Starts instantly against the bot" },
              ]} />
            </CmRow>
            <span className="cm-hint">
              Two fighters each, drafted. Both players reveal at the same time, and the
              deck is never shuffled.
            </span>
            <div className="cm-footer">
              <span className="cm-summary">
                Creating: <b>{createOpp === "ai" ? "vs Bot" : "vs Friend"}</b>
              </span>
              <button type="button" className="cm-create" onClick={() => createGame(createOpp === "ai")}>
                Create Game
              </button>
            </div>
          </CreateModal>
        )}

        <LobbyTabs value={lobbyTab} onChange={setLobbyTab} tabs={[
          { key: "open", label: "Open", count: openGames.length || null },
          { key: "active", label: "Active", count: activeMine.length || null },
          { key: "history", label: "History", count: history.length || null },
        ]} />

        <div className={`rt-lobby-cols lby-cols tab-${lobbyTab}`}>
          <div className="lby-col-open">
            <LobbySectionHd title="Open Games" />
            {openGames.length === 0 && <LobbyEmpty>No open games. Create one!</LobbyEmpty>}
            <div className="lby-list">
              {openGames.map((g) => (
                <div className="lby-card" key={g.id}>
                  <div className="lby-card-info">
                    <div className="lby-card-title">{g.host_name || "Player"}'s fight</div>
                    <div className="lby-card-meta">{g.id} · {timeAgo(g.created_at)}</div>
                  </div>
                  <div className="lby-card-actions">
                    {g.host_id === myId ? (
                      <>
                        <LobbyAction onClick={() => resumeGame(g.id)}>Return</LobbyAction>
                        <LobbyAction kind="secondary" onClick={() => cancelGame(g.id)}>Cancel</LobbyAction>
                      </>
                    ) : <LobbyAction onClick={() => joinGame(g.id)}>Join</LobbyAction>}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="lby-col-active">
            <LobbySectionHd title="Active Games" />
            {activeMine.length === 0 && <LobbyEmpty>No fights in progress.</LobbyEmpty>}
            <div className="lby-list">
              {activeMine.map((g) => (
                <div className="lby-card" key={g.id}>
                  <div className="lby-card-info">
                    <div className="lby-card-title">{g.player1_name || "?"} vs {g.player2_name || "?"}</div>
                    <div className="lby-card-meta">
                      {g.round ? `round ${g.round} · ` : ""}{timeAgo(g.updated_at)}
                    </div>
                  </div>
                  <div className="lby-card-actions">
                    {g.your_turn ? <TurnBadge mine>You're up</TurnBadge> : <TurnBadge>Waiting</TurnBadge>}
                    <LobbyAction onClick={() => resumeGame(g.id)}>Resume</LobbyAction>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="lby-col-history">
            <LobbySectionHd title="History" />
            {history.length === 0 && (
              <LobbyEmpty>{authUser ? "No finished fights yet." : "Log in to keep game history."}</LobbyEmpty>
            )}
            <div className="lby-list">
              {historyShown.map((g) => (
                <div className="lby-card lby-card-hist" key={g.id}>
                  <div className="lby-card-info">
                    <div className="lby-card-title">
                      <span className={`hist-result ${g.outcome === "won" ? "won" : "lost"}`}>
                        {g.outcome === "won" ? "Won" : g.outcome === "draw" ? "Draw" : "Lost"}
                      </span>
                      <span className="hist-scores"> vs {g.you_are_p1 ? g.player2_name : g.player1_name}</span>
                    </div>
                    <div className="lby-card-meta">
                      {(g.your_team || []).map((f) => catalog?.fighters?.[f]?.name || f).join(" + ")}
                      {" · "}{timeAgo(g.updated_at)}
                    </div>
                  </div>
                </div>
              ))}
              {historyMore}
            </div>
          </div>
        </div>
        {toast && <div className="rt-toast">{toast}</div>}
        {showRules && (
          <RulesModal title="How to play — Rag Tag" onClose={() => setShowRules(false)}>
            <RagTagRules />
          </RulesModal>
        )}
      </div>
    );
  }

  if (screen === "waiting") {
    const isHost = roomData?.host === myId;
    return (
      <div className="app ragtag">
        <style>{ragtagStyles}</style>
        <div className="rt-wrap rt-waiting">
          <h1>Rag Tag</h1>
          <p>Room code</p>
          <div className="rt-code">{roomId}</div>
          <p style={{ marginTop: "1rem" }}>
            {Object.keys(names).length < 2 ? "Waiting for an opponent…" : "Ready."}
          </p>
          {isHost && Object.keys(names).length >= 2 && (
            <button className="rt-go" onClick={() => send({ action: "start" })}>Start the fight</button>
          )}
          <div style={{ marginTop: "1.2rem" }}>
            <LobbyAction kind="secondary" onClick={leaveToLobby}>Back to lobby</LobbyAction>
          </div>
        </div>
        {toast && <div className="rt-toast">{toast}</div>}
      </div>
    );
  }

  /* ── The board ── */
  const myTeam = mySeat >= 0 ? teams[mySeat] : [];
  const theirTeam = theirSeat >= 0 ? teams[theirSeat] : [];
  // Nothing empty is rendered before the bell: the draft used to sit under two
  // hollow team headers and a 200px box reading "The bell has not rung yet.",
  // which pushed the only decision on the screen most of a phone-height down.
  const fightOn = turnBeats.length > 0;
  const teamsKnown = (teams?.[0]?.length || 0) > 0 && (teams?.[1]?.length || 0) > 0;

  /* The instant-bonus beat is a real beat but NOT a turn -- it carries turn -1
     and no cards. Counting it made a two-turn round read "Turn 3 of 3". */
  const realTurns = turnBeats.length;

  const turnLabel = realTurns
    ? `Turn ${Math.min(beatIdx, lastIdx) + 1} of ${realTurns}` : "—";

  /* `row.live` is the turn currently on the stage. The log includes it rather than
     stopping one short, and marks it so the reader can see which entry the cards above
     them belong to. */
  const logRow = (row) => (row.kind === "turn"
    ? (
      <div className={`rt-log-turn${row.live ? " rt-log-now" : ""}`} key={row.key}>
        <span className="rt-log-turn-n">{row.turn == null ? "Setup" : `Turn ${row.turn}`}</span>
        {row.cards.filter(Boolean).length > 0 && (
          <span className="rt-log-turn-cards">{row.cards.filter(Boolean).join(" · ")}</span>
        )}
        {row.live && <span className="rt-log-here">on screen</span>}
      </div>
    ) : (
      <div className={`rt-log-line rt-tone-${row.tone}${row.live ? " rt-log-now" : ""}`}
        key={row.key}>
        <Icon name={row.icon} /><span>{row.text}</span>
      </div>
    ));

  return (
    <div className="app ragtag">
      <style>{ragtagStyles}</style>
      <LobbyHeader
        title="Rag Tag"
        menu={<GameMenu items={[
          { label: "Return to lobby", onClick: leaveToLobby },
          { label: "How to play (rules)", onClick: () => setShowRules(true) },
          {
            label: "Abandon fight", danger: true,
            onClick: () => { if (!over) send({ action: "abandon" }); },
          },
        ]} />}
      />
      <div className="rt-wrap">
        {!connected && <div className="rt-waitline rt-warn">Reconnecting…</div>}

        <div className={`rt-layout${fightOn || pastRounds.length > 0 ? "" : " rt-layout-solo"}`}>
          <div className="rt-main">
            {teamsKnown && <TeamSide
              label={names[game?.seats?.[theirSeat]] || "Opponent"}
              team={theirTeam}
              fighters={boardState?.[theirSeat]}
              catalog={catalog}
              activeSlot={shownBeat?.active?.[theirSeat]}
              fxSlots={fxSlots[theirSeat]}
              beatKey={`${game?.round}-${beatIdx}`}
              scale={hpScale}
              onInfo={setInfo}
            />}

            {fightOn ? (
              <section className="rt-stage">
                <header className="rt-stage-hd">
                  <span className="rt-round">
                    Round <b>{game?.round}</b>
                    <span className="rt-round-sep">·</span>
                    <span className="rt-turnno">{turnLabel}</span>
                  </span>
                  <span className="rt-steps" role="tablist" aria-label="turns this round">
                    {turnBeats.map((b, i2) => (
                      <button
                        key={i2}
                        type="button"
                        role="tab"
                        aria-selected={i2 === beatIdx}
                        aria-label={`Turn ${i2 + 1}`}
                        title={`Turn ${i2 + 1}`}
                        className={`rt-step${i2 === beatIdx ? " rt-step-on" : ""}${i2 < beatIdx ? " rt-step-done" : ""}`}
                        onClick={() => setBeatIdx(i2)} />
                    ))}
                  </span>
                </header>

                <div className="rt-duel">
                  <PlayCard side="them" catalog={catalog}
                    card={cardOf(shownBeat?.insts?.[theirSeat])}
                    onInfo={() => setInfo({ kind: "card", card: cardOf(shownBeat?.insts?.[theirSeat]) })}
                    flipKey={`t-${game?.round}-${beatIdx}`} />
                  <div className="rt-clash" key={`c-${game?.round}-${beatIdx}`} aria-hidden="true">
                    <span className="rt-clash-burst" />
                    <span className="rt-clash-word">VS</span>
                  </div>
                  <PlayCard side="mine" catalog={catalog}
                    card={cardOf(shownBeat?.insts?.[mySeat])}
                    onInfo={() => setInfo({ kind: "card", card: cardOf(shownBeat?.insts?.[mySeat]) })}
                    flipKey={`m-${game?.round}-${beatIdx}`} />
                </div>

                <div className="rt-ribbon" key={`rb-${game?.round}-${beatIdx}`}>
                  {beatLines.length ? beatLines.map((l, n) => (
                    <span className={`rt-rib rt-tone-${l.tone}`} key={l.key}
                      style={{ "--d": `${Math.min(n, 8) * 60}ms` }}>
                      <Icon name={l.icon} />{l.text}
                    </span>
                  )) : <span className="rt-rib rt-tone-info"><Icon name="dot" />Nothing lands.</span>}
                </div>

                {atEnd && realTurns > 0 && (
                  <div className="rt-resolved">
                    <span className="rt-resolved-hd">Round {game?.round} resolved</span>
                    {roundTally.length > 0
                      ? roundTally.map((t) => (
                        <span key={t.key} className={`rt-tally rt-tally-${t.dir}`}>
                          {t.name} {t.dir === "down" ? "−" : "+"}{Math.abs(t.n)}
                        </span>))
                      : <span className="rt-tally">no health changed hands</span>}
                  </div>
                )}

                <div className="rt-controls">
                  <button type="button" className="rt-ctl" disabled={beatIdx <= 0}
                    onClick={() => setBeatIdx((n) => Math.max(0, n - 1))}>
                    <Icon name="prev" />Back
                  </button>
                  {!atEnd && (
                    <>
                      <button type="button" className="rt-ctl rt-ctl-go"
                        onClick={() => setBeatIdx((n) => Math.min(lastIdx, n + 1))}>
                        Next turn<Icon name="next" />
                      </button>
                      <button type="button" className="rt-ctl"
                        onClick={() => setBeatIdx(lastIdx)}>
                        To the end<Icon name="skip" />
                      </button>
                    </>
                  )}
                </div>
              </section>
            ) : null}

            {teamsKnown && <TeamSide
              label={names[myId] || "You"} mine
              team={myTeam}
              fighters={boardState?.[mySeat]}
              catalog={catalog}
              activeSlot={shownBeat?.active?.[mySeat]}
              fxSlots={fxSlots[mySeat]}
              beatKey={`${game?.round}-${beatIdx}`}
              scale={hpScale}
              onInfo={setInfo}
            />}

            {/* ── Prompts. Every one of them is "you owe a submission". ── */}
            {!over && owes === "pending" && game?.pending && (
              <div className="rt-prompt">
                <h3><Icon name="spirit" />Choose your next Character</h3>
                <p>Their marker goes on the top space of their track, and its icon applies at once.</p>
                <div className="rt-picks">
                  {game.pending.options.map((c) => (
                    <button type="button" className="rt-pick rt-pick-plain" key={c}
                      onClick={() => sendMove({ kind: "character", character: c })}>
                      <span className="rt-pick-body">
                        <span className="rt-pick-name rt-cap">{c}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {!over && owes === "draft" && (
              <div className="rt-prompt">
                <h3><Icon name="win" />
                  {game.draft_round === 2 ? "Your second fighter" : "Your first fighter"}
                  <span className="rt-step-of">fighter {game.draft_round === 2 ? 2 : 1} of 2</span>
                </h3>
                <p>
                  {game.draft_round === 2
                    ? "These are the ones your opponent passed on. This one fights beside your first."
                    : "Take one, then pass the rest across to your opponent."}
                </p>
                <div className="rt-picks rt-draft">
                  {(game.draft_hand || []).map((fid) => {
                    const b = catalog?.fighters?.[fid];
                    const sg = sigilOf(fid);
                    const hp = maxHpOf(b);
                    return (
                      <InfoTarget as="button" type="button" className="rt-pick rt-draft-card" key={fid}
                        style={{ "--f-ink": sg.ink, "--f-deep": sg.deep }}
                        title={`${b?.name || fid} — hold or right-click for details`}
                        onInfo={() => setInfo({ kind: "fighter", fid })}
                        onClick={() => sendMove({ kind: "draft", fighter: fid })}>
                        <span className="rt-draft-art"><Sigil fid={fid} /></span>
                        <span className="rt-draft-body">
                          <span className="rt-pick-name">{b?.name || fid}</span>
                          <span className="rt-draft-stats">
                            <span className="rt-stat rt-hp">
                              <Icon name="hp" /><b>{hp ?? "—"}</b><small>HP</small>
                            </span>
                            <span className="rt-stat rt-pw">
                              <Icon name="power" /><b>{b ? b.base_power : "?"}</b><small>Power</small>
                            </span>
                          </span>
                          <span className="rt-pick-tags">
                            {(b?.tags || []).map((t) => <em key={t}>{t}</em>)}
                          </span>
                        </span>
                      </InfoTarget>
                    );
                  })}
                </div>
              </div>
            )}

            {!over && owes === "order" && (
              <div className="rt-prompt">
                <h3><Icon name="again" />Who leads?</h3>
                <p>Whoever you pick plays their Starting Card first.</p>
                <div className="rt-picks rt-picks-wide">
                  {myTeam.map((fid, slot) => {
                    const sg = sigilOf(fid);
                    const sc = startingCards[fid];
                    return (
                      <InfoTarget as="button" type="button" className="rt-pick rt-pick-fighter" key={fid}
                        style={{ "--f-ink": sg.ink, "--f-deep": sg.deep }}
                        title={`${catalog?.fighters?.[fid]?.name || fid} — hold or right-click for details`}
                        onInfo={() => setInfo({ kind: "fighter", fid })}
                        onClick={() => sendMove({ kind: "order", slot })}>
                        <span className="rt-pick-crest"><Sigil fid={fid} /></span>
                        <span className="rt-pick-body">
                          <span className="rt-pick-name">{catalog?.fighters?.[fid]?.name || fid}</span>
                          <span className="rt-pick-sub">opens with <b>{sc?.name || "their Starting Card"}</b></span>
                          <span className="rt-pick-ops">
                            {(sc?.ops || []).map((op, n) => (
                              <em key={n}><Icon name={iconForOp(op)} />{opWords(op)}</em>
                            ))}
                          </span>
                        </span>
                      </InfoTarget>
                    );
                  })}
                </div>
              </div>
            )}

            {!over && owes === "build" && (() => {
              const offer = game.build_offer || [];
              // Two of the three offered cards are routinely the SAME card, and
              // rendered identically that reads as a rendering bug rather than
              // as a real choice between two copies. Number them.
              const seen = {};
              const copyOf = {};
              for (const inst of offer) {
                const cid = instances[inst]?.cid;
                seen[cid] = (seen[cid] || 0) + 1;
                copyOf[inst] = seen[cid];
              }
              const total = {};
              for (const inst of offer) total[instances[inst]?.cid] = seen[instances[inst]?.cid];

              const deck = game.fight_deck || [];
              const rows = [];
              const drop = (pos, label) => (
                <button type="button" key={`d${pos}`}
                  className={`rt-drop${buildPos === pos ? " rt-sel" : ""}`}
                  aria-label={label}
                  onClick={() => setBuildPos(pos)}>
                  <span className="rt-drop-line" />
                  <span className="rt-drop-label">{label}</span>
                  <span className="rt-drop-line" />
                </button>
              );
              // One grammar for all three, or the middle one reads as the only
              // target and the outer two read as section headings.
              rows.push(drop(0, "Insert here"));
              deck.forEach((inst, n) => {
                rows.push(
                  <InfoTarget className="rt-deck-row" key={`c${n}`}
                    title={`${cardOf(inst)?.name || "?"} — hold or right-click for details`}
                    onInfo={() => setInfo({ kind: "card", card: cardOf(inst) })}>
                    <span className="rt-deck-n">{n + 1}</span>
                    <span className="rt-deck-name">{cardOf(inst)?.name || "?"}</span>
                  </InfoTarget>);
                rows.push(drop(n + 1, "Insert here"));
              });

              const need = buildPick == null ? "Pick a card to keep"
                : buildPos == null ? "Now choose where it goes"
                : null;

              return (
                <div className="rt-prompt">
                  <h3><Icon name="plant_scheme" />Build your deck</h3>
                  <p>
                    The two you do not keep go to the bottom of your Build Deck.
                  </p>
                  <div className="rt-picks rt-picks-wide">
                    {offer.map((inst) => {
                      const c = cardOf(inst);
                      const sg = sigilOf(c?.fighter);
                      const cid = instances[inst]?.cid;
                      return (
                        <InfoTarget as="button" type="button" key={inst}
                          className={`rt-pick rt-pick-card${buildPick === inst ? " rt-sel" : ""}`}
                          aria-pressed={buildPick === inst}
                          style={{ "--f-ink": sg.ink, "--f-deep": sg.deep }}
                          title={`${c?.name || "card"} — hold or right-click for details`}
                          onInfo={() => setInfo({ kind: "card", card: c })}
                          onClick={() => { setBuildPick(inst); setBuildPos(null); }}>
                          <span className="rt-pick-crest"><Sigil fid={c?.fighter} /></span>
                          <span className="rt-pick-body">
                            <span className="rt-pick-name">
                              {c?.name || "?"}
                              {total[cid] > 1 && copyOf[inst] > 1 && (
                                <span className="rt-copy">2nd copy</span>
                              )}
                            </span>
                            <span className="rt-pick-sub">
                              {catalog?.fighters?.[c?.fighter]?.name}
                              {c?.instant_bonus ? " · instant bonus" : ""}
                            </span>
                            <span className="rt-pick-ops">
                              {(c?.ops || []).map((op, n) => (
                                <em key={n}><Icon name={iconForOp(op)} />{opWords(op)}</em>
                              ))}
                            </span>
                          </span>
                          {buildPick === inst && <span className="rt-pick-tick" aria-hidden="true" />}
                        </InfoTarget>
                      );
                    })}
                  </div>

                  {buildPick != null && (
                    <>
                      <div className="rt-slots">{rows}</div>
                    </>
                  )}

                  {need
                    ? <p className="rt-need"><Icon name="next" />{need}</p>
                    : (
                      <button type="button" className="rt-go"
                        onClick={() => sendMove({ kind: "build", inst: buildPick, pos: buildPos })}>
                        Lock it in
                      </button>
                    )}
                </div>
              );
            })()}

            {!over && owes === null && atEnd && (
              <div className="rt-waitline">
                {game?.phase === "build" ? "Waiting for your opponent to build…"
                  : game?.phase === "draft" ? "Waiting for their pick…"
                  : game?.phase === "order" ? "Waiting for them to choose who leads…"
                  : "Waiting…"}
              </div>
            )}

            {over && atEnd && (
              <div className={`rt-over rt-over-${game.winner === "draw" ? "draw" : game.winner === mySeat ? "win" : "lose"}`}>
                <span className="rt-over-crest"><Icon name="win" /></span>
                <h2>
                  {game.winner === "draw" ? "A draw"
                    : game.winner === mySeat ? "You win" : "You lose"}
                </h2>
                <p>{game.log?.[game.log.length - 1] || ""} · {game.round} rounds</p>
                <div className="rt-over-actions">
                  <LobbyAction onClick={leaveToLobby}>Back to lobby</LobbyAction>
                </div>
              </div>
            )}
            {over && !atEnd && (
              <div className="rt-waitline rt-warn">
                It is decided — step to the last turn to see how it ended.
              </div>
            )}
          </div>

          {/* ── The battle log ──
              Only what has actually been watched. Stepping back does not erase
              it: the log is the record of the fight, the stage is the moment. */}
          <aside className={`rt-rail${roundRows.length || pastRounds.length ? "" : " rt-rail-empty"}`}>
            <div className="rt-log">
              <header className="rt-log-hd"><Icon name="track" />Battle log</header>
              <div className="rt-log-body" ref={logRef}>
                {pastRounds.map((r) => (
                  <section className="rt-log-round" key={`r${r.round}`}>
                    <h4>Round {r.round}</h4>
                    {r.rows.map(logRow)}
                  </section>
                ))}
                {roundRows.length > 0 && (
                  <section className="rt-log-round rt-log-live" key={`live-${game?.round}`}>
                    <h4>Round {game?.round}</h4>
                    {roundRows.map(logRow)}
                  </section>
                )}
                {roundRows.length === 0 && pastRounds.length === 0 && (
                  <p className="rt-log-empty">No turns resolved yet.</p>
                )}
              </div>
            </div>
          </aside>
        </div>
      </div>
      {info && <InfoModal info={info} catalog={catalog} onClose={() => setInfo(null)} />}
      {toast && <div className="rt-toast">{toast}</div>}
      {showRules && (
        <RulesModal title="How to play — Rag Tag" onClose={() => setShowRules(false)}>
          <RagTagRules />
        </RulesModal>
      )}
    </div>
  );
}
