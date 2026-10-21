@echo off
rem One-time setup after copying Apex to a machine (or after moving the folder):
rem   1. registers the grip-backend watchdog for THIS folder (at logon + every 5 minutes)
rem   2. runs the environment doctor and prints what is missing
setlocal
set "BASE=%~dp0"
echo [1/2] Registering the grip watchdog for "%BASE%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%BASE%tools\install_watchdog.ps1"
echo.
echo [2/2] Environment check
powershell -NoProfile -ExecutionPolicy Bypass -File "%BASE%tools\apex_doctor.ps1"
echo.
pause
