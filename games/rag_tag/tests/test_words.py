"""Every mechanic in the data has WORDS in the UI, or the modal makes something up.

Rag Tag's card and board data is mechanics only — no publisher text — so the
frontend writes every sentence a player reads from op names, token ids and
track ids. Each of those lookups has a fallback, and every fallback is a
plausible-looking lie: an unglossed `fx` renders as the literal word "Special",
an unmapped token renders its JSON key ("Starts with 1 presence"), an unmapped
track renders its field name ("+1 navigation"), and an unnamed op renders
`op.op`. None of that throws, none of it fails a render test, and all of it
ships looking like a deliberate design choice.

That is not hypothetical — it is what the modal did until 2026-08-27. It named
KO, stop, icon and revive in the key of all twelve boards, nine of which have no
revive space; it said "Has a divine voice track of 5 spaces" and never drew it;
and it printed the raw ids `navigation`, `presence` and `scheme` on card faces.

So these read the JSX as TEXT and hold it to the DATA. The roster is derived
from `fighters.py`, never listed here, because a hardcoded list only guards the
data shrinking — a thirteenth fighter would join unguarded, which is exactly the
`range(13)` shape CLAUDE.md warns about.
"""
import re
from pathlib import Path

from games.rag_tag.fighters import CARDS, FIGHTERS

#: the five bars the printed Fighters' Guide rates every Fighter on
RATED = ("health", "offense", "defense", "heal", "special")

HERE = Path(__file__).resolve().parents[1]
ART = (HERE / "art.jsx").read_text(encoding="utf-8")
UI = (HERE / "RagTag.jsx").read_text(encoding="utf-8")


def _keys(src: str, name: str) -> set[str]:
    """The top-level keys of an exported object literal in a .jsx file."""
    m = re.search(rf"^export const {name} = \{{$(.*?)^\}};$", src, re.M | re.S)
    assert m, f"{name} is no longer an exported object literal — this guard has rotted"
    return set(re.findall(r"^  ([A-Za-z_][A-Za-z0-9_]*):", m.group(1), re.M))


def _cases(name: str) -> set[str]:
    """The `case "x":` labels inside one function in RagTag.jsx."""
    m = re.search(rf"^function {name}\(.*?^\}}$", UI, re.M | re.S)
    assert m, f"{name}() is gone from RagTag.jsx — this guard has rotted"
    return set(re.findall(r'case "([a-z_]+)":', m.group(0)))


def _walk_ops(ops, out):
    for op in ops or ():
        out.append(op)
        for key in ("then", "else", "success"):
            _walk_ops(op.get(key), out)


def _every_op():
    """Every op the game can put in front of a player, from all three sources."""
    out = []
    for card in CARDS.values():
        for key in ("ops", "ops_back", "instant_bonus"):
            _walk_ops(card.get(key), out)
    for board in FIGHTERS.values():
        _walk_ops(board.get("setup_icons"), out)
        tracks = [board.get("hp_track")] + [c["hp_track"] for c in board.get("characters", ())]
        if board.get("back"):
            tracks.append(board["back"].get("hp_track"))
        for space in (board.get("special_track") or {}).get("spaces", ()):
            _walk_ops([ic for ic in space.get("icons", ()) if not isinstance(ic, str)], out)
        for track in tracks:
            for space in track or ():
                _walk_ops([ic for ic in space.get("icons", ()) if not isinstance(ic, str)], out)
    return out


def test_every_special_ability_in_the_data_has_words():
    """An `fx` with no entry renders as the literal word "Special"."""
    named = {op["name"] for op in _every_op() if op["op"] == "fx"}
    assert named <= _keys(ART, "FX_TEXT"), "fx with no FX_TEXT — renders as 'Special'"


def test_every_op_the_data_uses_has_a_sentence():
    """`opCore`'s default returns `op.op`, i.e. the JSON key, on a card face."""
    used = {op["op"] for op in _every_op()}
    assert used <= _cases("opCore"), "op with no case in opCore — renders its own JSON key"


def test_every_condition_the_data_uses_has_a_sentence():
    """`condWords` falls through to `cond.kind` — "If power_at_least: Attack"."""
    used = {op["cond"]["kind"] for op in _every_op() if op["op"] == "if"}
    assert used <= _cases("condWords"), "condition with no case in condWords"


def test_every_token_on_a_board_is_named_and_explained():
    held = {t for b in FIGHTERS.values() for t, n in (b.get("tokens") or {}).items() if n}
    assert held <= _keys(ART, "TOKEN_WORD"), "token with no printed name — shows its JSON key"
    assert held <= _keys(ART, "TOKEN_GLOSSARY"), "token nothing in the UI can explain"


def test_every_special_track_is_named_and_explained():
    ids = {b["special_track"]["id"] for b in FIGHTERS.values() if b.get("special_track")}
    # ...and every track a CARD steps, which need not be a board's own: an op
    # naming a track no board has would advance nothing and say so in the JSON key.
    ids |= {op["track"] for op in _every_op() if op["op"] == "track"}
    assert ids <= _keys(ART, "TRACK_WORD"), "track with no printed name — '+1 navigation'"
    assert ids <= _keys(ART, "TRACK_GLOSSARY"), "track the modal cannot explain"


def test_every_complexity_rating_has_a_word():
    """The number alone was "N of 5 to learn" — a scale nobody is shown the ends of.

    Derived from the data, so a sixth tier fails here rather than rendering an
    empty chip with a label and no value in it.
    """
    m = re.search(r"^export const COMPLEXITY_WORD = \[(.*?)\];$", ART, re.M)
    assert m, "COMPLEXITY_WORD is gone from art.jsx — this guard has rotted"
    words = re.findall(r'"([^"]*)"', m.group(1))
    rated = {b["complexity"] for b in FIGHTERS.values() if b.get("complexity") is not None}
    for n in sorted(rated):
        assert 0 <= n < len(words) and words[n], f"complexity {n} has no word"


def test_every_fighter_has_a_profile_the_draft_can_be_read_from():
    """Epithet, paragraph and five rating bars, mirroring the Fighters' Guide.

    This is the half of a board that is a judgement rather than a rule, and the
    only part of the modal that answers "is this Fighter for me" — the question
    the draft actually asks. A board that gains none of it renders a modal that
    looks complete and opens on the mechanics.
    """
    for fid, board in FIGHTERS.items():
        assert board.get("title"), f"{fid} has no epithet"
        assert len(board.get("profile") or "") > 120, f"{fid}'s profile is a stub"
        rating = board.get("rating") or {}
        assert set(rating) == set(RATED), f"{fid} rates {sorted(rating)}"
        for k, v in rating.items():
            assert isinstance(v, int) and 0 <= v <= 5, f"{fid}.{k} = {v!r}"


def test_the_rating_bars_the_ui_draws_are_the_ones_the_data_carries():
    """`RATED` in the JSX and the keys in boards.json are one list seen twice."""
    m = re.search(r"^const RATED = \[(.*?)\];$", UI, re.M)
    assert m, "RATED is gone from RagTag.jsx — this guard has rotted"
    assert set(re.findall(r'"([a-z]+)"', m.group(1))) == set(RATED)


def test_a_circular_track_is_drawn_as_a_circle():
    """Joan's dial rendered as a row of boxes — the one shape a ring is not.

    A straight line cannot show that the last space leads back to the first, nor
    that the centre is entered once and never returned to. The browser gate can
    only check this when Joan happens to be drafted, so the structural half is
    here: the data says a track is circular, the UI must have something that
    draws one, and `SpecialTrack` must actually branch to it.
    """
    shapes = {(b.get("special_track") or {}).get("shape") for b in FIGHTERS.values()}
    if "circular" not in shapes:
        raise AssertionError(
            "no fighter has a circular track any more — delete this guard rather "
            "than letting it pass over nothing")
    assert "function DialRing(" in UI, "a circular track in the data and nothing to draw it"
    special = re.search(r"^function SpecialTrack\(.*?^\}$", UI, re.M | re.S)
    assert special, "SpecialTrack() is gone from RagTag.jsx — this guard has rotted"
    assert "<DialRing" in special.group(0), (
        "SpecialTrack no longer reaches DialRing — a ring would draw as a row of pips")


def test_a_board_of_characters_shows_all_of_them_on_the_fighting_card():
    """The card showed only the Character on the board.

    So the Fey Folk read "3/3" while carrying nine more health in two Characters
    nobody could see, and there was no way to tell which had already gone. Same
    shape as the guard above: sampled in the browser, structural here.
    """
    if not any(b.get("characters") for b in FIGHTERS.values()):
        raise AssertionError(
            "no fighter has Characters any more — delete this guard rather than "
            "letting it pass over nothing")
    assert "function CharacterRoster(" in UI, "Characters in the data and nothing to list them"
    card = re.search(r"^function FighterCard\(.*?^\}$", UI, re.M | re.S)
    assert card, "FighterCard() is gone from RagTag.jsx — this guard has rotted"
    assert "<CharacterRoster" in card.group(0), (
        "the fighting card no longer lists the Characters behind the one on the board")


def test_every_kind_of_space_is_in_the_key_and_the_key_is_ordered():
    kinds = set()
    for board in FIGHTERS.values():
        tracks = [board.get("hp_track")] + [c["hp_track"] for c in board.get("characters", ())]
        if board.get("back"):
            tracks.append(board["back"].get("hp_track"))
        for track in tracks:
            for space in track or ():
                if space["kind"] != "hp":
                    kinds.add(space["kind"])
                if "stop" in (space.get("icons") or ()):
                    kinds.add("stop")
                if space["kind"] == "hp" and any(not isinstance(ic, str)
                                                 for ic in space.get("icons") or ()):
                    kinds.add("icon")
    glossed = _keys(ART, "SPACE_GLOSSARY")
    assert kinds <= glossed, "a kind of space the board key cannot name"

    m = re.search(r"^const KIND_ORDER = \[(.*?)\];$", UI, re.M)
    assert m, "KIND_ORDER is gone from RagTag.jsx — this guard has rotted"
    ordered = set(re.findall(r'"([a-z]+)"', m.group(1)))
    # A kind missing from KIND_ORDER is filtered OUT of the key entirely, so the
    # board draws a colour with nothing saying what it means.
    assert glossed == ordered, "SPACE_GLOSSARY and KIND_ORDER disagree"


def test_the_fx_words_are_not_the_boards_own_icons_said_twice():
    """Bödvar's Rage space holds `power 3` AND the transform fx, side by side.

    FX_TEXT used to repeat the Power, so the read-out said "+3 Power — you, Rage
    tops out: +3 Power, then become the Berserker Bear".
    """
    for board in FIGHTERS.values():
        for space in (board.get("special_track") or {}).get("spaces", ()):
            icons = [ic for ic in space.get("icons", ()) if not isinstance(ic, str)]
            powers = [ic for ic in icons if ic["op"] == "power"]
            for fx in (ic for ic in icons if ic["op"] == "fx"):
                m = re.search(rf'^  {fx["name"]}: "(.*)",$', ART, re.M)
                assert m, fx["name"]
                for power in powers:
                    assert f"{power['n']} Power" not in m.group(1), (
                        f"{fx['name']} repeats the Power op it shares a space with")
