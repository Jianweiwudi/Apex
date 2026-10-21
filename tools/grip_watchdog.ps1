# Apex grip backend watchdog
#
# The panel can only report that the backend is down; a web page cannot start a process. And
# Apex.exe launched straight from the taskbar skips ApexLauncher.ps1, so nothing ever starts
# the Python service. This runs from a scheduled task (at logon, then every 5 minutes) and
# only acts when 127.0.0.1:7798 is not answering.
#
# Every path is resolved from this file's own location, so the folder can be moved, copied or
# installed on another machine and the watchdog still points at the right place.

$ErrorActionPreference = 'SilentlyContinue'
$tools = Split-Path -Parent $MyInvocation.MyCommand.Path
$base = Split-Path -Parent $tools

$up = $false
try {
    $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:7798/status'
    $up = ($r.StatusCode -eq 200)
} catch { }

if (-not $up) {
    $log = Join-Path $tools '_grip_watchdog.log'
    Add-Content -Path $log -Value ('{0}  backend down, starting ({1})' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $base)
    Start-Process -FilePath (Join-Path $base 'ApexGrip.cmd') -WorkingDirectory $base -WindowStyle Hidden
}
