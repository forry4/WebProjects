# coc-core/tools — offline ML tooling (Python trainers + shell orchestration chains)

None of this is served or built by CI. It's the offline campaign toolkit for the CoC netval/
attention nets. Every `.sh` chain has a header comment describing exactly what it does — read that
first; this file is just the map.

## Python

- `pv_net.py`, `attn_net.py` — the net definitions (PV / attention); PyTorch twins of `src/*.rs`.
- `train_pv.py`, `train_pv_exp.py`, `train_attn.py` — training entry points.
- `warmstart_4animal.py` — seed a net for the 4-animal (chicken) board expansion.
- `gpu_server.py` — batched GPU eval server used by the harvest bins.
- `pv_json_to_bin.py` — convert a trained `<net>.json` → `webapp/public/wasm/coc_pv_model.bin`
  (the model-swap step; no wasm rebuild needed).
- `gen_engine_fixtures.py`, `gen_value_fixtures.py`, `gen_board_tables.py` — parity fixtures /
  generated tables (see the crate's `tests/`).

## Shell chains (`.sh`) — long-running self-play → train → gate → ratchet loops

Naming taxonomy (the header comment in each file is authoritative):
- `loop_coc*.sh` — one self-play→train→paired-CRN-gate→greedy-ratchet loop. The suffix is the net
  line/config: `_attn`/`_attn2` (attention escalation), `_hs`/`_hs2` (hybrid self-play), `_v2`,
  `_r2` (rung-2 combined campaign), `_big`, `_aux` (aux-head), `_netval`.
- `*_chain.sh` — bootstrap that seeds an anchor harvest, then hands off to a `loop_*` (e.g.
  `attn2_chain.sh` → `loop_coc_attn2.sh`; `corpus2_chain.sh`, `ctl_aux0_chain.sh`, `epoch_traj_chain.sh`,
  `stg_chain.sh`).
- `*_aux.sh` — aux-head (card/region margin) harvest/train orchestration (`harvest_aux.sh`,
  `big_aux.sh`, `overnight_aux.sh`, `rerun_aux_gates.sh`).
- `ext_then_loop.sh`, `fresh_bootstrap.sh` — one-shot bootstrap/extend helpers.

Sibling note: the analogous (but game-specific) trainers live in `../../duel-core/tools/` and
`../../spender-core/tools/`; the feature encoders differ per game, so they are intentionally NOT shared.
