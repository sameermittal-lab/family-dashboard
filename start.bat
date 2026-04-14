@echo off
echo Starting Family Dashboard...

:: Launch Chrome after a short delay
start "" cmd /c "timeout /t 4 /nobreak > nul && start chrome --kiosk --app=http://localhost:5000"

:: Auto-restart loop — if app.py crashes, wait 3 seconds and restart
:loop
echo [%date% %time%] Starting server...
python app.py
echo [%date% %time%] Server exited! Restarting in 3 seconds...
timeout /t 3 /nobreak > nul
goto loop
