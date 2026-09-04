"""Technology-board helpers for Orbit."""

from __future__ import annotations

from .cards import FACTIONS, TECHNOLOGIES


# Printed strip references are S/D (Robot), U/O (Human), and N/P
# (Animod). The rulebook's learning layout uses the first face of each: S.U.N.
SUN_CONFIGURATION = {"robot": 1, "human": 1, "animod": 1}


def random_configuration(rng) -> dict[str, int]:
    """Choose one of the two printed sides independently for each faction."""

    return {faction: rng.choice((1, 2)) for faction in FACTIONS}


def board_reference(configuration: dict[str, int]) -> dict[str, list[dict]]:
    """Return the five visible effects for each assembled board strip."""

    return {
        faction: [
            {
                "level": level,
                "description": TECHNOLOGIES[(faction, configuration[faction], level)][
                    "description"
                ],
            }
            for level in range(1, 6)
        ]
        for faction in FACTIONS
    }
