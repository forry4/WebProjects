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
import sys

sys.path.insert(0, "C:/Users/Forrest/forrestm_projects")
from games.rag_tag import engine                                    # noqa: E402

import scrape_target as tgt                                         # noqa: E402
import tt_inspect                                                   # noqa: E402
import tt_oracle                                                    # noqa: E402

LOGS = tgt.CORP + "/logs"
SEATS = ["p0", "p1"]


# ── the BGA half — written against real logs (tt_inspect.py), not guessed ────────────
import collections                                                  # noqa: E402
from games.rag_tag.fighters import CARDS, FIGHTERS, ROSTER   # noqa: E402

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


def _build_events(events, fid_seat):
    """updateBuildDeckArgs split into (seat, kind, payload).

    kind == "order": the two starting cards being laid out (no drawnCards).
    kind == "build": a BUILD step — the offer is drawnCards + addedCard (2 shown-and-
    returned + 1 kept == BUILD_DRAW 3); `deck` carries locationArg = position.
    """
    out, seen = [], set()
    for _mid, d in events:
        if d["type"] != "updateBuildDeckArgs":
            continue
        a = d["args"]
        added = a.get("addedCard")
        if not added:
            continue
        # SEAT FROM THE CARD, not from the location string. Every card belongs to exactly
        # one fighter and every fighter to exactly one team, so cid -> fighter -> seat is
        # unambiguous and self-checking. Parsing `location` ("player-deck_<pid>") looked
        # equivalent but mis-attributed some packets, and the symptom was the far-away
        # "card N not in offer+deck" -- a seat error wearing a rules error's clothes.
        fid = BGA_TO_FID.get(added.get("type"))
        seat = fid_seat.get(fid)
        if seat is None:
            continue
        drawn = a.get("drawnCards") or []
        kind = "build" if drawn else "order"
        # BGA RE-SENDS identical state packets (the same payload arrived under move_id 0 and
        # again under 7). Undeduped, that emitted a second `order` for a seat whose
        # order_choice was already set, which the engine correctly refused -- and it read as
        # a rules divergence rather than a transport artefact. Dedupe on content.
        sig = (seat, kind,
               tuple(sorted((c.get("type"), c.get("typeArg")) for c in drawn)),
               (a["addedCard"].get("type"), a["addedCard"].get("typeArg")),
               tuple(sorted((c.get("locationArg"), c.get("type"), c.get("typeArg"))
                            for c in (a.get("deck") or []))))
        if sig in seen:
            continue
        seen.add(sig)
        out.append((seat, kind, a))
    return out


def parse_actions(events, manifest_row):
    """BGA events -> ordered replay instructions (see module docstring for the shapes)."""
    seats = _seat_map(events, manifest_row)
    picks = _drafts(events, seats)
    if len(picks) != 4:
        raise ValueError(f"expected 4 fighterDrafted, got {len(picks)}")

    plan = [{"op": "draft_hands", "hands": _reconstruct_hands(picks)}]
    for seat, fid in picks:
        plan.append({"op": "move", "seat": seat, "move": {"kind": "draft", "fighter": fid}})

    ordered = set()
    teams = collections.defaultdict(list)
    for seat, fid in picks:
        teams[seat].append(fid)

    fid_seat = {fid: seat for seat, fids in teams.items() for fid in fids}
    builds = {0: [], 1: []}
    for seat, kind, a in _build_events(events, fid_seat):
        if kind == "order":
            if seat in ordered:
                continue
            ordered.add(seat)
            # whichever starting card sits at position 0 went first
            deck = sorted((a.get("deck") or []), key=lambda c: c.get("locationArg", 0))
            if not deck:
                continue
            fid0 = BGA_TO_FID.get(deck[0].get("type"))
            if fid0 in teams[seat]:
                plan.append({"op": "move", "seat": seat,
                             "move": {"kind": "order", "slot": teams[seat].index(fid0)}})
        else:
            offer = [_cid(c) for c in a["drawnCards"]] + [_cid(a["addedCard"])]
            builds[seat].append({"op": "build_offer_cids", "seat": seat, "cids": offer,
                                 "kept_cid": _cid(a["addedCard"]),
                                 "pos": a["addedCard"].get("locationArg")})

    # INTERLEAVE BY ROUND. Both seats submit once per BUILD step and the engine only advances
    # when both are in, so replaying the log's own emission order (which can run several of one
    # seat's builds together) left build_choice already set and owes_move False -- reported as
    # an illegal move with an EMPTY legal list, which is the tell for "nobody owes a move".
    for k in range(max(len(builds[0]), len(builds[1]))):
        for seat in (0, 1):
            if k < len(builds[seat]):
                plan.append(builds[seat][k])

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


def replay(path, manifest_row, verbose=False, on_move=None):
    """Drive our engine from a log. Returns a dict describing how far it got."""
    events = list(tt_inspect.events(path))
    try:
        plan = parse_actions(events, manifest_row)
    except Exception as e:                            # noqa: BLE001
        return _stop(None, 0, f"parse: {type(e).__name__}: {e}")

    snaps = tt_oracle.snapshots(events)
    game = engine.new_game(SEATS, seed=0)
    applied, recorded, si, divergence = 0, None, 0, None

    def check():
        """Compare our state to the next BGA snapshot. Records, never aborts —
        a divergence is the RESULT of this gate, not an error in running it."""
        nonlocal si, divergence
        if divergence is not None or si >= len(snaps):
            return
        bad = tt_oracle.diff(game, snaps[si])
        if bad:
            divergence = {"snapshot": si, "round": game.get("round"), "fighters": bad}
        si += 1
    for step in plan:
        op = step["op"]
        try:
            if op == "draft_hands":
                force_draft_hands(game, step["hands"])
            elif op == "result":
                recorded = step["winner_seat"]
            elif op in ("move", "build_offer_cids"):
                # An unanswered choose_character pending blocks everything after it. Surface
                # it rather than guessing an option -- a wrong guess would look like a rules
                # divergence later, which is exactly the failure we are trying to detect.
                if game.get("pending_kind") == "choose_character":
                    return _stop(game, applied, "unhandled pending: choose_character")
                if op == "build_offer_cids":
                    seat = step["seat"]
                    insts = force_build_offer(game, seat, step["cids"])
                    kept = next(i for i in insts
                                if game["instances"][i]["cid"] == step["kept_cid"])
                    pos = step["pos"]
                    legal_pos = engine.legal_build_positions(game, seat)
                    if pos is None or pos not in legal_pos:
                        pos = legal_pos[-1] if legal_pos else 0
                    move = {"kind": "build", "inst": kept, "pos": pos}
                else:
                    seat, move = step["seat"], step["move"]
                legal = engine.legal_moves(game, seat)
                if move not in legal:
                    return _stop(game, applied,
                                 f"illegal {move!r} (phase={game['phase']}); "
                                 f"legal[:3]={legal[:3]}")
                if on_move is not None:
                    on_move(game, SEATS[seat], move, seat)
                was = game["phase"]
                engine.apply_move(game, SEATS[seat], move)
                applied += 1
                if verbose:
                    print(f"  [{applied:>3}] seat {seat} {move}")
                # snapshot 0 is the freshly-built boards; later ones follow each FIGHT, which
                # resolves when the second seat's build lands and the phase turns over.
                if was == "order" and game["phase"] != "order":
                    check()
                elif move.get("kind") == "build" and game["phase"] != "build":
                    check()
        except Exception as e:                        # noqa: BLE001
            return _stop(game, applied, f"{op}: {type(e).__name__}: {e}")

    over = engine.is_over(game)
    summary = engine.result_summary(game) if over else {}
    ours = summary.get("winner")
    return {"over": over, "applied": applied, "stopped": None,
            "winner": ours, "recorded_winner": recorded,
            "winner_match": bool(over) and ours == recorded,
            "phase": game["phase"], "summary": summary,
            "divergence": divergence, "snapshots": len(snaps), "checked": si}


def _stop(game, applied, why):
    return {"over": False, "applied": applied, "stopped": why,
            "winner": None, "recorded_winner": None, "winner_match": False, "summary": {},
            "divergence": None, "snapshots": 0, "checked": 0}


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[-1])
        return 2
    r = replay(f"{LOGS}/{sys.argv[1]}.json", verbose="-v" in sys.argv)
    print(json.dumps({k: v for k, v in r.items() if k != "summary"}, indent=1, default=str))
    return 0 if r["winner_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
