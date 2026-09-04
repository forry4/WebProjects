"""Extract public mechanical reference tables from a BGA Zenith replay page.

The replay HTML embeds the exact setup object passed to the public browser client.
This tool keeps only mechanical tables: card names/costs/factions/rule codes, board
effects, bonus-token counts, and lookup vocabularies.  It deliberately does not
download or commit publisher artwork.

Usage::

    python -m games.orbit.tools.extract_bga replay.html data/bga_reference.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


MARKER = 'completesetup( "zenith"'
REFERENCE_KEYS = (
    "card_ref",
    "bonus_ref",
    "tech_ref",
    "planet_ref",
    "race_ref",
    "help_ref",
    "techs",
)


def _object_after(text: str, marker: str) -> dict:
    """Return the first complete JSON object after *marker*.

    A non-greedy regular expression is unsafe here because the object contains
    nested arrays and objects.  This small scanner understands JSON strings and
    escapes, then hands the exact slice to the standard decoder.
    """

    marker_at = text.find(marker)
    if marker_at < 0:
        raise ValueError("Zenith completesetup call not found")
    start = text.find("{", marker_at + len(marker))
    if start < 0:
        raise ValueError("setup object start not found")

    depth = 0
    quoted = False
    escaped = False
    for pos in range(start, len(text)):
        char = text[pos]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : pos + 1])
    raise ValueError("setup object is unterminated")


def extract_reference(html: str, source_url: str = "") -> dict:
    setup = _object_after(html, MARKER)
    missing = [key for key in REFERENCE_KEYS if key not in setup]
    if missing:
        raise ValueError(f"setup object is missing reference keys: {missing}")
    return {
        "_source": source_url,
        "_note": "Public BGA replay setup; mechanical data only; no artwork.",
        **{key: setup[key] for key in REFERENCE_KEYS},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("html", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-url", default="")
    args = parser.parse_args()

    reference = extract_reference(args.html.read_text(encoding="utf-8"), args.source_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(reference, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    cards = reference["card_ref"]
    base = sum(not int(card.get("goodies", 0)) for card in cards.values())
    extra = len(cards) - base
    print(
        f"wrote {args.output}: {base} base cards, {extra} optional cards, "
        f"{len(reference['tech_ref'])} technology effects"
    )


if __name__ == "__main__":
    main()
