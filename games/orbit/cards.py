"""Canonical Orbit card, technology, and bonus-token data.

The payload is extracted from Board Game Arena's public Zenith client data by
``tools/extract_bga.py``.  Keeping the original rule strings beside the English
descriptions gives the engine a compact, auditable link back to the reference.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final


_DATA_PATH = Path(__file__).with_name("data") / "bga_reference.json"
_RAW = json.loads(_DATA_PATH.read_text(encoding="utf-8"))

PLANETS: Final[tuple[str, ...]] = (
    "mercury",
    "venus",
    "terra",
    "mars",
    "jupiter",
)
PLANET_NAMES: Final[dict[int, str]] = {
    int(key): value["name"] for key, value in _RAW["planet_ref"].items()
}
PLANET_COLORS: Final[dict[str, str]] = {
    value["name"].lower(): f"#{value['color']}"
    for value in _RAW["planet_ref"].values()
}

FACTIONS: Final[tuple[str, ...]] = ("robot", "human", "animod")
FACTION_NAMES: Final[dict[int, str]] = {
    int(key): value["name"] for key, value in _RAW["race_ref"].items()
}


def _card(raw: dict) -> dict:
    return {
        "id": int(raw["num"]),
        "name": str(raw["name"]),
        "planet": PLANET_NAMES[int(raw["planet"])].lower(),
        "faction": FACTION_NAMES[int(raw["race"])].lower(),
        "cost": int(raw["cost"]),
        "rule": str(raw["rule"]),
        "description": str(raw["desc"]),
    }


# The ten ``goodies`` cards are the Secret Agents mini-expansion.  Orbit v1 is
# deliberately the 90-card base game requested by the user.
CARDS: Final[dict[int, dict]] = {
    int(key): _card(value)
    for key, value in _RAW["card_ref"].items()
    if not int(value.get("goodies", 0))
}


def _technology(raw: dict) -> dict:
    return {
        "id": int(raw["id"]),
        "faction": FACTION_NAMES[int(raw["race"])].lower(),
        "side": int(raw["ab"]),
        "level": int(raw["step"]),
        "rule": str(raw["rule"]),
        "description": str(raw["desc"]),
    }


TECHNOLOGIES: Final[dict[tuple[str, int, int], dict]] = {}
for _raw_tech in _RAW["tech_ref"].values():
    _tech = _technology(_raw_tech)
    TECHNOLOGIES[(_tech["faction"], _tech["side"], _tech["level"])] = _tech


BONUS_TYPES: Final[dict[int, dict]] = {
    int(key): {
        "type": int(value["num"]),
        "count": int(value["nb"]),
        "rule": str(value["rule"]),
        "description": str(value["desc"]),
    }
    for key, value in _RAW["bonus_ref"].items()
}
BONUS_POOL: Final[tuple[int, ...]] = tuple(
    token_type
    for token_type, value in BONUS_TYPES.items()
    for _ in range(value["count"])
)


def card(card_id: int) -> dict:
    """Return the immutable reference record for ``card_id``."""

    return CARDS[int(card_id)]


def technology(faction: str, side: int, level: int) -> dict:
    """Return one board-space effect."""

    return TECHNOLOGIES[(faction, int(side), int(level))]


def public_card(card_id: int) -> dict:
    """Return the stable wire-safe card fields used by the React client."""

    value = card(card_id)
    return {
        "id": value["id"],
        "name": value["name"],
        "planet": value["planet"],
        "faction": value["faction"],
        "cost": value["cost"],
        "description": value["description"],
    }


def validate_reference() -> None:
    """Fail loudly if regenerated source data no longer matches the base game."""

    if len(CARDS) != 90:
        raise ValueError(f"Orbit must contain 90 base cards, found {len(CARDS)}")
    for planet in PLANETS:
        for faction in FACTIONS:
            found = sum(
                c["planet"] == planet and c["faction"] == faction
                for c in CARDS.values()
            )
            if found != 6:
                raise ValueError(f"Expected 6 {planet}/{faction} cards, found {found}")
    if len(TECHNOLOGIES) != 30:
        raise ValueError(f"Orbit must contain 30 technology effects, found {len(TECHNOLOGIES)}")
    if len(BONUS_POOL) != 16:
        raise ValueError(f"Orbit must contain 16 bonus tokens, found {len(BONUS_POOL)}")


validate_reference()
