@echo off
echo ========================================
echo  Family Dashboard — Kiosk Configuration
echo ========================================
echo.
echo Running as Administrator is required!
echo.

:: Check for admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Please right-click this file and select "Run as administrator"
    pause
    exit /b
)

echo [1/4] Disabling screen timeout...
powercfg /change monitor-timeout-ac 0
powercfg /change monitor-timeout-dc 0
echo       Screen will never turn off.

echo [2/4] Disabling sleep...
powercfg /change standby-timeout-ac 0
powercfg /change standby-timeout-dc 0
echo       Computer will never sleep.

echo [3/4] Disabling lock screen timeout...
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization" /v NoLockScreen /t REG_DWORD /d 1 /f >nul 2>&1
powercfg /change hibernate-timeout-ac 0
powercfg /change hibernate-timeout-dc 0
echo       Lock screen disabled.

echo [4/4] Setting sign-in to never require password after sleep...
reg add "HKLM\SOFTWARE\Policies\Microsoft\Power\PowerSettings\0e796bdb-100d-47d6-a2d5-f7d2daa51f51" /v ACSettingIndex /t REG_DWORD /d 0 /f >nul 2>&1
reg add "HKLM\SOFTWARE\Policies\Microsoft\Power\PowerSettings\0e796bdb-100d-47d6-a2d5-f7d2daa51f51" /v DCSettingIndex /t REG_DWORD /d 0 /f >nul 2>&1
echo       Sign-in after sleep disabled.

echo.
echo ========================================
echo  Power settings configured!
echo ========================================
echo.
echo MANUAL STEP REQUIRED — Auto-login:
echo   1. Press Win+R, type: netplwiz
echo   2. Uncheck "Users must enter a user name and password"
echo   3. Click Apply, enter your password, click OK
echo.
echo After that, the machine will boot straight to desktop.
echo Then run setup.bat to configure auto-start of the dashboard.
echo.
pause
