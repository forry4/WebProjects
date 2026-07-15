"""WHAT did the top players value differently from our net?

At each top-player clean decision where our net DISAGREES, resolve the actual tile
(or action) each side chose and aggregate:
  - move-type shift  (pro did X, net wanted Y)
  - tile-type the pro acquired vs the net (on take_hex / place_tile / buy_black)
  - specific building / monastery / livestock detail

Usage: python cob_tilepref.py [sims]
"""
import json, os, sys, subprocess, collections
import cob_replay, cob_collect as cc
from cob_analyze import move_key, rank_map
from games.castles_of_crimson import engine
from games.castles_of_crimson.az import compact, bridge

CORP = "C:/Users/Forrest/CoB_corpus"
LOGS, MANIFEST, KEPT = CORP + "/logs", CORP + "/manifest.json", CORP + "/kept_games.txt"
EXE = "C:/Users/Forrest/forrestm_projects-cobmining/coc-core/target/release/move_server_coc.exe"
MODEL = "C:/Users/Forrest/coc_run_4animal/pv_warm936.json"
SIMS = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
EXCLUDE = {"880518518"}  # board 4
ACQUIRE = {"take_hex", "place_tile", "buy_black"}

def resolve_tile(g, tid):
    for d in g.get("depots", {}).values():
        for t in d.get("hexes", []):
            if t and t.get("id") == tid: return t
    for t in g.get("black_depot", []):
        if t and t.get("id") == tid: return t
    for p in g["players"].values():
        for t in p.get("storage", []):
            if t and t.get("id") == tid: return t
        for t in (p.get("duchy") or {}).values():
            if t and t.get("id") == tid: return t
    return None

def tile_detail(tile):
    if not tile: return "?"
    t = tile["type"]
    if t == "building": return f"building:{tile.get('building')}"
    if t == "monastery": return f"monastery#{tile.get('effect_id')}"
    if t == "livestock": return f"livestock:{tile.get('animal')}{tile.get('count')}"
    return t  # ship / castle / mine

def move_info(g, move):
    """(move_type, tile_type or None, tile_detail or None)."""
    mt = move["type"]
    if mt in ACQUIRE and move.get("tile_id"):
        tile = resolve_tile(g, move["tile_id"])
        return mt, (tile["type"] if tile else "?"), tile_detail(tile)
    return mt, None, None

def main():
    srv = [None]; seed = [1]
    def start(): srv[0] = subprocess.Popen([EXE, MODEL, "30", "1.0"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, text=True, bufsize=1, encoding="utf-8")
    def net_move(g, pid):
        if srv[0] is None or srv[0].poll() is not None: start()
        try:
            srv[0].stdin.write(json.dumps({"proj": compact.project(g), "sims": SIMS, "seed": seed[0]}, separators=(",", ":")) + "\n"); srv[0].stdin.flush()
            seed[0] += 1
            line = srv[0].stdout.readline()
            return bridge.compact_to_move(g, pid, json.loads(line)["move"])
        except Exception:
            try: srv[0].kill()
            except Exception: pass
            srv[0] = None; raise

    ranks = rank_map()
    kept = [l.strip() for l in open(KEPT) if l.strip() and l.strip() not in EXCLUDE]
    man = json.load(open(MANIFEST))
    print(f"tile-preference analysis | {SIMS} sims | {len(kept)} games\n")

    n_dis = [0]
    shift = collections.Counter()          # (pro_movetype, net_movetype) on disagreement
    pro_acq = collections.Counter()        # tile TYPE the pro acquired (disagreements)
    net_acq = collections.Counter()        # tile TYPE the net wanted
    pro_detail = collections.Counter()     # specific tile the pro acquired
    net_detail = collections.Counter()
    hexhex = collections.Counter()         # both take_hex, different tile: (pro_type, net_type)

    for tid in kept:
        entry = man.get(tid, {})
        pl = [p for p in entry.get("players", "").split(",") if p]
        if len(pl) != 2: continue
        top = min(pl, key=lambda p: ranks.get(p, 999))

        def on_move(g, pid, move, tag, _top=top):
            if pid != _top or g.get("phase") != "playing" or g.get("pending_kind"): return
            legal = engine.legal_moves(g, pid)
            if len(legal) < 2: return
            hk = move_key(move)
            if hk not in {move_key(m) for m in legal}: return
            try: bot = net_move(g, pid)
            except Exception: return
            if hk == move_key(bot): return   # agreement
            n_dis[0] += 1
            pmt, ptype, pdet = move_info(g, move)
            nmt, ntype, ndet = move_info(g, bot)
            shift[(pmt, nmt)] += 1
            if ptype: pro_acq[ptype] += 1; pro_detail[pdet] += 1
            if ntype: net_acq[ntype] += 1; net_detail[ndet] += 1
            if pmt == "take_hex" and nmt == "take_hex":
                hexhex[(ptype, ntype)] += 1

        try: cob_replay.main(f"{LOGS}/{tid}.json", verbose=False, on_move=on_move)
        except Exception: continue

    try:
        if srv[0]: srv[0].terminate()
    except Exception: pass

    print(f"=== disagreements analyzed: {n_dis[0]} ===\n")
    print("--- MOVE-TYPE shift (pro did -> net wanted), top 12 ---")
    for (a, b), c in shift.most_common(12):
        print(f"  {c:>3}  pro:{a:<14} net:{b}")
    print("\n--- TILE TYPE acquired on disagreements (pro vs net) ---")
    allt = sorted(set(pro_acq) | set(net_acq), key=lambda k: -(pro_acq[k] + net_acq[k]))
    print(f"  {'type':<12} {'PRO':>5} {'NET':>5}   (pro-minus-net = pro values more)")
    for t in allt:
        print(f"  {t:<12} {pro_acq[t]:>5} {net_acq[t]:>5}   {pro_acq[t]-net_acq[t]:+d}")
    print("\n--- specific tiles the PRO grabbed (net didn't), top 12 ---")
    for d, c in pro_detail.most_common(12): print(f"  {c:>3}  {d}")
    print("\n--- specific tiles the NET wanted (pro didn't), top 12 ---")
    for d, c in net_detail.most_common(12): print(f"  {c:>3}  {d}")
    print("\n--- when BOTH take a hex but pick DIFFERENT tiles (pro_type -> net_type), top 12 ---")
    for (a, b), c in hexhex.most_common(12): print(f"  {c:>3}  pro:{a:<10} net:{b}")

if __name__ == "__main__":
    main()
