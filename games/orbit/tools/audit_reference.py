"""Human-readable audit of the imported Orbit mechanical reference."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


OP_RE = re.compile(r"(?:^|[_=>|])(\d+),")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("--ops", action="store_true")
    parser.add_argument("--cards", action="store_true")
    args = parser.parse_args()

    data = json.loads(args.reference.read_text(encoding="utf-8"))
    cards = list(data["card_ref"].values())
    base = [card for card in cards if not int(card.get("goodies", 0))]
    print(f"cards={len(cards)} base={len(base)} optional={len(cards) - len(base)}")
    for planet in range(1, 6):
        for race in range(1, 4):
            count = sum(
                int(card["planet"]) == planet and int(card["race"]) == race
                for card in base
            )
            print(f"planet={planet} race={race}: {count}")

    if args.cards:
        for card in sorted(base, key=lambda item: int(item["num"])):
            print(
                f"{card['num']}|P{card['planet']}|R{card['race']}|"
                f"C{card['cost']}|{card['name']}|{card['rule']}|{card['desc']}"
            )

    if not args.ops:
        return
    grouped: dict[int, list[str]] = defaultdict(list)
    refs = base + list(data["tech_ref"].values()) + list(data["bonus_ref"].values())
    for ref in refs:
        label = ref.get("name") or ref.get("desc", "")
        for op in OP_RE.findall(ref.get("rule", "")):
            grouped[int(op)].append(f"{label}: {ref['rule']}")
    for op, examples in sorted(grouped.items()):
        print(f"\nOP {op} ({len(examples)})")
        for example in examples[:10]:
            print(f"  {example}")


if __name__ == "__main__":
    main()
