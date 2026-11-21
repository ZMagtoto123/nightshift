@echo off
REM Copies a launcher into your Windows Startup folder so the agent
REM auto-runs (hidden console) every time you log in.
set SCRIPT_DIR=%~dp0
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
(
  echo @echo off
  echo cd /d "%SCRIPT_DIR%.."
  echo start "" /min python agent\local_agent.py
) > "%STARTUP%\nightshift_agent.bat"
echo Installed: %STARTUP%\nightshift_agent.bat
echo The agent will auto-start next time you log in.
pause
