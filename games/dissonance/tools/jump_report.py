"""The jump-bonus study's report: Expert self-play under the uncapped auction.

Reads `auction_arena.py` CHECKPOINT files (ARENA_CKPT) and prints the profile
the 2026-08-13 rule change was measured by: classic dropped the `MAX_RAISE` cap
and prices the FINAL bid's level jump instead (+`JUMP_SET_BONUS` per level to
the defender on a set). Everything here is computed from the settled event's
own fields -- the payoff signed for the declarer and the auction's level
sequence both ride on it since this study.

A MIRROR RUN'S TWO FLIPS ARE IDENTICAL (same tier both seats, and the
`Solved` cache is keyed on the cards), so this reads FLIP 0 ONLY -- every
count below is unique rounds, not the doubled raw counters the SHARD lines
carry.

    PYTHONPATH=. python3 games/dissonance/tools/jump_report.py shard0.ckpt ...
"""
import collections
import json
import statistics
import sys


def mean(xs):
    return statistics.mean(xs) if xs else 0.0


def pct(n, d):
    return f"{100.0 * n / d:5.1f}%" if d else "    --"


def main(paths):
    rounds = []          # one dict per unique round (flip 0)
    decisions = collections.Counter()
    doubles = collections.Counter()
    for path in paths:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            events = r["events"][0] if r.get("events") else []
            for e in events:
                if e[0] == "decision":
                    decisions[e[2]] += 1
                elif e[0] == "double":
                    doubles["on" if e[2] else "off"] += 1
                elif e[0] == "settled":
                    if len(e) < 12:
                        raise SystemExit("checkpoint predates the payoff/levels "
                                         "fields -- re-run the arena")
                    rounds.append({
                        "level": e[2], "outcome": e[3], "doubled": e[4],
                        "open": e[5], "denom": e[7], "price": e[8],
                        "n_bids": e[9], "payoff": e[10], "levels": e[11],
                    })
    n = len(rounds)
    print(f"\n=== {n} unique Expert-vs-Expert rounds "
          f"(classic, k=8 one tree, dd-resolved, flip 0 of each paired deal) ===")

    # --- auction length -----------------------------------------------------
    lens = collections.Counter(r["n_bids"] for r in rounds)
    print(f"\nAVG BIDS PER AUCTION: {mean([r['n_bids'] for r in rounds]):.2f}")
    print("  bids:  " + "  ".join(f"{k}:{pct(v, n)}" for k, v in sorted(lens.items())))
    print(f"  contested (>1 bid): {pct(sum(v for k, v in lens.items() if k > 1), n)}"
          f"   opener re-enters (>=3 bids): {pct(sum(v for k, v in lens.items() if k >= 3), n)}"
          f"   opener declares (odd bids): "
          f"{pct(sum(1 for r in rounds if r['n_bids'] % 2 == 1), n)}")

    # --- opening / settled distributions ------------------------------------
    opens = collections.Counter(r["open"] for r in rounds)
    settle = collections.Counter(r["level"] for r in rounds)
    top = max(max(opens), max(settle))
    hdr = "  ".join(f"{l:>6}" for l in range(1, top + 1))
    print(f"\nOPENING LEVEL       {hdr}")
    print("  share             " + "  ".join(pct(opens.get(l, 0), n) for l in range(1, top + 1)))
    print(f"  mean {mean([r['open'] for r in rounds]):.2f}  median {statistics.median([r['open'] for r in rounds])}")
    print(f"\nSETTLED LEVEL       {hdr}")
    print("  share             " + "  ".join(pct(settle.get(l, 0), n) for l in range(1, top + 1)))
    print(f"  mean {mean([r['level'] for r in rounds]):.2f}  median {statistics.median([r['level'] for r in rounds])}")

    # --- open -> settled matrix ---------------------------------------------
    print(f"\nOPEN -> SETTLED (row %, per opening level)")
    print(f"  open\\settled      {hdr}      n")
    for o in sorted(opens):
        row = [r for r in rounds if r["open"] == o]
        cells = collections.Counter(r["level"] for r in row)
        print(f"  {o:>4}              "
              + "  ".join(pct(cells.get(l, 0), len(row)) for l in range(1, top + 1))
              + f"  {len(row):>5}")

    # --- outcomes / doubling / sacrifice per settled level -------------------
    def decl_score(r):
        return max(r["payoff"], 0)

    def def_score(r):
        return max(-r["payoff"], 0)

    print("\nPER SETTLED LEVEL (avg score = match points actually paid; "
          "declarer/defender)")
    print("  lvl     n   made%   set%  null%   dbl%   sac%   avg made pay   "
          "avg set pay   avg payoff")
    for l in sorted(settle):
        row = [r for r in rounds if r["level"] == l]
        made = [r for r in row if r["outcome"] == "made"]
        set_ = [r for r in row if r["outcome"] == "set"]
        null = [r for r in row if r["outcome"] == "null"]
        dbl = [r for r in row if r["doubled"]]
        sac = [r for r in row if r["price"] == "sacrifice"]
        print(f"  {l:>3} {len(row):>5}  {pct(len(made), len(row))} {pct(len(set_), len(row))}"
              f" {pct(len(null), len(row))} {pct(len(dbl), len(row))} {pct(len(sac), len(row))}"
              f"   {mean([decl_score(r) for r in made]):6.1f} / 0     "
              f"  0 / {mean([def_score(r) for r in set_]):6.1f}"
              f"   {mean([r['payoff'] for r in row]):+7.2f}")

    # --- outcomes overall ----------------------------------------------------
    out = collections.Counter(r["outcome"] for r in rounds)
    print(f"\nOUTCOMES: made {pct(out['made'], n)}  set {pct(out['set'], n)}  "
          f"null {pct(out['null'], n)}")
    print(f"  avg payoff (declarer-signed) {mean([r['payoff'] for r in rounds]):+.2f}"
          f"   avg declarer score {mean([decl_score(r) for r in rounds]):.2f}"
          f"   avg defender score {mean([def_score(r) for r in rounds]):.2f}")

    # --- doubling ------------------------------------------------------------
    opp = doubles["on"] + doubles["off"]
    dbl_rounds = [r for r in rounds if r["doubled"]]
    und = [r for r in rounds if not r["doubled"]]
    print(f"\nDOUBLING: taken {pct(doubles['on'], opp)} of {opp} opportunities; "
          f"{pct(len(dbl_rounds), n)} of rounds")
    for label, rows in (("doubled", dbl_rounds), ("undoubled", und)):
        if not rows:
            continue
        made = [r for r in rows if r["outcome"] == "made"]
        set_ = [r for r in rows if r["outcome"] == "set"]
        null = [r for r in rows if r["outcome"] == "null"]
        print(f"  {label:>9}: n {len(rows):>4}  made {pct(len(made), len(rows))}"
              f" (declarer avg {mean([decl_score(r) for r in made]):6.1f})"
              f"  set {pct(len(set_), len(rows))}"
              f" (defender avg {mean([def_score(r) for r in set_]):6.1f})"
              f"  null {pct(len(null), len(rows))}"
              f"  avg payoff {mean([r['payoff'] for r in rows]):+6.2f}")
    if dbl_rounds:
        m = mean([r["payoff"] for r in dbl_rounds])
        who = "the DECLARER" if m > 0 else "the DEFENDER"
        print(f"  doubled rounds pay {m:+.2f} on average -> the bet benefits {who}")

    # --- sacrifice -----------------------------------------------------------
    sac = [r for r in rounds if r["price"] == "sacrifice"]
    print(f"\nSACRIFICE (declarer's own search priced the final bid negative "
          f"over an available pass):")
    print(f"  {pct(len(sac), n)} of rounds; decisions: sacrifice "
          f"{decisions['sacrifice']}, positively-priced bid {decisions['bid_positive']}, "
          f"forced open {decisions['forced_open']}, pass {decisions['passed']}")
    if sac:
        print(f"  avg payoff {mean([r['payoff'] for r in sac]):+.2f} "
              f"(declarer avg {mean([decl_score(r) for r in sac]):.2f}, "
              f"defender avg {mean([def_score(r) for r in sac]):.2f}); "
              f"doubled {pct(sum(r['doubled'] for r in sac), len(sac))}")

    # --- raises and jumps ----------------------------------------------------
    # Every non-opening bid's rise over the level it overtook: 0 is a
    # same-level overtake, 1 a step, >=2 a JUMP. The FINAL bid's rise is what
    # the set bonus charges for.
    all_deltas = collections.Counter()
    jumps_by_open = collections.Counter()   # opening level -> total jumps (>=2)
    raises_by_open = collections.Counter()  # opening level -> total raises
    rounds_by_open = collections.Counter()
    jump_sizes = collections.Counter()
    final_jump = collections.Counter()
    for r in rounds:
        seq = r["levels"]
        rounds_by_open[r["open"]] += 1
        deltas = [b - a for a, b in zip(seq, seq[1:])]
        for d in deltas:
            all_deltas[d] += 1
            raises_by_open[r["open"]] += 1
            if d >= 2:
                jumps_by_open[r["open"]] += 1
                jump_sizes[d] += 1
        # The CHARGED final rise -- v2 semantics: the opening is a raise over
        # level 0, so a passed-out opening is charged its whole level.
        final_jump[seq[-1] - (seq[-2] if len(seq) > 1 else 0)] += 1
    total_over = sum(all_deltas.values())
    print(f"\nOVERTAKES: {total_over} across {n} auctions "
          f"({total_over / n:.2f} per auction)")
    print("  rise sizes (0 = same-level overtake): "
          + "  ".join(f"+{k}:{v} ({pct(v, total_over)})"
                      for k, v in sorted(all_deltas.items())))
    print(f"  JUMPS (rise >= 2): {sum(jump_sizes.values())} "
          f"({pct(sum(jump_sizes.values()), total_over)} of overtakes); sizes: "
          + "  ".join(f"+{k}:{v}" for k, v in sorted(jump_sizes.items())))
    print("\n  jumps per auction by OPENING level:")
    print("  open      n   overtakes/auction   jumps/auction   jump share of overtakes")
    for o in sorted(rounds_by_open):
        ro = rounds_by_open[o]
        print(f"  {o:>4}  {ro:>5}   {raises_by_open[o] / ro:>17.2f}"
              f"   {jumps_by_open[o] / ro:>13.2f}"
              f"   {pct(jumps_by_open[o], raises_by_open[o]):>18}")
    print("\n  FINAL bid's rise (what the set bonus charges; the opening "
          "counts from level 0, so 0 = same-level overtake only):")
    print("    " + "  ".join(f"+{k}:{v} ({pct(v, n)})"
                             for k, v in sorted(final_jump.items())))


if __name__ == "__main__":
    main(sys.argv[1:])
