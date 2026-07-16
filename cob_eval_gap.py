"""Quantify the EXPERT GAP: when a top player disagrees with our net, who was right?

Agreement rate can't answer this (see cob_analyze_both.py: our net agrees ~43% with the top
player AND ~43% with their opponent -- the test has no strength spread to discriminate).
This measures the thing that matters instead: the VALUE our own deep search assigns to the
pro's move vs the value it assigns to our net's pick.

Method, at each clean top-player decision where pro_move != our_move:
    V_pro  = -eval(child after the pro's move)      # negamax: child is the opponent to move
    V_ours = -eval(child after our net's move)
    delta  = V_pro - V_ours                          # >0 => the pro's move is better BY OUR OWN EVAL

Why apply-and-re-search rather than one root search's edge-Q: PUCT starves the runner-up, so
edge-Q overstates gaps and gets worse with sims. Visit counts pick a move; they can't price it.

THE CIRCULARITY, STATED HONESTLY: the referee is our own net, so it cannot see a weakness it
shares. Two guards:
  * The referee searches at REF_SIMS >> the play budget. CoC's sims ladder shows real strength
    still climbing to the ~4-8k knee, so a deep referee genuinely out-plays a shallow pick --
    that headroom is what lets it overrule our own move at all.
  * A positive mean delta is therefore a LOWER BOUND on the gap: it counts only the pro moves
    our own eval can already recognise as better. Blind spots we share stay invisible, so the
    true gap can only be larger. A delta of ~0 is the ambiguous case (either parity, or a
    shared blind spot) -- it does NOT prove parity.

Usage: python cob_eval_gap.py [ref_sims] [play_sims] [max_games]
"""
import collections
import contextlib
import copy
import glob
import io
import json
import math
import os
import random
import subprocess
import sys

import cob_replay
from cob_analyze import move_key, rank_map
from games.castles_of_crimson import engine
from games.castles_of_crimson.az import compact, bridge

CORP = "C:/Users/Forrest/CoB_corpus"
LOGS, MANIFEST = CORP + "/logs", CORP + "/manifest.json"
BIN = "C:/Users/Forrest/forrestm_projects-cobmining/coc-core/target/release/"
MOVE_EXE, EVAL_EXE = BIN + "move_server_coc.exe", BIN + "eval_server_coc.exe"
MODEL = "C:/Users/Forrest/coc_run_4animal/pv_warm936.json"

REF_SIMS = int(sys.argv[1]) if len(sys.argv) > 1 else 4000     # referee (deep)
PLAY_SIMS = int(sys.argv[2]) if len(sys.argv) > 2 else 800     # our net's own pick
MAX_GAMES = int(sys.argv[3]) if len(sys.argv) > 3 else 999


class Srv:
    def __init__(self, exe, *extra):
        self.exe = [exe, MODEL, *extra]
        self.p = None
        self.seed = 1

    def _start(self):
        self.p = subprocess.Popen(self.exe, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, bufsize=1, encoding="utf-8")

    def ask(self, proj, sims):
        if self.p is None or self.p.poll() is not None:
            self._start()
        try:
            self.p.stdin.write(json.dumps({"proj": proj, "sims": sims, "seed": self.seed},
                                          separators=(",", ":")) + "\n")
            self.p.stdin.flush()
            self.seed += 1
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("server died")
            return json.loads(line)
        except Exception:
            try: self.p.kill()
            except Exception: pass
            self.p = None
            raise


def main():
    mover, refer = Srv(MOVE_EXE), Srv(EVAL_EXE)
    ranks = rank_map()
    man = json.load(open(MANIFEST))
    RNG = random.Random(12345)
    deltas = []
    rand_deltas = []
    by_phase = collections.defaultdict(list)
    by_type = collections.defaultdict(list)
    n_dec = [0]

    def eval_after(g, pid, move):
        """Value of `move` to `pid`: apply it, evaluate the child, convert to pid's view.

        The referee reports from the CHILD ACTOR's perspective. CoC turns are multi-action, so
        the child is often STILL pid to move -- negating unconditionally would flip the sign on
        exactly those. Compare seats explicitly.
        """
        gg = copy.deepcopy(g)
        ok, _ = engine.apply_move(gg, pid, move)
        if not ok:
            return None
        r = refer.ask(compact.project(gg), REF_SIMS)
        v, child_actor = float(r["value"]), int(r["actor"])
        my_seat = gg["order"].index(pid)
        return v if child_actor == my_seat else -v

    games = sorted(glob.glob(LOGS + "/*.json"))[:MAX_GAMES]
    for p in games:
        tid = os.path.basename(p)[:-5]
        entry = man.get(tid, {})
        pl = [x for x in entry.get("players", "").split(",") if x]
        if len(pl) != 2:
            continue
        top = min(pl, key=lambda x: ranks.get(x, 999))

        def on_move(g, pid, move, tag, _t=top):
            if pid != _t or g.get("phase") != "playing" or g.get("pending_kind"):
                return
            legal = engine.legal_moves(g, pid)
            if len(legal) < 2:
                return
            hk = move_key(move)
            if hk not in {move_key(m) for m in legal}:
                return
            n_dec[0] += 1
            try:
                ours = bridge.compact_to_move(g, pid, mover.ask(compact.project(g), PLAY_SIMS)["move"])
            except Exception:
                return
            if move_key(ours) == hk:
                return                       # agreement -> nothing to price
            # RANDOM CONTROL. V_our is an argmax chosen by a search sharing the referee's net,
            # so the referee systematically confirms it -- a maximization bias that pushes any
            # delta negative no matter who is better. Pricing a random OTHER legal move under
            # the identical procedure measures that floor: it is the score of a move nobody
            # selected. Read delta_pro RELATIVE to delta_rand, not against 0.
            others = [m for m in legal if move_key(m) not in (hk, move_key(ours))]
            rnd = RNG.choice(others) if others else None
            try:
                v_pro = eval_after(g, pid, move)
                v_our = eval_after(g, pid, ours)
                v_rnd = eval_after(g, pid, rnd) if rnd is not None else None
            except Exception:
                return
            if v_pro is None or v_our is None:
                return
            d = v_pro - v_our
            deltas.append(d)
            if v_rnd is not None:
                rand_deltas.append(v_rnd - v_our)
            by_phase[g.get("phase_letter")].append(d)
            by_type[move.get("type")].append(d)

        try:
            with contextlib.redirect_stdout(io.StringIO()):
                cob_replay.main(p, verbose=False, on_move=on_move)
        except Exception:
            continue
        if deltas:
            m = sum(deltas) / len(deltas)
            print(f"  {tid}: disagreements priced {len(deltas):<4} running mean delta {m:+.4f}",
                  flush=True)

    for s in (mover, refer):
        try:
            if s.p: s.p.terminate()
        except Exception:
            pass

    if not deltas:
        print("no priced disagreements")
        return
    n = len(deltas)
    mean = sum(deltas) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in deltas) / max(1, n - 1))
    se = sd / math.sqrt(n)
    print(f"\n=== EXPERT GAP (referee {REF_SIMS} sims, our play {PLAY_SIMS} sims) ===")
    print(f"top-player decisions seen : {n_dec[0]}")
    print(f"disagreements priced      : {n}  ({n/max(1,n_dec[0])*100:.0f}%)")
    print(f"mean delta (V_pro - V_our): {mean:+.4f}  +-{1.96*se:.4f}")
    print(f"pro's move better in       : {sum(1 for x in deltas if x > 0)}/{n} "
          f"({sum(1 for x in deltas if x > 0)/n*100:.0f}%)")
    if rand_deltas:
        rn = len(rand_deltas); rm = sum(rand_deltas) / rn
        rsd = math.sqrt(sum((x - rm) ** 2 for x in rand_deltas) / max(1, rn - 1))
        rse = rsd / math.sqrt(rn)
        print(f"RANDOM control (V_rand-V_our): {rm:+.4f}  +-{1.96*rse:.4f}   <- the argmax-bias floor")
        lift = mean - rm
        lse = math.sqrt(se**2 + rse**2)
        print(f"pro ABOVE random             : {lift:+.4f}  +-{1.96*lse:.4f}")
    verdict = ("STRENGTH GAP (lower bound): the pro's moves out-evaluate ours by OUR OWN referee"
               if mean > 1.96 * se else
               "no significant gap detectable BY OUR OWN EVAL -- ambiguous (parity, or a shared blind spot)")
    print(f"verdict: {verdict}")
    print("\n--- by phase ---")
    for k in "ABCDE":
        v = by_phase.get(k, [])
        if v: print(f"  {k}: n={len(v):<4} mean {sum(v)/len(v):+.4f}")
    print("--- by move type (pro's move) ---")
    for k, v in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        if len(v) >= 5: print(f"  {k:<18} n={len(v):<4} mean {sum(v)/len(v):+.4f}")


if __name__ == "__main__":
    main()
