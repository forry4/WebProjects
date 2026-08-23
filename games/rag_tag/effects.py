"""The op vocabulary, and the registries the engine resolves it through.

`fighters.py` is generated data; this module is the closed set of things that data
is allowed to say. Nothing here knows how a turn resolves — that is `engine.py`.
What it knows is the SHAPE of every op, condition and computed value, so that a
mis-transcribed card or a newly imported expansion fails at test time with the
offending path named, instead of resolving to nothing at runtime.

Three registries:

* ``OPS`` — every declarative op, with the fields it takes. The engine dispatches
  on the op name; this is the schema those handlers can rely on.
* ``FIGHTER_FX`` — the escape hatch. A card whose behaviour is not expressible as
  ops carries ``{"op": "fx", "name": ...}``, and the named function does the work.
  Register with the ``@fx`` decorator.
* ``FIGHTER_HOOKS`` — per-fighter lifecycle callbacks the engine calls at fixed
  points, rather than a card calling them.

``UNIMPLEMENTED_FX`` is the honest half of that: the fx names the data already
uses and this module has not implemented yet. ``tests/test_fighters.py`` asserts
the data's fx names are exactly ``FIGHTER_FX | UNIMPLEMENTED_FX``, that the two
never overlap, and that nothing in ``UNIMPLEMENTED_FX`` has gone stale — so the
remaining work is machine-checked in both directions and an fx that is in neither
fails loudly rather than silently doing nothing.
"""

from __future__ import annotations

from typing import Any, Callable

# --------------------------------------------------------------------------
# The vocabulary
# --------------------------------------------------------------------------

#: Who an op acts on. ``both_opps`` is the opposing Active Fighter and their
#: Partner; ``all_others`` adds your own Partner; ``all`` adds you as well.
TARGETS = frozenset({"self", "partner", "opp", "opp_partner", "both_opps",
                     "all_others", "all"})

#: A numeric field may be an int, or one of these computed values as
#: ``{"kind": ..., ...}``. Resolved by the engine at resolution time.
VALUE_KINDS = {
    # As many as the Active Fighter's Power at the start of the turn.
    "power": (),
    # The combined Power of every Opponent whose Attack this Block negated.
    "attacking_opponents_power": (),
    # The Fey Folk's Spirit count, read at the START of the turn.
    "spirits": ("times",),
}

#: Condition kinds usable in an ``if`` op, and the extra fields each requires.
COND_KINDS = {
    "power_at_least": ("n",),
    "hp_equals": ("n",),
    "no_opponent_attacked": (),
    "self_attacked": (),
    "own_attack_blocked": (),
    "opponent_played_starting_card": (),
    "serpent": ("face",),
    "face": ("face",),
    "ships": ("min", "max"),
    "has_token": ("token",),
    "token_on": ("token", "who"),
}

def _op(*fields: str, **optional: Any) -> dict:
    return {"required": frozenset(fields), "optional": frozenset(optional)}


#: name -> the fields it takes. Every op additionally accepts ``after`` (the
#: printed THEN keyword: resolve me only once the ops before me have).
OPS = {
    "attack":         _op(target=None, success=None, flamepower=None, power_bonus=None, by=None),
    "block":          _op(success=None),
    "damage":         _op("n", target=None),
    "heal":           _op("n", target=None),
    "power":          _op("n", target=None),
    "transfer_power": _op("n", "from", "to"),
    "cancel":         _op(target=None),
    "track":          _op("track", "n"),
    "if":             _op("cond", "then", **{"else": None}),
    "fx":             _op("name"),
    # Fighter-specific verbs that are still declarative enough to stay ops:
    # they take no arguments and always mean the same thing.
    "ignite":         _op(),           # Shango: 1 Aflame! token on the Opponent
    "plant_scheme":   _op(),           # Milady: top token from the pile, face down
    "unleash_scheme": _op(),           # Milady: flip a random planted token
    "give_token":     _op("token", "to"),
    "take_token":     _op("token"),
    "flip_card":      _op(),           # The Fey Folk's Summoning cards
    "spirit":         _op("n"),        # advance the Spirits track
}

#: Ops every one of them also accepts.
UNIVERSAL_OP_FIELDS = frozenset({"op", "after"})

#: Non-op icons a health-track space may carry.
TRACK_ICONS = frozenset({"stop"})


# --------------------------------------------------------------------------
# The registries
# --------------------------------------------------------------------------

FIGHTER_FX: dict[str, Callable] = {}
FIGHTER_HOOKS: dict[str, dict[str, Callable]] = {}


def fx(name: str) -> Callable[[Callable], Callable]:
    """Register the handler for ``{"op": "fx", "name": name}``."""

    def deco(fn: Callable) -> Callable:
        if name in FIGHTER_FX:
            raise ValueError(f"duplicate FIGHTER_FX registration: {name!r}")
        if name in UNIMPLEMENTED_FX:
            raise ValueError(
                f"{name!r} is implemented — drop it from UNIMPLEMENTED_FX")
        FIGHTER_FX[name] = fn
        return fn

    return deco


#: Named by the data, not yet implemented. Shrinks to empty as engine.py lands;
#: test_fighters.py fails if it disagrees with what the data actually uses.
#: Named by the data and not yet implemented. Empty since the engine landed;
#: test_fighters.py fails if it disagrees with what the data actually uses, in
#: BOTH directions, so it cannot rot into a lie either way.
UNIMPLEMENTED_FX = frozenset()


# --------------------------------------------------------------------------
# Validation — used by tests and by tools/import_bga.py
# --------------------------------------------------------------------------

class OpError(ValueError):
    """A malformed op, with the path through the data that reached it."""


def _fail(path: str, msg: str) -> None:
    raise OpError(f"{path}: {msg}")


def validate_value(value: Any, path: str) -> None:
    """An int, or a computed ``{"kind": ...}``."""
    if isinstance(value, bool):
        _fail(path, "a bool is not a number")
    if isinstance(value, int):
        return
    if not isinstance(value, dict):
        _fail(path, f"expected a number or a computed value, got {value!r}")
    kind = value.get("kind")
    if kind not in VALUE_KINDS:
        _fail(path, f"unknown computed value kind {kind!r}")
    extra = set(value) - {"kind"} - set(VALUE_KINDS[kind])
    if extra:
        _fail(path, f"computed value {kind!r} has unexpected fields {sorted(extra)}")


def validate_cond(cond: Any, path: str) -> None:
    if not isinstance(cond, dict):
        _fail(path, f"expected a condition object, got {cond!r}")
    kind = cond.get("kind")
    if kind not in COND_KINDS:
        _fail(path, f"unknown condition kind {kind!r}")
    missing = set(COND_KINDS[kind]) - set(cond)
    if missing:
        _fail(path, f"condition {kind!r} is missing {sorted(missing)}")
    extra = set(cond) - {"kind"} - set(COND_KINDS[kind])
    if extra:
        _fail(path, f"condition {kind!r} has unexpected fields {sorted(extra)}")


def validate_op(op: Any, path: str) -> None:
    if not isinstance(op, dict):
        _fail(path, f"expected an op object, got {op!r}")
    name = op.get("op")
    if name not in OPS:
        _fail(path, f"unknown op {name!r}")
    spec = OPS[name]

    missing = spec["required"] - set(op)
    if missing:
        _fail(path, f"op {name!r} is missing {sorted(missing)}")
    allowed = spec["required"] | spec["optional"] | UNIVERSAL_OP_FIELDS
    extra = set(op) - allowed
    if extra:
        _fail(path, f"op {name!r} has unexpected fields {sorted(extra)}")

    if "target" in op and op["target"] not in TARGETS:
        _fail(path, f"unknown target {op['target']!r}")
    if "to" in op and op["to"] not in TARGETS:
        _fail(path, f"unknown target {op['to']!r}")
    if "from" in op and op["from"] not in TARGETS:
        _fail(path, f"unknown target {op['from']!r}")
    if "by" in op and op["by"] not in TARGETS:
        _fail(path, f"unknown actor {op['by']!r}")
    if "n" in op:
        validate_value(op["n"], f"{path}.n")
    if "cond" in op:
        validate_cond(op["cond"], f"{path}.cond")
    if "power_bonus" in op:
        validate_value(op["power_bonus"], f"{path}.power_bonus")

    for branch in ("then", "else", "success"):
        if branch in op:
            validate_ops(op[branch], f"{path}.{branch}")


def validate_ops(ops: Any, path: str) -> None:
    if not isinstance(ops, list):
        _fail(path, f"expected a list of ops, got {ops!r}")
    for i, op in enumerate(ops):
        validate_op(op, f"{path}[{i}]")


def validate_icons(icons: Any, path: str) -> None:
    """A health-track space's icons: ops, plus the bare string ``stop``."""
    if not isinstance(icons, list):
        _fail(path, f"expected a list of icons, got {icons!r}")
    for i, icon in enumerate(icons):
        if isinstance(icon, str):
            if icon not in TRACK_ICONS:
                _fail(f"{path}[{i}]", f"unknown track icon {icon!r}")
            continue
        validate_op(icon, f"{path}[{i}]")


def collect_fx_names(ops: Any, found: set[str]) -> set[str]:
    """Every fx name reachable from an op list, branches included."""
    if isinstance(ops, dict):
        ops = [ops]
    for op in ops or ():
        if isinstance(op, str):
            continue
        if op.get("op") == "fx":
            found.add(op["name"])
        for branch in ("then", "else", "success"):
            if branch in op:
                collect_fx_names(op[branch], found)
    return found


# ==========================================================================
# The escape hatch, implemented
# ==========================================================================
#
# Every handler takes (turn, seat, who, phase) and reaches state only through
# the Turn helpers, never the game dict, so a card cannot quietly break an
# invariant. `who` is the acting fighter as (seat, slot); `phase` is 'declare'
# during the cards' own resolution and 'late' for icons, bonuses and THEN.
#
# `engine` is imported inside each function: engine imports THIS module for its
# registries, so a module-level import would be a cycle.


@fx("bodvar_transform")
def _bodvar_transform(turn, seat, who, phase):
    """Rage tops out. +3 Power has already applied; now he becomes the Bear.

    The Bear's opening HP is Bödvar's Power cubes at this instant, capped at 15 --
    a starting point, not a ceiling, so he can Heal above it afterwards. Tokens
    ride along, because they live on the fighter rather than the board. And he
    takes no HP change at all for the rest of this turn.
    """
    from . import engine

    f = turn.f(who)
    if f.get("face") == "berserker_bear":
        return
    turn.flush_power(who)
    f["face"] = "berserker_bear"
    f["hp"] = min(f["power"], 15)
    turn.immune.add(who)
    turn.hp_delta.pop(who, None)
    turn.note(kind="transform", seat=who[0], slot=who[1], to="berserker_bear",
              hp=f["hp"])


@fx("brijit_revive")
def _brijit_revive(turn, seat, who, phase):
    """Pushed past both KO spaces, she comes back -- at the END of the turn."""
    turn.revive.add(who)
    turn.note(kind="revive", seat=who[0], slot=who[1])


@fx("mephisto_flip_serpent")
def _mephisto_flip_serpent(turn, seat, who, phase):
    """Flip the token WITHOUT applying the new face. Next card reads the new one."""
    f = turn.f(who)
    f["tokens"]["serpent_face"] = 1 - f["tokens"].get("serpent_face", 0)
    turn.note(kind="serpent", seat=who[0], slot=who[1],
              face="black" if f["tokens"]["serpent_face"] else "white")


@fx("milady_unleash_scheme")
def _milady_unleash_from_track(turn, seat, who, phase):
    """An Intrigue off the HEALTH TRACK, which resolves after all card actions.

    That timing is the whole difference from the card version: because it lands
    later it can move a marker that is currently sitting on a Stop.
    """
    turn.deferred.append((who[0], {"op": "unleash_scheme"}))


@fx("golem_reanimation")
def _golem_reanimation(turn, seat, who, phase):
    """The card on the Golem's next turn resolves twice, the second as a new turn."""
    turn.game["double_next"][seat] = True
    turn.note(kind="reanimation", seat=seat)


@fx("mordred_execution")
def _mordred_execution(turn, seat, who, phase):
    """A finisher, read after the Opponent's card has resolved."""
    from . import engine

    if phase == "declare":
        turn.deferred.append((seat, {"op": "fx", "name": "mordred_execution"}))
        return
    opp = turn.resolve_target(seat, "opp")[0]
    left = engine.hp_value(turn.f(opp))
    if 0 < left <= 4:
        turn.add_hp(opp, -left)
        turn.note(kind="execution", seat=opp[0], slot=opp[1], damage=left)


@fx("mephisto_drag_you_to_hell")
def _drag_you_to_hell(turn, seat, who, phase):
    """Lose this turn for ANY reason -- KO, your Partner, even Incineration -- and
    you win the fight instead."""
    turn.drag.add(seat)


@fx("feyfolk_all_legends_must_pass")
def _all_legends_must_pass(turn, seat, who, phase):
    """Their only KO condition: all three already Spirits when this is revealed."""
    from . import engine

    if turn.spirits_at_start.get(who, 0) >= 4:
        turn.fey_folk_losses.add(seat)
        turn.note(kind="ko", seat=who[0], slot=who[1])


@fx("brijit_redirect_attacks")
def _brijit_redirect(turn, seat, who, phase):
    """Every Attack her Block caught turns around onto the opposing Partner."""
    opp_mate = turn.resolve_target(seat, "opp_partner")[0]
    for atk in turn.attacks:
        if atk["seat"] != seat and atk["negated"] and atk["power"] > 0:
            turn.add_hp(opp_mate, -atk["power"])
            turn.note(kind="redirect", seat=opp_mate[0], slot=opp_mate[1],
                      power=atk["power"])


@fx("brijit_eternal_youth")
def _eternal_youth(turn, seat, who, phase):
    """She steals the Opponents' Healing.

    It cancels only their Heal, not their whole card, and she gains the 2 Power
    only if she actually recovered something. Deferred to the end of declaration
    because the other side's card may not have been walked yet.
    """
    if phase == "declare":
        turn.post_declare.append(("eternal_youth", seat, who))
        return
    stolen = 0
    for src_seat, tgt, amount in turn.heal_log:
        if src_seat != seat and tgt[0] != seat:
            turn.add_hp(tgt, -amount)
            stolen += amount
    if stolen:
        turn.add_hp(who, stolen)
        turn.add_power(who, 2)
        turn.note(kind="steal_heal", seat=who[0], slot=who[1], amount=stolen)


@fx("ching_terror_of_the_seas")
def _terror_of_the_seas(turn, seat, who, phase):
    """Three different cards depending on the Fleet, and 16-19 really is nothing."""
    from . import engine

    ships = turn.f(who)["tracks"].get("navigation", 0)
    if ships <= 7:
        turn.add_attack(seat, who, turn.resolve_target(seat, "opp"), turn.power(who))
        return
    if ships <= 15:
        turn.add_hp(who, 2)
        return
    if ships < 20:
        return
    # Twenty Ships. Both Opponents drop to 1 HP as Direct Damage -- so Stops and
    # health-track icons all still apply -- and nothing else this turn touches
    # them. The Fleet then goes back to nothing.
    for tgt in turn.resolve_target(seat, "both_opps"):
        turn.hp_delta.pop(tgt, None)
        left = engine.hp_value(turn.f(tgt))
        if left > 1:
            turn.add_hp(tgt, -(left - 1))
        turn.ignore_hp.add(tgt)
    turn.f(who)["tracks"]["navigation"] = 0
    turn.note(kind="terror", seat=seat)


@fx("wong_harder_they_fall")
def _harder_they_fall(turn, seat, who, phase):
    """Mark the Opponent, or cash the mark in and hit them with their own Power."""
    from . import engine

    opp = turn.resolve_target(seat, "opp")[0]
    if turn.f(opp)["tokens"].get("concentration", 0) > 0:
        # Their Power, not his -- and if the target gets redirected it is still
        # the ORIGINAL target's Power that is used.
        turn.add_attack(seat, who, [opp], turn.power(opp))
        turn.deferred.append((seat, {"op": "take_token", "token": "concentration"}))
        return
    if turn.f(who)["tokens"].get("concentration", 0) > 0:
        turn.move_token(who, opp, "concentration")


@fx("wong_crippling_touch")
def _crippling_touch(turn, seat, who, phase):
    """After the Opponent's card resolves, remove it; THEN remove this one.

    Both leave the game permanently, so both decks get smaller -- which is the
    one thing in Rag Tag that changes how long a fight can run.
    """
    if phase == "declare":
        turn.deferred.append((seat, {"op": "fx", "name": "wong_crippling_touch"}))
        return
    turn.remove_from_play(turn.revealed[1 - seat])
    turn.remove_from_play(turn.revealed[seat])


@fx("wong_match_partner_power")
def _match_partner_power(turn, seat, who, phase):
    """His Power becomes his Partner's. It does go DOWN if theirs is lower."""
    mate = turn.resolve_target(seat, "partner")[0]
    turn.add_power(who, turn.f(mate)["power"] - turn.f(who)["power"])


@fx("wb_corrupted_lawman")
def _corrupted_lawman(turn, seat, who, phase):
    """The Sheriff changes sides, and is worth something to whoever holds him."""
    opp = turn.resolve_target(seat, "opp")[0]
    if turn.f(who)["tokens"].get("sheriff", 0) > 0:
        turn.move_token(who, opp, "sheriff")
        turn.add_attack(seat, who, [opp], turn.power(who))
        return
    holder = turn.token_holder("sheriff")
    if holder is not None and holder[0] != seat:
        turn.add_power(holder, 1)
        turn.move_token(holder, who, "sheriff")
        turn.add_power(who, 1)


@fx("wb_keys_to_the_armory")
def _keys_to_the_armory(turn, seat, who, phase):
    """Whoever is holding the Sheriff gains 2 Power -- that may be an Opponent."""
    holder = turn.token_holder("sheriff")
    if holder is not None:
        turn.add_power(holder, 2)


@fx("milady_poison")
def _poison(turn, seat, who, phase):
    """Half the Opponent's CURRENT HP, rounded down, so it can never finish them.

    It resolves after every other Intrigue and reads the HP total left once
    everything else has landed, which is why it arrives here deferred.
    """
    from . import engine

    opp = turn.resolve_target(seat, "opp")[0]
    left = engine.hp_value(turn.f(opp))
    hurt = left // 2
    if hurt:
        turn.add_hp(opp, -hurt)
        turn.note(kind="poison", seat=opp[0], slot=opp[1], damage=hurt)
