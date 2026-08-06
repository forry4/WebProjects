"""MENAGERIE (phase 10) — the union of the two batch halves.

Card batches are written in two halves by parallel agents that may touch only
the files they own (`games/dontminion/CLAUDE.md`). This module is the seam:
each registry is declared ONCE here and the halves only `.update()` into it, so
a name registered by both halves is caught by `effects.py`'s duplicate check
rather than one half silently winning.

Half A owns the 20 cards whose interest is their own play ability plus the 20
Events; half B owns the 20 WAYS, the self-playing Reactions, the Attacks, the
Durations and the two Treasures.
"""

from . import effects_menagerie_a as _a, effects_menagerie_b as _b

_HALVES = (_a, _b)

_DICTS = ("EFFECTS", "STAGES", "TRIGGERS", "COST_MODS", "DYN_COSTS",
          "COST_OVERRIDE", "BUY_PAY_ALT", "BUY_GATES", "ATTACK_REACTIONS",
          "WATCHER_WHENS", "LANDSCAPE_FX", "LANDSCAPE_SCORING",
          "LANDSCAPE_SETUP")
_SETS = ("MANUAL_TREASURES", "AUTOPLAY_LAST")

for _name in _DICTS:
    _merged = {}
    for _h in _HALVES:
        for _k, _v in getattr(_h, _name, {}).items():
            if _k in _merged:
                raise RuntimeError(
                    f"dontminion: both Menagerie halves registered {_name} {_k!r}")
            _merged[_k] = _v
    globals()[_name] = _merged

for _name in _SETS:
    globals()[_name] = set().union(*(getattr(_h, _name, set()) for _h in _HALVES))
