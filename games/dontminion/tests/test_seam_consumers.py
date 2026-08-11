"""EVERY KERNEL SEAM MUST HAVE A CONSUMER, OR SAY THAT IT DOESN'T.

This exists because the project spent nine phases documenting a mechanism that
no card used. `effects.COST_MODS` — "the Quarry-class while-in-play cost
modifier seam" — shipped **empty through twelve expansions**: the 2022 errata
had converted every cost reducer in Dominion to turn-scoped, so the mechanic it
modelled no longer existed. Three separate phases wrote a LOCAL note explaining
why their card declined it ("Highway is not a COST_MODS card", "Renown is
Bridge, not a while-in-play modifier") and none asked the global question. A
contract test in `test_trigger_bus.py` kept it green the entire time, which is
the real lesson: **a contract test proves a seam WORKS, never that anything
NEEDS it.** The same audit found `emit("buy")` with zero consumers, and a
`would_gain` replacement protocol the ledger recorded as PAID naming a consumer
(Trader) that had quietly chosen a different seam.

So the rule is: a seam with no consumer is not a bug, but an UNDECLARED one is.
Anything empty must be listed in `UNCONSUMED` with a reason — which turns "we
built this speculatively" from something you discover by grepping into
something you read.

Two things here are load-bearing, and both are lessons this repo has already
paid for elsewhere:

* **The rosters are DERIVED, never hand-listed.** Registries come from the
  merged `effects` namespace and events from `engine.py`'s AST, so a seam added
  next phase is covered the day it lands. A hardcoded roster only ever guards
  the list SHRINKING — the `range(13)` bug's exact shape.
* **It reads the MERGED registries, not the source text.** Three sites register
  in LOOPS (the 20 Ways, the Travellers, the 10 Knights), so a grep-based
  census undercounts them badly — the audit that prompted this file read
  `would_resolve` as 1 consumer when it has 21. Import and count.

`UNCONSUMED` is checked in BOTH directions: an undeclared empty seam fails, and
so does a declared one that has since acquired a consumer. A one-way check
would rot into a list of excuses nobody revisits.
"""

import ast
import pathlib

import pytest

from games.dontminion import effects

PKG = pathlib.Path(__file__).resolve().parent.parent
ENGINE_SRC = (PKG / "engine.py").read_text(encoding="utf-8")
EFFECT_MODULES = sorted(PKG.glob("effects_*.py"))

# Seams that genuinely have no consumer today. Each MUST carry the reason it is
# still here rather than deleted — "we might need it" is not one, as COST_MODS
# demonstrated for nine phases. Deleting a seam is the other valid answer.
UNCONSUMED = {
    "event:buy": (
        "The 2022 errata retimed every when-buy ability to when-gain, so all 62 "
        "on-gain triggers read `via_buy` off the `gain` event instead. `emit(\"buy\")` "
        "also fires AFTER gain() has parked its whole ability pool, so a consumer "
        "could not be ordered against them even if one existed. Kept because it is "
        "one line and the buy/gain distinction is real; delete it if a set reaches "
        "ph. 13 without using it."
    ),
    "event:would_gain": (
        "The replacement protocol (park the physical gain + offer a hand reaction). "
        "Built ph. 2, ledgered PAID naming Trader, and Trader does not use it — it "
        "exchanges on a COMPLETED gain, as its own comment says. Kept because the "
        "mechanic genuinely exists in Dominion and a later set will print one, but "
        "four assumptions are unverified (see the ⚠ block in CLAUDE.md, headlined by "
        "'only ONE reactor is ever offered and the window never reaches "
        "park_abilities'). The first real consumer owes checking all four."
    ),
}


def _registries():
    """The merged card registries, derived from the effects namespace."""
    return {name: value for name, value in vars(effects).items()
            if name.isupper() and isinstance(value, (dict, set))}


def _engine_tree():
    return ast.parse(ENGINE_SRC)


def _call_name(node):
    fn = node.func
    return fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)


def _str_args(node, start=0):
    return [a.value for a in node.args[start:]
            if isinstance(a, ast.Constant) and isinstance(a.value, str)]


def _emitted_events():
    """Event names the kernel fires.

    ⚠ THERE ARE THREE EMIT FUNCTIONS, NOT ONE, and the event is at a DIFFERENT
    ARGUMENT POSITION in the third: `emit(game, "x")` and `emit_batch(game,
    "x", ...)` put it second, but `_emit_collect(game, pools, "x", ...)` puts
    it third. Matching on a fixed index silently missed `turn_start` and
    `would_resolve` — two of the most-consumed events in the game — and the
    census still passed its non-vacuity floor, because it had found plenty of
    OTHER events. So take the first string constant in the call instead of a
    positional index."""
    found = set()
    for node in ast.walk(_engine_tree()):
        if isinstance(node, ast.Call) and (_call_name(node) or "").startswith(
                ("emit", "_emit")):
            strs = _str_args(node)
            if strs:
                found.add(strs[0])
    return found


def _dispatched_events():
    """Events the kernel dispatches on WITHOUT emitting them — a literal
    compared against a spec's `on` or a watcher's `event`, e.g.
    `s["on"] == "would_gain"` in gain() and `w["event"] == "protect"` in
    attack_protected(). Both are real seams a card can register for, and
    NEITHER is ever `emit`ted: Lighthouse's protection is consulted by the
    attack wrap rather than fired, so an emit-only census reports every
    Lighthouse-class watcher as registering for an event that does not
    exist."""
    found = set()
    for node in ast.walk(_engine_tree()):
        if not isinstance(node, ast.Compare):
            continue
        left = node.left
        if (isinstance(left, ast.Subscript)
                and isinstance(left.slice, ast.Constant)
                and left.slice.value in ("on", "event")):
            for comparator in node.comparators:
                if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                    found.add(comparator.value)
    return found


def _event_seams():
    return _emitted_events() | _dispatched_events()


def _watcher_events():
    """Events registered dynamically by card code. Consumers just as much as a
    TRIGGERS spec is — Lighthouse, Haunted Woods and Champion are all watchers.

    ⚠ THE LOOP CASE IS NOT OPTIONAL. Invest registers its watchers with
    `for event in ("gain", "exile"): _landscape_watcher(..., event, ...)` — a
    WRAPPER around add_watcher, with the event name as a LOOP VARIABLE. Neither
    a grep nor a literal-argument walk can see it, and the first version of this
    file duly reported `exile` as an unconsumed seam that ph. 10 had documented
    as consumed. That is the same blind spot, in a new shape, that made the
    audit behind this file undercount `would_resolve` as 1 consumer when it has
    21.

    ⚠ AND THE POSITIONAL FIX FOR IT WAS UNSOUND, which is the more useful
    lesson. "The event is argument 3 of anything named *watcher*" holds for
    `add_watcher` and for `_landscape_watcher(g, pid, card, event, stage)` — and
    is WRONG for `_this_turn_gain_watcher(g, pid, card, stage)`, which bakes its
    event in and puts the STAGE there. That handed the census three stage names
    (`gain_check`, `gold_check`, `vp_check`) as if they were events. Two
    wrappers, two signatures, and no reason a third would match either.

    So this is deliberately LOOSE and then GATED: take every string constant in
    any watcher-ish call (and any `for` loop over literals whose body makes
    one), then keep only names that are in the kernel's own event vocabulary.
    The gate is what makes the looseness sound — a stage name can never
    impersonate an event, because the engine is the authority on what an event
    is. The cost is that this cannot detect a MISSPELLED watcher event; that is
    what the TRIGGERS-side orphan check below covers, on data that is exact."""
    found = set()
    for path in EFFECT_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and "watcher" in (_call_name(node) or ""):
                found.update(_str_args(node))
            elif isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List)):
                names = [e.value for e in node.iter.elts
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if names and any("watcher" in (_call_name(n) or "")
                                 for n in ast.walk(node) if isinstance(n, ast.Call)):
                    found.update(names)
    return found & _event_seams()


def _trigger_events():
    """Events consumed by the static TRIGGERS registry, read from the MERGED
    registry so loop-registered cards (Ways, Travellers, Knights) are counted."""
    return {spec["on"] for specs in effects.TRIGGERS.values() for spec in specs}


def _consumed_events():
    return _trigger_events() | _watcher_events()


# --------------------------------------------------------------------------
# non-vacuity: a broken walk must FAIL, not silently census nothing
# --------------------------------------------------------------------------

def test_the_census_actually_finds_the_seams():
    """Every derivation here can fail open — an AST shape that stops matching
    returns an empty set and every assertion below passes. These floors are
    deliberately well under today's counts, so they catch a broken walk without
    failing on ordinary growth."""
    assert len(_registries()) >= 10, "registry census found almost nothing"
    assert len(_emitted_events()) >= 10, "emit() AST walk found almost nothing"
    assert len(_trigger_events()) >= 8, "TRIGGERS census found almost nothing"
    assert len(_watcher_events()) >= 5, "add_watcher AST walk found almost nothing"
    # Each of these was MISSED by the first version of this file, and a count
    # floor did not catch any of them — the walk found plenty of other names
    # and passed. Pin the specific shapes instead: a third emit function with
    # the event at a different argument index, a never-emitted event consulted
    # by the attack wrap, and a wrapper called with the event as a loop var.
    assert "turn_start" in _emitted_events(), "_emit_collect's events are being missed"
    assert "would_resolve" in _emitted_events(), "_emit_collect's events are being missed"
    assert "would_gain" in _dispatched_events(), (
        "the dispatched-event walk stopped finding would_gain — the one seam it "
        "exists to see")
    assert "protect" in _dispatched_events(), (
        "'protect' is consulted, never emitted — the `w[\"event\"] ==` shape is "
        "no longer being read")
    assert "exile" in _watcher_events(), (
        "Invest's loop-registered watcher is being missed — the exact blind "
        "spot this census exists to not have")
    # the loop-registered cards the grep-based audit undercounted
    assert len(effects.TRIGGERS) >= 100, "TRIGGERS is not the merged registry"
    assert "would_resolve" in _trigger_events(), "the 20 Ways are not being counted"


# --------------------------------------------------------------------------
# the census itself
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(_registries()))
def test_every_registry_has_a_consumer_or_is_declared_unconsumed(name):
    """A registry with no entries is a mechanism no card uses. That is allowed
    — but it has to SAY so, because the alternative is COST_MODS: nine phases
    of documentation describing a seam whose mechanic the errata had removed."""
    entries = len(_registries()[name])
    key = f"registry:{name}"
    if entries:
        assert key not in UNCONSUMED, (
            f"{name} has {entries} entries but is still listed in UNCONSUMED — "
            f"delete the row; a stale exemption is how the list stops being read")
        return
    assert key in UNCONSUMED, (
        f"effects.{name} is EMPTY: no card in twelve expansions uses it. Either "
        f"delete the seam (see engine.cost for how COST_MODS went) or add a "
        f"'{key}' row to UNCONSUMED in this file saying why it stays.")


@pytest.mark.parametrize("event", sorted(_event_seams()))
def test_every_event_has_a_consumer_or_is_declared_unconsumed(event):
    """An event the kernel emits that nothing listens to is the same debt in a
    different shape — and it is worse than an empty registry, because the emit
    site reads like working plumbing at every call site it appears in."""
    consumed = event in _consumed_events()
    key = f"event:{event}"
    if consumed:
        assert key not in UNCONSUMED, (
            f"the {event!r} event now HAS a consumer but is still listed in "
            f"UNCONSUMED — delete the row")
        return
    assert key in UNCONSUMED, (
        f"the kernel emits/dispatches {event!r} and no TRIGGERS spec or "
        f"add_watcher call consumes it. Either delete the seam or add a "
        f"'{key}' row to UNCONSUMED in this file saying why it stays.")


def test_no_card_registers_for_an_event_the_kernel_never_fires():
    """The reverse direction: a spec whose `on` the kernel never fires is dead
    code that LOOKS live — the failure mode of a renamed event (`play_attack`
    became `before_play` in ph. 6H) or a plain typo. Neither leaves any runtime
    signal: the card simply never triggers.

    This reads the MERGED TRIGGERS registry, which is exact — it covers all 131
    trigger-carrying cards including the loop-registered Ways, Travellers and
    Knights. Watchers are deliberately NOT checked here: their events can only
    be recovered statically, `_watcher_events` gates them against this very
    vocabulary to stay sound, and a set gated by the vocabulary can never
    contradict it. A misspelled watcher event is therefore still invisible —
    the honest statement of this check's limit, rather than a check that looks
    total and is not."""
    orphans = sorted(_trigger_events() - _event_seams())
    assert not orphans, (
        f"these events are registered for in TRIGGERS but never fired by the "
        f"kernel: {orphans} — the cards registering them can never trigger")


def test_unconsumed_rows_name_a_real_seam():
    """A row for a seam that no longer exists is the same rot as a stale test
    citation in the ambiguity list — it reads as coverage of something that is
    not there. (COST_MODS would be caught here the day someone re-adds a row
    for it without re-adding the registry.)"""
    known = ({f"registry:{n}" for n in _registries()}
             | {f"event:{e}" for e in _event_seams()})
    unknown = sorted(set(UNCONSUMED) - known)
    assert not unknown, (
        f"UNCONSUMED names seams that do not exist: {unknown}")


def test_every_unconsumed_row_gives_a_reason():
    """'We might need it later' is what kept COST_MODS alive for nine phases."""
    for key, reason in UNCONSUMED.items():
        assert len(reason) >= 80, (
            f"UNCONSUMED[{key!r}] needs a real reason — what it is for, why it "
            f"is kept rather than deleted, and what would settle it")
