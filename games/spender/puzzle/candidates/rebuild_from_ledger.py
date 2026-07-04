"""Re-emit puzzle JSONs from the committed candidate ledger at ANY threshold — a pure re-filter with
ZERO AI recompute. Self-contained (only in-repo deps: engine/actions/schema).

The ledger (`candidate_ledger.jsonl.gz`) is one line per VERIFIED position: its compact engine state
plus every legal move's K=8-averaged N eval. Producing a line is expensive (per position:
#moves x 8 searches); persisting it means changing the accept threshold later is instant.

  # see what's available at various bars, no writes:
  python -m games.spender.puzzle.candidates.rebuild_from_ledger --stats

  # emit takes at the current rule (>=0.25, no upper bound) into a dir:
  python -m games.spender.puzzle.candidates.rebuild_from_ledger --out /tmp/takes --types take

  # try a softer take bar:
  python -m games.spender.puzzle.candidates.rebuild_from_ledger --out /tmp/t --types take --gap-take 0.15

Accept rule (matches the shipped bank): buy/reserve in [--gap, --gap-hi]; take >= --gap-take (NO upper
bound — a big-gap take is subtle, not obvious, since the wrong gem-combos look like the right one).
Answers that would force a discard/noble sub-step are always excluded.
"""
import argparse
import glob
import gzip
import json
import os
import sys
from collections import Counter
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "..", "..")))  # repo root
from games.spender.ai.az import engine as E, actions as A   # noqa: E402
from games.spender.puzzle import schema                       # noqa: E402

LEDGER = os.path.join(_HERE, "candidate_ledger.jsonl.gz")


def state_from_dump(d):
    """Rebuild an engine State from the compact dump (inverse of the miner's _dump)."""
    s = E.State.__new__(E.State)
    s.bank = list(d["bank"])
    s.tokens = (list(d["tokens"][0]), list(d["tokens"][1]))
    s.bonuses = (list(d["bonuses"][0]), list(d["bonuses"][1]))
    s.points = list(d["points"])
    s.purchased_n = list(d["purchased_n"])
    s.purchased = (list(d["purchased"][0]), list(d["purchased"][1]))
    s.reserved = (list(d["reserved"][0]), list(d["reserved"][1]))
    s.reserved_blind = (list(map(bool, d["reserved_blind"][0])), list(map(bool, d["reserved_blind"][1])))
    s.nobles_won = (list(d["nobles_won"][0]), list(d["nobles_won"][1]))
    s.board = list(d["board"])
    s.decks = (list(d["decks"][0]), list(d["decks"][1]), list(d["decks"][2]))
    s.nobles = list(d["nobles"])
    s.turn = d["turn"]; s.phase = d["phase"]; s.pending_nobles = list(d["pending_nobles"])
    s.final_trigger = d["final_trigger"]; s.winner = d["winner"]; s.ply = d["ply"]
    s.win_points = d["win_points"]
    return s


def load(paths):
    by_key = {}
    for p in paths:
        for pat in ([p] if os.path.isfile(p) else glob.glob(p)):
            op = gzip.open(pat, "rt", encoding="utf-8") if pat.endswith(".gz") else open(pat, encoding="utf-8")
            with op as f:
                for line in f:
                    if line.strip():
                        e = json.loads(line)
                        by_key[(json.dumps(e["dump"], sort_keys=True), e["hero"])] = e
    return list(by_key.values())


def qualifies(e, gap_lo, gap_hi, gap_take, types):
    if e.get("forces_sub") or (types and e["answer_type"] not in types):
        return False
    if e["answer_type"] == "take":
        return e["gap"] >= gap_take
    return gap_lo <= e["gap"] <= gap_hi


def build(e):
    s = state_from_dump(e["dump"]); hero = e["hero"]
    best_move = e["move_evals"][0]["move"]
    a_best = next(a for a in E.legal_actions(s) if A.action_to_move(s, a) == best_move)
    meta = {"title": None, "kind": "advantage",
            "difficulty": "Hard" if best_move.get("type") == "reserve" else "Tricky",
            "hand_crafted": False, "source": e.get("source", "ledger"),
            "best_eval": e["best_eval"], "second_eval": e["second_eval"], "gap": round(e["gap"], 3),
            "eval_seeds": 8, "move_evals": e["move_evals"]}
    sol = SimpleNamespace(hero=hero, K=1, line=[(hero, a_best, s.phase)], unique=True)
    puz = schema.build_puzzle(s, sol, opponent="N", meta=meta)
    puz["kind"] = "advantage"
    return puz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=LEDGER)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--gap", type=float, default=0.25)
    ap.add_argument("--gap-hi", type=float, default=0.50)
    ap.add_argument("--gap-take", type=float, default=0.25)
    ap.add_argument("--types", default="buy,reserve,take")
    args = ap.parse_args()

    entries = load([args.ledger])
    print(f"ledger: {len(entries)} verified positions ({dict(Counter(e['answer_type'] for e in entries))})")
    if args.stats or not args.out:
        for at in ("take", "reserve", "buy"):
            gs = sorted((e["gap"] for e in entries if e["answer_type"] == at and not e.get("forces_sub")), reverse=True)
            b = lambda lo, hi=99: sum(1 for g in gs if lo <= g <= hi)
            print(f"  {at:8s}: {len(gs)} playable | >=0.30:{b(0.30) if at=='take' else b(0.30,0.50)} "
                  f">=0.25:{b(0.25) if at=='take' else b(0.25,0.50)} >=0.20:{b(0.20) if at=='take' else b(0.20,0.50)} "
                  f">=0.15:{b(0.15) if at=='take' else b(0.15,0.50)} | top {[round(g,3) for g in gs[:6]]}")
        if not args.out:
            return
    types = set(args.types.split(","))
    keep = [e for e in entries if qualifies(e, args.gap, args.gap_hi, args.gap_take, types)]
    os.makedirs(args.out, exist_ok=True)
    for i, e in enumerate(keep):
        schema.save(build(e), os.path.join(args.out, f"advantage_{args.start + i:04d}.json"))
    print(f"wrote {len(keep)} puzzles ({dict(Counter(e['answer_type'] for e in keep))}) to {args.out}")


if __name__ == "__main__":
    main()
