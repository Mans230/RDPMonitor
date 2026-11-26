@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo   RDP Suite - Install
echo ============================================
echo.

rem Find a real Python: skip the Windows Store alias in WindowsApps, else use py
set "PYCMD="
where python >nul 2>nul && (
    for /f "delims=" %%i in ('python -c "import sys;print(sys.executable)" 2^>nul') do (
        echo %%i | findstr /i "WindowsApps" >nul || set "PYCMD=python"
    )
)
if not defined PYCMD (
    where py >nul 2>nul && set "PYCMD=py"
)
if not defined PYCMD (
    echo [ERROR] Python not found in PATH.
    echo Install Python from python.org and re-run this file.
    pause
    exit /b 1
)

echo [1/2] Installing dependencies (monitor and backup)...
%PYCMD% -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

rem psutil + requests are mandatory - abort if they cannot be imported
%PYCMD% -c "import psutil, requests" 2>nul
if errorlevel 1 (
    echo [ERROR] Mandatory dependencies failed to import ^(psutil, requests^).
    echo Aborting so the scheduled tasks do not crash-loop.
    pause
    exit /b 1
)

echo [2/2] Registering RDP Suite tasks ^(Administrator terminal required^)...
%PYCMD% rdp_suite.py install
set "RESULT=%errorlevel%"
pause
exit /b %RESULT%
