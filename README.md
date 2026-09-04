# Forrest Games

Eight real-time multiplayer board games and four site features, on **one** FastAPI
backend, **one** React shell, and a shared auth/persistence platform.
Live at **https://forry4.github.io/**.

Three parts are worth a reviewer's time: a **server-authoritative realtime
architecture** over WebSockets, **per-game AIs** ranging from hand-built heuristics
to learned nets, and a **Rust→WASM inference path** that runs those nets in the
player's browser, so search strength isn't capped by a free-tier server.

---

## The games

| Game | What it is | Players | Opponent |
|---|---|---|---|
| **Spender** | Splendor — gem trading, prestige race | 1–4 | heuristics → determinized PUCT → a learned value net served client-side |
| **Castles of Crimson** | Castles of Burgundy — dice and tile placement | 1–4 | determinized MCTS; the Expert tier is a net served via WASM |
| **Spender Duel** | Splendor Duel — hidden reserves, privileges, crowns | 1–2 | MCTS with a card-set **attention** value-net leaf (Rust→WASM) |
| **Where Wolf?** | One Night Ultimate Werewolf — social deduction | 3–10 | none by design: a timed night conductor and leak-free roles |
| **Dontminion** | Dominion — 12 sets, 368 cards + 114 landscape cards | 1–4 | heuristic bots, several to a room |
| **Dissonance** | a 2-player parity trick-taker, in five modes | 1–2 | PIMC / double-dummy search, served in the browser |
| **Rag Tag** | Tag Team — a simultaneous auto-battler; the deck is never shuffled | 1–2 | random, deliberately: v1 exists to make the game playtestable |
| **Orbit** | Zenith (2025) — move five planets' discs to control the solar system | 1–2 | random, same as Rag Tag — a first playable release |

Plus **Books** (ranking + reading suggestions), **Spender Puzzles** (late-game
positions harvested from self-play and kept only where a forced win exists, the
line is unique at every decision, and the greedy move does *not* find it), **BGG
Filter** (a BoardGameGeek harvest behind a frontend-only filter page), and an
**offline hub** where four of the games run with no server at all — wasm engine,
IndexedDB saves. **WWSD** is a separate browser autoplayer for a friend's external
Splendor site.

Everything above is live in production.

---

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI + asyncio, one uvicorn process; WebSockets for realtime |
| Persistence | SQLite locally / **Turso (libSQL)** in prod, behind one driver-agnostic wrapper with a boot-time self-test and local fallback |
| Frontend | React 18, plain JS, Vite 6 — one self-contained component per game on a shared shell and kit |
| AI (search) | determinized MCTS / PUCT, PIMC, hand-built heuristics |
| AI (learned) | AlphaZero-style policy+value nets and card-set **attention** nets, trained offline in PyTorch, served client-side |
| Model serving | **Rust → WebAssembly** (`wasm-pack`), parity-checked against the Python engine |
| Auth | session + per-room reconnect tokens (CSPRNG), PBKDF2 passwords, in-process rate limiting, security-headers middleware |
| CI/CD | GitHub Actions (frontend build + two render gates), Render (backend, test-gated), Cloudflare Worker (staging mirror) |

---

## How it fits together

**The server is authoritative.** Clients render and propose; a pure `engine.py`
validates every move before it applies. That is what makes client-side AI safe — a
tampered client only weakens its own opponent. It is also what makes the AI
*correct*: the search holds the true game dict, so it must **determinize**
(resample decks, blind reserves, future dice) before searching, and provably cannot
read hidden order.

**Hidden information is a boundary, not a UI convention.** Each game builds a
per-recipient view and broadcasts redacted state — a Werewolf client is only ever
*sent* the cards it may see this phase; a Duel opponent's reserves arrive as
`{level, facedown}`. Reconnect and save/load go through the same redaction, and
each socket must prove it owns its seat before it can act as one or be sent its view.

**Heavy work never blocks the event loop.** An AI turn snapshots state under the
room lock, releases it, searches in a thread pool, then re-locks, re-validates that
the turn hasn't changed, and applies. That shape exists because an earlier version
that ran sync engine work under the lock took production down.

**The backend is layered so features can't entangle.** `core/` depends on nothing;
each game and Books depends only on `core/`; `app.py` is the composition root that
wires them and applies cross-cutting middleware. This deliberately broke a legacy
circular-import knot, and the direction is one-way in the frontend too — games
import `shared/`, never the reverse.

---

## Layout

```
app.py                 # composition root: FastAPI app + middleware + feature wiring
core/                  # shared backend platform (DB, auth, rooms, rate limiting) — imports no game
games/<game>/          # engine.py (the rules) + main.py (rooms/WS/REST) + <Game>.jsx + tests/
                       #   spender, castles_of_crimson, wherewolf, spender_duel,
                       #   dontminion, dissonance, rag_tag, orbit
books/  bggfilter/     # site features
shared/                # cross-game frontend kits: theme, lobby, rules modal, shell screens
webapp/                # Vite + React build; test/smoke.mjs + test/screens.mjs are the deploy gates
rust-cores/            # per-game Rust → WASM search crates (spender, coc, duel, dissonance)
wwsd/                  # standalone browser autoplayer for an external site
docs/                  # rollback copy of the Pages build + ai-research-log.md
```

---

## Testing

Rules/engine unit tests are the most valuable asset here and are protected
accordingly: every game has one covering board invariants, move legality, scoring
and lifecycle, plus — for the hidden-info games — the full redaction and
win-condition matrices. The suite is defined once in `pytest.ini` and runs in
parallel. Beyond that:

- **Python↔Rust differential parity.** Generated fixtures are replayed through both
  the Python engine and the Rust/WASM core and must match exactly. This is what
  makes it safe to serve a Rust port of the real engine to browsers.
- **Conservation soaks.** Spender Duel asserts an exact 25-token multiset across
  board, bag and hands after every move of bot-vs-bot games; Dontminion replays
  production saves as its migration gate.
- **No state-reachability skips, repo-wide,** mechanically enforced: a test that
  can't reach the state it means to exercise must fail, not opt out.
- **Deploys are gated.** Render runs the Python suite; Pages runs `smoke` (blank
  page / layout shift) and `screens`, which boots the real backend and drives every
  game route in a browser. `smoke` never renders a game — only `screens` does.

```bash
python -m pytest                # backend: engines, AI, core, kits, books
cd webapp && npm run smoke      # frontend: builds + headless-loads
cd webapp && npm run screens    # frontend: real render gate, against a live backend
```

---

## Local development

```bash
pip install -r games/spender/requirements.txt
python -m uvicorn app:app --reload --port 8000     # serves every game and feature
# health: http://127.0.0.1:8000/health

cd webapp && npm install && npm run dev            # MUST be port 5173 — the CORS allowlist
```

Two local players need two *browser profiles*: separate windows share
`localStorage`, so they collapse into one identity.

---

## Deployment

- **Frontend** → GitHub Pages. Actions builds `webapp/`, runs both gates, and
  publishes on every push to `main` touching the frontend. The build is CI-owned —
  never hand-built or committed.
- **Backend** → Render, one web service for everything, auto-deployed on push to
  `main` and gated on tests. The deploy job polls `/health` for the pushed commit,
  because the deploy hook returning 200 only means Render accepted the request.
- **Staging** → a Cloudflare Worker mirrors the `staging` branch against the prod
  backend, so layout changes can be checked on a real URL first.

---

## More

[`CLAUDE.md`](CLAUDE.md) is the engineering operating manual — architecture
decisions, invariants, and the "do not regress" notes for each subsystem, with a
per-area `CLAUDE.md` next to each game.
[`docs/ai-research-log.md`](docs/ai-research-log.md) is the AI campaign history:
what shipped, what saturated, and the rejected-experiment postmortems.
