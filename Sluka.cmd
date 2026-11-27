@echo off
rem SPDX-License-Identifier: LicenseRef-Sluka
rem Copyright (c) 2026 Sluka. Part of Sluka Desktop; see LICENSE.txt.
rem Sluka Desktop for Windows.  Double-click to open the app.
rem In a terminal, from this folder:   .\sluka doctor     .\sluka --help
rem A sluka-extension zip dragged onto this file is installed into the app.
rem
rem Python is started isolated (-I): it reads no PYTHON* settings from the
rem environment and looks for modules only in this app's own folder.
setlocal
set "SLUKA_HERE=%~dp0"
rem Ends with 0 on Python 3.9 or newer.
set "SLUKA_TEST=import sys; sys.exit(sys.hexversion // 0x3090000 == 0)"
set "SLUKA_PY="
py -3 -c "%SLUKA_TEST%" >nul 2>nul && set "SLUKA_PY=py -3"
if not defined SLUKA_PY python -c "%SLUKA_TEST%" >nul 2>nul && set "SLUKA_PY=python"
if not defined SLUKA_PY python3 -c "%SLUKA_TEST%" >nul 2>nul && set "SLUKA_PY=python3"
if not defined SLUKA_PY goto nopython

rem Started by a double-click or a shortcut: what goes wrong is also said in a
rem message box, since this window may be minimised or gone in a moment.
if "%~1"=="" set "SLUKA_CLICKED=1"
if "%~1"=="" echo Starting Sluka Desktop...
%SLUKA_PY% -I "%SLUKA_HERE%app\run.py" %*
set "SLUKA_CODE=%ERRORLEVEL%"
if not "%SLUKA_CODE%"=="0" if "%~1"=="" pause
exit /b %SLUKA_CODE%

:nopython
echo.
echo   Sluka Desktop needs Python 3.9 or newer, and found none on this computer.
echo.
echo   Get it one of these ways, then start Sluka again:
echo     - from https://www.python.org/downloads/windows/
echo     - or in a terminal:   winget install -e --id Python.Python.3.13
echo   (Not the "Python 3.x" apps of the Microsoft Store: what those write for
echo   mpv and Anki, Windows keeps where mpv and Anki do not look.)
echo.
echo   Nothing else has to be installed: the app uses only what comes with
echo   Python: its windows are its own, with the web view Windows itself has.
echo.
pause
exit /b 9009
