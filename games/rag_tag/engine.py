"""Rag Tag rules. Pure functions over a JSON-safe game dict; no I/O, no server.

THE SHAPE OF A ROUND
    FIGHT!  both players flip the top card of their Fight Deck at the same time and
            resolve both at the same time. Repeat until both decks are empty. The
            two decks are always the same length -- both start at 2 and both gain
            exactly one card a round -- so they empty together.
    BUILD!  draw the top 3 of your Build Deck, secretly keep 1 and slide it anywhere
            into your Fight Deck WITHOUT reordering what is already there, and put
            the other 2 on the bottom. Instant Bonuses fire once both players have
            inserted. The Fight Deck is NEVER shuffled.

WITHIN A TURN, in this order. Steps 1-4 are all "simultaneous" in the rulebook's
sense; the ordering below is what makes that computable, not extra rules.

    1. Reveal. The fighter whose card came up is that side's Active Fighter; the
       other is the Partner. Snapshot every fighter's Power -- ALL Attack damage
       this turn reads the snapshot, never the running value.
    2. Cancel. A cancelled card contributes nothing whatsoever, so this is first.
    3. Declare. Walk both cards' ops and collect the Attacks, Blocks, Direct
       Damage and Heals they perform. A Block negates every Attack performed by
       the opposing Active Fighter AND their Partner, whatever it targeted.
       Success is then knowable without moving anything: a Block succeeded if it
       negated at least one Attack (a 0-Power one counts), an Attack succeeded if
       it was not Blocked. Success bonuses join this same pool, because the
       rulebook is explicit that actions conditional on a success are still
       simultaneous with everything else.
    4. Move. Net each fighter's HP delta -- surviving Attacks and all Direct
       Damage down, all Heals up, as ONE movement -- then walk the marker one
       space at a time, halting on a STOP, clamping at Max HP and at the bottom
       space. A fighter on KO cannot be Healed.
    5. Icons. Only now do the health-track icons fire, all at once, for every
       space each marker LANDED ON or PASSED THROUGH. The space a marker started
       on does not fire. Icons can move markers again, which can pass more icons,
       so this repeats until it settles.
    6. Power, tokens, tracks, and the fighter hooks they trigger.
    7. Deferred effects -- the printed THEN, and the handful of cards that read
       "after your Opponent's card is resolved".
    8. End of turn: a marker on KO now loses the fight for that team. Both teams
       at once is a draw -- except that Shango's Incineration and Mephisto's Drag
       You to Hell each override that.

THREE READINGS THE PRINTED RULES DO NOT SETTLE, all marked INFERRED below and all
things the BGA replay fixtures would confirm:
  * mirrored Hidden Daggers ("if neither Opponent Attacks") would be circular, so
    a conditional Attack that is itself gated on that condition does not count as
    an Attack when evaluating it;
  * "if you are Attacked" counts an Attack that was declared and not cancelled,
    even if a Block then negated its damage -- consistent with a 0-Power Attack
    still triggering a Block's Bonus Action;
  * Maman Brijit's You are Mine redirects the Attacks her Block caught onto the
    opposing Partner. Both readings of that card land the damage in the same
    place, so the ambiguity is harmless.

STATE. The dict is JSON-safe: no sets, no tuples that must survive, RNG as a list.
Sub-decisions live in `pending_pid` / `pending_kind` / `pending` -- real state, so
they survive a save and a reconnect and cannot be cleared by a stray message.
"""

from __future__ import annotations

import random
from typing import Any, Iterable

from . import effects
from .fighters import CARDS, DECKS, FIGHTERS, MILADY_SCHEMES, ROSTER, STARTING_CARD

VERSION = 1

DRAFT_HAND = 6          # 12 draft cards, half to each player
FIGHT_DECK_START = 2    # one Starting Card per fighter
BUILD_DRAW = 3          # drawn each BUILD! step
MAX_ICON_PASSES = 20    # a settle guard; real boards need one or two


class IllegalMove(ValueError):
    """A move the rules do not allow. The server turns this into an error."""


# ==========================================================================
# RNG
# ==========================================================================

def _rng(game: dict) -> random.Random:
    r = random.Random()
    state = game["rng_state"]
    r.setstate((state[0], tuple(state[1]), state[2]))
    return r


def _save_rng(game: dict, r: random.Random) -> None:
    version, internal, gauss = r.getstate()
    game["rng_state"] = [version, list(internal), gauss]


def _with_rng(game: dict):
    r = _rng(game)

    class _Ctx:
        def __enter__(self):
            return r

        def __exit__(self, *exc):
            _save_rng(game, r)
            return False

    return _Ctx()


# ==========================================================================
# Fighter access
# ==========================================================================

def fighter(game: dict, seat: int, slot: int) -> dict:
    return game["fighters"][seat][slot]


def _board(f: dict) -> dict:
    return FIGHTERS[f["id"]]


def track_of(f: dict) -> list[dict]:
    """The health track the fighter's marker is currently on.

    Bödvar swaps his for the Bear's; the Fey Folk have one per Character and only
    the active one is on a track at all.
    """
    board = _board(f)
    if f.get("face") == "berserker_bear":
        return board["back"]["hp_track"]
    if board.get("characters"):
        for ch in board["characters"]:
            if ch["id"] == f.get("character"):
                return ch["hp_track"]
        return []
    return board["hp_track"]


def hp_index(f: dict) -> int:
    return f["hp"]


def hp_value(f: dict) -> int:
    """Printed HP, or 0 on a KO / Spirit / revive space."""
    track = track_of(f)
    if not track or f["hp"] is None:
        return 0
    space = track[f["hp"]]
    return space["hp"] if space["kind"] == "hp" else 0


def max_hp(f: dict) -> int:
    return max((s["hp"] for s in track_of(f) if s["kind"] == "hp"), default=0)


def is_ko(f: dict) -> bool:
    track = track_of(f)
    if not track or f["hp"] is None:
        return False
    return track[f["hp"]]["kind"] == "ko"


def partner_slot(slot: int) -> int:
    return 1 - slot


def other_seat(seat: int) -> int:
    return 1 - seat


# ==========================================================================
# Setup
# ==========================================================================

def new_game(seats: list[str], seed: int | None = None) -> dict:
    """A fresh game in the draft phase. `seats` is [pid, pid]."""
    if len(seats) != 2:
        raise IllegalMove("Rag Tag is a two-player game")

    r = random.Random(seed)
    draft = list(ROSTER)
    r.shuffle(draft)

    game: dict[str, Any] = {
        "version": VERSION,
        "phase": "draft",
        "seats": list(seats),
        "round": 1,
        "turn": 0,
        "draft_round": 1,
        "draft_hands": [draft[:DRAFT_HAND], draft[DRAFT_HAND:]],
        "draft_picks": [[], []],
        "teams": [[], []],
        "fighters": [[], []],
        "instances": [],
        "fight_deck": [[], []],
        "build_deck": [[], []],
        "played": [[], []],
        "build_offer": [None, None],
        "build_choice": [None, None],
        "order_choice": [None, None],
        "beats": [],
        "pending_pid": None,
        "pending_kind": None,
        "pending": None,
        "double_next": [False, False],
        "log": [],
        "winner": None,
        "rng_state": None,
    }
    _save_rng(game, r)
    return game


def seat_of(game: dict, pid: str) -> int:
    try:
        return game["seats"].index(pid)
    except ValueError as exc:
        raise IllegalMove("not a player in this game") from exc


def _log(game: dict, text: str) -> None:
    game["log"].append(text)


# -------------------------------------------------------------- the draft

def draft_pick(game: dict, pid: str, fid: str) -> None:
    """Both players pick simultaneously; the phase advances when both are in."""
    if game["phase"] != "draft":
        raise IllegalMove("not drafting")
    seat = seat_of(game, pid)
    if len(game["draft_picks"][seat]) >= game["draft_round"]:
        raise IllegalMove("you have already picked this round")
    if fid not in game["draft_hands"][seat]:
        raise IllegalMove("that fighter is not in your hand")

    game["draft_picks"][seat].append(fid)
    game["draft_hands"][seat].remove(fid)

    if all(len(p) >= game["draft_round"] for p in game["draft_picks"]):
        if game["draft_round"] == 1:
            # Pass the leftovers across and pick a second.
            game["draft_hands"] = [game["draft_hands"][1], game["draft_hands"][0]]
            game["draft_round"] = 2
        else:
            _begin_order(game)


def _begin_order(game: dict) -> None:
    """Teams are set. Build the boards, the decks, and ask for the card order."""
    for seat in (0, 1):
        game["teams"][seat] = list(game["draft_picks"][seat])
        game["fighters"][seat] = [_new_fighter(fid) for fid in game["teams"][seat]]
    game["draft_hands"] = [[], []]

    with _with_rng(game) as r:
        for seat in (0, 1):
            build: list[int] = []
            for slot, fid in enumerate(game["teams"][seat]):
                start_cid = STARTING_CARD[fid]
                start_done = False
                for cid in DECKS[fid]:
                    inst = len(game["instances"])
                    game["instances"].append(
                        {"cid": cid, "seat": seat, "slot": slot, "flipped": False})
                    if cid == start_cid and not start_done:
                        start_done = True
                        game["fight_deck"][seat].append(inst)
                    else:
                        build.append(inst)
            r.shuffle(build)
            game["build_deck"][seat] = build
        for side in game["fighters"]:
            for f in side:
                if "serpent" in f["tokens"]:
                    f["tokens"]["serpent_face"] = r.randint(0, 1)
                if f["tokens"].get("scheme"):
                    f["scheme_pool"] = _scheme_pile(r)

    game["phase"] = "order"
    _apply_setup_icons(game)
    _pend_fey_folk_setup(game)


def _apply_setup_icons(game: dict) -> None:
    """Fighter board icons that resolve ONCE, the moment the teams are known.

    Only the Wild Bunch has one today ("gives partner 1 power"), and the engine simply
    never read the field -- `setup_icons` was generated by import_bga, validated by
    test_fighters, and executed by nobody. That silence is the whole bug: the partner
    started the game one Power short in EVERY game with the Wild Bunch on the table,
    and no test noticed because nothing asserted a starting Power that wasn't base.

    So this raises on any op it does not implement, rather than skipping it. A setup
    icon that no longer resolves must break the suite, not go quiet again.
    """
    for seat in (0, 1):
        for slot, f in enumerate(game["fighters"][seat]):
            for op in _board(f).get("setup_icons", []):
                if op["op"] != "power":
                    raise IllegalMove(
                        f"unimplemented setup icon {op['op']!r} on {f['id']}")
                target = op.get("target", "self")
                if target == "self":
                    who = slot
                elif target == "partner":
                    who = partner_slot(slot)
                else:
                    raise IllegalMove(
                        f"unimplemented setup icon target {target!r} on {f['id']}")
                n = op["n"]
                if not isinstance(n, int):
                    raise IllegalMove(
                        f"non-constant setup icon amount {n!r} on {f['id']}")
                game["fighters"][seat][who]["power"] += n


def _new_fighter(fid: str) -> dict:
    board = FIGHTERS[fid]
    f: dict[str, Any] = {
        "id": fid,
        "power": board["base_power"],
        "tokens": {k: 0 for k in board.get("tokens", {})},
        "tracks": {},
        "face": board["faces"][0] if board.get("faces") else None,
        "character": None,
        "chars": {},
        "hp": None,
    }
    special = board.get("special_track")
    if special:
        f["tracks"][special["id"]] = special.get("start", 0)
        if special["id"] == "divine_voice":
            f["tracks"]["divine_voice"] = 0         # the central Halo, space 0 of 5
    if board.get("characters"):
        f["chars"] = {ch["id"]: "waiting" for ch in board["characters"]}
    else:
        f["hp"] = _start_index(board["hp_track"])
    # Supplies start in the fighter's own pool: Shango holds his 5 Aflame! tokens,
    # Milady her 11 Schemes, the Wild Bunch the Sheriff, the Golem his Presence.
    for name, count in board.get("tokens", {}).items():
        f["tokens"][name] = count
    f["planted"] = 0        # Milady: face-down Schemes above her board
    f["scheme_pool"] = []   # filled at setup so a reveal is reproducible
    return f


def _scheme_pile(r: random.Random) -> list[str]:
    """Milady's Intrigues, shuffled face-down at setup.

    The pile is drawn WITHOUT REPLACEMENT -- a revealed token leaves the game -- so the
    eleven tokens have to exist as eleven tokens. Picking an effect at random per reveal
    (what this used to do) makes every Intrigue an independent 1-in-9, which prices poison
    at 11% instead of the 3-in-11 it starts at and lets one game reveal the same unique
    token four times.

    Shuffling at SETUP rather than drawing at reveal is what makes a game reproducible from
    its seed, and it is the hook a replay overrides -- the same treatment the draft and the
    Build deck get.
    """
    pile = [eff["id"] for eff in MILADY_SCHEMES["effects"] for _ in range(eff["copies"])]
    r.shuffle(pile)
    return pile


def _start_index(track: list[dict]) -> int:
    for i, space in enumerate(track):
        if space.get("start"):
            return i
    raise IllegalMove("track has no start space")


def _pend_fey_folk_setup(game: dict) -> None:
    """The Fey Folk choose their opening Character before anything else."""
    for seat in (0, 1):
        for slot, f in enumerate(game["fighters"][seat]):
            if not _board(f).get("characters") or f["character"] is not None:
                continue
            options = [ch["id"] for ch in _board(f)["characters"]
                       if f["chars"][ch["id"]] == "waiting"]
            if not options:
                # All three are Spirits. They stay off the tracks -- still able
                # to perform card actions, just unable to lose or recover HP --
                # and there is nothing to ask.
                continue
            game["pending_pid"] = game["seats"][seat]
            game["pending_kind"] = "choose_character"
            game["pending"] = {"seat": seat, "slot": slot, "options": options}
            return
    game["pending_pid"] = game["pending_kind"] = game["pending"] = None


# ==========================================================================
# Card faces
# ==========================================================================

def card_of(game: dict, inst: int) -> dict:
    return CARDS[game["instances"][inst]["cid"]]

def _ops_of(game: dict, inst: int, f: dict) -> list[dict]:
    """The ops actually printed on the face now showing."""
    card = card_of(game, inst)
    if card.get("two_faced") and game["instances"][inst]["flipped"]:
        return card["ops_back"]
    return card["ops"]


# ==========================================================================
# Health-track movement
# ==========================================================================

def _move_marker(game: dict, seat: int, slot: int, delta: int,
                 beat: dict) -> list[dict]:
    """Move one marker by `delta` and return the spaces it landed on or passed.

    STOP halts movement the instant the marker lands on it, up or down alike. A
    fighter already on KO can never be Healed. The bottom space of the track is
    the floor: further losses there are simply ignored, which is exactly how
    Maman Brijit survives on her revive space.
    """
    f = fighter(game, seat, slot)
    track = track_of(f)
    if not track or f["hp"] is None or delta == 0:
        return []
    if delta > 0 and is_ko(f):
        return []                                   # no healing at KO

    step = 1 if delta > 0 else -1
    top = len(track) - 1
    passed: list[dict] = []
    start = f["hp"]
    pos = start
    for _ in range(abs(delta)):
        nxt = pos + step
        if nxt < 0 or nxt > top:
            break
        pos = nxt
        passed.append(track[pos])
        if "stop" in track[pos].get("icons", []):
            break

    if pos == start:
        return []
    f["hp"] = pos
    beat["events"].append({"kind": "hp", "seat": seat, "slot": slot,
                           "from": start, "to": pos})
    return passed


# ==========================================================================
# The turn
# ==========================================================================

class Turn:
    """One FIGHT! turn in flight. This is the object every fx receives.

    It carries the Power snapshot, the declared actions, and the helpers an
    effect is allowed to reach state through -- so a card can never poke the game
    dict directly and quietly break an invariant.
    """

    def __init__(self, game: dict, revealed: list[int | None]):
        self.game = game
        self.revealed = revealed
        self.active: list[int] = []
        self.cancelled = [False, False]
        self.attacks: list[dict] = []
        self.blocks: list[dict] = []
        self.hp_delta: dict[tuple[int, int], int] = {}
        self.power_ops: list[tuple[int, int, int]] = []
        # (seat, ACTING FIGHTER, op). The fighter has to travel with the op: a deferred
        # op used to be re-run against `turn.active[seat]`, so an Intrigue unleashed by an
        # icon on Milady's own health track resolved as her PARTNER and found no planted
        # Schemes -- silently nothing, in eight games.
        self.deferred: list[tuple[int, tuple[int, int], dict]] = []
        self.beat: dict = {"events": []}
        self.power_snapshot: dict[tuple[int, int], int] = {}
        self.immune: set[tuple[int, int]] = set()
        self.ignore_hp: set[tuple[int, int]] = set()
        self.instant_win: int | None = None
        self.instant_loss: set[int] = set()
        self.fey_folk_losses: set[int] = set()
        self.revive: set[tuple[int, int]] = set()
        self.drag: set[int] = set()
        self.post_declare: list = []
        self.late_conds: list = []
        self.in_lull_cond = 0
        self.heal_log: list = []
        self.removed: list[int] = []
        self.spirits_at_start: dict[tuple[int, int], int] = {}
        for _s in (0, 1):
            for _t in (0, 1):
                self.spirits_at_start[(_s, _t)] = \
                    game["fighters"][_s][_t]["tracks"].get("spirits", 0)
        self.double_next: set[int] = set()

        for seat in (0, 1):
            for slot in (0, 1):
                self.power_snapshot[(seat, slot)] = fighter(game, seat, slot)["power"]
            inst = revealed[seat]
            self.active.append(game["instances"][inst]["slot"] if inst is not None else 0)

    # ---- addressing --------------------------------------------------
    def resolve_target(self, seat: int, target: str,
                       who: tuple[int, int] | None = None) -> list[tuple[int, int]]:
        """Who `target` names, from the point of view of the fighter doing the acting.

        `who` DEFAULTS to the seat's Active Fighter, which is right for a card -- a card is
        played by the fighter who is up. It is NOT right for a HEALTH-TRACK ICON, which
        belongs to whoever's marker just moved, and that fighter is often the Partner.
        Reading "self" off the active fighter regardless sent every icon on a non-active
        board to the wrong fighter: the Golem's own +1 Power icons landed on Bodvar all game
        (902218046 f2t2 and f2t3), and his Attacks then went out at 2 Power where BGA's went
        out at 4.
        """
        me = who or (seat, self.active[seat])
        mate = (me[0], partner_slot(me[1]))
        opp = (other_seat(seat), self.active[other_seat(seat)])
        opp_mate = (other_seat(seat), partner_slot(self.active[other_seat(seat)]))
        return {
            "self": [me], "partner": [mate], "opp": [opp], "opp_partner": [opp_mate],
            "both_opps": [opp, opp_mate],
            "all_others": [mate, opp, opp_mate],
            "all": [me, mate, opp, opp_mate],
        }[target]

    def actor(self, seat: int, by: str | None,
              who: tuple[int, int] | None = None) -> tuple[int, int]:
        """Whose Power an Attack is thrown with.

        Same rule as `resolve_target`: the fighter doing the acting, which defaults to the
        Active Fighter but is not it when a health-track icon or an Intrigue is what
        performs the Attack. Milady's Intrigue Attack was being thrown with her PARTNER's
        Power and credited to them (886310308 f4t5: BGA hits for 4, we hit for 2).
        """
        me = who or (seat, self.active[seat])
        if by == "partner":
            return (me[0], partner_slot(me[1]))
        return me

    # ---- helpers effects may use -------------------------------------
    def f(self, who: tuple[int, int]) -> dict:
        return fighter(self.game, who[0], who[1])

    def power(self, who: tuple[int, int]) -> int:
        """Power at the START of the turn -- what every Attack reads."""
        return self.power_snapshot[who]

    def add_hp(self, who: tuple[int, int], delta: int) -> None:
        if who in self.ignore_hp or who in self.immune:
            return
        self.hp_delta[who] = self.hp_delta.get(who, 0) + delta

    def add_power(self, who: tuple[int, int], delta: int) -> None:
        self.power_ops.append((who[0], who[1], delta))

    def flush_power(self, who: tuple[int, int]) -> None:
        """Apply this fighter's queued Power changes right now.

        Power normally settles after the cards, because Power gained this turn
        must not fuel this turn's Attacks. Bödvar's transformation is the one
        thing that has to read the NEW number: the rage space grants +3 and only
        THEN does he flip, and the Bear's opening HP is his cubes at that instant.
        """
        keep = []
        for seat, slot, delta in self.power_ops:
            if (seat, slot) == who:
                f = fighter(self.game, seat, slot)
                f["power"] = max(0, f["power"] + delta)
            else:
                keep.append((seat, slot, delta))
        self.power_ops = keep

    def add_attack(self, seat: int, source: tuple[int, int],
                   targets: list[tuple[int, int]], power: int,
                   conditional_on_lull: bool = False,
                   success: list[dict] | None = None) -> dict:
        atk = {"seat": seat, "source": source, "targets": list(targets),
               "power": power, "negated": False, "success": success or [],
               "conditional_on_lull": conditional_on_lull or self.in_lull_cond > 0}
        self.attacks.append(atk)
        return atk

    def note(self, **event) -> None:
        self.beat["events"].append(event)

    def move_token(self, src, dst, token: str) -> None:
        _move_token(self, src, dst, token)

    def token_holder(self, token: str):
        return token_holder(self.game, token)

    def remove_from_play(self, inst) -> None:
        """Take a card out of the game for good (Wong's Crippling Touch).

        It has already left the Fight Deck by the time a card resolves, so the
        removal is from this round's played pile -- otherwise it would come back
        as part of the next Fight Deck.
        """
        if inst is None:
            return
        game = self.game
        seat = game["instances"][inst]["seat"]
        for pile in (game["played"][seat], game["fight_deck"][seat],
                     game["build_deck"][seat]):
            if inst in pile:
                pile.remove(inst)
        if inst not in self.removed:
            self.removed.append(inst)
            self.note(kind="removed", seat=seat, inst=inst)


# ---------------------------------------------------------------- declare

def _value(turn: Turn, seat: int, who: tuple[int, int], value: Any) -> int:
    """An int, or one of the computed values effects.VALUE_KINDS declares."""
    if isinstance(value, int):
        return value
    kind = value["kind"]
    if kind == "power":
        return turn.power(who)
    if kind == "spirits":
        return _spirits(turn.f(who)) * value.get("times", 1)
    if kind == "attacking_opponents_power":
        total = 0
        for atk in turn.attacks:
            if atk["seat"] == other_seat(seat) and atk["negated"]:
                total += atk["power"]
        return total
    raise IllegalMove(f"unknown computed value {kind!r}")


def _spirits(f: dict) -> int:
    return f["tracks"].get("spirits", 0)


#: Conditions that read the opposing card. Evaluating one during the first pass
#: would answer it against a half-declared turn -- and since seat 0 is always
#: walked first, it would answer it WRONG, always and only for seat 0. That is a
#: silent seat bias, which is exactly the kind of bug a soak shows as a losing
#: record and never as a crash.
OPPONENT_DEPENDENT = frozenset({
    "no_opponent_attacked", "self_attacked", "own_attack_blocked",
})


def _cond(turn: Turn, seat: int, who: tuple[int, int], cond: dict) -> bool:
    kind = cond["kind"]
    me = turn.f(who)
    if kind == "power_at_least":
        return turn.power(who) >= cond["n"]
    if kind == "hp_equals":
        return hp_value(me) == cond["n"]
    if kind == "no_opponent_attacked":
        # INFERRED: a conditional Attack gated on this same clause does not count,
        # or two mirrored Hidden Daggers would be circular.
        return not any(a["seat"] == other_seat(seat) and not a["conditional_on_lull"]
                       for a in turn.attacks)
    if kind == "self_attacked":
        # INFERRED: declared and not cancelled is enough -- a Block negates the
        # damage, not the fact that an Attack was performed.
        return any(who in a["targets"] for a in turn.attacks
                   if a["seat"] == other_seat(seat))
    if kind == "own_attack_blocked":
        return any(a["negated"] for a in turn.attacks if a["source"] == who)
    if kind == "opponent_played_starting_card":
        inst = turn.revealed[other_seat(seat)]
        if inst is None:
            return False
        card = card_of(turn.game, inst)
        return bool(card.get("starting"))
    if kind == "serpent":
        return me["tokens"].get("serpent_face", 0) == (1 if cond["face"] == "black" else 0)
    if kind == "face":
        return me.get("face") == cond["face"]
    if kind == "ships":
        return cond["min"] <= me["tracks"].get("navigation", 0) <= cond["max"]
    if kind == "has_token":
        return me["tokens"].get(cond["token"], 0) > 0
    if kind == "token_on":
        who2 = turn.resolve_target(who[0], cond["who"], who)[0]
        return turn.f(who2)["tokens"].get(cond["token"], 0) > 0
    raise IllegalMove(f"unknown condition {kind!r}")


def _run_ops(turn: Turn, seat: int, ops: Iterable[dict], phase: str) -> None:
    """Walk a card's ops. `phase` is 'declare' or 'late' (icons, bonuses, THEN)."""
    who = (seat, turn.active[seat])
    for op in ops:
        if op.get("after") and phase == "declare":
            turn.deferred.append((seat, who, op))
            continue
        _run_op(turn, seat, who, op, phase)


def _run_op(turn: Turn, seat: int, who: tuple[int, int], op: dict, phase: str) -> None:
    name = op["op"]

    if name == "if":
        if phase == "declare" and op["cond"]["kind"] in OPPONENT_DEPENDENT:
            turn.late_conds.append((seat, who, op))
            return
        lull = op["cond"]["kind"] == "no_opponent_attacked"
        if lull:
            turn.in_lull_cond += 1
        try:
            branch = (op["then"] if _cond(turn, seat, who, op["cond"])
                      else op.get("else", []))
            for sub in branch:
                _run_op(turn, seat, who, sub, phase)
        finally:
            if lull:
                turn.in_lull_cond -= 1
        return

    if name == "attack":
        src = turn.actor(seat, op.get("by"), who)
        power = turn.power(src)
        if op.get("power_bonus"):
            power += _value(turn, seat, who, op["power_bonus"])
        targets = turn.resolve_target(seat, op.get("target", "opp"), who)
        if op.get("flamepower"):
            # Shango: +1 per Aflame! token already on the target, so each target
            # takes a different number and they cannot share one attack entry.
            made = [turn.add_attack(seat, src, [tgt],
                                    power + turn.f(tgt)["tokens"].get("aflame", 0),
                                    success=op.get("success"))
                    for tgt in targets]
        else:
            made = [turn.add_attack(seat, src, targets, power,
                                    success=op.get("success"))]
        if phase == "late":
            # AN ATTACK DECLARED AFTER THE DECLARE STEP HAS TO LAND ITSELF. The declare
            # step turns queued Attacks into HP at its end, and it has already run by the
            # time an icon or a deferred THEN speaks -- so a late Attack used to be filed
            # and never resolved. Milady's health-track Intrigue is the visible case: BGA
            # 901568802 f2t2 has her Attack the Golem off the track, the presence eat it
            # and the token go home, which flips the NEXT Protect the Innocent to its
            # expensive branch. We queued the Attack, dealt nothing, kept the token, and
            # took the cheap branch for the rest of the game.
            _apply_blocks(turn)                    # a Block still catches it
            for atk in made:
                # Note it here: the declare step narrates its own Attacks and has already
                # been and gone, so without this an Intrigue's Attack lands with nothing in
                # the beat to show for it and the fight log skips a hit.
                turn.note(kind="attack", seat=atk["seat"], slot=atk["source"][1],
                          power=atk["power"], negated=bool(atk["negated"]),
                          targets=[[t[0], t[1]] for t in atk["targets"]])
                _land_attack(turn, atk)
        return

    if name == "block":
        turn.blocks.append({"seat": seat, "source": who, "success": op.get("success", []),
                            "worked": False})
        return

    if name == "damage":
        for tgt in turn.resolve_target(seat, op.get("target", "opp"), who):
            turn.add_hp(tgt, -_value(turn, seat, who, op["n"]))
        return

    if name == "heal":
        for tgt in turn.resolve_target(seat, op.get("target", "self"), who):
            amount = _value(turn, seat, who, op["n"])
            turn.add_hp(tgt, amount)
            turn.heal_log.append((seat, tgt, amount))
        return

    if name == "power":
        for tgt in turn.resolve_target(seat, op.get("target", "self"), who):
            turn.add_power(tgt, _value(turn, seat, who, op["n"]))
        return

    if name == "transfer_power":
        src = turn.resolve_target(seat, op["from"], who)[0]
        dst = turn.resolve_target(seat, op["to"], who)[0]
        amount = min(op["n"], turn.f(src)["power"])
        if amount:
            turn.add_power(src, -amount)
            turn.add_power(dst, amount)
        return

    if name == "cancel":
        for tgt in turn.resolve_target(seat, op.get("target", "opp"), who):
            turn.cancelled[tgt[0]] = True
        return

    if name == "track":
        advance_track(turn, who, op["track"], op["n"])
        return

    if name == "spirit":
        advance_track(turn, who, "spirits", op["n"])
        return

    if name == "ignite":
        opp = turn.resolve_target(seat, "opp", who)[0]
        _ignite(turn, who, opp)
        return

    if name == "plant_scheme":
        _plant_scheme(turn, who)
        return

    if name == "unleash_scheme":
        _unleash_scheme(turn, who, phase)
        return

    if name == "give_token":
        dst = turn.resolve_target(seat, op["to"], who)[0]
        _move_token(turn, who, dst, op["token"])
        return

    if name == "take_token":
        if op.get("from"):
            _move_token(turn, turn.resolve_target(seat, op["from"], who)[0], who,
                        op["token"])
        else:
            _take_token(turn, who, op["token"])
        return

    if name == "flip_card":
        inst = turn.revealed[seat]
        if inst is not None:
            turn.game["instances"][inst]["flipped"] = True
            turn.note(kind="flip", seat=seat, inst=inst)
        return

    if name == "fx":
        handler = effects.FIGHTER_FX.get(op["name"])
        if handler is None:
            raise IllegalMove(f"unimplemented effect {op['name']!r}")
        handler(turn, seat, who, phase)
        return

    raise IllegalMove(f"unknown op {name!r}")


# ==========================================================================
# Tracks, tokens, schemes
# ==========================================================================

def advance_track(turn: Turn, who: tuple[int, int], name: str, n: int) -> None:
    f = turn.f(who)
    board = _board(f)
    special = board.get("special_track")
    if name == "spirits":
        spec = special if special and special["id"] == "spirits" else None
    else:
        spec = special if special and special["id"] == name else None
    if spec is None:
        return

    before = f["tracks"].get(name, 0)
    if spec["shape"] == "circular":
        # Only the space it LANDS on fires; spaces stepped over do nothing.
        #
        # `wrap_to` is the space the ring returns to, which is NOT always index 0: Joan's
        # dial has five printed positions but a cycle of four, because the central Halo is
        # only where the marker starts. Measured over the corpus -- 21 first moves all onto
        # 1, transitions 1->2, 2->3, 3->4, 4->1, and not one 4->0. A plain modulo made the
        # ring five long, so from the second lap her Power arrived a step late.
        spaces = spec["spaces"]
        wrap = next((i for i, sp in enumerate(spaces)
                     if sp.get("name") == spec.get("wrap_to")), 0)
        pos = before
        for _ in range(n):
            pos = pos + 1 if pos + 1 < len(spaces) else wrap
        f["tracks"][name] = pos
        turn.note(kind="track", seat=who[0], slot=who[1], track=name,
                  **{"from": before, "to": pos})
        for icon in spaces[pos].get("icons", []):
            _run_op(turn, who[0], who, icon, "late")
        return

    if spec["shape"] == "linear" and "max" in spec:
        pos = max(spec.get("min", 0), min(spec["max"], before + n))
    else:
        pos = max(0, min(len(spec["spaces"]) - 1, before + n))
    if pos == before:
        return
    f["tracks"][name] = pos
    turn.note(kind="track", seat=who[0], slot=who[1], track=name,
              **{"from": before, "to": pos})
    if spec.get("spaces"):
        for step in range(before + 1, pos + 1):
            for icon in spec["spaces"][step].get("icons", []):
                _run_op(turn, who[0], who, icon, "late")


def _ignite(turn: Turn, src: tuple[int, int], tgt: tuple[int, int]) -> None:
    """Shango: 1 Aflame! on the Opponent. Not an Attack, so unblockable.

    If they had none, every token on their Partner goes back to Shango's supply
    first -- the flames jump rather than spread.
    """
    shango, target = turn.f(src), turn.f(tgt)
    had = target["tokens"].get("aflame", 0)
    if had == 0:
        mate = turn.f((tgt[0], partner_slot(tgt[1])))
        back = mate["tokens"].get("aflame", 0)
        if back:
            mate["tokens"]["aflame"] = 0
            shango["tokens"]["aflame"] = shango["tokens"].get("aflame", 0) + back
            turn.note(kind="token", token="aflame", seat=tgt[0],
                      slot=partner_slot(tgt[1]), delta=-back)
    if shango["tokens"].get("aflame", 0) <= 0:
        return
    shango["tokens"]["aflame"] -= 1
    target["tokens"]["aflame"] = had + 1
    turn.note(kind="token", token="aflame", seat=tgt[0], slot=tgt[1], delta=1)
    if target["tokens"]["aflame"] >= 5:
        # Incineration is an instant loss and OVERRIDES a simultaneous double KO.
        turn.instant_loss.add(tgt[0])


def _plant_scheme(turn: Turn, who: tuple[int, int]) -> None:
    f = turn.f(who)
    if f["tokens"].get("scheme", 0) <= 0:
        return
    f["tokens"]["scheme"] -= 1
    f["planted"] += 1
    turn.note(kind="scheme", seat=who[0], slot=who[1], planted=f["planted"])


def _unleash_scheme(turn: Turn, who: tuple[int, int], phase: str) -> None:
    """Flip one random planted Scheme, apply it, and remove it from the game.

    Poison always goes last of all the Intrigues resolved this turn, and it reads
    the HP total AFTER everything else -- so it is deferred rather than run here.
    """
    f = turn.f(who)
    if f["planted"] <= 0 or not f.get("scheme_pool"):
        return
    f["planted"] -= 1
    eid = f["scheme_pool"].pop(0)
    eff = next(e for e in MILADY_SCHEMES["effects"] if e["id"] == eid)
    turn.note(kind="scheme_reveal", seat=who[0], slot=who[1], effect=eff["id"])
    if eff["id"] == "poison":
        turn.deferred.append((who[0], who, {"op": "fx", "name": "milady_poison"}))
        return
    for op in eff["ops"]:
        _run_op(turn, who[0], who, op, phase)


def _move_token(turn: Turn, src: tuple[int, int], dst: tuple[int, int],
                token: str) -> None:
    """Move a token to `dst`. If `src` is not holding it, whoever is does.

    The Wild Bunch's Keys to the Armory hands over a Sheriff that may be sitting
    on an opposing board, so "give" cannot mean "give one of mine".
    """
    if turn.f(src)["tokens"].get(token, 0) <= 0:
        holder = token_holder(turn.game, token)
        if holder is None or holder == dst:
            return
        src = holder
    a, b = turn.f(src), turn.f(dst)
    if a["tokens"].get(token, 0) <= 0:
        return
    a["tokens"][token] -= 1
    b["tokens"][token] = b["tokens"].get(token, 0) + 1
    turn.note(kind="token", token=token, seat=dst[0], slot=dst[1], delta=1)


def _take_token(turn: Turn, who: tuple[int, int], token: str) -> None:
    """Pull a token back from whoever is holding it."""
    for seat in (0, 1):
        for slot in (0, 1):
            if (seat, slot) == who:
                continue
            other = fighter(turn.game, seat, slot)
            if other["tokens"].get(token, 0) > 0:
                other["tokens"][token] -= 1
                turn.f(who)["tokens"][token] = turn.f(who)["tokens"].get(token, 0) + 1
                turn.note(kind="token", token=token, seat=who[0], slot=who[1], delta=1)
                return


def token_holder(game: dict, token: str) -> tuple[int, int] | None:
    for seat in (0, 1):
        for slot in (0, 1):
            if fighter(game, seat, slot)["tokens"].get(token, 0) > 0:
                return (seat, slot)
    return None


# ==========================================================================
# Resolving one turn
# ==========================================================================

def _declare(turn: Turn) -> None:
    """Steps 2-3: cancels, then everything both cards perform."""
    game = turn.game

    # Cancel is read off both cards BEFORE anything else runs, because a
    # cancelled card contributes nothing at all -- including its own cancel.
    for seat in (0, 1):
        inst = turn.revealed[seat]
        if inst is None:
            continue
        f = fighter(game, seat, turn.active[seat])
        for op in _ops_of(game, inst, f):
            if op["op"] == "cancel":
                turn.cancelled[other_seat(seat)] = True
                turn.note(kind="cancel", seat=seat, target=other_seat(seat))

    for seat in (0, 1):
        inst = turn.revealed[seat]
        if inst is None or turn.cancelled[seat]:
            continue
        f = fighter(game, seat, turn.active[seat])
        _run_ops(turn, seat, _ops_of(game, inst, f), "declare")

    _apply_blocks(turn)

    # BLOCKS, THEIR BONUSES AND THE CONDITIONAL BRANCHES SETTLE TOGETHER, by iterating.
    # There is no fixed order that gets both of these right, and the corpus has both:
    #
    #   902217634 f2t3  Milady Attacks -> Mordred BLOCKS -> the Block's bonus is a riposte
    #                   -> Milady's "if you are Attacked" must SEE that riposte.
    #   902206465 f6t1  Mordred's "if neither Opponent Attacks" fires -> that Attack is
    #                   what makes Milady's Block work -> only then does her Block pay out.
    #
    # Bonuses-first gets the second wrong; branches-first gets the first wrong. So each pass
    # applies the Blocks, pays out any Block that has NOW caught something (once each), and
    # only when nothing new came of that does it read the branches whose condition has
    # become true. Whatever that adds starts another pass. A branch still undecided when
    # the loop settles is false, and takes its else.
    fired: set[int] = set()
    pending = list(turn.late_conds)
    for _ in range(MAX_ICON_PASSES):
        _apply_blocks(turn)
        progressed = False
        for i, block in enumerate(turn.blocks):
            if i in fired or not (block["worked"] and block["success"]):
                continue
            fired.add(i)
            for op in block["success"]:
                _run_op(turn, block["seat"], block["source"], op, "declare")
            progressed = True
        if progressed:
            continue
        still = []
        for cond_seat, cond_who, op in pending:
            if _cond(turn, cond_seat, cond_who, op["cond"]):
                _run_op(turn, cond_seat, cond_who, op, "late_cond")
                progressed = True
            else:
                still.append((cond_seat, cond_who, op))
        pending = still
        if not progressed:
            break
    _apply_blocks(turn)
    for cond_seat, cond_who, op in pending:
        _run_op(turn, cond_seat, cond_who, op, "late_cond")   # settles false: the else branch
    _apply_blocks(turn)

    # An Attack that nothing Blocked is knowable only once every Block is in.
    for atk in list(turn.attacks):
        if not atk["negated"] and atk["success"]:
            for op in atk["success"]:
                _run_op(turn, atk["seat"], atk["source"], op, "declare")

    # Hooks that must see BOTH cards walked before they act -- Maman Brijit's
    # Eternal Youth cannot know what to steal until the other side has healed.
    for name, hook_seat, hook_who in turn.post_declare:
        effects.FIGHTER_FX[name if name in effects.FIGHTER_FX
                           else "brijit_eternal_youth"](turn, hook_seat, hook_who, "late")

    # Record what was thrown BEFORE the damage is queued, so the beat reads in
    # causal order: cards, then Attacks and Blocks, then the HP that moved. The
    # targets are stored as lists, not tuples -- beats are persisted, and a tuple
    # comes back from JSON as a list, so storing tuples makes a reloaded game
    # differ from a live one in a way nothing would notice until it mattered.
    for block in turn.blocks:
        turn.note(kind="block", seat=block["seat"], slot=block["source"][1],
                  worked=bool(block["worked"]))
    for atk in turn.attacks:
        turn.note(kind="attack", seat=atk["seat"], slot=atk["source"][1],
                  power=atk["power"], negated=bool(atk["negated"]),
                  targets=[[t[0], t[1]] for t in atk["targets"]])

    # Surviving Attacks land. Several sources hitting one fighter is a single
    # Attack of their combined Power, which only shows in the log.
    for atk in turn.attacks:
        _land_attack(turn, atk)


def _land_attack(turn: Turn, atk: dict) -> None:
    """Turn one surviving Attack into HP loss, spending any shield in its way."""
    if atk["negated"] or atk["power"] < 0:
        return
    for tgt in atk["targets"]:
        if atk["power"] > 0 and _absorb_attack(turn, tgt):
            continue
        turn.add_hp(tgt, -atk["power"])


def _absorb_attack(turn: Turn, who: tuple[int, int]) -> bool:
    """Eat one Attack with a shield token, and send the token home.

    The Golem's presence is the only one today. Protect the Innocent INVESTS -- he takes 3
    and his Partner gains the token -- and the token is spent the next time an Attack is
    aimed at whoever holds it, returning to the Golem so the card can be invested again.

    Read straight off BGA's log rather than guessed: 902218046 f1t2 has "The Wild Bunch
    attacks Bodvar", Bodvar loses no health, and "The Golem gains [token]" in the same
    breath; 886355216 f2t2 has Maman Brijit DEFLECT the Golem's own Attack onto his partner
    Milady, where the presence eats it. Modelling the token as a permanent flag -- which is
    what we had -- pinned the card's if/else on "partner has it" after a single play, so the
    Golem attacked free for the rest of the game and never paid the 3 again.

    A 0-Power Attack does not spend it (nothing would have landed); a Block, which negates
    the Attack outright, gets there first and spends nothing either.
    """
    holder = turn.f(who)
    for seat in (0, 1):
        for slot in (0, 1):
            owner = fighter(turn.game, seat, slot)
            for token in _board(owner).get("absorbs_attack", []):
                # The owner holding it is the token sitting BESIDE their board, unassigned:
                # it shields whoever it was given to, never its owner.
                if (seat, slot) == who or holder["tokens"].get(token, 0) <= 0:
                    continue
                holder["tokens"][token] -= 1
                owner["tokens"][token] = owner["tokens"].get(token, 0) + 1
                turn.note(kind="absorb", token=token, seat=who[0], slot=who[1])
                turn.note(kind="token", token=token, seat=seat, slot=slot, delta=1)
                return True
    return False


def _apply_blocks(turn: Turn) -> None:
    """A Block negates every Attack the opposing team performed, whatever it was
    aimed at -- and a Block that catches even a 0-Power Attack has succeeded."""
    for block in turn.blocks:
        for atk in turn.attacks:
            if atk["seat"] == other_seat(block["seat"]):
                atk["negated"] = True
                block["worked"] = True


def _apply_hp_and_icons(turn: Turn) -> None:
    """Steps 4-5: one netted movement each, then icons until everything settles."""
    pending = dict(turn.hp_delta)
    turn.hp_delta.clear()

    for _ in range(MAX_ICON_PASSES):
        if not pending:
            return
        passed: list = []
        for who, delta in sorted(pending.items()):
            if delta == 0 or who in turn.immune:
                continue
            for space in _move_marker(turn.game, who[0], who[1], delta, turn.beat):
                passed.append((who, space))
        pending = {}

        # Icons fire only once every marker has finished moving, and all at once.
        for who, space in passed:
            for icon in space.get("icons", []):
                if isinstance(icon, str):
                    continue                       # 'stop' is a movement rule
                _run_op(turn, who[0], who, icon, "late")
        pending = dict(turn.hp_delta)
        turn.hp_delta.clear()


def _apply_power(turn: Turn) -> None:
    for seat, slot, delta in turn.power_ops:
        f = fighter(turn.game, seat, slot)
        before = f["power"]
        f["power"] = max(0, before + delta)
        if f["power"] != before:
            turn.note(kind="power", seat=seat, slot=slot,
                      **{"from": before, "to": f["power"]})
    turn.power_ops.clear()


def _settle(turn: Turn) -> None:
    _apply_hp_and_icons(turn)
    _do_revives(turn)
    _apply_power(turn)


#: Fighter fields a BEAT must not carry. `scheme_pool` is Milady's face-down Intrigue
#: pile, and its ORDER is every reveal she has left -- `public_view` strips it from the
#: live fighters, but a beat is shipped whole and by reference, so a snapshot that copied
#: the fighter dict verbatim would hand it back through the side door. That is the exact
#: shape of CoC's `turn_undo` leak: top-level redaction correct for months while a nested
#: snapshot shipped the same hidden keys to every client.
_BEAT_HIDDEN = frozenset({"scheme_pool"})


def _fighter_snapshot(game: dict) -> list[list[dict]]:
    """Every fighter's PUBLIC state, frozen as it stands right now.

    A round is resolved server-side in one go, so without this the client has the state
    after the LAST turn of the round and nothing else -- health, Power and tokens all jump
    to their end-of-round values the instant the round lands, while the cards and the log
    step through turn by turn. Freezing the state onto each beat is what lets the fighter
    boards step with them.

    Deliberately NOT reconstructed on the client by rewinding the events. The client would
    have to model every event kind the engine can emit -- hp, power, track, token,
    transform, spirit, absorb, revive -- and stay in step with it forever; the engine
    already knows the answer.
    """
    return [[{k: (dict(v) if isinstance(v, dict) else v)
              for k, v in f.items() if k not in _BEAT_HIDDEN}
             for f in side]
            for side in game["fighters"]]


def _resolve_turn(game: dict, revealed: list, doubles=None) -> dict:
    turn = Turn(game, revealed)
    turn.beat.update({"turn": game["turn"], "insts": list(revealed),
                      "cids": [card_of(game, i)["id"] if i is not None else None
                               for i in revealed],
                      "active": list(turn.active)})

    _declare(turn)
    _settle(turn)

    # The Golem's Reanimation: this card resolves a SECOND time, and the second
    # pass is a fresh turn for him alone -- it reads the state the first pass
    # left behind, so two Attacks can clear a Stop twice.
    for seat in (0, 1):
        if not (doubles or [False, False])[seat] or revealed[seat] is None:
            continue
        again = Turn(game, revealed)
        again.beat = turn.beat
        again.cancelled = list(turn.cancelled)
        # POWER IS STILL READ FROM THE START OF THE TURN. The second pass reads the state
        # the first one left behind -- HP, stops, tokens -- but not Power, which every
        # Attack takes from the turn's opening snapshot. A fresh Turn object makes its own
        # snapshot, so the Golem's +1 icon fired by his own first Attack fed straight back
        # into his second: BGA 888405016 f2t3 has him hit for 3 and 3, we hit for 3 and 4.
        again.power_snapshot = dict(turn.power_snapshot)
        if not again.cancelled[seat]:
            f = fighter(game, seat, again.active[seat])
            again.note(kind="again", seat=seat, slot=again.active[seat])
            # THE OPPOSING BLOCK IS STILL STANDING, so it catches the second pass too --
            # "against an opposing Block both Attacks die but their bonus fires once",
            # which this code said and did not do: `again` started with an empty block
            # list, so the second Attack sailed past a Block that had just stopped the
            # first (886317681 f4t2, where BGA logs it blocked and we dealt 4).
            again.blocks = turn.blocks
            _run_ops(again, seat, _ops_of(game, revealed[seat], f), "declare")
            _apply_blocks(again)
            for atk in again.attacks:
                again.note(kind="attack", seat=atk["seat"], slot=atk["source"][1],
                           power=atk["power"], negated=bool(atk["negated"]),
                           targets=[[t[0], t[1]] for t in atk["targets"]])
                _land_attack(again, atk)
            _settle(again)
            while again.deferred:
                d_seat, d_who, op = again.deferred.pop(0)
                _run_op(again, d_seat, d_who, op, "late")
                _settle(again)
            turn.instant_loss |= again.instant_loss
            turn.drag |= again.drag
            turn.fey_folk_losses |= again.fey_folk_losses
            turn.revive |= again.revive

    # Step 7: the printed THEN, and the cards that read "after your Opponent's
    # card is resolved". They run in declaration order against the settled state.
    while turn.deferred:
        seat, who, op = turn.deferred.pop(0)
        _run_op(turn, seat, who, op, "late")
        _settle(turn)

    _become_spirits(turn)
    _check_end_of_turn(turn)
    _pend_fey_folk_setup(game)
    turn.beat["state"] = _fighter_snapshot(game)
    return turn.beat


def _do_revives(turn: Turn) -> None:
    """Maman Brijit's marker returns to 4 as soon as the movement that revived her settles.

    NOT at the end of the turn, which is what this used to say and do. BGA 902742623 f5t2
    puts it inline: she is pushed past both KO spaces, gains her Power and "resets their
    Health Points to 4", and only THEN does the next Intrigue deal its 1 damage -- taking
    her to 3. Reviving at the end of the turn let that damage land on the revive space,
    where the floor swallows it, and she finished the turn a point up.
    """
    for who in list(turn.revive):
        turn.revive.discard(who)
        f = turn.f(who)
        target = _board(f).get("revive_to_hp")
        if target is None:
            continue
        for i, space in enumerate(track_of(f)):
            if space["kind"] == "hp" and space["hp"] == target:
                before, f["hp"] = f["hp"], i
                turn.note(kind="hp", seat=who[0], slot=who[1],
                          **{"from": before, "to": i})
                break


def _become_spirits(turn: Turn) -> None:
    """A Fey Folk Character on its Spirit space steps off, at end of turn.

    In the printed order: the Spirits track goes up, and only then is the next
    Character chosen -- which is why HP loss never carries across.
    """
    game = turn.game
    for seat in (0, 1):
        for slot in (0, 1):
            f = fighter(game, seat, slot)
            if not _board(f).get("characters") or f.get("character") is None:
                continue
            track = track_of(f)
            if not track or f["hp"] is None:
                continue
            if track[f["hp"]]["kind"] != "spirit":
                continue
            f["chars"][f["character"]] = "spirit"
            turn.note(kind="spirit", seat=seat, slot=slot, character=f["character"])
            f["character"] = None
            f["hp"] = None


def _check_end_of_turn(turn: Turn) -> None:
    """Step 8. A marker on KO now loses the fight for that team."""
    game = turn.game
    if game["winner"] is not None:
        return

    if turn.instant_win is not None:
        _finish(game, turn.instant_win, "instant win")
        return

    losers = set(turn.instant_loss)
    for seat in (0, 1):
        for slot in (0, 1):
            f = fighter(game, seat, slot)
            if is_ko(f) and not f.get("ko"):
                f["ko"] = True
                turn.note(kind="ko", seat=seat, slot=slot)
            if f.get("ko"):
                losers.add(seat)
    losers |= turn.fey_folk_losses

    for seat in sorted(turn.drag):
        if seat in losers:
            _finish(game, seat, "dragged them to hell")
            return

    if not losers:
        return
    if len(losers) == 2:
        # Both teams down in the same turn is a draw -- unless exactly one of
        # them burned, which is a loss for that side rather than a draw.
        if len(turn.instant_loss) == 1:
            _finish(game, other_seat(next(iter(turn.instant_loss))), "incineration")
        else:
            _finish(game, "draw", "double KO")
        return
    _finish(game, other_seat(next(iter(losers))), "KO")


def _finish(game: dict, winner, why: str) -> None:
    game["winner"] = winner
    game["phase"] = "over"
    game["pending_pid"] = game["pending_kind"] = game["pending"] = None
    _log(game, "game over (" + why + ")")


# ==========================================================================
# The FIGHT! step
# ==========================================================================

def _fight_turn(game: dict) -> bool:
    """Play one turn. Returns False when both Fight Decks are empty."""
    if not game["fight_deck"][0] and not game["fight_deck"][1]:
        return False

    revealed = []
    for seat in (0, 1):
        deck = game["fight_deck"][seat]
        inst = deck.pop(0) if deck else None
        revealed.append(inst)
        if inst is not None:
            game["played"][seat].append(inst)

    game["turn"] += 1
    doubles = list(game["double_next"])
    game["double_next"] = [False, False]
    game["beats"].append(_resolve_turn(game, revealed, doubles))
    return True


def _begin_build(game: dict) -> None:
    """Played cards keep their order and become the next Fight Deck."""
    for seat in (0, 1):
        game["fight_deck"][seat] = list(game["played"][seat])
        game["played"][seat] = []

    # Cannot draw 3? The fight is judged a draw. That is also what caps a game at
    # about sixteen rounds and makes every soak terminate.
    if any(len(game["build_deck"][seat]) < BUILD_DRAW for seat in (0, 1)):
        _finish(game, "draw", "depleted Build Deck")
        return

    game["phase"] = "build"
    for seat in (0, 1):
        game["build_offer"][seat] = game["build_deck"][seat][:BUILD_DRAW]
        game["build_deck"][seat] = game["build_deck"][seat][BUILD_DRAW:]
        game["build_choice"][seat] = None


def _finish_build(game: dict) -> None:
    """Both are in: insert, discard, then fire the Instant Bonuses."""
    instant = []
    for seat in (0, 1):
        choice = game["build_choice"][seat]
        inst, pos = choice["inst"], choice["pos"]
        game["fight_deck"][seat].insert(pos, inst)
        for other in choice["discard"]:
            game["build_deck"][seat].append(other)
        if card_of(game, inst).get("instant_bonus"):
            instant.append((seat, inst))
        game["build_offer"][seat] = None
        game["build_choice"][seat] = None

    if instant:
        turn = Turn(game, [None, None])
        turn.beat.update({"turn": -1, "insts": [None, None], "cids": [None, None],
                          "active": [0, 0], "instant": True})
        for seat, inst in instant:
            turn.active[seat] = game["instances"][inst]["slot"]
            who = (seat, turn.active[seat])
            turn.note(kind="instant_bonus", seat=seat, cid=card_of(game, inst)["id"])
            for op in card_of(game, inst)["instant_bonus"]:
                _run_op(turn, seat, who, op, "late")
        _settle(turn)
        _check_end_of_turn(turn)
        turn.beat["state"] = _fighter_snapshot(game)
        game["beats"].append(turn.beat)

    if game["winner"] is None:
        game["round"] += 1
        game["turn"] = 0
        game["phase"] = "fight"
        game["beats"] = []


def advance(game: dict) -> None:
    """Push the game as far as it can go without further input.

    Called after every move. It stops at a phase that needs a submission, at a
    pending sub-decision, or at the end of the game.
    """
    guard = 0
    while game["winner"] is None and game["pending_pid"] is None:
        guard += 1
        if guard > 2000:
            raise IllegalMove("engine failed to settle")

        if game["phase"] == "fight":
            if not _fight_turn(game):
                _begin_build(game)
            continue
        if game["phase"] == "build" and all(c is not None for c in game["build_choice"]):
            _finish_build(game)
            continue
        return


# ==========================================================================
# Moves
# ==========================================================================

def choose_character(game: dict, pid: str, character: str) -> None:
    """The Fey Folk pick their next Character -- at setup and after each Spirit."""
    if game["pending_kind"] != "choose_character" or game["pending_pid"] != pid:
        raise IllegalMove("nothing to choose")
    pend = game["pending"]
    if character not in pend["options"]:
        raise IllegalMove("that Character is not available")

    seat, slot = pend["seat"], pend["slot"]
    f = fighter(game, seat, slot)
    f["chars"][character] = "active"
    f["character"] = character
    track = track_of(f)
    f["hp"] = _start_index(track)
    game["pending_pid"] = game["pending_kind"] = game["pending"] = None

    # The top space's icons apply as the Character steps onto the track.
    turn = Turn(game, [None, None])
    turn.active[seat] = slot
    for icon in track[f["hp"]].get("icons", []):
        if not isinstance(icon, str):
            _run_op(turn, seat, (seat, slot), icon, "late")
    _settle(turn)
    if turn.beat["events"]:
        turn.beat.setdefault("turn", game["turn"])
        game["beats"].append(turn.beat)

    _pend_fey_folk_setup(game)
    advance(game)


def order_pick(game: dict, pid: str, first_slot: int) -> None:
    """Choose which of your two Starting Cards sits on top of the Fight Deck."""
    if game["phase"] != "order":
        raise IllegalMove("not ordering")
    seat = seat_of(game, pid)
    if game["order_choice"][seat] is not None:
        raise IllegalMove("you have already chosen")
    if first_slot not in (0, 1):
        raise IllegalMove("pick one of your two fighters")

    deck = game["fight_deck"][seat]
    if len(deck) != FIGHT_DECK_START:
        raise IllegalMove("the Fight Deck is not the two Starting Cards")
    deck.sort(key=lambda inst: 0 if game["instances"][inst]["slot"] == first_slot else 1)
    game["order_choice"][seat] = first_slot

    if all(c is not None for c in game["order_choice"]):
        game["phase"] = "fight"
        advance(game)


def build_submit(game: dict, pid: str, inst: int, pos: int,
                 bottom_last=None) -> None:
    """Keep one of the three drawn cards and slide it into the Fight Deck.

    `pos` indexes the CURRENT Fight Deck: 0 is the top, len() the bottom.
    `bottom_last` names which of the two discards ends up lowest. That is the
    player's call -- the Build Deck is never shuffled again, so it matters.
    """
    if game["phase"] != "build":
        raise IllegalMove("not building")
    seat = seat_of(game, pid)
    if game["build_choice"][seat] is not None:
        raise IllegalMove("you have already built this round")
    offer = game["build_offer"][seat]
    if not offer or inst not in offer:
        raise IllegalMove("that card was not drawn")
    if not 0 <= pos <= len(game["fight_deck"][seat]):
        raise IllegalMove("that is not a position in your Fight Deck")

    rest = [i for i in offer if i != inst]
    if bottom_last is not None:
        if bottom_last not in rest:
            raise IllegalMove("that card is not one of the two discards")
        rest = [i for i in rest if i != bottom_last] + [bottom_last]

    game["build_choice"][seat] = {"inst": inst, "pos": pos, "discard": rest}
    advance(game)


def legal_build_positions(game: dict, seat: int) -> list:
    return list(range(len(game["fight_deck"][seat]) + 1))


# ==========================================================================
# Views
# ==========================================================================

#: Keys that must never reach a client as-is. `public_view` is the only place
#: allowed to build a payload; the server redacts through it, never by hand.
HIDDEN = ("build_deck", "draft_hands", "rng_state", "build_choice", "pending")


def public_view(game: dict, seat) -> dict:
    """What one seat may see.

    Your own Fight Deck ORDER is yours to know -- it is the whole game. Everyone
    else's is a count. Both Build Decks are hidden from both players, because
    their order decides future draws, and so is an unsubmitted build choice.
    """
    view = {
        "version": game["version"],
        "phase": game["phase"],
        "round": game["round"],
        "turn": game["turn"],
        "seats": list(game["seats"]),
        "teams": [list(t) for t in game["teams"]],
        "fighters": [[dict(f) for f in side] for side in game["fighters"]],
        "beats": game["beats"],
        "winner": game["winner"],
        "pending_kind": game["pending_kind"],
        "log": game["log"][-200:],
        "fight_deck_counts": [len(d) for d in game["fight_deck"]],
        "build_deck_counts": [len(d) for d in game["build_deck"]],
        "played_counts": [len(p) for p in game["played"]],
        "played": [list(p) for p in game["played"]],
        "draft_round": game["draft_round"],
        "instances": [dict(i) for i in game["instances"]],
        "build_submitted": [c is not None for c in game["build_choice"]],
        "order_submitted": [c is not None for c in game["order_choice"]],
    }
    for side in view["fighters"]:
        for f in side:
            f.pop("scheme_pool", None)

    if seat is None:
        view["draft_hand"] = []
        view["fight_deck"] = None
        view["build_offer"] = []
        view["pending_is_yours"] = False
        view["pending"] = None
        return view

    view["draft_hand"] = list(game["draft_hands"][seat])
    view["fight_deck"] = list(game["fight_deck"][seat])
    view["build_offer"] = list(game["build_offer"][seat] or [])
    view["pending_is_yours"] = game["pending_pid"] == game["seats"][seat]
    view["pending"] = game["pending"] if view["pending_is_yours"] else None
    # Whether each side still owes a submission. The client must not have to
    # re-derive this: a simultaneous game has no "your turn" to read off the
    # phase, and a client that guesses wrong shows the wrong prompt.
    view["you_owe"] = owes_move(game, seat)
    view["they_owe"] = owes_move(game, 1 - seat)
    return view


# ==========================================================================
# The server-facing API
# ==========================================================================
#
# Rag Tag is SIMULTANEOUS, so there is no single seat on turn. `may_act` is the
# question the server actually needs -- does this player owe a submission? -- and
# `turn_pid` exists only for the bot scheduler, which wants one pid or none.


def is_over(game) -> bool:
    return bool(game) and game.get("winner") is not None


def owes_move(game: dict, seat: int) -> bool:
    """Is this seat holding the game up?"""
    if is_over(game):
        return False
    if game["pending_pid"] == game["seats"][seat]:
        return True
    phase = game["phase"]
    if phase == "draft":
        return len(game["draft_picks"][seat]) < game["draft_round"]
    if phase == "order":
        return game["order_choice"][seat] is None
    if phase == "build":
        return game["build_choice"][seat] is None
    return False


def may_act(game, pid: str) -> bool:
    if not game or is_over(game):
        return False
    try:
        seat = seat_of(game, pid)
    except IllegalMove:
        return False
    return owes_move(game, seat)


def turn_pid(game):
    """One pid the bot scheduler can act on, or None.

    Both seats can owe a move at once; the scheduler only ever asks about the
    bot's own pid, so returning the first owing seat is enough and is stable.
    """
    if not game or is_over(game):
        return None
    for seat in (0, 1):
        if owes_move(game, seat):
            return game["seats"][seat]
    return None


def legal_moves(game: dict, seat: int) -> list[dict]:
    """Every move this seat could legally submit right now."""
    if not owes_move(game, seat):
        return []
    if game["pending_pid"] == game["seats"][seat]:
        if game["pending_kind"] == "choose_character":
            return [{"kind": "character", "character": c}
                    for c in game["pending"]["options"]]
        return []
    phase = game["phase"]
    if phase == "draft":
        return [{"kind": "draft", "fighter": fid}
                for fid in game["draft_hands"][seat]]
    if phase == "order":
        return [{"kind": "order", "slot": s} for s in (0, 1)]
    if phase == "build":
        return [{"kind": "build", "inst": inst, "pos": pos}
                for inst in (game["build_offer"][seat] or [])
                for pos in legal_build_positions(game, seat)]
    return []


def apply_move(game: dict, pid: str, move: dict) -> None:
    """The single entry point the server validates every move through.

    A client-side bot is safe precisely because it cannot skip this.
    """
    if is_over(game):
        raise IllegalMove("the fight is over")
    kind = (move or {}).get("kind")
    if kind == "draft":
        draft_pick(game, pid, move.get("fighter"))
    elif kind == "order":
        order_pick(game, pid, move.get("slot"))
    elif kind == "build":
        build_submit(game, pid, move.get("inst"), move.get("pos"),
                     move.get("bottom_last"))
    elif kind == "character":
        choose_character(game, pid, move.get("character"))
    else:
        raise IllegalMove("unknown move")
    advance(game)


def player_view(game, pid):
    """`public_view` addressed by pid -- what a socket for `pid` may receive."""
    if not game:
        return None
    seat = None
    if pid in game.get("seats", []):
        seat = game["seats"].index(pid)
    return public_view(game, seat)


def result_summary(game) -> dict:
    """A finished game in the shape the lobby's History row wants."""
    if not is_over(game):
        return {}
    return {
        "winner": game["winner"],
        "rounds": game["round"],
        "teams": [list(t) for t in game.get("teams", [[], []])],
        "reason": (game["log"][-1] if game.get("log") else ""),
    }
