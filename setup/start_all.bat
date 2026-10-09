@echo off
REM Starts the three local services. Task Scheduler runs this at logon (see install_windows.ps1).
set ROOT=C:\RhymeFactory

REM 1) ACE-Step song API  -> http://127.0.0.1:8001
start "ACE-Step API" /MIN cmd /c "cd /d %ROOT%\ACE-Step-1.5 && uv run --no-sync acestep-api >> %ROOT%\logs\acestep.log 2>&1"

REM 2) Rhyme helper       -> http://127.0.0.1:8765
start "Rhyme Helper" /MIN cmd /c "cd /d %ROOT%\helper && %ROOT%\venv\Scripts\python.exe rhyme_helper.py >> %ROOT%\logs\helper.log 2>&1"

REM 3) n8n                -> http://localhost:5678
set GENERIC_TIMEZONE=Asia/Kolkata
set TZ=Asia/Kolkata
set N8N_DEFAULT_BINARY_DATA_MODE=filesystem
set EXECUTIONS_DATA_PRUNE=true
set EXECUTIONS_DATA_MAX_AGE=336
set N8N_DIAGNOSTICS_ENABLED=false
start "n8n" /MIN cmd /c "n8n start >> %ROOT%\logs\n8n.log 2>&1"

echo Started ACE-Step (8001), helper (8765) and n8n (5678). Logs: %ROOT%\logs
