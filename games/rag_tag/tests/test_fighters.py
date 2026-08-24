"""The generated data is the whole game's rules table, so it is guarded harder
than it looks like it needs.

Two failure modes this is aimed at. The first is a stale ``fighters.py``: it is
generated and committed, so an edit to ``data/*.json`` that was never re-imported
would ship silently. The second is a card naming an effect nothing implements —
which does not crash, it just quietly does nothing at the table, which is the
worst possible way for a rules bug to behave.

Every roster size here is DERIVED from the data. A hardcoded count only ever
guards the roster shrinking, and the next fighter added would go unchecked.
"""

from __future__ import annotations

import json
import pathlib

from games.rag_tag import effects, fighters
from games.rag_tag.tools import import_bga

DATA = pathlib.Path(import_bga.DATA)


def _data(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- generated

def test_fighters_py_is_not_stale():
    assert import_bga.main.__module__  # the tool imports
    built = import_bga.build()
    assert import_bga.render(built) == import_bga.OUT.read_text(encoding="utf-8"), (
        "fighters.py is stale — re-run: python -m games.rag_tag.tools.import_bga")


def test_the_generator_validates_rather_than_trusting():
    """build() is the gate, so prove it actually rejects something."""
    bad = [{"op": "attack", "target": "the_referee"}]
    try:
        effects.validate_ops(bad, "probe")
    except effects.OpError as exc:
        assert "the_referee" in str(exc)
    else:
        raise AssertionError("an unknown target was accepted")


# ------------------------------------------------------------------- roster

def test_roster_matches_the_source_data():
    boards = _data("boards.json")["fighters"]
    assert set(fighters.ROSTER) == set(boards)
    assert set(fighters.DECKS) == set(boards)
    assert set(fighters.STARTING_CARD) == set(boards)


def test_every_fighter_has_a_ten_card_deck_and_one_starting_card():
    for fid in fighters.ROSTER:
        deck = fighters.DECKS[fid]
        assert len(deck) == 10, f"{fid}: {len(deck)} cards"
        start = fighters.STARTING_CARD[fid]
        assert start in deck, f"{fid}: starting card is not in its own deck"
        assert fighters.CARDS[start]["fighter"] == fid


def test_the_whole_box_is_120_fight_cards():
    """The printed contents list says 120. Three counts have to agree."""
    total = sum(len(fighters.DECKS[fid]) for fid in fighters.ROSTER)
    assert total == 120
    assert total == sum(c["copies"] for c in fighters.CARDS.values())
    assert len(fighters.ROSTER) * 10 == total


def test_card_art_ids_are_unique_and_listed_in_sources():
    listed = set()
    for entry in _data("sources.json")["fighters"].values():
        for path in entry["cards"]:
            listed.add(int(path.rsplit("-", 1)[1].split(".")[0]))

    seen: set[int] = set()
    for cid, card in fighters.CARDS.items():
        for art in card["art_ids"]:
            assert art not in seen, f"card {cid}: art id {art} used twice"
            seen.add(art)
    assert seen == listed, "card art ids and sources.json disagree"


# ------------------------------------------------------------ health tracks

def test_every_health_track_can_end_a_fighter():
    for fid in fighters.ROSTER:
        board = fighters.FIGHTERS[fid]
        tracks = []
        if board.get("hp_track"):
            tracks.append((fid, board["hp_track"]))
        for ch in board.get("characters", ()):
            tracks.append((f"{fid}/{ch['id']}", ch["hp_track"]))
        assert tracks, f"{fid}: no health track anywhere"
        for label, track in tracks:
            kinds = {s["kind"] for s in track}
            assert kinds & {"ko", "spirit"}, f"{label}: cannot be finished"


def test_exactly_one_start_space_per_track():
    for fid in fighters.ROSTER:
        board = fighters.FIGHTERS[fid]
        tracks = [t for t in [board.get("hp_track")] if t]
        tracks += [ch["hp_track"] for ch in board.get("characters", ())]
        for track in tracks:
            assert sum(1 for s in track if s.get("start")) == 1, fid


def test_the_wild_bunch_moves_at_most_one_space_a_turn():
    """Their whole identity is a stop on every space below the top."""
    track = fighters.FIGHTERS["the_wild_bunch"]["hp_track"]
    hp = [s for s in track if s["kind"] == "hp"]
    top = max(s["hp"] for s in hp)
    for space in hp:
        has_stop = "stop" in space.get("icons", [])
        assert has_stop == (space["hp"] != top), f"HP {space['hp']}"


def test_maman_brijit_can_come_back_from_the_dead():
    track = fighters.FIGHTERS["maman_brijit"]["hp_track"]
    assert [s["kind"] for s in track[:3]] == ["revive", "ko", "ko"], (
        "her revive space must sit BELOW both KO spaces — that is the whole trick")
    assert fighters.FIGHTERS["maman_brijit"]["revive_to_hp"] == 4


# ------------------------------------------------------------------ effects

def _all_op_lists():
    """Every op list in the game, with a path, so a failure names the culprit."""
    for cid, card in fighters.CARDS.items():
        where = f"card {cid} ({card['name']})"
        yield f"{where}.ops", card["ops"]
        if "ops_back" in card:
            yield f"{where}.ops_back", card["ops_back"]
        if "instant_bonus" in card:
            yield f"{where}.instant_bonus", card["instant_bonus"]
    for fid in fighters.ROSTER:
        board = fighters.FIGHTERS[fid]
        yield f"{fid}.setup_icons", board.get("setup_icons", [])
        tracks = [t for t in [board.get("hp_track")] if t]
        tracks += [ch["hp_track"] for ch in board.get("characters", ())]
        for track in tracks:
            for space in track:
                icons = [i for i in space.get("icons", []) if not isinstance(i, str)]
                yield f"{fid}.hp_track.icons", icons
        special = board.get("special_track")
        for space in (special or {}).get("spaces", ()):
            yield f"{fid}.{special['id']}[{space['name']}]", space.get("icons", [])
    for eff in fighters.MILADY_SCHEMES["effects"]:
        yield f"milady_scheme[{eff['id']}]", eff["ops"]


def test_every_op_in_the_game_validates():
    for path, ops in _all_op_lists():
        effects.validate_ops(ops, path)


def _data_fx_names() -> set[str]:
    found: set[str] = set()
    for _, ops in _all_op_lists():
        effects.collect_fx_names(ops, found)
    return found


def test_every_fx_the_data_names_is_accounted_for():
    """Implemented, or explicitly listed as not yet. Never neither."""
    used = _data_fx_names()
    known = set(effects.FIGHTER_FX) | set(effects.UNIMPLEMENTED_FX)
    assert used <= known, f"unhandled effects: {sorted(used - known)}"


def test_the_unimplemented_list_does_not_rot():
    used = _data_fx_names()
    stale = set(effects.UNIMPLEMENTED_FX) - used
    assert not stale, f"UNIMPLEMENTED_FX names effects no card uses: {sorted(stale)}"
    both = set(effects.FIGHTER_FX) & set(effects.UNIMPLEMENTED_FX)
    assert not both, f"implemented AND listed as unimplemented: {sorted(both)}"


def test_milady_has_nine_distinct_schemes_across_eleven_tokens():
    schemes = fighters.MILADY_SCHEMES
    ids = [e["id"] for e in schemes["effects"]]
    assert len(ids) == len(set(ids)) == 9
    assert schemes["total_tokens"] == 11
    assert fighters.FIGHTERS["milady"]["tokens"]["scheme"] == 11


def test_no_transcription_artefacts_reach_the_table():
    """`--` is a shell-safety habit, not punctuation, and it shipped to a card.

    The rules notes are prose I typed, and the detail modal renders them
    verbatim, so a double hyphen lands on screen mid-sentence looking like
    unprocessed source data. Cheap to assert, and the only place it can be
    caught is here -- the engine never reads these strings.
    """
    bad = []
    for card in fighters.CARDS.values():
        for field in ("name", "note"):
            text = card.get(field) or ""
            if "--" in text:
                bad.append(f"{card['name']}.{field}")
    for fid, board in fighters.FIGHTERS.items():
        if "--" in (board.get("name") or ""):
            bad.append(f"{fid}.name")
    assert not bad, f"double hyphens reach the UI in: {bad}"
