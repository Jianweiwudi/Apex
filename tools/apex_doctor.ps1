# Apex environment doctor
#
#   powershell -ExecutionPolicy Bypass -File tools\apex_doctor.ps1
#
# Checks everything the app needs on a machine it has never run on, and prints a table.
# PASS = required and working, FAIL = required and broken, INFO = optional / situational.
# Every path is derived from this file, so the folder can live anywhere.

$ErrorActionPreference = 'SilentlyContinue'
$tools = Split-Path -Parent $MyInvocation.MyCommand.Path
$base = Split-Path -Parent $tools
$log = Join-Path $tools '_doctor.log'
$rows = New-Object System.Collections.ArrayList

function Add-Row($name, $state, $detail) {
    [void]$rows.Add([pscustomobject]@{ Check = $name; Result = $state; Detail = $detail })
}

# ---- 1. files the app needs
$need = @('Apex.exe', 'ui\index.html', 'ui\media\apex_intro.wmv', 'grip\apex_grip_server.py',
          'ApexLauncher.ps1', 'ApexGrip.cmd', 'ApexOverlay.ps1')
$missing = @($need | Where-Object { -not (Test-Path (Join-Path $base $_)) })
Add-Row 'App files' $(if ($missing.Count) { 'FAIL' } else { 'PASS' }) $(if ($missing.Count) { 'missing: ' + ($missing -join ', ') } else { 'all present' })

# ---- 2. WebView2 runtime (Apex.exe is a WinForms WebView2 host; without it the window is blank)
$wvExe = @(
    (Get-ChildItem 'C:\Program Files (x86)\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe' -ErrorAction SilentlyContinue),
    (Get-ChildItem 'C:\Program Files\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe' -ErrorAction SilentlyContinue)
) | Select-Object -First 1
$wvVer = ''
if ($wvExe) { $wvVer = Split-Path (Split-Path $wvExe.FullName -Parent) -Leaf }
if (-not $wvVer) {
    $k = Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' -ErrorAction SilentlyContinue
    if ($k) { $wvVer = $k.pv }
}
Add-Row 'WebView2 runtime' $(if ($wvVer) { 'PASS' } else { 'FAIL' }) $(if ($wvVer) { "version $wvVer" } else { 'install the WebView2 Evergreen runtime' })

# ---- 3. python for the grip backend (same order ApexGrip.cmd uses)
$py = $null
if ($env:APEX_PY -and (Test-Path $env:APEX_PY)) { $py = $env:APEX_PY }
if (-not $py) { $c = Get-Command pyw.exe -ErrorAction SilentlyContinue; if ($c) { $py = $c.Source + ' -3' } }
if (-not $py) { $c = Get-Command pythonw.exe -ErrorAction SilentlyContinue; if ($c) { $py = $c.Source } }
if (-not $py) {
    $cand = @()
    $cand += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\pythonw.exe" -ErrorAction SilentlyContinue
    $cand += Get-ChildItem 'C:\Python3*\pythonw.exe' -ErrorAction SilentlyContinue
    $cand += Get-ChildItem 'C:\Program Files\Python3*\pythonw.exe' -ErrorAction SilentlyContinue
    $cand += Get-ChildItem "$env:USERPROFILE\.workbuddy\binaries\python\versions\*\pythonw.exe" -ErrorAction SilentlyContinue
    if ($cand.Count) { $py = $cand[0].FullName }
}
Add-Row 'Python' $(if ($py) { 'PASS' } else { 'FAIL' }) $(if ($py) { $py } else { 'install Python 3 or set APEX_PY' })

# ---- 4. grip backend
$status = $null
try { $status = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 'http://127.0.0.1:7798/status' } catch { }
$okStatus = ($status -and $status.StatusCode -eq 200)
Add-Row 'Grip backend' $(if ($okStatus) { 'PASS' } else { 'FAIL' }) $(if ($okStatus) { '127.0.0.1:7798 answering' } else { 'not running - run ApexGrip.cmd' })

# ---- 5. ACC install + startup movie
$movie = $null
if ($okStatus) {
    try { $movie = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 'http://127.0.0.1:7798/movie').Content | ConvertFrom-Json } catch { }
}
$acc = if ($movie) { $movie.acc } else { $null }
$accOk = [bool]($acc -and $acc.found)
Add-Row 'ACC install' $(if ($accOk) { 'PASS' } else { 'FAIL' }) $(if ($accOk) { $acc.root } elseif ($movie) { 'not located - pick the folder in the panel' } else { 'backend offline' })
if ($accOk) {
    $m = $acc.movie
    $exists = Test-Path $m
    Add-Row 'Startup movie' $(if ($exists) { 'PASS' } else { 'FAIL' }) $(if ($exists) { '{0:N1} MB  state={1}  backup={2}' -f ((Get-Item $m).Length / 1MB), $movie.state, $(if ($movie.backup.exists) { 'yes' } else { 'none' }) } else { 'missing: ' + $m })
    $payload = Join-Path $base 'ui\media\apex_intro.wmv'
    if ((Test-Path $payload) -and $exists) {
        $same = ((Get-Item $m).Length -eq (Get-Item $payload).Length)
        Add-Row 'Movie up to date' $(if ($same) { 'PASS' } else { 'INFO' }) $(if ($same) { 'game payload matches ui\media' } else { 'game payload differs from ui\media - re-apply in the panel' })
    }
}

# ---- 5a. PowerShell scripts that contain non-ASCII must carry a UTF-8 BOM
#         Without it Windows PowerShell reads them as ANSI, the Chinese strings turn into
#         mojibake and the script dies on a parse error - which is exactly how the overlay
#         "stopped launching" once.
$noBom = @()
foreach ($f in Get-ChildItem $base -Recurse -Filter '*.ps1') {
    $b = [System.IO.File]::ReadAllBytes($f.FullName)
    $hasBom = ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF)
    $nonAscii = $false
    foreach ($byte in $b) { if ($byte -gt 127) { $nonAscii = $true; break } }
    if ($nonAscii -and -not $hasBom) { $noBom += $f.Name }
}
Add-Row 'Script encoding' $(if ($noBom.Count) { 'FAIL' } else { 'PASS' }) $(if ($noBom.Count) { 'no UTF-8 BOM: ' + ($noBom -join ', ') } else { 'every non-ASCII script has a BOM' })

# ---- 5b. ffmpeg (only the "import my own video" feature needs it)
$ff = @(
    (Join-Path $tools 'ffmpeg\ffmpeg.exe'),
    (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1).Source
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
Add-Row 'ffmpeg (import)' $(if ($ff) { 'PASS' } else { 'INFO' }) $(if ($ff) { $ff } else { 'run tools\get_ffmpeg.ps1 to enable "import my own video"' })

# ---- 6. optional companions
$ov = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -match 'ApexOverlay' }
Add-Row 'Overlay' $(if ($ov) { 'PASS' } else { 'INFO' }) $(if ($ov) { 'running' } else { 'not running - start ApexOverlay.cmd for the HUD' })
$game = Get-Process -Name AC2 -ErrorAction SilentlyContinue
Add-Row 'ACC running' $(if ($game) { 'PASS' } else { 'INFO' }) $(if ($game) { 'yes' } else { 'no (only needed while driving)' })

# ---- 7. display
$dpi = (Get-ItemProperty 'HKCU:\Control Panel\Desktop\WindowMetrics' -ErrorAction SilentlyContinue).AppliedDPI
$scale = if ($dpi) { [math]::Round($dpi / 96 * 100) } else { 100 }
Add-Row 'Display scaling' 'INFO' "$scale% (the overlay is per-monitor DPI aware)"
$free = [math]::Round((Get-PSDrive ((Split-Path $base -Qualifier).TrimEnd(':'))).Free / 1GB, 1)
Add-Row 'Free space' $(if ($free -ge 2) { 'PASS' } else { 'FAIL' }) "$free GB on $((Split-Path $base -Qualifier))"

$rows | Format-Table -AutoSize | Out-String -Width 120 | Write-Output
$fails = @($rows | Where-Object { $_.Result -eq 'FAIL' }).Count
$rows | ForEach-Object { '{0,-16} {1,-4} {2}' -f $_.Check, $_.Result, $_.Detail } | Set-Content -Path $log -Encoding UTF8
Write-Output ("{0} required check(s) failing.  log: {1}" -f $fails, $log)