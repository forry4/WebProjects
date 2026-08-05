"""Merged card-effect registries.

ONE effects_* module per expansion, each owning a disjoint set of cards and
exporting EFFECTS/STAGES (contract: games/dontminion/CLAUDE.md). This module is
the single lookup point the engine uses; a duplicate registration across
modules is a packaging bug and raises at import.
"""

from . import (effects_base, effects_intrigue, effects_seaside, effects_prosperity,
               effects_hinterlands, effects_cornucopia, effects_alchemy,
               effects_darkages, effects_adventures, effects_empires)

_MODULES = (effects_base, effects_intrigue, effects_seaside, effects_prosperity,
            effects_hinterlands, effects_cornucopia, effects_alchemy,
            effects_darkages, effects_adventures, effects_empires)

EFFECTS = {}
STAGES = {}
# The trigger-bus registries (see engine.py "THE TRIGGER BUS" for the spec
# shapes): TRIGGERS = {card: [{"on": event, "from": source, ...}, ...]};
# COST_MODS = {card: fn(game, priced_name) -> reduction per in-play copy}.
TRIGGERS = {}
COST_MODS = {}
DYN_COSTS = {}          # card -> fn(game) -> reduction on the card's OWN cost (Peddler)
BUY_GATES = {}          # card -> fn(game, pid) -> error string | None (Grand Market)
MANUAL_TREASURES = set()  # treasures play_all must skip (interactive: Anvil-class)
# Treasures whose VALUE depends on what else is already in play, so play_all
# must play them AFTER the rest (Bank). Membership means "later is never
# worse" — a card where the player might genuinely want it early belongs in
# MANUAL_TREASURES instead, since the button must not choose for them.
AUTOPLAY_LAST = set()
# card -> reaction spec for the attack window (see engine.attack_reactions)
ATTACK_REACTIONS = {}
# (card, stage) -> fn(game, watcher, ctx) -> bool: does this WATCHER actually
# fire for this occurrence? Evaluated by emit() at JOIN time (p25 §3 — triggers
# are based on the actual occurrence), so a watcher whose ability would no-op
# (Monkey on anyone but the right-hand neighbour, a spent Sailor) never enters
# the ability pool and never pollutes the what-resolves-first prompt. The stage
# keeps its own guard as the resolve-time re-check.
WATCHER_WHENS = {}
# ph. 6H: landscape_name -> fn(game, pid) — the ability an Event/Project hands
# you when you BUY it. Same shape as EFFECTS, on the other table: a landscape
# is not a card (see cards.LANDSCAPES), so it cannot live in EFFECTS without
# making every `card in EFFECTS` test wrong.
LANDSCAPE_FX = {}
# ph. 7H: landscape_name -> fn(game, pid) -> int — what a LANDMARK adds to (or
# subtracts from) a player's score. Summed into engine._total_vp for every
# landscape DEALT to the game, so it is live all game, not only at the end.
LANDSCAPE_SCORING = {}
# ph. 7H: landscape_name -> fn(game, rng) — a landscape whose SETUP needs the
# board (Obelisk picks an Action pile, Tax and Aqueduct write pile attachments).
# Run by new_game once every pile exists, before the opening deal.
LANDSCAPE_SETUP = {}

for _m in _MODULES:
    for _name, _fn in _m.EFFECTS.items():
        if _name in EFFECTS:
            raise RuntimeError(f"dontminion: duplicate EFFECTS entry {_name!r}")
        EFFECTS[_name] = _fn
    for _key, _fn in _m.STAGES.items():
        if _key in STAGES:
            raise RuntimeError(f"dontminion: duplicate STAGES entry {_key!r}")
        STAGES[_key] = _fn
    for _name, _specs in getattr(_m, "TRIGGERS", {}).items():
        if _name in TRIGGERS:
            raise RuntimeError(f"dontminion: duplicate TRIGGERS entry {_name!r}")
        TRIGGERS[_name] = _specs
    for _name, _fn in getattr(_m, "COST_MODS", {}).items():
        if _name in COST_MODS:
            raise RuntimeError(f"dontminion: duplicate COST_MODS entry {_name!r}")
        COST_MODS[_name] = _fn
    for _name, _fn in getattr(_m, "DYN_COSTS", {}).items():
        if _name in DYN_COSTS:
            raise RuntimeError(f"dontminion: duplicate DYN_COSTS entry {_name!r}")
        DYN_COSTS[_name] = _fn
    for _name, _fn in getattr(_m, "BUY_GATES", {}).items():
        if _name in BUY_GATES:
            raise RuntimeError(f"dontminion: duplicate BUY_GATES entry {_name!r}")
        BUY_GATES[_name] = _fn
    for _name in getattr(_m, "MANUAL_TREASURES", ()):
        MANUAL_TREASURES.add(_name)
    for _name in getattr(_m, "AUTOPLAY_LAST", ()):
        AUTOPLAY_LAST.add(_name)
    for _name, _spec in getattr(_m, "ATTACK_REACTIONS", {}).items():
        if _name in ATTACK_REACTIONS:
            raise RuntimeError(f"dontminion: duplicate ATTACK_REACTIONS entry {_name!r}")
        ATTACK_REACTIONS[_name] = _spec
    for _key, _fn in getattr(_m, "WATCHER_WHENS", {}).items():
        if _key in WATCHER_WHENS:
            raise RuntimeError(f"dontminion: duplicate WATCHER_WHENS entry {_key!r}")
        WATCHER_WHENS[_key] = _fn
    for _name, _fn in getattr(_m, "LANDSCAPE_FX", {}).items():
        if _name in LANDSCAPE_FX:
            raise RuntimeError(f"dontminion: duplicate LANDSCAPE_FX entry {_name!r}")
        LANDSCAPE_FX[_name] = _fn
    for _name, _fn in getattr(_m, "LANDSCAPE_SCORING", {}).items():
        if _name in LANDSCAPE_SCORING:
            raise RuntimeError(f"dontminion: duplicate LANDSCAPE_SCORING entry {_name!r}")
        LANDSCAPE_SCORING[_name] = _fn
    for _name, _fn in getattr(_m, "LANDSCAPE_SETUP", {}).items():
        if _name in LANDSCAPE_SETUP:
            raise RuntimeError(f"dontminion: duplicate LANDSCAPE_SETUP entry {_name!r}")
        LANDSCAPE_SETUP[_name] = _fn
