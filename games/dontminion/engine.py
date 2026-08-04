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

from .cards import (
    CARDS, KINGDOM, PILES, REWARDS, KNIGHTS, RUINS, RUINS_EACH, SHELTERS,
    pile_size, REQUIREMENTS, REQUIREMENT_ORDER,
    grants as cards_grant, overpays as cards_overpay, potion_of as cards_potion,
    expansion_of as cards_expansion, printed_cost as cards_printed_cost,
)

BASIC_CARDS = ("Copper", "Silver", "Gold", "Estate", "Duchy", "Province", "Curse")
_DRIVE_CAP = 500
_ENUM_CAP = 200

# Game-dict shape version. BUMP THIS whenever a phase adds a key the kernel
# reads, and add the matching step to migrate(). The server migrates at LOAD,
# so kernel code may assume the CURRENT shape — no defensive .get() for keys
# migrate guarantees (lazily-built transients like dur_setup stay lazy).
SCHEMA = 9
#   1 = Base + Intrigue
#   2 = Seaside      (durations/mats/watchers/extra turns)
#   3 = Prosperity   (VP tokens, Platinum/Colony, Charlatan's Curse rule)
#   4 = card RENAMES (Harem -> Farm) — the first genuine TRANSFORM step
#   5 = Hinterlands  (per-turn counters for Crossroads/Fool's Gold/Cauldron)
#   6 = the PILE MODEL (game["piles"]: ordered/non-supply piles, attachments)
#   7 = Cornucopia & Guilds (Coffers, the setup-chosen Bane/Ferryman piles,
#       Footpad's game rule, per-seat set-asides + start-of-turn abilities)
#   8 = Alchemy (the cost VECTOR's second money pool, game["potions"])
#   9 = Dark Ages (game["shelters"] — the Shelter starting decks)

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
    # the pile model (ph. 3H). Every pile a pre-3H save can hold is an
    # ordinary Supply pile of the card it is named after, so the whole model
    # rebuilds from the count index — and it stays a FILL, not a transform,
    # because a game that already has `piles` must keep the one it has.
    "nonsupply": lambda g: {},
    "piles": lambda g: {c: _plain_pile(c) for c in g.get("supply", {})},
    # Cornucopia & Guilds (ph. 4)
    "coffers": lambda g: {p: 0 for p in g.get("players", [])},
    "potions": lambda g: 0,
    "bane": lambda g: None,             # Young Witch's extra Supply pile
    "ferryman_pile": lambda g: None,    # Ferryman's extra NON-Supply pile
    "footpad_draw": lambda g: False,    # Footpad's game-wide when-gain rule
    # Dark Ages (ph. 6): did this game deal Shelters instead of Estates? Read
    # by nothing at runtime but the view and the tests — it is a SETUP record,
    # and an old save that never had one played without them.
    "shelters": lambda g: False,
}
_SEAT_FILLS = {
    "aside": list,
    # Seaside zones + mats
    "duration": list, "dur_aside": list,
    "island": list, "village_mat": list,
    # C&G: cards set aside to be played at the start of your next turn
    # (Farmhands), and the seat-level start-of-turn abilities that play them
    "set_aside": list, "start_fx": list, "cleanup_aside": list,
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
                  "immune", "_outpost", "_cur_dur", "_actor"}
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
    # A PILE NAME IS NOT A CARD NAME: "'Knight', 'Loot', 'Ruins', 'Castle' and
    # 'Shelter' are types, not names" — you can't name the Knights pile, so an
    # ordered pile's key is filtered out of the offer (its cards are named by
    # their own names, which is what pile_top would give you).
    _push_frame(game, {"kind": "name_card", "pid": pid, "card": card, "stage": stage,
                       "constraint": {"cards": sorted(c for c in game["supply"]
                                                      if c in CARDS)},
                       "data": data or {}})


def push_auto(game, pid, card, stage, data=None):
    _push_frame(game, {"kind": "auto", "pid": pid, "card": card, "stage": stage,
                       "constraint": None, "data": data or {}})


def _run_stage(game, card, stage, pid, frame, choice):
    """THE stage entry point. Binds `_actor` so resource helpers credit the
    player whose stage is running, not whoever's turn it is — the two differ
    for any reaction resolving on an opponent's turn."""
    prev = game.get("_actor")
    game["_actor"] = pid
    _push_depth(game)
    try:
        _stage_fn(card, stage)(game, pid, frame, choice)
    finally:
        _pop_depth(game)
        if prev is None:
            game.pop("_actor", None)
        else:
            game["_actor"] = prev


def _stage_fn(card, stage):
    fn = KERNEL_STAGES.get((card, stage))
    if fn is None and stage.startswith("__"):
        # a KERNEL stage usable by ANY card ("*"): the frame keeps the card's
        # own name so the prompt still reads "Sentry", but the handler is the
        # kernel's. Card-name-agnostic shared shapes live here.
        fn = KERNEL_STAGES.get(("*", stage))
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
        _run_stage(game, frame["card"], frame["stage"], frame["pid"], frame, None)
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


# --- THE PILE MODEL -----------------------------------------------------------
# `supply = {name: count}` could only ever say "a pile of N copies of the card
# it is named after". Five later sets need more than that (ordered Ruins and
# Knights, split piles and Castles, ROTATING piles, per-pile Traits and
# Adventures tokens) and six need gain sources that are not in the Supply at
# all (Rewards, Spoils/Madman/Mercenary, Horses, Spirits, Loot).
#
# So a pile is an OBJECT — but its COUNT deliberately stays in a flat
# {name: count} index, because that is the shape ~60 read sites across five
# effects modules, both bots, the client and a hundred tests already speak.
# There are two such indexes, identical in shape:
#
#   game["supply"]    — the BUYABLE piles. Untouched by this phase: still the
#                       same dict, still hand-writable, so `g["supply"]["Curse"]
#                       = 0` in a test or a fixture is still exactly right.
#   game["nonsupply"] — the piles that are not in the Supply. Never buyable,
#                       never counted for the three-empty-piles game end.
#
# and one metadata record per pile:
#
#   game["piles"][name] = {
#     "supply":   bool,           # which index holds this pile's count
#     "face":     card_name,      # the card whose cost/types this pile SHOWS.
#                                 #   == name for an ordinary pile; the top card
#                                 #   for an ordered one, and it is RETAINED
#                                 #   when the pile empties so cost()/types_of()
#                                 #   stay total (an empty pile still has a
#                                 #   price on the board)
#     "contents": [card, ...]|None,  # ORDERED piles only, top first. None means
#                                 #   "index[name] copies of `name`" — no list of
#                                 #   identical strings to keep in step
#     "members":  [card, ...],    # every card name that belongs to this pile —
#                                 #   how a RETURNED card finds its way home
#                                 #   once the pile is empty and `contents` can
#                                 #   no longer answer it
#     "attach":   {},             # per-pile attachments (Adventures tokens,
#                                 #   Empires' gathered VP, Plunder's Traits)
#   }
#
# EXACTLY ONE AUTHORITY PER COUNT, which is the whole point of splitting it
# this way: an ordinary pile's count is its index entry, and an ORDERED pile's
# count is len(contents) — for those the index is a MIRROR, written only by
# _pile_take/_pile_return so the enumeration sites keep working, and never
# read by pile_count(). The soak asserts the mirror. Storing the count on the
# pile object instead would have made every existing `g["supply"][x] = 0` a
# silent desync, in tests today and in every future card batch.
#
# The reason non-supply piles live in a SEPARATE index rather than a flag
# inside `supply`: every "piles costing up to $4" enumeration in card code
# reads `game["supply"]`, and "gain a card from the Supply" must never offer a
# Spoils. Out of that dict they are excluded by construction, in every module,
# with no call site to remember. Card code reaches them through gain_from().

def _plain_pile(name, supply=True):
    return {"supply": supply, "face": name, "contents": None,
            "members": [name], "attach": {}}


def _pile_index(game, pile):
    """The count map holding this pile — see THE PILE MODEL."""
    return game["supply"] if pile["supply"] else game["nonsupply"]


def add_pile(game, name, count=None, contents=None, supply=False, members=None):
    """Create a pile at SETUP time. `contents` (top first) makes it ORDERED —
    Ruins, Knights, split piles, Castles; otherwise it is `count` copies of a
    card named `name`. Defaults to a NON-supply pile, which is what every
    caller outside new_game wants (Rewards, Spoils, Horses, Spirits, Loot):
    never buyable, never counted for the game end."""
    if name in game["piles"]:
        raise ValueError(f"pile {name!r} already exists")
    # Every pile FACE has to be a real card, because cost()/types_of() price a
    # pile through its face and player_view prices every pile on every wire
    # build. Catching it here names the pile; catching it there is a KeyError
    # deep in a view the client is waiting on.
    unknown = [c for c in (contents if contents is not None else [name])
               if c not in CARDS]
    if unknown:
        raise ValueError(f"pile {name!r} holds unknown cards: {unknown}")
    if contents is not None:
        contents = list(contents)
        if not contents:
            raise ValueError("an ordered pile must start with cards in it")
        pile = {"supply": supply, "face": contents[0], "contents": contents,
                "members": list(members) if members else sorted(set(contents)),
                "attach": {}}
        n = len(contents)
    else:
        pile = _plain_pile(name, supply)
        n = int(count or 0)
    game["piles"][name] = pile
    _pile_index(game, pile)[name] = n
    return pile


def pile_count(game, name):
    """How many cards are left in a pile. THE reader — never index the count
    maps directly for an ordered pile, whose index entry is only a mirror."""
    p = game["piles"].get(name)
    if p is None:
        return 0
    if p["contents"] is not None:
        return len(p["contents"])
    return _pile_index(game, p).get(name, 0)


def is_supply_pile(game, name):
    p = game["piles"].get(name)
    return bool(p and p["supply"])


def pile_face(game, name):
    """The card whose cost and types this pile SHOWS — total, even for an empty
    ordered pile (it keeps the last card's face, so the board still prices it).
    A plain card name is its own face, so this is safe to call on anything."""
    p = game["piles"].get(name)
    return p["face"] if p else name


def pile_top(game, name):
    """The card a gain or buy from this pile would actually yield, or None if
    the pile is empty. For an ordinary pile that is the pile's own name; for an
    ordered one it is the top card, which is what the pile costs and is."""
    p = game["piles"].get(name)
    if p is None or pile_count(game, name) <= 0:
        return None
    return p["contents"][0] if p["contents"] is not None else name


def pile_of(game, card):
    """Which pile `card` belongs to — how a returned card (exchange, Spoils
    going home) finds its way back. None if the card came from nowhere we own.

    A pile of the card's own name wins over an ordered pile listing it. Nothing
    real is ambiguous here (a card in an ordered pile — a Ruin, a Knight, half
    of a split pile — never also has a Supply pile of its own), so this only
    fixes an order for a situation the sets cannot produce."""
    p = game["piles"].get(card)
    if p is not None and p["contents"] is None:
        return card
    for name, pile in game["piles"].items():
        if pile["contents"] is not None and card in pile["members"]:
            return name
    return None


def supply_piles(game):
    """Sorted names of the buyable piles — the Supply."""
    return sorted(game["supply"])


def pile_cards(game):
    """Every REAL card sitting in a pile, as a {name: count} map. The pile NAME
    is not a card for an ordered pile ("Knights" is nothing you can own), so
    the conservation census has to ask this rather than count the index — and
    it has to reach the non-supply piles, which the index does not hold."""
    out = {}
    for name, p in game["piles"].items():
        if p["contents"] is not None:
            for c in p["contents"]:
                out[c] = out.get(c, 0) + 1
        else:
            n = pile_count(game, name)
            if n:
                out[name] = out.get(name, 0) + n
    return out


def pile_attach(game, name, key, value):
    """Put something ON a pile (an Adventures token, a Trait, gathered VP).
    Public table state — it ships in the pile view."""
    game["piles"][name]["attach"][key] = value


def pile_attachment(game, name, key, default=None):
    p = game["piles"].get(name)
    return p["attach"].get(key, default) if p else default


def _pile_take(game, name):
    """Remove the top card from a pile and return its NAME (None if empty).
    THE take — with _pile_return it is the only writer of an ordered pile's
    contents, and the only thing that keeps that pile's index mirror honest."""
    p = game["piles"].get(name)
    n = pile_count(game, name)
    if p is None or n <= 0:
        return None
    if p["contents"] is not None:
        card = p["contents"].pop(0)
        if p["contents"]:
            p["face"] = p["contents"][0]     # else keep the last face
    else:
        card = name
    _pile_index(game, p)[name] = n - 1
    return card


def _pile_return(game, card):
    """Put a card back on its pile (Trader's exchange; Spoils going home).
    False if we can't tell which pile it belongs to — nothing happens then,
    rather than conjuring a new buyable pile out of the card's name, which is
    what the old `supply[card] = supply.get(card, 0) + 1` would have done."""
    name = pile_of(game, card)
    if name is None:
        return False
    p = game["piles"][name]
    n = pile_count(game, name)
    if p["contents"] is not None:
        p["contents"].insert(0, card)
        p["face"] = card
    _pile_index(game, p)[name] = n + 1
    return True


def return_to_pile(game, pid, card, zone="in_play"):
    """Move a card a player holds back onto its own pile — Spoils, Madman and
    Mercenary "return this to its pile" (ph. 6), Encampment (ph. 8). Not a
    trash and not a discard: it emits nothing and the card leaves play."""
    seat = game["seats"][pid]
    if card not in seat[zone]:
        return False
    if not _pile_return(game, card):
        return False
    seat[zone].remove(card)
    _log(game, pid, "return_to_pile", card=card)
    return True


def _priced(game, name):
    """Resolve a name that may be a PILE into the card whose printed cost and
    types apply — "the cost and types of a pile are those of its top card".
    A real card name is itself, so every cost/type query can call this."""
    if name in CARDS:
        return name
    p = game["piles"].get(name)
    return p["face"] if p is not None else name


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


def gain(game, pid, pile, dest="discard", via_buy=False, overpay=0):
    """Gain the top card of a pile. `pile` is a pile NAME — for every ordinary
    pile that is the card's own name, which is why every existing call site
    reads as "gain this card"; for an ordered pile (Knights, a split pile) the
    card you actually get is its top one, and that is what lands in your zone,
    logs, and rides the `gain` event as the subject. Returns False (nothing
    happens) if the pile is empty.

    WOULD-GAIN interception (the replacement protocol, Trader-class): if any
    TRIGGERS entry with on="would_gain"/from="hand" matches for the GAINER, the
    physical gain is parked as a __gain/resolve auto frame with the reaction
    windows on top; a replacement stage calls cancel_pending_gain() and
    performs its own effect instead. Callers see True ("a gain is underway") —
    no current call site branches on the difference, and new card code must
    not either."""
    got = pile_top(game, pile)
    if got is None:
        return False
    from . import effects
    would = [(rc, s) for rc, specs in getattr(effects, "TRIGGERS", {}).items()
             for s in specs if s["on"] == "would_gain" and s.get("from") == "hand"]
    for rcard, spec in would:
        when = spec.get("when")
        if rcard in game["seats"][pid]["hand"] and (when is None or when(game, pid,
                {"actor": pid, "subject": got, "dest": dest, "via_buy": via_buy})):
            verb = "Reveal" if spec.get("mode") == "reveal" else "Play"
            push_auto(game, pid, "__gain", "resolve",
                      data={"pid": pid, "card": pile, "dest": dest,
                            "via_buy": via_buy, "overpay": overpay,
                            "cancelled": False})
            push_choose_option(game, pid, rcard, spec["stage"],
                               options=[{"id": "react", "label": f"{verb} {rcard} ({got} gain)"},
                                        {"id": "decline", "label": "Don't react"}],
                               data={"card": got, "gainer": pid, "dest": dest})
            return True
    return _gain_now(game, pid, pile, dest, via_buy, overpay)


def gain_from(game, pid, pile, dest="discard"):
    """Gain from a NON-SUPPLY pile — Rewards (ph. 4), Spoils/Madman/Mercenary
    (ph. 6), Horses (ph. 10), Spirits (ph. 11), Loot (ph. 13). Mechanically the
    same physical gain as any other (it IS a gain: Watchtower reacts to it,
    when-gain abilities fire), so it shares one code path; the name exists so a
    card SAYS it is reaching outside the Supply, and so a reader can tell that
    from a Supply gain at the call site rather than by knowing the pile."""
    return gain(game, pid, pile, dest=dest)


def _gain_now(game, pid, pile, dest, via_buy=False, overpay=0):
    """The physical gain — pile decrement, placement, bookkeeping, emit."""
    card = _pile_take(game, pile)
    if card is None:
        return False
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
        if game["phase"] == "buy":
            game["turn_ctx"]["buy_gains"] += 1        # Merchant Guild counts these
            if has_type(game, card, "victory"):
                game["turn_ctx"]["gained_victory_in_buy"] = True   # Treasury's gate
    _log(game, pid, "gain", card=card, dest=dest)
    # via_buy rides the event: Hoard fires only on BOUGHT gains, Mint on any.
    # overpay rides it too — the `$N+` cards' overpay ability IS a when-gain
    # ability (2022 retiming), so it reads its amount off the event.
    emit(game, "gain", actor=pid, subject=card, dest=dest, via_buy=via_buy,
         overpay=overpay)
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
        _gain_now(game, d["pid"], d["card"], d["dest"], d.get("via_buy", False),
                  d.get("overpay", 0))


def gain_from_trash(game, pid, card, dest="discard"):
    """Gain a card OUT OF THE TRASH (Lurker, Graverobber, Rogue). It really is
    a gain — "When-gain abilities will trigger" (compendium, Graverobber 4) —
    so it emits like any other, and "it's possible to gain non-Kingdom cards
    from the trash". `dest` is the zone it lands in: Graverobber's is the
    DECK."""
    if card not in game["trash"]:
        return False
    game["trash"].remove(card)
    seat = game["seats"][pid]
    if dest == "deck":
        seat["deck"].insert(0, card)
    elif dest == "hand":
        seat["hand"].append(card)
    else:
        seat["discard"].append(card)
    if pid == game["turn"]:
        game.setdefault("_turn_gains", []).append(card)   # Smugglers
        if game["phase"] == "buy":
            game["turn_ctx"]["buy_gains"] += 1
            if has_type(game, card, "victory"):
                game["turn_ctx"]["gained_victory_in_buy"] = True
    _log(game, pid, "gain_from_trash", card=card, dest=dest)
    emit(game, "gain", actor=pid, subject=card, dest=dest, via_buy=False, overpay=0)
    return True


def from_trash(game, pid, card, dest="hand"):
    """Take a card out of the trash WITHOUT gaining it — Fortress' "when you
    trash this, put it into your hand" ("This is not gaining it. It was still
    trashed"), and Lich's discard later. Emits nothing, by that definition.
    False if the card is no longer in the trash (the lose-track case)."""
    if card not in game["trash"]:
        return False
    game["trash"].remove(card)
    seat = game["seats"][pid]
    if dest == "hand":
        seat["hand"].append(card)
    elif dest == "discard":
        seat["discard"].append(card)
    else:
        raise ValueError(f"bad from_trash dest {dest!r}")
    _log(game, pid, "from_trash", card=card, dest=dest)
    return True


def deck_to_discard(game, pid):
    """Put your whole deck into your discard pile (Scavenger). NOT a discard
    for trigger purposes — "this doesn't trigger cards that say WHEN YOU
    DISCARD THIS" — so it never goes through discard(). It does expose
    information (the bottom of the deck becomes the visible discard top), so it
    locks undo like any other reveal."""
    seat = game["seats"][pid]
    n = len(seat["deck"])
    if not n:
        return 0
    seat["discard"].extend(seat["deck"])
    seat["deck"] = []
    _mark_revealed(game)
    _log(game, pid, "deck_to_discard", count=n)
    return n


def exchange(game, pid, card, into, zone="discard"):
    """Return `card` to its pile and take `into` from ITS pile — Trader's 2020
    reaction. NOT a gain: "even if you exchanged it, you DID gain the card (and
    triggered any when-gain ability). You DIDN'T gain the Silver." So this
    emits nothing; a `gain` event here would double-fire every when-gain
    watcher on the card being handed back.

    "You return the card to its pile no matter where you gained it from. You
    place the Silver in your discard pile no matter where you gained the card
    to." Returns False if `into` is empty (nothing happens), if the card isn't
    where we expect (lose-track), or if it belongs to no pile we know — the
    last of which used to CREATE a pile keyed on the card's name."""
    if pile_top(game, into) is None:
        return False
    seat = game["seats"][pid]
    if card not in seat[zone]:
        return False                    # lost track of it; the exchange fails
    if pile_of(game, card) is None:
        return False                    # came from no pile; nothing to return to
    seat[zone].remove(card)
    _pile_return(game, card)
    got = _pile_take(game, into)
    seat["discard"].append(got)          # always the discard pile
    _log(game, pid, "exchange", card=card, into=got)
    return True


def shuffle_into_deck(game, pid, cards, zone="discard"):
    """Shuffle `cards` from a zone into the deck (Inn's on-gain). Shuffles the
    deck EVEN WHEN `cards` IS EMPTY — "if you shuffle zero cards into your
    deck, you still shuffle" — which matters because the shuffle itself
    randomises deck order."""
    seat = game["seats"][pid]
    for c in cards:
        seat[zone].remove(c)
    seat["deck"].extend(cards)
    rng = _make_rng(game)
    rng.shuffle(seat["deck"])
    _save_rng(game, rng)
    _mark_revealed(game)                 # deck order changed under the player
    _log(game, pid, "shuffle_into_deck", count=len(cards))
    return list(cards)


def trash(game, pid, cards, zone="hand"):
    seat = game["seats"][pid]
    for c in cards:
        seat[zone].remove(c)
        game["trash"].append(c)
    if cards:
        _log(game, pid, "trash", cards=list(cards))
        # same simultaneity rule as discard (the Steward ruling: "both cards
        # must be trashed simultaneously, and on-trash effects resolved
        # afterwards") — one pool per player across the batch. Dark Ages' seam.
        emit_batch(game, "trash", pid, cards)


def trash_from_supply(game, card):
    got = _pile_take(game, card)
    if got is None:
        return False
    game["trash"].append(got)
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
        # ONE batch, ONE pool: the cards were discarded simultaneously, so
        # their when-discard abilities are concurrent and the owner orders
        # them (Trail + Tunnel in one Militia discard) — never list order
        emit_batch(game, "discard", pid, cards, zone=zone)


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
    Patrol pockets victory cards, Sea Chart puts its match into hand, ...)."""
    seat = game["seats"][pid]
    for c in cards:
        seat["aside"].remove(c)
        if dest == "hand":
            seat["hand"].append(c)
        elif dest == "discard":
            seat["discard"].append(c)
        else:
            raise ValueError(f"bad take_aside dest {dest!r}")
    # A card entering the HAND is a visible effect the player wants logged —
    # Sea Chart's "put it into your hand", Wishing Well's match, Library's keep,
    # Patrol's pocketed Victory cards were all SILENT. Card names are per-field
    # redacted (owner-only pre-over), exactly like draw.
    if dest == "hand" and cards:
        _log(game, pid, "to_hand", count=len(cards), cards=list(cards))


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

# Actions/Buys/Coins are ONE set of counters, belonging to whoever's turn it
# is: "each turn always starts like this: your Action pool has 1 Action, your
# Buy pool has 1 Buy, and your money pool is empty" (compendium ch. II). So a
# bonus earned OFF-TURN — a reaction that plays itself, a when-gain trigger on
# an opponent's turn — has no pool to land in and is simply lost; the pools it
# would join are reset before that player next acts.
#
# `pid` is therefore not optional bookkeeping: without it these credited the
# CURRENT TURN PLAYER, i.e. an off-turn reaction handed its bonus to the
# attacker. Latent until a card grants resources off-turn (Hinterlands' Trail
# and Nomads are the first), and silently wrong the moment one does.
def _acting(game, pid=None):
    """WHO the resource is for. Card code says `add_actions(game, 2)` without a
    pid, so the kernel has to know: `_actor` is the player whose effect/stage is
    currently running, which is NOT always the turn player (a reaction that
    plays itself runs during an opponent's turn). Falls back to the turn player
    when nothing is running."""
    if pid is not None:
        return pid
    return game.get("_actor") or game["turn"]


def _grant(game, pid, key, n, log_key):
    if n == 0:
        return False
    pid = _acting(game, pid)
    if pid != game["turn"]:
        # earned on someone else's turn: no pool to add to
        _log(game, pid, "off_turn_bonus", **{log_key: n})
        return False
    game[key] += n
    if n > 0:
        _log(game, game["turn"], "plus", **{log_key: n})
    return True


def add_actions(game, n, pid=None):
    _grant(game, pid, "actions", n, "actions")


def add_buys(game, n, pid=None):
    _grant(game, pid, "buys", n, "buys")


def add_coins(game, n, pid=None):
    """n may be NEGATIVE (Souk deducts per card in hand). The money pool floors
    at $0 — "your money pool can never go below $0, but if you had any $ before
    playing Souk, you might lose more than $X when deducting"."""
    if n < 0:
        if _acting(game, pid) != game["turn"]:
            return
        game["coins"] = max(0, game["coins"] + n)
        _log(game, game["turn"], "minus", coins=-n)
        return
    _grant(game, pid, "coins", n, "coins")


def add_coffers(game, n, pid=None):
    """+x Coffers — Coin tokens onto a player's Coffers mat (Guilds/C&G).

    Deliberately NOT routed through _grant: the per-turn pools evaporate off
    turn because "on another player's turn you always start with empty pools",
    but Coffers are a MAT. They persist across turns by their whole nature, so
    a Coffers earned on someone else's turn is simply kept — the off-turn rule
    does not apply and applying it would silently eat the tokens."""
    if n == 0:
        return
    pid = _acting(game, pid)
    game["coffers"][pid] = game["coffers"].get(pid, 0) + n
    _log(game, pid, "coffers", n=n, total=game["coffers"][pid])


def spendable(game, pid):
    """What pid may spend right now, as {kind: count}. THE reader — legal_moves,
    the handler and the client all go through it (the manual_treasures lesson:
    an enumerator and a handler that disagree hand the bot a no-op move).

    Coffers are spendable "at any time during your turn" (the 2022 rules
    change; before, only the first part of the Buy phase). We additionally
    require no open decision — see the deviation note in CLAUDE.md."""
    if game["over"] or game["pending"] or pid != game["turn"]:
        return {}
    out = {}
    if game["coffers"].get(pid, 0) > 0:
        out["coffers"] = game["coffers"][pid]
    return out


def _h_spend(game, pid, move):
    """The generic spend move — one surface for every "spendable counter" the
    later sets add (Villagers ph. 9, Favors ph. 12, Debt payoff ph. 8), so each
    one is a registry entry rather than a new move type."""
    what = move.get("what")
    avail = spendable(game, pid)
    if what not in avail:
        return False, "nothing to spend"
    try:
        n = int(move.get("n", 1))
    except (TypeError, ValueError):
        return False, "bad amount"
    if not 1 <= n <= avail[what]:
        return False, f"you don't have {n} {what}"
    game["coffers"][pid] -= n
    _log(game, pid, "spend", what=what, n=n)
    add_coins(game, n, pid)
    return True, None


def add_potions(game, n, pid=None):
    """+Potions into the money pool. Same per-turn pool discipline as coins —
    a Potion produced on someone else's turn has no pool to land in."""
    _grant(game, pid, "potions", n, "potions")


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
    """The three-empty-piles game end counts SUPPLY piles only — a spent
    non-supply pile (Spoils, Horses) is not an empty Supply pile. Non-supply
    piles are already out of this dict, so this is the pre-3H code unchanged."""
    return sum(1 for v in game["supply"].values() if v == 0)


def types_of(game, card):
    """THE type query — card code must never read CARDS[x]["types"] directly
    for a rules decision. Game-wide type injections live here: Charlatan in
    the kingdom makes Curse also a Treasure for the whole game (2E rule).
    Accepts a PILE name too, resolving to the pile's face (an ordered pile is
    the type of its top card)."""
    card = _priced(game, card)
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
    card = _priced(game, card)
    if card == "Curse" and game["curse_is_treasure"]:
        return 1
    return CARDS[card]["coins"]


def cost(game, card):
    """THE single cost function — Bridge reduction applies everywhere, min 0.
    effects.COST_MODS is the while-in-play modifier seam (Quarry-class,
    Prosperity+): {source_card: fn(game, priced_name) -> reduction per copy},
    summed over every copy on ANY table (cost changes are global).

    Takes a card name or a PILE name: a pile costs what its face card costs
    (its top card, retained when the pile empties so the board keeps a price)."""
    card = _priced(game, card)
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


def potion_cost(game, card):
    """The POTION component of a cost (Alchemy) — the second dimension of the
    cost VECTOR. Cost reductions only ever touch the COIN component, so this is
    the printed value; Bridge does not make a Golem cost fewer Potions."""
    return cards_potion(_priced(game, card))


# THE COST VECTOR (compendium, POTIONS § IV). A cost is {coins, potions}: a
# printed cost of just {Potion} is {$0, 1P}, and a plain $3 is {$3, 0P}. Three
# rules follow, and they live HERE rather than in thirty batch call sites —
# which is the whole reason cost_le/cost_eq/cost_lt were introduced in ph. 2:
#
#   "up to $3"        -> coins <= 3 AND potions == 0
#   "exactly $1 more" -> "the same cost plus $1", so {$3,P} is exactly $1 more
#                        than {$2,P} but NOT than {$2}
#   "lower than"      -> no component higher and at least one lower, so {$4,P}
#                        and {$5} are INCOMPARABLE — neither is lower
#
# The number forms below are "…$N", which by the first rule means no Potion.
# When the reference is a CARD rather than a number, use the *_card forms —
# that is where the second and third rules actually bite.

def cost_le(game, card, coins):
    """'costing up to $coins' — the ONLY way card code may bound a cost against
    a number. A card with a Potion in its cost is NEVER "up to $N"."""
    return potion_cost(game, card) == 0 and cost(game, card) <= coins


def cost_eq(game, card, coins):
    """'costing exactly $coins' against a NUMBER (Stonemason's overpay). For
    "exactly $N more than THIS card", use cost_eq_card — the two differ the
    moment a Potion is involved."""
    return potion_cost(game, card) == 0 and cost(game, card) == coins


def cost_lt(game, card, coins):
    """'costing LESS than $coins'. Distinct from cost_le: "cheaper" excludes an
    equal cost. For "cheaper than THIS card", use cost_lt_card."""
    return potion_cost(game, card) == 0 and cost(game, card) < coins


def cost_ge(game, card, coins):
    """'costing $coins or MORE' — a LOWER bound, which reads the coin component
    alone. The Potion rule the other three enforce ("up to $N" excludes every
    Potion card) is a rule about UPPER bounds: a {$3,P} card is not "up to $3",
    but nothing about it is below $3 either, so Sage finds it. A range like
    Knights' "from $3 to $6" is written as cost_ge + cost_le, and the upper
    half is what (correctly) keeps the Potion cards out. Recorded as an open
    ambiguity in CLAUDE.md — the compendium states the rule for upper bounds
    only."""
    return cost(game, card) >= coins


def cost_eq_card(game, card, ref, delta=0):
    """'costing exactly $delta more than `ref`' — Remake, Upgrade, Develop,
    Farmland, Swindler (delta 0). "Costing exactly $1 more" means "having the
    same cost plus $1", so the POTION component must MATCH."""
    return (potion_cost(game, card) == potion_cost(game, ref)
            and cost(game, card) == cost(game, ref) + delta)


def cost_le_card(game, card, ref, delta=0):
    """'costing up to $delta more than `ref`' — Remodel, Expand, Butcher.
    "Up to $2 more than {$3,P}" means "up to {$5,P}": the potion component may
    not be HIGHER than the reference's."""
    return (potion_cost(game, card) <= potion_cost(game, ref)
            and cost(game, card) <= cost(game, ref) + delta)


def cost_lt_card(game, card, ref):
    """'a cheaper card than `ref`' — Border Village, Berserker, Haggler,
    Stonemason. A vector is LOWER only if no component is higher and at least
    one is lower, so {$4,P} is not cheaper than {$5} (nor the reverse)."""
    c1, p1 = cost(game, card), potion_cost(game, card)
    c2, p2 = cost(game, ref), potion_cost(game, ref)
    return c1 <= c2 and p1 <= p2 and (c1 < c2 or p1 < p2)


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
                immune=None, commutes=False):
    """Register a cross-player trigger. events: "gain" (any player gains),
    "play_treasure" (any treasure play), "protect" (Lighthouse — no stage, the
    attack wrap consults it). until: "owner_turn_start" (default, the Duration
    contract) or "turn_end" (this-turn triggers like Sailor's). The stage runs
    as an auto frame with data + {"actor", "subject", "owner"} when fired.
    immune: explicit per-play immunity override for watchers registered from a
    LATER stage of an attack play (Blockade) — by default the current play's
    _atk_immune transient is captured.
    commutes: this watcher's stage is decision-free AND order-independent
    (Collection's +1 VP) — the ability pool auto-runs it instead of offering
    it in the what-resolves-first prompt. Declare it only when resolving the
    stage can never change what any other pending ability does."""
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
                             **({"commutes": True} if commutes else {}),
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


def set_aside(game, pid, cards, zone="hand", until=None):
    """Move cards to pid's own SET-ASIDE zone — Farmhands' "set aside an Action
    or Treasure from your hand". Distinct from Seaside's `dur_aside`, which
    hangs off a Duration entry on the table: this one belongs to the seat and
    outlives any card in play (the Farmhands itself goes to the discard).

    `until="cleanup"` sets the card aside only for THIS turn — Joust's "discard
    the Province in Clean-up". Both zones are set-aside rather than in play, so
    nothing there counts for Horn of Plenty or Shop; they differ only in who
    takes the card back and when."""
    dest = "cleanup_aside" if until == "cleanup" else "set_aside"
    seat = game["seats"][pid]
    for c in cards:
        seat[zone].remove(c)
        seat[dest].append(c)
    if cards:
        _mark_revealed(game)             # the owner learns where a card went
        _log(game, pid, "set_aside", count=len(cards), private_to=[pid],
             cards=list(cards))
    return list(cards)


def take_set_aside(game, pid, cards, dest="hand"):
    seat = game["seats"][pid]
    taken = []
    for c in cards:
        if c in seat["set_aside"]:
            seat["set_aside"].remove(c)
            taken.append(c)
    if dest is not None:
        seat[dest].extend(taken)
    return taken


def add_start_fx(game, pid, card, stage, data=None):
    """Register an ability that resolves at the START of pid's next turn, with
    no Duration on the table to hang it off (Farmhands sets one up from its
    when-gain, and can do it on an OPPONENT's turn). It joins the same ability
    pool as the duration fx and the turn_start reactions, so the player orders
    all of them together — they are simultaneous."""
    game["seats"][pid]["start_fx"].append(
        {"card": card, "stage": stage, "data": data or {}})


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

# How a from="hand" reaction (or an attack-window reaction) SHOWS ITSELF, by
# the spec's `mode`. It is the card's own instruction: Watchtower reveals,
# Guard Dog plays itself, Market Square discards itself, Hovel trashes itself.
# The stage still performs the move — this only names it in the prompt.
_REACT_VERB = {"reveal": "Reveal", "play": "Play",
               "discard": "Discard", "trash": "Trash"}


def emit(game, event, actor=None, subject=None, **extra):
    """Fire an event AFTER the triggering change has been applied.

    ONE occurrence can hand a player several abilities — the gained card's own
    when-gain, a reaction in hand, a standing watcher. Each player's consumers
    are collected into ONE ability pool (p23 §2: THE PLAYER picks what resolves
    first, re-offered after each), and the pools are pushed in reversed turn
    order so the current player's resolves first, then each other player's in
    turn order (p23 §3 — cross-player order is NOT a choice)."""
    pools = {}
    _emit_collect(game, pools, event, actor, subject, **extra)
    _park_pools(game, pools)


def emit_batch(game, event, actor, subjects, **extra):
    """One SIMULTANEOUS batch — a multi-card discard or trash. The cards moved
    at once ("unless that effect is explicitly sequential, they are discarded
    at the same time"), so every card's consumers trigger together and land in
    ONE pool per player: with Trail + Tunnel discarded to a Militia, their
    owner picks which reacts first. Per-card emit() here would order them by
    LIST position instead — the pre-phase-3 accident (ledger B4) where the
    order came from the player's clicks in the discard picker, reversed.
    Gains stay per-emit on purpose: those resolve one at a time by rule."""
    pools = {}
    for subject in subjects:
        _emit_collect(game, pools, event, actor, subject, **extra)
    _park_pools(game, pools)


def _park_pools(game, pools):
    order = game["players"]
    i = order.index(game["turn"]) if game["turn"] in order else 0
    for p in reversed(order[i:] + order[:i]):
        if p in pools:
            park_abilities(game, p, [a for bucket in pools[p] for a in bucket])


def _emit_collect(game, pools, event, actor=None, subject=None, **extra):
    """Collect one occurrence's consumers into per-player pools.

    Trigger conditions (in hand? in play? `when`?) are evaluated HERE, at the
    occurrence (p25 §3); the deferred runners re-check only card PRESENCE at
    resolution (the lose-track rule) and log `lost_track` when it fails.

    Bucket order inside a pool = self, in_play, hand, watchers — the exact pop
    order of the pre-pool fixed-order engine, so the FIRST option is always the
    historical default and a single consumer behaves byte-identically."""
    ctx = {"actor": actor, "subject": subject, **extra}

    def add(pid, bucket, card, stage, data, commutes=False):
        d = {"card": card, "stage": stage, "data": data}
        if commutes:
            d["commutes"] = True     # decision-free + order-independent: the
        pools.setdefault(pid, ([], [], [], []))[bucket].append(d)   # pool auto-runs it

    from . import effects
    for card, specs in getattr(effects, "TRIGGERS", {}).items():
        for si, spec in enumerate(specs):
            if spec["on"] != event:
                continue
            src = spec.get("from", "hand")
            when = spec.get("when")
            if src == "self":
                if subject == card and (when is None or when(game, actor, ctx)):
                    # **extra carries the emit's context (gain's via_buy/dest,
                    # discard's zone) — actor/subject stay authoritative.
                    add(actor, 0, card, spec["stage"],
                        {**extra, "actor": actor, "subject": subject},
                        commutes=spec.get("commutes", False))
            elif src == "in_play":
                if actor is not None and card in game["seats"][actor]["in_play"] \
                        and (when is None or when(game, actor, ctx)):
                    # deferred: the pool may resolve other abilities first, so
                    # the push runs via __inplay_push, which re-finds THIS spec
                    # (by index) and re-checks the card is still on the table
                    add(actor, 1, card, "__inplay_push",
                        {"event": event, "spec": si, "ctx": ctx})
            elif src == "game":
                # A GAME-WIDE rule: "in games using this, ..." (Footpad). It
                # binds every player whether or not anyone owns a copy, so the
                # test is the SUPPLY, not a zone — the same shape as
                # Charlatan's Curse rule, but on the trigger bus rather than a
                # game-dict flag, because this one has to resolve in order with
                # the other abilities the same gain triggered.
                #
                # `supply`, not `kingdom`: a set-up EXTRA pile (Young Witch's
                # Bane) is in the game without being one of the dealt 10, and
                # "in games using this" plainly covers it.
                if actor is not None and card in game["supply"] \
                        and (when is None or when(game, actor, ctx)):
                    add(actor, 0, card, spec["stage"],
                        {**extra, "actor": actor, "subject": subject},
                        commutes=spec.get("commutes", False))
            elif src == "hand":
                verb = _REACT_VERB.get(spec.get("mode"), "Play")
                for p in game["players"]:
                    if spec.get("who") == "actor" and p != actor:
                        continue          # when-YOU-x reactions (Watchtower-class)
                    if card in game["seats"][p]["hand"] and (when is None or when(game, p, ctx)):
                        add(p, 2, card, "__offer_window",
                            {"stage": spec["stage"], "verb": verb,
                             "extra": {**extra, "gained": subject, "gainer": actor}})
    whens = getattr(effects, "WATCHER_WHENS", {})
    for w in list(game["watchers"]):
        if w["event"] != event or not w.get("stage"):
            continue
        if actor is not None and actor in w.get("immune", []):
            continue          # immune to the attack PLAY that set this watcher
        # a watcher whose ability would no-op for THIS occurrence (Monkey on
        # anyone but the right-hand neighbour) never joins the pool — a prompt
        # ordering a no-op against a real ability is worse than noise, it
        # implies the no-op will do something
        when = whens.get((w["card"], w["stage"]))
        if when is not None and not when(game, w, ctx):
            continue
        add(w["owner"], 3, w["card"], w["stage"],
            {**w["data"], **extra, "actor": actor, "subject": subject,
             "owner": w["owner"]}, commutes=w.get("commutes", False))


def _k_offer_window(game, pid, frame, choice):
    """Deferred hand-reaction window (a pooled `from:"hand"` trigger). The card
    was in hand at the OCCURRENCE; by the time the player picks this ability an
    earlier pick may have moved it — lose track, and say so."""
    card, d = frame["card"], frame["data"]
    if card not in game["seats"][pid]["hand"]:
        lost_track(game, pid, card, f"{d['verb'].lower()}ed")
        return
    push_choose_option(game, pid, card, d["stage"],
                       options=[{"id": "play",
                                 "label": f"{d['verb']} {card} from your hand"},
                                {"id": "decline", "label": "Don't react"}],
                       data=d["extra"])


def _k_inplay_push(game, pid, frame, choice):
    """Deferred `from:"in_play"` trigger: re-find the registered spec (by index
    — frames are short-lived, so a registry reorder across a deploy is the only
    hazard, accepted) and run its push if the card is still on the table."""
    from . import effects
    card, d = frame["card"], frame["data"]
    if card not in game["seats"][pid]["in_play"]:
        lost_track(game, pid, card)
        return
    effects.TRIGGERS[card][d["spec"]]["push"](game, pid, d["ctx"])


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


# --- concurrent-ability ordering (compendium p23 §2) ---------------------------
# "When a player has several concurrent abilities to resolve, they choose which
# to resolve first. After resolving it, they choose which to resolve next."
# The pool is that rule's shape: pick ONE, resolve it FULLY (its frames stack on
# top — atomicity for free), then the remainder pool re-surfaces and re-offers.
# Sequential re-offer, NEVER an order-the-list-up-front prompt: later picks may
# react to what earlier resolutions revealed, abilities that died mid-window
# drop out, and interleaving (p24 §3) falls out naturally.
#
# CONTRACT: any code path that would push >=2 same-player frames from ONE
# triggering occurrence must route them through park_abilities. One ability
# skips every prompt and behaves exactly like a direct push.

# (card, stage) pairs whose COPIES must not collapse into one option. Empty
# today, deliberately: every shipped duplicate is interchangeable (two Tide
# Pools, a throne-roomed Caravan's two draws, two Havens each returning their
# own set-aside), so offering "which copy first?" would be pure noise. A future
# card whose copies genuinely differ adds its pair here — and a ledger row.
ORDER_MATTERS = set()


def park_abilities(game, pid, abilities):
    """Queue same-player abilities born of one occurrence.
    abilities = [{"card", "stage", "data"}] in the order they would have
    resolved historically — the order a no-prompt collapse preserves."""
    if not abilities:
        return
    push_auto(game, pid, "__abilities", "pool", data={"abilities": list(abilities)})


def _pool_groups(abilities):
    """[(key, [indices])] in first-appearance order; interchangeable copies
    share a group (one option), ORDER_MATTERS pairs get one group each."""
    groups, by_key = [], {}
    for i, a in enumerate(abilities):
        key = (a["card"], a["stage"])
        if key in ORDER_MATTERS:
            key = (a["card"], a["stage"], i)
        if key not in by_key:
            by_key[key] = []
            groups.append((key, by_key[key]))
        by_key[key].append(i)
    return groups


def _k_ability_pool(game, pid, frame, choice):
    abilities = frame["data"]["abilities"]
    # An ability marked "commutes" is decision-free AND order-independent
    # (Collection's +1 VP, Nomads' +$2): resolving it never changes what any
    # other pending ability does, so offering it in the prompt is pure noise —
    # it runs automatically, first, and never spends the player's choice.
    # The marker is declared at REGISTRATION (spec/add_watcher), never inferred.
    auto = [a for a in abilities if a.get("commutes")]
    rest = [a for a in abilities if not a.get("commutes")]
    groups = _pool_groups(rest)
    if len(groups) <= 1:
        # no real choice — run everything, first-parked first (reversed push:
        # the stack pops last-pushed first). Two Tide Pools never prompt.
        for a in reversed(rest):
            push_auto(game, pid, a["card"], a["stage"], data=a["data"])
    else:
        names = [k[0] for k, _ in groups]
        options = []
        for key, idxs in groups:
            label = key[0]
            if names.count(key[0]) > 1:             # same card, different stage
                label += f" ({rest[idxs[0]]['stage']})"
            if len(idxs) > 1:
                label += f" ×{len(idxs)}"           # "Tide Pools ×2"
            options.append({"id": str(idxs[0]), "label": label})
        push_choose_option(game, pid, "__abilities", "pick", options=options,
                           pick=1, data={"abilities": rest})
    for a in reversed(auto):                        # on top: commuters run first
        push_auto(game, pid, a["card"], a["stage"], data=a["data"])


def _k_ability_pick(game, pid, frame, choice):
    abilities = frame["data"]["abilities"]
    i = int(choice["ids"][0])                       # ids validated vs options
    chosen = abilities[i]
    rest = abilities[:i] + abilities[i + 1:]
    if rest:
        # remainder BELOW the chosen ability: it re-surfaces (and re-groups)
        # only after the chosen one has fully resolved
        push_auto(game, pid, "__abilities", "pool", data={"abilities": rest})
    push_auto(game, pid, chosen["card"], chosen["stage"], data=chosen["data"])


def _start_of_turn(game, pid):
    """Resolve pid's duration entries: park their fx as ONE ability pool (the
    player picks what resolves first when the cards differ — p23 §2), expire
    pid's watchers, mark entries done.
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
    game["watchers"] = [w for w in game["watchers"] if w["owner"] != pid]
    # ONE concurrent set (phase 4): pid's duration fx AND every turn_start
    # consumer (Clerk's own-turn hand reaction; any future turn_start watcher)
    # pool together — "the start of turn is considered to be part of the
    # Action phase" and all its abilities are simultaneous, so a Wharf and a
    # Clerk in hand are the player's ordering choice, not the engine's. Also
    # fixes the cross-player order: pools park current-player-FIRST (p23 §3),
    # where the old separate emit made reactions cut ahead of the fx.
    # ...and the seat-level start-of-turn abilities (Farmhands), which have no
    # Duration on the table to hang off but are just as simultaneous
    for fx in seat["start_fx"]:
        fx_batch.append((fx["card"], fx))
    seat["start_fx"] = []
    pools = {}
    for card, fx in fx_batch:
        pools.setdefault(pid, ([], [], [], []))[0].append(
            {"card": card, "stage": fx["stage"], "data": dict(fx["data"])})
    _emit_collect(game, pools, "turn_start", actor=pid)
    _park_pools(game, pools)


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

def discard_then_putback(game, pid, card, chosen, rest, zone="aside"):
    """THE look-at-cards / discard-some / put-the-rest-back shape (Sentry,
    Lookout, Rabble, Cartographer).

    Order is load-bearing and easy to get backwards: the put-back is pushed
    FIRST so it sits BELOW the discard's when-discard triggers, which the
    discard then pushes on top of it. Compendium, Sentry: "See TRIGGERED
    ABILITY (first trash, then discard, THEN PUT CARDS BACK)", and p54: the
    kept cards "are kept aside… this matters if, for example, discarding or
    trashing triggers an ability that lets you draw."

    Pushing the put-back last (the obvious reading of LIFO) returned the kept
    cards to the deck BEFORE a discarded Tunnel/Trail/Weaver could react — and
    a Trail's +1 Card then drew a card the player had never been allowed to
    see. Four cards had their own copy of this ordering; now they share one.
    """
    if len(rest) >= 2:
        push_order_cards(game, pid, card, "__putback_order", cards=list(rest))
    elif rest:
        push_auto(game, pid, card, "__putback", data={"rest": list(rest)})
    if chosen:
        discard(game, pid, chosen, zone=zone, public=True)


def _k_putback(game, pid, frame, choice):
    deck_from_aside(game, pid, frame["data"]["rest"])


def _k_putback_order(game, pid, frame, choice):
    deck_from_aside(game, pid, choice["order"])     # order[0] ends up on top


def persisting_in_play(game, pid):
    """Cards on pid's table that will NOT be discarded at this clean-up — the
    duration setups about to be promoted, plus their riders. THE reader of
    _cleanup_durations' keep-out rule, so card code never re-derives it."""
    kept = []
    for e in game["seats"][pid].get("dur_setup", []):
        if (e["fx"] or e["watchers"]) and not e.get("fired"):
            kept.append(e["card"])
            kept.extend(e.get("riders", []))
    return kept


def _in_play_leaving(game, pid):
    """The in_play copies this clean-up will actually discard — in_play minus
    the setups being promoted. A MULTISET subtraction, because zones hold
    NAMES: a seat can hold a finishing Tide Pools and a freshly played one at
    the same time, and only the count tells the two copies apart."""
    out = list(game["seats"][pid]["in_play"])
    for name in persisting_in_play(game, pid):
        if name in out:
            out.remove(name)
    return out


def leaving_play(game, pid):
    """Everything that WILL be discarded from pid's table at this clean-up.

    Not just `in_play`: a Duration whose last ability has resolved sits in the
    `duration` zone marked done and is discarded from play by THIS clean-up, so
    it is every bit as much "discarded from play" as a card in in_play. Scheme
    may target it, and looking only at in_play silently hid finishing Durations
    (and their Throne-Room riders) from the offer."""
    out = _in_play_leaving(game, pid)
    for e in game["seats"][pid]["duration"]:
        if e.get("done"):
            out.append(e["card"])
            out.extend(e.get("riders", []))
    return out


def topdeck_from_play(game, pid, card):
    """Topdeck a card that is leaving play this clean-up, wherever it sits —
    in_play, or a finished duration entry (its own card or one of its riders).
    Returns False if it isn't actually there (lose-track)."""
    seat = game["seats"][pid]
    # NOT `card in seat["in_play"]`: a Duration played THIS turn also sits in
    # in_play and is not leaving, so with two copies of one Duration on the
    # table — one finishing, one just played — a name match takes the wrong
    # one. The persisting copy then vanishes from under _cleanup_durations,
    # whose kept-out removal is unguarded, and _end_turn raised ValueError.
    if card in _in_play_leaving(game, pid):
        topdeck(game, pid, card, zone="in_play", public=True)
        return True
    for e in seat["duration"]:
        if not e.get("done"):
            continue
        if e["card"] == card:
            seat["duration"].remove(e)
            seat["deck"].insert(0, card)
            # riders lose their host and discard normally
            seat["discard"].extend(e.get("riders", []))
            _log(game, pid, "topdeck", card=card)
            return True
        if card in e.get("riders", []):
            e["riders"].remove(card)
            seat["deck"].insert(0, card)
            _log(game, pid, "topdeck", card=card)
            return True
    return False


def find_card_zone(game, pid, card, zones=("discard", "hand", "trash")):
    """Where is `card` right now — or None if it has MOVED (the lose-track
    rule). A when-gain/trash/discard reaction fires after the card landed, but
    another ability may have moved it in between; "cards that are lost track of
    can't be played" (2021 expanded rule). Card code must ask this rather than
    assume the zone it expects, or it will remove() a card that isn't there."""
    seat = game["seats"][pid]
    for z in zones:
        pile = game["trash"] if z == "trash" else seat.get(z)
        if pile and card in pile:
            return z
    return None


def lost_track(game, pid, card, verb=None, why=None):
    """LOG that an ability was skipped because its card moved.

    **Every lose-track guard that silently returns owes one of these.** The
    ability not happening is correct; happening in SILENCE is not — a prompt
    that never opens is indistinguishable from a trigger that failed to fire,
    which is exactly how a real game (two Trails discarded, the first one's
    draw shuffling the second back into the deck) got reported as a bug. The
    player cannot see the zone the rule is talking about, so the engine has to
    say it.

    `verb` is what can't happen to it — "played", "revealed"; omit it where the
    ability isn't one word (Watchtower's trash-or-topdeck) and the client says
    "the ability is skipped" instead. `why` overrides the default "it moved"
    for the cases that aren't literally a move — Sailor's gained Duration
    landing somewhere it was never playable from."""
    extra = {}
    if verb:
        extra["verb"] = verb
    if why:
        extra["why"] = why
    _log(game, pid, "lost_track", card=card, **extra)


def play_action_card(game, pid, card, from_zone="hand", count=True):
    """Move the card to in_play (from_zone=None for throne-room replays), count the
    play, and run its effect. Attack-typed plays are wrapped: reaction windows for
    every opponent holding an eligible Reaction resolve BEFORE the play ability
    (official timing), with per-play immunity collected in the play_ability frame.
    count=False for off-turn reaction plays (Pirate) — they must not pollute the
    turn player's actions_played counter."""
    seat = game["seats"][pid]
    if from_zone is not None:
        # "trash" is the shared public pile, not a seat zone — Trail reacts to
        # being TRASHED and plays itself from there.
        src = game["trash"] if from_zone == "trash" else seat[from_zone]
        src.remove(card)
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
        _open_attack_window(game, pid, card)
        _emit_play_attack(game, pid, card, replay=from_zone is None)
    else:
        from . import effects as _fx
        fn = _fx.EFFECTS.get(card)
        if fn is None and not has_type(game, card, "treasure"):
            raise KeyError(f"dontminion: no effect registered for {card!r}")
        if fn is not None:
            prev = game.get("_actor")
            game["_actor"] = pid            # see _acting: off-turn plays exist
            _push_depth(game)
            try:
                fn(game, pid)
            finally:
                _pop_depth(game)
                if prev is None:
                    game.pop("_actor", None)
                else:
                    game["_actor"] = prev
        if has_type(game, card, "treasure"):
            emit(game, "play_treasure", actor=pid, subject=card)


def _emit_play_attack(game, pid, card, replay=False):
    """The BEFORE-PLAY window for an Attack (Urchin's "when you play another
    Attack card with this in play, you may first trash this").

    Emitted AFTER _open_attack_window on purpose: pushes are LIFO, so the
    ability pool this parks sits ABOVE the opponents' reaction windows and
    resolves first — which is what "you may FIRST trash this" means, and what
    the compendium's Skirmisher example needs ("you gain a Mercenary before
    resolving the played Attack, so Skirmisher's when-gain ability is not
    active yet").

    `replay` marks a throne-room replay of a card already in play: "the
    before-play ability only triggers if you play ANOTHER Attack card, not if
    you play the same Urchin multiple times with a throne-room"."""
    emit(game, "play_attack", actor=pid, subject=card, replay=replay)


def playable_from_supply(game, pid, pred=None):
    """Supply piles whose TOP CARD a Command card may play. Only the top card
    of a pile is choosable ("you can only choose a card that is currently on
    top of a Supply pile"), which is why this asks pile_top rather than reading
    the pile name — ph. 3H's ordered piles make the two differ."""
    out = []
    for name in sorted(game["supply"]):
        top = pile_top(game, name)
        if top is None or not command_may_play(game, top):
            continue
        if pred is not None and not pred(name):
            continue
        out.append(name)
    return out


def command_may_play(game, card):
    """Can a Command card play this? Two exclusions, both from the current
    card texts rather than the original ones:

      * NOT another Command card — "this is to prevent loops from occurring".
      * NOT a Duration (the 2025 change). Before it, playing one directly was
        allowed and its later ability stopped after this turn.
    """
    return (has_type(game, card, "action")
            and not has_type(game, card, "command")
            and not has_type(game, card, "duration"))


def play_from_supply(game, pid, pile, count=True):
    """PLAY A CARD WHILE LEAVING IT — run the play ability of a Supply pile's
    top card with the card never moving: it stays on its pile, and the Command
    card that played it is the one in play.

    This is what the CURRENT Band of Misfits and Overlord do, and what
    Inheritance's Estates do ("play the card with your Estate token, leaving it
    there"). It is deliberately NOT a "play this card AS that one": the 2019
    errata retired that reading — "unlike the first version, this version does
    not change itself to another card, nor does it play itself. Instead it
    PLAYS AN ACTION CARD from the Supply."

    Returns False if the pile's top card is not something a Command card may
    play, so the caller can offer the choice without pre-filtering twice."""
    card = pile_top(game, pile)
    if card is None or not command_may_play(game, card):
        return False
    _log(game, pid, "play_from_supply", card=card, pile=pile)
    if count:
        game["turn_ctx"]["actions_played"] += 1
    if has_type(game, card, "attack"):
        # _open_attack_window ALREADY parks the play ability under the reaction
        # windows, so this path needs no continuation of its own — adding one
        # ran the attack twice. Same machinery as an Attack played from hand,
        # which is the point: an attack is an attack however it reached play.
        _open_attack_window(game, pid, card)
        _emit_play_attack(game, pid, card)
        return True
    _run_supply_ability(game, pid, card)
    return True


def _run_supply_ability(game, pid, card):
    from . import effects
    fn = effects.EFFECTS.get(card)
    if fn is None:
        return
    prev = game.get("_actor")
    game["_actor"] = pid
    _push_depth(game)
    try:
        fn(game, pid)
    finally:
        _pop_depth(game)
        if prev is None:
            game.pop("_actor", None)
        else:
            game["_actor"] = prev


def attack_reactions():
    """THE registry of cards that react to an Attack being played, merged from
    the effects modules. Was hardcoded to Moat + Diplomat in the kernel, which
    made every new reaction a kernel edit. Entry shape:

        {"label": str,
         "when":  fn(game, pid) -> bool | None,   # beyond "it's in your hand"
         "immunity": bool,                        # Moat: unaffected by this play
         "mode": "reveal" | "play",               # play = it plays ITSELF (p53)
         "stage": str | None,                     # STAGES[(card, stage)] to run
         "repeatable": bool}                      # may react again with a copy
    """
    from . import effects
    return getattr(effects, "ATTACK_REACTIONS", {})


def _reaction_options(game, o, immune, used=()):
    """Options for one opponent's reaction window. `used` is what this player
    already reacted with against THIS attack play — a non-repeatable reaction
    isn't offered twice (you can't Moat the same attack again), while a
    repeatable one is (the compendium allows several Guard Dogs per attack)."""
    hand = game["seats"][o]["hand"]
    opts = []
    for card, spec in sorted(attack_reactions().items()):
        if card not in hand:
            continue
        if card in used and not spec.get("repeatable"):
            continue
        if spec.get("immunity") and o in immune:
            continue                     # already unaffected; nothing to gain
        when = spec.get("when")
        if when is not None and not when(game, o):
            continue
        verb = _REACT_VERB.get(spec.get("mode"), "Reveal")
        opts.append({"id": f"react:{card}",
                     "label": spec.get("label") or f"{verb} {card}"})
    if opts:
        opts.append({"id": "decline", "label": "Don't react"})
    return opts


def _open_attack_window(game, pid, card):
    """Park the attack's play ability and offer every eligible opponent their
    reaction window FIRST — the compendium's timing: reactions resolve when the
    Attack is PLAYED, before its ability does anything.

    Shared by the Action and TREASURE play paths; an attack is an attack
    whichever way it reached the table (Cauldron is an Attack Treasure)."""
    # Lighthouse protection (until-their-next-turn watcher) = unaffected,
    # no window needed (public, so it's logged rather than asked)
    immune0 = [o for o in opponents(game, pid) if attack_protected(game, o)]
    for o in immune0:
        _log(game, o, "lighthouse")
    push_auto(game, pid, "__attack", "play_ability",
              data={"card": card, "immune": list(immune0)})
    for o in reversed(opponents(game, pid)):
        # An ALREADY-PROTECTED player still gets the window: "it triggers
        # whenever an Attack card is played, no matter if the card would have
        # any effect on you" (p53). Skipping them cost a Lighthouse-protected
        # Guard Dog holder its +2/+4 Cards on every attack — Guard Dog is pure
        # upside and grants no immunity of its own. Passing immune0 keeps the
        # pointless options out: _reaction_options drops an immunity-granting
        # reaction (Moat) for someone already unaffected, so a protected player
        # holding only a Moat is still offered nothing.
        opts = _reaction_options(game, o, immune=immune0)
        if opts:
            _push_window(game, o, opts)


def _push_window(game, o, opts):
    push_choose_option(game, o, "__attack", "window", options=opts, pick=1)


def reopen_attack_window(game, pid):
    """Re-offer the current attack's window to pid — for a reaction whose own
    stage pushed frames (Diplomat's discard, Guard Dog's play) and must let the
    player react again afterwards. Safe to call when no attack is open."""
    atk = _current_attack_frame(game)
    if atk is None:
        return
    used = atk["data"].setdefault("used", {}).get(pid, [])
    opts = _reaction_options(game, pid, atk["data"]["immune"], used)
    if opts:
        _push_window(game, pid, opts)


def _current_attack_frame(game):
    for f in reversed(game["pending"]):
        if f["card"] == "__attack" and f["stage"] == "play_ability":
            return f
    return None


# Option ids the window used before the registry (they are PERSISTED inside an
# open frame, so a game paused on an attack window survives a deploy holding
# one). Compatibility only — delete once no live save can carry them.
_LEGACY_REACTION_IDS = {"reveal_moat": "Moat", "reveal_diplomat": "Diplomat"}


def _k_window(game, pid, frame, choice):
    cid = choice["ids"][0]
    if cid == "decline":
        return
    if cid in _LEGACY_REACTION_IDS:
        card = _LEGACY_REACTION_IDS[cid]
    elif ":" in cid:
        card = cid.split(":", 1)[1]
    else:
        return
    spec = attack_reactions().get(card)
    if spec is None:
        return
    atk = _current_attack_frame(game)
    if atk is not None:
        atk["data"].setdefault("used", {}).setdefault(pid, []).append(card)
        if spec.get("immunity") and pid not in atk["data"]["immune"]:
            atk["data"]["immune"].append(pid)

    if spec.get("mode") == "play":
        # REACTION THAT PLAYS ITSELF (compendium p53): "this doesn't use up an
        # Action from your Action pool. You discard the card in THAT TURN'S
        # Clean-up phase" — i.e. the attacker's, which is why clean-up has to
        # sweep every seat's in_play, not just the turn player's.
        # count only on your OWN turn: an opponent's reaction must not bump the
        # turn player's actions_played (Conspirator counts ACTIONS YOU played).
        play_action_card(game, pid, card, from_zone="hand",
                         count=(pid == game["turn"]))
    elif spec.get("mode") == "discard":
        # "you may first DISCARD this to ..." (Beggar). The card leaves the
        # hand as the cost of reacting, which is also why a second copy is
        # offered again without `repeatable` doing any work for the first one.
        discard(game, pid, [card])
    else:
        reveal(game, pid, [card], "hand")

    stage = spec.get("stage")
    if stage is not None:
        _run_stage(game, card, stage, pid, frame, None)
        return          # the stage re-opens the window itself once it's done
    reopen_attack_window(game, pid)


def _k_legacy_diplomat_discard(game, pid, frame, choice):
    """Resolves a Diplomat discard frame written by the pre-registry kernel."""
    discard(game, pid, choice["cards"])
    reopen_attack_window(game, pid)


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
    # "*" = a kernel stage any card may push (see _stage_fn)
    ("*", "__putback"): _k_putback,
    ("*", "__putback_order"): _k_putback_order,
    ("__attack", "window"): _k_window,
    # legacy stage: a game paused mid-Diplomat across the deploy still holds a
    # frame naming it. Compatibility only — delete with _LEGACY_REACTION_IDS.
    ("__attack", "diplomat_discard"): _k_legacy_diplomat_discard,
    ("__attack", "play_ability"): _k_play_ability,
    ("__attack", "next"): _k_next,
    # ("__turn", "finish") registers below its definition
}


# --- turn-move handlers ------------------------------------------------------

def _fresh_turn_ctx():
    return {"bridges": 0, "actions_played": 0, "merchants": 0,
            "silver_played": False, "bought": False,
            # C&G: cards GAINED in this Buy phase (Merchant Guild counts all
            # gains, not just buys, and counts ones from before it was played)
            # and cards owed at the end of the turn (Farrier's overpay).
            "buy_gains": 0, "end_draw": 0}


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
    if card == "Potion":
        # "When you play a Potion, it produces a Potion (instead of $, like
        # other Treasures do), which is added to your money pool."
        add_potions(game, 1, pid)
        return
    game["coins"] += coins_of(game, card)
    if card == "Silver" and not game["turn_ctx"]["silver_played"]:
        game["turn_ctx"]["silver_played"] = True
        m = game["turn_ctx"]["merchants"]
        if m:
            game["coins"] += m
            _log(game, pid, "plus", coins=m, why="Merchant")


def play_treasure_card(game, pid, card, from_zone="hand"):
    """Play a Treasure from somewhere other than the ordinary buy-phase flow —
    Coronet plays one twice, Farmhands plays a set-aside one at the start of a
    turn. `from_zone=None` replays a Treasure already in play (the throne-room
    shape), running its ability and its coins again without moving it."""
    return _play_one_treasure(game, pid, card, from_zone)


def _play_one_treasure(game, pid, card, from_zone="hand"):
    from . import effects
    seat = game["seats"][pid]
    if from_zone is not None:
        seat[from_zone].remove(card)
        seat["in_play"].append(card)
    game["_cur_dur"] = None
    if has_type(game, card, "duration"):
        _dur_setup_list(game, pid).append({"card": card, "fx": [], "watchers": 0, "riders": []})
        game["_cur_dur"] = [pid, len(_dur_setup_list(game, pid)) - 1]
    _log(game, pid, "play", card=card, coins=coins_of(game, card))
    _treasure_coins(game, pid, card)
    if has_type(game, card, "attack"):
        # An ATTACK-typed Treasure (Cauldron) opens the reaction window exactly
        # like an Attack Action: the compendium's reaction window "triggers
        # whenever an Attack card is PLAYED". This path never wrapped attacks,
        # so `_atk_immune` was never set and a watcher registered from the play
        # captured an EMPTY immune list — i.e. the attack would have been
        # unblockable by Moat, silently.
        _open_attack_window(game, pid, card)
        _emit_play_attack(game, pid, card, replay=from_zone is None)
        emit(game, "play_treasure", actor=pid, subject=card)
        return
    # treasures with abilities (Astrolabe's duration half) run their effect too
    fn = effects.EFFECTS.get(card)
    if fn is not None:
        prev = game.get("_actor")
        game["_actor"] = pid
        _push_depth(game)
        try:
            fn(game, pid)
        finally:
            _pop_depth(game)
            if prev is None:
                game.pop("_actor", None)
            else:
                game["_actor"] = prev
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
    # `supply` is the index of BUYABLE piles, so a non-supply pile (Spoils,
    # Horses, Rewards) fails here without needing its own check — the only
    # way to those is gain_from().
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
    p = potion_cost(game, card)
    if p > game["potions"]:
        return False, "not enough Potions"
    # you buy a PILE and get its top card — the same for every pile we ship
    # today, and the distinction an ordered pile (Knights, Castles) needs
    got = pile_top(game, card)
    game["coins"] -= c
    game["potions"] -= p
    game["buys"] -= 1
    game["turn_ctx"]["bought"] = True
    # OVERPAY (Guilds/C&G): a `$N+` card lets you pay MORE than it costs. The
    # payment happens HERE, while paying for the card; the ability it buys is a
    # when-gain ability that reads how much you overpaid (the 2022 retiming —
    # pre-2022 it was a when-buy ability, which is why the compendium's older
    # examples read differently). With money left, ask before finishing.
    if cards_overpay(got) and game["coins"] > 0:
        push_auto(game, pid, "__buy", "finish", data={"pile": card, "card": got, "overpay": 0})
        push_choose_option(
            game, pid, got, "__overpay",
            options=[{"id": str(k), "label": "Don't overpay" if k == 0 else f"Overpay ${k}"}
                     for k in range(game["coins"] + 1)])
        return True, None
    _finish_buy(game, pid, card, got, 0)
    return True, None


def _finish_buy(game, pid, pile, got, overpay):
    """The half of a buy that follows the price being settled. Split out so the
    overpay prompt can sit in the middle of it: the log line, the gain (which
    carries `overpay` so the card's own when-gain ability can read it) and the
    buy event all belong AFTER the money has actually been paid."""
    _log(game, pid, "buy", card=got, **({"overpay": overpay} if overpay else {}))
    gain(game, pid, pile, via_buy=True, overpay=overpay)
    emit(game, "buy", actor=pid, subject=got)   # Prosperity's on-buy seam


def _k_overpay(game, pid, frame, choice):
    """Answer to the overpay prompt. A kernel stage named `__*`, so it displays
    under the bought card's own name (_stage_fn falls back to ("*", stage))."""
    n = int(choice["ids"][0])
    n = max(0, min(n, game["coins"]))
    for f in reversed(game["pending"]):
        if f["card"] == "__buy" and f["stage"] == "finish":
            f["data"]["overpay"] = n
            break
    if n:
        game["coins"] -= n


def _k_buy_finish(game, pid, frame, choice):
    d = frame["data"]
    _finish_buy(game, pid, d["pile"], d["card"], d["overpay"])


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
KERNEL_STAGES[("__buy", "finish")] = _k_buy_finish
KERNEL_STAGES[("*", "__overpay")] = _k_overpay
KERNEL_STAGES[("__gain", "resolve")] = _k_gain_resolve
KERNEL_STAGES[("__abilities", "pool")] = _k_ability_pool
KERNEL_STAGES[("__abilities", "pick")] = _k_ability_pick
KERNEL_STAGES[("*", "__offer_window")] = _k_offer_window
KERNEL_STAGES[("*", "__inplay_push")] = _k_inplay_push


_HANDLERS = {
    "play_action": _h_play_action,
    "play_treasure": _h_play_treasure,
    "play_all_treasures": _h_play_all_treasures,
    "buy": _h_buy,
    "spend": _h_spend,
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
    """START Clean-up. The SWEEP is parked as a continuation rather than run
    inline, which is what makes Clean-up INTERRUPTIBLE: a consumer of
    `cleanup_start` or `cleanup_discard` may push a real decision frame and
    MOVE a card before anything is discarded and before the new hand is drawn.

    Before ph. 5H the events fired but the sweep carried straight on, so a
    consumer could be told a card was being discarded and had no way to act on
    it — a seam that looked usable and was not. Three cards (Scheme,
    Alchemist, Herbalist) worked around it with a `buy_phase_end` watcher.
    """
    seat = game["seats"][pid]
    # durations: discard resolved entries, keep this turn's setups on the table
    kept_out = _cleanup_durations(game, pid)
    push_auto(game, pid, "__cleanup", "sweep", data={"kept_out": list(kept_out)})
    # "at the start of Clean-up" (Alchemist, Hermit-class) — before any card
    # has moved, so a consumer can still see the whole table.
    emit(game, "cleanup_start", actor=pid)
    inplay = list(seat["in_play"])
    for name in kept_out:
        inplay.remove(name)
    # "when you discard this FROM PLAY" during Clean-up (Scheme, Herbalist). A
    # distinct event from `discard`, deliberately: the when-discard reactions
    # (Tunnel/Trail/Weaver) are all "other than during a Clean-up phase" and
    # must NOT see this. Fired BEFORE the cards move, so a consumer can still
    # find them in in_play — and now actually relocate them.
    for c in inplay:
        emit(game, "cleanup_discard", actor=pid, subject=c)


def _k_cleanup_sweep(game, pid, frame, choice):
    """The rest of Clean-up, once every start-of-Clean-up ability has resolved."""
    seat = game["seats"][pid]
    kept_out = frame["data"]["kept_out"]
    # a consumer may have MOVED a card off the table (Scheme topdecks it), so
    # re-read what is actually still in play rather than trusting a snapshot.
    # kept_out (Durations + their riders) is accounted for in the duration
    # zone, so it must not also be discarded — or counted twice.
    inplay = list(seat["in_play"])
    for name in kept_out:
        if name in inplay:
            inplay.remove(name)
    seat["discard"].extend(inplay)
    seat["in_play"] = []
    seat["discard"].extend(seat["hand"])
    seat["hand"] = []
    # cards set aside only until this Clean-up (Joust's Province: "Discard the
    # Province in Clean-up"). They are NOT in play while set aside, which is
    # what keeps them out of Horn of Plenty's and Shop's in-play counts.
    if seat["cleanup_aside"]:
        _log(game, pid, "discard", cards=list(seat["cleanup_aside"]))
        seat["discard"].extend(seat["cleanup_aside"])
        seat["cleanup_aside"] = []
    # OTHER seats' in_play too: a REACTION THAT PLAYS ITSELF was played during
    # THIS turn and "you discard the card in that turn's Clean-up phase" —
    # this turn's, not the reactor's. Left behind it would still be on the
    # table when its owner's turn came round, wrongly counting as a card in
    # play for Bank / Peddler / Grand Market / Conspirator. Durations and
    # their riders are protected: _cleanup_durations already promoted them out
    # of in_play for every seat.
    for other, s in game["seats"].items():
        if other == pid or not s["in_play"]:
            continue
        held = [e["card"] for e in s["duration"]]
        for e in s["duration"]:
            held.extend(e.get("riders", []))
        leaving = list(s["in_play"])
        for name in held:
            if name in leaving:
                leaving.remove(name)
        if leaving:
            s["discard"].extend(leaving)
            s["in_play"] = [c for c in s["in_play"] if c in held]
            _log(game, other, "cleanup_off_turn", cards=leaving)
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
    # "+1 Card at the end of this turn" (Farrier's overpay) — AFTER the new
    # hand is drawn, which is the whole point of the card: the extra cards are
    # for NEXT turn, so a Farrier overpaid by 2 leaves you holding 7.
    if game["turn_ctx"]["end_draw"]:
        draw(game, pid, game["turn_ctx"]["end_draw"])
    # An EXTRA turn (Outpost) does not add to the player's turn count — the
    # count exists for the fewest-turns tiebreaker, and "extra turns do not add
    # to a player's turn count, and are not used in breaking ties" (wiki Turn
    # page; Outpost's FAQ agrees). game["extra_turn"] still describes the turn
    # now ENDING — it is reassigned for the next turn below.
    if not game.get("extra_turn"):
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
    game["potions"] = 0
    game["turn_ctx"] = _fresh_turn_ctx()
    _log(game, nxt, "turn_start", turn=game["turn_number"], extra=bool(extra))
    _arm_undo(game)
    _start_of_turn(game, nxt)   # duration fx queue as auto frames; watchers expire
    _maybe_auto_buy(game)       # a hand with no Action cards skips straight to buy


KERNEL_STAGES[("__cleanup", "sweep")] = _k_cleanup_sweep


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
    _run_stage(game, frame["card"], frame["stage"], pid, frame, move)
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
                        and potion_cost(game, pile) <= game["potions"] \
                        and buy_gate(game, pid, pile) is None:
                    mv.append({"type": "buy", "card": pile})
    # Coffers (and every later spendable counter) — legal in EITHER phase,
    # "at any time during your turn". Enumerated per amount so a search or a
    # bot can pick how much, the way it picks any other move.
    for what, have in spendable(game, pid).items():
        for k in range(1, have + 1):
            mv.append({"type": "spend", "what": what, "n": k})
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

def owned_cards(game, pid):
    """Every card pid owns, across every zone — the scoring census, and also
    what a deck-composition bot reads (bot.py's Big Money counts its Silvers
    with this)."""
    s = game["seats"][pid]
    owned = s["deck"] + s["hand"] + s["discard"] + s["in_play"] + s["aside"]
    # Seaside zones + mats (migrate guarantees these on every loaded save)
    owned += s["dur_aside"] + s["island"] + s["village_mat"]
    owned += s["set_aside"] + s["cleanup_aside"]   # C&G set-asides
    for entry in s["duration"]:
        owned.append(entry["card"])
        owned += entry.get("riders", [])
    return owned


def _vp_of(game, pid):
    owned = owned_cards(game, pid)
    n = len(owned)
    duchies = owned.count("Duchy")
    golds = owned.count("Gold")
    silvers = owned.count("Silver")
    actions = sum(1 for c in owned if has_type(game, c, "action"))
    # "differently named cards you have" (Fairgrounds) — the whole deck, by name
    distinct = len(set(owned))
    total = 0
    for c in owned:
        v = CARDS[c]["vp"]
        if v == "gardens":
            total += n // 10
        elif v == "duke":
            total += duchies
        elif v == "fairgrounds":
            total += 2 * (distinct // 5)
        elif v == "demesne":
            total += golds
        elif v == "vineyard":
            total += actions // 3
        elif v == "feodum":
            total += silvers // 3
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
    g.pop("_actor", None)
    # watchers are public table state, but their data can reference hidden
    # resume info — ship only the visible identity
    g["watchers"] = [{"event": w["event"], "owner": w["owner"], "card": w["card"]}
                     for w in g["watchers"]]
    # EFFECTIVE prices, computed by THE cost function — the client must never
    # re-derive them. It used to subtract only Bridge, so every other cost rule
    # (Quarry's turn discount, Peddler's dynamic self-cost, and every future
    # one) was invisible: the pile showed its printed price, never lit up as
    # affordable, and the click handler refused to send the buy.
    g["costs"] = {c: cost(game, c) for c in game["piles"]}
    # the POTION half of each price (Alchemy). Shipped separately rather
    # than folded into `costs` so the existing numeric field keeps its
    # meaning for every client — a cached bundle still prices $ correctly,
    # it just does not draw the Potion. Only non-zero entries ship.
    g["potion_costs"] = {c: potion_cost(game, c) for c in game["piles"]
                         if potion_cost(game, c)}
    # Piles ship as face + count, never `contents`: an ordered pile's order
    # below the top is HIDDEN (Ruins and Knights are shuffled), and "an honest
    # client ignores it" is not security — the repo has paid for that three
    # times. `attach` is genuinely public table state (tokens, Traits) and
    # `members` is static setup data the client has no use for.
    g["piles"] = {n: {"count": pile_count(game, n), "supply": p["supply"],
                      "face": p["face"], "ordered": p["contents"] is not None,
                      "attach": copy.deepcopy(p["attach"])}
                  for n, p in game["piles"].items()}
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
        # C&G: a set-aside card is face down in front of you until you play it
        seat["set_aside_count"] = len(seat["set_aside"])
        seat.pop("duration", None)
        seat.pop("dur_setup", None)
        seat.pop("start_fx", None)       # holds resume data, like watcher data
        if not over:
            seat.pop("deck")
            seat.pop("discard")
            seat.pop("aside")
            if p != viewer:
                seat.pop("hand")
                seat.pop("dur_aside", None)
                seat.pop("village_mat", None)
                seat.pop("set_aside", None)
    log = []
    for e in g["log"]:
        if "private_to" in e and viewer not in e["private_to"]:
            continue
        # draw / to_hand entries carry card names — owner-only until game over
        # (per-field redaction; the count stays public)
        if not over and e.get("event") in ("draw", "to_hand") \
                and e.get("pid") != viewer and "cards" in e:
            e = {k: v for k, v in e.items() if k != "cards"}
        log.append(e)
    g["log"] = log
    return g


# --- setup -------------------------------------------------------------------

_REQUIRE_TRIES = 500


def deal_kingdom(pool, requires, rng):
    """The random 10, honouring create-time REQUIREMENTS (`cards.REQUIREMENTS`
    keys — "give me a village / a +Buy / a drawer").

    REJECTION SAMPLING, deliberately: deal an ordinary random 10 and re-deal
    until it satisfies every requirement. The result is the NORMAL kingdom
    distribution conditioned on "has at least one of each", which is exactly
    what the option promises — it deletes the boards with none of a checked
    bonus and changes nothing else. In particular it does NOT reserve a slot
    per requirement: ticking all three still yields boards where one Worker's
    Village covers two of them, or where the ordinary fill already supplied a
    Smithy, at the rates those boards occur naturally.

    CONSTRUCTING the board instead (force one qualifying card per requirement,
    fill the other seven at random) is the obvious implementation and it is
    wrong for this: it guarantees three DIFFERENT qualifying cards whenever all
    three are ticked, which over-represents +Action/+Buy/+Card cards badly —
    measured, it pushed the mean number of villages from 1.58 to 1.95 and cut
    exactly-one-village boards from 57% to 35%. That was the first
    implementation; this replaced it.

    With nothing required this is EXACTLY `rng.sample(pool, 10)`: the rng call
    sequence is unchanged, so every seed that already exists still deals the
    same kingdom (the determinism soak and every forced-kingdom test depend on
    that). Requirements are read in `REQUIREMENT_ORDER`, never client order, so
    the deal stays reproducible from (seed, options) alone."""
    reqs = [r for r in REQUIREMENT_ORDER if r in set(requires or ())]
    kingdom = rng.sample(pool, 10)
    if not reqs:
        return kingdom
    # An unsatisfiable pool fails HERE with a usable message rather than after
    # 500 doomed re-deals. (No shipped expansion can hit this — each one alone
    # satisfies all three — but the option must not depend on that staying true.)
    for req in reqs:
        if not any(cards_grant(c, req) for c in pool):
            raise ValueError(
                f"no card in the chosen expansions gives {REQUIREMENTS[req]['label']}")
    for _ in range(_REQUIRE_TRIES):
        if all(any(cards_grant(c, req) for c in kingdom) for req in reqs):
            return kingdom
        kingdom = rng.sample(pool, 10)
    # Every requirement is individually satisfiable, so reaching here needs ~500
    # unlucky draws in a row; the measured accept rate is ~0.55 on the full pool
    # and ~0.46 on the smallest (Base alone, all three ticked).
    raise ValueError("could not deal a kingdom meeting the chosen requirements")


def new_game(player_ids, expansions, seed=None, names=None, kingdom=None,
             requires=None):
    """players in seat/turn order (the caller shuffles seats); expansions a
    non-empty subset of KINGDOM's keys; kingdom overrides the random 10 (tests,
    forced-kingdom soaks) and, being an explicit board, ignores `requires`;
    requires a subset of cards.REQUIREMENTS naming bonuses the dealt kingdom
    must contain at least one of."""
    players = list(player_ids)
    if not 2 <= len(players) <= 4:
        raise ValueError("dontminion needs 2-4 players")
    exps = sorted(set(expansions or []))
    if not exps or any(e not in KINGDOM for e in exps):
        raise ValueError(f"expansions must be a non-empty subset of {sorted(KINGDOM)}")
    rng = random.Random(seed)
    if kingdom is not None:
        kingdom = list(kingdom)
        # an entry may be a PILE name rather than a card (Knights) — see PILES
        bad = [c for c in kingdom
               if c not in PILES and (c not in CARDS or not CARDS[c]["kingdom"])]
        if bad:
            raise ValueError(f"unknown kingdom cards: {bad}")
    else:
        bad_req = sorted(set(requires or ()) - set(REQUIREMENTS))
        if bad_req:
            raise ValueError(f"unknown kingdom requirements: {bad_req}")
        pool = sorted({c for e in exps for c in KINGDOM[e]})
        if len(pool) < 10:
            raise ValueError("not enough kingdom cards in the enabled expansions")
        kingdom = sorted(deal_kingdom(pool, requires, rng))
    n = len(players)
    supply = {c: pile_size(c, n) for c in BASIC_CARDS}
    for c in kingdom:
        if c in PILES:
            continue          # ORDERED piles are built below, from `contents`
        supply[c] = pile_size(c, n)
    # Prosperity: Platinum/Colony join the Supply with probability equal to
    # the Prosperity proportion of the kingdom (official randomizer rule);
    # both piles or neither. Colony-empty becomes a game-end condition.
    prosperity_n = sum(1 for c in kingdom if cards_expansion(c) == "prosperity")
    colony = prosperity_n > 0 and rng.random() < prosperity_n / 10
    # Dark Ages, the same probabilistic shape (SPECIAL SETUP § I): Shelters
    # replace the 3 starting Estates with probability equal to the Dark Ages
    # proportion of the kingdom. A SEPARATE draw from the Colony one —
    # "it should not be the same card you check for Colonies".
    darkages_n = sum(1 for c in kingdom if cards_expansion(c) == "darkages")
    shelters = darkages_n > 0 and rng.random() < darkages_n / 10
    if colony:
        supply["Platinum"] = pile_size("Platinum", n)
        supply["Colony"] = pile_size("Colony", n)
    # Charlatan's game-wide rule: Curse is also a Treasure worth $1
    curse_is_treasure = "Charlatan" in kingdom
    # Cornucopia & Guilds SPECIAL SETUP (compendium § I). Both extra piles are
    # drawn from the kingdom cards this game did NOT deal, so they can only
    # come from the expansions in play; with none eligible we simply play
    # without one (a legal board — Young Witch just attacks unblockably, and
    # Ferryman gains nothing), rather than re-dealing the whole kingdom.
    # A Potion is PART of a card's cost, so "$2 or $3" / "$3 or $4" means those
    # coin amounts with NO Potion component — a {$3,P} card does not cost $3, so
    # both selections exclude every Potion-costed card.
    bane = ferryman_pile = None
    # ORDERED piles (Knights) are excluded as candidates: both selections build
    # an ordinary pile out of the chosen name, which cannot represent a
    # shuffled one. Nothing is lost today — the only such pile costs $5, which
    # neither selection can reach — and a future one gets a deliberate decision
    # rather than a silently malformed pile.
    unused = sorted({c for e in exps for c in KINGDOM[e] if c in CARDS}
                    - set(kingdom))
    if "Young Witch" in kingdom:
        # "an extra Kingdom card pile costing $2 or $3, added TO the Supply"
        pick = [c for c in unused
                if cards_printed_cost(c) in (2, 3) and not cards_potion(c)]
        if pick:
            bane = rng.choice(pick)
            supply[bane] = pile_size(bane, n)
            unused.remove(bane)
    if "Ferryman" in kingdom:
        # "an unused Kingdom card pile costing $3 or $4, OUTSIDE the Supply"
        pick = [c for c in unused
                if cards_printed_cost(c) in (3, 4) and not cards_potion(c)]
        if pick:
            ferryman_pile = rng.choice(pick)
            unused.remove(ferryman_pile)
    # Alchemy: "if any Kingdom card has a Potion in its cost, include the 16
    # Potion cards in the Supply" — a setup rule, not a randomiser roll. The
    # extra Cornucopia piles are never Potion-costed (filtered above), so the
    # dealt kingdom is the whole test.
    if any(cards_potion(c) for c in kingdom if c in CARDS):
        supply["Potion"] = pile_size("Potion", n)
    # Dark Ages SPECIAL SETUP, part 2 — the shuffled piles. Their contents are
    # drawn HERE, from the setup rng, so the whole board is a function of the
    # seed; the piles themselves are added once the game dict exists.
    #
    # "If any Kingdom card has the type Looter, include a Ruins pile in the
    # Supply. Shuffle the 50 Ruins cards, and from those draw and include the
    # same number of Ruins as Curses." Only the top card is ever visible, which
    # is exactly what an ordered pile is (ph. 3H).
    # "If these extra cards have a special setup rule, do that setup" — a Bane
    # or a Ferryman pile IS in the game, so a Hermit picked as the Bane brings
    # the Madman pile with it and a Death Cart brings the Ruins.
    in_play_cards = [c for c in kingdom + [bane, ferryman_pile]
                     if c is not None and c in CARDS]
    ruins_pile = knights_pile = None
    if any("looter" in CARDS[c]["types"] for c in in_play_cards):
        deck = [r for r in RUINS for _ in range(RUINS_EACH)]
        rng.shuffle(deck)
        ruins_pile = deck[:pile_size("Curse", n)]
    if "Knights" in kingdom:
        knights_pile = list(KNIGHTS)
        rng.shuffle(knights_pile)
    game = {
        "game": "dontminion",
        "players": players,
        "names": dict(names or {p: p for p in players}),
        "expansions": exps,
        "kingdom": kingdom,
        # `supply` is the count index over the BUYABLE piles (unchanged);
        # `nonsupply` the same shape for piles outside the Supply; `piles` the
        # per-pile model that says which index holds a pile and what it shows.
        # See THE PILE MODEL above.
        "supply": supply,
        "nonsupply": {},
        "piles": {c: _plain_pile(c) for c in supply},
        "trash": [],
        "seats": {},
        "turn": players[0],
        "turn_number": 1,
        "phase": "action",
        "actions": 1,
        "buys": 1,
        "coins": 0,
        "potions": 0,              # the Potion half of the money pool (Alchemy)
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
        "shelters": shelters,      # Shelter starting decks (Dark Ages setup rule)
        "curse_is_treasure": curse_is_treasure,   # Charlatan's game-wide rule
        # Cornucopia & Guilds
        "coffers": {p: 0 for p in players},
        "bane": bane,                     # the Young Witch pile (IS in the Supply)
        "ferryman_pile": ferryman_pile,   # Ferryman's pile (is NOT in the Supply)
        "footpad_draw": "Footpad" in kingdom,     # its game-wide when-gain rule
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
    # the non-Supply piles this set brings, all riding ph. 3H's pile model
    if ferryman_pile:
        add_pile(game, ferryman_pile, count=pile_size(ferryman_pile, n))
    if "Joust" in kingdom:
        # "a pile of the 6 different Rewards outside the Supply. In a 2-player
        # game, use one of each, otherwise two of each." Modelled as six piles
        # rather than one ordered pile: every Reward is face up and Joust gains
        # ANY of them, so there is no top card and no hidden order.
        for r in REWARDS:
            add_pile(game, r, count=1 if n == 2 else 2)
    # Dark Ages: the two shuffled SUPPLY piles (only their top card is ever
    # visible — the wire never ships `contents`), then the three piles that sit
    # OUTSIDE the Supply, so "gain a card from the Supply" excludes them by
    # construction rather than by anyone remembering to check.
    if ruins_pile:
        add_pile(game, "Ruins", contents=ruins_pile, supply=True, members=RUINS)
    if knights_pile:
        add_pile(game, "Knights", contents=knights_pile, supply=True, members=KNIGHTS)
    if "Hermit" in in_play_cards:
        add_pile(game, "Madman", count=10)
    if "Urchin" in in_play_cards:
        add_pile(game, "Mercenary", count=10)
    if any(c in in_play_cards for c in ("Bandit Camp", "Marauder", "Pillage")):
        add_pile(game, "Spoils", count=15)
    for pid in players:
        game["seats"][pid] = {"deck": [], "hand": [], "discard": [],
                              "in_play": [], "aside": [], "turns_taken": 0,
                              # Seaside zones: persistent duration entries, their
                              # face-down set-asides (Haven/Blockade), and mats
                              "duration": [], "dur_aside": [],
                              "island": [], "village_mat": [],
                              # C&G: Farmhands' set-aside + its start-of-turn play
                              "set_aside": [], "start_fx": [],
                              "cleanup_aside": []}
        # "If Shelters are used, each player starts with 3 Shelters — a Hovel, a
        # Necropolis, and an Overgrown Estate — instead of the 3 Estates. (Don't
        # include those Estates in the game.)" The Estate PILE is untouched: it
        # is the players' three copies that are replaced, and Shelters belong to
        # no pile at all.
        start = ["Copper"] * 7 + (list(SHELTERS) if shelters else ["Estate"] * 3)
        r = _make_rng(game)
        r.shuffle(start)
        _save_rng(game, r)
        game["seats"][pid]["deck"] = start
        draw(game, pid, 5)
    if "Baker" in kingdom:
        # "If Baker is in the game, each player starts with one token on their
        # Coffers mat" — set directly, not via add_coffers, which would log a
        # gain for a player before the game has begun
        game["coffers"] = {p: 1 for p in players}
    _log(game, players[0], "turn_start", turn=1)
    _post_move(game)
    # The setup draws marked "revealed" — arm the FIRST turn's undo cleanly.
    _arm_undo(game)
    return game
