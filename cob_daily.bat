@echo off
REM BGA replay downloader — run by Windows Task Scheduler task "CoB_daily_download" on a
REM REPEATING 24.5-HOUR trigger (P1DT30M, indefinite), NOT a fixed clock time. Read the task,
REM not this comment, for the current fire time: it DRIFTS ~30 min later every run by design.
REM Game-agnostic: cob_resume reads the ACTIVE target from scrape_target.py (game id + corpus
REM dir), so switching games is a scrape_target.py edit — this .bat needs no change. The real
REM per-run log lands in <active corpus>/resume_log.txt; this cron_stdout is just launch markers.
REM
REM WHY 24.5h AND NOT DAILY: the replay cap is NOT a clean daily reset — it's a ROLLING ~24h
REM window of ~10 downloads (confirmed 2026-07-21: 8 slots freed exactly when the prior day's
REM batch aged out). A fixed daily time sits EXACTLY ~24h after the last run, so the oldest
REM downloads have only just aged out and a few minutes of clock jitter can leave the window
REM still full — the run then burns its slot on a "quota reached" no-op. The extra 30 min is
REM margin: the whole previous batch is provably rolled off before the next run starts.
REM Still keep collection to this ONE trigger — off-cycle catch-up runs re-anchor the rolling
REM window and starve the following run.
REM
REM (History: this was a fixed 6:40 PM daily, then a 9:00 AM daily. The 9:00 AM trigger missed
REM two consecutive days in 2026-08 — machine asleep, and the one run that did fire was killed
REM at the PT30M ExecutionTimeLimit with 0xC000013A — losing that quota permanently. Unused
REM quota does not bank; a missed day is 10 games gone. StartWhenAvailable is ON so a missed
REM slot is retried, but it cannot recover a window that has already passed.)
REM
REM The script preflights the quota and exits cleanly if it's still spent, so
REM firing when there's nothing to do costs exactly two API calls.

cd /d C:\Users\Forrest\forrestm_projects-cobmining
echo [%date% %time%] cob_daily.bat launching python >> C:\Users\Forrest\.bga_session\cron_stdout.txt
REM -u = unbuffered: log lines appear immediately, so a hang is visible (a stuck run once
REM stalled with no output). Task ExecutionTimeLimit is set to 30 min so a hang self-kills.
C:\Users\Forrest\forrestm_projects\.venv\Scripts\python.exe -u cob_resume.py 10 100 >> C:\Users\Forrest\.bga_session\cron_stdout.txt 2>&1
echo [%date% %time%] cob_daily.bat done (exit %ERRORLEVEL%) >> C:\Users\Forrest\.bga_session\cron_stdout.txt
exit /b %ERRORLEVEL%
