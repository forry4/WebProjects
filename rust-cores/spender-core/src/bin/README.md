# spender-core/src/bin

**SERVING BRIDGE:** `move_server.rs` — the ONLY bin in the serving path (native counterpart of the
WASM the site's `spender-worker.js` runs).

**Everything else is OFFLINE** (benches, harvests, gates, parity — `bench`, `harvest*`, `gate_attn*`,
`simgate`, `rung1`/`rung2`, `selfgate_endgame`, `net_bench`, `score_bench`, `net_export_check`,
`attn_parity`, `verify_opt`). Run manually with `--features bridge`; NOT built by CI, never served.
