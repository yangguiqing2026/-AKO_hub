@echo off
chcp 65001 >nul
title AKO one-click start
setlocal

REM AKO full-stack one-click launcher.
REM Wraps start_all.ps1, which is also what the boot scheduled task runs,
REM so a manual double-click and an unattended boot produce identical results.
REM Idempotent: already-running services are left untouched.

echo.
echo   AKO full-stack start - three workbenches + agent cluster
echo   -------------------------------------------------------
echo.

PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_all.ps1"
set RC=%ERRORLEVEL%

echo.
if "%RC%"=="0" (
    echo   Opening the boss workbench: http://localhost:8081
    start "" "http://localhost:8081"
) else (
    echo   Some steps failed. Check logs\start_all_*.log for details.
)

echo.
pause
endlocal
