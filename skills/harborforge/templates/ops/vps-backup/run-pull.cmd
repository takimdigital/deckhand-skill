@echo off
rem Deckhand home pull - Windows Task Scheduler wrapper (vps-ops ref 55 section 7).
rem Copy this file where local-pull.sh lives and point the scheduled task at it.
rem
rem 1) PATH: add %USERPROFILE%\bin (rclone/restic live there; the scheduler env lacks it).
rem 2) HOME: pin it - the scheduler starts bash without a user profile, MSYS falls back
rem    to /home/<user>, the vault env file is not found, and the pull dies silently (exit 1).
rem 3) BASH: use YOUR MSYS bash - discover it with:  where bash
rem    NOT C:\Windows\System32\bash.exe (that is the WSL launcher, not MSYS). The Git-for-Windows
rem    default is C:\Program Files\Git\bin\bash.exe - but CHECK it exists.
rem 4) CRLF + ASCII only in this file. Fire the task once, expect Last Result 0.
set "PATH=%USERPROFILE%\bin;%PATH%"
"C:\Program Files\Git\bin\bash.exe" -lc "HOME=/c/Users/<you> bash /c/Users/<you>/deckhand-backups/local-pull.sh > /c/Users/<you>/deckhand-backups/task-run.log 2>&1"
