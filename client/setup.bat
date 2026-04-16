@echo off
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] กรุณาคลิกขวา แล้วเลือก "Run as administrator"
    pause
    exit /b
)

echo ========================================
echo   ติดตั้ง Screen Monitor (ทุก User)
echo ========================================

SET "BIN_DIR=C:\ProgramData\ScreenMonitor"
SET "RECORDER_EXE=%~dp0dist\recorder.exe"
SET "LAUNCHER_EXE=%~dp0dist\launcher.exe"
SET "CONFIG_JSON=%~dp0config.json"
SET "RECORDER_TASK_XML=%~dp0task.xml"
SET "LAUNCHER_TASK_XML=%~dp0launcher_task.xml"

IF NOT EXIST "%RECORDER_EXE%" (
    echo [!] ไม่พบ dist\recorder.exe  -- กรุณา build ก่อน
    pause
    exit /b
)
IF NOT EXIST "%LAUNCHER_EXE%" (
    echo [!] ไม่พบ dist\launcher.exe  -- กรุณา build ก่อน
    pause
    exit /b
)

echo [1/4] คัดลอกไฟล์...
mkdir "%BIN_DIR%" 2>nul
copy /y "%RECORDER_EXE%" "%BIN_DIR%\recorder.exe" >nul
copy /y "%LAUNCHER_EXE%" "%BIN_DIR%\launcher.exe"  >nul
copy /y "%CONFIG_JSON%"   "%BIN_DIR%\config.json"  >nul

echo [2/4] ลบ Task เก่า...
schtasks /delete /tn "ScreenMonitor"         /f >nul 2>&1
schtasks /delete /tn "ScreenMonitorLauncher" /f >nul 2>&1

echo [3/4] สร้าง Scheduled Tasks...
schtasks /create /tn "ScreenMonitorLauncher" /xml "%LAUNCHER_TASK_XML%" /f >nul
if %errorlevel% neq 0 (
    echo [!] สร้าง ScreenMonitorLauncher task ไม่สำเร็จ
    pause
    exit /b
)

echo [4/4] รัน Launcher ทันที (จะ start recorder สำหรับ User ปัจจุบัน)...
schtasks /run /tn "ScreenMonitorLauncher" >nul

echo.
echo ========================================
echo   ติดตั้งสำเร็จ!
echo.
echo   Launcher (SYSTEM) จะรันทุก 1 นาที
echo   และ launch recorder.exe เข้าทุก User
echo   ที่ login อยู่โดยอัตโนมัติ
echo ========================================
pause
