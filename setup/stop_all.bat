@echo off
REM Stops ACE-Step, the helper and n8n (the windows start_all.bat opened). Do not run while a video is rendering.
taskkill /FI "WINDOWTITLE eq ACE-Step API*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Rhyme Helper*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq n8n*" /T /F >nul 2>&1
echo Stopped. Start again with C:\RhymeFactory\start_all.bat
timeout /t 5 >nul
