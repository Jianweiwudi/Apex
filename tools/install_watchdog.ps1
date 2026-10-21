# Registers (or refreshes) the grip watchdog for THIS copy of Apex.
#
#   powershell -ExecutionPolicy Bypass -File tools\install_watchdog.ps1
#
# Uses schtasks, which works without elevation for a task that runs as the current user.

$ErrorActionPreference = 'Continue'
$tools = Split-Path -Parent $MyInvocation.MyCommand.Path
$base = Split-Path -Parent $tools
$watch = Join-Path $tools 'grip_watchdog.vbs'      # wscript entry: never shows a console

if (-not (Test-Path $watch)) { Write-Output "missing $watch"; exit 1 }

$tr = 'wscript.exe //B "' + $watch + '"'
schtasks /Delete /TN "Apex Grip Watchdog" /F 2>$null | Out-Null
schtasks /Create /TN "Apex Grip Watchdog" /SC MINUTE /MO 5 /TR $tr /F

$q = schtasks /Query /TN "Apex Grip Watchdog" /FO LIST 2>$null
$next = ($q | Select-String 'Next Run Time') -join ' '
Write-Output ("watchdog -> {0}" -f $watch)
Write-Output $next