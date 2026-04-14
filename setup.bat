@echo off
echo ========================================
echo  Family Dashboard — Setup
echo ========================================
echo.

:: Install Python dependencies
echo Installing dependencies...
pip install -r requirements.txt
echo.

:: Create startup shortcut
echo Creating auto-start shortcut...
set SCRIPT_DIR=%~dp0
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

:: Create a VBS script to launch silently
echo Set WshShell = CreateObject("WScript.Shell") > "%STARTUP_DIR%\FamilyDashboard.vbs"
echo WshShell.Run "cmd /c cd /d %SCRIPT_DIR% && python app.py", 0, False >> "%STARTUP_DIR%\FamilyDashboard.vbs"
echo WshShell.Run "cmd /c timeout /t 5 && start chrome --kiosk --app=http://localhost:5000", 0, False >> "%STARTUP_DIR%\FamilyDashboard.vbs"

echo.
echo Setup complete!
echo.
echo To start now, run: python app.py
echo Then open: http://localhost:5000
echo.
echo For kiosk mode: chrome --kiosk --app=http://localhost:5000
echo Remote control: http://YOUR-PC-IP:5000/remote
echo.
pause
