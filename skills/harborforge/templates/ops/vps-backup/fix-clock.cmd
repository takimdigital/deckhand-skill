@echo off
rem Deckhand - Windows clock fix for S3 SigV4 skew (vps-ops ref 55 section 7).
rem Run ELEVATED on the machine that pulls backups when skew >15 min:
rem rclone S3 calls fail with "Timestamp is in the future".
echo Starting Windows Time service and resyncing clock...
net start w32time
w32tm /resync /force
w32tm /query /status | findstr /i "Source Last"
echo.
echo Done. You can close this window (or it closes when you press a key).
pause
