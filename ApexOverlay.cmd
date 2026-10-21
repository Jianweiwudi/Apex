@echo off
rem ---------------------------------------------------------------
rem  Apex Overlay launcher
rem  Starts the always-on-top HUD (ApexOverlay.ps1) without leaving
rem  a console window behind. Right-click the overlay itself to
rem  lock its position, change its size, or close it.
rem ---------------------------------------------------------------
setlocal
set "PS1=%~dp0ApexOverlay.ps1"
if not exist "%PS1%" (
  echo ApexOverlay.ps1 not found next to this file.
  pause
  exit /b 1
)
start "" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%PS1%"
endlocal
