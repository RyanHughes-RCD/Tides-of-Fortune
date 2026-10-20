@echo off
rem Tides Dice Studio launcher for Windows.
rem First run creates a private Python environment in .venv and installs the dependencies.
setlocal
cd /d "%~dp0"

if exist ".venv\installed.ok" goto run

echo.
echo  Tides Dice Studio - first-time setup
echo  ------------------------------------
set "PYCMD="
where py >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if not defined PYCMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD goto nopython

%PYCMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto oldpython

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python environment in .venv ...
  %PYCMD% -m venv .venv
  if errorlevel 1 goto venvfail
)
echo Installing dependencies (one time, needs internet) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 goto pipfail
echo ok> ".venv\installed.ok"

:run
echo Starting Tides Dice Studio - your browser will open automatically.
echo Keep this window open while you work; close it to quit.
".venv\Scripts\python.exe" -m dicestudio %*
if errorlevel 1 pause
exit /b 0

:nopython
echo.
echo Python 3.10 or newer was not found.
echo Install it from https://www.python.org/downloads/windows/
echo (tick "Add python.exe to PATH" and keep "tcl/tk" selected), then run this file again.
pause
exit /b 1

:oldpython
echo.
echo Your Python is older than 3.10. Install a newer Python from https://www.python.org/downloads/windows/
pause
exit /b 1

:venvfail
echo.
echo Could not create the Python environment in .venv
pause
exit /b 1

:pipfail
echo.
echo Installing the dependencies failed. Check your internet connection and run this file again.
pause
exit /b 1
