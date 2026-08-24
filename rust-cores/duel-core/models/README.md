# duel-core net models — manifest

Which net blob is which, so "is this the live one?" is never a guess.

## Served (embedded in the WASM)

- **`../src/attn_value_net.json`** — the **LIVE** Hard-tier leaf. Embedded into the WASM at build
  time via `include_str!` in `src/wasm.rs`. This is the card-set **attention value net, v2**
  (byte-identical to `archive/attn_value_net_v2.json`; shipped `3d0cecb`).

## Offline-only nets in `../src/` (NOT served — used by tooling)

- **`../src/value_net.json`** — the earlier MLP value net; loaded by the cross-impl arena/gate
  bins (`bin/{move_server,bench_leaf,gate_netleaf}.rs`) and `valuenet.rs` tests, not the WASM.
- **`../src/pv_net.json`** — the policy+value net line; the default `--net`/`--out` for
  `tools/{train_pv,eval_pv_coverage}.py`. Not served (the WASM embeds the attention net).

## Archive (historical snapshots, not built or served)

- **`archive/attn_value_net_v1_shipped.json`** — the FIRST shipped attention leaf (`e4b2c06`);
  beat the hand heuristic 0.62. Superseded by v2.
- **`archive/attn_value_net_v2.json`** — the current LIVE net (== `../src/attn_value_net.json`).
  Kept as a stable v2 record for when the live net advances past v2.
- **`archive/attn_value_net_v3.json`** — the larger-data v3 retrain; overfit, **did not ship**
  (see `docs/ai-research-log.md`). Kept as a record.

**Upgrading the live net:** replace `../src/attn_value_net.json` with the winner, snapshot the
outgoing one into `archive/` under its version, rebuild the WASM (`wasm-pack …`), and update the
"LIVE" line above.
