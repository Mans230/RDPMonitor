@echo off
title rclone Installer
echo ==========================================
echo   Installing rclone (cloud upload tool)
echo ==========================================
echo.

where rclone >nul 2>&1
if %errorlevel%==0 (
    echo rclone is already installed on this system.
    rclone version
    pause
    exit /b 0
)

echo Downloading rclone from the official site...
powershell -Command "Invoke-WebRequest -Uri 'https://downloads.rclone.org/rclone-current-windows-amd64.zip' -OutFile '%TEMP%\rclone.zip'"
if not exist "%TEMP%\rclone.zip" (
    echo [ERROR] Download failed - check your internet connection.
    pause
    exit /b 1
)

echo Extracting...
powershell -Command "Expand-Archive -Path '%TEMP%\rclone.zip' -DestinationPath '%TEMP%\rclone_tmp' -Force"

if not exist "%~dp0..\rclone" mkdir "%~dp0..\rclone"
for /r "%TEMP%\rclone_tmp" %%f in (rclone.exe) do copy "%%f" "%~dp0..\rclone\rclone.exe" >nul

if exist "%~dp0..\rclone\rclone.exe" (
    echo.
    echo rclone installed successfully in the tool folder.
    echo Next step: open the tool GUI - Cloud tab - "Add new cloud account"
) else (
    echo [ERROR] Could not copy rclone.exe
)
echo.
pause
