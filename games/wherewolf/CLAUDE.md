# Where Wolf? (One Night Ultimate Werewolf) — package notes

Real-time social deduction, 3–10 players, one device each. Mounted at `/werewolf`. LIVE on prod.
**No AI** — humans only. See the root `CLAUDE.md` for the room-server invariants and deploy.

---

## Engine model (`engine.py` — single source of truth)

- **`dealt_role` is the role you PERFORM all night (immutable); `card` is your FINAL role (swappable).**
  Whatever card sits in front of you when night ends IS your final role. The WIN uses FINAL cards.
- **`player_view(game, pid)` is the hidden-information boundary** — a per-recipient redaction; a client is
  only ever sent cards it may see this phase (everything else is literally `None` in the payload).
  Redaction matrix (do not regress): werewolves see each other; **minion sees the wolves but wolves do NOT
  see the minion (asymmetric)**; masons see each other; seer sees the peek; **drunk sees NOTHING of its own
  (blind swap)**; lone wolf's center peek is private. Self-target rejected for robber/seer/troublemaker.
- **Voting is MULTI-DEATH** (`resolve_votes`): most-voted die; a tie for most → all tied die; nobody ≥2
  votes → no one dies. Hunter: a dead hunter also kills whom they voted (cycle-guarded).
- **Win (the load-bearing care points):** ≥1 **werewolf CARD** dies → village; else wolf-in-play + none died
  → wolves; no wolf in play → village iff nobody died. **Killing the MINION is NOT a werewolf death.** A
  **tanner death with no werewolf death suppresses the wolf win** (only the tanner wins).
- JSON-safe + reconnect-safe (all collections are lists).
- **NO `rng_state` IS PERSISTED, and that is deliberate.** Unlike CoC/Duel, WW spends all its
  randomness at setup — `new_game` builds the deck and shuffles, and nothing afterwards draws (the
  night steps and the vote are pure functions of player choices). Persisting the state meant every
  row carried 625 words of Mersenne noise nothing read: **89.5% of the stored blob** (5,350 → 562
  bytes), and incompressible, so it dominated the row even after zlib. `_load_rng`/`_save_rng` are
  kept but uncalled. **If you add randomness after setup, re-arm them around it** or that draw
  silently stops being reproducible across a save/reconnect —
  `tests/test_rng_not_persisted.py` plays a whole game with the stdlib RNG booby-trapped and fails
  the moment anything draws, so the trap can't reopen quietly. `main.load_game_to_memory` also drops
  the key from legacy rows so they shrink on their next save.
- Pending sub-decision state is `night_step` (a real game-state key, server-enforced).

---

## Night conductor + host picker

- `_run_night` iterates `roles.NIGHT_ORDER` keyed on **deck presence** — every role in the deck is
  announced even if entirely in the center (silence can't leak which roles are out). Each step is a
  **fixed-duration window** (no early-advance, no per-step Event → uniform timing → leak-free).
- **Lone-wolf no-leak (do not regress):** the werewolves step ALWAYS uses the action window and ALWAYS
  narrates the conditional lone-wolf line, so a 1-wolf and 2-wolf game look/sound identical.
- Host picks the deck in the lobby via `set_roles` → `roles.validate_deck(deck, n, partial=True)` (the
  `partial` flag skips only the exact-count check so an in-progress selection broadcasts live). Full
  re-validation at deal, silently falling back to `recommended_deck(n)`.
- Doppelgänger is deferred (in the deck data but excluded from the picker + `validate_deck`).

---

## Frontend + deploy

- Circle seating (you at 6 o'clock); mobile reshapes into a tall ellipse; SVG vote-arrows; browser TTS
  narration + caption; auto-reconnect. WW has **no "Abandon"** (leaving just returns to lobby).
- **WS identity is bound server-side** (a hardening fix — was a hidden-role compromise). Launched to prod
  by a **selective frontend add**, not a `staging→main` push (staging had a stale WW backend — never
  blind-push staging; see the root Footguns).

---

## Tests

`tests/` (~73: deck validation, every night action, the win-condition matrix, the `player_view` redaction
matrix) + `test_ws_auth.py`.
