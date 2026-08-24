# coc-core/src/bin

**SERVING BRIDGE:** `move_server_coc.rs` — the ONLY bin in the serving path. The site's CoC worker
(`webapp/public/wasm/coc-worker.js`) talks to the WASM built from `src/lib.rs`/`wasm.rs`; this native
`move_server_coc` bin is the offline arena/gate counterpart that runs the same search natively.

**Everything else is OFFLINE** (arenas, gates, harvests, benches, audits — `gate_coc`, `harvest_*`,
`bench_*`, `*_arena`, `firstplayer_*`, `endgame_*`, `m6_arena`, `ship_timing_arena`, `storage_arena`,
`denial_probe`, `tile_audit`, `*_export_check`). Run manually with `--features bridge`; NOT built by CI,
never served.
