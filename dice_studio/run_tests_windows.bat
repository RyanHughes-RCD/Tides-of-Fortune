@echo off
rem Runs the automated test suite (run run_windows.bat once first to set up .venv).
setlocal
cd /d "%~dp0"
if not exist ".venv\installed.ok" (
  echo Run run_windows.bat once first to set up the environment.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pytest -v tests
pause
