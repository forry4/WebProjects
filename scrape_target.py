"""Which BGA game the scraper targets — SWAP HERE to change games.

Corpora live in SEPARATE dirs, so switching preserves both: swap back any time by
restoring the other block. Both cob_collect (manifest builder) and cob_resume (the daily
downloader / cron) read GAME_ID + CORP from here, so one edit re-points the whole pipeline.
The daily task runs cob_resume, which is game-agnostic (it just downloads table logs), so
no other change is needed to switch.

WHAT DOES *NOT* FOLLOW THE SWITCH: the replay/harvest tools are per-game rules code and
stay pinned to their own game. cob_replay/cob_filter/cob_harvest understand Castles of
Burgundy logs only — a Tag Team corpus needs its own replayer against games/rag_tag before
any of it becomes training rows or an engine-parity check.
"""

# ── ACTIVE TARGET: Tag Team (Le Scorpion Masqué 2025; our port = games/rag_tag) ──
# 2 players, so cob_collect's 2p table filter is correct unchanged. Recent release, so
# expect far shallower player histories than CoB's 120-a-piece.
GAME_ID = 2165
CORP = "C:/Users/Forrest/TagTeam_corpus"
NAME = "Tag Team"

# ── swap back to Castles of Burgundy: comment the block above, uncomment this ──
# Corpus parked at 204/1689 downloaded (manifest built 2026-08-06 after the `page` fix).
# GAME_ID = 1390
# CORP = "C:/Users/Forrest/CoB_corpus"
# NAME = "Castles of Burgundy"

# ── swap back to Splendor Duel: comment the block above, uncomment this ──
# GAME_ID = 1903
# CORP = "C:/Users/Forrest/Duel_corpus"
# NAME = "Splendor Duel"
