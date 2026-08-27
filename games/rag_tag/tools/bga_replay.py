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
from games.rag_tag.fighters import CARDS, FIGHTERS, MILADY_SCHEMES, ROSTER



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


# When BGA re-sends a build at a DIFFERENT insert position, which packet is the real one?
# Settled by measurement, not by argument: winner parity is 15/30 either way, so it cannot
# break the tie, but oracle agreement over the corpus reads 0.7247 keeping the re-send
# against 0.7120 keeping the first. Small, and pointing the way the reading suggests -- the
# re-send is the server's settled view of where the card landed.
_RESEND_WINS = True

# BGA's addedCard.locationArg counts from the OPPOSITE END of the Fight deck to our insert
# index, so it has to be flipped: our_pos = len(legal) - 1 - locationArg.
#
# Settled by measurement, and it is the single biggest correction in the harness. Three
# independent measures move together, which is what makes it believable rather than a
# coincidence that flattered one game:
#
#                       winner parity   power agreement   hp agreement
#     flipped (this)        19/30           0.7405           0.5424
#     as-is                 15/30           0.7247           0.5068
#
# It was invisible for a long time because EVERY position stayed in range either way
# (246/246), so nothing ever threw -- the cards simply went into the deck in the wrong order
# and the fight played out differently. The tell was in the HP oracle: in a game that
# reproduced the winner, ching_shih tracked exactly while joan and mordred were wrong in
# OPPOSITE directions -- our damage landing on the other side, which is what a reordered
# deck does, and what no amount of per-card rules reading would have suggested.
#
# OPEN, AND WORTH SAYING SO: reading the packets structurally says the flip should NOT be
# needed. Tracing one seat, the Fight deck runs 10@0, 100@1; card 11 is inserted at loc 2;
# and after the round the deck is 100@0, 11@1 -- card 10, at loc 0, was revealed first. Our
# engine also reveals index 0 (`deck.pop(0)`) and inserts with 0 as the top. By that reading
# the two conventions already agree and flipping should HURT. It does the opposite, on three
# independent measures, reproducibly. Something about how BGA maintains locationArg inside
# `deck` is not what the trace above implies, and I have not pinned it down.
#
# One concrete alternative WAS tested and refuted: that BGA turns the played pile over when
# it becomes the next Fight deck, which would make this a real engine bug rather than a
# harness setting. Reversing `played` in _begin_build reads 16/31 and 19/31 against 24/31 --
# clearly worse both ways, so our engine's order preservation is right and this stays a
# property of the LOG, not of the rules.
_POS_FROM_TOP = True


def public_builds(events, fid_seat):
    """The PUBLIC record of each build: {(seat, deck_sig): (offer multiset, kept cid)}.

    A build's public packet carries `addedCard` (what was kept) and `discardedCards` (the
    rest of the offer), so it names the whole step by itself and needs no reconstruction.
    It exists for only about half the builds -- a log carries one player's private stream --
    which is why the parse cannot be driven off it. But where it DOES exist it is an
    independent check on the private reconstruction, and that is what `verify_against_public`
    uses it for. Feeding it into the parse instead changes nothing at all (measured: 22/30
    either way, and with every combination of displacing and gap-filling), which is the
    result worth having -- the two streams agree.
    """
    out = {}
    for _mid, d in events:
        if d["type"] != "updateBuildDeckArgs":
            continue
        a = d["args"]
        added, disc = a.get("addedCard"), a.get("discardedCards")
        if not added or not disc or a.get("drawnCards"):
            continue
        seat = fid_seat.get(BGA_TO_FID.get(added.get("type")))
        if seat is None:
            continue
        offer = tuple(sorted([_cid(added)] + [_cid(c) for c in disc]))
        sig = (seat,
               tuple((c.get("type"), c.get("typeArg")) for c in (a.get("deck") or [])),
               offer)
        out[sig] = (offer, _cid(added))
    return out


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
    ordered, out, seen = set(), [], {}
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
            #
            # THE KEY IS THE FIGHT DECK PLUS THE OFFER AS A MULTISET. One build emits up
            # to three packets and the two private ones DISAGREE about which card was kept:
            #
            #   added=82 loc=2 drawn=[21,21] deck=[20,80]                private view A
            #   added=21 loc=0 drawn=[82,21] deck=[20,80]                private view B
            #   added=21 loc=0 drawn=[]      deck=[20,80] disc=[21,82]   PUBLIC, confirms B
            #
            # They disagree about the KEPT CARD, but `added + drawn` is the same three cards
            # either way -- so the offer as an unordered multiset merges the views of one
            # build, while the kept card alone would split them.
            #
            # `deck` alone is NOT enough, and this is the trap: it is the Fight deck before
            # the insert, so it usually differs between a seat's consecutive builds -- but
            # Wong's Crippling Touch REMOVES ITSELF FROM THE GAME, so a deck can come back
            # to a state it has already been in. In 886302456 seat 1 builds a second
            # Crippling Touch into the identical 2-card deck, and keying on the deck alone
            # merged that build with the NEXT one and dropped it. The offer breaks the tie.
            #
            # This is also what keeps genuine repeats apart, and it has to: several cards have
            # 2-3 copies and are legitimately built more than once.
            sig = (seat,
                   tuple((c.get("type"), c.get("typeArg")) for c in (a.get("deck") or [])),
                   tuple(sorted([_cid(c) for c in drawn] + [_cid(added)])))
            if sig in seen:
                if _RESEND_WINS:            # measured; see the constant
                    out[seen[sig]] = (mid, seat, "build", a, drawn)
                continue
            seen[sig] = len(out)
            out.append((mid, seat, "build", a, drawn))
        elif CARDS[_cid(added)].get("starting") and seat not in ordered:
            ordered.add(seat)
            out.append((mid, seat, "order", a, None))
    return out


def fight_entries(events):
    """Every `fightLog` entry in the log, de-duplicated by (fight, log_id), in play order.

    The entries arrive spread over many `newPrivateState` packets that re-send overlapping
    slices of the same fight, so they have to be KEYED rather than concatenated. Both ids are
    STRINGS in the log and sorting them as strings interleaves turn 10 with turn 1 -- an
    ordering bug that reads exactly like a rules divergence.

    Yields ((fight, log_id), (type, parsed value)).
    """
    out = {}
    for _mid, d in events:
        if d["type"] != "newPrivateState":
            continue
        a = d.get("args") or {}
        inner = a.get("args") if isinstance(a, dict) else None
        if not isinstance(inner, dict) or "fightLog" not in inner:
            continue
        for e in inner["fightLog"]:
            try:
                out[(int(e["fight_id"]), int(e["log_id"]))] = (e["type"],
                                                               json.loads(e["value"]))
            except Exception:                     # noqa: BLE001 — a malformed entry is not fatal
                continue
    return [(k, v) for k, v in sorted(out.items())]


def scheme_pile(events):
    """Milady's Intrigue pile, in the order the log reveals it.

    Her pile is face-down and drawn without replacement, so it is setup randomness the same
    way the draft and the Build deck are, and a replay has to override it rather than seed
    its way to it. BGA names each revealed token `token-milady-scheme-N`, and `bga_token` in
    the data carries that N -- a mapping derived from the corpus (see cards.json), not
    guessed.

    Returns the revealed faces in order; the caller pads with whatever is left of the pile.
    """
    by_n = {eff["bga_token"]: eff["id"] for eff in MILADY_SCHEMES["effects"]}
    out = []
    for _k, (kind, v) in fight_entries(events):
        if kind != "schemeUnleashed":
            continue
        face = ((v.get("token") or {}).get("typeArg") or "")
        if face.startswith("token-milady-scheme-"):
            eid = by_n.get(int(face.rsplit("-", 1)[1]))
            if eid:
                out.append(eid)
    return out


def reveals(events, seat_of_pid):
    """The exact card each seat revealed, per fight and turn, from BGA's own fightLog.

    `newPrivateState` carries a `fightLog`, and its `cardsRevealed` entries name both
    revealed cards outright -- with the active Fighter, the turn and the fight. This is the
    strongest record in the log by a distance: everything else about the Fight deck has to
    be inferred from insert positions, and this simply says what happened.

    It is also what settles which end of the Fight deck is the top. Round 1 of table
    886302456 reveals the card at locationArg 1 out of a deck holding locationArgs 0 and 1,
    so the HIGHEST is the top -- confirming the flip that three separate measures had
    already forced, and correcting a structural reading that said the opposite (it had
    confused BGA's per-instance `id` with the card's `typeArg`).

    Returns [(fight, turn, {seat: cid})] in play order.
    """
    out = []
    for (_f, _l), (kind, v) in fight_entries(events):
        if kind != "cardsRevealed":
            continue
        row = {}
        for who, team in (("card1", "teamId1"), ("card2", "teamId2")):
            card, seat = v.get(who), seat_of_pid.get(str(v.get(team)))
            if card is not None and seat is not None:
                row[seat] = ART_TO_CID[int(card["typeArg"])]
        if row:
            out.append((_f, v.get("turnNumber"), row))
    return out


def serpent_faces(events):
    """{fid: 0|1} — the face Mephisto's serpent token is SET UP on, from the log.

    This is setup randomness, exactly like the draft and the build shuffle, and it has to be
    overridden for the same reason: `_begin_order` rolls it (`r.randint(0, 1)`) and a replay
    cannot seed its way to the same coin. Leaving it random silently halves the games where
    Mephisto plays, because Twin Serpents ATTACKS on black and merely gives a Power on white.

    The mapping is DERIVED, not guessed: over the four games in the corpus that field
    Mephisto, `state: "back"` always precedes a first Twin Serpents that attacks (884758143,
    888405016) and `"front"` always precedes one that only grants Power (902099944,
    902266350). The split is 2/2, which is also the evidence that the real game randomises it
    -- so our engine's coin is the right RULE, and this is a harness override rather than a
    fix.
    """
    out = {}
    for _mid, d in events:
        if d["type"] != "updateCardAndFighterData":
            continue
        for f in (d["args"].get("allFighters") or []):
            fid = BGA_TO_FID.get(f.get("typeArg"))
            st = f.get("fighterState") or {}
            if fid is None or fid in out or not isinstance(st, dict):
                continue
            for t in (st.get("tokens") or []):
                if t.get("typeArg") == "token-serpent" and t.get("state") in ("front", "back"):
                    out[fid] = 1 if t["state"] == "back" else 0
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


def character_tracks(events):
    """fid -> [character ids] read off which health TRACK BGA moves, in play order.

    A SECOND source for the same fact `_character_choices` reads from
    `fighterSpecificState.activeTrack`, and it is needed because that one has gaps: a log
    can stop re-broadcasting fighter state and still keep logging the fight, which left
    884758143 with one recorded choice and a Fey Folk who had to pick twice. The fightLog
    names the track it moves ("TheFeyFolk_track_2"), and track N is that fighter's Nth
    Character in board order -- the same 1-based numbering `activeTrack` uses.
    """
    out, last = collections.defaultdict(list), {}
    for _k, (kind, v) in fight_entries(events):
        if kind != "trackPositionUpdated":
            continue
        m = v.get("marker") or {}
        if m.get("type") != "health":
            continue
        where = str(m.get("location", "")).split("_track_")
        fid = BGA_TO_FID.get(where[0])
        if fid is None or len(where) != 2 or not where[1].isdigit():
            continue
        chars = FIGHTERS[fid].get("characters") or []
        n = int(where[1])
        if 1 <= n <= len(chars) and last.get(fid) != n:
            last[fid] = n
            out[fid].append(chars[n - 1]["id"])
    return out


def parse_actions(events, manifest_row):
    """BGA events -> ordered replay instructions (see module docstring for the shapes)."""
    seats = _seat_map(events, manifest_row)
    picks = _drafts(events, seats)
    if len(picks) != 4:
        raise ValueError(f"expected 4 fighterDrafted, got {len(picks)}")

    plan = [{"op": "draft_hands", "hands": _reconstruct_hands(picks)},
            {"op": "characters", "choices": _character_choices(events),
             "from_tracks": character_tracks(events)},
            {"op": "tokens", "serpent": serpent_faces(events),
             "schemes": scheme_pile(events)}]
    for seat, fid in picks:
        plan.append({"op": "move", "seat": seat, "move": {"kind": "draft", "fighter": fid}})

    teams = collections.defaultdict(list)
    for seat, fid in picks:
        teams[seat].append(fid)
    fid_seat = {fid: seat for seat, fids in teams.items() for fid in fids}

    # The Fighter each seat leads with, straight from the first revealed cards.
    seq = reveals(events, _seat_map(events, manifest_row))
    lead = {}
    if seq:
        _f, _t, first = seq[0]
        for seat, cid in first.items():
            fid = CARDS[cid].get("fighter")
            if fid in teams[seat]:
                lead[seat] = fid

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
            # WHICH FIGHTER LEADS COMES FROM THE FIGHT LOG, not from the Starting-Card
            # packet. That packet holds a single card and says nothing about the choice, so
            # the old reading -- take the card already in the deck -- was a guess; flipping
            # it fixed three games and broke four, which is the signature of a guess rather
            # than an off-by-one. The first `cardsRevealed` of the first fight names the
            # active Fighter for BOTH seats outright, so there is nothing left to infer.
            fid0 = lead.get(seat)
            if fid0 is None:                       # no fightLog (a game that ended in draft)
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

    # A TIE ON RANK IS A DRAW, and `ranks.index("1")` quietly called it a win for seat 0.
    # 54 of the 1738 tables in the manifest end "1,1" with scores "0,0" -- a double KO --
    # and our engine reports those as `winner == "draw"`, so every one of them counted as a
    # parity failure while the engine was right. 902200012 is the reproduction: 124 of 124
    # turns exact, both fighters of one team on 0 HP, and the gate still scored it wrong.
    ranks = manifest_row["ranks"].split(",")
    plan.append({"op": "result",
                 "winner_seat": "draw" if ranks.count("1") > 1 else ranks.index("1")})
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


def _force_tokens(game, faces, pile):
    """Override the setup randomness that lives on a fighter board.

    Two things, both hidden and both rolled in `_begin_order`: Mephisto's serpent coin, and
    Milady's face-down Intrigue pile. Neither can be reached by seeding, and both change the
    fight outright -- Twin Serpents attacks on black and merely grants a Power on white, and
    the Intrigues run from "heal 6" to poison.

    The pile is set to the faces the log actually revealed, with whatever is left of the
    eleven appended so the pile stays the right multiset. A log that revealed MORE of a face
    than the pile holds would be a mapping error rather than a long game, so the leftovers
    are computed by removal and the extras are kept where they fall -- visible, not silently
    dropped.
    """
    for seat in (0, 1):
        for slot in (0, 1):
            f = game["fighters"][seat][slot]
            want = faces.get(game["teams"][seat][slot])
            if want is not None and "serpent" in f["tokens"]:
                f["tokens"]["serpent_face"] = want
            if pile and f.get("scheme_pool"):
                left = list(f["scheme_pool"])
                for eid in pile:
                    if eid in left:
                        left.remove(eid)
                f["scheme_pool"] = list(pile) + left


class _Pending(Exception):
    """A choose_character the log has not told us how to answer."""


def verify_against_public(events, manifest_row):
    """Check the private reconstruction against BGA's own public record.

    Returns (confirmed, disagreed, unchecked). This is the alignment-free half of the gate:
    it needs no engine, no oracle and no calibration, so it stays meaningful on a log our
    engine cannot finish. A disagreement means the PARSE is wrong, which is a different
    animal from an engine bug and worth telling apart before chasing rules.
    """
    plan = parse_actions(events, manifest_row)
    picks = [(st["seat"], st["move"]["fighter"]) for st in plan
             if st["op"] == "move" and st["move"]["kind"] == "draft"]
    fid_seat = {fid: seat for seat, fid in picks}
    pub = public_builds(events, fid_seat)
    confirmed = disagreed = 0
    for _m, seat, kind, a, drawn in _steps(events, fid_seat):
        if kind != "build":
            continue
        sig = (seat,
               tuple((c.get("type"), c.get("typeArg")) for c in (a.get("deck") or [])),
               tuple(sorted([_cid(c) for c in drawn] + [_cid(a["addedCard"])])))
        want = pub.get(sig)
        if want is None:
            continue
        ours = (tuple(sorted([_cid(c) for c in drawn] + [_cid(a["addedCard"])])),
                _cid(a["addedCard"]))
        if ours == want:
            confirmed += 1
        else:
            disagreed += 1
    return confirmed, disagreed, len(pub)


def replay(path, manifest_row, verbose=False, on_move=None):
    """Drive our engine from a log. Returns a dict describing how far it got."""
    events = list(tt_inspect.events(path))
    try:
        plan = parse_actions(events, manifest_row)
    except Exception as e:                            # noqa: BLE001
        return _stop(None, 0, f"parse: {type(e).__name__}: {e}")

    seat_of_pid = _seat_map(events, manifest_row)
    want_reveals = reveals(events, seat_of_pid)
    seen_beats = {}                 # (round, turn) -> revealed cids, accumulated across rounds

    def _collect():
        """`game["beats"]` is CLEARED every round, so it has to be harvested as it goes.

        Reading it at the end compares one round against the whole game and scores ~0.21
        while the truth is 0.935 -- a measurement that looks like a catastrophic engine bug
        and is nothing but a stale read.
        """
        for b in game["beats"]:
            # Not every beat is a reveal: the Golem's Reanimation and Milady's Schemes append
            # their own beats, which carry narration but no `cids`. Only the reveal beats are
            # comparable, and skipping the rest is not a loss -- BGA logs them separately too.
            if "cids" in b and "turn" in b:
                seen_beats.setdefault((game["round"], b["turn"]), b["cids"])

    game = engine.new_game(SEATS, seed=0)
    tokens, schemes, forced = {}, [], False
    applied, recorded, checked, divergence = 0, None, 0, None
    pending = None          # (our state, where we were) awaiting the NEXT BGA snapshot
    trace = []
    characters, by_track = {}, {}

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
                          "bga": {k: v[0] for k, v in snap.items()},
                          "ours_hp": {k: v[2] for k, v in prev_ours.items()},
                          "bga_hp": {k: v[2] for k, v in snap.items()}})
            bad = [(fid, prev_ours.get(fid), theirs) for fid, theirs in snap.items()
                   if tt_oracle.disagrees(prev_ours.get(fid), theirs)]
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
        want = (len(legal_pos) - 1 - step["pos"]) if _POS_FROM_TOP else step["pos"]
        pos = want if want in legal_pos else (legal_pos[-1] if legal_pos else 0)
        move = {"kind": "build", "inst": kept, "pos": pos}
        if move not in engine.legal_moves(game, seat):
            raise ValueError(f"illegal {move} (phase={game['phase']})")
        if on_move is not None:
            on_move(game, SEATS[seat], move, seat)
        engine.apply_move(game, SEATS[seat], move)
        _collect()
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
                # `activeTrack` has gaps -- a log can stop re-broadcasting fighter state
                # while the fight carries on -- so fall back to which health TRACK the
                # fightLog moves next. Same fact, different half of the log.
                queue = by_track.get(fid) or []
                pick = next((c for c in queue if c in pend["options"]), None)
            if pick is None and len(pend["options"]) == 1:
                # A FORCED choice is not a decision, and BGA does not log one. The Fey Folk
                # reach their last Character with nothing left to choose between, so the
                # log's activeTrack never flips a third time (table 901568802 records elf,
                # then fairy, then all three as Spirits). Demanding the log name it stalled
                # the replay on a move that had exactly one legal answer.
                pick = pend["options"][0]
            if pick is None:
                raise _Pending()
            if pick in queue:
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
                by_track.update(step["from_tracks"])
            elif op == "tokens":
                tokens.update(step["serpent"])
                schemes[:] = step["schemes"]
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
                # `_begin_order` rolls the serpent coin as the last draft pick lands, so the
                # override goes in the moment the phase leaves "draft" -- before any card can
                # read it. Setting it earlier is a no-op (the fighters do not exist yet).
                #
                # EXACTLY ONCE. The two `order` moves are emitted where their Starting-Card
                # packets sit in the log, and the second one can land after the engine has
                # already played the whole first fight -- so re-forcing on every move reset
                # Mephisto's serpent to its setup face mid-game and un-flipped it. That read
                # as a rules divergence in a game which, before the override existed, had
                # reproduced all 74 of its turns exactly.
                if game["phase"] != "draft" and not forced:
                    forced = True
                    _force_tokens(game, tokens, schemes)
                _collect()
                applied += 1
                drain()
        # THE LAST THING THE ENGINE ASKS FOR CAN ARRIVE AFTER THE PLAN RUNS OUT. A Character
        # that dies on the final turn of a fight leaves a `choose_character` pending with no
        # plan step behind it, and the game sat there unfinished -- reported as "stalled in
        # phase=fight", which reads like a rules bug and is a driver that stopped early.
        answer_pending()
        drain()
    except _Pending:
        return _stop(game, applied, "unhandled pending: choose_character")
    except Exception as e:                            # noqa: BLE001 — report, don't crash the batch
        return _stop(game, applied, f"{type(e).__name__}: {e}")
    _collect()
    ours_reveals = [c for _k, c in sorted(seen_beats.items())]
    rev_ok = rev_tot = 0
    rev_first_bad = None
    for i, (_f, _t, row) in enumerate(want_reveals):
        if i >= len(ours_reveals):
            break
        for st in (0, 1):
            if row.get(st) is None:
                continue
            rev_tot += 1
            if row[st] == ours_reveals[i][st]:
                rev_ok += 1
            elif rev_first_bad is None:
                rev_first_bad = i + 1
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
            "divergence": divergence, "checked": checked, "unused": left, "trace": trace,
            "rev_ok": rev_ok, "rev_tot": rev_tot, "rev_first_bad": rev_first_bad}


def _stop(game, applied, why):
    return {"over": False, "applied": applied, "stopped": why,
            "winner": None, "recorded_winner": None, "winner_match": False, "summary": {},
            "divergence": None, "checked": 0, "unused": 0, "trace": [],
            "rev_ok": 0, "rev_tot": 0, "rev_first_bad": None}


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[-1])
        return 2
    r = replay(f"{LOGS}/{sys.argv[1]}.json", verbose="-v" in sys.argv)
    print(json.dumps({k: v for k, v in r.items() if k != "summary"}, indent=1, default=str))
    return 0 if r["winner_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
