# Apex launcher
#
# Starts the grip backend if it is not already answering, waits for it to come up, then starts
# the panel. Everything is resolved from this file's own folder, so the app can be copied to
# another machine or another drive without edits.

$ErrorActionPreference = "SilentlyContinue"
$base = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Backend {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 "http://127.0.0.1:7798/status"
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

if (-not (Test-Backend)) {
    # the .vbs wrapper runs the batch through wscript, which has no console at all: starting
    # the .cmd directly from here still flashed a black window for a fraction of a second
    Start-Process -FilePath "wscript.exe" -ArgumentList '//B', ('"' + (Join-Path $base 'ApexGrip.vbs') + '"') -WindowStyle Hidden
    # wait up to 6 s: starting the panel first is what produced a "backend not running" toast
    # on the first paint of a cold machine
    for ($i = 0; $i -lt 24; $i++) {
        Start-Sleep -Milliseconds 250
        if (Test-Backend) { break }
    }
}

Start-Process -FilePath (Join-Path $base "Apex.exe") -WorkingDirectory $base