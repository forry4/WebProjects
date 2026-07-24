# webapp

Minimal Vite + React wrapper (repo-root, neutral — not owned by any one game). This is the
**build harness only**; almost no application code lives here.

`main.jsx` mounts the site shell (`../games/spender/Spender.jsx`), and the actual UI is
**co-located with each feature's backend**, reached via relative imports — so if you're looking
for a game's UI, it's under `games/<game>/`, not here:

- **Game / shell UI:** `../games/*/*.jsx` — `Spender.jsx`, `CastlesOfCrimson.jsx`,
  `SpenderDuel.jsx`, `WhereWolf.jsx`
- **Books UI:** `../../books/Books.jsx`
- **Shared frontend kit:** `../../shared/` (`theme.js`, `lobby.jsx`, `splendor.jsx`, `router.js`)
- **Client-side WASM search cores + workers:** `public/wasm/` (built from the `rust-cores/*` crates)

## Run locally

```powershell
cd webapp
npm install
VITE_BASE=/ VITE_WS_URL=wss://splendid-nelz.onrender.com/ws npm run dev   # HMR vs prod backend
```

Open http://localhost:5173 (Vite **must** run on 5173 — the CORS allowlist only permits that
port). Smoke gate before pushing: `npm run smoke`. The production build is **CI-owned**
(`.github/workflows/deploy-pages.yml`) — never build or commit `dist/` by hand.
