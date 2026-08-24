"""Summarise the EVENT SHAPES in downloaded Tag Team logs.

This is step zero of writing a replayer, and it is the step cob_replay.py had to learn the
hard way: you cannot guess BGA's event names or arg spellings, and a wrong guess fails
SILENTLY (the parser just never matches, the replay stalls, and it looks like a rules bug).
So: dump what is actually there, then write the parser against it.

  python tt_inspect.py                # every log, type histogram + arg keys
  python tt_inspect.py <table_id>     # one table, full ordered event stream

Reads the ACTIVE corpus from scrape_target.py.
"""
import collections
import glob
import json
import os
import sys

import scrape_target as tgt

LOGS = tgt.CORP + "/logs"


def events(path):
    """Flatten a BGA log to (move_id, event). plToIgnore packets are per-recipient echoes."""
    for pkt in json.load(open(path, encoding="utf-8")):
        for d in pkt.get("data", []):
            a = d.get("args", {})
            if isinstance(a, dict) and "plToIgnore" in a:
                continue
            yield (int(pkt["move_id"]) if pkt.get("move_id") is not None else 0, d)


def main():
    paths = sorted(glob.glob(LOGS + "/*.json"))
    if not paths:
        print(f"no logs yet in {LOGS} — the cron fills this.")
        return 1

    if len(sys.argv) > 1:
        p = f"{LOGS}/{sys.argv[1]}.json"
        for mid, d in events(p):
            args = {k: v for k, v in (d.get("args") or {}).items()
                    if k not in ("i18n", "playerName")}
            print(f"[{mid:>4}] {d['type']:<24} {json.dumps(args, default=str)[:200]}")
        return 0

    types = collections.Counter()
    argkeys = collections.defaultdict(collections.Counter)
    sample = {}
    for p in paths:
        for _, d in events(p):
            t = d["type"]
            types[t] += 1
            for k in (d.get("args") or {}):
                argkeys[t][k] += 1
            sample.setdefault(t, d.get("args"))

    print(f"{len(paths)} logs | {sum(types.values())} events | {len(types)} distinct types\n")
    for t, n in types.most_common():
        keys = ", ".join(k for k, _ in argkeys[t].most_common(12))
        print(f"{n:>7}  {t}")
        print(f"         args: {keys or '(none)'}")
        print(f"         e.g.: {json.dumps(sample[t], default=str)[:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
