"""Replay a BGA Tag Team log through our own engine (games/rag_tag).

TWO JOBS, and the first one is the point:
  1. ENGINE PARITY. Every log that replays to the recorded winner is a real game BGA and our
     engine agree about. Every divergence names a rule we have wrong, with a reproduction.
     This is a stronger check than the unit suite because it is adversarial in the right way:
     top humans reach positions nobody writes a test for.
  2. TRAINING ROWS. The same drive loop, with `on_move`, is the harvest hook.

THE HARD PART IS NOT THE MOVES, IT IS THE RANDOMNESS. rag_tag's engine shuffles in exactly
two places (engine.py: `r.shuffle(draft)` and `r.shuffle(build)`), and a replay cannot seed
its way to the same order. Both must be OVERRIDDEN from what the log reveals -- the same
trick cob_replay.py used for CoB's dice:

  * DRAFT HANDS  -- forced once, from whatever the log shows each player was offered.
  * BUILD DECK   -- forced LAZILY. We never learn the full shuffled order, only the three
    cards offered each BUILD step, so instead of reconstructing the deck we reorder it just
    before each draw so its top three ARE the observed offer. Cards not kept go to the
    BOTTOM (engine.py:1197), so the tail order matters and is preserved.

DECISIONS ARE FEW, which is what makes this tractable: the FIGHT step resolves automatically
(both players flip simultaneously), so the only player choices are draft / order / build /
character -- exactly engine.legal_moves' four kinds.

STATUS: the engine-driving half is written and correct against rag_tag's API. The BGA-parsing
half (`parse_actions`) is DELIBERATELY UNIMPLEMENTED -- run tt_inspect.py against real logs
first and fill it in from what is actually there. Guessing event names is how you get a
parser that silently matches nothing.

  python tt_replay.py <table_id> [-v]
"""
import json
import os
import sys

from games.rag_tag import engine

from games.rag_tag.tools import bga_inspect as tt_inspect
from games.rag_tag.tools import bga_oracle as tt_oracle

# The corpus lives OUTSIDE the repo (BGA table logs, ~9MB per 100 games) — override with
# TAGTEAM_CORPUS. The `cob-mining` branch's scraper writes it; nothing here downloads.
CORP = os.environ.get("TAGTEAM_CORPUS", "C:/Users/Forrest/TagTeam_corpus")
LOGS = CORP + "/logs"
SEATS = ["p0", "p1"]


# ── the BGA half — written against real logs (tt_inspect.py), not guessed ────────────
import collections
from games.rag_tag.fighters import CARDS, FIGHTERS, ROSTER



BGA_TO_FID = {v["bga_id"]: k for k, v in FIGHTERS.items()}

# BGA's `typeArg` is an ART id, NOT our card id, and the two diverge exactly where a card has
# two copies: CARDS[10] (golem, "Protect the Innocent", copies 2) carries art_ids [10, 15], so
# BGA calls the second copy 15 and we have no cid 15 at all. 78 art ids -> 74 cards, 4 of them
# doubled — which matches the "78 card faces" the package docs cite.
#
# Assuming typeArg == cid therefore worked for ~95% of cards and failed only on the four
# duplicated ones, surfacing as "card 15 not in offer+deck" — a lookup miss dressed up as a
# deck-state bug. Map through art_ids.
ART_TO_CID = {int(a): cid
              for cid, c in CARDS.items()
              for a in (c.get("art_ids") or [cid])}


def _cid(card):
    """BGA card dict -> our card id."""
    return ART_TO_CID[int(card["typeArg"])]


def _seat_map(events, manifest_row):
    """BGA player id -> our seat index, in the manifest's player order."""
    return {pid: i for i, pid in enumerate(manifest_row["players"].split(","))}


def _drafts(events, seats):
    """[(seat, fid), ...] in pick order — two per seat, round 1 then round 2."""
    out = []
    for _mid, d in events:
        if d["type"] != "fighterDrafted":
            continue
        a = d["args"]
        pid = str(a["playerId"])
        fid = BGA_TO_FID.get((a.get("fighter") or {}).get("typeArg"))
        if pid in seats and fid:
            out.append((seats[pid], fid))
    return out


def _reconstruct_hands(picks):
    """Draft hands consistent with the observed picks.

    The real hands are not in the log, but the draft PASSES: pick 1 of 6, leftovers swap,
    pick a second. So a seat's SECOND pick must have started in the OPPONENT's hand. That
    fully determines which hand each pick came from; the other eight fighters are padding.

    NOTE FOR HARVESTING: padding is invented, so a draft decision harvested from this is a
    choice over a partly fictional option set. Fine for engine parity (teams end up right);
    do NOT train a draft policy on it without recovering the true hands.
    """
    first = {s: f for s, f in picks[:2]}
    second = {s: f for s, f in picks[2:]}
    hands = {0: [first[0], second[1]], 1: [first[1], second[0]]}
    used = set(hands[0]) | set(hands[1])
    pad = [f for f in ROSTER if f not in used]
    hands[0] += pad[:4]
    hands[1] += pad[4:8]
    return [hands[0], hands[1]]


def _steps(events, fid_seat):
    """The real per-seat step sequence, in log order.

    THE PRIVATE PACKETS ARE AUTHORITATIVE. updateBuildDeckArgs arrives in two flavours: a
    move_id-0 packet carrying `drawnCards` (the acting player's own view) and a move_id-
    bearing one with `drawnCards` stripped (what the opponent may see). Counting them settles
    which to trust — one game had 15 private build packets against only 7 public ones, so the
    public stream is a PARTIAL duplicate and driving off it silently dropped over half the
    builds ("ran out of plan in phase=build").

    Getting here cost three wrong models in a row — "no drawnCards means order step", then
    "first packet per seat is the order step", then "move_id packets are the sequence". Each
    was refuted by counting rather than by reasoning; the counts were available the whole
    time. Reach for them earlier next time.

      * BUILD  — any packet with drawnCards; the offer is drawnCards + addedCard.
      * ORDER  — addedCard is a STARTING card (those begin in the Fight Deck and never enter
                 the Build Deck), once per seat; later views of it are duplicates.

    Yields (mid, seat, kind, args, drawn) in log order.
    """
    ordered, out, seen = set(), [], set()
    for mid, d in events:
        if d["type"] != "updateBuildDeckArgs":
            continue
        a = d["args"]
        added = a.get("addedCard")
        if not added:
            continue
        seat = fid_seat.get(BGA_TO_FID.get(added.get("type")))
        if seat is None:
            continue
        drawn = a.get("drawnCards")
        if drawn:
            # BGA re-sends identical packets. Without this the same build is replayed twice,
            # the two seats stop pairing up round by round, and the second submission comes
            # back with an EMPTY legal list — the tell for "this seat already moved".
            sig = (seat, tuple(sorted((c.get("type"), c.get("typeArg")) for c in drawn)),
                   (added.get("type"), added.get("typeArg")),
                   added.get("locationArg"), len(a.get("deck") or []))
            if sig in seen:
                continue
            seen.add(sig)
            out.append((mid, seat, "build", a, drawn))
        elif CARDS[_cid(added)].get("starting") and seat not in ordered:
            ordered.add(seat)
            out.append((mid, seat, "order", a, None))
    return out


def _character_choices(events):
    """fid -> [character ids, in the order the log first reveals them].

    A fighter with Characters (the Fey Folk) picks one before anything else, and our engine
    models that as a `choose_character` pending that blocks the whole game until answered.
    BGA records it as `fighterSpecificState.activeTrack` flipping from null to a 1-based track
    number, so track N is that fighter's Nth character in board order.
    """
    out, last = collections.defaultdict(list), {}
    for _mid, d in events:
        if d["type"] != "updateCardAndFighterData":
            continue
        for f in (d["args"].get("allFighters") or []):
            fid = BGA_TO_FID.get(f.get("typeArg"))
            st = f.get("fighterState") or {}
            spec = st.get("fighterSpecificState") if isinstance(st, dict) else None
            track = spec.get("activeTrack") if isinstance(spec, dict) else None
            if fid is None or not track:
                continue
            chars = FIGHTERS[fid].get("characters") or []
            # Record every TRANSITION, not every distinct value. The Fey Folk switch
            # Character repeatedly and can return to one they held before, so deduping on
            # (fighter, track) silently dropped the repeats and the replay ran out of answers
            # mid-game — it stopped at 12 moves instead of 4, which looked like progress
            # rather than a truncated table.
            if 1 <= int(track) <= len(chars) and last.get(fid) != int(track):
                last[fid] = int(track)
                out[fid].append(chars[int(track) - 1]["id"])
    return out


def parse_actions(events, manifest_row):
    """BGA events -> ordered replay instructions (see module docstring for the shapes)."""
    seats = _seat_map(events, manifest_row)
    picks = _drafts(events, seats)
    if len(picks) != 4:
        raise ValueError(f"expected 4 fighterDrafted, got {len(picks)}")

    plan = [{"op": "draft_hands", "hands": _reconstruct_hands(picks)},
            {"op": "characters", "choices": _character_choices(events)}]
    for seat, fid in picks:
        plan.append({"op": "move", "seat": seat, "move": {"kind": "draft", "fighter": fid}})

    teams = collections.defaultdict(list)
    for seat, fid in picks:
        teams[seat].append(fid)
    fid_seat = {fid: seat for seat, fids in teams.items() for fid in fids}

    # Snapshots carry move_ids too, so checks can be INTERLEAVED BY MOVE ID rather than
    # consumed in sequence — which is what made the earlier "joan power 2 vs 1" divergence
    # untrustworthy. A check now lands at the point in the game it actually describes.

    # Anchor checks by EVENT ORDER. The authoritative build packets carry move_id 0, so
    # anchoring on move_id emitted no checks whatsoever (checked=0 everywhere) — a gate that
    # silently measures nothing, which is worse than one that fails.
    steps = {id(a): (seat, kind, a, drawn)
             for _m, seat, kind, a, drawn in _steps(events, fid_seat)}
    for _mid, d in events:
        if d["type"] == "updateCardAndFighterData" and d["args"].get("allFighters"):
            plan.append({"op": "check", "mid": _mid, "event": d})
            continue
        if d["type"] != "updateBuildDeckArgs" or id(d["args"]) not in steps:
            continue
        seat, kind, a, drawn = steps.pop(id(d["args"]))
        # A snapshot at move_id M describes the state AFTER the move at M, so its check is
        # emitted after that step. Checking before it read every fighter exactly one power
        # low — a uniform off-by-one across all four fighters, which is the signature of a
        # timing offset rather than a rules bug, and worth recognising as such.
        if kind == "order":
            deck = sorted((a.get("deck") or []), key=lambda c: c.get("locationArg", 0))
            fid0 = BGA_TO_FID.get(deck[0].get("type")) if deck else None
            if fid0 in teams[seat]:
                plan.append({"op": "move", "seat": seat,
                             "move": {"kind": "order", "slot": teams[seat].index(fid0)}})
        else:
            kept = _cid(a["addedCard"])
            offer = [_cid(c) for c in (drawn or [])] + [kept]
            plan.append({"op": "build_offer_cids", "seat": seat, "cids": offer,
                         "kept_cid": kept, "pos": a["addedCard"].get("locationArg")})

    ranks = manifest_row["ranks"].split(",")
    plan.append({"op": "result", "winner_seat": ranks.index("1")})
    return plan


# ── the engine half — correct today, no logs required ─────────────────────────────────
def force_draft_hands(game, hands):
    """Override the dealt draft (engine.py:182 shuffles it)."""
    game["draft_hands"] = [list(hands[0]), list(hands[1])]


def force_build_offer(game, seat, cids):
    """Make this seat's BUILD offer be exactly `cids`, and return the chosen insts.

    Set the OFFER, not the deck. `_begin_build` draws build_offer off the top the moment the
    phase is entered — reordering build_deck afterwards is a no-op, which is why the first
    version silently offered whatever the engine's own shuffle had dealt and every build move
    came back illegal. Any already-drawn offer goes back to the deck first so no card is lost.

    Copies are rules-identical, so any consistent inst assignment works; we do not need to
    reproduce BGA's own instance identity, only the multiset of card ids.
    """
    pool = list(game["build_offer"][seat] or []) + list(game["build_deck"][seat])
    chosen, taken = [], set()
    for cid in cids:
        hit = next((i for i in pool
                    if i not in taken and game["instances"][i]["cid"] == cid), None)
        if hit is None:
            raise ValueError(f"seat {seat}: card {cid} not in offer+deck")
        taken.add(hit)
        chosen.append(hit)
    game["build_offer"][seat] = chosen
    game["build_deck"][seat] = [i for i in pool if i not in taken]
    return chosen


class _Pending(Exception):
    """A choose_character the log has not told us how to answer."""


def replay(path, manifest_row, verbose=False, on_move=None):
    """Drive our engine from a log. Returns a dict describing how far it got."""
    events = list(tt_inspect.events(path))
    try:
        plan = parse_actions(events, manifest_row)
    except Exception as e:                            # noqa: BLE001
        return _stop(None, 0, f"parse: {type(e).__name__}: {e}")

    game = engine.new_game(SEATS, seed=0)
    applied, recorded, checked, divergence = 0, None, 0, None
    pending = None          # (our state, where we were) awaiting the NEXT BGA snapshot
    trace = []
    characters = {}

    def do_check(step):
        """Compare our state to the PREVIOUS snapshot's counterpart — the oracle runs at lag 1.

        CALIBRATED, and by measurement rather than by argument. BGA emits
        `updateCardAndFighterData` BEFORE resolving the step it announces, so our engine sits
        exactly one snapshot ahead of it. Scored over the whole corpus, matching our state at
        check i against BGA snapshot i+k:

            k = -1   0.358        k = +1   0.716   <-- calibrated
            k =  0   0.537        k = +2   0.454

        +1 is not a close call, and the peak either side of it is the shape you want to see:
        a real alignment, not a shift that happens to flatter one game.

        This file previously said a one-step lag "was tried and changed nothing". That was
        measured BEFORE the Wild Bunch setup icon and Joan's divine-voice dial were fixed --
        two real Power bugs that were then drowning the alignment signal. The lesson is the
        order: a miscalibrated oracle and a buggy engine are indistinguishable from inside,
        so the bugs whose cause is understood get fixed first and the oracle is calibrated
        against what is left. Calibrating first would have fitted the lag to the bugs.

        Residual mismatch at +1 is ~28% and is NOT all noise -- some of it is real engine
        divergence still to be found. Treat a divergence as a LEAD, not a verdict.
        """
        nonlocal checked, divergence, pending
        snap = tt_oracle.snapshot_of(step["event"])
        if not snap or game["phase"] == "draft":
            return
        if pending is not None:
            prev_ours, prev_step = pending
            checked += 1
            trace.append({"round": prev_step["round"],
                          "ours": {k: v[0] for k, v in prev_ours.items()},
                          "bga": {k: v[0] for k, v in snap.items()}})
            bad = [(fid, prev_ours.get(fid), theirs)
                   for fid, theirs in snap.items() if prev_ours.get(fid) != theirs]
            if bad and divergence is None:
                divergence = {"mid": step["mid"], "round": prev_step["round"],
                              "phase": prev_step["phase"], "fighters": bad}
        pending = (tt_oracle.our_state(game),
                   {"round": game.get("round"), "phase": game["phase"]})

    def do_build(step):
        """Submit one queued BUILD for its seat."""
        nonlocal applied
        seat = step["seat"]
        insts = force_build_offer(game, seat, step["cids"])
        kept = next(i for i in insts if game["instances"][i]["cid"] == step["kept_cid"])
        legal_pos = engine.legal_build_positions(game, seat)
        pos = step["pos"] if step["pos"] in legal_pos else (legal_pos[-1] if legal_pos else 0)
        move = {"kind": "build", "inst": kept, "pos": pos}
        if move not in engine.legal_moves(game, seat):
            raise ValueError(f"illegal {move} (phase={game['phase']})")
        if on_move is not None:
            on_move(game, SEATS[seat], move, seat)
        engine.apply_move(game, SEATS[seat], move)
        applied += 1
        if verbose:
            print(f"  [{applied:>3}] seat {seat} {move}")

    # BUILDS ARE QUEUED PER SEAT AND DRIVEN BY owes_move, NOT BY LOG ORDER.
    # Both seats submit once per BUILD step and the engine advances only when both are in, so
    # replaying the log's own sequence requires it to alternate perfectly. It does not: one
    # game runs [0,1][1,0][0,1][0,0] with counts 8 vs 7, and the moment it desyncs every later
    # submission comes back with an EMPTY legal list. Asking the engine who owes a move makes
    # the replay immune to a missing, duplicated or reordered packet in either seat's stream.
    #
    # Builds are queued AS ENCOUNTERED, never all up front. Pre-queuing them let the first
    # drain run the entire game to completion, after which every remaining `check` compared a
    # FINISHED game to a mid-game snapshot — all seven checks in one game fired at round 6.
    # The gate reported divergences the whole time while measuring nothing real, which is the
    # worst failure mode available to a correctness check.
    queues = {0: [], 1: []}

    def answer_pending():
        """Resolve a choose_character from the log, or report that we cannot."""
        while game.get("pending_kind") == "choose_character":
            pend = game["pending"]
            fid = game["teams"][pend["seat"]][pend["slot"]]
            queue = characters.get(fid) or []
            pick = next((c for c in queue if c in pend["options"]), None)
            if pick is None:
                raise _Pending()
            queue.remove(pick)   # consume in order; transitions are recorded in sequence
            engine.apply_move(game, SEATS[pend["seat"]], {"kind": "character",
                                                          "character": pick})

    def drain():
        """Submit whatever builds the engine is currently asking for, and no more."""
        answer_pending()
        while not engine.is_over(game) and game["phase"] == "build":
            answer_pending()
            progressed = False
            for seat in (0, 1):
                if engine.owes_move(game, seat) and queues[seat]:
                    do_build(queues[seat].pop(0))
                    progressed = True
            if not progressed:
                return

    try:
        for step in plan:
            op = step["op"]
            if op == "draft_hands":
                force_draft_hands(game, step["hands"])
            elif op == "characters":
                characters.update(step["choices"])
            elif op == "result":
                recorded = step["winner_seat"]
            elif op == "check":
                do_check(step)
            elif op == "build_offer_cids":
                queues[step["seat"]].append(step)
                drain()
            elif op == "move":
                answer_pending()
                seat, move = step["seat"], step["move"]
                if move not in engine.legal_moves(game, seat):
                    return _stop(game, applied, f"illegal {move!r} (phase={game['phase']})")
                if on_move is not None:
                    on_move(game, SEATS[seat], move, seat)
                engine.apply_move(game, SEATS[seat], move)
                applied += 1
                drain()
    except _Pending:
        return _stop(game, applied, "unhandled pending: choose_character")
    except Exception as e:                            # noqa: BLE001 — report, don't crash the batch
        return _stop(game, applied, f"{type(e).__name__}: {e}")
    left = len(queues[0]) + len(queues[1])
    over = engine.is_over(game)
    summary = engine.result_summary(game) if over else {}
    ours = summary.get("winner")
    stopped = None
    if not over:
        stopped = f"stalled in phase={game['phase']} with {left} builds unused"
    elif left:
        stopped = f"our engine ended {left} builds early"
    return {"over": over, "applied": applied, "stopped": stopped,
            "winner": ours, "recorded_winner": recorded,
            "winner_match": bool(over) and ours == recorded,
            "phase": game["phase"], "summary": summary,
            "divergence": divergence, "checked": checked, "unused": left, "trace": trace}


def _stop(game, applied, why):
    return {"over": False, "applied": applied, "stopped": why,
            "winner": None, "recorded_winner": None, "winner_match": False, "summary": {},
            "divergence": None, "checked": 0, "unused": 0, "trace": []}


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[-1])
        return 2
    r = replay(f"{LOGS}/{sys.argv[1]}.json", verbose="-v" in sys.argv)
    print(json.dumps({k: v for k, v in r.items() if k != "summary"}, indent=1, default=str))
    return 0 if r["winner_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
