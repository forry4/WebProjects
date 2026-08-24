"""`HISTORY_LIMIT` is one number seen from two ends — guard the seam.

`core.rooms.HISTORY_LIMIT` is the SQL cap on every game's `list_user_history`;
`HISTORY_MAX` in `shared/lobby.jsx` is where the lobby's progressive History
list stops asking for more. They are the same ceiling, and nothing at runtime
notices when they disagree — the failure is silent and directional. If the
server drops below the client, the last page is short and the reader is left
scrolling at a sentinel that never resolves; if the client drops below the
server, rows are fetched and never shown. Both look like "history is fine".

This lives in core/tests because the constant does, and it deliberately reads
the JSX as TEXT rather than importing any game: `core/` may not depend on a
feature, and that rule holds for its tests too.
"""
import re
from pathlib import Path

from core import rooms as _rooms

LOBBY_JSX = Path(__file__).resolve().parents[2] / "shared" / "lobby.jsx"


def _const(name: str) -> int:
    src = LOBBY_JSX.read_text(encoding="utf-8")
    m = re.search(rf"^export const {name} = (\d+);", src, re.M)
    assert m, f"{name} is no longer declared in shared/lobby.jsx — this guard has rotted"
    return int(m.group(1))


def test_the_client_cap_matches_the_sql_cap():
    assert _const("HISTORY_MAX") == _rooms.HISTORY_LIMIT


def test_a_page_is_smaller_than_the_cap_and_divides_it():
    """A page bigger than the cap would mean the whole list on the first render
    (no paging at all), and one that doesn't divide it makes the final page a
    stub — reachable only by an odd edit, so say so here rather than at 3am."""
    page, cap = _const("HISTORY_PAGE"), _rooms.HISTORY_LIMIT
    assert 0 < page < cap
    assert cap % page == 0, f"{cap} games in pages of {page} leaves a stub page"
