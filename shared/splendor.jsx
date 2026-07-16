/* Shared Splendor visual vocabulary — gem tokens, jewel cards, and the move log.
 *
 * Spender and Spender Duel are the same FAMILY of game (gems, cards with costs and
 * bonuses, gold-as-wild, reserves), so they must LOOK the same. The components and
 * CSS below were extracted VERBATIM out of Spender.jsx — which exported only its app
 * component, so Duel had re-implemented lookalikes and drifted visually (square
 * swatches vs round, its own palette/fonts, a different log). Both games now import
 * from here, so there is no second copy to drift.
 *
 * Duel-only affordances (crowns, pearls, wild bonuses, ability glyphs) are OPTIONAL:
 * Spender never passes them and renders exactly as it always did.
 *
 * NOTE: like every css string in this repo, the template literals here must contain
 * NO backtick (the documented blank-page footgun).
 */

// The 5 gem colors (both games) + Duel's pearl and the shared gold wild.
export const GEM_COLORS = ["white", "blue", "green", "red", "black"];
export const GEM_LABELS = {
  white: "Diamond", blue: "Sapphire", green: "Emerald", red: "Ruby",
  black: "Onyx", gold: "Gold", pearl: "Pearl",
};
export const GEM_HEX = {
  white: "#ddd4be", blue: "#4257ff", green: "#3f9c2e", red: "#dc4040",
  black: "#15151a", gold: "#f5c842", pearl: "#e8c0d4",
};
// Light chips need a dark glyph.
const DARK_TEXT = new Set(["white", "gold", "pearl"]);
// Gems show their initial; the wilds show a symbol.
const tokenGlyph = (c) => (c === "gold" ? "★" : c === "pearl" ? "●" : c[0].toUpperCase());

/* Gem token. `size` is applied inline (Spender's 42px default). Pass size={null} to
 * let CSS size it instead — Duel's board scales its tokens with the column, and an
 * inline width/height would beat the stylesheet and freeze them. */
export function GemToken({ color, size = 42, className = "", onClick, title, dataCell }) {
  const style = { background: GEM_HEX[color], color: DARK_TEXT.has(color) ? "#333" : "#fff" };
  if (size) { style.width = size; style.height = size; }
  return (
    <div className={`gem-token ${className}`.trim()} style={style} onClick={onClick}
      title={title} data-cell={dataCell}>
      {tokenGlyph(color)}
    </div>
  );
}

/* A jewel card.
 * Spender passes {card, selected, affordable, needsGold, disabled, onClick, aiValue,
 * valsMine, dataPos}. Duel additionally uses card.crowns, card.cost.pearl,
 * card.bonus === "wild" (+ `asColor` once attached), and card.ability with the glyph
 * and tooltip supplied BY THE CALLER — so this shared file owns no game rules. */
export function CardView({ card, selected, affordable, needsGold, disabled, onClick,
                          aiValue, valsMine, dataPos, asColor, abilityGlyph, abilityTitle,
                          small }) {
  const who = valsMine ? "Your values" : "AI's values";
  // An opponent's blind deck-top reserve is hidden info — show a face-down back.
  if (card.hidden) {
    return (
      <div className={`card card-back${small ? " card-small" : ""}`}>
        <span className="card-back-level">{["I", "II", "III"][(card.level || 1) - 1]}</span>
        <span className="card-back-label">Reserved</span>
      </div>
    );
  }
  const isWild = card.bonus === "wild";
  const bonusBg = isWild
    ? (asColor ? GEM_HEX[asColor] : "linear-gradient(135deg,#8d8579 0%,#d9d2c4 50%,#8d8579 100%)")
    : GEM_HEX[card.bonus];
  const gems = Object.entries(card.cost || {}).filter(([c, n]) => c !== "pearl" && n > 0);
  const pearl = (card.cost || {}).pearl || 0;
  return (
    <div data-pos={dataPos}
      className={`card${small ? " card-small" : ""}${selected ? " selected" : ""}${affordable ? (needsGold ? " affordable-gold" : " affordable") : ""}${disabled ? " disabled" : ""}`}
      onClick={disabled ? undefined : onClick}
    >
      <div className="card-header">
        <span className={`card-points${card.points === 0 ? " zero" : ""}`}>{card.points || ""}</span>
        {card.crowns > 0 && (
          <span className="card-crowns" title={`${card.crowns} crown${card.crowns > 1 ? "s" : ""}`}>
            {"♛".repeat(card.crowns)}
          </span>
        )}
        {card.bonus && (
          <div className={`card-bonus${isWild ? " card-bonus-wild" : ""}${card.bonus_count === 2 ? " card-bonus-double" : ""}`}
            style={{ background: bonusBg }}
            title={isWild ? (asColor ? `Wild bonus (as ${asColor})` : "Wild bonus — attaches to one of your colors") : undefined} />
        )}
      </div>
      {card.ability && abilityGlyph && (
        <div className="card-ability" title={abilityTitle}>{abilityGlyph}</div>
      )}
      {/* Gems stack in the first column; a pearl ALWAYS sits in the second, so its
          position never shifts from card to card. With no pearl there is a single
          column and this renders exactly as Spender always has. */}
      <div className={`card-cost${pearl ? " card-cost-2col" : ""}`}>
        <div className="cost-col">
          {gems.map(([c, n]) => (
            <div key={c} className="cost-row">
              <div className="cost-gem" style={{ background: GEM_HEX[c] }} />
              <span className="cost-num">{n}</span>
            </div>
          ))}
        </div>
        {pearl > 0 && (
          <div className="cost-col">
            <div className="cost-row">
              <div className="cost-gem" style={{ background: GEM_HEX.pearl }} />
              <span className="cost-num">{pearl}</span>
            </div>
          </div>
        )}
      </div>
      {aiValue != null && (typeof aiValue === "object" ? (
        <div className={`ai-vals${valsMine ? " mine" : ""}`} title={`${who} — ${aiValue._s
          ? "S"
          : aiValue.pot != null
          ? "H3"
          : "H2"} — take / engine / point / cost`}>
          <span><b>T</b>{aiValue.t}</span>
          <span><b>E</b>{aiValue.e}</span>
          <span><b>P</b>{aiValue.p}</span>
          <span><b>C</b>{aiValue.c}</span>
        </div>
      ) : (
        <span className={`ai-val${valsMine ? " mine" : ""}`} title={`${who} (variant H)`}>{aiValue}</span>
      ))}
    </div>
  );
}

/* One move-log row, in Spender's structure: turn | name | action. `win`/`start` are
 * the review anchors ("X won the game" / "Game started"). */
export function LogEntry({ turn, name, action, clickable, selected, kind, future, onClick }) {
  const extra = kind === "win" ? " log-win" : kind === "start" ? " log-start" : "";
  return (
    <div className={`log-entry${clickable ? " clickable" : ""}${selected ? " log-selected" : ""}${future ? " future" : ""}${extra}`}
      onClick={onClick}>
      {kind ? null : <span className="log-turn">{turn ?? ""}</span>}
      {name ? <span className="log-name">{name}</span> : null}
      <span className="log-action">{action}</span>
    </div>
  );
}

/* Gems + jewel cards — extracted VERBATIM from Spender.jsx. Don't restyle for one
   game only: both import this. */
export const splendorCardCss = `
.gem-stack{display:flex;flex-direction:column;align-items:center;gap:4px;cursor:pointer;transition:transform .12s;user-select:none}
.gem-stack:hover .gem-token{transform:scale(1.08)}
.gem-stack.selected .gem-token{box-shadow:0 0 0 2px var(--gold-light),0 0 12px rgba(232,201,106,.3)}
.gem-stack.disabled{opacity:.35;cursor:not-allowed}
.gem-stack.reserve-ready .gem-token{box-shadow:0 0 0 2px var(--gold-light),0 0 14px rgba(232,201,106,.6);animation:reserve-pulse 1.1s ease-in-out infinite}
@keyframes reserve-pulse{0%,100%{box-shadow:0 0 0 2px var(--gold-light),0 0 8px rgba(232,201,106,.45)}50%{box-shadow:0 0 0 2px var(--gold-light),0 0 18px rgba(232,201,106,.85)}}
.gem-token{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;font-size:.95rem;border:2px solid rgba(255,255,255,.12);transition:all .12s}
.gem-count{font-size:.75rem;color:var(--text-dim);font-family:'Cinzel','Cinzel Fallback',serif}

/* ─── Cards ─────────────────────────────────────────────────────────────── */
/* overflow-x:auto clips both axes, which would cut off the hover lift / top border
   and the selection outline of the first & last items (flush at the clip edges).
   Padding on all sides + matching -margin gives clip-room without moving the row. */
.level-row{display:flex;gap:8px;align-items:flex-start;flex-wrap:nowrap;overflow-x:auto;padding:6px 4px 4px;margin:-6px -4px 0}
.level-row::-webkit-scrollbar{height:4px}.level-row::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.deck-pile{width:var(--card-w,88px);min-height:var(--card-h,120px);border-radius:var(--radius);border:1px dashed var(--border);display:flex;align-items:center;justify-content:center;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.68rem;color:var(--text-dim);cursor:pointer;flex-shrink:0;background:var(--surface2);transition:all .12s;flex-direction:column;gap:4px}
.deck-pile:hover{border-color:var(--gold);color:var(--gold)}
.deck-pile.selected{border-color:var(--gold-light);color:var(--gold-light);box-shadow:0 0 0 2px var(--gold-light)}
.deck-pile.disabled{cursor:not-allowed;opacity:.5}
.deck-remaining{font-size:1.3rem;font-weight:700;color:var(--text);font-family:'Cinzel','Cinzel Fallback',serif}
.card{width:var(--card-w,88px);min-height:var(--card-h,120px);border-radius:var(--radius);background:var(--surface2);border:1px solid var(--border);padding:8px 6px 6px;display:flex;flex-direction:column;cursor:pointer;transition:all .15s;flex-shrink:0;position:relative}
.card-slot{width:var(--card-w,88px);flex-shrink:0}
/* Each cell in a level row (deck pile / card / empty slot) shares the row width
   equally but never exceeds --card-w (88px default; bigger on desktop). A full
   level (deck + 4 cards) always fits the column width — no horizontal scroll or
   clipped card — at every size. */
.level-row>*{flex:1 1 0;min-width:0;max-width:var(--card-w,88px)}
.ai-val{position:absolute;bottom:5px;right:5px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;font-weight:600;color:#e8c86a;background:rgba(0,0,0,.4);border-radius:4px;padding:0 4px;line-height:1.4;pointer-events:none}
.ai-vals{position:absolute;bottom:3px;right:3px;display:grid;grid-template-columns:auto auto;gap:0 5px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.5rem;font-weight:600;color:#e8c86a;background:rgba(0,0,0,.5);border-radius:4px;padding:2px 4px;line-height:1.4;pointer-events:none}
.ai-vals b{color:#9a8fb0;font-weight:700;margin-right:1px}
/* "mine" = overlay computed for the player on the move (your turn) — tinted green to
   distinguish from the AI's own values (gold), since the overlay flips with the turn. */
.ai-vals.mine,.ai-val.mine{color:#8fdca0;box-shadow:0 0 0 1px rgba(143,220,160,.55)}
/* The "Show AI values" toggle sits at the far LEFT of the actions box (Take/Buy stay
   to its right); same gold styling as the action buttons via .btn.btn-gold. */
.ai-vals-toggle{margin-right:auto}
/* S's whole-position eval chip, shown beside the toggle when the overlay is on (S games only). */
.ai-pos-eval{display:inline-flex;align-items:center;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.72rem;font-weight:600;color:#e8c86a;background:rgba(0,0,0,.4);border:1px solid rgba(201,168,76,.4);border-radius:5px;padding:1px 7px;white-space:nowrap}
.ai-pos-eval.mine{color:#8fdca0;border-color:rgba(143,220,160,.5)}
.ai-pos-eval b{color:#9a8fb0;font-weight:700;margin-right:3px}
.ai-pos-eval-srch{margin-left:7px;padding-left:7px;border-left:1px solid rgba(201,168,76,.3)}
/* Pinned to the top-right of the actions box (absolute) so it never displaces the
   Target / buttons / hint. The box is position:relative (.actions-panel / .board-actions). */
.ai-pos-eval-row{position:absolute;top:7px;right:9px;display:flex;z-index:2}
.card:hover{border-color:rgba(201,168,76,.5);transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.4)}
.card.selected{border-color:var(--gold-light);box-shadow:0 0 0 2px var(--gold-light)}
.card.affordable{border-color:var(--green-gem)}
.card.affordable-gold{border-color:var(--gold-light)}
.card.disabled{cursor:not-allowed;opacity:.6}
.card-back{cursor:default;align-items:center;justify-content:center;gap:8px;border-style:dashed;background:repeating-linear-gradient(45deg,var(--surface2),var(--surface2) 6px,var(--surface) 6px,var(--surface) 12px)}
.card-back:hover{transform:none;border-color:var(--border);box-shadow:none}
.card-back-level{font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;font-size:1.3rem;color:var(--text-dim)}
.card-back-label{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.55rem;letter-spacing:.1em;color:var(--text-dim);text-transform:uppercase}
.card-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px}
.card-points{font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;font-size:1.1rem;color:var(--gold);min-width:16px}
.card-points.zero{color:transparent}
.card-bonus{width:20px;height:20px;border-radius:50%;flex-shrink:0;border:1.5px solid rgba(255,255,255,.25)}
.card-cost{display:flex;flex-direction:column;gap:3px;margin-top:auto}
.cost-row{display:flex;align-items:center;gap:4px}
.cost-gem{width:10px;height:10px;border-radius:50%;flex-shrink:0;border:1px solid rgba(255,255,255,.25)}
.cost-num{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.7rem;color:var(--text-dim)}
`;

/* Additions the shared CardView needs beyond Spender's originals: Duel's crowns, wild
   bonus, ability glyph and the pearl's second cost column, plus a `small` variant for
   reserve hands. Kept SEPARATE and applied after the verbatim block, so Spender's own
   rules keep both their content and their order — it simply never emits these. */
export const splendorCardExtraCss = `
.card-crowns{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;letter-spacing:-1px;color:var(--gold);margin:3px 3px 0 auto;white-space:nowrap;line-height:1}
.card-header .card-crowns+.card-bonus{margin-left:4px}
.card-bonus-wild{border-style:dashed}
.card-bonus-double{box-shadow:0 0 0 1.5px var(--surface2),0 0 0 3px rgba(255,255,255,.25)}
.card-ability{position:absolute;top:32px;right:6px;font-size:.7rem;color:var(--text);background:rgba(0,0,0,.35);border:1px solid var(--border);border-radius:4px;padding:0 3px;line-height:1.35;pointer-events:none}
.card-cost .cost-col{display:flex;flex-direction:column;gap:3px}
.card-cost.card-cost-2col{flex-direction:row;align-items:flex-end;gap:8px}
.card.card-small{width:var(--card-w-small,62px);min-height:var(--card-h-small,86px);padding:5px 4px 4px}
.card.card-small .card-points{font-size:.9rem}
.card.card-small .card-bonus{width:14px;height:14px}
.card.card-small .card-back-level{font-size:1rem}
`;

/* The move log — extracted VERBATIM from Spender.jsx. It already carries the review
   vocabulary (clickable rows, log-selected, log-win, log-start). */
export const splendorLogCss = `
/* ─── Move log ──────────────────────────────────────────────────────────── */
.move-log{display:flex;flex-direction:column;gap:0;max-height:200px;overflow-y:auto;overflow-x:hidden}
.log-empty{color:var(--text-muted);font-style:italic;font-size:.85rem;padding:4px 0}
.move-log::-webkit-scrollbar{width:3px}.move-log::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.log-entry{display:flex;gap:6px;align-items:baseline;font-size:.76rem;color:var(--text-dim);padding:4px 0;line-height:1.4;animation:log-in .2s ease}
.log-entry+.log-entry{border-top:1px solid rgba(58,52,42,.4)}
.log-entry:first-child{color:var(--text)}
.log-turn{flex:0 0 auto;min-width:1.6em;text-align:right;color:var(--text-muted);font-variant-numeric:tabular-nums;font-size:.92em}
.log-entry.clickable{cursor:pointer}
.log-entry.clickable:hover{background:rgba(201,168,76,.08);border-radius:4px}
/* Review: the turn currently shown on the board is highlighted in the log. */
.log-entry.log-selected{background:rgba(201,168,76,.2);border-radius:4px;box-shadow:inset 2px 0 0 var(--gold)}
/* "X won the game" marker at the top of a finished game's log. */
.log-entry.log-win .log-action{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.74rem;letter-spacing:.04em;color:var(--gold-light);font-weight:600}
/* "Game started" anchor at the bottom of the log (jumps to the initial board). */
.log-entry.log-start .log-action{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.72rem;letter-spacing:.04em;color:var(--text-dim)}
/* Review controls in the action bar: Prev / where / Next / Latest. */
.replay-nav{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.replay-where{font-size:.78rem;color:var(--text-dim);white-space:nowrap;max-width:220px;overflow:hidden;text-overflow:ellipsis}
.replay-move{color:var(--text-muted)}
.log-name{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.7rem;color:var(--gold-light);flex-shrink:0}
.log-action{flex:1}
`;
