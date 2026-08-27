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
export function narrateBeat(beat, ctx) {
  if (!beat) return [];
  const lines = [];
  const name = (s, l) => ctx.name(s, l) || "?";
  const push = (tone, icon, text, key) => lines.push({ tone, icon, text, key });

  for (const [i, ev] of (beat.events || []).entries()) {
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
          `${name(ev.seat, ev.slot)} plants an Intrigue (${ev.planted} waiting)`, k);
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
  }
  return lines;
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

export function narrateRound(beats, upto, ctx, livePos) {
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
    const lines = narrateBeat(beat, ctx);
    if (!lines.length) rows.push({ kind: "line", key: `t${i}-q`, tone: "info", icon: "dot", text: "Nothing lands.", live });
    else for (const l of lines) rows.push({ kind: "line", ...l, live });
  }
  return rows;
}
