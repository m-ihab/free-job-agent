@echo off
REM Sync the local job database into the Obsidian vault, then open it.
REM Double-click this file from Explorer. Works even when the dashboard is off.
setlocal
cd /d "%~dp0"

echo Syncing jobs to the Obsidian vault...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m job_agent.cli.main obsidian-sync
) else (
    job-agent obsidian-sync
)
if errorlevel 1 (
    echo.
    echo Sync failed - see the messages above.
    pause
    exit /b 1
)

echo.
echo Opening the vault in Obsidian (open second-brain as a vault once if it does not appear)...
start "" "obsidian://open?vault=second-brain"

echo.
echo Done. Vault: "%~dp0second-brain"  -  start at Dashboard.md and toggle the graph view.
pause
endlocal
