"""Generate differential-parity fixtures: engine.py games replayed by coc-core.

Drives biased-random self-play through the AUTHORITATIVE Python engine and records,
per move: the compact move (bridge.move_to_compact), any dice rolled by the move
(injected into the Rust replay via State.dice_script — sidesteps the Mersenne/
splitmix RNG mismatch), and the FNV-64 hash of the canonical projection string
after the move (compact.proj_hash). Every K-th position (and every pending-decision
position) also records the FULL legal-move set as compact moves — the Rust test
walks these as a micro-action trie and asserts set equality per node, which is what
proves the 102-action decomposition equals engine.legal_moves in both directions.

Coverage counters (manifest.json) prove the fixture set actually exercises every
rule: all 26 monastery effects placed + trigger proxies, every pending kind + skip,
adjust refunds, black buys, m6, color-bonus first/second, all 9 boards both seats,
winner tiebreak branches. "Loaded" scenario games (players granted broad monastery
effects + resources) backfill the rare paths random play misses.

Run:  python coc-core/tools/gen_engine_fixtures.py --games 2000 --loaded 300
Output: coc-core/tests/fixtures/games.jsonl + manifest.json  (gitignored)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)

from games.castles_of_crimson import engine, tiles  # noqa: E402
from games.castles_of_crimson.ai.az import bridge, compact  # noqa: E402

PIDS = ["P0", "P1"]

# Move-type sampling weights (development-biased; epsilon-uniform keeps rare heads alive).
PRI = {
    "place_tile": 5.0, "townhall_place": 5.0,
    "extra_action": 4.0, "building_take_choice": 4.0, "ship_take_goods": 4.0,
    "ship_adjacent_take": 4.0, "goods_pick": 4.0, "warehouse_sell": 4.0,
    "take_hex": 3.0, "sell_goods": 3.0,
    "buy_black": 2.2, "monastery6_take": 2.2,
    "adjust_die": 1.4, "take_workers": 1.0,
    "discard_storage": 0.6, "skip_pending": 0.3, "end_turn": 0.25,
    "place_starting_castle": 1.0,
}
EPSILON = 0.12


def _actor(game):
    return game["pending_pid"] or game["turn"]


def _pick_move(rng, moves):
    if rng.random() < EPSILON:
        return rng.choice(moves)
    weights = [PRI.get(m["type"], 1.0) for m in moves]
    return rng.choices(moves, weights=weights, k=1)[0]


def _round_key(game):
    return (game["phase"], game["phase_letter"], game.get("round_in_game"))


def _dice_after_round_start(game):
    """The 5 rolls _begin_round made, in roll order (seat order d0 d1, then white)."""
    out = []
    for pid in game["order"]:
        d = game["dice"][pid]
        out += [d["orig"][0], d["orig"][1]]
    out.append(game["white_die"])
    return out


def _tile_type_of_move(game, pid, move):
    """Tile type a place-like move places (for coverage), or None."""
    p = game["players"][pid]
    tid = None
    if move["type"] in ("place_tile", "townhall_place"):
        tid = move.get("tile_id")
    elif move["type"] == "extra_action" and (move.get("sub") or {}).get("type") == "place_tile":
        tid = move["sub"]["tile_id"]
    if tid is None:
        return None
    for t in p["storage"]:
        if t["id"] == tid:
            return t
    return None


def _apply_loadout(game, rng):
    """Grant both players a broad effect kit + resources so rare rules exercise.
    Engine-consistent: effects/resources are authoritative state; tiles moved into
    storage come out of the real supply so ids stay unique."""
    for pid in PIDS:
        p = game["players"][pid]
        eids = rng.sample(range(1, 27), k=rng.randint(6, 14))
        p["monastery_effects"] = sorted(set(eids))
        p["workers"] += rng.randint(2, 8)
        p["silver"] += rng.randint(2, 6)
        p["mines_count"] += rng.randint(0, 2)
        # a couple of tiles straight into storage (ships/buildings bias the chains)
        want = rng.sample(["ship", "ship", "building", "castle", "livestock", "monastery"],
                          k=rng.randint(1, 3))
        for ttype in want:
            if len(p["storage"]) >= 3:
                break
            t = engine._draw_type(game["supply"], ttype)
            if t is not None:
                p["storage"].append(t)
        # sold goods so endgame monasteries 15/25 score
        for _ in range(rng.randint(0, 4)):
            p["sold_goods"].append(rng.choice(tiles.GOODS_COLORS))


def play_game(seed, boards, cov, loaded=False, legal_every=7):
    rng = random.Random(seed ^ 0xF1C7)
    game = engine.new_game(PIDS, seed=seed, boards={"P0": boards[0], "P1": boards[1]})
    if loaded:
        _apply_loadout(game, rng)

    rec = {
        "seed": seed,
        "boards": boards,
        "loaded": loaded,
        "init": compact.project(game),
        "ih": compact.proj_hash(game),
        "moves": [],
    }
    cov["board_seat0_" + boards[0]] += 1
    cov["board_seat1_" + boards[1]] += 1

    step = 0
    while not engine.is_over(game):
        pid = _actor(game)
        moves = engine.legal_moves(game, pid)
        assert moves, f"no legal moves (seed {seed} step {step})"
        move = _pick_move(rng, moves)

        mrec = {"m": bridge.move_to_compact(game, pid, move)}
        if game["pending_pid"] is not None or step % legal_every == 0:
            mrec["L"] = [bridge.move_to_compact(game, pid, m) for m in moves]

        # coverage before apply (needs pre-move state)
        p = game["players"][pid]
        eff = p["monastery_effects"]
        mt = move["type"]
        cov["move_" + mt] += 1
        if mt == "adjust_die":
            d = game["dice"][pid]
            orig = d["orig"][move["die_index"]]
            frm = d["values"][move["die_index"]]
            delta = engine._adjust_cost(game, pid, orig, move["to"]) - engine._adjust_cost(
                game, pid, orig, frm)
            if delta < 0:
                cov["adjust_refund"] += 1
            if 8 in eff:
                cov["m8_adjust"] += 1
        if mt in ("sell_goods", "warehouse_sell"):
            if 3 in eff:
                cov["m3_sell"] += 1
            if 4 in eff:
                cov["m4_sell"] += 1
        if mt == "take_workers" or (
                mt == "extra_action" and (move.get("sub") or {}).get("type") == "take_workers"):
            if 13 in eff:
                cov["m13_workers"] += 1
            if 14 in eff:
                cov["m14_workers"] += 1
        if mt == "take_hex" and 12 in eff:
            v = game["dice"][pid]["values"][move["die_index"]]
            if move.get("depot", v) != v:
                cov["m12_adjacent_take"] += 1
        if mt == "monastery6_take":
            cov["m6_take"] += 1
        tile = _tile_type_of_move(game, pid, move)
        if tile is not None:
            cov["place_type_" + tile["type"]] += 1
            if tile["type"] == "livestock" and 7 in eff:
                cov["m7_livestock"] += 1
            if tile["type"] == "building" and 1 in eff:
                rid = engine._pboard(p).region_of(
                    move.get("space_id") or move["sub"]["space_id"])
                if tile["building"] in p["town_buildings"].get(rid, []):
                    cov["m1_dupe_building"] += 1

        prev_key = _round_key(game)
        ok, err = engine.apply_move(game, pid, move)
        assert ok, f"apply failed (seed {seed} step {step}): {err} move={move}"
        step += 1

        if game["phase"] == "playing" and _round_key(game) != prev_key:
            mrec["d"] = _dice_after_round_start(game)
        mrec["h"] = compact.proj_hash(game)
        if step % 25 == 0:
            mrec["p"] = compact.project(game)
        rec["moves"].append(mrec)

        if game["pending_kind"]:
            cov["pending_" + game["pending_kind"]] += 1
            if game["pending_kind"] == "ship_adjacent_depot":
                cov["m5_adjacent_offer"] += 1

        assert step < 4000, f"runaway game (seed {seed})"

    # end-of-game coverage
    scores = engine.final_scores(game)
    rec["scores"] = [scores[p] for p in PIDS]
    win = game["winner"]
    rec["winner"] = -1 if isinstance(win, list) else game["order"].index(win)
    if scores[PIDS[0]] == scores[PIDS[1]]:
        cov["tiebreak_empties"] += 1
        e0 = sum(1 for t in game["players"][PIDS[0]]["duchy"].values() if t is None)
        e1 = sum(1 for t in game["players"][PIDS[1]]["duchy"].values() if t is None)
        if e0 == e1:
            cov["tiebreak_track"] += 1
    for pid in PIDS:
        p = game["players"][pid]
        for eid in p["monastery_effects"]:
            cov[f"placed_m{eid}"] += 1
        if 2 in p["monastery_effects"] and p["mines_count"] > 0:
            cov["m2_income"] += 1
        for eid in range(15, 27):
            if eid in p["monastery_effects"] and engine._endgame_monastery_vp(game, pid) > 0:
                cov[f"endgame_m{eid}_held"] += 1
        for cb in p["claimed_bonus"]:
            cov["bonus_first" if cb["vp"] == tiles.bonus_first(2) else "bonus_second"] += 1
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=2000)
    ap.add_argument("--loaded", type=int, default=300)
    ap.add_argument("--seed0", type=int, default=0)
    ap.add_argument("--legal-every", type=int, default=7)
    ap.add_argument("--out", default=os.path.join(_REPO, "coc-core", "tests", "fixtures"))
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    cov = Counter()
    boards_cycle = [(str(a + 1), str(b + 1)) for a in range(9) for b in range(9)]

    path = os.path.join(args.out, "games.jsonl")
    n = 0
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for i in range(args.games + args.loaded):
            seed = args.seed0 + i
            b = boards_cycle[i % len(boards_cycle)]
            rec = play_game(seed, list(b), cov, loaded=(i >= args.games),
                            legal_every=args.legal_every)
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
            n += 1
            if n % 200 == 0:
                print(f"  {n} games...", flush=True)

    manifest = {"games": n, "coverage": dict(sorted(cov.items()))}
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)

    # Coverage gate: every monastery placed, every pending kind, key mechanics.
    missing = []
    for eid in range(1, 27):
        if cov[f"placed_m{eid}"] == 0:
            missing.append(f"placed_m{eid}")
    for k in ("pending_extra_action", "pending_ship_choose_depot", "pending_ship_adjacent_depot",
              "pending_goods_pick", "pending_building_take_choice", "pending_warehouse_sell",
              "pending_townhall_place", "move_skip_pending", "move_discard_storage",
              "move_buy_black", "move_monastery6_take", "adjust_refund", "bonus_first",
              "bonus_second", "m5_adjacent_offer", "m8_adjust", "m12_adjacent_take"):
        if cov[k] == 0:
            missing.append(k)
    print(f"wrote {n} games to {path}")
    print(f"coverage keys: {len(cov)}; MISSING: {missing if missing else 'none'}")


if __name__ == "__main__":
    main()
