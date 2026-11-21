@echo off
title NIGHTSHIFT local agent
cd /d "%~dp0\.."
python agent\local_agent.py
pause
