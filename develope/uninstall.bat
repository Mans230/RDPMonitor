@echo off
setlocal
cd /d "%~dp0"
set "RESULT=0"
echo ============================================
echo   RDP Suite - Remove Scheduled Tasks
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

if defined PYCMD (
    %PYCMD% rdp_suite.py uninstall
    set "RESULT=%errorlevel%"
    goto :done
)

echo [WARN] Python not found in PATH. Removing tasks via PowerShell...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; foreach ($n in 'RDPSuite','RDPSuiteBackup','RDPMonitor','RDPWebConsole','rdp','VPSBackupTool') { $t=Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue; if ($t) { Stop-ScheduledTask -InputObject $t -ErrorAction Stop; Unregister-ScheduledTask -InputObject $t -Confirm:$false -ErrorAction Stop } }"
if errorlevel 1 (
    set "RESULT=1"
    echo [WARN] Task removal reported an error. Right-click this file and Run as administrator.
) else (
    echo [OK] Scheduled tasks removed (if they were installed).
    echo [WARN] Python is unavailable; firewall policy cleanup was NOT performed.

:done
echo.
pause
exit /b %RESULT%
