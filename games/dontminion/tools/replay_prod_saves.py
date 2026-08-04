"""Replay every REAL prod save through the current load path.

THE migration gate. `engine.migrate`'s input is HISTORY, not the current tree,
so tests built by downgrading a current game (tests/test_migrate.py) cannot
synthesize what prod actually holds — run this too whenever the game dict's
shape or the move surface changes. It has already caught, in one run:

  * a schema stamp that didn't partition shapes (prod carries `schema = 2`
    blobs from across two eras; two live games lacked `last_turn_gains`, which
    a version-gated migrate skipped and the kernel then KeyError'd on);
  * a bot livelock on a no-op move (play_all_treasures with only
    MANUAL_TREASURES in hand) that stuck two live games.

Each save is migrated exactly as main.load_game_to_memory does, checked for the
shape the kernel now assumes, then played forward with the bot under the soak's
per-move invariants.

Usage (from the repo root; needs Turso creds in ~/.spender_turso):
    python -m games.dontminion.tools.replay_prod_saves
    python -m games.dontminion.tools.replay_prod_saves --file saves.json
"""

import argparse
import collections
import json
import os
import random
import re
import sys
import urllib.request

from games.dontminion import bot, engine
from core.rooms import decode_state
from games.dontminion import persist

CREDS = os.path.expanduser("~/.spender_turso")
MOVE_CAP = 4000


def fetch_saves():
    """Pull every dontminion blob from the prod Turso DB over the libSQL HTTP
    API (no libsql wheel needed on this box — see the root CLAUDE.md)."""
    blob = open(CREDS, encoding="utf-8").read()
    url = re.search(r"TURSO_DATABASE_URL\s*=\s*(\S+)", blob).group(1).strip('"')
    token = re.search(r"TURSO_AUTH_TOKEN\s*=\s*(\S+)", blob).group(1).strip('"')
    body = json.dumps({"requests": [
        {"type": "execute", "stmt": {"sql": (
            "SELECT id, status, state_json FROM dontminion_games "
            "ORDER BY updated_at DESC")}},
        {"type": "close"},
    ]}).encode()
    req = urllib.request.Request(
        url.replace("libsql://", "https://") + "/v2/pipeline", data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.load(r)["results"][0]["response"]["result"]["rows"]
    return [{"id": r[0]["value"], "status": r[1]["value"], "state": r[2]["value"]}
            for r in rows]


def census(g):
    # engine.pile_cards, not the supply index: it reaches the non-supply piles
    # and unpacks an ORDERED pile into the real cards it holds (a pile's NAME
    # is not a card anyone can own) — see THE PILE MODEL in engine.py
    c = collections.Counter(engine.pile_cards(g))
    c.update(g["trash"])
    for pid in g["players"]:
        c.update(engine.owned_cards(g, pid))
    return c


def check(row):
    """Migrate one save and play it forward. Returns a one-line report."""
    rid, status = row["id"], row["status"]
    # state_json is COMPACTED at rest (packed rng_state) — expand before replaying,
    # or engine._load_rng gets a base64 blob where it wants 625 ints. A row written
    # before compaction carries no marker and passes through untouched.
    saved = persist.expand_state(decode_state(row["state"])).get("game")
    if not isinstance(saved, dict):
        return f"  {rid} {status:8} no game dict (open room) — skipped"
    was = saved.get("schema", 1)

    g = engine.migrate(saved)
    assert g["schema"] == engine.SCHEMA, f"{rid}: schema not bumped"
    once = json.dumps(g, sort_keys=True)
    assert json.dumps(engine.migrate(g), sort_keys=True) == once, f"{rid}: not idempotent"

    # the shape the kernel is allowed to assume post-migrate
    for key in _GAME_KEYS:
        assert key in g, f"{rid}: migrate left {key} missing"
    for pid in g["players"]:
        seat = g["seats"][pid]
        for key in _SEAT_KEYS:
            assert isinstance(seat[key], list), f"{rid}: seat {pid} missing {key}"
        assert isinstance(g["vp_tokens"][pid], int), f"{rid}: no vp_tokens"
    for key in engine._fresh_turn_ctx():
        assert key in g["turn_ctx"], f"{rid}: turn_ctx missing {key}"

    for viewer in list(g["players"]) + [None]:
        view = engine.player_view(g, viewer)
        assert "pending" not in view and "rng_state" not in view, f"{rid}: view leak"
        json.dumps(view)

    if status == "over" or g["over"]:
        return f"  {rid} {status:8} v{was}→{g['schema']} migrated + views OK (finished)"

    baseline, rng, moves = census(g), random.Random(1234), 0
    for _ in range(MOVE_CAP):
        if engine.is_over(g):
            break
        actor = g["pending_pid"] or g["turn"]
        mv = bot.choose(g, actor, rng)
        ok, err = engine.apply_move(g, actor, mv)
        assert ok, f"{rid}: bot move {mv} rejected: {err}"
        moves += 1
        assert census(g) == baseline, f"{rid}: card conservation broken after {mv}"
        if not engine.is_over(g):
            assert engine.legal_moves(g, g["pending_pid"] or g["turn"]), f"{rid}: stranded"
        json.dumps(g)
    assert engine.is_over(g), (
        f"{rid}: no termination in {MOVE_CAP} moves — a no-op move is looping "
        f"(this is exactly how the play_all_treasures livelock showed up)")
    return f"  {rid} {status:8} v{was}→{g['schema']} migrated, played {moves:4} moves → over"


_GAME_KEYS = tuple(engine._GAME_FILLS)
_SEAT_KEYS = ("deck", "hand", "discard", "in_play") + tuple(engine._SEAT_FILLS)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", help="JSON dump of saves instead of querying Turso")
    args = ap.parse_args()

    rows = (json.loads(open(args.file, encoding="utf-8-sig").read())
            if args.file else fetch_saves())
    seen = collections.Counter()
    for row in rows:
        g = persist.expand_state(decode_state(row["state"])).get("game")
        seen[g.get("schema", 1) if isinstance(g, dict) else "none"] += 1
        print(check(row), flush=True)
    print(f"\n{len(rows)} prod saves replayed; schema versions on prod: "
          f"{dict(sorted(seen.items(), key=str))}")
    print("REPLAY PASS")


if __name__ == "__main__":
    sys.exit(main())
