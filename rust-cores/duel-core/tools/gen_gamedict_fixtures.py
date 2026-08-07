"""Generate offline-surface parity fixtures: player_view + compact.project + log events.

The engine fixtures (`gen_engine_fixtures.py`) prove the RULES port; this proves the
OFFLINE SERVING surface around it — the three writers the browser depends on when it is
the authority:

  - `gamedict::to_player_view`  vs  `engine.player_view(game, pid)`   (render redaction)
  - `gamedict::to_proj`         vs  `compact.project(game, pid)`      (search redaction)
  - `gamedict::synth_events`    vs  the log delta `engine.apply_move` appended

Replay machinery (SpyRng fill scripting, setup encoding, enc_move) is imported from
gen_engine_fixtures so the two corpora can never drift in schema. Views are SAMPLED
(every pending, every k-th move, game start/over — they're big); the log delta rides on
EVERY move (events are where a diff-based synthesizer drifts).

    PYTHONPATH=<repo root> python rust-cores/duel-core/tools/gen_gamedict_fixtures.py

Writes rust-cores/duel-core/fixtures/gamedict_fixtures.jsonl (gitignored — regenerate
on demand; the Rust gate names this file in its failure message).
"""
import argparse
import copy
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

from games.spender_duel import bot, compact, engine  # noqa: E402
import gen_engine_fixtures as gef  # noqa: E402

A, B = gef.A, gef.B


def views_of(g):
    """player_view for both seats + spectator, log stripped (the Rust writer emits []
    because the offline driver owns the log — same policy as the other games)."""
    out = []
    for pid in (A, B, None):
        v = engine.player_view(g, pid)
        v["log"] = []
        out.append(v)
    return out


def record_views(g):
    return {
        "views": views_of(g),
        "projs": [compact.project(g, A), compact.project(g, B)],
    }


def play(seed: int, sample_every: int, max_moves: int = 4000, loaded: bool = False) -> dict:
    fills: list = []
    orig_fill = engine._fill_board
    engine._fill_board = lambda game, rng: orig_fill(game, gef._SpyRng(rng, fills))
    try:
        g = engine.new_game([A, B], seed=seed)
        setup = gef.setup_of(g)
        setup_fills = list(fills)
        views0 = record_views(g)
        fills.clear()
        rng = random.Random(seed + 7919)
        pick = gef._pick_loaded if loaded else bot.choose
        moves = []
        for step in range(max_moves):
            if engine.is_over(g):
                break
            actor = g.get("pending_pid") or g["turn"]
            mv = pick(g, actor, rng)
            if mv is None:
                break
            fills.clear()
            log_len = len(g["log"])
            ok, err = engine.apply_move(g, actor, mv)
            assert ok, (mv, err)
            rec = {
                "actor": g["order"].index(actor),
                "mv": gef.enc_move(mv),
                "fills": list(fills),
                # deep copy — log entries are live dicts in the mutating game
                "events": copy.deepcopy(g["log"][log_len:]),
            }
            pending = g["pending_pid"] is not None
            if pending or step % sample_every == 0 or engine.is_over(g):
                rec.update(record_views(g))
            moves.append(rec)
    finally:
        engine._fill_board = orig_fill
    return {"seed": seed, "setup": setup, "setup_fills": setup_fills,
            "views0": views0, "moves": moves}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=60, help="tiered-bot games")
    ap.add_argument("--loaded", type=int, default=40,
                    help="uniform-random games (reach skip_pending/use_privilege etc.)")
    ap.add_argument("--sample-every", type=int, default=17)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "fixtures"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    dst = os.path.join(args.out, "gamedict_fixtures.jsonl")
    n_moves = n_views = n_pending = 0
    kinds = {}
    with open(dst, "w") as f:
        for i in range(args.games + args.loaded):
            loaded = i >= args.games
            fx = play((2_000_000 + i) if loaded else i, args.sample_every, loaded=loaded)
            n_moves += len(fx["moves"])
            for m in fx["moves"]:
                kinds[m["mv"]["t"]] = kinds.get(m["mv"]["t"], 0) + 1
                if "views" in m:
                    n_views += 1
                for e in m["events"]:
                    kinds["ev:" + e["type"]] = kinds.get("ev:" + e["type"], 0) + 1
            n_pending += sum(1 for m in fx["moves"]
                             if "views" in m and m["views"][0]["pending_kind"])
            f.write(json.dumps(fx) + "\n")
    print(f"wrote {os.path.normpath(dst)}: {args.games + args.loaded} games, "
          f"{n_moves} moves, {n_views} sampled view-positions ({n_pending} pending)")
    print("coverage: " + "  ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    # The corpus must exercise every move type AND every log/event type, or the gate is
    # silently blind to one (repo policy: fail loud, never skip).
    need_mv = gef.REQUIRED
    need_ev = {"take", "reserve", "buy", "replenish", "use_privilege", "take_same",
               "steal", "royal", "discard", "skip_pending", "again", "privilege_gain",
               "extra_turn", "game_over"}
    missing = sorted(need_mv - {k for k in kinds if not k.startswith("ev:")}) + \
        sorted("ev:" + e for e in need_ev if "ev:" + e not in kinds)
    if missing:
        raise SystemExit(f"FATAL: corpus never exercises {missing} — raise --loaded/--games.")
    # Pending-phase VIEWS specifically: pending ctx is where a view writer drifts.
    if n_pending == 0:
        raise SystemExit("FATAL: no pending-phase view sampled — the ctx writer is untested.")


if __name__ == "__main__":
    main()
