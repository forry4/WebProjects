/* Turning one beat into readable lines.
 *
 * The engine records a beat as a flat list of events in CAUSAL order — the
 * Attack that was thrown, then the Block that ate it, then the HP that actually
 * moved. This walks that list once and produces log lines in the same order, so
 * the log reads as an account of the turn rather than as a diff of the state.
 *
 * It is a separate module from the component because it is pure and worth
 * testing on its own, and because the ring and the log render the SAME lines —
 * the ribbon under the cards is just the current beat's narration, so the two
 * can never disagree about what happened.
 */

import { tokenWord, trackWord } from "./art.jsx";

const cap = (s) => (s ? String(s)[0].toUpperCase() + String(s).slice(1) : "");

/* HP events carry track INDICES, not hit points: a fighter's marker sits on a
 * space, and what that space is worth is a property of their board. Converting
 * here (rather than showing the raw index) is the difference between "Shango
 * 12 → 9" and "Shango takes 3, down to 9". */
function spaceLabel(track, idx) {
  const sp = track && track[idx];
  if (!sp) return null;
  if (sp.kind === "ko") return "KO";
  if (sp.kind === "spirit") return "Spirit";
  if (sp.kind === "revive") return "the veil";
  return String(sp.hp);
}

function spaceHp(track, idx) {
  const sp = track && track[idx];
  return sp && sp.kind === "hp" ? sp.hp : null;
}

/* Milady's Intrigue tokens, in words. The raw id was rendered with its
   underscores swapped for spaces, which produced "Intrigue unleashed: attack
   and unleash" -- not a sentence in any language. */
const SCHEME_TEXT = {
  attack_and_unleash: "attack, then unleash another",
  attack_both: "attack both opponents",
  partner_heal_6: "your partner heals 6",
  all_take_1: "everyone takes 1",
  gain_2_power: "you gain 2 Power",
  partner_gains_2_power: "your partner gains 2 Power",
  unleash_and_partner_power: "unleash another, and your partner gains 1 Power",
  both_gain_1_power: "you and your partner each gain 1 Power",
  poison: "poison — half their health, rounded down",
};

function joinNames(list) {
  if (list.length <= 1) return list[0] || "";
  if (list.length === 2) return `${list[0]} and ${list[1]}`;
  return `${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}`;
}

/* `ctx` supplies everything board-shaped that narration cannot know:
 *   name(seat, slot)   -> the fighter's display name
 *   track(seat, slot, beat) -> that fighter's health track AS OF THIS BEAT. It changes
 *                         within a round -- Bödvar flips onto a second board and a Fey
 *                         Folk Character brings their own -- so narrating an early turn
 *                         against the round's FINAL track reads the indices off the wrong
 *                         board and reports the wrong numbers.
 *   mine(seat)         -> is this my side
 */
export function narrateEvent(beat, i, ctx) {
  const lines = [];
  const ev = (beat?.events || [])[i];
  if (!ev) return lines;
  const name = (s, l) => ctx.name(s, l) || "?";
  const push = (tone, icon, text, key) => lines.push({ tone, icon, text, key });

  const k = `${beat.turn}-${i}`;
  switch (ev.kind) {
    case "cancel":
      push("info", "cancel",
        `${name(ev.seat, beat.active?.[ev.seat] ?? 0)} cancels the other card — it does nothing at all`, k);
      break;

    case "attack": {
      const who = name(ev.seat, ev.slot);
      const at = joinNames((ev.targets || []).map(([s, l]) => name(s, l)));
      const force = ev.power > 0 ? ` for ${ev.power}` : " — no damage";
      if (ev.negated) push("info", "block", `${who}'s attack on ${at} is blocked`, k);
      else if (ev.power <= 0) push("info", "attack", `${who} attacks ${at}${force}`, k);
      else push(ctx.mine(ev.seat) ? "good" : "hit", "attack", `${who} attacks ${at}${force}`, k);
      break;
    }

    case "block": {
      // A Block that WORKED is already narrated from the other side, once per
      // attack it swallowed ("X's attack on Y is blocked"). Saying "Y blocks"
      // as well told both halves of one fact and doubled the log.
      if (ev.worked) break;
      push("info", "block", `${name(ev.seat, ev.slot)} braces, but nothing comes`, k);
      break;
    }

    case "again":
      push("info", "again", `${name(ev.seat, ev.slot)} makes the card resolve a second time`, k);
      break;

    case "hp": {
      const track = ctx.track(ev.seat, ev.slot, beat);
      const down = ev.to < ev.from;
      const before = spaceHp(track, ev.from);
      const after = spaceLabel(track, ev.to);
      const size = before != null && spaceHp(track, ev.to) != null
        ? Math.abs(before - spaceHp(track, ev.to)) : Math.abs(ev.to - ev.from);
      const who = name(ev.seat, ev.slot);
      push(down ? "hit" : "heal", down ? "damage" : "heal",
        down ? `${who} takes ${size}${after != null ? ` — down to ${after}` : ""}`
          : `${who} recovers ${size}${after != null ? ` — up to ${after}` : ""}`, k);
      break;
    }

    case "power": {
      const d = ev.to - ev.from;
      push("power", "power",
        `${name(ev.seat, ev.slot)} ${d > 0 ? "gains" : "loses"} ${Math.abs(d)} Power — now ${ev.to}`, k);
      break;
    }

    case "ko":
      push("big", "ko", `${name(ev.seat, ev.slot)} is knocked out`, k);
      break;

    case "spirit":
      // The Character id, which is lower case in the data and a proper noun
      // on the board.
      push("big", "spirit", `${cap(ev.character)} passes into Spirit`, k);
      break;

    case "track": {
      // The name the board prints, not the JSON key: the log read
      // "Ching Shih: navigation 3 -> 4". The plural is the track's name in
      // all four cases (Ships, Spirits, Rage, Divine Voice).
      const label = trackWord(ev.track, 2);
      push("info", "track",
        `${name(ev.seat, ev.slot)}: ${label} ${ev.from} → ${ev.to}`, k);
      break;
    }

    case "token": {
      const label = tokenWord(ev.token);
      push("info", ev.token === "aflame" ? "ignite" : "give_token",
        ev.token === "aflame"
          ? `${name(ev.seat, ev.slot)} is set Aflame`
          : `${name(ev.seat, ev.slot)} takes the ${label} token`, k);
      break;
    }

    case "scheme":
      push("info", "plant_scheme",
        `${name(ev.seat, ev.slot)} plants a Scheme (${ev.planted} waiting)`, k);
      break;

    case "scheme_reveal":
      push("big", "unleash_scheme",
        `Intrigue: ${SCHEME_TEXT[ev.effect] || String(ev.effect).replace(/_/g, " ")}`, k);
      break;

    case "flip":
      push("info", "flip_card", `${name(ev.seat, 0)} turns a card over`, k);
      break;

    case "removed":
      push("big", "cancel", "a card is removed from the game for good", k);
      break;

    case "instant_bonus":
      push("info", "fx", "Instant Bonus", k);
      break;

    default:
      break;
  }
  return lines;
}

/* Every line of a beat, in order. `limit` stops after that many EVENTS, which is
   how the ribbon and the log show a turn that is still playing out. */
export function narrateBeat(beat, ctx, limit) {
  if (!beat) return [];
  const evs = beat.events || [];
  const upto = limit == null ? evs.length : Math.max(0, Math.min(limit, evs.length));
  const lines = [];
  for (let i = 0; i < upto; i++) lines.push(...narrateEvent(beat, i, ctx));
  return lines;
}

/* A turn, cut into the ACTIONS it is made of.
 *
 * The engine records a beat as a flat list of events in causal order, and the
 * whole turn used to land in one frame: four sentences at once, and every health
 * bar, Power total and token jumping to its end-of-turn value together. The card
 * said "attack, then heal, then burn" and the table showed the sum.
 *
 * A STEP is one event that has something to say, plus any silent events that ran
 * up to it -- a Block that worked narrates nothing (the attack it swallowed is
 * already narrated from the other side) but it is still part of what happened, so
 * it rides with the next thing that speaks rather than becoming an empty beat to
 * click past. Trailing silent events ride on the last step for the same reason:
 * `upto` there is stretched to the end so no event is left unapplied.
 *
 * `upto` is an EXCLUSIVE index into `beat.events` -- both the narration cutoff and
 * how far the board has moved, so the sentence and the numbers cannot disagree. */
export function beatSteps(beat, ctx) {
  const evs = beat?.events || [];
  const steps = [];
  for (let i = 0; i < evs.length; i++) {
    const lines = narrateEvent(beat, i, ctx);
    if (lines.length) steps.push({ upto: i + 1, lines });
  }
  if (steps.length) steps[steps.length - 1].upto = evs.length;
  else if (evs.length) steps.push({ upto: evs.length, lines: [] });
  return steps;
}

/* The board as it stood after `upto` events of this beat.
 *
 * Each event carries the fighters IT moved (`st`), stamped by the engine at the
 * instant it happened, so this is a merge and never a re-derivation: the client
 * models no event kind, exactly as it did when a beat carried a single snapshot.
 * A beat saved before per-event state existed has no `pre` and no `st`, and the
 * honest answer for one of those is the only state it has. */
export function beatStateAt(beat, upto) {
  if (!beat) return null;
  if (!beat.pre) return beat.state || null;
  const evs = beat.events || [];
  const n = upto == null ? evs.length : Math.max(0, Math.min(upto, evs.length));
  if (n >= evs.length && beat.state) return beat.state;
  const out = [[...(beat.pre[0] || [])], [...(beat.pre[1] || [])]];
  for (let i = 0; i < n; i++) {
    for (const [seat, slot, f] of evs[i].st || []) {
      if (out[seat]) out[seat][slot] = f;
    }
  }
  return out;
}

/* The whole round, as a flat list of {kind:"turn"|"line"} rows. The log builds
 * from this so a turn heading and its lines cannot drift apart. `upto` is the
 * playback cursor: the log only ever shows what the player has actually
 * watched, which is the entire point of stepping through by hand. */
/* A beat with no revealed cards is setup, not a turn -- see isTurnBeat in
   RagTag.jsx. Numbering it made the log disagree with the stage about how many
   turns a round had. */
function isTurnBeat(beat) {
  return !!beat && (beat.insts || []).some((x) => x != null);
}

/* `liveUpto` cuts the LIVE beat's lines off where its replay has got to, so a
   turn that is still playing out reaches the log one sentence at a time -- the
   same cutoff the ribbon and the boards use, from the same step. */
export function narrateRound(beats, upto, ctx, livePos, liveUpto) {
  const rows = [];
  let nth = 0;
  for (let i = 0; i <= Math.min(upto, (beats?.length ?? 0) - 1); i++) {
    const beat = beats[i];
    if (!beat) continue;
    // Number the turns the way the stage does -- from 1, counting only real
    // turns. `beat.turn` is the ENGINE's counter and starts at 0.
    const real = isTurnBeat(beat);
    if (real) nth += 1;
    // `livePos` is the beat currently on the stage. The log includes it -- stopping one
    // short reads as a log that is always a turn behind -- and marks it instead, so the
    // reader can see which entry the cards above them belong to.
    const live = livePos != null && i === livePos;
    rows.push({
      kind: "turn", key: `t${i}`, turn: real ? nth : null, live,
      cards: (beat.cids || []).map((_, s) => ctx.cardName(beat.insts?.[s])),
    });
    const lines = narrateBeat(beat, ctx, live ? liveUpto : undefined);
    // "Nothing lands." belongs to a turn that HAD nothing to say, not to one
    // whose first action has yet to be revealed -- printing it there put a
    // verdict on the turn a beat before the turn had one.
    const quiet = !lines.length && !(live && liveUpto === 0 && (beat.events || []).length);
    if (quiet) rows.push({ kind: "line", key: `t${i}-q`, tone: "info", icon: "dot", text: "Nothing lands.", live });
    for (const l of lines) rows.push({ kind: "line", ...l, live });
  }
  return rows;
}
