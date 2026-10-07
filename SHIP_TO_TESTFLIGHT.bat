@echo off
setlocal
title Ship RuskiMaxxing to TestFlight
rem Double-click to build the iPhone app on GitHub's Mac and upload it to TestFlight.
rem Installs Git and Python if needed, then runs tools\ship_ios.py (which does the rest).

set "PATH=%ProgramFiles%\Git\cmd;%ProgramFiles%\GitHub CLI;%LOCALAPPDATA%\Microsoft\WindowsApps;%PATH%"
set "PYUSER=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

where winget >nul 2>nul
if errorlevel 1 (
  echo winget is missing. Install "App Installer" from the Microsoft Store, then run this again.
  pause
  exit /b 1
)

where git >nul 2>nul
if errorlevel 1 (
  echo Installing Git...
  winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
)

set PY=
if exist "%PYUSER%" set PY="%PYUSER%"
if not defined PY (
  py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul && set PY=py -3
)
if not defined PY (
  echo Installing Python...
  winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
  set PY="%PYUSER%"
)

set "SCRIPT=%~dp0tools\ship_ios.py"
if not exist "%SCRIPT%" (
  if not exist "%USERPROFILE%\ruskimaxxing\.git" git clone https://github.com/andrewsdillon-design/ruskimaxxing.git "%USERPROFILE%\ruskimaxxing"
  set "SCRIPT=%USERPROFILE%\ruskimaxxing\tools\ship_ios.py"
)

%PY% "%SCRIPT%"
echo.
pause
