# Forrest Games

A full-stack, real-time board-game website — four multiplayer games plus site
features — built on **one** FastAPI backend, **one** React shell, and a shared
auth/persistence platform. Live at **https://forry4.github.io/**.

The interesting engineering is in three places: a **server-authoritative real-time architecture** over WebSockets, a set of **game AIs** that range from
hand-built heuristics to AlphaZero-style neural nets, and a **Rust→WASM inference core** that ships those nets into the player's browser so search runs ~1000× faster than it could on a free-tier server using Python.

---

## Highlights (for the impatient reviewer)

- **Real-time, server-authoritative multiplayer.** Every move is validated by a
  pure game engine on the server; clients only render and propose. One uvicorn
  process holds all rooms in memory under a single lock, with reconnect tokens,
  per-recipient hidden-information redaction, and a save/load layer that survives
  cold starts.
- **A genuine AI/ML campaign.** Determinized MCTS/PUCT search,
  hand-tuned heuristics, and **learned value/policy nets trained offline in PyTorch**
  — including a card-set **attention** network — selected by paired, equal-time
  arenas and rigorous ablation methodology. The findings (what moved strength, what
  saturated, what was noise) are written up in a 
  [research log](docs/ai-research-log.md).
- **Rust→WASM model serving.** The search cores for three games are ported to Rust,
  compiled to WebAssembly, and run client-side — validated **bit-for-bit** against
  the Python reference via differential parity tests. The server stays a cheap
  validator; the heavy compute runs on the user's machine.
- **Reliability treated as a first-class concern.** The codebase carries documented
  postmortems: an event-loop outage from running sync work under a lock, a libSQL
  driver quirk that silently dropped admin rights, CORS misconfigurations, cache
  footguns. Each fix is locked in by tests and notes.
- **Layered, dependency-directed backend.** `core/` (DB + auth + config) depends on
  nothing; each game is a self-contained feature; a composition root wires them.
  This deliberately broke a legacy circular-import knot.

---

## The games

| Game | What it is | Players | AI |
|------|-----------|---------|----|
| **Spender** | a faithful port of the Splendor gem-trading / prestige race game | 2–4 (vs-AI is 2p) | heuristics → determinized PUCT → **attention value net** (client-WASM, ~20k sims/move) |
| **Castles of Crimson** | a faithful port of the Castles of Burgundy dice-and-tile euro | 2–4 | determinized-MCTS bot; two neural champions served via WASM |
| **Spender Duel** | the 2-player Splendor variant (hidden reserves, privileges, crowns) | 2 | MCTS with a card-set attention value-net leaf (ported to Rust→WASM) |
| **Where Wolf?** | a One Night Ultimate Werewolf-style social-deduction party game | 3–10 | none — a timed "night conductor" and leak-free hidden roles instead |

Plus two site features: **Books** (a public book ranking + reading suggestions) and
**Puzzles** (auto-generated single-best-move Spender positions, verified offline by
re-searching every alternative). A separate **WWSD** service is a browser autoplayer
for an alternative Splendor site.

All four games and both features are **live in production**.

---

## Tech stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI + asyncio, one uvicorn process; WebSockets for realtime |
| Persistence | SQLite locally / **Turso (libSQL)** in prod, behind one driver-agnostic wrapper with a boot-time self-test + local fallback |
| Frontend | React 18, plain JS, Vite 6 — one self-contained component per game, one shared shell |
| AI (search) | determinized MCTS / PUCT; hand-built heuristics |
| AI (learned) | AlphaZero-style policy+value nets and card-set **attention** nets, **trained in PyTorch offline**, served client-side |
| Model serving | **Rust → WebAssembly** (`wasm-pack`), parity-checked against the Python engine |
| Auth/security | session + per-room reconnect tokens (CSPRNG), PBKDF2 passwords, in-process rate limiting, security-headers middleware |
| CI/CD | GitHub Actions (frontend build + smoke gate), Render (backend, test-gated), Cloudflare Worker (staging mirror) |

---

## Why the architecture is shaped the way it is

**Server is authoritative for all game state.** Clients render and send moves; the
server validates every move through a pure `engine.py` before applying it. This is
what makes client-side AI safe: a tampered client only weakens *its own* opponent,
because the proposed move is still validated server-side. It's also what makes the
AI *correct* — the AI holds the true game dict, so it must **determinize** (resample
everything it can't legally see: decks, blind reserves, future dice) before
searching, so the search provably can't read hidden order.

**Hidden information is a real boundary, not a UI convention.** Each game computes a
per-recipient view (`player_view`) and broadcasts redacted state — a Werewolf client
is only ever *sent* the cards it may see this phase; a Duel opponent's reserves
arrive as `{level, facedown}`. Reconnect and save/load go through the same redaction.

**Heavy work never blocks the event loop.** AI turns snapshot state under the lock,
release it, run search in a thread pool, then re-lock, re-validate that the turn
hasn't changed, and apply. (This pattern exists because an earlier version that ran
sync engine work under the lock took production down — the postmortem is in the
code.)

**The backend is layered so features can't entangle.** `core/` depends on nothing;
games and Books depend only on `core/`; `app.py` is the composition root that wires
everything and applies cross-cutting middleware. Books is wired by dependency
injection specifically so a site feature never imports a game.

---

## The AI, in one paragraph

Every game's AI subtracts two same-eval seat scores so that *denial* falls out of
search for free (no special-cased "block the opponent" logic). The consistent lesson
across dozens of offline experiments — captured in the [research log](docs/ai-research-log.md)
— is that **search depth (simulations/move) is the dominant strength lever**, and
that static-eval re-weighting saturates fast. That's what motivated the Rust→WASM
port: moving inference into the browser buys ~1000× more simulations per move on
the same free hosting. The learned nets (an AlphaZero-style policy+value net for
Spender, a card-set **attention** value net for Spender Duel) were each shipped only
after beating the prior champion in **equal-time**, paired-seed arenas — and the log
is equally explicit about the experiments that *didn't* work, and why.

---

## Repository layout

```
app.py                 # composition root: FastAPI app + CORS/security middleware + feature wiring
core/                  # shared backend platform (DB, auth, rate limiting, config) — imports no game
games/
  spender/             # Spender: engine + room server + the full AI stack (ai/, ai/az/)
  castles_of_crimson/  # Castles of Crimson: engine + bot + AI serving
  wherewolf/           # Where Wolf?: engine (night conductor, redaction) + room server
  spender_duel/        # Spender Duel: engine + bot + AI serving
books/                 # Books site feature (wired via dependency injection)
shared/                # cross-game frontend kits (theme, lobby, shared card/gem components)
webapp/                # Vite + React build — the shell that mounts every feature
spender-core/          # Rust → WASM: Spender search core (client-side inference)
coc-core/              # Rust → WASM: Castles of Crimson search core
duel-core/             # Rust → WASM: Spender Duel search core
wwsd/                  # standalone browser autoplayer for a friend's external site
docs/                  # GitHub Pages build output (CI-owned) + ai-research-log.md
```

---

## Testing

Rules/engine unit tests are the most valuable asset here and are protected
accordingly — each game has an engine test suite covering board invariants,
move legality, scoring, lifecycle, and (for the hidden-info games) the full
redaction matrix and win-condition matrix. Beyond that:

- **Python↔Rust differential parity** — generated fixtures are replayed through both
  the Python engine and the Rust/WASM core; they must match bit-for-bit. This is what
  makes it safe to serve a Rust port of the "real" engine to browsers.
- **Token/state conservation soak tests** — e.g. Spender Duel asserts an exact 25-token
  multiset across board + bag + hands after every move in bot-vs-bot games.
- **CI gates deploys** — the backend deploy on Render is gated on the test suite; the
  frontend deploy is gated on a headless smoke test that fails on a blank page or a
  layout shift.

```bash
python -m pytest              # backend: engines, AI, core (auth/db/ratelimit), books
cd webapp && npm run smoke    # frontend: builds + headless-loads, fails on a blank page
```

---

## Local development

Backend — the composition root serves the whole site (every game and feature):

```bash
pip install -r games/spender/requirements.txt
python -m uvicorn app:app --reload --port 8000
# health check: http://127.0.0.1:8000/health
```

Frontend — Vite dev server on port 5173 (the backend's CORS allowlist expects it):

```bash
cd webapp
npm install
npm run dev
```

---

## Deployment

- **Frontend** → GitHub Pages at https://forry4.github.io/. GitHub Actions builds
  `webapp/`, runs the smoke gate, and publishes on every push to `main` touching the
  frontend. The build is CI-owned — the committed source is never hand-built.
- **Backend** → Render — one web service hosts every game and feature; auto-deploys
  on push to `main`, gated on tests. Prod persistence is Turso (libSQL); Render's
  filesystem is ephemeral.
- **Staging** → a Cloudflare Worker mirrors the frontend from the `staging` branch
  (reusing the prod backend) so UI/layout changes can be validated on a real URL
  before shipping.

---

## More

[`CLAUDE.md`](CLAUDE.md) is the detailed engineering operating manual — architecture
decisions, invariants, and the hard-won "do not regress" notes for each subsystem.
[`docs/ai-research-log.md`](docs/ai-research-log.md) is the full AI campaign history:
what was tried, what shipped, and the rejected-experiment postmortems.
