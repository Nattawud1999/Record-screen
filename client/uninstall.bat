@echo off
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] กรุณาคลิกขวา แล้วเลือก "Run as administrator"
    pause
    exit /b
)
taskkill /F /IM recorder.exe >nul 2>&1
taskkill /F /IM launcher.exe  >nul 2>&1
schtasks /delete /tn "ScreenMonitor"         /f >nul 2>&1
schtasks /delete /tn "ScreenMonitorLauncher" /f >nul 2>&1
reg delete "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v "ScreenMonitor" /f >nul 2>&1
if exist "C:\ProgramData\ScreenMonitor" rmdir /s /q "C:\ProgramData\ScreenMonitor"
echo ถอนการติดตั้งเรียบร้อย
pause
