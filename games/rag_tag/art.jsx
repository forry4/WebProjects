/* Rag Tag — the drawn half of the game.
 *
 * The card and board DATA is mechanics only: no publisher wording, no
 * illustration, because rules are not copyrightable and art is. That is the
 * right call for the repo and it leaves the UI with nothing to show, so
 * everything visual here is ORIGINAL and generated in the bundle — no image
 * files, no external requests, nothing to 404 and nothing to cache-bust.
 *
 * Two things live here:
 *   SIGILS — one hand-authored emblem and accent colour per fighter. Twelve is
 *     small enough to draw by hand, and hand-drawn beats a hash: a hashed hue
 *     puts the pirate and the devil on neighbouring reds and reads as a bug.
 *   ICONS — the mechanical vocabulary (attack, block, heal, power, …). The op
 *     lists are rendered from these, so a card says what it does in pictures
 *     the health track and the log also use.
 *
 * Every icon is a 24x24 stroke drawing on `currentColor`, matching the site's
 * existing icon language (see shared/HomeScreen.jsx).
 */

/* ── Per-fighter identity ────────────────────────────────────────────────
 * `ink` is the accent. `deep` is the same hue dropped to a panel-safe
 * darkness — used behind the emblem so a board reads as that fighter's colour
 * without the text on it losing contrast.
 */
export const SIGILS = {
  joan: {
    ink: "#f0c463", deep: "#3a2c12",
    // A banner on a staff, with the cross-bar of a sword through it.
    path: <><path d="M8 21V4" /><path d="M8 5h10l-2.2 3.4L18 12H8" /><path d="M5.5 7.5h5" /></>,
  },
  ching_shih: {
    ink: "#48c2b2", deep: "#0f302e",
    // A ship's wheel.
    path: <><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1.7" /><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8" /></>,
  },
  bodvar: {
    ink: "#e8823f", deep: "#3d2110",
    // A bear's head. Drawn as a silhouette because the claw it replaced read as
    // three unrelated scratches once it was scaled to the boards.
    path: <><path d="M6.6 7.2A3.4 3.4 0 1 1 9.4 5" /><path d="M17.4 7.2A3.4 3.4 0 1 0 14.6 5" /><path d="M12 4.2c4 0 6.6 2.8 6.6 6.6 0 4.4-3 8.4-6.6 8.4s-6.6-4-6.6-8.4C5.4 7 8 4.2 12 4.2z" /><path d="M9.6 10.6h.01M14.4 10.6h.01" /><path d="M10.4 14.6c.9.8 2.3.8 3.2 0" /></>,
  },
  wong_fei_hung: {
    ink: "#46c6a0", deep: "#0f3329",
    // An open palm — the striking hand.
    path: <><path d="M9 13V5.5a1.4 1.4 0 0 1 2.8 0V12" /><path d="M11.8 11.4V4.4a1.4 1.4 0 0 1 2.8 0v7" /><path d="M14.6 11.6V6.2a1.4 1.4 0 0 1 2.8 0v8.2A6.4 6.4 0 0 1 11 20.8h-.7A5.6 5.6 0 0 1 4.7 15l-.5-3.1a1.4 1.4 0 0 1 2.6-.9L9 14" /></>,
  },
  the_wild_bunch: {
    ink: "#cf8a4a", deep: "#3a2313",
    // A lawman's star, which this lot are emphatically on the wrong side of.
    path: <><path d="M12 3.2l2.3 4.9 5.3.7-3.9 3.7 1 5.3-4.7-2.6-4.7 2.6 1-5.3L4.4 8.8l5.3-.7z" /><circle cx="12" cy="11" r="1.6" /></>,
  },
  shango: {
    ink: "#f5ab3d", deep: "#3f2a0c",
    // The thunderbolt, doubled — Shango carries a twin axe.
    path: <><path d="M13.5 2.5L6 13h4.5L9 21.5 17.5 10H13z" /></>,
  },
  maman_brijit: {
    ink: "#d178bd", deep: "#361632",
    // A veve cross over a crescent — the graveyard loa.
    path: <><path d="M12 3.5v17" /><path d="M6.5 8.5h11" /><path d="M7.5 17.5c1.6 1.8 7.4 1.8 9 0" /><circle cx="12" cy="6" r="1.3" /></>,
  },
  mephisto: {
    ink: "#ef6a52", deep: "#3d150f",
    // A horned head. The previous horns-over-a-shaft read as a letterform.
    path: <><path d="M4.6 3.8c3 .5 4.8 2.4 5.6 5.2" /><path d="M19.4 3.8c-3 .5-4.8 2.4-5.6 5.2" /><path d="M12 7.6c3.8 0 6.4 2.7 6.4 6.3 0 3.9-2.9 6.9-6.4 6.9s-6.4-3-6.4-6.9c0-3.6 2.6-6.3 6.4-6.3z" /><path d="M9.6 13.4h.01M14.4 13.4h.01" /><path d="M9.8 17.6c1.3-1 3.1-1 4.4 0" /></>,
  },
  mordred: {
    ink: "#93b0dd", deep: "#1a2436",
    // A visored helm. The sword it replaced was a plain vertical stroke and read
    // as a divider rather than as a fighter.
    path: <><path d="M6 10.5a6 6 0 0 1 12 0v4.2c0 3-2.7 5.3-6 5.3s-6-2.3-6-5.3z" /><path d="M6.4 12.4h11.2" /><path d="M9 15.2h6" /><path d="M12 4.5V2.2" /></>,
  },
  milady: {
    ink: "#b48be0", deep: "#2b1c3c",
    // A domino mask.
    path: <><path d="M3.5 9.5c3-1.4 14-1.4 17 0 .5 3.2-.6 5.6-3.2 5.9-2 .2-3.4-1-4.2-2.4h-2.2c-.8 1.4-2.2 2.6-4.2 2.4C4.1 15.1 3 12.7 3.5 9.5z" /><path d="M9 11.4h.01M15 11.4h.01" /></>,
  },
  golem: {
    // Stone with a blue cast rather than plain grey — as neutral grey it was the
    // one fighter whose art window had no hue to lift it off the panel.
    ink: "#93a4b3", deep: "#232c34",
    // A blocky clay figure.
    path: <><rect x="7.5" y="3.5" width="9" height="7" rx="1.2" /><path d="M6 12h12v5.5a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2z" /><path d="M10 6.6h.01M14 6.6h.01" /><path d="M10.2 19.5v2M13.8 19.5v2" /></>,
  },
  the_fey_folk: {
    ink: "#86d873", deep: "#173318",
    // A leaf with a spiral vein.
    path: <><path d="M19 4.5C10 4.5 4.5 9 4.5 15.5c0 2.2 1.4 4 3.6 4 6 0 10.9-5.6 10.9-15z" /><path d="M8.1 19.5C11 15 14.6 11.6 18.4 9.4" /></>,
  },
};

export const FALLBACK_SIGIL = {
  ink: "#c9a45e", deep: "#332a1a",
  path: <><circle cx="12" cy="12" r="8" /><path d="M12 8v8M8 12h8" /></>,
};

export function sigilOf(fid) {
  return SIGILS[fid] || FALLBACK_SIGIL;
}

/* One fighter's emblem. `size` is a CSS length so it can be driven by clamp()
 * from the sheet rather than by a magic pixel number here. */
export function Sigil({ fid, className = "", title }) {
  const s = sigilOf(fid);
  return (
    <svg className={`rt-sigil ${className}`} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.1" strokeLinecap="round"
      strokeLinejoin="round" aria-hidden={title ? undefined : "true"}
      role={title ? "img" : undefined}>
      {title && <title>{title}</title>}
      {s.path}
    </svg>
  );
}

/* ── The mechanical icon set ─────────────────────────────────────────────
 * Keyed by the op name in `effects.py`, plus a few the log needs. Anything
 * missing falls through to a neutral dot rather than rendering nothing, so a
 * new op added to the data shows up as an unstyled-but-present row instead of
 * silently disappearing from the card.
 */
const P = (d, extra) => <><path d={d} />{extra}</>;

export const ICONS = {
  attack: P("M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1.1 5.9L12 16.9 6.7 19.7l1.1-5.9L3.5 9.7l5.9-.8z"),
  block: P("M12 3l7 2.6v5.6c0 4.2-2.8 7.6-7 9.3-4.2-1.7-7-5.1-7-9.3V5.6z"),
  damage: P("M13.6 2.5L6.5 12.6h4.2l-1.3 8.9 8.1-11h-4.6z"),
  heal: P("M12 20.4S4 15.6 4 9.9A4.2 4.2 0 0 1 12 7.6 4.2 4.2 0 0 1 20 9.9c0 5.7-8 10.5-8 10.5z"),
  power: P("M6.5 4.5h11l2.5 4.2-8 11.3-8-11.3z", <path d="M4.5 9h15M9.5 9l2.5 11M14.5 9L12 20M9.5 9l2.5-4.5L14.5 9" />),
  hp: P("M12 20.4S4 15.6 4 9.9A4.2 4.2 0 0 1 12 7.6 4.2 4.2 0 0 1 20 9.9c0 5.7-8 10.5-8 10.5z"),
  cancel: P("M5.6 5.6l12.8 12.8", <circle cx="12" cy="12" r="8.6" />),
  ignite: P("M12 21c3.6 0 6-2.4 6-5.6 0-4.2-4.2-5.9-3.2-10.4C11.6 6 8.4 8.6 8.4 12c0 1.2.4 2 .4 2S8 13.4 8 12c-1.3 1.2-2 2.4-2 3.9C6 18.6 8.4 21 12 21z"),
  transfer_power: P("M4 9h12l-3-3M20 15H8l3 3"),
  plant_scheme: P("M12 20V9", <><path d="M12 9c0-2.6-1.8-4.4-4.4-4.4C7.6 7.2 9.4 9 12 9z" /><path d="M12 12c0-2.6 1.8-4.4 4.4-4.4C16.4 10.2 14.6 12 12 12z" /></>),
  unleash_scheme: P("M4.5 12h9M13.5 12l-3.4-3.4M13.5 12l-3.4 3.4", <path d="M17 4.5v15" />),
  give_token: P("M4 12h12l-3.6-3.6M16 12l-3.6 3.6", <circle cx="20" cy="12" r="1.4" />),
  take_token: P("M20 12H8l3.6-3.6M8 12l3.6 3.6", <circle cx="4" cy="12" r="1.4" />),
  flip_card: P("M7 4.5h10v15H7z", <path d="M12 4.5v15" />),
  spirit: P("M12 3.5c3 0 5.4 2.5 5.4 5.6 0 3.6-2.4 4.6-2.4 7.4H9c0-2.8-2.4-3.8-2.4-7.4C6.6 6 9 3.5 12 3.5z", <path d="M9.4 19.5h5.2M10.2 21.5h3.6" />),
  track: P("M4 18h16", <path d="M7 18V9M12 18V5M17 18v-6" />),
  fx: P("M12 3.5l1.7 4.3 4.3 1.7-4.3 1.7L12 15.5l-1.7-4.3L6 9.5l4.3-1.7z", <path d="M18.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z" />),
  ko: P("M8.5 20.5v-2.2A6.6 6.6 0 0 1 5 12.4 6.9 6.9 0 0 1 12 5.5a6.9 6.9 0 0 1 7 6.9 6.6 6.6 0 0 1-3.5 5.9v2.2z", <path d="M9.6 12h.01M14.4 12h.01M10 17.4h4" />),
  again: P("M20 12a8 8 0 1 1-2.5-5.8", <path d="M20 4v4.5h-4.5" />),
  win: P("M7 4h10v4a5 5 0 0 1-10 0z", <path d="M7 5.5H4.5V7A3 3 0 0 0 7 10M17 5.5h2.5V7A3 3 0 0 1 17 10M10 13.2V17h4v-3.8M8 20.5h8" />),
  next: P("M9 5.5l6.5 6.5L9 18.5"),
  prev: P("M15 5.5L8.5 12l6.5 6.5"),
  skip: P("M6 5.5L12.5 12 6 18.5", <path d="M13.5 5.5L20 12l-6.5 6.5" />),
  dot: <circle cx="12" cy="12" r="3.2" />,
};

export function Icon({ name, className = "", strokeWidth = 1.6 }) {
  return (
    <svg className={`rt-i ${className}`} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true">
      {ICONS[name] || ICONS.dot}
    </svg>
  );
}

/* What a `fx` op actually DOES, in words.
 *
 * These are the cards the declarative op vocabulary cannot express, so the card
 * face used to render the literal word "Special" — a database enum leaking onto
 * the table. The wording follows the fx docstrings in effects.py so the two move
 * together. An unknown name still falls back to "Special" rather than to blank.
 */
export const FX_TEXT = {
  // Board-icon only, and it sits BESIDE the +3 Power op on the same space --
  // so saying the Power here printed it twice on Bödvar's Rage read-out.
  bodvar_transform: "Turn over into the Berserker Bear",
  // NOT "at the end of the turn" -- that was the bug the BGA corpus corrected
  // in the engine, and the words here were never corrected with it.
  brijit_revive: "Come straight back, the moment that movement settles",
  brijit_eternal_youth: "Steal the healing your opponents receive",
  brijit_redirect_attacks: "Every attack your Block caught turns onto their partner",
  ching_terror_of_the_seas: "Three different cards, depending on how many Ships you have",
  feyfolk_all_legends_must_pass: "KO them if all three Characters are already Spirits",
  golem_reanimation: "Your next card resolves twice",
  mephisto_drag_you_to_hell: "Lose this turn for any reason and you win instead",
  mephisto_flip_serpent: "Turn the serpent over — the next card reads the new face",
  milady_poison: "Poison: half their current HP, rounded down",
  milady_unleash_scheme: "Unleash a Scheme, once both cards have resolved",
  mordred_execution: "A finisher, read after their card resolves",
  wb_corrupted_lawman: "The Sheriff changes sides",
  wb_keys_to_the_armory: "Whoever holds the Sheriff gains 2 Power — even them",
  wong_crippling_touch: "Remove their card from the game, then this one",
  wong_harder_they_fall: "Mark them, or cash the mark in for their own Power",
  wong_match_partner_power: "Your Power becomes your partner's — down as well as up",
};

/* What a mechanic MEANS, for the detail modal.
 *
 * Without this the card modal was an empty state wearing a panel: for a card
 * with no rules note it printed the title, the fighter, and the same one-line
 * effect already on the face. A player who holds a card and learns nothing
 * stops holding cards. These are the non-obvious halves — the parts the verb
 * does not tell you — so even a one-op card is worth opening.
 */
export const OP_GLOSSARY = {
  attack: "Attack — deals your Power in damage. A single Block cancels EVERY attack that team makes this turn, whatever it was aimed at.",
  block: "Block — cancels every attack the opposing team makes this turn, even the ones aimed at their own partner.",
  damage: "Direct damage — not an attack, so a Block does not stop it.",
  heal: "Heal — moves the marker back up the track. A fighter already on a KO space can never be healed.",
  power: "Power — settles after the cards resolve, so Power gained this turn does not fuel this turn's attack.",
  transfer_power: "Moving Power settles with everything else, after both cards have resolved.",
  cancel: "Cancel — the other card does nothing at all, including its own cancel. Read before anything else happens.",
  ignite: "Aflame — a burning token that stays. Five of them is Incineration, and that is an instant loss.",
  track: "A track advances a marker on this fighter's own board, separately from their health.",
  spirit: "Spirits are the Fey Folk's Characters after they fall. They still count, and some cards scale with how many there are.",
  plant_scheme: "A planted Scheme waits above Milady's board. It is Unleashed later — by a card, or by her Health marker reaching one of the three spaces that call for one.",
  unleash_scheme: "Unleashing turns a planted Scheme face up and applies it. Schemes Unleashed from the Health track resolve AFTER every card Action, which is how they can move a marker sitting on a Stop.",
  give_token: "Passing a token can hand an opponent something they want. Check who ends up holding it.",
  take_token: "Taking a token pulls it from whoever holds it, including an opponent.",
  flip_card: "This card has two faces. Turning it over changes what it does next time it is revealed.",
  fx: "This one does not follow the usual pattern — read the note above.",
};

/* How hard a fighter is to play, in words.
 *
 * The board data carries a 1-5 rating and the modal rendered it as the number
 * plus "of 5 to learn", which is a scale nobody has been shown either end of.
 * A word needs no scale.
 */
export const COMPLEXITY_WORD = ["", "Simple", "Easy", "Moderate", "Complex", "Expert"];

export function complexityWord(n) {
  return COMPLEXITY_WORD[n] || "";
}

/* The words the BOARD uses for a track and a token, against the ids the data
 * uses for them. Cards read "+1 navigation" and "Pass the presence token" —
 * field names, straight out of the JSON, on the face of a card. */
export const TRACK_TITLE = {
  divine_voice: "Divine Voice",
  navigation: "Fleet",
  rage: "Rage",
  spirits: "Spirit",
};

/* The numbers a range-only track's own cards ask about, notched onto the bar so
   the next one you are playing toward is visible rather than remembered. Ching
   Shih's board rings these four; the Fey Folk's Spirit track has no thresholds
   because every step of it counts. */
export const TRACK_MARKS = {
  navigation: [7, 10, 15, 20],
};

/* The UNIT a track counts, which is not always its name: Ching Shih's is the
   Fleet track and it counts Ships. */
export const TRACK_WORD = {
  divine_voice: ["Divine Voice", "Divine Voice"],
  navigation: ["Ship", "Ships"],
  rage: ["Rage", "Rage"],
  spirits: ["Spirit", "Spirits"],
};

export const TOKEN_WORD = {
  presence: "Presence",
  aflame: "Aflame!",
  sheriff: "Sheriff",
  concentration: "Concentration",
  scheme: "Scheme",
  serpent: "serpent",
};

export function trackWord(id, n) {
  const w = TRACK_WORD[id];
  if (!w) return String(id).replace(/_/g, " ");
  return Math.abs(n) === 1 ? w[0] : w[1];
}

export function tokenWord(id) {
  return TOKEN_WORD[id] || String(id).replace(/_/g, " ");
}

/* What a named track BESIDE the health track is for.
 *
 * The modal used to describe these straight from the data — "Has a divine voice
 * track of 5 spaces" — which is a field name and a length. It never said what
 * the track was for, never drew it, and never mentioned that two of Joan's five
 * printed spaces pay out and three do not. A player who opens a board to find
 * out what the dial does and reads its array length has been told nothing.
 *
 * Only the MEANING is written here. Every number the modal shows — how many
 * spaces, which ones pay, the cap — is derived from the same data the strip is
 * drawn from, so a corrected import cannot leave this disagreeing with the art.
 */
export const TRACK_GLOSSARY = {
  divine_voice: "Joan's dial. Her cards step it round, and ONLY the space it lands on pays out — a space it steps over does nothing. The Halo in the middle is where it starts and it is never returned to, so from the first step on it is a ring of four.",
  rage: "Bödvar's Rage. Each gain steps up one space. Reaching the top pays him 3 Power and then turns his board over to the Berserker Bear — a different fighter, with its own health track, and there is no way back.",
  navigation: "Ching Shih's Fleet track, counted in Ships. It pays nothing by itself; her cards read the number off it, and the board rings 7, 10, 15 and 20 as the thresholds they ask about. Ships gained past 20 are ignored.",
  spirits: "The Fey Folk's Spirit track. It starts at 1 and steps up each time a Character becomes a Spirit, so it counts how far through the three they are. Several of their cards scale with it — and at the top all three are Spirits, which is the only state in which they can lose.",
};

/* What each kind of space on a health track does. The modal printed this as a
 * four-swatch key on EVERY board, including the nine with no revive space and
 * the ten with no STOP — a legend for things that were not there. */
export const SPACE_GLOSSARY = {
  ko: "KO — a marker sitting here at the end of a turn loses the fight for its whole team.",
  stop: "STOP — the marker halts the instant it reaches this space, going down or up. The rest of the movement is lost.",
  revive: "Revive — below the KO spaces. Pushed all the way past them and the fighter comes back instead of falling.",
  spirit: "Spirit — this Character's last space. Reaching it turns them into a Spirit and the next Character steps in.",
  icon: "An icon fires when the marker lands on it or passes through it, once every marker has finished moving. Sitting on one and stepping off pays nothing.",
};

/* What a token is for.
 *
 * Keyed by the name in the board data, which is all the modal had: it said
 * "Starts with 1 presence" and left the player to guess what a presence is.
 */
export const TOKEN_GLOSSARY = {
  presence: "Whoever holds the Presence has one Attack aimed at them eaten whole, and the token goes home to the Golem to be spent again. A Block gets there first, and a 0-Power Attack does not spend it.",
  aflame: "Shango's flames sit on the fighter they are put on and never come off. Two of his cards hit for 1 extra per flame already on the target. A fifth on one fighter is Incineration — that team loses on the spot.",
  sheriff: "The Sheriff changes hands, and several Wild Bunch cards ask who is holding him — including one that pays the holder even when that is an opponent.",
  concentration: "Wong Fei-Hung spends a Concentration to mark an opponent. A later card cashes the mark in and hits them with their OWN Power, and takes the token back off the fighter it cashed.",
  scheme: "Milady's Schemes, face down. Eleven of them, drawn without replacement, so the pile runs out; a Scheme's effect is hidden until it is Unleashed, and a spent one leaves the Fight.",
  serpent: "Mephisto's serpent shows one of two faces, chosen at random at setup. Some of his cards read the face that is showing; others turn it over — so the same card is two cards depending on when it comes up.",
};

/* Which icon fronts an op row on a card. Kept beside the icon table so adding
 * an op to the data and forgetting the picture is one file to notice it in. */
export function iconForOp(op) {
  if (!op) return "dot";
  if (op.op === "if") return "fx";
  return ICONS[op.op] ? op.op : "dot";
}
