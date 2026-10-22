@echo off
rem Runs fair_gem_dice.py (the standalone gemstone D4/D6 generator).
rem Double-click for the demo, or drag nothing - results go to the "fair_dice_output" folder.
setlocal
cd /d "%~dp0"
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python 3 was not found. Install it from https://www.python.org/downloads/windows/
  echo ^(tick "Add python.exe to PATH"^), then run this file again.
  pause
  exit /b 1
)
%PY% -c "import numpy" >nul 2>nul || %PY% -m pip install numpy
%PY% fair_gem_dice.py %*
echo.
echo Done. Your STL files are in: %~dp0fair_dice_output
pause
