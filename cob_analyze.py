"""Compare our CoC bot against the TOP player in each kept CoB game.

For every decision the TOP player makes (the higher-ranked of the two players,
i.e. the strong player whose games we mined) where a real choice exists, we ask
our bot (ai.choose_move) what it would play and compare:
  - agreement:  does the bot pick the SAME move the top human did?
  - eval-regret: bot's leaf value after the human's move minus after the bot's
                 move, from the top player's seat (<=0 => the bot rates its own
                 move higher; near 0 => the bot agrees the human's move is fine).
Only the top player's decisions are scored; the opponent's turns are ignored.

Usage: python cob_analyze.py [time_limit] [max_iters]
"""
import json, os, sys, collections
import cob_replay, cob_collect as cc
from games.castles_of_crimson import engine, ai as coc_ai

CORP = "C:/Users/Forrest/CoB_corpus"
LOGS, MANIFEST, KEPT = CORP + "/logs", CORP + "/manifest.json", CORP + "/kept_games.txt"

TIME = float(sys.argv[1]) if len(sys.argv) > 1 else 0.4
ITERS = int(sys.argv[2]) if len(sys.argv) > 2 else 1500

_KEYF = ("space_id", "tile_id", "die_index", "to", "depot", "color", "value", "sub")
def move_key(m):
    return (m.get("type"), tuple(str(m.get(k)) for k in _KEYF))

def rank_map():
    cookie, token = cc.load_cookie()
    rm = {}
    for start in (0, 20, 40):
        d = cc.api(f"https://boardgamearena.com/gamepanel/gamepanel/getRanking.html"
                   f"?game=1390&mode=elo&start={start}", cookie, token)
        for i, r in enumerate(d.get("data", {}).get("ranks", [])):
            rm.setdefault(str(r["id"]), start + i)  # lower rank index = stronger
    return rm

def val_after(g, pid, move):
    """1-ply leaf value from pid's seat after applying `move` on a clone (or None)."""
    try:
        gg = coc_ai._clone_game(g)
        ok, _ = engine.apply_move(gg, pid, move)
        if not ok:
            return None
        return coc_ai._value(gg, pid)
    except Exception:
        return None

def analyze():
    ranks = rank_map()
    kept = [l.strip() for l in open(KEPT) if l.strip()]
    man = json.load(open(MANIFEST))
    print(f"analyzing {len(kept)} kept games | bot budget: {TIME}s / {ITERS} iters\n")

    agg = collections.Counter()
    bytype = collections.defaultdict(lambda: [0, 0])   # type -> [agree, total]
    regrets = []
    rows = []

    for tid in kept:
        entry = man.get(tid, {})
        pl = [p for p in entry.get("players", "").split(",") if p]
        names = entry.get("player_names", "").split(",")
        if len(pl) != 2:
            continue
        top = min(pl, key=lambda p: ranks.get(p, 999))
        top_name = names[pl.index(top)] if len(names) == 2 else top
        st = {"agree": 0, "total": 0, "reg": [], "fail": 0}

        def on_move(g, pid, move, tag, _top=top, _st=st):
            # Score only the top player's CLEAN primary decisions: normal play phase,
            # no pending sub-decision (choose_move is only well-defined there), a real
            # choice (>=2 legal), and the human's move directly legal (no die-adjust
            # needed) so bot & human pick from the SAME legal set.
            if pid != _top or g.get("phase") != "playing" or g.get("pending_kind"):
                return
            legal = engine.legal_moves(g, pid)
            if len(legal) < 2:
                return
            hk = move_key(move)
            if hk not in {move_key(m) for m in legal}:
                return
            gg = coc_ai._clone_game(g)
            try:
                bot = coc_ai.choose_move(gg, pid, time_limit=TIME, max_iters=ITERS)
            except Exception:
                _st["fail"] += 1
                return
            _st["total"] += 1
            t = move.get("type")
            bytype[t][1] += 1
            same = move_key(move) == move_key(bot)
            if same:
                _st["agree"] += 1
                bytype[t][0] += 1
            else:
                vh, vb = val_after(g, pid, move), val_after(g, pid, bot)
                if vh is not None and vb is not None:
                    _st["reg"].append(vb - vh)   # >0 => bot's leaf rates its own move higher

        try:
            r = cob_replay.main(f"{LOGS}/{tid}.json", verbose=False, on_move=on_move)
        except Exception as e:
            print(f"  {tid}: replay error {type(e).__name__}")
            continue
        won = (r.get("coc_winner") == top)
        rate = st["agree"] / st["total"] if st["total"] else 0.0
        reg = sum(st["reg"]) / len(st["reg"]) if st["reg"] else 0.0
        rows.append((tid, top_name, won, st["agree"], st["total"], rate, reg, st["fail"]))
        agg["agree"] += st["agree"]; agg["total"] += st["total"]
        regrets += st["reg"]
        print(f"  {tid}  {top_name:<16} {'WON ' if won else 'lost'} "
              f"agree {st['agree']:>3}/{st['total']:<3} ({rate*100:4.1f}%)  "
              f"regret {reg:+.3f}  fails {st['fail']}")

    print("\n=== OVERALL (top player's decisions only) ===")
    tot = agg["total"]
    print(f"games scored: {len(rows)}")
    print(f"top-player decisions: {tot}")
    print(f"bot agreed with top player: {agg['agree']}/{tot} = "
          f"{(agg['agree']/tot*100) if tot else 0:.1f}%")
    if regrets:
        avg = sum(regrets) / len(regrets)
        botbetter = sum(1 for x in regrets if x > 0.05)
        humanbetter = sum(1 for x in regrets if x < -0.05)
        print(f"on DISAGREEMENTS ({len(regrets)}): avg bot-advantage {avg:+.3f} "
              f"(bot-move leaf minus human-move leaf, top seat; >0 = bot prefers its own)")
        print(f"  bot's move rated better: {botbetter}  |  human's move rated better: {humanbetter}  "
              f"|  ~tie: {len(regrets)-botbetter-humanbetter}")
    print("\n=== agreement by move type ===")
    for t, (a, n) in sorted(bytype.items(), key=lambda kv: -kv[1][1]):
        print(f"  {t:<22} {a:>3}/{n:<3} ({(a/n*100) if n else 0:4.1f}%)")

if __name__ == "__main__":
    analyze()
