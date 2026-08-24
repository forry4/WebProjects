#!/usr/bin/env python
"""Search-hyperparameter sweep under COHERENT serving conditions.

Every MCTS knob was tuned (or defaulted) in the PER-SIM determinization era, whose Q-noise masked
them — the same regime shift that voided the policy-prior verdicts and made lower cpuct win. This
sweep re-tests the remaining knobs, each isolated as champion-1-vs-champion-1 with the knob on side
A only, serving-real (coherent + cpuct 1.0 both sides), disjoint seed base 95000.

  E1 MINIMAX  — the big one: deployed select() is MAX-MAX (node.w is root-perspective at every node
                and select maximizes it even at OPPONENT nodes — the opponent is modeled as
                cooperating; found 2026-07-26, spender-core signs by actor). Masked when visits were
                near-uniform; live under coherent concentration. --minimax signs Q by node actor.
  E2 DEPTH    — MAX_TREE_DEPTH=14 caps the tree before rollout; per-sim deep lines were cross-world
                noise, coherent deep lines are real, and prod (~20-60k sims) exceeds 14 plies easily.
  E3 FPU      — unvisited q=0.0-neutral vs AlphaZero-style parent-q-minus-reduction.
  E4 ROLLOUT  — 12-step leaf rollout length was tuned per-sim; a frozen world changes its variance.

Directional ladders (E2/E4) EARLY-STOP on two consecutive declines clearly below best (the k_sweep
rule); few-point argmax sweeps (E3) run in full. Effects that grow with sims (minimax, depth) get a
higher-sims confirm. Winners (>=0.53) combine into one final combo-vs-default gate.

  HP_GAMES=200 HP_SIMS=1500 python hp_sweep.py
"""
import os, re, subprocess

CORE = r"C:/Users/Forrest/forrestm_projects/rust-cores/duel-core"
# Overridable: when the flywheel is running it holds target/release, so point this at the side
# build (target-pool/release) to use a fresher binary without fighting the lock.
GATE = os.environ.get("HP_GATE", CORE + "/target/release/gate_netleaf.exe")
CHAMP0 = CORE + "/src/attn_champion1_frozen.json"
RUN = r"C:/Users/Forrest/duel_run/hp_sweep"
GAMES = int(os.environ.get("HP_GAMES", 200))
SIMS = int(os.environ.get("HP_SIMS", 1500))
DEEP_SIMS = int(os.environ.get("HP_DEEP_SIMS", 6000))
SEED = int(os.environ.get("HP_SEED", 95000))  # disjoint: loops 70000 / pivotal 80000 / runoff+ksweep 90000
MARGIN = 0.04  # early-stop noise guard (~1 SE at 150-200 games)

GATE_RE = re.compile(r"NETLEAF GATE: .*: (\d+\.\d+) \[(\d+\.\d+), (\d+\.\d+)\]")
os.makedirs(RUN, exist_ok=True)

# E0/E1 may have been run EARLY (standalone e1_minimax_now.sh, pre-empting this chain — the
# 2026-07-26 interception: the search verdict had to precede the pivotal harvest). If the summary
# already carries them, skip re-running and ADOPT the verdict: minimax won -> it becomes the BASE
# config for every remaining knob (they should be tuned on the search we'll actually fly).
BASE_MM = {"on": False}


def note(m):
    print(m, flush=True)
    with open(RUN + "/summary.txt", "a") as f:
        f.write(m + "\n")


def gate(a_extra, b_extra, games, sims):
    """champion-1 both sides, coherent+cpuct1.0 both sides unless overridden in extras."""
    base_a = ["--coherent", "--cpuct", "1.0"] + (["--minimax"] if BASE_MM["on"] else [])
    base_b = ["--coherent-b", "--cpuct-b", "1.0"] + (["--minimax-b"] if BASE_MM["on"] else [])
    cmd = ([GATE, "--leaf", "attnfile", "--attn-file", CHAMP0] + base_a + a_extra +
           ["--leaf-b", "attnfile2", "--attn-file-b", CHAMP0] + base_b + b_extra +
           ["--sims", str(sims), "--games", str(games), "--seed", str(SEED)])
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = GATE_RE.search(r.stdout or "")
    if not m:
        note(f"  GATE FAIL: {(r.stdout or '')[-200:]} {(r.stderr or '')[-150:]}")
        return None, None, None
    return float(m.group(1)), float(m.group(2)), float(m.group(3))


def measured(name, p):
    """A point already in the summary from an earlier (interrupted) run, or None.

    RESUMABILITY (2026-07-28): these 6000-sim gates cost 70-95 MINUTES each and the run was
    interrupted twice in one day, each time re-measuring points that were already banked. The
    gates are deterministic — same seed base, same binary, same config — so a logged value is
    exactly what a re-run would produce. Only adopt REAL numbers: the 2026-07-27 invalidation
    wrote 'None' rows for killed gates, and re-adopting those would relaunch that whole disaster.
    """
    try:
        prior = open(RUN + "/summary.txt").read()
    except OSError:
        return None
    m = re.search(rf"^\s*{re.escape(name)}={re.escape(str(p))}\s+vs default = ([0-9.]+)",
                  prior, re.M)
    return float(m.group(1)) if m else None


def ladder(name, points, mk_extra, games, sims):
    """Directional sweep with the early-stop rule. Returns {point: winrate}."""
    results, prev, best_v, best_p, declines = {}, None, -1.0, None, 0
    for p in points:
        done = measured(name, p)
        if done is not None:
            v, lo, hi = done, None, None
            note(f"  {name}={p:<4} ADOPTED from an earlier run = {v}  (deterministic gate, not re-run)")
        else:
            v, lo, hi = gate(mk_extra(p), [], games, sims)
            note(f"  {name}={p:<4} vs default = {v} [{lo}, {hi}]  ({games}g @{sims} sims)")
        # BUG FIX 2026-07-29: the adoption edit dropped this line, so `results` came back EMPTY and
        # main()'s winner detection saw nothing — it printed "no knob cleared 0.53" while rollout=0
        # had just measured 0.6100. Exactly the same failure shape as the 2026-07-27 taskkill: a
        # confident no-winner verdict synthesised from an empty set. The measured numbers were in
        # the summary the whole time; only the machine-readable path was severed.
        results[p] = v
        if v is None:
            continue
        declines = declines + 1 if (prev is not None and v < prev) else 0
        if v > best_v:
            best_v, best_p = v, p
        if declines >= 2 and v < best_v - MARGIN:
            note(f"  EARLY STOP: {declines} consecutive declines, {v:.4f} << best {name}={best_p}={best_v:.4f}")
            break
        prev = v
    return results


def main():
    note(f"=== HP SWEEP: coherent-era search knobs (champion-1 self-A/B, knob on side A, seed {SEED}) ===")
    winners = []  # (extra_args, label, winrate)

    prior = ""
    try:
        prior = open(RUN + "/summary.txt").read()
    except OSError:
        pass
    e1_done = "E1a" in prior

    def early_val(tag):
        m = re.search(tag + r" [^=]*= ([0-9.]+)", prior)
        return float(m.group(1)) if m else None

    if e1_done:
        vals = [v for v in (early_val("E1a"), early_val("E1b")) if v is not None]
        BASE_MM["on"] = bool(vals) and max(vals) >= 0.53
        note(f"E0/E1 already run early (E1a={early_val('E1a')} E1b={early_val('E1b')}) — "
             f"adopting minimax={'ON' if BASE_MM['on'] else 'OFF'} as the BASE for the remaining knobs")
        if BASE_MM["on"] and "base sanity" not in prior:
            # With BASE_MM on the plain gate is already minimax-vs-minimax — a symmetric sanity
            # (must straddle 0.5) doubling as the E1 depth-confirm's mirror at DEEP sims.
            # RESUMABLE (2026-07-28): this gate cost 165 MINUTES measured, and it is a property of
            # the HARNESS, not of any knob — re-running it on every restart is pure overhead. Once
            # the summary carries it, adopt it. (The run was interrupted twice today; without this
            # guard each restart pays 2h45m before measuring anything.)
            vc, loc, _ = gate([], [], 150, DEEP_SIMS)
            note(f"  base sanity minimax-vs-minimax @{DEEP_SIMS} sims = {vc} [{loc}, ..] (must straddle 0.5)")
        elif BASE_MM["on"]:
            m = re.search(r"base sanity[^=]*= ([0-9.]+)", prior)
            note(f"  base sanity ADOPTED from a previous run = {m.group(1) if m else '?'} "
                 f"(harness property, already measured @{DEEP_SIMS} sims — not re-run)")
    else:
        # E0 — noise floor: identical configs must read ~0.5; the yardstick for everything below.
        v, lo, hi = gate([], [], GAMES, SIMS)
        note(f"E0 noise floor (default vs default) = {v} [{lo}, {hi}]  (must straddle 0.5)")

        # E1 — MINIMAX selection (the max-max fix). Expected to matter MORE at lower cpuct / higher
        # sims (both concentrate visits — when the cooperating-opponent model actually distorts).
        note("E1 MINIMAX select:")
        v1, lo1, _ = gate(["--minimax"], [], max(GAMES, 300), SIMS)
        note(f"  minimax vs max-max @cpuct1.0 = {v1} [{lo1}, ..]  ({max(GAMES, 300)}g @{SIMS} sims)")
        v2, lo2, _ = gate(["--minimax", "--cpuct", "0.3"], ["--cpuct-b", "0.3"], GAMES, SIMS)
        note(f"  minimax vs max-max @cpuct0.3 = {v2} [{lo2}, ..]  (higher concentration)")
        best_mm = max([x for x in (v1, v2) if x is not None], default=None)
        if best_mm is not None and best_mm >= 0.53:
            vc, loc, _ = gate(["--minimax"], [], 150, DEEP_SIMS)
            note(f"  CONFIRM minimax @{DEEP_SIMS} sims = {vc} [{loc}, ..]  (does the edge grow with depth?)")
            winners.append((["--minimax"], "minimax", best_mm))

    # E2 — in-tree depth cap ladder at DEEP sims (the 14-ply cap binds only when the tree is deep).
    note(f"E2 DEPTH cap (default 14) @{DEEP_SIMS} sims:")
    # 40 DROPPED 2026-07-28: max-depth 24 measured EXACTLY 0.5000 [0.444, 0.556] over 300 plays.
    # An exact 0.5 with a symmetric CI means the two sides played identically, i.e. the default
    # 14-ply cap never binds even at 6000 sims — so raising it changed nothing. A cap that does
    # not bind at 24 cannot bind at 40; the point costs ~80 min to re-confirm a tautology. If the
    # sim count ever rises far enough that trees genuinely exceed 14 plies, restore it.
    dres = ladder("max-depth", [24], lambda d: ["--max-depth", str(d)], 150, DEEP_SIMS)
    dbest = max((p for p, v in dres.items() if v is not None), key=lambda p: dres[p], default=None)
    if dbest is not None and dres[dbest] >= 0.53:
        winners.append((["--max-depth", str(dbest)], f"max-depth {dbest}", dres[dbest]))

    # E4 — rollout-steps ladder (12 default -> shorter). One direction; early-stop applies.
    note("E4 ROLLOUT steps (default 12):")
    rres = ladder("rollout", [6, 2, 0], lambda s: ["--rollout-steps", str(s)], GAMES, SIMS)
    rbest = max((p for p, v in rres.items() if v is not None), key=lambda p: rres[p], default=None)
    if rbest is not None and rres[rbest] >= 0.53:
        winners.append((["--rollout-steps", str(rbest)], f"rollout {rbest}", rres[rbest]))

    # E3 — FPU reduction (argmax-type, few points, run in full).
    note("E3 FPU reduction (default neutral-0):")
    fres = {}
    for r in (0.2, 0.5):
        v, lo, hi = gate(["--fpu", str(r)], [], GAMES, SIMS)
        fres[r] = v
        note(f"  fpu={r} vs neutral = {v} [{lo}, {hi}]")
    fbest = max((p for p, v in fres.items() if v is not None), key=lambda p: fres[p], default=None)
    if fbest is not None and fres[fbest] >= 0.53:
        winners.append((["--fpu", str(fbest)], f"fpu {fbest}", fres[fbest]))

    # COMBO — stack every individual winner and re-verify against the plain default.
    if len(winners) >= 2:
        combo = [a for w in winners for a in w[0]]
        v, lo, hi = gate(combo, [], 400, SIMS)
        note(f"COMBO {'+'.join(w[1] for w in winners)} vs default = {v} [{lo}, {hi}]  (400g)")
    elif len(winners) == 1:
        note(f"single winner: {winners[0][1]} at {winners[0][2]:.4f} (already measured)")
    else:
        note("no knob cleared 0.53 — the coherent-era defaults stand")
    note("=== HP SWEEP COMPLETE ===")


if __name__ == "__main__":
    main()
