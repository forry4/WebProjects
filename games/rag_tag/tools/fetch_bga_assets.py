"""Re-download the public BGA art the data/ transcription was read from.

The images are the publisher's and are NOT committed; only the mechanical transcription
in data/boards.json and data/cards.json is. This script exists so a correction can be
checked against the same pixels the transcription was made from.

    python -m games.rag_tag.tools.fetch_bga_assets [--out DIR]

Everything it fetches is served without a login. Nothing here is imported at runtime.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import urllib.request

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "rag-tag-import/1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="_bga_assets", help="directory to write into")
    args = ap.parse_args()

    src = json.loads((DATA / "sources.json").read_text(encoding="utf-8"))
    base, out = src["base_url"], pathlib.Path(args.out)

    rel = [src["client_bundle"].rsplit("/", 1)[1], src["client_css"].rsplit("/", 1)[1]]
    for entry in src["fighters"].values():
        rel.append(entry["board"])
        rel.append(entry["draft"])
        if "board_back" in entry:
            rel.append(entry["board_back"])
        rel.extend(entry["cards"])

    ok = 0
    for path in rel:
        dest = out / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_bytes(_get(f"{base}/{path}"))
        except Exception as exc:  # noqa: BLE001 - a missing asset is worth naming, not raising
            print(f"FAIL {path}: {exc}")
            continue
        ok += 1

    print(f"{ok}/{len(rel)} assets -> {out}")
    print(f"rulebook (12.9MB PDF, not fetched here): {src['rulebook']}")
    return 0 if ok == len(rel) else 1


if __name__ == "__main__":
    raise SystemExit(main())
