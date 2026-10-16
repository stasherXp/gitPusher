@echo off
chcp 65001 >nul
title GitPusher launcher
cd /d "%~dp0"

echo ============================================================
echo   GitPusher launcher
echo ============================================================
echo.

if not exist "app\gitpusher.py" goto :no_app

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    where python3 >nul 2>nul
    if not errorlevel 1 set "PY=python3"
)
if not defined PY goto :no_python

echo [OK] Python command: %PY%

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>nul
if errorlevel 1 goto :old_python

%PY% -c "import tkinter" 2>nul
if errorlevel 1 goto :no_tk

%PY% -c "import sqlite3" 2>nul
if errorlevel 1 goto :no_sqlite

echo [OK] Python 3.8+, tkinter, sqlite3 -- all good.

where git >nul 2>nul
if errorlevel 1 (
    echo [WARN] git not found in PATH. Push buttons won't work.
    echo        Install Git for Windows: https://git-scm.com/download/win
) else (
    for /f "tokens=*" %%G in ('git --version 2^>nul') do echo [OK] %%G
)

echo.
echo ------------------------------------------------------------
echo   Launching: %PY% app\gitpusher.py
echo ------------------------------------------------------------
echo.

%PY% app\gitpusher.py
set "RC=%errorlevel%"
echo.
if %RC% NEQ 0 (
    echo [ERROR] gitpusher.py exited with code %RC%
) else (
    echo [OK] gitpusher.py finished normally.
)
goto :end


:no_app
echo [ERROR] gitpusher.py not found in:
echo         %CD%
echo         Put this .bat next to gitpusher.py.
goto :end

:no_python
echo [ERROR] Python not found (tried py, python, python3).
echo.
echo   Install Python 3.11+ from:
echo     https://www.python.org/downloads/windows/
echo   During install check:
echo     [x] Add python.exe to PATH
echo     [x] tcl/tk and IDLE
goto :end

:old_python
echo [ERROR] Python is older than 3.8.
echo         Install Python 3.11+ from python.org
goto :end

:no_tk
echo [ERROR] tkinter is missing in this Python.
echo         Reinstall Python and enable "tcl/tk and IDLE".
goto :end

:no_sqlite
echo [ERROR] sqlite3 module is missing. Very unusual.
echo         Reinstall Python from python.org
goto :end

:end
echo.
echo ------------------------------------------------------------
echo   Press any key to close this window.
echo ------------------------------------------------------------
pause >nul
exit /b