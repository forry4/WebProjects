# Books (site feature — not a game)

Standalone page for ranking favorite books + collecting reading suggestions. Deliberately its own
top-level package (neither a game nor part of Spender).

- **Backend** (`api.py`) — tables in the shared DB (`books`, `books_meta`, `book_suggestions`).
  **Wired into the app via dependency injection** (`setup_books(app, get_db_conn, get_user_by_session,
  token_resolver)`) so `books` never imports a game (no cycle). Pure functions unit-tested against
  `:memory:`. Owner = `SITE_OWNER` env (a username), else first-authenticated-saver claims.
- **Frontend** (`Books.jsx`) — two-column layout; ▲/▼ reorder buttons (native drag doesn't work on
  touch); only the ⠿ handle is `draggable`; `makeDrop` inserts AFTER when dragging downward; Open Library
  keyless search-to-add (12s abort guard); covers cached as inline `data:` URIs on save (the remote CDN
  double-redirects with a 3h cache). Existing books need one Edit→Save to backfill covers.
- Field caps are enforced server-side (a 2026-07 hardening pass).
- **Tests:** `tests/` (17, in-memory DB).
