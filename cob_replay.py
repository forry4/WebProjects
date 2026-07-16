"""Replay a BGA Castles of Burgundy 2-player game through the CoC engine and
check legality + final-score parity. Run from the worktree root:
    python cob_replay.py CoB_BGA/bga_880137656.json.txt
"""
import json, sys, re, copy, collections
from games.castles_of_crimson import engine, tiles, board
from games.castles_of_crimson.az import spaces

LOC_TO_DEPOT = {1:1,2:1,4:2,6:2,8:3,10:3,13:4,14:4,17:5,19:5,21:6,23:6}
BUILD = {"cityhall":"townhall","boardinghouse":"boarding","warehouse":"warehouse",
         "market":"market","carpenter":"carpenter","church":"church","bank":"bank","watchtower":"watchtower"}
TYPEMAP = {"knowledge":"monastery","animal":"livestock","building":"building",
           "ship":"ship","mine":"mine","castle":"castle"}
COLOR = {"monastery":"yellow","livestock":"green","building":"beige","ship":"blue","mine":"gray","castle":"burgundy"}

_COC_SIGS = None
def match_board(est):
    """CoC board id whose layout equals this BGA plEstSpaces layout, or None (board not in CoC)."""
    global _COC_SIGS
    if _COC_SIGS is None:
        _COC_SIGS = {}
        for bid in board.BOARDS:
            b = board.get_board(bid)
            canon = sorted(b.SPACES, key=lambda s: (b.SPACES[s]["r"], b.SPACES[s]["q"]))
            _COC_SIGS[tuple((tiles.COLOR_TO_TYPE[b.SPACES[s]["color"]], b.SPACES[s]["number"])
                            for s in canon)] = bid
    sig = tuple((TYPEMAP.get(x["type"], x["type"]), int(x["dieValue"])) for x in est)
    return _COC_SIGS.get(sig)

def die_value(d):
    intro = d["args"].get("logIntro", {})
    a = intro.get("args", {}) if isinstance(intro, dict) else {}
    img = a.get("dieImage", "") if isinstance(a, dict) else ""
    m = re.match(r"die_(\d)_", img) if isinstance(img, str) else None
    return int(m.group(1)) if m else None

def load_events(path):
    log = json.load(open(path, encoding="utf-8"))
    ev = []
    for pkt in log:
        for d in pkt.get("data", []):
            a = d.get("args", {})
            if isinstance(a, dict) and "plToIgnore" in a:
                continue
            ev.append((int(pkt["move_id"]) if pkt.get("move_id") is not None else 0, d))
    cancel = set()
    for mid, d in ev:
        if d["type"] == "undoTurn":
            for m in d["args"].get("movesToCancel", []):
                cancel.add(int(m))
    # An undoTurn's movesToCancel names the move_id of the packet holding the undone
    # actions -- but BGA puts the ROUND BOOKKEEPING (turnPlayed/newRound/newPhase) in that
    # same packet, alongside plToIgnore echoes of the real actions. Dropping the whole
    # move_id therefore threw away the round transition, so sync_round never ran, the dice
    # never refreshed, and every later action in that round died with "die already used".
    # The undone ACTIONS are the plToIgnore echoes (already filtered above), so cancelling
    # was only ever meant to drop those. Keep the bookkeeping.
    KEEP = {"newRound", "turnPlayed", "newPhase"}
    return [(mid, d) for mid, d in ev
            if d["type"] != "undoTurn" and (mid not in cancel or d["type"] in KEEP)], log

def build_catalog(events):
    """tileId -> CoC tile dict template (id/type/color + extras). Monastery effect
    numbers + animal counts harvested from tileImages / drawnTiles."""
    raw = {}          # tid -> (type, subtype, sprite)
    loc = {}          # (phase_idx, tid) -> location_arg   (per phase)
    mon = {}          # tid -> effect_id
    phase = -1
    for mid, d in events:
        if d["type"] == "newPhase":
            phase += 1
            for t in d["args"]["drawnTiles"]:
                raw[t["id"]] = (t["type"], t.get("subtype",""), int(t["sprite_pos"]))
                loc[(phase, t["id"])] = int(t["location_arg"])
        a = d.get("args", {})
        if isinstance(a, dict):
            img = a.get("tileImage", "")
            if isinstance(img, str) and "knowledge" in img:
                m = re.search(r"knowledge\s+(\d+)", img)
                if m: mon[a.get("tileId")] = int(m.group(1))
    return raw, loc, mon

# sprite_pos -> livestock count, decoded from BGA sprite sheet ordering (probed).
SPRITE_COUNT = {}   # filled by decode_counts()

def decode_counts(events, raw):
    """Animal placement immediately scores sum-of-counts of same animal in region.
    Track per-player region membership to solve each tile's count.

    The region grouping MUST use each player's OWN board. This hardcoded board 9 for
    everyone, and regions differ on 34/37 spaces between boards -- so for any player not
    on board 9 the `same` subtraction used the wrong pasture, every derived animal count
    came out wrong, and the error compounded through every livestock score (one game
    over-credited a player 40 VP). Games on board 9 were exact, which is the tell.
    """
    # pid -> the player's actual board (falls back to the default if unmatched)
    pboards = {}
    for mid, d in events:
        if d["type"] == "playerEstate":
            bid = match_board(d["args"]["plEstSpaces"])
            pboards[str(d["args"]["plId"])] = board.get_board(bid or board.DEFAULT_BOARD_ID)

    _canon = {}
    def region_of(pid, idx):
        b = pboards.get(pid) or board.get_board(board.DEFAULT_BOARD_ID)
        if b.id not in _canon:
            _canon[b.id] = sorted(b.SPACES, key=lambda s: (b.SPACES[s]["r"], b.SPACES[s]["q"]))
        sid = _canon[b.id][idx]
        return b.region_of(sid)
    placed = {}   # pid -> {region -> [(animal,count?)]}
    pending_place = None
    counts = {}
    it = iter(events)
    for mid, d in events:
        t = d["type"]; a = d.get("args", {})
        if t == "tileAddedToEstate" and a.get("tileId") in raw and raw[a["tileId"]][0]=="animal":
            pending_place = (str(a["plId"]), int(a["spaceId"]), a["tileId"], raw[a["tileId"]])
        elif t == "pointsForAnimals" and pending_place:
            pid, sp, tid, (typ, sub, sprite) = pending_place
            reg = region_of(pid, sp)
            prior = placed.setdefault(pid, {}).setdefault(reg, [])
            same = sum(c for an,c in prior if an==sub)
            cnt = int(a["pointsForAnimals"]) - same
            counts[sprite] = cnt
            prior.append((sub, cnt))
            pending_place = None
    return counts

def coc_tile(tid, raw, mon, counts):
    typ, sub, sprite = raw[tid]
    ctype = TYPEMAP[typ]
    t = {"id": "b"+str(tid), "kind":"hex", "type":ctype, "color":COLOR[ctype]}
    if ctype == "building":
        t["building"] = BUILD[sub]
    elif ctype == "monastery":
        t["effect_id"] = mon.get(tid)
    elif ctype == "livestock":
        t["animal"] = sub
        t["count"] = counts.get(sprite, 3)
    return t

def main(path, verbose=True, on_move=None):
    _pr = print if verbose else (lambda *a, **k: None)
    events, log = load_events(path)
    raw, loc, mon = build_catalog(events)
    counts = decode_counts(events, raw)
    goods_type = {}   # goods id -> type (1..6)
    for mid, d in events:
        if d["type"] == "newPhase":
            for gd in d["args"].get("drawnGoods", []):
                goods_type[str(gd["id"])] = int(gd["type"])
    _pr("decoded sprite->count:", dict(sorted(counts.items())))

    # players in recorded seat order (from startingBoardsAndCastles / playerEstate order)
    pids = []
    boards = {}
    board_ok = True
    for mid, d in events:
        if d["type"] == "playerEstate":
            pid = str(d["args"]["plId"])
            pids.append(pid)
            bid = match_board(d["args"]["plEstSpaces"])
            if bid is None:
                board_ok = False; bid = str(d["args"].get("board_nb", "9"))
            boards[pid] = bid
    if not board_ok:
        _pr("board layout not in CoC's set -> unreplayable")
        return {"path": path, "completed": False, "stopped": "board_not_in_coc_set",
                "applied": 0, "over": False, "winner_match": False, "worker_ok": True}
    # names
    names = {}
    for mid, d in events:
        a = d.get("args", {})
        if isinstance(a, dict) and a.get("plId") and a.get("player_name"):
            names[str(a["plId"])] = a["player_name"]
    # seat the round-1 start player first (seat-dependent starting workers: start=1, next=2)
    first = next((str(d["args"]["plId"]) for mid, d in events if d["type"] == "turnPlayed"), None)
    if first in pids:
        pids = [first] + [p for p in pids if p != first]
    _pr("players (seated, start first):", [(p, names.get(p)) for p in pids])

    g = engine.new_game(pids, names=names, boards=boards)
    bobj = {p: board.get_board(boards.get(p,"9")) for p in pids}

    # reconstruct + inject starting goods: any goods a player sells beyond what it
    # took from ships must have been a starting good (present from t=0).
    invp = collections.defaultdict(collections.Counter)
    startp = collections.defaultdict(collections.Counter)
    for mid, d in events:
        t = d["type"]; a = d.get("args", {})
        if t == "goodsTaken":
            pid = str(a["plId"])
            for gt in a.get("goodsTilesToMove", []):
                ty = goods_type.get(str(gt["id"]))
                if ty: invp[pid][ty] += 1
        elif t == "goodsSold":
            pid = str(a["plId"]); m = re.match(r"goods_(\d)", a.get("goodsImage",""))
            ty = int(m.group(1)) if m else None
            n = len(a.get("soldGoods", [])) or 1
            if ty:
                if invp[pid][ty] < n:
                    dd = n - invp[pid][ty]; startp[pid][ty] += dd; invp[pid][ty] += dd
                invp[pid][ty] -= n
    for p in pids:
        g["players"][p]["goods"] = {}
        for ty, c in startp[p].items():
            g["players"][p]["goods"][tiles.goods_color_for_die(ty)] = c
    _pr("reconstructed starting goods:", {names.get(p,p): dict(startp[p]) for p in pids})

    def ensure_goods(pid, gtype, n=1):
        col = tiles.goods_color_for_die(gtype)
        if g["players"][pid]["goods"].get(col, 0) < n:
            g["players"][pid]["goods"][col] = n

    # precompute per-round turn order from the log (turnPlayed sequence between newRounds)
    round_orders = []          # one entry per newRound, aligned 1:1 (the turnPlayeds that follow it)
    cur = None
    for mid, d in events:
        if d["type"] == "newRound":
            if cur is not None: round_orders.append(cur)
            cur = []
        elif d["type"] == "turnPlayed" and cur is not None:
            p = str(d["args"]["plId"])
            if p not in cur: cur.append(p)
    if cur is not None: round_orders.append(cur)
    ro_iter = iter(round_orders)

    phase_idx = -1
    tile_obj = {}   # tid -> the exact coc tile dict currently in play (so moves ref same obj id)

    def inject_phase(pi):
        """Overwrite depots+black with this phase's exact drawn tiles."""
        # gather this phase's drawnTiles
        dt = None
        cnt = 0
        for mid, d in events:
            if d["type"] == "newPhase":
                if cnt == pi:
                    dt = d["args"]["drawnTiles"]; break
                cnt += 1
        by_depot = {i: [] for i in range(1,7)}
        black = []
        for t in dt:
            la = int(t["location_arg"])
            ct = coc_tile(t["id"], raw, mon, counts)
            tile_obj[t["id"]] = ct
            if la in LOC_TO_DEPOT:
                by_depot[LOC_TO_DEPOT[la]].append(ct)
            else:
                black.append(ct)
        for i in range(1,7):
            g["depots"][str(i)]["hexes"] = by_depot[i]
        g["black_depot"] = black

    def sync_round(nd):
        """Override dice + white die + relocate the white-die goods tile."""
        dice = {}
        for die in nd["args"]["dice"]:
            dice.setdefault(str(die["plId"]), [None,None])[die["dieNb"]-1] = die["dieValue"]
        white = nd["args"]["depot"]
        # relocate any goods the engine's _begin_round auto-placed
        old_white = g["white_die"]
        for pid in g["order"]:
            if pid in dice:
                g["dice"][pid]["values"] = list(dice[pid])
                g["dice"][pid]["orig"] = list(dice[pid])
                g["dice"][pid]["used"] = [False, False]
                g["dice"][pid]["adjusted"] = [False, False]
        # drop the engine's auto-placed random round-goods, inject the recorded one
        if g["depots"][str(old_white)]["goods"]:
            g["depots"][str(old_white)]["goods"].pop()
        gid = nd["args"].get("goodsId")
        gt = goods_type.get(str(gid))
        if gt:
            g["depots"][str(white)]["goods"].append(
                {"id":"rg"+str(gid), "kind":"goods", "color":tiles.goods_color_for_die(gt)})
        g["white_die"] = white
        try:
            order = next(ro_iter)
            if order:
                g["round_order"] = list(order)
                g["start_player"] = order[0]
                g["turn"] = order[0]
        except StopIteration:
            pass

    stats = {"applied": 0, "last": None, "wdiv": None, "sdiv": None}
    def AP(pid, move, tag=""):
        if on_move is not None:
            try: on_move(g, pid, move, tag)
            except Exception: pass
        ok, err = engine.apply_move(g, pid, move)
        if not ok:
            raise RuntimeError(f"apply FAILED [{tag}] pid={pid} move={move} err={err}\n"
                               f"  dice={g['dice'].get(pid)} pending={g.get('pending_kind')}")
        stats["applied"] += 1; stats["last"] = tag
        return ok

    def check_workers(pid, a, mid):
        if stats["wdiv"] is None and "newNbWorkers" in a:
            got = g["players"][pid]["workers"]; want = int(a["newNbWorkers"])
            if got != want:
                stats["wdiv"] = f"move {mid} pid {names.get(pid,pid)}: CoC workers={got} vs log={want}"
        if stats.get("sdiv") is None and "silverlings" in a and str(a["silverlings"]).lstrip("-").isdigit():
            got = g["players"][pid]["silver"]; want = int(a["silverlings"])
            if got != want:
                stats["sdiv"] = f"move {mid} {names.get(pid,pid)}: CoC silver={got} vs log={want} (after {a.get('goodsImage','?')})"

    def pend(pid):
        return g["pending_kind"] if g.get("pending_pid") == pid else None

    def _wrap(a, b):
        d = abs(a - b) % 6
        return min(d, 6 - d)

    def do_die_action(pid, di, want, move, tag, shift=True):
        # try as-is first (free shift / already-right die), else adjust to `want` or, when a
        # ±1 free shift applies (monastery 9/10/11 place, 12 take), the cheaper neighbor.
        if on_move is not None:
            try: on_move(g, pid, move, tag)
            except Exception: pass
        ok, err = engine.apply_move(g, pid, move)
        if ok:
            stats["applied"] += 1; stats["last"] = tag; return
        orig = g["dice"][pid]["orig"][di]
        cands = {want, want % 6 + 1, (want - 2) % 6 + 1} if shift else {want}
        for t in sorted(cands, key=lambda t: _wrap(orig, t)):
            if g["dice"][pid]["values"][di] != t:
                ao, ae = engine.apply_move(g, pid, {"type": "adjust_die", "die_index": di, "to": t})
                if not ao:
                    continue
            ok, err = engine.apply_move(g, pid, move)
            if ok:
                stats["applied"] += 1; stats["last"] = tag; return
        raise RuntimeError(f"apply FAILED [{tag}] pid={pid} err={err} want={want} dice={g['dice'][pid]}")

    def ensure_die(pid, di, want):
        cur = g["dice"][pid]["values"][di]
        if cur != want:
            AP(pid, {"type":"adjust_die","die_index":di,"to":want}, "adjust")

    # place starting castles in SEAT order (CoC-enforced; placements are independent)
    castles = {}
    for mid, d in events:
        if d["type"] == "startingCastleplaced":
            c = d["args"]["castle"]
            castles[str(c["player_id"])] = spaces.SPACE_IDS[int(c["location_arg"])]
    for pid in pids:
        AP(pid, {"type":"place_starting_castle","space_id":castles[pid]}, "castle")

    # ---- drive the log ----
    stopped = None
    try:
     for mid, d in events:
        t = d["type"]; a = d.get("args", {})
        # replay ground truth: if the engine's turn drifted, the log's actor owns the turn
        if (t in ("tileTakenToStorage", "tileAddedToEstate", "goodsSold", "workersTaken", "goodsTaken")
                and isinstance(a, dict) and a.get("plId") and g.get("phase") == "playing"
                and g.get("pending_pid") is None and g.get("turn") != str(a["plId"])):
            g["turn"] = str(a["plId"])
        # a ship-depot pending not followed by a goods take -> the player took no ship goods
        if (t in ("tileTakenToStorage", "tileAddedToEstate", "goodsSold", "workersTaken")
                and isinstance(a, dict) and a.get("plId")
                and g.get("pending_pid") == str(a["plId"])
                and g.get("pending_kind") in ("ship_choose_depot", "ship_adjacent_depot")):
            AP(str(a["plId"]), {"type":"skip_pending"}, "ship_skip")
        if t == "startingCastleplaced":
            continue
        elif t == "newPhase":
            phase_idx += 1
            inject_phase(phase_idx)
        elif t == "newRound":
            sync_round(d)
        elif t == "tileTakenToStorage":
            pid = str(a["plId"]); tid = a["tileId"]; pk = pend(pid)
            if a.get("bTileBought"):
                tobj = "b"+str(tid)
                img = a.get("silvOrWorkersImage", "")
                in_black = any(x["id"] == tobj for x in g["black_depot"])
                if in_black and img.startswith("silver"):
                    AP(pid, {"type":"buy_black","tile_id":tobj}, f"buy {tid}")   # normal black-depot buy
                else:
                    # BGA's monastery 6 = "spend 2 silver OR 2 workers to take a tile from ANY
                    # depot". CoC has no equivalent, so a game where it's used can't be replayed
                    # faithfully -> filter the whole game. This guard is exactly right: the only
                    # buy everyone has is black-depot-with-silver, so anything else IS mon6.
                    # Measured over the corpus: 450 black/silver (normal) vs 37 numbered/silver
                    # + 7 numbered/workers + 7 black/workers (= 51 mon6 uses). Not a bug, not a
                    # missing purchase rule, not a LOC_TO_DEPOT problem -- all three were checked
                    # and refuted. Do not re-investigate.
                    raise RuntimeError("mon6_buy_mechanic")
            elif pk == "building_take_choice":
                AP(pid, {"type":"building_take_choice","tile_id":"b"+str(tid)}, f"btake {tid}")
            elif pk == "extra_action":
                dep = LOC_TO_DEPOT[loc[(phase_idx, tid)]]
                AP(pid, {"type":"extra_action","value":dep,
                         "sub":{"type":"take_hex","depot":dep,"tile_id":"b"+str(tid)}}, f"xtake {tid}")
            else:
                di = int(a["dieNb"]) - 1
                dep = LOC_TO_DEPOT[loc[(phase_idx, tid)]]
                do_die_action(pid, di, dep, {"type":"take_hex","die_index":di,"depot":dep,"tile_id":"b"+str(tid)}, f"take {tid} d{dep}")
        elif t == "tileAddedToEstate":
            pid = str(a["plId"]); tid = a["tileId"]
            sid = spaces.SPACE_IDS[int(a["spaceId"])]; num = bobj[pid].SPACES[sid]["number"]; pk = pend(pid)
            if pk == "townhall_place":
                AP(pid, {"type":"townhall_place","tile_id":"b"+str(tid),"space_id":sid}, f"townhall {tid}")
            elif pk == "extra_action":
                AP(pid, {"type":"extra_action","value":num,
                         "sub":{"type":"place_tile","tile_id":"b"+str(tid),"space_id":sid}}, f"xplace {tid}")
            elif int(a.get("dieNb") or 0) == 0:
                # dieNb 0 = a town-hall extra placement; CoC only opens that pending if storage
                # was non-empty at town-hall time (CoB allows a later-acquired tile), so force it.
                if pk != "townhall_place":
                    engine._set_pending(g, pid, "townhall_place", {"building": "townhall"})
                AP(pid, {"type":"townhall_place","tile_id":"b"+str(tid),"space_id":sid}, f"townhall2 {tid}")
            else:
                di = int(a["dieNb"]) - 1
                do_die_action(pid, di, num, {"type":"place_tile","die_index":di,"tile_id":"b"+str(tid),"space_id":sid}, f"place {tid}@{a['spaceId']}")
        elif t == "goodsSold":
            pid = str(a["plId"]); di = int(a.get("dieNb", 0)); pk = pend(pid)
            m = re.match(r"goods_(\d)", a.get("goodsImage",""))
            stype = int(m.group(1)) if m else None
            n = len(a.get("soldGoods", [])) or 1
            if stype: ensure_goods(pid, stype, n)
            if pk == "warehouse_sell":
                AP(pid, {"type":"warehouse_sell","color":tiles.goods_color_for_die(stype)}, "wh_sell")
            elif pk == "extra_action":
                AP(pid, {"type":"extra_action","value":stype,"sub":{"type":"sell_goods"}}, "xsell")
            else:
                do_die_action(pid, di-1, stype, {"type":"sell_goods","die_index":di-1}, "sell", shift=False)
        elif t == "workersTaken":
            pid = str(a["plId"]); pk = pend(pid)
            if pk == "extra_action":
                AP(pid, {"type":"extra_action","value":1,"sub":{"type":"take_workers"}}, "xworkers")
            else:
                di = int(a["dieNb"]) - 1                        # workers: any die, no adjust
                AP(pid, {"type":"take_workers","die_index":di}, "workers")
        elif t == "goodsTaken":
            pid = str(a["plId"])
            # `depots` names EVERY depot drained by this one action: "(3)" -> [3], and for
            # monastery 5 "(6,1)" -> [6, 1] = the ship depot AND the adjacent one, in ONE
            # record (there is no second goodsTaken for the m5 follow-up). Parsing only the
            # first number left the m5 pending armed, and a LATER ship's goodsTaken then got
            # eaten by that stale pending -> "not an adjacent depot with goods". Consume all.
            deps = [int(x) for x in re.findall(r"\d+", a.get("depots", ""))]
            if g.get("pending_kind") == "ship_choose_depot":
                # For a monastery-5 pair, BGA does NOT guarantee source-first order: '(2,1)'
                # can mean source=1/adjacent=2. Both orders are ring-adjacent so the text alone
                # can't disambiguate -- but only ONE is legal (the source must hold goods, and
                # the engine only offers adjacent depots that do). So try deps[0] as source and
                # fall back to the reverse, letting the engine arbitrate.
                for src, adj in ([ (deps[0], deps[1]), (deps[1], deps[0]) ] if len(deps) > 1
                                 else [ (deps[0], None) ]):
                    snap = copy.deepcopy(g)
                    try:
                        AP(pid, {"type":"ship_take_goods","depot":src}, "ship_goods")
                        if adj is not None and g.get("pending_kind") == "ship_adjacent_depot":
                            AP(pid, {"type":"ship_adjacent_take","depot":adj}, "ship_adj")
                        break
                    except RuntimeError:
                        g.clear(); g.update(snap)   # restore and try the other orientation
                else:
                    raise RuntimeError(f"ship goods: neither order legal for depots={deps}")
            elif g.get("pending_kind") == "ship_adjacent_depot":
                # We arrive here when the m5 pending armed LATE -- a ship take that overflows
                # opens a goods_pick first, so the pending only becomes ship_adjacent_depot
                # after the picks resolve, and the follow-up rides in a DUPLICATE record (BGA
                # logs some m5 takes twice, neither copy flagged plToIgnore). That record
                # still reads '(6,1)' = (source, adjacent), so deps[0] is the SOURCE and would
                # be rejected. Take the entry that's an actual candidate.
                cands = g["pending"]["ctx"].get("candidates", [])
                d2 = next((x for x in deps if x in cands), deps[0])
                AP(pid, {"type":"ship_adjacent_take","depot":d2}, "ship_adj")
            # resolve a goods_pick overflow using the colours the log kept (from goodsTilesToMove)
            kept = [tiles.goods_color_for_die(goods_type[str(gt["id"])])
                    for gt in a.get("goodsTilesToMove", []) if str(gt["id"]) in goods_type]
            guard = 0
            while pend(pid) == "goods_pick" and guard < 6:
                cands = g["pending"]["ctx"].get("colors", [])
                pick = next((c for c in kept if c in cands), cands[0] if cands else None)
                if pick is None:
                    AP(pid, {"type":"skip_pending"}, "gp_skip"); break
                AP(pid, {"type":"goods_pick", "color":pick}, "goods_pick")
                if pick in kept: kept.remove(pick)
                guard += 1
        elif t == "tileDiscarded":
            pid = str(a["plId"])
            AP(pid, {"type":"discard_storage", "tile_id":"b"+str(a["tileId"])}, f"discard {a['tileId']}")
        elif t == "turnPlayed":
            pid = str(a["plId"])
            # flush any lingering pending for this player (e.g. an unused ability)
            while g.get("pending_pid") == pid:
                AP(pid, {"type":"skip_pending"}, "skip")
            if g.get("turn") == pid:
                AP(pid, {"type":"end_turn"}, "end_turn")
        if isinstance(a, dict) and a.get("plId"):     # verify AFTER the action applied
            check_workers(str(a["plId"]), a, mid)

    except RuntimeError as e:
        stopped = str(e).split(chr(10))[0]
        _pr("\n!! STOPPED:", stopped)
    _pr(f"\napplied {stats['applied']} moves; last='{stats['last']}'; phase={g.get('phase')} "
          f"round={g.get('phase_letter')}-{g.get('round')}")
    if stats["wdiv"]:
        _pr("FIRST worker divergence:", stats["wdiv"])
    else:
        _pr("worker counts matched the log everywhere they were reported")
    if stats.get("sdiv"):
        _pr("FIRST silver divergence:", stats["sdiv"])
    _pr("live VP:", {names.get(p,p): g['players'][p]['vp'] for p in pids},
          " workers:", {names.get(p,p): g['players'][p]['workers'] for p in pids},
          " silver:", {names.get(p,p): g['players'][p]['silver'] for p in pids})
    if engine.is_over(g):
        fs = engine.final_scores(g)
        _pr("CoC final_scores:", {names.get(p,p): fs[p] for p in pids})
        # per-category comparison vs the recorded finalScoring
        rec = None
        for mid, d in events:
            if d["type"] == "finalScoring":
                rec = d["args"]["scoreTable"]
        for p in pids:
            pl = g["players"][p]
            gd = sum(pl["goods"].values())
            endmon = fs[p] - pl["vp"] - gd - pl["silver"] - pl["workers"] // 2
            _pr(f"  CoC {names[p]:16s}: inGame(vp)={pl['vp']:3d} yellow(endmon)={endmon:2d} "
                  f"unsold={gd} silver={pl['silver']} workers={pl['workers']}")
            if rec:
                _pr(f"  REC {names[p]:16s}: inGame={rec['inGame'][p]:>3} yellow={rec['yellowTiles'][p]:>2} "
                      f"unsold={rec['unsoldGoods'][p]} silver={rec['silverlings'][p]} workers={rec['workers'][p]} total={rec['total'][p]}")
            _pr(f"    endgame items: {engine._endgame_monastery_items(g, p)}")
            _pr(f"    buildings={dict((k,v) for k,v in pl['buildings_placed'].items() if v)} "
                  f"livestock_types={pl['livestock_types']} sold_types={sorted(set(pl['sold_goods']))} "
                  f"mon={sorted(pl['monastery_effects'])}")

    # ---- structured result (for the batch filter) ----
    over = engine.is_over(g)
    result = {"path": path, "completed": stopped is None and over, "stopped": stopped,
              "applied": stats["applied"], "over": over, "worker_ok": stats["wdiv"] is None,
              "winner_match": False}
    if over:
        fs = engine.final_scores(g)
        cw = max(pids, key=lambda q: fs[q])
        rw = None
        for mid, d in events:
            if d["type"] == "finalScoring":
                tot = d["args"]["scoreTable"]["total"]
                rw = max(pids, key=lambda q: int(tot[q]))
        result.update(coc_winner=cw, rec_winner=rw, winner_match=(rw is not None and cw == rw))
    return result

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv)>1 else "CoB_BGA/bga_880137656.json.txt")
