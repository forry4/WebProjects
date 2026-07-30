"""Dontminion engine — pure rules for Dominion (Base 2E + Intrigue 2E).

No I/O, no FastAPI. The game dict is JSON-safe (no sets, RNG persisted as lists)
so it survives save/reconnect. Public API (the frozen contract — see
.claude-plans/i-want-to-add-luminous-pebble.md §9 and games/dontminion/CLAUDE.md):

    new_game(player_ids, expansions, seed=None, names=None, kingdom=None) -> game
    apply_move(game, pid, move) -> (ok, err)
    legal_moves(game, pid) -> list[move]
    sample_decision(game, pid, rng) -> decision payload
    is_over(game) / winners(game) / score_game(game)
    player_view(game, pid) -> per-recipient redacted dict
    cost(game, card) -> int

Moves are dicts keyed on "type": play_action / play_treasure / play_all_treasures /
buy / end_phase / decision. Pauses for input are FRAMES on the game["pending"] stack;
pending_pid / pending_kind mirror the top frame. Auto frames (parked continuations)
are executed by _drive() so at rest the top frame is always a decision frame or the
stack is empty. Card effects live in effects_*.py and register EFFECTS/STAGES; they
may only touch the game through the kernel helpers exported here.
"""

import copy
import itertools
import random

from .cards import CARDS, KINGDOM, pile_size

BASIC_CARDS = ("Copper", "Silver", "Gold", "Estate", "Duchy", "Province", "Curse")
_DRIVE_CAP = 500
_ENUM_CAP = 200

# Game-dict shape version. BUMP THIS whenever a phase adds a key the kernel
# reads, and add the matching step to migrate(). The server migrates at LOAD,
# so kernel code may assume the CURRENT shape — no defensive .get() for keys
# migrate guarantees (lazily-built transients like dur_setup stay lazy).
SCHEMA = 4
#   1 = Base + Intrigue
#   2 = Seaside      (durations/mats/watchers/extra turns)
#   3 = Prosperity   (VP tokens, Platinum/Colony, Charlatan's Curse rule)
#   4 = card RENAMES (Harem -> Farm) — the first genuine TRANSFORM step

# Cards renamed by the publisher, old -> current. We ship current names (user
# directive), so a persisted save written under an old name must be rewritten
# at load: the string lives inside real decks, hands, supplies, trash, pending
# frames and undo snapshots, so nothing short of a deep rewrite is correct.
# EVERY future rename adds a line here AND bumps SCHEMA.
_RENAMES = {
    "Harem": "Farm",      # compendium: "In 2023 this card was renamed 'Farm'"
}


# Every key new_game creates that the kernel later reads by direct index, with
# the value an OLD save should inherit. migrate fills these by PRESENCE, not by
# schema version — see the comment in migrate() for why the version gate can't
# be trusted for fills. Factories keep the defaults unshared.
_GAME_FILLS = {
    "turn_number": lambda g: 1,
    "log_depth": lambda g: 0,
    "undo_stack": lambda g: [],
    # Seaside
    "watchers": lambda g: [],
    "last_turn_pid": lambda g: None,
    "last_turn_gains": lambda g: {},
    "extra_turn": lambda g: False,
    # Prosperity
    "vp_tokens": lambda g: {p: 0 for p in g.get("players", [])},
    "colony": lambda g: False,
    "curse_is_treasure": lambda g: False,
}
_SEAT_FILLS = {
    "aside": list,
    # Seaside zones + mats
    "duration": list, "dur_aside": list,
    "island": list, "village_mat": list,
}


def migrate(game):
    """Bring a persisted game up to SCHEMA, in place. Called by the server on
    every load; live prod games predate every later phase, so each phase's new
    keys need an entry in _GAME_FILLS/_SEAT_FILLS (and a test in test_migrate.py).

    Fills are UNCONDITIONAL, deliberately — do not put them behind `v < N`.
    A stamp only partitions shapes if it was bumped in the same commit that
    added the key, and ours wasn't: prod carries `schema = 2` games written
    across the whole Seaside AND Prosperity eras, some predating keys added
    later under that same stamp (found by replaying real prod saves: two live
    games had schema 2 and no `last_turn_gains`, which a version-gated migrate
    skips and the kernel then KeyErrors on at end of turn). setdefault is
    idempotent, so an unconditional fill is never wrong and costs one lookup.
    The version gate is reserved for genuine TRANSFORMS — a value whose meaning
    or shape changed, where re-running the step could corrupt a current game.
    The rename step below is the first, and it is gated soundly because SCHEMA
    was bumped in the same commit that added it (the condition the fills above
    could not rely on). It happens to be idempotent too, so a missed gate would
    cost time, not correctness.
    """
    if not isinstance(game, dict) or "seats" not in game:
        return game
    v = game.get("schema", 1)
    for key, factory in _GAME_FILLS.items():
        if key not in game:
            game[key] = factory(game)
    for seat in game["seats"].values():
        for key, factory in _SEAT_FILLS.items():
            if key not in seat:
                seat[key] = factory()
    ctx = game.setdefault("turn_ctx", _fresh_turn_ctx())
    for key, val in _fresh_turn_ctx().items():
        ctx.setdefault(key, val)
    if v < 4:                                   # pre-rename saves
        _apply_renames(game, _RENAMES)
    game["schema"] = SCHEMA
    return game


def _apply_renames(game, mapping):
    """Rewrite renamed card names EVERYWHERE in a persisted game.

    A card name is not confined to a tidy list of zones — it is a bare string
    in decks, hands, discards, in-play, aside, mats, duration entries and their
    riders, trash, the supply's KEYS, the kingdom list, last_turn_gains, every
    open pending frame's constraint and data, every undo snapshot (which are
    whole game dicts), and the log. Missing any one of them would leave a live
    game holding a card the kernel no longer knows, so this walks the whole
    structure instead of enumerating zones.

    The one thing it must not touch is player identity — a DISPLAY NAME equal
    to a renamed card is entirely possible (someone can call themselves "Farm").
    Identity is protected POSITIONALLY, by which key holds it, not by comparing
    against the pid set: a value-blind guard would also refuse to rename the
    real card whenever a player shared its name, quietly leaving the game
    holding a card the kernel no longer knows."""
    # keys whose VALUE is a pid, or a list of pids — never a card
    pid_valued = {"turn", "pid", "pending_pid", "last_turn_pid", "host", "owner",
                  "actor", "gainer", "players", "winners", "private_to",
                  "immune", "_outpost", "_cur_dur"}
    # keys whose dict KEYS are pids (values still recursed — last_turn_gains
    # maps pid -> cards). "names" is skipped WHOLESALE: user-chosen text.
    pid_keyed = {"seats", "vp", "vp_tokens", "scores", "last_turn_gains", "meta"}

    def walk(node, rename_keys=True):
        if isinstance(node, str):
            return mapping.get(node, node)
        if isinstance(node, list):
            return [walk(x) for x in node]
        if isinstance(node, dict):
            out = {}
            for k, val in node.items():
                nk = mapping.get(k, k) if rename_keys else k
                if k == "names" or k in pid_valued:
                    out[nk] = val                      # identity: untouched
                else:
                    out[nk] = walk(val, rename_keys=k not in pid_keyed)
            return out
        return node

    game.update(walk(game))
    return game


# --- RNG (persisted as lists so the game dict stays JSON-safe) ---------------

def _make_rng(game):
    rng = random.Random()
    st = game.get("rng_state")
    if st is not None:
        rng.setstate((st[0], tuple(st[1]), st[2]))
    return rng


def _save_rng(game, rng):
    st = rng.getstate()
    game["rng_state"] = [st[0], list(st[1]), st[2]]


# --- logging -----------------------------------------------------------------

def _log(game, pid, event, private_to=None, **kw):
    entry = dict(kw)
    d = game.get("log_depth", 0)
    if d:
        entry["d"] = min(d, 3)
    if private_to is not None:
        entry["private_to"] = list(private_to)
    # Core fields are set LAST so an event kwarg can never clobber them. A
    # draw kwarg named n= used to overwrite the SEQUENCE n with the card count
    # — every draw entry shared n, the client keyed lines on it, and React's
    # reconciler visibly scrambled the log. Counts are the `count` kwarg now.
    entry["n"] = len(game["log"])
    entry["pid"] = pid
    entry["event"] = event
    game["log"].append(entry)


# log_depth tracks how deep inside a card's resolution we are, so the client can
# indent sub-effects under the play that caused them (the Dominion-online look).
# Incremented around every effect/stage dispatch; always 0 at rest (try/finally),
# so snapshots/saves never carry a stale depth.

def _push_depth(game):
    game["log_depth"] = game.get("log_depth", 0) + 1


def _pop_depth(game):
    game["log_depth"] = max(0, game.get("log_depth", 1) - 1)


# --- frame machinery ---------------------------------------------------------

def _sync_pending(game):
    top = game["pending"][-1] if game["pending"] else None
    game["pending_pid"] = top["pid"] if top else None
    game["pending_kind"] = top["kind"] if top else None


def _push_frame(game, frame):
    game["pending"].append(frame)
    _sync_pending(game)


def _pop_frame(game):
    frame = game["pending"].pop()
    _sync_pending(game)
    return frame


def push_choose_cards(game, pid, card, stage, cards, mn, mx, purpose, data=None):
    cards = list(cards)
    mn = max(0, min(mn, len(cards)))
    mx = max(mn, min(mx, len(cards)))
    _push_frame(game, {"kind": "choose_cards", "pid": pid, "card": card, "stage": stage,
                       "constraint": {"cards": cards, "min": mn, "max": mx, "purpose": purpose},
                       "data": data or {}})


def push_choose_pile(game, pid, card, stage, piles, data=None):
    piles = list(piles)
    if not piles:
        raise ValueError("push_choose_pile with no piles — pusher must guard")
    _push_frame(game, {"kind": "choose_pile", "pid": pid, "card": card, "stage": stage,
                       "constraint": {"piles": piles}, "data": data or {}})


def push_choose_option(game, pid, card, stage, options, pick=1, distinct=True, data=None):
    _push_frame(game, {"kind": "choose_option", "pid": pid, "card": card, "stage": stage,
                       "constraint": {"options": list(options), "pick": pick, "distinct": distinct},
                       "data": data or {}})


def push_order_cards(game, pid, card, stage, cards, data=None):
    _push_frame(game, {"kind": "order_cards", "pid": pid, "card": card, "stage": stage,
                       "constraint": {"cards": list(cards)}, "data": data or {}})


def push_place_in_deck(game, pid, card, stage, deck_card, data=None):
    deck_len = len(game["seats"][pid]["deck"])
    _push_frame(game, {"kind": "place_in_deck", "pid": pid, "card": card, "stage": stage,
                       "constraint": {"card": deck_card, "deck_len": deck_len}, "data": data or {}})


def push_name_card(game, pid, card, stage, data=None):
    _push_frame(game, {"kind": "name_card", "pid": pid, "card": card, "stage": stage,
                       "constraint": {"cards": sorted(game["supply"])}, "data": data or {}})


def push_auto(game, pid, card, stage, data=None):
    _push_frame(game, {"kind": "auto", "pid": pid, "card": card, "stage": stage,
                       "constraint": None, "data": data or {}})


def _stage_fn(card, stage):
    fn = KERNEL_STAGES.get((card, stage))
    if fn is None:
        from . import effects
        fn = effects.STAGES.get((card, stage))
    if fn is None:
        raise KeyError(f"dontminion: no stage handler for {card!r}/{stage!r}")
    return fn


def _effect_fn(card):
    from . import effects
    fn = effects.EFFECTS.get(card)
    if fn is None:
        raise KeyError(f"dontminion: no effect registered for {card!r}")
    return fn


def _drive(game):
    """Run auto frames until the top of the stack is a decision frame (or empty)."""
    for _ in range(_DRIVE_CAP):
        if not game["pending"] or game["pending"][-1]["kind"] != "auto":
            return
        frame = _pop_frame(game)
        _push_depth(game)
        try:
            _stage_fn(frame["card"], frame["stage"])(game, frame["pid"], frame, None)
        finally:
            _pop_depth(game)
    raise RuntimeError("dontminion: _drive exceeded iteration cap (runaway auto frames)")


# --- undo (one MOVE at a time; gated on HIDDEN INFORMATION, the Duel model) ---
# A snapshot is pushed before each of the turn player's own moves, so undo can
# be pressed repeatedly — walking back move by move until the start of the turn
# ("nothing to undo") or until something revealed information that can't be
# un-seen.
#
# The gate is the STACK ITSELF, not a sticky flag: a reveal CLEARS the stack
# (you can never rewind across new information), but moves made AFTER it are
# snapshotted again and stay undoable. A sticky "this turn revealed something"
# flag used to block every later snapshot, so one +1 Card (Upgrade, Laboratory,
# a start-of-turn Duration draw...) killed undo for the WHOLE turn — including
# ordinary, fully-reversible buys.

_UNDO_CAP = 30  # snapshots per turn — a runaway backstop, far above real turns


def _mark_revealed(game):
    """This turn exposed information that can't be un-seen (a draw, a look, a
    reveal, a pass, an opponent's choice): nothing before this point may be
    rewound. Later moves are undoable again — the empty stack is the gate.
    `turn_revealed` stays as a display/telemetry signal only."""
    game["turn_revealed"] = True
    game["undo_stack"] = []


def _arm_undo(game):
    game["turn_revealed"] = False
    game["undo_stack"] = []


def _push_undo(game):
    """Snapshot the game before a (turn player's) move. Snapshots exclude the
    stack itself (else they'd nest) and THE LOG — which is append-only, so a
    snapshot only needs its LENGTH and undo restores by truncating. Copying it
    put up to _UNDO_CAP copies of a growing log inside every save blob (and
    into the deepcopy on every single move). JSON-safe so they survive
    save/reconnect; stripped from player_view (they hold every hidden zone)."""
    snap = copy.deepcopy({k: v for k, v in game.items()
                          if k not in ("undo_stack", "log")})
    snap["_log_len"] = len(game["log"])
    game["undo_stack"].append(snap)
    if len(game["undo_stack"]) > _UNDO_CAP:
        game["undo_stack"].pop(0)


def _undo_move(game, pid):
    if pid != game["turn"]:
        return False, "not your turn"
    stack = game.get("undo_stack") or []
    if not stack:
        return False, "nothing to undo"
    snap = stack.pop()
    # the log is not in the snapshot: truncate it back to its recorded length
    # (append-only ⇒ everything after the snapshot belongs to the undone move)
    log = game["log"][:snap.pop("_log_len", len(game["log"]))]
    game.clear()
    game.update(snap)
    game["log"] = log
    game["undo_stack"] = stack   # the remaining, earlier snapshots
    _log(game, pid, "undo")
    return True, None


# --- kernel zone helpers (importable by card modules) ------------------------

def draw(game, pid, n):
    """Draw up to n cards (shuffle-on-empty per the rules). Returns the drawn list."""
    seat = game["seats"][pid]
    drawn = []
    for _ in range(n):
        if not seat["deck"]:
            if not seat["discard"]:
                break
            rng = _make_rng(game)
            pile = seat["discard"][:]
            rng.shuffle(pile)
            seat["deck"] = pile
            seat["discard"] = []
            _save_rng(game, rng)
            _log(game, pid, "shuffle")
        drawn.append(seat["deck"].pop(0))
    seat["hand"].extend(drawn)
    if drawn:
        _mark_revealed(game)
        # card names are per-field redacted in player_view (owner-only pre-over)
        _log(game, pid, "draw", count=len(drawn), cards=list(drawn))
    return drawn


def look_top(game, pid, n):
    """Move up to n cards from the top of the deck to the seat's aside zone.

    Aside cards are excluded from any mid-look shuffle (they are not in the
    deck or discard), matching the reveal/look rules. Returns the moved list.
    """
    seat = game["seats"][pid]
    moved = []
    for _ in range(n):
        if not seat["deck"]:
            if not seat["discard"]:
                break
            rng = _make_rng(game)
            pile = seat["discard"][:]
            rng.shuffle(pile)
            seat["deck"] = pile
            seat["discard"] = []
            _save_rng(game, rng)
            _log(game, pid, "shuffle")
        moved.append(seat["deck"].pop(0))
    seat["aside"].extend(moved)
    if moved:
        _mark_revealed(game)
    return moved


def gain(game, pid, card, dest="discard", via_buy=False):
    """Gain from the supply. Returns False (nothing happens) if the pile is
    empty. WOULD-GAIN interception (the replacement protocol, Trader-class):
    if any TRIGGERS entry with on="would_gain"/from="hand" matches for the
    GAINER, the physical gain is parked as a __gain/resolve auto frame with
    the reaction windows on top; a replacement stage calls
    cancel_pending_gain() and performs its own effect instead. Callers see
    True ("a gain is underway") — no current call site branches on the
    difference, and new card code must not either."""
    if game["supply"].get(card, 0) <= 0:
        return False
    from . import effects
    would = [(rc, s) for rc, specs in getattr(effects, "TRIGGERS", {}).items()
             for s in specs if s["on"] == "would_gain" and s.get("from") == "hand"]
    for rcard, spec in would:
        when = spec.get("when")
        if rcard in game["seats"][pid]["hand"] and (when is None or when(game, pid,
                {"actor": pid, "subject": card, "dest": dest, "via_buy": via_buy})):
            verb = "Reveal" if spec.get("mode") == "reveal" else "Play"
            push_auto(game, pid, "__gain", "resolve",
                      data={"pid": pid, "card": card, "dest": dest,
                            "via_buy": via_buy, "cancelled": False})
            push_choose_option(game, pid, rcard, spec["stage"],
                               options=[{"id": "react", "label": f"{verb} {rcard} ({card} gain)"},
                                        {"id": "decline", "label": "Don't react"}],
                               data={"card": card, "gainer": pid, "dest": dest})
            return True
    return _gain_now(game, pid, card, dest, via_buy)


def _gain_now(game, pid, card, dest, via_buy=False):
    """The physical gain — pile decrement, placement, bookkeeping, emit."""
    if game["supply"].get(card, 0) <= 0:
        return False
    game["supply"][card] -= 1
    seat = game["seats"][pid]
    if dest == "discard":
        seat["discard"].append(card)
    elif dest == "hand":
        seat["hand"].append(card)
    elif dest == "deck":
        seat["deck"].insert(0, card)
    elif dest == "dur_aside":
        seat.setdefault("dur_aside", []).append(card)   # Blockade gains straight to set-aside
    else:
        raise ValueError(f"bad gain dest {dest!r}")
    if pid == game["turn"]:
        # Smugglers: what a player gained during THEIR OWN turn
        game.setdefault("_turn_gains", []).append(card)
        if game["phase"] == "buy" and has_type(game, card, "victory"):
            game["turn_ctx"]["gained_victory_in_buy"] = True   # Treasury's gate
    _log(game, pid, "gain", card=card, dest=dest)
    # via_buy rides the event: Hoard fires only on BOUGHT gains, Mint on any
    emit(game, "gain", actor=pid, subject=card, dest=dest, via_buy=via_buy)
    return True


def cancel_pending_gain(game):
    """A would-gain replacement stage (Trader's 'instead') cancels the parked
    physical gain. Returns the parked frame's data (card/dest) or None."""
    for f in reversed(game["pending"]):
        if f["card"] == "__gain" and f["stage"] == "resolve" and not f["data"]["cancelled"]:
            f["data"]["cancelled"] = True
            return dict(f["data"])
    return None


def _k_gain_resolve(game, pid, frame, choice):
    d = frame["data"]
    if not d["cancelled"]:
        _gain_now(game, d["pid"], d["card"], d["dest"], d.get("via_buy", False))


def gain_from_trash(game, pid, card):
    if card not in game["trash"]:
        return False
    game["trash"].remove(card)
    game["seats"][pid]["discard"].append(card)
    _log(game, pid, "gain_from_trash", card=card)
    return True


def trash(game, pid, cards, zone="hand"):
    seat = game["seats"][pid]
    for c in cards:
        seat[zone].remove(c)
        game["trash"].append(c)
    if cards:
        _log(game, pid, "trash", cards=list(cards))
        for c in cards:
            emit(game, "trash", actor=pid, subject=c)   # Dark Ages' seam


def trash_from_supply(game, card):
    if game["supply"].get(card, 0) <= 0:
        return False
    game["supply"][card] -= 1
    game["trash"].append(card)
    return True


def discard(game, pid, cards, zone="hand", public=False):
    """Discard named cards from a zone. Names are logged for every discard —
    faithful to the table, where cards land face-up on the pile one at a time
    (the pile can't be browsed later, but the event itself is public).

    Emits `discard` per card AFTER the whole batch has moved, not inline per
    card. That ordering is load-bearing under the 2022 rules change (you now
    discard all at once rather than one at a time), and the compendium's
    Tunnel ruling turns on it: discarding your hand to Minion while holding
    Tunnel + Watchtower lets you reveal the Tunnel for its Gold, but the
    Watchtower has already left your hand by the time you do.

    Clean-up does NOT come through here — `_end_turn` moves in_play and hand
    to the discard pile directly — so the when-discard reactions
    (Tunnel/Trail/Weaver, all "other than during a Clean-up phase") correctly
    cannot fire there. Scheme, which triggers ON the Clean-up discard, will
    need its own emit at that site."""
    seat = game["seats"][pid]
    for c in cards:
        seat[zone].remove(c)
        seat["discard"].append(c)
    if cards:
        _log(game, pid, "discard", cards=list(cards), count=len(cards))
        for c in cards:
            emit(game, "discard", actor=pid, subject=c, zone=zone)


def topdeck(game, pid, card, zone="hand", public=False):
    seat = game["seats"][pid]
    seat[zone].remove(card)
    seat["deck"].insert(0, card)
    if public:
        _log(game, pid, "topdeck", card=card)
    else:
        _log(game, pid, "topdeck")


def reveal(game, pid, cards, source):
    """Reveals are information events only — cards stay where they are."""
    _mark_revealed(game)
    _log(game, pid, "reveal", cards=list(cards), source=source)


def take_aside(game, pid, cards, dest="hand"):
    """Move looked-at/set-aside cards out of the aside zone (Library keeps,
    Patrol pockets victory cards, ...)."""
    seat = game["seats"][pid]
    for c in cards:
        seat["aside"].remove(c)
        if dest == "hand":
            seat["hand"].append(c)
        elif dest == "discard":
            seat["discard"].append(c)
        else:
            raise ValueError(f"bad take_aside dest {dest!r}")


def deck_from_aside(game, pid, order):
    """Return aside cards to the top of the deck in the given order
    (order[0] ends up on top) — Sentry/Patrol put-backs."""
    seat = game["seats"][pid]
    for c in order:
        seat["aside"].remove(c)
    seat["deck"] = list(order) + seat["deck"]


def deck_insert(game, pid, card, position, zone="hand"):
    """Put a card from a zone anywhere in the deck (0 = top) — Secret Passage."""
    seat = game["seats"][pid]
    seat[zone].remove(card)
    seat["deck"].insert(position, card)
    _log(game, pid, "deck_insert")


def pass_card(game, giver, receiver, card):
    """Masquerade hand-to-hand pass: identity visible only to giver+receiver."""
    _mark_revealed(game)
    game["seats"][giver]["hand"].remove(card)
    game["seats"][receiver]["hand"].append(card)
    _log(game, giver, "pass", private_to=[giver, receiver], card=card, to=receiver)
    _log(game, giver, "pass_public", to=receiver)


# The +X counters always belong to the turn player (they're turn-scoped), so the
# "plus" log lines carry game["turn"] no matter which card path granted them.

def add_actions(game, n):
    game["actions"] += n
    if n > 0:
        _log(game, game["turn"], "plus", actions=n)


def add_buys(game, n):
    game["buys"] += n
    if n > 0:
        _log(game, game["turn"], "plus", buys=n)


def add_coins(game, n):
    game["coins"] += n
    if n > 0:
        _log(game, game["turn"], "plus", coins=n)


def add_vp_tokens(game, pid, n):
    """VP tokens (Prosperity+): per-player, only ever gained, scored at game
    end, public. The pool is unlimited."""
    if n > 0:
        game["vp_tokens"][pid] = game["vp_tokens"].get(pid, 0) + n
        _log(game, pid, "vp_tokens", count=n)


def opponents(game, pid):
    """All other players, in turn order starting after pid."""
    order = game["players"]
    i = order.index(pid)
    return order[i + 1:] + order[:i]


def count_empty_piles(game):
    return sum(1 for v in game["supply"].values() if v == 0)


def types_of(game, card):
    """THE type query — card code must never read CARDS[x]["types"] directly
    for a rules decision. Game-wide type injections live here: Charlatan in
    the kingdom makes Curse also a Treasure for the whole game (2E rule)."""
    types = CARDS[card]["types"]
    if card == "Curse" and game["curse_is_treasure"]:
        return types + ["treasure"]
    return types


def has_type(game, card, t):
    return t in types_of(game, card)


def manual_treasures():
    """Treasures play_all_treasures must SKIP — the interactive ones (Anvil,
    War Chest) that push a decision frame, so they'd have to be answered
    mid-autoplay. THE reader of the registry: legal_moves, the handler, and
    the catalog all go through here so they can never disagree (they did:
    legal_moves offered play_all for a hand of nothing but manual treasures,
    which the handler then no-op'd, and the bot preferring that move spun the
    scheduler's whole iteration cap)."""
    from . import effects
    return getattr(effects, "MANUAL_TREASURES", set())


def autoplay_last():
    """Treasures play_all_treasures must play AFTER the rest, because their
    value depends on what is already in play (Bank: +$1 per Treasure in play,
    counting itself). Hand order is arbitrary from the player's side, so
    leaving Bank where it fell silently cost up to 40% of a turn's coins —
    measured $6 vs $10 on the same five-card hand.

    Membership means "later is never worse", so the button needs no judgement
    from the player. A treasure where playing EARLY might genuinely be right
    belongs in MANUAL_TREASURES instead — the button must not choose for them.
    (Highwayman-class effects, where the choice depends on game STATE rather
    than the card, need a predicate; see the ledger in EXPANSIONS.md.)"""
    from . import effects
    return getattr(effects, "AUTOPLAY_LAST", set())


def coins_of(game, card):
    """Printed coin value under game rules (Charlatan's Curse plays for $1)."""
    if card == "Curse" and game["curse_is_treasure"]:
        return 1
    return CARDS[card]["coins"]


def cost(game, card):
    """THE single cost function — Bridge reduction applies everywhere, min 0.
    effects.COST_MODS is the while-in-play modifier seam (Quarry-class,
    Prosperity+): {source_card: fn(game, priced_name) -> reduction per copy},
    summed over every copy on ANY table (cost changes are global)."""
    c = CARDS[card]["cost"] - game["turn_ctx"]["bridges"]
    # Quarry (2022): a TURN-scoped discount — survives the Quarry leaving play
    if game["turn_ctx"].get("quarries") and "action" in CARDS[card]["types"]:
        c -= 2 * game["turn_ctx"]["quarries"]
    from . import effects
    # dynamic SELF-costs (Peddler-class): the priced card's own cost rule
    dyn = getattr(effects, "DYN_COSTS", {}).get(card)
    if dyn is not None:
        c -= dyn(game)
    mods = getattr(effects, "COST_MODS", {})
    for src, fn in mods.items():
        n = 0
        for seat in game["seats"].values():
            n += seat["in_play"].count(src)
            n += sum(1 for e in seat["duration"]
                     if e["card"] == src or src in e.get("riders", []))
        if n:
            c -= fn(game, card) * n
    return max(0, c)


def cost_le(game, card, coins):
    """'costing up to $coins' — the ONLY way card code may bound a cost.
    This boundary is what makes the future cost VECTOR cheap: when Potion
    (Alchemy) and Debt (Empires) arrive, a card with a non-coin component is
    never 'up to $n' — that rule lands HERE, not in thirty batch call sites."""
    return cost(game, card) <= coins


def cost_eq(game, card, coins):
    """'costing exactly $coins' (Upgrade's +1, Swindler's same-cost)."""
    return cost(game, card) == coins


# --- the DURATION kernel (Seaside; reused by later expansions) ----------------
# A Duration card sets up abilities that fire after this turn. Model:
#  * While being played it sits in in_play like any card; its effect registers
#    future work on a per-physical-card SETUP ENTRY via add_duration_fx /
#    add_watcher (Throne Room replays add to the SAME entry, doubling the fx).
#  * At that player's clean-up, entries with registered work move (card +
#    riders) into seat["duration"] — still "in play" on the table — everything
#    else is discarded. An effect that registered nothing ("failed to set up",
#    e.g. Haven with an empty hand) is discarded normally.
#  * At the owner's next turn START, each entry's fx run as auto frames (they
#    may push decisions — Sailor's trash), its watchers expire, and the entry
#    is marked done; done entries are discarded at that turn's clean-up.
#  * WATCHERS are cross-player triggers fired by gain()/treasure plays
#    (Monkey, Corsair, Blockade). GAIN_REACTIONS (effects.py registry) are
#    reveal-windows offered from hand when someone gains (Pirate).

def _dur_setup_list(game, pid):
    return game["seats"][pid].setdefault("dur_setup", [])


def _current_dur_entry(game):
    ptr = game.get("_cur_dur")
    if not ptr:
        return None
    pid, idx = ptr
    lst = _dur_setup_list(game, pid)
    return lst[idx] if idx < len(lst) else None


def add_duration_fx(game, pid, card, stage, data=None):
    """Register a next-turn ability on the duration card currently being
    played. Card code calls this from on_play (or a later stage of the same
    play — the pointer stays live for the whole resolution)."""
    entry = _current_dur_entry(game)
    if entry is None or entry["card"] != card:
        entry = {"card": card, "fx": [], "watchers": 0, "riders": []}
        _dur_setup_list(game, pid).append(entry)
        game["_cur_dur"] = (pid, len(_dur_setup_list(game, pid)) - 1)
    entry["fx"].append({"stage": stage, "data": data or {}})


def add_watcher(game, pid, card, event, stage=None, data=None, until="owner_turn_start",
                immune=None):
    """Register a cross-player trigger. events: "gain" (any player gains),
    "play_treasure" (any treasure play), "protect" (Lighthouse — no stage, the
    attack wrap consults it). until: "owner_turn_start" (default, the Duration
    contract) or "turn_end" (this-turn triggers like Sailor's). The stage runs
    as an auto frame with data + {"actor", "subject", "owner"} when fired.
    immune: explicit per-play immunity override for watchers registered from a
    LATER stage of an attack play (Blockade) — by default the current play's
    _atk_immune transient is captured."""
    entry = _current_dur_entry(game)
    if entry is None or entry["card"] != card:
        entry = {"card": card, "fx": [], "watchers": 0, "riders": []}
        _dur_setup_list(game, pid).append(entry)
        game["_cur_dur"] = [pid, len(_dur_setup_list(game, pid)) - 1]
    if until != "turn_end":
        # only CROSS-TURN watchers keep the card on the table; a this-turn
        # watcher (Collection/Hoard/Tiara's 2022 "this turn, when..." class)
        # dies with the turn — the card discards at its own clean-up, and may
        # even be trashed from play mid-turn without stranding the entry
        entry["watchers"] += 1
    # A watcher registered during an Attack's play ability carries that play's
    # immunity set: a player who Moat-revealed (or was Lighthouse-protected)
    # when Corsair/Blockade was PLAYED is immune to its delayed effects too —
    # emit() never fires the watcher for an immune actor.
    game["watchers"].append({"event": event, "owner": pid, "card": card,
                             "stage": stage, "data": data or {}, "until": until,
                             "immune": list(immune if immune is not None
                                            else game.get("_atk_immune", []))})


def mark_duration_rider(game, pid, duration_card, rider_card):
    """A card (Throne Room) that played a persisting Duration stays on the
    table with it — attach it to the most recent setup entry for that card.
    Riding an entry that ends up registering nothing is harmless: the entry
    doesn't persist and the rider is discarded normally with it."""
    for entry in reversed(_dur_setup_list(game, pid)):
        if entry["card"] == duration_card:
            entry["riders"].append(rider_card)
            return True
    return False


def set_aside_duration(game, pid, cards, zone="hand"):
    """Move cards into the seat's duration set-aside (Haven, Blockade) —
    contents owner-only on the wire, still owned for scoring/conservation."""
    seat = game["seats"][pid]
    for c in cards:
        seat[zone].remove(c)
        seat.setdefault("dur_aside", []).append(c)


def take_dur_aside(game, pid, cards, dest="hand"):
    seat = game["seats"][pid]
    for c in cards:
        seat["dur_aside"].remove(c)
        if dest == "hand":
            seat["hand"].append(c)
        elif dest == "discard":
            seat["discard"].append(c)
        else:
            raise ValueError(f"bad take_dur_aside dest {dest!r}")


def to_island(game, pid, cards, zone="hand"):
    """Island mat: set aside until game end (still yours for scoring)."""
    seat = game["seats"][pid]
    for c in cards:
        seat[zone].remove(c)
        seat.setdefault("island", []).append(c)
    if cards:
        _log(game, pid, "island", cards=list(cards))


def to_village_mat(game, pid, cards, zone="hand"):
    seat = game["seats"][pid]
    for c in cards:
        seat[zone].remove(c)
        seat.setdefault("village_mat", []).append(c)
    if cards:
        _log(game, pid, "village_mat", count=len(cards))


def take_village_mat(game, pid):
    """Native Village: the whole mat into your hand."""
    seat = game["seats"][pid]
    taken = seat["village_mat"]
    seat["hand"].extend(taken)
    seat["village_mat"] = []
    if taken:
        _log(game, pid, "village_take", count=len(taken))
    return taken


def request_extra_turn(game, pid):
    """Outpost: flag an extra turn after this one (the _end_turn gate applies
    the official can't-take-three-turns rule and the 3-card draw)."""
    game["_outpost"] = pid


# --- THE TRIGGER BUS ----------------------------------------------------------
# One event system for every ability that fires off another change. The kernel
# emits a small vocabulary of events; two consumer layers answer:
#   1. WATCHERS — dynamic per-play instances registered by card effects
#      (add_watcher: Monkey, Corsair, Blockade, Sailor, Lighthouse-protect).
#   2. effects.TRIGGERS — the STATIC registry: {card: [spec, ...]} where
#      spec = {"on": event, "from": source, ...}:
#        "hand"    — a reaction window (play/decline) offered to each holder in
#                    turn order (Pirate; Watchtower/Sheepdog later);
#                    needs "stage", optional "when"(game, pid, ctx).
#        "in_play" — evaluated on the ACTOR's table; runs "push"(game, pid)
#                    once if they have a copy in play (Treasury;
#                    Hoard/Goons-class later); optional "when".
#        "self"    — fires when the event's SUBJECT is this card ("when you
#                    gain this" — the entire Hinterlands theme; Dark Ages
#                    on-trash); needs "stage", optional "when".
# Emitted today: "gain", "buy", "play_treasure", "trash", "buy_phase_end".
# Adding a future set's timing = new emit() call site (one line) + registry
# entries — never another bespoke kernel mechanism.

def emit(game, event, actor=None, subject=None, **extra):
    """Fire an event AFTER the triggering change has been applied."""
    ctx = {"actor": actor, "subject": subject, **extra}
    for w in list(game["watchers"]):
        if w["event"] != event or not w.get("stage"):
            continue
        if actor is not None and actor in w.get("immune", []):
            continue          # immune to the attack PLAY that set this watcher
        push_auto(game, w["owner"], w["card"], w["stage"],
                  data={**w["data"], **extra, "actor": actor, "subject": subject,
                        "owner": w["owner"]})
    from . import effects
    for card, specs in getattr(effects, "TRIGGERS", {}).items():
        for spec in specs:
            if spec["on"] != event:
                continue
            src = spec.get("from", "hand")
            when = spec.get("when")
            if src == "hand":
                order = game["players"]
                i = order.index(game["turn"]) if game["turn"] in order else 0
                verb = "Reveal" if spec.get("mode") == "reveal" else "Play"
                for p in reversed(order[i:] + order[:i]):
                    if spec.get("who") == "actor" and p != actor:
                        continue          # when-YOU-x reactions (Watchtower-class)
                    if card in game["seats"][p]["hand"] and (when is None or when(game, p, ctx)):
                        push_choose_option(game, p, card, spec["stage"],
                                           options=[{"id": "play", "label": f"{verb} {card} from your hand"},
                                                    {"id": "decline", "label": "Don't react"}],
                                           data={**extra, "gained": subject, "gainer": actor})
            elif src == "in_play":
                if actor is not None and card in game["seats"][actor]["in_play"] \
                        and (when is None or when(game, actor, ctx)):
                    # ctx carries actor/subject + the emit's extras. Treasury
                    # ignores it, but a "while this is in play, when you buy a
                    # card, gain a cheaper one" card (Haggler) is useless
                    # without knowing WHAT was bought — the push used to get
                    # only (game, pid).
                    spec["push"](game, actor, ctx)
            elif src == "self":
                if subject == card and (when is None or when(game, actor, ctx)):
                    # **extra carries the emit's context (gain's via_buy/dest,
                    # discard's zone). It used to be dropped here, so a self
                    # trigger could only ever see actor+subject — which blocks
                    # a when-BUY-this card (Farmland) from telling a buy from
                    # any other gain. actor/subject stay authoritative.
                    push_auto(game, actor, card, spec["stage"],
                              data={**extra, "actor": actor, "subject": subject})


def attack_protected(game, pid):
    """Lighthouse (2022): an ongoing until-your-next-turn protection, NOT a
    while-in-play effect — it exists exactly while a 'protect' watcher does."""
    return any(w["event"] == "protect" and w["owner"] == pid
               for w in game["watchers"])


def watcher_data(game, owner, card):
    """Live data dict of a standing watcher (Corsair's per-turn bookkeeping)."""
    for w in game["watchers"]:
        if w["owner"] == owner and w["card"] == card:
            return w["data"]
    return None


def watcher_datas(game, owner, card):
    """ALL live data dicts for owner's copies of a watcher — per-INSTANCE
    bookkeeping (two Sailors each grant their own once-per-turn play)."""
    return [w["data"] for w in game["watchers"]
            if w["owner"] == owner and w["card"] == card]


def duration_in_play(game, pid, card):
    """Is `card` on pid's table (played this turn or persisting)? Riders (a
    Throne Room staying out with its Duration) are on the table too — Sea
    Chart's copy check must see them."""
    seat = game["seats"][pid]
    if card in seat["in_play"]:
        return True
    return any(e["card"] == card or card in e.get("riders", [])
               for e in seat["duration"])


def remove_watcher(game, owner, card, n=1):
    """Card code may burn out a fired watcher (Blockade is per-copy-gained and
    stays; Corsair's per-player-first-treasure tracks in data instead)."""
    kept, removed = [], 0
    for w in game["watchers"]:
        if removed < n and w["owner"] == owner and w["card"] == card:
            removed += 1
            continue
        kept.append(w)
    game["watchers"] = kept


def _start_of_turn(game, pid):
    """Resolve pid's duration entries: queue their fx (LIFO push so the first
    registered resolves first), expire pid's watchers, mark entries done.
    ALSO sweeps pid's own dur_setup entries — a Duration played OFF-TURN
    (Pirate's reaction) never went through pid's clean-up, but its next-turn
    ability still belongs to THIS turn start; its card then discards from
    in_play at pid's ordinary clean-up (entry marked fired = spent)."""
    seat = game["seats"][pid]
    fx_batch = []
    for entry in seat["duration"]:
        for fx in entry["fx"]:
            fx_batch.append((entry["card"], fx))
        entry["fx"] = []
        entry["done"] = True
    for entry in seat.get("dur_setup", []):
        for fx in entry["fx"]:
            fx_batch.append((entry["card"], fx))
        entry["fx"] = []
        entry["fired"] = True
    for card, fx in reversed(fx_batch):
        push_auto(game, pid, card, fx["stage"], data=dict(fx["data"]))
    game["watchers"] = [w for w in game["watchers"] if w["owner"] != pid]
    emit(game, "turn_start", actor=pid)   # Clerk-class start-of-turn reactions


def _cleanup_durations(game, pid):
    """At pid's clean-up: discard done entries — for EVERY seat, not just the
    turn player's (official timing: a Duration discards at the clean-up of the
    turn its last ability resolved, and an ability that resolved BETWEEN turns
    — a denied Outpost — means the following turn's clean-up, whoever's that
    is). Then promote pid's setup entries (in_play -> duration zone). Returns
    the names (incl. riders) that must NOT be discarded from pid's in_play."""
    for p, s in game["seats"].items():
        still_p = []
        for entry in s["duration"]:
            if entry.get("done"):
                s["discard"].append(entry["card"])
                s["discard"].extend(entry.get("riders", []))
            else:
                still_p.append(entry)
        s["duration"] = still_p
    seat = game["seats"][pid]
    kept_out = []
    still = seat["duration"]
    for entry in seat.pop("dur_setup", []):
        # fired = an off-turn play whose fx already resolved at this seat's own
        # turn start — spent, so it discards from in_play like any other card
        if (entry["fx"] or entry["watchers"]) and not entry.get("fired"):
            kept_out.append(entry["card"])
            kept_out.extend(entry["riders"])
            still.append({"card": entry["card"], "fx": entry["fx"],
                          "riders": entry["riders"]})
    seat["duration"] = still
    return kept_out


# --- playing action cards + the attack/reaction kernel -----------------------

def play_action_card(game, pid, card, from_zone="hand", count=True):
    """Move the card to in_play (from_zone=None for throne-room replays), count the
    play, and run its effect. Attack-typed plays are wrapped: reaction windows for
    every opponent holding an eligible Reaction resolve BEFORE the play ability
    (official timing), with per-play immunity collected in the play_ability frame.
    count=False for off-turn reaction plays (Pirate) — they must not pollute the
    turn player's actions_played counter."""
    seat = game["seats"][pid]
    if from_zone is not None:
        seat[from_zone].remove(card)
        seat["in_play"].append(card)
        game["_cur_dur"] = None          # a new physical play gets a fresh entry
        if has_type(game, card, "duration"):
            # eager entry: later stages (Haven's pick) and Throne Room's rider
            # marking both need the physical card's entry to already exist
            _dur_setup_list(game, pid).append({"card": card, "fx": [], "watchers": 0, "riders": []})
            game["_cur_dur"] = [pid, len(_dur_setup_list(game, pid)) - 1]
    else:
        # replay (Throne Room): duration fx pile onto the SAME physical card
        lst = _dur_setup_list(game, pid)
        game["_cur_dur"] = None
        for i in range(len(lst) - 1, -1, -1):
            if lst[i]["card"] == card:
                game["_cur_dur"] = [pid, i]
                break
    if count and has_type(game, card, "action"):
        game["turn_ctx"]["actions_played"] += 1   # Conspirator counts ACTIONS only
    if has_type(game, card, "treasure"):
        # a Treasure played out-of-band (Sailor playing a gained Astrolabe)
        # still produces its printed $ — and the Merchant/first-Silver hook
        _log(game, pid, "play", card=card, coins=coins_of(game, card))
        _treasure_coins(game, pid, card)
    else:
        _log(game, pid, "play", card=card)
    if has_type(game, card, "attack"):
        # Lighthouse protection (until-their-next-turn watcher) = unaffected,
        # no window needed (public, so it's logged rather than asked)
        immune0 = [o for o in opponents(game, pid) if attack_protected(game, o)]
        for o in immune0:
            _log(game, o, "lighthouse")
        push_auto(game, pid, "__attack", "play_ability", data={"card": card, "immune": list(immune0)})
        for o in reversed(opponents(game, pid)):
            if o in immune0:
                continue
            opts = _reaction_options(game, o, immune=[], moat_ok=True)
            if opts:
                _push_window(game, o, opts)
    else:
        from . import effects as _fx
        fn = _fx.EFFECTS.get(card)
        if fn is None and not has_type(game, card, "treasure"):
            raise KeyError(f"dontminion: no effect registered for {card!r}")
        if fn is not None:
            _push_depth(game)
            try:
                fn(game, pid)
            finally:
                _pop_depth(game)
        if has_type(game, card, "treasure"):
            emit(game, "play_treasure", actor=pid, subject=card)


def _reaction_options(game, o, immune, moat_ok=True):
    hand = game["seats"][o]["hand"]
    opts = []
    if moat_ok and "Moat" in hand and o not in immune:
        opts.append({"id": "reveal_moat", "label": "Reveal Moat (unaffected by this attack)"})
    if "Diplomat" in hand and len(hand) >= 5:
        opts.append({"id": "reveal_diplomat", "label": "Reveal Diplomat (+2 cards, then discard 3)"})
    if opts:
        opts.append({"id": "decline", "label": "Don't react"})
    return opts


def _push_window(game, o, opts):
    push_choose_option(game, o, "__attack", "window", options=opts, pick=1)


def _current_attack_frame(game):
    for f in reversed(game["pending"]):
        if f["card"] == "__attack" and f["stage"] == "play_ability":
            return f
    return None


def _k_window(game, pid, frame, choice):
    atk = _current_attack_frame(game)
    immune = atk["data"]["immune"] if atk else []
    cid = choice["ids"][0]
    if cid == "decline":
        return
    if cid == "reveal_moat":
        reveal(game, pid, ["Moat"], "hand")
        if pid not in immune:
            immune.append(pid)
        opts = _reaction_options(game, pid, immune, moat_ok=False)
        if opts:
            _push_window(game, pid, opts)
    elif cid == "reveal_diplomat":
        reveal(game, pid, ["Diplomat"], "hand")
        draw(game, pid, 2)
        hand = game["seats"][pid]["hand"]
        push_choose_cards(game, pid, "__attack", "diplomat_discard",
                          cards=list(hand), mn=3, mx=3, purpose="discard")


def _k_diplomat_discard(game, pid, frame, choice):
    discard(game, pid, choice["cards"])
    atk = _current_attack_frame(game)
    immune = atk["data"]["immune"] if atk else []
    opts = _reaction_options(game, pid, immune, moat_ok=True)
    if opts:
        _push_window(game, pid, opts)


def _k_play_ability(game, pid, frame, choice):
    game["_atk_immune"] = list(frame["data"]["immune"])
    try:
        _effect_fn(frame["data"]["card"])(game, pid)
    finally:
        game.pop("_atk_immune", None)


def attack_opponents(game, pid, card, per_opp_stage, data=None, immune=None):
    """Queue the card's per-opponent stage for every non-immune opponent, in turn
    order; each opponent's whole chain resolves before the next starts.

    Called from on_play (inside the play_ability frame) the per-play immune set
    is picked up automatically. A card that calls this from a LATER stage (its
    attack part follows another choice — Minion's mode, Replace's gain) must
    capture `list(game["_atk_immune"])` into its frame data during on_play and
    pass it back via `immune=` — the transient is gone by then."""
    if immune is None:
        immune = game.get("_atk_immune", [])
    targets = [o for o in opponents(game, pid) if o not in immune]
    if targets:
        push_auto(game, pid, "__attack", "next",
                  data={"queue": targets, "card": card, "stage": per_opp_stage,
                        "extra": data or {}})


def _k_next(game, pid, frame, choice):
    queue = frame["data"]["queue"]
    if not queue:
        return
    o, rest = queue[0], queue[1:]
    if rest:
        push_auto(game, pid, "__attack", "next", data={**frame["data"], "queue": rest})
    push_auto(game, o, frame["data"]["card"], frame["data"]["stage"],
              data={"opp": o, **frame["data"]["extra"]})


KERNEL_STAGES = {
    ("__attack", "window"): _k_window,
    ("__attack", "diplomat_discard"): _k_diplomat_discard,
    ("__attack", "play_ability"): _k_play_ability,
    ("__attack", "next"): _k_next,
    # ("__turn", "finish") registers below its definition
}


# --- turn-move handlers ------------------------------------------------------

def _fresh_turn_ctx():
    return {"bridges": 0, "actions_played": 0, "merchants": 0,
            "silver_played": False, "bought": False}


def _h_play_action(game, pid, move):
    if game["phase"] != "action":
        return False, "not in your action phase"
    card = move.get("card")
    if card not in game["seats"][pid]["hand"]:
        return False, "card not in hand"
    if not has_type(game, card, "action"):
        return False, "not an action card"
    if game["actions"] <= 0:
        return False, "no actions left"
    game["actions"] -= 1
    play_action_card(game, pid, card, from_zone="hand")
    return True, None


def _treasure_coins(game, pid, card):
    """The printed $ of a played Treasure + the Merchant first-Silver hook —
    shared by the buy-phase handler and out-of-band plays (play_action_card)."""
    game["coins"] += coins_of(game, card)
    if card == "Silver" and not game["turn_ctx"]["silver_played"]:
        game["turn_ctx"]["silver_played"] = True
        m = game["turn_ctx"]["merchants"]
        if m:
            game["coins"] += m
            _log(game, pid, "plus", coins=m, why="Merchant")


def _play_one_treasure(game, pid, card):
    from . import effects
    seat = game["seats"][pid]
    seat["hand"].remove(card)
    seat["in_play"].append(card)
    game["_cur_dur"] = None
    if has_type(game, card, "duration"):
        _dur_setup_list(game, pid).append({"card": card, "fx": [], "watchers": 0, "riders": []})
        game["_cur_dur"] = [pid, len(_dur_setup_list(game, pid)) - 1]
    _log(game, pid, "play", card=card, coins=coins_of(game, card))
    _treasure_coins(game, pid, card)
    # treasures with abilities (Astrolabe's duration half) run their effect too
    fn = effects.EFFECTS.get(card)
    if fn is not None:
        _push_depth(game)
        try:
            fn(game, pid)
        finally:
            _pop_depth(game)
    emit(game, "play_treasure", actor=pid, subject=card)


def _h_play_treasure(game, pid, move):
    if game["phase"] != "buy":
        return False, "treasures are played in your buy phase"
    if game["turn_ctx"]["bought"]:
        return False, "can't play treasures after buying"
    card = move.get("card")
    if card not in game["seats"][pid]["hand"]:
        return False, "card not in hand"
    if not has_type(game, card, "treasure"):
        return False, "not a treasure"
    _play_one_treasure(game, pid, card)
    return True, None


def _h_play_all_treasures(game, pid, move):
    if game["phase"] != "buy":
        return False, "treasures are played in your buy phase"
    if game["turn_ctx"]["bought"]:
        return False, "can't play treasures after buying"
    manual = manual_treasures()
    hand = game["seats"][pid]["hand"]
    # interactive treasures (Anvil-class decisions) are never autoplayed —
    # they stay in hand for individual plays
    auto = [c for c in list(hand)
            if has_type(game, c, "treasure") and c not in manual]
    if not auto:
        # a no-op that reported success is what let a bot livelock here
        return False, "no treasures to autoplay"
    # order-sensitive treasures go last; stable, so everything else keeps
    # hand order (which is what determinism/replay compares on)
    last = autoplay_last()
    auto.sort(key=lambda c: c in last)
    for card in auto:
        _play_one_treasure(game, pid, card)
    return True, None


def _h_buy(game, pid, move):
    if game["phase"] != "buy":
        return False, "not in your buy phase"
    card = move.get("card")
    if card not in game["supply"]:
        return False, "no such pile"
    if game["supply"][card] <= 0:
        return False, "pile is empty"
    if game["buys"] <= 0:
        return False, "no buys left"
    err = buy_gate(game, pid, card)
    if err:
        return False, err
    c = cost(game, card)
    if c > game["coins"]:
        return False, "can't afford it"
    game["coins"] -= c
    game["buys"] -= 1
    game["turn_ctx"]["bought"] = True
    _log(game, pid, "buy", card=card)
    gain(game, pid, card, via_buy=True)
    emit(game, "buy", actor=pid, subject=card)   # Prosperity's on-buy seam
    return True, None


def buy_gate(game, pid, card):
    """Pile-specific BUY restrictions (Grand Market's no-Copper-in-play).
    effects.BUY_GATES = {card: fn(game, pid) -> error string | None}. Gaining
    bypasses gates — they bind buying only."""
    from . import effects
    fn = getattr(effects, "BUY_GATES", {}).get(card)
    return fn(game, pid) if fn is not None else None


def _h_end_phase(game, pid, move):
    if game["phase"] == "action":
        game["phase"] = "buy"
        _log(game, pid, "phase", phase="buy")
    elif not _push_cleanup_choices(game, pid):
        _end_turn(game, pid)
    return True, None


def _push_cleanup_choices(game, pid):
    """End-of-buy-phase decisions (Treasury's may-topdeck) via the trigger
    bus. When any fire, the turn end runs through frames: the parked
    __turn/finish continuation fires _end_turn once the choices resolve.
    Returns True if frames were pushed (else callers end the turn directly)."""
    n0 = len(game["pending"])
    push_auto(game, pid, "__turn", "finish", data={})
    emit(game, "buy_phase_end", actor=pid)
    if len(game["pending"]) == n0 + 1:
        _pop_frame(game)          # nothing triggered — unpark the finish
        return False
    return True


def _k_turn_finish(game, pid, frame, choice):
    _end_turn(game, pid)


KERNEL_STAGES[("__turn", "finish")] = _k_turn_finish
KERNEL_STAGES[("__gain", "resolve")] = _k_gain_resolve


_HANDLERS = {
    "play_action": _h_play_action,
    "play_treasure": _h_play_treasure,
    "play_all_treasures": _h_play_all_treasures,
    "buy": _h_buy,
    "end_phase": _h_end_phase,
}


def _maybe_auto_buy(game):
    """Auto-advance action -> buy once the turn player can't act any further:
    effects fully resolved (no pending) and either no Actions left or no
    Action card in hand. Evaluated only inside apply_move (after _drive) and
    at the hand-off in _end_turn — never at new_game, so test fixtures that
    stage a hand post-deal still start in the action phase. Because it folds
    into the CAUSING move, that move's undo snapshot restores the pre-move
    action phase (no separate skip to unwind)."""
    if game["over"] or game["phase"] != "action" or game["pending"]:
        return
    hand = game["seats"][game["turn"]]["hand"]
    if game["actions"] <= 0 or not any(has_type(game, c, "action") for c in hand):
        game["phase"] = "buy"
        _log(game, game["turn"], "phase", phase="buy", auto=True)


def _end_turn(game, pid):
    seat = game["seats"][pid]
    # durations: discard resolved entries, keep this turn's setups on the table
    kept_out = _cleanup_durations(game, pid)
    inplay = list(seat["in_play"])
    for name in kept_out:
        inplay.remove(name)
    seat["discard"].extend(inplay)
    seat["in_play"] = []
    seat["discard"].extend(seat["hand"])
    seat["hand"] = []
    # Sailor-class this-turn watchers die with the turn
    game["watchers"] = [w for w in game["watchers"]
                        if w.get("until") != "turn_end"]
    # Smugglers: this turn's gains become pid's "last completed turn" record
    game["last_turn_gains"][pid] = game.pop("_turn_gains", [])
    # Outpost: the 3-card clean-up draw ALWAYS applies once played; the extra
    # turn only if the PREVIOUS turn wasn't also pid's (no 3rd turn in a row)
    prev = game.get("last_turn_pid")
    outpost_played = game.pop("_outpost", None) == pid
    extra = outpost_played and prev != pid
    if outpost_played and not extra:
        # the extra-turn ability resolved (denied) BETWEEN turns: the Outpost
        # is spent now — mark done (dropping its parked no-op fx) so the next
        # clean-up's all-seats sweep discards it, per official timing
        for entry in seat["duration"]:
            if entry["card"] == "Outpost" and not entry.get("done"):
                entry["fx"] = []
                entry["done"] = True
    draw(game, pid, 3 if outpost_played else 5)
    seat["turns_taken"] += 1
    game["last_turn_pid"] = pid
    if game["supply"].get("Province", 0) <= 0 or count_empty_piles(game) >= 3 \
            or (game["colony"] and game["supply"].get("Colony", 1) <= 0):
        _finish_game(game)
        return
    order = game["players"]
    nxt = pid if extra else order[(order.index(pid) + 1) % len(order)]
    game["extra_turn"] = bool(extra)
    game["turn"] = nxt
    game["turn_number"] += 1
    game["phase"] = "action"
    game["actions"] = 1
    game["buys"] = 1
    game["coins"] = 0
    game["turn_ctx"] = _fresh_turn_ctx()
    _log(game, nxt, "turn_start", turn=game["turn_number"], extra=bool(extra))
    _arm_undo(game)
    _start_of_turn(game, nxt)   # duration fx queue as auto frames; watchers expire
    _maybe_auto_buy(game)       # a hand with no Action cards skips straight to buy


def _finish_game(game):
    game["over"] = True
    scores = score_game(game)
    game["scores"] = scores
    best = max(s["vp"] for s in scores.values())
    tied = [p for p in game["players"] if scores[p]["vp"] == best]
    if len(tied) > 1:
        fewest = min(scores[p]["turns"] for p in tied)
        tied = [p for p in tied if scores[p]["turns"] == fewest]
    game["winners"] = tied
    _log(game, None, "game_over", winners=list(tied))


# --- the move gate -----------------------------------------------------------

def apply_move(game, pid, move):
    if game["over"]:
        return False, "game is over"
    if not isinstance(move, dict):
        return False, "bad move"
    mt = move.get("type")
    if mt == "undo_turn":
        # BEFORE the pending gate — an unrevealed move is undoable even with a
        # frame open (yours: a Workshop pile pick; an opponent's: a Militia they
        # haven't answered yet). legal_moves deliberately never offers this, so
        # the random bot can't take it back.
        ok, err = _undo_move(game, pid)
        if ok:
            _post_move(game)
        return ok, err
    pushed = False
    if game["pending_pid"] is not None:
        if pid != game["pending_pid"]:
            return False, "not your decision"
        if mt != "decision":
            return False, f"must resolve {game['pending_kind']} first"
        if pid == game["turn"]:
            _push_undo(game)      # a reveal inside the move clears it again
            pushed = True
        ok, err = _resolve_decision(game, pid, move)
    elif mt == "decision":
        return False, "nothing to decide"
    elif pid != game["turn"]:
        return False, "not your turn"
    else:
        handler = _HANDLERS.get(mt)
        if handler is None:
            return False, f"unknown move: {mt}"
        _push_undo(game)          # a reveal inside the move clears it again
        pushed = True
        ok, err = handler(game, pid, move)
    if ok:
        _drive(game)
        _maybe_auto_buy(game)
        _post_move(game)
    elif pushed and game.get("undo_stack"):
        game["undo_stack"].pop()   # a rejected move mutated nothing
    return ok, err


def _resolve_decision(game, pid, move):
    top = game["pending"][-1]
    ok, err = _validate_choice(top, move)
    if not ok:
        return False, err
    if pid != game["turn"]:
        # An opponent's choice (attack response, Masquerade pick, window
        # decline) is information the turn player didn't have — no undo after.
        _mark_revealed(game)
    frame = _pop_frame(game)
    _push_depth(game)
    try:
        _stage_fn(frame["card"], frame["stage"])(game, pid, frame, move)
    finally:
        _pop_depth(game)
    return True, None


def _validate_choice(frame, move):
    kind = frame["kind"]
    c = frame["constraint"]
    if kind == "choose_cards":
        cards = move.get("cards")
        if not isinstance(cards, list) or not all(isinstance(x, str) for x in cards):
            return False, "bad cards"
        if not (c["min"] <= len(cards) <= c["max"]):
            return False, f"pick between {c['min']} and {c['max']} cards"
        if not _is_submultiset(cards, c["cards"]):
            return False, "cards not available"
        return True, None
    if kind == "choose_option":
        ids = move.get("ids")
        if not isinstance(ids, list) or len(ids) != c["pick"]:
            return False, f"pick exactly {c['pick']} option(s)"
        valid = {o["id"] for o in c["options"]}
        if not all(i in valid for i in ids):
            return False, "unknown option"
        if c.get("distinct", True) and len(set(ids)) != len(ids):
            return False, "options must be different"
        return True, None
    if kind == "order_cards":
        order = move.get("order")
        if not isinstance(order, list) or sorted(order) != sorted(c["cards"]):
            return False, "order must use exactly the shown cards"
        return True, None
    if kind == "place_in_deck":
        pos = move.get("position")
        if not isinstance(pos, int) or not (0 <= pos <= c["deck_len"]):
            return False, f"position must be 0..{c['deck_len']}"
        return True, None
    if kind == "name_card":
        if move.get("card") not in c["cards"]:
            return False, "name a card in the supply"
        return True, None
    if kind == "choose_pile":
        if move.get("pile") not in c["piles"]:
            return False, "not an eligible pile"
        return True, None
    return False, f"unknown decision kind {kind}"


def _is_submultiset(sub, full):
    counts = {}
    for x in full:
        counts[x] = counts.get(x, 0) + 1
    for x in sub:
        counts[x] = counts.get(x, 0) - 1
        if counts[x] < 0:
            return False
    return True


# --- legal moves + uniform sampling ------------------------------------------

def legal_moves(game, pid):
    """Every ≥1-valid-move guarantee applies to the ACTOR; others get [].
    Decision spaces are enumerated completely when small (≤ _ENUM_CAP), else a
    single valid sampled fallback is returned (apply_move validates, so the UI
    never depends on this being complete)."""
    if game["over"]:
        return []
    if game["pending_pid"] is not None:
        if pid != game["pending_pid"]:
            return []
        return _legal_decisions(game, pid)
    if pid != game["turn"]:
        return []
    mv = []
    hand = game["seats"][pid]["hand"]
    if game["phase"] == "action":
        if game["actions"] > 0:
            for c in sorted(set(hand)):
                if has_type(game, c, "action"):
                    mv.append({"type": "play_action", "card": c})
    else:
        if not game["turn_ctx"]["bought"]:
            treasures = sorted({c for c in hand if has_type(game, c, "treasure")})
            for c in treasures:
                mv.append({"type": "play_treasure", "card": c})
            # only when play_all would actually PLAY something — it skips the
            # interactive MANUAL_TREASURES (War Chest/Anvil), so a hand holding
            # nothing else makes it a no-op, and a bot that prefers it loops.
            if any(c not in manual_treasures() for c in treasures):
                mv.append({"type": "play_all_treasures"})
        if game["buys"] > 0:
            for pile in sorted(game["supply"]):
                if game["supply"][pile] > 0 and cost(game, pile) <= game["coins"] \
                        and buy_gate(game, pid, pile) is None:
                    mv.append({"type": "buy", "card": pile})
    mv.append({"type": "end_phase"})
    return mv


def _legal_decisions(game, pid):
    frame = game["pending"][-1]
    kind = frame["kind"]
    c = frame["constraint"]
    out = []
    if kind == "choose_cards":
        seen = set()
        for k in range(c["min"], c["max"] + 1):
            for combo in itertools.combinations(sorted(c["cards"]), k):
                if combo in seen:
                    continue
                seen.add(combo)
                out.append({"type": "decision", "cards": list(combo)})
                if len(out) > _ENUM_CAP:
                    return [_sampled_fallback(game, pid)]
    elif kind == "choose_option":
        ids = [o["id"] for o in c["options"]]
        for combo in itertools.combinations(ids, c["pick"]):
            out.append({"type": "decision", "ids": list(combo)})
    elif kind == "order_cards":
        seen = set()
        for perm in itertools.permutations(c["cards"]):
            if perm in seen:
                continue
            seen.add(perm)
            out.append({"type": "decision", "order": list(perm)})
            if len(out) > _ENUM_CAP:
                return [_sampled_fallback(game, pid)]
    elif kind == "place_in_deck":
        out = [{"type": "decision", "position": p} for p in range(c["deck_len"] + 1)]
    elif kind == "name_card":
        out = [{"type": "decision", "card": n} for n in c["cards"]]
    elif kind == "choose_pile":
        out = [{"type": "decision", "pile": n} for n in c["piles"]]
    return out or [_sampled_fallback(game, pid)]


def _sampled_fallback(game, pid):
    return {"type": "decision", **sample_decision(game, pid, random.Random(0))}


def sample_decision(game, pid, rng):
    """Uniform valid payload for the top frame. Uses the caller's rng, never the
    game's rng_state (the AI must not consume game entropy)."""
    frame = game["pending"][-1]
    assert frame["pid"] == pid, "sample_decision for the wrong seat"
    kind = frame["kind"]
    c = frame["constraint"]
    if kind == "choose_cards":
        k = rng.randint(c["min"], c["max"])
        return {"cards": rng.sample(c["cards"], k)}
    if kind == "choose_option":
        ids = [o["id"] for o in c["options"]]
        return {"ids": rng.sample(ids, c["pick"])}
    if kind == "order_cards":
        order = list(c["cards"])
        rng.shuffle(order)
        return {"order": order}
    if kind == "place_in_deck":
        return {"position": rng.randint(0, c["deck_len"])}
    if kind == "name_card":
        return {"card": rng.choice(c["cards"])}
    if kind == "choose_pile":
        return {"pile": rng.choice(c["piles"])}
    raise ValueError(f"unknown decision kind {kind}")


# --- scoring -----------------------------------------------------------------

def _all_cards(game, pid):
    s = game["seats"][pid]
    owned = s["deck"] + s["hand"] + s["discard"] + s["in_play"] + s["aside"]
    # Seaside zones + mats (migrate guarantees these on every loaded save)
    owned += s["dur_aside"] + s["island"] + s["village_mat"]
    for entry in s["duration"]:
        owned.append(entry["card"])
        owned += entry.get("riders", [])
    return owned


def _vp_of(game, pid):
    owned = _all_cards(game, pid)
    n = len(owned)
    duchies = owned.count("Duchy")
    total = 0
    for c in owned:
        v = CARDS[c]["vp"]
        if v == "gardens":
            total += n // 10
        elif v == "duke":
            total += duchies
        else:
            total += v
    return total


def _total_vp(game, pid):
    return _vp_of(game, pid) + game["vp_tokens"].get(pid, 0)


def _post_move(game):
    game["vp"] = {p: _total_vp(game, p) for p in game["players"]}


def score_game(game):
    return {p: {"vp": _total_vp(game, p), "turns": game["seats"][p]["turns_taken"]}
            for p in game["players"]}


def is_over(game):
    return bool(game["over"])


def winners(game):
    return list(game["winners"]) if game["over"] else []


# --- per-recipient redaction -------------------------------------------------

def player_view(game, viewer):
    """Build (not filter) the wire view. Deck order NEVER ships; hands only to
    their owner; discard = top + count; the raw pending stack (frame data!) is
    replaced by pending_view; rng_state/seed popped; the undo snapshots (every
    hidden zone!) never leave the server — only their COUNT ships (undo_depth),
    which with turn_revealed drives the client's Undo button. Everything
    reveals at over."""
    g = copy.deepcopy({k: v for k, v in game.items() if k != "undo_stack"})
    g["undo_depth"] = len(game.get("undo_stack") or [])
    g.pop("rng_state", None)
    g.pop("seed", None)
    g.pop("_cur_dur", None)
    g.pop("_outpost", None)
    # watchers are public table state, but their data can reference hidden
    # resume info — ship only the visible identity
    g["watchers"] = [{"event": w["event"], "owner": w["owner"], "card": w["card"]}
                     for w in g["watchers"]]
    # EFFECTIVE prices, computed by THE cost function — the client must never
    # re-derive them. It used to subtract only Bridge, so every other cost rule
    # (Quarry's turn discount, Peddler's dynamic self-cost, and every future
    # one) was invisible: the pile showed its printed price, never lit up as
    # affordable, and the click handler refused to send the buy.
    g["costs"] = {c: cost(game, c) for c in game["supply"]}
    pend = g.pop("pending")
    if pend:
        top = pend[-1]
        if viewer == top["pid"]:
            g["pending_view"] = {"kind": top["kind"], "card": top["card"],
                                 "constraint": top["constraint"]}
        else:
            g["pending_view"] = {"card": top["card"], "waiting_on": top["pid"]}
    else:
        g["pending_view"] = None
    over = g["over"]
    for p, seat in g["seats"].items():
        seat["deck_count"] = len(seat["deck"])
        seat["hand_count"] = len(seat["hand"])
        seat["aside_count"] = len(seat["aside"])
        seat["discard_view"] = {"top": seat["discard"][-1] if seat["discard"] else None,
                                "count": len(seat["discard"])}
        # Seaside zones: durations + island are open table state; the duration
        # set-aside (Haven) and Native Village mat are owner-only until over
        seat["duration_view"] = [{"card": e["card"], "riders": list(e.get("riders", []))}
                                 for e in seat["duration"]]
        seat["island"] = list(seat["island"])
        seat["dur_aside_count"] = len(seat["dur_aside"])
        seat["village_count"] = len(seat["village_mat"])
        seat.pop("duration", None)
        seat.pop("dur_setup", None)
        if not over:
            seat.pop("deck")
            seat.pop("discard")
            seat.pop("aside")
            if p != viewer:
                seat.pop("hand")
                seat.pop("dur_aside", None)
                seat.pop("village_mat", None)
    log = []
    for e in g["log"]:
        if "private_to" in e and viewer not in e["private_to"]:
            continue
        # draw entries carry the drawn card names — owner-only until game over
        # (per-field redaction; the count n stays public)
        if not over and e.get("event") == "draw" and e.get("pid") != viewer and "cards" in e:
            e = {k: v for k, v in e.items() if k != "cards"}
        log.append(e)
    g["log"] = log
    return g


# --- setup -------------------------------------------------------------------

def new_game(player_ids, expansions, seed=None, names=None, kingdom=None):
    """players in seat/turn order (the caller shuffles seats); expansions a
    non-empty subset of KINGDOM's keys; kingdom overrides the random 10 (tests,
    forced-kingdom soaks)."""
    players = list(player_ids)
    if not 2 <= len(players) <= 4:
        raise ValueError("dontminion needs 2-4 players")
    exps = sorted(set(expansions or []))
    if not exps or any(e not in KINGDOM for e in exps):
        raise ValueError(f"expansions must be a non-empty subset of {sorted(KINGDOM)}")
    rng = random.Random(seed)
    if kingdom is not None:
        kingdom = list(kingdom)
        bad = [c for c in kingdom if c not in CARDS or not CARDS[c]["kingdom"]]
        if bad:
            raise ValueError(f"unknown kingdom cards: {bad}")
    else:
        pool = sorted({c for e in exps for c in KINGDOM[e]})
        if len(pool) < 10:
            raise ValueError("not enough kingdom cards in the enabled expansions")
        kingdom = sorted(rng.sample(pool, 10))
    n = len(players)
    supply = {c: pile_size(c, n) for c in BASIC_CARDS}
    for c in kingdom:
        supply[c] = pile_size(c, n)
    # Prosperity: Platinum/Colony join the Supply with probability equal to
    # the Prosperity proportion of the kingdom (official randomizer rule);
    # both piles or neither. Colony-empty becomes a game-end condition.
    prosperity_n = sum(1 for c in kingdom if CARDS[c]["expansion"] == "prosperity")
    colony = prosperity_n > 0 and rng.random() < prosperity_n / 10
    if colony:
        supply["Platinum"] = pile_size("Platinum", n)
        supply["Colony"] = pile_size("Colony", n)
    # Charlatan's game-wide rule: Curse is also a Treasure worth $1
    curse_is_treasure = "Charlatan" in kingdom
    game = {
        "game": "dontminion",
        "players": players,
        "names": dict(names or {p: p for p in players}),
        "expansions": exps,
        "kingdom": kingdom,
        "supply": supply,
        "trash": [],
        "seats": {},
        "turn": players[0],
        "turn_number": 1,
        "phase": "action",
        "actions": 1,
        "buys": 1,
        "coins": 0,
        "turn_ctx": _fresh_turn_ctx(),
        "pending": [],
        "pending_pid": None,
        "pending_kind": None,
        "schema": SCHEMA,
        "watchers": [],            # cross-player triggers (Monkey/Corsair/Blockade)
        "last_turn_pid": None,     # who took the previous turn (Outpost's gate)
        "last_turn_gains": {},     # pid -> cards gained on their last own turn (Smugglers)
        "extra_turn": False,       # the CURRENT turn is an Outpost extra turn
        "colony": colony,          # Platinum/Colony game (Prosperity setup rule)
        "curse_is_treasure": curse_is_treasure,   # Charlatan's game-wide rule
        "vp_tokens": {p: 0 for p in players},
        "vp": {},
        "log": [],
        "log_depth": 0,
        "over": False,
        "winners": [],
        "scores": {},
        "seed": seed,
        "rng_state": None,
    }
    _save_rng(game, rng)
    for pid in players:
        game["seats"][pid] = {"deck": [], "hand": [], "discard": [],
                              "in_play": [], "aside": [], "turns_taken": 0,
                              # Seaside zones: persistent duration entries, their
                              # face-down set-asides (Haven/Blockade), and mats
                              "duration": [], "dur_aside": [],
                              "island": [], "village_mat": []}
        start = ["Copper"] * 7 + ["Estate"] * 3
        r = _make_rng(game)
        r.shuffle(start)
        _save_rng(game, r)
        game["seats"][pid]["deck"] = start
        draw(game, pid, 5)
    _log(game, players[0], "turn_start", turn=1)
    _post_move(game)
    # The setup draws marked "revealed" — arm the FIRST turn's undo cleanly.
    _arm_undo(game)
    return game
