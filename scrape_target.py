"""Which BGA game the scraper targets — SWAP HERE to change games.

Corpora live in SEPARATE dirs, so switching preserves both: swap back any time by
restoring the other block. Both cob_collect (manifest builder) and cob_resume (the daily
downloader / cron) read GAME_ID + CORP from here, so one edit re-points the whole pipeline.
The daily task runs cob_resume, which is game-agnostic (it just downloads table logs), so
no other change is needed to switch. (The CoB-specific replay/harvest tools are NOT run by
the cron and stay pinned to CoB data.)
"""

# ── swap back to Splendor Duel: comment the block below, uncomment this ──
# GAME_ID = 1903
# CORP = "C:/Users/Forrest/Duel_corpus"
# NAME = "Splendor Duel"

# ── ACTIVE TARGET: Castles of Burgundy ──
GAME_ID = 1390
CORP = "C:/Users/Forrest/CoB_corpus"
NAME = "Castles of Burgundy"
