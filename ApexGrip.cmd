@echo off
rem ---------------------------------------------------------------
rem  Apex grip backend launcher
rem
rem  Finds a Python on this machine instead of assuming one fixed
rem  install path, then starts the service hidden. Order:
rem    1. %APEX_PY%            (explicit override, for odd setups)
rem    2. pyw.exe -3           (python.org launcher)
rem    3. pythonw.exe on PATH
rem    4. %LOCALAPPDATA%\Programs\Python\Python3*
rem    5. C:\Python3*, C:\Program Files\Python3*
rem    6. the workbuddy runtime, if this machine happens to have one
rem  What it picked is appended to tools\_grip_start.log, so a machine
rem  where the panel says "backend not running" can be diagnosed
rem  without a console window.
rem ---------------------------------------------------------------
setlocal EnableDelayedExpansion
set "BASE=%~dp0"
set "LOG=%BASE%tools\_grip_start.log"
set "PY="
set "PYARGS="

if defined APEX_PY if exist "%APEX_PY%" (
  set "PY=%APEX_PY%"
  goto :found
)

where pyw.exe >nul 2>nul
if not errorlevel 1 (
  set "PY=pyw.exe"
  set "PYARGS=-3"
  goto :found
)

where pythonw.exe >nul 2>nul
if not errorlevel 1 (
  set "PY=pythonw.exe"
  goto :found
)

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
  if exist "%%~fD\pythonw.exe" set "PY=%%~fD\pythonw.exe"
)
if defined PY goto :found

for /d %%D in ("C:\Python3*" "C:\Program Files\Python3*" "C:\Program Files (x86)\Python3*") do (
  if exist "%%~fD\pythonw.exe" set "PY=%%~fD\pythonw.exe"
)
if defined PY goto :found

for /d %%D in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*") do (
  if exist "%%~fD\pythonw.exe" set "PY=%%~fD\pythonw.exe"
)
if defined PY goto :found

echo no python found; set APEX_PY to pythonw.exe >> "%LOG%"
exit /b 1

:found
echo starting with "%PY%" %PYARGS% >> "%LOG%"
start "" "%PY%" %PYARGS% "%BASE%grip\apex_grip_server.py"
endlocal