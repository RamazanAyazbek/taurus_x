@echo off
cd /d "%~dp0"
python run_experiments.py
if errorlevel 1 (
  echo.
  echo ERROR: Check Python installation, Internet connectivity and logs.
)
pause
