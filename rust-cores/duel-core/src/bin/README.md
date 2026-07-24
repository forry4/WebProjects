# duel-core/src/bin

**SERVING BRIDGE:** `move_server.rs` — the ONLY bin in the serving path (native counterpart of the
WASM the site's `duel-worker.js` runs).

**Everything else is OFFLINE** (harvests, gates, benches, parity — `harvest_*`, `gate_*`, `attn_bench`,
`bench_leaf`, `featurize_positions`, `endgame_diag`, `*_parity`). Run manually with `--features bridge`;
NOT built by CI, never served.
