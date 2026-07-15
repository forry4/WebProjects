@echo off
REM Daily BGA replay downloader — run by Windows Task Scheduler.
REM
REM Fires just after BGA's daily replay cap resets. BGA's day is PARIS time
REM (verified: the server's own clock reference matches utc+2), so the reset is
REM midnight CEST = 15:00 LOCAL, not local midnight.
REM
REM The script preflights the quota and exits cleanly if it's still spent, so
REM firing when there's nothing to do costs exactly two API calls.

cd /d C:\Users\Forrest\forrestm_projects-cobmining
C:\Users\Forrest\forrestm_projects\.venv\Scripts\python.exe cob_resume.py 10 100 >> C:\Users\Forrest\CoB_corpus\cron_stdout.txt 2>&1
exit /b %ERRORLEVEL%
