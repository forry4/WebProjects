"""Merged card-effect registries.

Each effects_* module owns a disjoint set of cards and exports EFFECTS/STAGES
(see effects_core.py for the contract). This module is the single lookup point
the engine uses; a duplicate registration is a packaging bug and raises.
"""

from . import (effects_core, effects_base_a, effects_base_b,
               effects_intrigue_a, effects_intrigue_b,
               effects_seaside_a, effects_seaside_b)

_MODULES = (effects_core, effects_base_a, effects_base_b,
            effects_intrigue_a, effects_intrigue_b,
            effects_seaside_a, effects_seaside_b)

EFFECTS = {}
STAGES = {}
GAIN_REACTIONS = {}    # card -> {"stage": str, "when": fn(gained_name) -> bool}
CLEANUP_PROMPTS = {}   # card -> {"when": fn(game, pid) -> bool, "push": fn(game, pid)}

for _m in _MODULES:
    for _name, _fn in _m.EFFECTS.items():
        if _name in EFFECTS:
            raise RuntimeError(f"dontminion: duplicate EFFECTS entry {_name!r}")
        EFFECTS[_name] = _fn
    for _key, _fn in _m.STAGES.items():
        if _key in STAGES:
            raise RuntimeError(f"dontminion: duplicate STAGES entry {_key!r}")
        STAGES[_key] = _fn
    for _name, _spec in getattr(_m, "GAIN_REACTIONS", {}).items():
        if _name in GAIN_REACTIONS:
            raise RuntimeError(f"dontminion: duplicate GAIN_REACTIONS entry {_name!r}")
        GAIN_REACTIONS[_name] = _spec
    for _name, _spec in getattr(_m, "CLEANUP_PROMPTS", {}).items():
        if _name in CLEANUP_PROMPTS:
            raise RuntimeError(f"dontminion: duplicate CLEANUP_PROMPTS entry {_name!r}")
        CLEANUP_PROMPTS[_name] = _spec
