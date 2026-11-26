@echo off
title restic Installer
echo ==========================================
echo   Installing restic (incremental backups)
echo ==========================================
echo.

if exist "%~dp0..\restic\restic.exe" (
    echo restic is already installed in the tool folder.
    "%~dp0..\restic\restic.exe" version
    pause
    exit /b 0
)

echo Downloading the latest restic release from GitHub...
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; $r=Invoke-RestMethod 'https://api.github.com/repos/restic/restic/releases/latest'; $a=$r.assets | Where-Object { $_.name -like '*windows_amd64.zip' } | Select-Object -First 1; Invoke-WebRequest -UseBasicParsing -Uri $a.browser_download_url -OutFile '%TEMP%\restic.zip'"
if not exist "%TEMP%\restic.zip" (
    echo [ERROR] Download failed - check your internet connection.
    pause
    exit /b 1
)

echo Extracting...
powershell -NoProfile -Command "Expand-Archive -Path '%TEMP%\restic.zip' -DestinationPath '%TEMP%\restic_tmp' -Force"
if not exist "%~dp0..\restic" mkdir "%~dp0..\restic"
for /r "%TEMP%\restic_tmp" %%f in (restic*.exe) do copy "%%f" "%~dp0..\restic\restic.exe" >nul
rmdir /s /q "%TEMP%\restic_tmp" >nul 2>&1
del /f /q "%TEMP%\restic.zip" >nul 2>&1

if exist "%~dp0..\restic\restic.exe" (
    echo.
    echo restic installed successfully in the tool folder.
    echo Next step: GUI - Advanced page - choose the restic engine, set a repository
    echo ^(e.g. rclone:drive:VPS-Restic^) and a password, then Save.
) else (
    echo [ERROR] Could not copy restic.exe
)
echo.
pause
