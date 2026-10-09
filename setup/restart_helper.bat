@echo off
REM Restarts only the Rhyme helper (use after editing C:\RhymeFactory\helper\.env, e.g. MOCK=1 / MOCK=0).
set ROOT=C:\RhymeFactory
taskkill /FI "WINDOWTITLE eq Rhyme Helper*" /T /F >nul 2>&1
timeout /t 2 /nobreak >nul
start "Rhyme Helper" /MIN cmd /c "cd /d %ROOT%\helper && %ROOT%\venv\Scripts\python.exe rhyme_helper.py >> %ROOT%\logs\helper.log 2>&1"
echo Helper restarted. Current setting:
findstr /B "MOCK=" "%ROOT%\helper\.env"
timeout /t 5 >nul
