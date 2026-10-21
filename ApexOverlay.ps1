<#
  Apex Overlay - a small, always-on-top HUD for Assetto Corsa / ACC.

  Why this is a separate program: a web page (which is what the Apex window runs) cannot
  create an OS window that stays above a fullscreen game, and it cannot start another
  program either. This script is a plain WinForms window with TopMost set, so it floats
  over the game, and it reads the game's shared memory directly - which is also how it
  gets the session type, the session clock and the lap times that Apex never receives.

  Control: the Apex settings panel drives it over 127.0.0.1:7799 (show / hide / lock /
  size), so those buttons act on the thing that is actually on screen. The tray icon does
  the same without Apex.

  Data (read-only): Local\acpmf_graphics / acpmf_physics / acpmf_static.
  Nothing is written to the game and nothing leaves the machine.

  Switches:
    -Diag            print what the shared memory looks like right now, then exit
    -Shot out.png    render the HUD to a PNG, then exit  (add -Demo for sample values)
#>
param([Parameter(Position=0)][string]$Uri = '', [string]$Shot = '', [switch]$Demo, [switch]$Diag,
      [string]$Lang = '')

# ---------------------------------------------------------------- language
# The overlay is a separate process, so it cannot read Apex's own language setting. It follows
# the Windows UI language instead, which is what a panel floating over a game should do.
function Get-UiLang {
  $n = ''
  try { $n = [System.Globalization.CultureInfo]::CurrentUICulture.Name } catch { }
  if (-not $n) { try { $n = (Get-UICulture).Name } catch { } }
  if ($n -match '^zh') {
    if ($n -match '(?i)tw|hk|mo|hant') { return 'hant' }
    return 'hans'
  }
  return 'en'
}
$script:lang = if ($Lang -eq 'hans' -or $Lang -eq 'hant' -or $Lang -eq 'en') { $Lang } else { Get-UiLang }

$L10N = @{
  hans = @{
    'total' = '合计'; 'unit.s' = 's'
    'phase.idle' = '待起步'; 'phase.run' = '计时中'; 'phase.half' = '已过 100'; 'phase.done' = '完成'
    'r.session' = '赛段'; 'r.fuel' = '油量'; 'r.lap' = '圈速'
    'laps' = '圈'; 'nolimit' = '不限时'
    'wait.title' = '等待 Assetto Corsa / ACC'; 'wait.sub' = '进入赛道后自动出现'
    'sess.0' = '练习'; 'sess.1' = '排位'; 'sess.2' = '正赛'; 'sess.3' = '热圈'
    'sess.4' = '计时赛'; 'sess.5' = '漂移'; 'sess.6' = '直线'; 'sess.other' = '赛段'
    'toast.locked' = '已锁定'; 'toast.unlocked' = '已解锁'
    'tray.show' = '显示叠加层'; 'tray.hide' = '隐藏叠加层'; 'tray.lock' = '锁定位置'
    'tray.s' = '尺寸 小'; 'tray.m' = '尺寸 中'; 'tray.l' = '尺寸 大'
    'tray.shortcut' = '创建桌面快捷方式'; 'tray.startup' = '开机自启'
    'tray.proto' = '一键启动（注册 apexoverlay: 协议）'; 'tray.quit' = '退出'
    'msg.shortcut' = '桌面快捷方式已创建：'; 'msg.fail' = '创建失败：'
    'msg.hidden' = '叠加层已隐藏 · 托盘双击，或在 Apex 设置里点「显示叠加层」可恢复'
  }
  hant = @{
    'total' = '合計'; 'unit.s' = 's'
    'phase.idle' = '待起步'; 'phase.run' = '計時中'; 'phase.half' = '已過 100'; 'phase.done' = '完成'
    'r.session' = '賽段'; 'r.fuel' = '油量'; 'r.lap' = '圈速'
    'laps' = '圈'; 'nolimit' = '不限時'
    'wait.title' = '等待 Assetto Corsa / ACC'; 'wait.sub' = '進入賽道後自動出現'
    'sess.0' = '練習'; 'sess.1' = '排位'; 'sess.2' = '正賽'; 'sess.3' = '熱圈'
    'sess.4' = '計時賽'; 'sess.5' = '漂移'; 'sess.6' = '直線'; 'sess.other' = '賽段'
    'toast.locked' = '已鎖定'; 'toast.unlocked' = '已解鎖'
    'tray.show' = '顯示疊加層'; 'tray.hide' = '隱藏疊加層'; 'tray.lock' = '鎖定位置'
    'tray.s' = '尺寸 小'; 'tray.m' = '尺寸 中'; 'tray.l' = '尺寸 大'
    'tray.shortcut' = '建立桌面捷徑'; 'tray.startup' = '開機自動啟動'
    'tray.proto' = '一鍵啟動（註冊 apexoverlay: 協議）'; 'tray.quit' = '結束'
    'msg.shortcut' = '桌面捷徑已建立：'; 'msg.fail' = '建立失敗：'
    'msg.hidden' = '疊加層已隱藏 · 托盤雙擊，或在 Apex 設定裡點「顯示疊加層」可恢復'
  }
  en = @{
    'total' = 'Total'; 'unit.s' = 's'
    'phase.idle' = 'Idle'; 'phase.run' = 'Timing'; 'phase.half' = 'Past 100'; 'phase.done' = 'Done'
    'r.session' = 'Session'; 'r.fuel' = 'Fuel'; 'r.lap' = 'Lap'
    'laps' = 'laps'; 'nolimit' = 'no limit'
    'wait.title' = 'Waiting for Assetto Corsa / ACC'; 'wait.sub' = 'Appears once you are on track'
    'sess.0' = 'Practice'; 'sess.1' = 'Qualify'; 'sess.2' = 'Race'; 'sess.3' = 'Hotlap'
    'sess.4' = 'Time attack'; 'sess.5' = 'Drift'; 'sess.6' = 'Drag'; 'sess.other' = 'Session'
    'toast.locked' = 'Locked'; 'toast.unlocked' = 'Unlocked'
    'tray.show' = 'Show overlay'; 'tray.hide' = 'Hide overlay'; 'tray.lock' = 'Lock position'
    'tray.s' = 'Size small'; 'tray.m' = 'Size medium'; 'tray.l' = 'Size large'
    'tray.shortcut' = 'Create desktop shortcut'; 'tray.startup' = 'Start with Windows'
    'tray.proto' = 'One-click start (registers apexoverlay:)'; 'tray.quit' = 'Quit'
    'msg.shortcut' = 'Desktop shortcut created: '; 'msg.fail' = 'Could not create: '
    'msg.hidden' = 'Overlay hidden - double-click the tray icon, or use "Show overlay" in Apex'
  }
}
function T([string]$k) {
  $t = $L10N[$script:lang]
  if ($t -and $t.ContainsKey($k)) { return $t[$k] }
  if ($L10N['en'].ContainsKey($k)) { return $L10N['en'][$k] }
  return $k
}


$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

# ---------------------------------------------------------------- paths / state
$StateDir  = Join-Path $env:LOCALAPPDATA 'Apex'
$StateFile = Join-Path $StateDir 'overlay.json'
if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Path $StateDir -Force | Out-Null }

$script:mtx = $null
if (-not $Shot -and -not $Diag) {
  $created = $false
  try { $script:mtx = [System.Threading.Mutex]::new($true, 'Local\ApexOverlay_v1', [ref]$created) }
  catch { $created = $true }
  if (-not $created) { return }        # already running: the tray icon is the way back in
}

function New-State {
  [ordered]@{
    x = -1; y = -1; size = 'm'; lock = $false; forceShow = $false; hidden = $false; leftScale = 1000
    pb = @{}       # "car|track" -> @{ a = 0-100 s; s = 100-200 s; t = total }
    fuel = @{}     # "car|track" -> @{ lpl = litres per lap }
    lapBest = @{}  # "car|track" -> best lap in ms, kept across sessions
  }
}
$State = New-State
if (Test-Path $StateFile) {
  try {
    $j = Get-Content $StateFile -Raw | ConvertFrom-Json
    foreach ($k in 'x','y','size','lock','forceShow','hidden','leftScale') { if ($null -ne $j.$k) { $State[$k] = $j.$k } }
    # pb and fuel are "car|track" -> nested record, so every entry is rebuilt as a hashtable.
    foreach ($grp in 'pb','fuel') {
      if ($j.$grp) {
        foreach ($p in $j.$grp.PSObject.Properties) {
          $inner = @{}
          if ($null -ne $p.Value) {
            foreach ($q in $p.Value.PSObject.Properties) { $inner[$q.Name] = $q.Value }
          }
          $State[$grp][$p.Name] = $inner
        }
      }
    }
    # lapBest is a FLAT map of "car|track" -> best lap in milliseconds, so its values are
    # plain numbers, not the nested records above. Sending it through the same pass stored an
    # EMPTY hashtable for every entry - a number has no sub-properties to copy - and the first
    # read of that entry then threw "cannot convert Hashtable to Double" on EVERY tick, which
    # aborted Update-All before Serve-Control and Render-Frame ever ran: the HUD froze on
    # whatever was last drawn and the control endpoint the Apex panel reads went silent.
    # Only numbers are accepted here, so a state file already corrupted this way heals itself
    # on the next start instead of bricking the overlay on that car and track.
    if ($j.lapBest) {
      foreach ($p in $j.lapBest.PSObject.Properties) {
        $v = $p.Value
        if ($v -is [int] -or $v -is [long] -or $v -is [double] -or $v -is [decimal]) {
          $State['lapBest'][$p.Name] = [int]$v
        }
      }
    }
  } catch { }
}
function Save-State {
  try { $State | ConvertTo-Json -Depth 6 | Set-Content -Path $StateFile -Encoding UTF8 } catch { }
}

# One remembered best lap, 0 when there is none. lapBest is a flat "car|track" -> ms map, so a
# read has to tolerate whatever the file actually held: an entry written by a build that
# treated these as records lands here as a hashtable, and casting that straight to a number
# is exactly what used to tear the frame loop down. A value that is not a number is dropped
# instead, which also clears it from the next save.
function Get-LapBest([string]$key) {
  try {
    if (-not $State.lapBest -or -not $State.lapBest.ContainsKey($key)) { return 0 }
    $v = $State.lapBest[$key]
    if ($v -is [int]    -or $v -is [long] -or
        $v -is [double] -or $v -is [decimal]) { return [int]$v }
    try { $State.lapBest.Remove($key) } catch { }
  } catch { }
  return 0
}


# ---------------------------------------------------------------- shared memory
$script:gfV = $null; $script:phV = $null; $script:stV = $null
$script:bufG = New-Object byte[] 768
$script:bufP = New-Object byte[] 256
$script:bufS = New-Object byte[] 512
$script:lastTry = [datetime]::MinValue
$script:lastErr = ''

function Open-Page([string]$name, [int]$len) {
  # OpenExisting only - never create. Creating a mapping under the game's name would hand the
  # game a zero-filled page it did not ask for.
  foreach ($n in @("Local\$name", $name)) {
    try {
      $mmf = [System.IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting($n)
      return $mmf.CreateViewAccessor(0, $len, [System.IO.MemoryMappedFiles.MemoryMappedFileAccess]::Read)
    } catch { $script:lastErr = $_.Exception.Message }
  }
  return $null
}

function Connect-Pages {
  $script:lastTry = [datetime]::Now
  $script:gfV = Open-Page 'acpmf_graphics' 768
  $script:phV = Open-Page 'acpmf_physics' 256
  $script:stV = Open-Page 'acpmf_static' 512
  return ($null -ne $script:gfV -and $null -ne $script:phV)
}

function Read-I32($b, [int]$o) { [BitConverter]::ToInt32($b, $o) }
function Read-F32($b, [int]$o) { [BitConverter]::ToSingle($b, $o) }
function Read-WStr($b, [int]$o, [int]$n) {
  $s = [Text.Encoding]::Unicode.GetString($b, $o, $n * 2)
  $i = $s.IndexOf([char]0)
  if ($i -ge 0) { $s = $s.Substring(0, $i) }
  return $s.Trim()
}

function Read-Game {
  if (-not $script:gfV) {
    if (([datetime]::Now - $script:lastTry).TotalSeconds -lt 2) { return $null }
    if (-not (Connect-Pages)) { return $null }
  }
  try {
    $script:gfV.ReadArray(0, $script:bufG, 0, 768) | Out-Null
    $script:phV.ReadArray(0, $script:bufP, 0, 256) | Out-Null
    if ($script:stV) { $script:stV.ReadArray(0, $script:bufS, 0, 512) | Out-Null }
  } catch {
    $script:gfV = $null; $script:phV = $null; $script:stV = $null
    return $null
  }
  $g = $script:bufG; $p = $script:bufP; $s = $script:bufS
  $d = @{
    packet  = Read-I32 $g 0
    status  = Read-I32 $g 4
    session = Read-I32 $g 8
    laps    = Read-I32 $g 132
    cur     = Read-I32 $g 140
    last    = Read-I32 $g 144
    best    = Read-I32 $g 148
    leftRaw = Read-F32 $g 152
    inPit   = Read-I32 $g 160
    numLaps = Read-I32 $g 172
    fuel    = Read-F32 $p 12
    gear    = Read-I32 $p 16
    rpm     = Read-I32 $p 20
    speed   = Read-F32 $p 28
    # Physics page wheel block, same offsets as AC's SPageFilePhysics 1.7 - ACC keeps the head of
    # that layout intact. Read defensively: if a layout ever moves, the values land outside the
    # ranges checked below and the panel simply hides the tyre card instead of showing nonsense.
    press   = @((Read-F32 $p 88), (Read-F32 $p 92), (Read-F32 $p 96), (Read-F32 $p 100))
    wear    = @((Read-F32 $p 120), (Read-F32 $p 124), (Read-F32 $p 128), (Read-F32 $p 132))
    ttemp   = @((Read-F32 $p 152), (Read-F32 $p 156), (Read-F32 $p 160), (Read-F32 $p 164))
    car     = (Read-WStr $s 68 33)
    track   = (Read-WStr $s 134 33)
    maxRpm  = 0
    maxFuel = 0
    ok      = $false
  }
  # sessionTimeLeft is a float of SECONDS in the published layout, but ACC writes MILLISECONDS
  # (measured 541824 with 9:01.8 on the clock, and 10783 with seconds left on a 10 min session).
  # The numbers overlap, so the unit is decided by how fast the value moves and remembered in
  # the state file; the default is ms because that is what this title does.
  $raw = $d.leftRaw
  if ($raw -gt 43200 -and $script:leftScale -eq 1) { $script:leftScale = 1000; Save-LeftScale }
  $dt = ($script:now - $script:leftT)
  if ($script:leftLast -gt 0 -and $dt -ge 3 -and $dt -le 30) {
    $rate = [math]::Abs($raw - $script:leftLast) / $dt
    if ($rate -gt 20 -and $script:leftScale -ne 1000) { $script:leftScale = 1000; Save-LeftScale }
    elseif ($rate -gt 0.1 -and $rate -lt 5 -and $script:leftScale -ne 1) { $script:leftScale = 1; Save-LeftScale }
  }
  $script:leftLast = $raw
  $script:leftT = $script:now
  $d.left = $raw / $script:leftScale
  # ACC uses INT32_MAX for "no lap time yet"; without this the panel prints 35791 minutes.
  if ($d.last -ge 1000000000) { $d.last = 0 }
  if ($d.best -ge 1000000000) { $d.best = 0 }
  if ($d.cur -ge 1000000000) { $d.cur = 0 }

  # Sanity: a wrong layout shows up here long before it shows up on screen.
  # The lower bound on .left is NOT -1: AC keeps counting past zero once a session's clock has
  # run out while the car is still on track, and drag / unlimited practice simply report a
  # large negative from the start (measured -108499.2 on ks_drag with the car sitting on the
  # grid). Gating at -1 threw that whole packet away, so the HUD fell back to "Waiting for
  # Assetto Corsa / ACC" mid-session - which read as "AC does not work" while ACC, whose own
  # clock never goes negative in the same way, kept working. The render path already treats
  # anything <= 0.5 as "no limit", so a negative is display-correct here; the bound only has
  # to reject the kind of garbage a wrong layout produces, and it stays symmetric with the
  # upper bound for exactly that purpose.
  $d.ok = ($d.speed -ge -1 -and $d.speed -lt 600 -and $d.fuel -ge 0 -and $d.fuel -le 400 -and
           $d.session -ge -1 -and $d.session -le 8 -and $d.laps -ge 0 -and $d.laps -lt 100000 -and
           $d.left -ge -90000 -and $d.left -lt 90000)
  return $d
}

# ---------------------------------------------------------------- derived state
$script:carKey = ''
$script:lpl = 0.0
$script:lapStartFuel = -1.0
$script:lastLaps = -1
$script:run = @{ active = $false; armed = $true; t0 = 0.0; t100 = 0.0; t200 = 0.0; stoppedAt = 0.0 }
$script:sw = [System.Diagnostics.Stopwatch]::StartNew()
$script:now = 0.0
$script:data = $null
$script:leftScale = if ($State.leftScale -eq 1) { 1 } else { 1000 }
$script:leftLast = 0.0
$script:leftT = 0.0

function Session-Name([int]$t) {
  if ($t -lt 0 -or $t -gt 6) { return (T 'sess.other') }
  return (T ('sess.' + $t))
}
function Fmt-Lap([int]$ms) {
  if ($ms -le 0) { return '--:--.-' }
  $m = [math]::Floor($ms / 60000)
  $s = ($ms % 60000) / 1000.0
  return ('{0}:{1:00.0}' -f $m, $s)
}
function Fmt-Clock([double]$sec) {
  if ($sec -lt 0) { $sec = 0 }
  $t = [int][math]::Round($sec)
  $h = [math]::Floor($t / 3600); $m = [math]::Floor(($t % 3600) / 60); $s = $t % 60
  if ($h -gt 0) { return ('{0}:{1:00}:{2:00}' -f $h, $m, $s) }
  return ('{0:00}:{1:00}' -f $m, $s)
}
function Fmt-2([double]$v) { if ($v -le 0) { return '--.--' } return ('{0:0.00}' -f $v) }

# ---------------------------------------------------------------- palette
$C = @{
  bgTop = [Drawing.Color]::FromArgb(22, 25, 31)
  bgBot = [Drawing.Color]::FromArgb(10, 12, 15)
  edge  = [Drawing.Color]::FromArgb(52, 58, 68)
  sep   = [Drawing.Color]::FromArgb(34, 39, 47)
  tx    = [Drawing.Color]::FromArgb(246, 247, 249)
  dim   = [Drawing.Color]::FromArgb(150, 156, 166)
  faint = [Drawing.Color]::FromArgb(104, 110, 120)
  green = [Drawing.Color]::FromArgb(52, 211, 153)
  blue  = [Drawing.Color]::FromArgb(94, 164, 250)
  amber = [Drawing.Color]::FromArgb(250, 190, 60)
  red   = [Drawing.Color]::FromArgb(248, 113, 113)
}
$brTx = New-Object Drawing.SolidBrush $C.tx
$brDim = New-Object Drawing.SolidBrush $C.dim
$brFaint = New-Object Drawing.SolidBrush $C.faint
$brGreen = New-Object Drawing.SolidBrush $C.green
$brBlue = New-Object Drawing.SolidBrush $C.blue
$brAmber = New-Object Drawing.SolidBrush $C.amber
$brRed = New-Object Drawing.SolidBrush $C.red
$brPanel = New-Object Drawing.SolidBrush $C.bgBot
$penSep = New-Object Drawing.Pen $C.sep, 1
$penIcon = New-Object Drawing.Pen ([Drawing.Color]::FromArgb(150, 156, 166)), 1.4
$brGreenSoft = New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(46, 52, 211, 153))
$brBlueSoft  = New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(46, 94, 164, 250))
$brAmberSoft = New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(46, 250, 190, 60))
$brFaintSoft = New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(38, 104, 110, 120))
$penBarBlue  = New-Object Drawing.Pen $C.blue, 3
$penBarAmber = New-Object Drawing.Pen $C.amber, 3
$penBarRed   = New-Object Drawing.Pen $C.red, 3
# hover / press / state for the two header buttons: the glyphs are the only controls on the
# panel, so they need a plate under the pointer and a colour that says "locked"
$brHover     = New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(44, 246, 247, 249))
$brHoverOn   = New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(72, 246, 247, 249))
$brRedSoft   = New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(52, 248, 113, 113))
$brRedHover  = New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(72, 248, 113, 113))
$brToast     = New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(232, 34, 39, 47))
$penIconHot  = New-Object Drawing.Pen $C.tx, 1.5
$penLockOn   = New-Object Drawing.Pen $C.amber, 1.6
$penCloseHot = New-Object Drawing.Pen $C.red, 1.5

# The phase colour is animated rather than assigned. The chip, the top hairline, the hero figure
# and the background wash all slide from amber to green (or back) over roughly half a second, so
# a phase change reads as the panel settling into its new colour instead of swapping in one frame.
# Exponential approach: fast at first, asymptotic at the end, and it stops when it is within one
# level of the target so a settled HUD rebuilds nothing.
$script:brAcc = New-Object Drawing.SolidBrush $C.faint
$script:brAccSoft = New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(38, $C.faint.R, $C.faint.G, $C.faint.B))
$script:accNow = $null
$script:accSoftA = 38.0
$script:accAt = 0.0
function Step-Accent($target, [double]$softAlpha) {
  if ($null -eq $script:accNow -or $script:now -le 0.0) {
    $script:accNow = $target; $script:accSoftA = $softAlpha; $script:accAt = $script:now
    return $target
  }
  $dt = $script:now - $script:accAt
  if ($dt -le 0.0) { return $script:accNow }
  if ($dt -gt 0.5) { $dt = 0.5 }
  $script:accAt = $script:now
  # 0.26 s: the HUD repaints at 12.5 Hz, so a faster curve would land in three or four visible
  # steps. This one reads as one continuous move over about two thirds of a second.
  $a = 1.0 - [math]::Exp(-$dt / 0.26)
  # $cur, not $c: PowerShell variable names are case-insensitive, so a $c here would shadow the
  # palette hashtable $C that every other draw call reads from.
  $cur = $script:accNow
  $r = $cur.R + ($target.R - $cur.R) * $a
  $g = $cur.G + ($target.G - $cur.G) * $a
  $b = $cur.B + ($target.B - $cur.B) * $a
  $script:accSoftA = $script:accSoftA + ($softAlpha - $script:accSoftA) * $a
  if ([math]::Abs($r - $target.R) -lt 1.0 -and [math]::Abs($g - $target.G) -lt 1.0 -and [math]::Abs($b - $target.B) -lt 1.0) {
    $script:accNow = $target
    $script:accSoftA = $softAlpha
  } else {
    $script:accNow = [Drawing.Color]::FromArgb([int][math]::Round($r), [int][math]::Round($g), [int][math]::Round($b))
  }
  return $script:accNow
}

# Same application icon as the Apex window. Loaded once and drawn with uniform scaling so
# a non-square source can never be stretched; the current 80x80 asset stays square.
$script:icon = $null
$iconPath = Join-Path $PSScriptRoot 'overlay-icon.png'
if (Test-Path $iconPath) {
  try { $script:icon = [Drawing.Image]::FromFile($iconPath) } catch { $script:icon = $null }
}

$sfL = New-Object Drawing.StringFormat; $sfL.Alignment = 'Near'; $sfL.LineAlignment = 'Center'
$sfR = New-Object Drawing.StringFormat; $sfR.Alignment = 'Far';  $sfR.LineAlignment = 'Center'
$sfC = New-Object Drawing.StringFormat; $sfC.Alignment = 'Center'; $sfC.LineAlignment = 'Center'
$sfEll = New-Object Drawing.StringFormat
$sfEll.Alignment = 'Far'; $sfEll.LineAlignment = 'Center'; $sfEll.Trimming = 'EllipsisCharacter'

$script:fonts = @{}
function F([string]$face, [single]$pt, [string]$style) {
  # the point size is part of the key, otherwise the cache keeps the old size after 小/中/大
  $id = '{0}|{1}|{2}' -f $face, $pt, $style
  if (-not $script:fonts.ContainsKey($id)) {
    $script:fonts[$id] = New-Object Drawing.Font $face, $pt, ([Drawing.FontStyle]$style), 'Point'
  }
  return $script:fonts[$id]
}
function Draw-Text($g, [string]$text, $font, $brush, [double]$x, [double]$y, [double]$w, [double]$h, $sf) {
  $g.DrawString($text, $font, $brush, [Drawing.RectangleF]::new([single]$x, [single]$y, [single]$w, [single]$h), $sf)
}

# ---------------------------------------------------------------- window
$script:scale = 1.0
switch ($State.size) { 's' { $script:scale = 0.86 } 'l' { $script:scale = 1.18 } default { $script:scale = 1.0 } }

# A Region can only clip on whole pixels, so a rounded panel gets stair-stepped corners and a
# 1 px stroke that reads as a white frame over a bright game. A layered window pushed with
# UpdateLayeredWindow composites a 32bpp bitmap with per-pixel alpha instead: the corners are
# anti-aliased, the area outside the panel is truly transparent, and clicks that land there
# pass through to the game because fully transparent pixels are not hit-tested.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class ApexLayer {
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
  [StructLayout(LayoutKind.Sequential)] public struct SIZE { public int cx, cy; }
  [StructLayout(LayoutKind.Sequential, Pack = 1)] public struct BLENDFUNCTION {
    public byte BlendOp, BlendFlags, SourceConstantAlpha, AlphaFormat;
  }
  [DllImport("user32.dll")] static extern IntPtr GetDC(IntPtr h);
  [DllImport("user32.dll")] static extern int ReleaseDC(IntPtr h, IntPtr dc);
  [DllImport("gdi32.dll")] static extern IntPtr CreateCompatibleDC(IntPtr dc);
  [DllImport("gdi32.dll")] static extern IntPtr SelectObject(IntPtr dc, IntPtr o);
  [DllImport("gdi32.dll")] public static extern bool DeleteObject(IntPtr o);
  [DllImport("gdi32.dll")] static extern bool DeleteDC(IntPtr dc);
  [DllImport("user32.dll")] static extern bool UpdateLayeredWindow(IntPtr hwnd, IntPtr dst, ref POINT pd,
      ref SIZE ps, IntPtr src, ref POINT pSrc, int key, ref BLENDFUNCTION blend, int flags);
  [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr h, int i);
  [DllImport("user32.dll")] static extern int SetWindowLong(IntPtr h, int i, int v);
  [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  public static void MakeLayered(IntPtr h) {
    SetWindowLong(h, -20, GetWindowLong(h, -20) | 0x80000);
    // Apply the new extended style to an already-created HWND.
    SetWindowPos(h, IntPtr.Zero, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0004 | 0x0020);
  }
  public static bool Push(IntPtr hwnd, IntPtr hbmp, int w, int h, int x, int y, byte alpha) {
    IntPtr screen = GetDC(IntPtr.Zero);
    IntPtr mem = CreateCompatibleDC(screen);
    IntPtr old = SelectObject(mem, hbmp);
    POINT pd = new POINT(); pd.X = x; pd.Y = y;
    SIZE sz = new SIZE(); sz.cx = w; sz.cy = h;
    POINT ps = new POINT(); ps.X = 0; ps.Y = 0;
    BLENDFUNCTION bf = new BLENDFUNCTION();
    bf.BlendOp = 0; bf.BlendFlags = 0; bf.SourceConstantAlpha = alpha; bf.AlphaFormat = 1;
    bool ok = UpdateLayeredWindow(hwnd, screen, ref pd, ref sz, mem, ref ps, 0, ref bf, 2);
    SelectObject(mem, old);
    DeleteDC(mem);
    ReleaseDC(IntPtr.Zero, screen);
    return ok;
  }
}
'@

# The panel fill used to be a GDI+ LinearGradientBrush. A 12-level ramp spread over ~200 px is
# only about fifteen distinct 8-bit colours, so the compositor turned it into a stack of visible
# horizontal bands - the "lines" that read as stripes over the game. This builds the same field
# at float precision and quantises it through an 8x8 Bayer matrix, so no single row can own a
# step; the surface reads as one soft, blurred plane instead. Add-Type also compiles it once,
# which keeps a frame cheap: the bitmap is built on size/phase changes only.
Add-Type -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

public class ApexGlass {
  static readonly int[] Bayer = BuildBayer();

  static int[] BuildBayer() {
    int[] m = new int[] { 0 };
    int n = 1;
    while (n < 8) {
      int[] next = new int[(n * 2) * (n * 2)];
      for (int y = 0; y < n; y++) {
        for (int x = 0; x < n; x++) {
          int v = 4 * m[y * n + x];
          next[y * 2 * n + x] = v;
          next[y * 2 * n + x + n] = v + 2;
          next[(y + n) * 2 * n + x] = v + 3;
          next[(y + n) * 2 * n + x + n] = v + 1;
        }
      }
      m = next; n *= 2;
    }
    return m;
  }

  static double Clamp(double v) { return v < 0 ? 0 : (v > 255 ? 255 : v); }

  public static Bitmap Backdrop(int w, int h, Color top, Color bottom, Color accent) {
    Bitmap bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb);
    BitmapData bd = bmp.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
    byte[] buf = new byte[bd.Stride * h];
    double iw = 1.0 / Math.Max(1, w);
    double ih = 1.0 / Math.Max(1, h);
    // The sheen is a product of one x term and one y term, so both can be precomputed: the
    // phase colour is animated, which means this bitmap can be rebuilt on every frame for the
    // half second a transition lasts, and no exp() may survive in the pixel loop.
    double[] xf = new double[w];
    for (int x = 0; x < w; x++) {
      double dx = ((x + 0.5) * iw - 0.08) / 0.66;
      xf[x] = Math.Exp(-(dx * dx) * 1.30);
    }
    for (int y = 0; y < h; y++) {
      double ty = (y + 0.5) * ih;
      // Almost linear ramp, eased only at the two ends so neither terminates in a hard stop
      // against the 1 px edge.
      double v = 0.72 * ty + 0.28 * (ty * ty * (3.0 - 2.0 * ty));
      double baseR = top.R + (bottom.R - top.R) * v;
      double baseG = top.G + (bottom.G - top.G) * v;
      double baseB = top.B + (bottom.B - top.B) * v;

      // Frosted light: one broad, off-centre falloff. A blurred dark surface still keeps one
      // soft bright corner, and that is what separates "glass" from "flat rectangle".
      double dy = (ty + 0.30) / 0.92;
      double sy = Math.Exp(-(dy * dy) * 1.30) * 7.0;

      // Phase colour: a wash leaving from the top edge plus a faint retention along the
      // bottom, so the panel still says which phase it is without turning into a colour slab.
      // The 0.55 exponent is deliberate: a steeper falloff left the middle of the panel duller
      // than the gradient it replaced, and "fix the banding" must not quietly change the colour.
      double tint = Math.Pow(1.0 - ty, 0.55) * 0.190 + Math.Pow(ty, 2.0) * 0.050;
      double keep = 1.0 - tint;
      double ar = accent.R * tint, ag = accent.G * tint, ab = accent.B * tint;
      int row = y * bd.Stride;
      int bayerRow = (y & 7) * 8;

      for (int x = 0; x < w; x++) {
        double sheen = xf[x] * sy;
        double r = (baseR + sheen * 0.92) * keep + ar;
        double g = (baseG + sheen) * keep + ag;
        double b = (baseB + sheen * 1.06) * keep + ab;

        // Ordered dither, +/-1 level: the ramp stays continuous, only the rounding is noisy.
        // Truncate-and-bias instead of Math.Round: this loop runs on every frame of a colour
        // transition, and 200k Math.Round calls measured at about 3 ms of the frame budget.
        double d = ((Bayer[bayerRow + (x & 7)] + 0.5) / 64.0 - 0.5) * 1.9 + 0.5;
        double vr = r + d, vg = g + d, vb = b + d;
        int rr = (int)vr; int gg = (int)vg; int bb = (int)vb;
        if (rr < 0) rr = 0; else if (rr > 255) rr = 255;
        if (gg < 0) gg = 0; else if (gg > 255) gg = 255;
        if (bb < 0) bb = 0; else if (bb > 255) bb = 255;

        int i = row + x * 4;
        buf[i] = (byte)bb; buf[i + 1] = (byte)gg; buf[i + 2] = (byte)rr; buf[i + 3] = 255;
      }
    }
    Marshal.Copy(buf, 0, bd.Scan0, buf.Length);
    bmp.UnlockBits(bd);
    return bmp;
  }
}
'@ -ReferencedAssemblies System.Drawing


# PowerShell/WinForms is DPI-unaware by default. At 125% Windows then scales the HWND
# after WinForms positions it, so a saved y that clamped correctly became 1077 px and the
# HUD was cut off below the screen. Opt into physical pixels before creating the form.
# Per-monitor v2 first: on a 125%/150% display it renders the HUD at true device pixels
# (system-DPI aware is already crisp on one monitor, but goes soft when monitors differ).
try {
  Add-Type -Namespace ApexDpi -Name Ctx -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);' -ErrorAction SilentlyContinue
  if (-not [ApexDpi.Ctx]::SetProcessDpiAwarenessContext([IntPtr](-4))) { throw 'fallback' }
} catch {
  try { [ApexLayer]::SetProcessDPIAware() | Out-Null } catch { }
}

$form = New-Object System.Windows.Forms.Form
$form.FormBorderStyle = 'None'
$form.StartPosition = 'Manual'
$form.TopMost = $true
$form.ShowInTaskbar = $false
$form.BackColor = [Drawing.Color]::FromArgb(12, 14, 18)
$form.Text = 'Apex Overlay'
$form.MinimizeBox = $false
$form.MaximizeBox = $false
try {
  $prop = $form.GetType().GetProperty('DoubleBuffered', [Reflection.BindingFlags]'Instance,NonPublic')
  $prop.SetValue($form, $true, $null)
} catch { }

function Get-Layout {
  $k = $script:scale
  @{ w = [int](252 * $k); h = [int](202 * $k); pad = [int](14 * $k) }
}

# Every frame is composed into one ARGB bitmap and handed to the compositor. Text uses
# grayscale anti-aliasing here: ClearType needs an opaque background and would fringe against
# transparent pixels.
$script:frame = $null
$script:hbmp = [IntPtr]::Zero
$script:layered = $false
$script:alpha = 240
$script:layerLogged = $false
# Apply WS_EX_LAYERED before the first Show as well as in Shown. Setting it only after the
# form was already on screen could leave a plain black window with no composed bitmap.
try {
  [ApexLayer]::MakeLayered($form.Handle)
  $script:layered = $true
} catch { }
# If the layered path cannot be used, still paint the HUD on the form instead of leaving
# a black rectangle. The fallback loses per-pixel transparency, not the information.
$form.Add_Paint({
  param($sender, $e)
  if (-not $script:layered) {
    try { Draw-Hud $e.Graphics } catch { }
  }
})
function Render-Frame {
  $L = Get-Layout
  $w = [int]$L.w; $h = [int]$L.h
  if ($null -eq $script:frame -or $script:frame.Width -ne $w -or $script:frame.Height -ne $h) {
    if ($script:frame) { $script:frame.Dispose() }
    if ($script:hbmp -ne [IntPtr]::Zero) { [ApexLayer]::DeleteObject($script:hbmp); $script:hbmp = [IntPtr]::Zero }
    $script:frame = New-Object Drawing.Bitmap $w, $h, ([Drawing.Imaging.PixelFormat]::Format32bppArgb)
  }
  $g = [Drawing.Graphics]::FromImage($script:frame)
  $g.Clear([Drawing.Color]::FromArgb(0, 0, 0, 0))
  $g.SmoothingMode = 'AntiAlias'
  $g.TextRenderingHint = [Drawing.Text.TextRenderingHint]::AntiAliasGridFit
  # A swallowed paint error leaves the window fully transparent, which looks exactly like
  # "the overlay did not start". Log the first one so it stops being invisible.
  try { Draw-Hud $g } catch {
    if (-not $script:hudErr) {
      $script:hudErr = $true
      try { Add-Content -Path (Join-Path $StateDir 'overlay-error.log') -Value ('[' + (Get-Date -Format 'HH:mm:ss') + '] Draw-Hud: ' + $_.Exception.Message + ' @ ' + $_.InvocationInfo.ScriptLineNumber) } catch { }
    }
  }
  $g.Dispose()
  if (-not $script:layered -or -not $form.Visible) { return }
  if ($script:hbmp -ne [IntPtr]::Zero) { [ApexLayer]::DeleteObject($script:hbmp) }
  $script:hbmp = $script:frame.GetHbitmap([Drawing.Color]::FromArgb(0, 0, 0, 0))
  $ok = [ApexLayer]::Push($form.Handle, $script:hbmp, $w, $h, [int]$form.Left, [int]$form.Top, [byte]$script:alpha)
  if (-not $ok) {
    if (-not $script:layerLogged) {
      $script:layerLogged = $true
      try { Add-Content -Path (Join-Path $StateDir 'overlay-layer.log') -Value ('[' + (Get-Date -Format 'HH:mm:ss') + '] UpdateLayeredWindow failed; using paint fallback') } catch { }
    }
    # Stop trying to compose into a layered surface and let the Paint handler draw.
    $script:layered = $false
    $form.Invalidate()
  }
}

function Rounded([double]$x, [double]$y, [double]$w, [double]$h, [double]$r) {
  $path = New-Object Drawing.Drawing2D.GraphicsPath
  $d = $r * 2
  $path.AddArc([single]$x, [single]$y, [single]$d, [single]$d, 180, 90)
  $path.AddArc([single]($x + $w - $d), [single]$y, [single]$d, [single]$d, 270, 90)
  $path.AddArc([single]($x + $w - $d), [single]($y + $h - $d), [single]$d, [single]$d, 0, 90)
  $path.AddArc([single]$x, [single]($y + $h - $d), [single]$d, [single]$d, 90, 90)
  $path.CloseFigure()
  return $path
}

# Both header glyphs are drawn from the same 24x24 stroke grid the rest of the UI borrows from
# (Lucide's lock / lock-open / x): one continuous shackle with round caps, a rounded body and
# two round-capped diagonals. The old padlock was a square-cornered rectangle plus a bare arc,
# which at 11 px looked like it had been drawn with a ruler rather than a pen.
function Icon-Pen($pen) {
  # The palette pens are shared with other strokes, so the round caps live on a copy.
  $p = $pen.Clone()
  $p.StartCap = [Drawing.Drawing2D.LineCap]::Round
  $p.EndCap = [Drawing.Drawing2D.LineCap]::Round
  $p.LineJoin = [Drawing.Drawing2D.LineJoin]::Round
  return $p
}

function Build-LockPath([double]$cx, [double]$cy, [double]$s, [bool]$closed) {
  $u = $s / 24.0
  $x0 = $cx - $s / 2
  $y0 = $cy - $s / 2

  # body: 3..21 x 11..22, corner radius 2
  $bx = $x0 + 3 * $u; $by = $y0 + 11 * $u
  $bw = 18 * $u; $bh = 11 * $u; $r2 = 4 * $u
  $body = New-Object Drawing.Drawing2D.GraphicsPath
  $body.AddArc([single]$bx, [single]$by, [single]$r2, [single]$r2, 180, 90)
  $body.AddArc([single]($bx + $bw - $r2), [single]$by, [single]$r2, [single]$r2, 270, 90)
  $body.AddArc([single]($bx + $bw - $r2), [single]($by + $bh - $r2), [single]$r2, [single]$r2, 0, 90)
  $body.AddArc([single]$bx, [single]($by + $bh - $r2), [single]$r2, [single]$r2, 90, 90)
  $body.CloseFigure()

  # shackle: up out of the body, over the top, and either back down into it (locked) or left
  # short of it (open). One path, so the two ends cannot drift apart.
  $sh = New-Object Drawing.Drawing2D.GraphicsPath
  $sh.AddLine([single]($x0 + 7 * $u), [single]($y0 + 11 * $u), [single]($x0 + 7 * $u), [single]($y0 + 7 * $u))
  if ($closed) {
    # The arc box is centred on (12,7) with r = 5, so its left edge is x = 7 - the x the leg
    # arrives on. AddArc would silently draw a connector if those two did not meet.
    $sh.AddArc([single]($x0 + 7 * $u), [single]($y0 + 2 * $u), [single](10 * $u), [single](10 * $u), 180, 180)
    $sh.AddLine([single]($x0 + 17 * $u), [single]($y0 + 7 * $u), [single]($x0 + 17 * $u), [single]($y0 + 11 * $u))
  } else {
    $sh.AddArc([single]($x0 + 7 * $u), [single]($y0 + 2 * $u), [single](10 * $u), [single](10 * $u), 180, 168)
  }
  # Body and shackle in one path: the glyph is stroked as a single shape, so the joins where
  # the shackle meets the body are rounded instead of overlapping caps.
  $body.AddPath($sh, $false)
  $sh.Dispose()
  return $body
}

function Build-ClosePath([double]$cx, [double]$cy, [double]$s) {
  $u = $s / 24.0
  $x0 = $cx - $s / 2
  $y0 = $cy - $s / 2
  $path = New-Object Drawing.Drawing2D.GraphicsPath
  $path.AddLine([single]($x0 + 6 * $u), [single]($y0 + 6 * $u), [single]($x0 + 18 * $u), [single]($y0 + 18 * $u))
  # StartFigure is the whole glyph: without it the second AddLine continues from the end of the
  # first, and the two diagonals are stroked as one zig-zag - an X with a bar across its right
  # side. The lock builds separate subpaths and never had this problem.
  $path.StartFigure()
  $path.AddLine([single]($x0 + 18 * $u), [single]($y0 + 6 * $u), [single]($x0 + 6 * $u), [single]($y0 + 18 * $u))
  return $path
}

# One backdrop bitmap (and the brush that maps it 1:1 onto the panel) per size and accent.
# Building either costs a few milliseconds, so they are kept for every frame that does not move
# the phase colour; during a transition the accent does move, and this is where that cost lands.
$script:backdrop = $null
$script:bgBrush = $null
$script:backdropKey = ''
function Get-BackdropBrush([int]$w, [int]$h, $accent) {
  $key = '{0}x{1}|{2}' -f $w, $h, $accent.ToArgb()
  if ($null -ne $script:bgBrush -and $script:backdropKey -eq $key) { return $script:bgBrush }
  $script:backdrop = [ApexGlass]::Backdrop($w, $h, $C.bgTop, $C.bgBot, $accent)
  if ($null -ne $script:bgBrush) { $script:bgBrush.Dispose() }
  $script:bgBrush = New-Object Drawing.TextureBrush $script:backdrop, ([Drawing.Drawing2D.WrapMode]::Clamp)
  $script:backdropKey = $key
  return $script:bgBrush
}

# Everything that only depends on the panel size: the rounded outline, the two rim pens, the two
# header glyphs and their round-capped pens. These used to be built on every frame - a dozen GDI+
# objects at 12.5 Hz - which is most of why a colour transition could not be drawn often enough
# to look continuous. One cache per scale makes a 30 Hz fade affordable.
$script:chrome = @{}
function Get-Chrome([double]$k) {
  $key = '{0:0.###}' -f $k
  if ($script:chrome.ContainsKey($key)) { return $script:chrome[$key] }
  $L = Get-Layout
  $w = [int]$L.w; $h = [int]$L.h
  $halo = [Drawing.Pen]::new([Drawing.Color]::FromArgb(30, 160, 176, 198), [single](2.0 * $k))
  $halo.Alignment = 'Inset'
  $edge = [Drawing.Pen]::new([Drawing.Color]::FromArgb(72, 142, 154, 174), [single](1.0 * $k))
  $edge.Alignment = 'Inset'
  $rl = Get-IconRect 'lock'
  $rc = Get-IconRect 'close'
  $o = @{
    path = (Rounded 0.5 0.5 ($w - 1) ($h - 1) (12 * $k))
    halo = $halo
    edge = $edge
    lockClosed = (Build-LockPath ($rl.Left + $rl.Width / 2) ($rl.Top + $rl.Height / 2) (15.5 * $k) $true)
    lockOpen = (Build-LockPath ($rl.Left + $rl.Width / 2) ($rl.Top + $rl.Height / 2) (15.5 * $k) $false)
    close = (Build-ClosePath ($rc.Left + $rc.Width / 2) ($rc.Top + $rc.Height / 2) (18 * $k))
    penIcon = (Icon-Pen $penIcon)
    penLock = (Icon-Pen $penLockOn)
    penHot = (Icon-Pen $penIconHot)
    penClose = (Icon-Pen $penCloseHot)
  }
  $script:chrome[$key] = $o
  return $o
}

function Draw-Hud($g) {
  $L = Get-Layout
  $k = $script:scale
  $w = $L.w; $h = $L.h; $pad = $L.pad
  $g.SmoothingMode = 'AntiAlias'
  $g.CompositingQuality = 'HighQuality'
  $g.InterpolationMode = 'HighQualityBicubic'
  $g.PixelOffsetMode = 'HighQuality'
  $g.TextRenderingHint = [Drawing.Text.TextRenderingHint]::AntiAliasGridFit

  $d = $script:data
  $live = ($d -and $d.ok)

  $phase = 'idle'
  if ($script:run.t200 -gt 0) { $phase = 'done' }
  elseif ($script:run.t100 -gt 0) { $phase = 'half' }
  elseif ($script:run.active) { $phase = 'run' }

  # One eased colour drives every accent in the panel - the wash, the hairline, the chip, the
  # hero figure, the session dot - so a phase change is one slow move instead of four jumps.
  $phaseColor = switch ($phase) {
    'run' { $C.amber } 'half' { $C.blue } 'done' { $C.green } default { $C.faint }
  }
  $phaseSoftA = if ($phase -eq 'idle') { 38.0 } else { 46.0 }
  $accentColor = Step-Accent $phaseColor $phaseSoftA
  $script:brAcc.Color = $accentColor
  $script:brAccSoft.Color = [Drawing.Color]::FromArgb([int][math]::Round($script:accSoftA),
    $accentColor.R, $accentColor.G, $accentColor.B)
  $accentBrush = $script:brAcc
  $accentSoft = $script:brAccSoft
  # While the accent is still moving, a second timer repaints at 30 Hz instead of the 12.5 Hz
  # data tick. Without it the fade lands in about ten visible steps - the "dropped frames" look.
  $script:fading = ($accentColor.ToArgb() -ne $phaseColor.ToArgb())

  # Rounded glass panel: one dithered bitmap (no band edges), then the 2 px halo and the 1 px
  # rim. The outline and both rim pens come from the per-size cache.
  $chrome = Get-Chrome $k
  $g.FillPath((Get-BackdropBrush $w $h $accentColor), $chrome.path)
  $g.DrawPath($chrome.halo, $chrome.path)
  $g.DrawPath($chrome.edge, $chrome.path)

  # Thin phase accent along the top edge.
  $accentPen = [Drawing.Pen]::new([Drawing.Color]::FromArgb(220, $accentColor.R, $accentColor.G, $accentColor.B), [single](1.5 * $k))
  $g.DrawLine($accentPen, [single]($pad), [single](1.2 * $k), [single]($w - $pad), [single](1.2 * $k))
  $accentPen.Dispose()

  # ---- header: application icon, name, phase chip, then the two icon buttons
  $logoX = 12 * $k; $logoY = 6 * $k; $logoBox = 18 * $k
  if ($script:icon) {
    $g.InterpolationMode = 'HighQualityBicubic'
    $g.PixelOffsetMode = 'HighQuality'
    $iw = $script:icon.Width; $ih = $script:icon.Height
    $fit = [math]::Min($logoBox / $iw, $logoBox / $ih)
    $dw = $iw * $fit; $dh = $ih * $fit
    $dx = $logoX + ($logoBox - $dw) / 2
    $dy = $logoY + ($logoBox - $dh) / 2
    $dest = [Drawing.RectangleF]::new([single]$dx, [single]$dy, [single]$dw, [single]$dh)
    $src = [Drawing.RectangleF]::new(0, 0, [single]$iw, [single]$ih)
    $g.DrawImage($script:icon, $dest, $src, [Drawing.GraphicsUnit]::Pixel)
  } else {
    $logo = Rounded $logoX $logoY $logoBox $logoBox (6 * $k)
    $g.FillPath($accentSoft, $logo)
    $logo.Dispose()
    Draw-Text $g 'A' (F 'Segoe UI' (9.5 * $k) 'Bold') $accentBrush $logoX $logoY $logoBox $logoBox $sfC
  }
  Draw-Text $g 'APEX HUD' (F 'Segoe UI' (8.4 * $k) 'Bold') $brTx (35 * $k) (6 * $k) 120 (18 * $k) $sfL

  if ($live) {
    # The chip used to be a fixed 52 px. "已過 100" is wider than that once GDI+ falls back to a
    # CJK face, and DrawString clips to its layout rectangle - which is why the badge read
    # "已過 10". It is measured with the same format it is drawn with and grows to the left, so
    # the two icon buttons keep their positions and the label is never truncated.
    $fChip = F 'Segoe UI' (7.2 * $k) 'Bold'
    $chipTxt = (T ('phase.' + $phase))
    $chipH = 16 * $k
    $chipW = [math]::Max(52 * $k, $g.MeasureString($chipTxt, $fChip, 400, $sfC).Width + 9 * $k)
    $chipY = 7 * $k
    $chipX = ($w - 62 * $k) - $chipW
    $chipPath = Rounded $chipX $chipY $chipW $chipH (5 * $k)
    $g.FillPath($accentSoft, $chipPath)
    $chipPath.Dispose()
    Draw-Text $g $chipTxt $fChip $accentBrush $chipX $chipY $chipW $chipH $sfC
  }

  $rLock = Get-IconRect 'lock'
  $rClose = Get-IconRect 'close'
  foreach ($it in @(@{ n = 'lock'; r = $rLock }, @{ n = 'close'; r = $rClose })) {
    $on = ($script:press -eq $it.n -or $script:hover -eq $it.n)
    if ($on) {
      $plate = Rounded $it.r.Left $it.r.Top $it.r.Width $it.r.Height (5 * $k)
      $soft = if ($it.n -eq 'close') { if ($script:press -eq 'close') { $brRedHover } else { $brRedSoft } }
              else { if ($script:press -eq 'lock') { $brHoverOn } else { $brHover } }
      $g.FillPath($soft, $plate)
      $plate.Dispose()
    }
  }
  $penL = $chrome.penIcon
  if ($State.lock) { $penL = $chrome.penLock }
  elseif ($script:hover -eq 'lock' -or $script:press -eq 'lock') { $penL = $chrome.penHot }
  $penC = $chrome.penIcon
  if ($script:hover -eq 'close' -or $script:press -eq 'close') { $penC = $chrome.penClose }
  # The glyphs are cached paths on a 24 px grid (15.5 puts an 11.6 px body in a 22 px target).
  if ($State.lock) { $g.DrawPath($penL, $chrome.lockClosed) } else { $g.DrawPath($penL, $chrome.lockOpen) }
  $g.DrawPath($penC, $chrome.close)

  if ($script:toast -and $script:now -lt $script:toastUntil) {
    $fToast = F 'Segoe UI' (7.4 * $k) 'Bold'
    $tw = $g.MeasureString($script:toast, $fToast).Width + 12 * $k
    $tx = [math]::Max(86 * $k, $rLock.Left - 6 * $k - $tw)
    $tp = Rounded $tx (6 * $k) $tw (17 * $k) (4 * $k)
    $g.FillPath($brToast, $tp)
    $tp.Dispose()
    Draw-Text $g $script:toast $fToast $brTx $tx (6 * $k) $tw (17 * $k) $sfC
  }
  $g.DrawLine($penSep, 0, 30 * $k, $w, 30 * $k)

  if (-not $live) {
    Draw-Text $g (T 'wait.title') (F 'Segoe UI' (10 * $k) 'Regular') $brDim $pad (($h / 2) - 26 * $k) ($w - $pad * 2) (20 * $k) $sfC
    Draw-Text $g (T 'wait.sub') (F 'Segoe UI' (7.6 * $k) 'Regular') $brFaint $pad (($h / 2) - 4 * $k) ($w - $pad * 2) (16 * $k) $sfC
    return
  }

  $fLab = F 'Segoe UI' (7.3 * $k) 'Regular'
  $fRowKey = F 'Segoe UI' (8.2 * $k) 'Regular'
  $fRowVal = F 'Segoe UI' (9.2 * $k) 'Bold'
  # 21 pt, not 24: at 24 the hero figures drew their ascenders straight through the
  # "0 - 100" label above them and the label was half hidden. The label now owns 33-45 px and
  # the figure owns 47-73, with the unit sitting on the figure's baseline.
  $fNum = F 'Consolas' (21 * $k) 'Bold'
  $fNumSm = F 'Consolas' (13.2 * $k) 'Bold'
  $fUnit = F 'Segoe UI' (9 * $k) 'Bold'

  # ---- headline: 0-100
  Draw-Text $g '0 – 100' $fLab $brFaint $pad (33 * $k) 100 (12 * $k) $sfL
  if ($script:run.t100 -gt 0) {
    $numTxt = '{0:0.00}' -f $script:run.t100
    Draw-Text $g $numTxt $fNum $accentBrush $pad (47 * $k) 128 (26 * $k) $sfL
    $nw = $g.MeasureString($numTxt, $fNum).Width
    Draw-Text $g 's' $fUnit $brFaint ($pad + $nw - 5 * $k) (56 * $k) 20 (16 * $k) $sfL
  } else {
    Draw-Text $g '—' (F 'Consolas' (15 * $k) 'Bold') $brFaint $pad (53 * $k) 40 (20 * $k) $sfL
    Draw-Text $g 's' $fUnit $brFaint ($pad + 21 * $k) (56 * $k) 20 (16 * $k) $sfL
  }

  # ---- split row: 100-200 and total
  $half = ($w - $pad * 2) / 2.0
  $g.DrawLine($penSep, $pad, (79 * $k), ($w - $pad), (79 * $k))
  Draw-Text $g '100 – 200' $fLab $brFaint $pad (84 * $k) $half (12 * $k) $sfL
  Draw-Text $g (T 'total') $fLab $brFaint ($pad + $half) (84 * $k) $half (12 * $k) $sfL
  $split = 0.0
  if ($script:run.t100 -gt 0 -and $script:run.t200 -gt 0) { $split = $script:run.t200 - $script:run.t100 }
  Draw-Text $g $(if ($split -gt 0) { '{0:0.00}' -f $split } else { '—' }) $fNumSm $brTx $pad (94 * $k) $half (20 * $k) $sfL
  Draw-Text $g $(if ($script:run.t200 -gt 0) { '{0:0.00}' -f $script:run.t200 } else { '—' }) $fNumSm $brTx ($pad + $half) (94 * $k) $half (20 * $k) $sfL
  $g.DrawLine($penSep, $pad, (120 * $k), $w - $pad, (120 * $k))

  # ---- session / fuel / lap rows, with a small colour cue per row
  $sessName = Session-Name $d.session
  $clockTxt = if ($d.left -gt 0.5) { Fmt-Clock $d.left } else { T 'nolimit' }
  $lapsTxt = $sessName + ' · ' + $clockTxt
  $lapsLeftNum = -1
  if ($script:lpl -gt 0.05) { $lapsLeftNum = [math]::Max(0, [math]::Floor(($d.fuel - 0.5) / $script:lpl)) }
  $fuelTxt = ('{0:0.0} L' -f $d.fuel)
  if ($lapsLeftNum -ge 0) { $fuelTxt = $fuelTxt + ' · ' + $lapsLeftNum + ' ' + (T 'laps') }
  $lapTxt = (Fmt-Lap $d.cur)
  if ($d.best -gt 0) { $lapTxt = $lapTxt + ' / ' + (Fmt-Lap $d.best) }

  $rows = @(
    @{ k = (T 'r.session'); v = $lapsTxt;  y = 126 * $k; tone = $accentBrush; dot = $accentBrush },
    @{ k = (T 'r.fuel');    v = $fuelTxt;  y = 148 * $k; tone = $brTx;       dot = $brBlue },
    @{ k = (T 'r.lap');     v = $lapTxt;   y = 170 * $k; tone = $brTx;       dot = $brFaint }
  )
  foreach ($r in $rows) {
    $g.FillEllipse($r.dot, [single]($pad + 1 * $k), [single]($r.y + 6 * $k), [single](4 * $k), [single](4 * $k))
    Draw-Text $g $r.k $fRowKey $brDim ($pad + 10 * $k) $r.y ($w - $pad * 2 - 10 * $k) (16 * $k) $sfL
    Draw-Text $g $r.v $fRowVal $r.tone ($pad + 74 * $k) $r.y ($w - $pad * 2 - 74 * $k) (16 * $k) $sfR
  }
}

function Show-Hud {
  $script:userHidden = $false
  if (-not $form.Visible) { $form.Show(); $form.TopMost = $true }
  Render-Frame
}
function Hide-Hud { if ($form.Visible) { $form.Hide() } }

# Hiding has to survive the tick that follows it. The frame loop re-opens the panel whenever
# there is a session to describe, so a hide that only calls Hide-Hud is undone 80 ms later -
# which is exactly why the app's button and the tray item appeared to do nothing.
function Hide-ByUser {
  $script:userHidden = $true
  $State.hidden = $true
  $State.forceShow = $false
  Save-State
  Hide-Hud
}
function Show-ByUser {
  $script:userHidden = $false
  $State.hidden = $false
  $State.forceShow = $true
  Save-State
  Show-Hud
}
function Set-Size([string]$s) {
  $State.size = $s
  $script:scale = switch ($s) { 's' { 0.86 } 'l' { 1.18 } default { 1.0 } }
  $L = Get-Layout
  $form.Size = [Drawing.Size]::new([int]$L.w, [int]$L.h)
  Save-State
  Render-Frame
}
function Set-Lock([bool]$v) { $State.lock = $v; Save-State }
function Save-LeftScale { $State.leftScale = $script:leftScale; Save-State }
function Toggle-Lock {
  Set-Lock (-not $State.lock)
  try { if ($null -ne $miLock) { $miLock.Checked = [bool]$State.lock } } catch { }
  Update-Cursor $script:hover
}

# The paint code and the hit test read the same rectangles, so the glyphs cannot drift away
# from the place the mouse has to be. The box is deliberately larger than the glyph.
function Get-IconRect([string]$which) {
  $L = Get-Layout
  $k = $script:scale
  $cx = if ($which -eq 'close') { $L.w - 22 * $k } else { $L.w - 45 * $k }
  $cy = 15 * $k
  $hw = 11 * $k
  return [Drawing.Rectangle]::new([int]($cx - $hw), [int]($cy - $hw), [int]($hw * 2), [int]($hw * 2))
}
function Icon-At([int]$x, [int]$y) {
  foreach ($n in @('lock', 'close')) {
    $r = Get-IconRect $n
    if ($x -ge $r.Left -and $x -lt $r.Right -and $y -ge $r.Top -and $y -lt $r.Bottom) { return $n }
  }
  return ''
}
function Toast([string]$msg) { $script:toast = $msg; $script:toastUntil = $script:now + 1.8 }
function Update-Cursor([string]$hit) {
  try {
    if ($hit) { $form.Cursor = [System.Windows.Forms.Cursors]::Hand }
    elseif ($State.lock) { $form.Cursor = [System.Windows.Forms.Cursors]::Default }
    else { $form.Cursor = [System.Windows.Forms.Cursors]::SizeAll }
  } catch { }
}

# ---------------------------------------------------------------- control API
# The Apex settings panel has buttons for size and lock. A web page cannot start a process,
# but it can talk to one on loopback, so the panel drives this window instead of keeping a
# second copy of the same settings. Plain TcpListener rather than HttpListener: no URL ACL,
# no admin.
$script:port = 7799
$script:listener = $null
$script:lastBindTry = -99.0
# A previous instance that was killed can leave 7799 in TIME_WAIT and the bind then fails.
# Failing once used to disable the control channel for the rest of the run, which left the
# Apex window saying "not running" with the overlay plainly on screen; now it retries and
# asks for reuse-address so a restart cycle cannot lock itself out.
function Open-Control {
  try {
    $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $script:port)
    try {
      $l.Server.SetSocketOption([System.Net.Sockets.SocketOptionLevel]::Socket,
                                [System.Net.Sockets.SocketOptionName]::ReuseAddress, $true)
    } catch { }
    $l.Start()
    return $l
  } catch {
    # Why the control channel is down belongs in the log: a failed bind used to be invisible,
    # and the Apex window then reported "not running" with nothing to explain it.
    try {
      Add-Content -Path (Join-Path $StateDir 'overlay-error.log') -Value (
        '[' + (Get-Date -Format 'HH:mm:ss') + '] control channel bind failed: ' + $_.Exception.Message)
    } catch { }
    return $null
  }
}
$script:listener = Open-Control

function State-Json {
  $d = $script:data
  $o = [ordered]@{
    ok = $true; port = $script:port; visible = $form.Visible; lock = [bool]$State.lock
    size = $State.size; hasGame = [bool]($d -and $d.ok)
  }
  if ($d -and $d.ok) {
    $o.car = $d.car; $o.track = $d.track; $o.session = $d.session
    $o.left = [math]::Round($d.left, 1); $o.laps = $d.laps; $o.fuel = [math]::Round($d.fuel, 2)
    $o.lpl = [math]::Round($script:lpl, 2)
    # Lap times, in seconds, from the graphics page. The Apex stint card needs the pace and
    # the burn per lap to work out laps and fuel by itself; Read-Game has already mapped AC's
    # "no lap yet" sentinel (INT32_MAX) to 0, so a missing value is simply absent here.
    if ($d.cur -gt 0) { $o.cur = [math]::Round($d.cur / 1000.0, 3) }
    if ($d.last -gt 0) { $o.last = [math]::Round($d.last / 1000.0, 3) }
    if ($d.best -gt 0) { $o.best = [math]::Round($d.best / 1000.0, 3) }
    if ($d.numLaps -gt 0 -and $d.numLaps -lt 1000) { $o.numLaps = $d.numLaps }
    # Tyre block, in AC's wheel order (FL, FR, RL, RR). Rejected wholesale if any wheel is out of
    # range: a half-valid set would be worse than none, because the card reads as measured data.
    $pr = @($d.press); $tt = @($d.ttemp); $tw = @($d.wear)
    $okP = ($pr.Count -eq 4) -and (($pr | Where-Object { $_ -lt 5 -or $_ -gt 80 }).Count -eq 0)
    $okT = ($tt.Count -eq 4) -and (($tt | Where-Object { $_ -lt -30 -or $_ -gt 260 }).Count -eq 0)
    if ($okP) { $o.press = @($pr | ForEach-Object { [math]::Round($_, 1) }) }
    if ($okT) { $o.ttemp = @($tt | ForEach-Object { [math]::Round($_, 0) }) }
    if ($okT -and ($tw.Count -eq 4) -and (($tw | Where-Object { $_ -lt -0.01 -or $_ -gt 2 }).Count -eq 0)) {
      $o.wear = @($tw | ForEach-Object { [math]::Round($_, 3) })
    }
    $sb = Get-LapBest ("$($d.car)|$($d.track)")
    if ($sb -gt 0) { $o.bestSaved = [math]::Round($sb / 1000.0, 3) }
  }
  return ($o | ConvertTo-Json -Compress)
}

function Write-Response($stream, [string]$json) {
  $body = [Text.Encoding]::UTF8.GetBytes($json)
  $head = "HTTP/1.1 200 OK`r`n" +
          "Content-Type: application/json; charset=utf-8`r`n" +
          "Access-Control-Allow-Origin: *`r`n" +
          "Access-Control-Allow-Private-Network: true`r`n" +
          "Access-Control-Allow-Methods: GET, OPTIONS`r`n" +
          "Access-Control-Allow-Headers: *`r`n" +
          "Cache-Control: no-store`r`n" +
          "Content-Length: $($body.Length)`r`nConnection: close`r`n`r`n"
  $hb = [Text.Encoding]::ASCII.GetBytes($head)
  $stream.Write($hb, 0, $hb.Length)
  $stream.Write($body, 0, $body.Length)
  $stream.Flush()
}

function Serve-Control {
  if (-not $script:listener) { return }
  try {
    $guard = 0
    while ($script:listener.Pending() -and $guard -lt 4) {
      $guard++
      $cli = $script:listener.AcceptTcpClient()
      $cli.ReceiveTimeout = 300
      $st = $cli.GetStream()
      $buf = New-Object byte[] 2048
      $n = 0
      try { $n = $st.Read($buf, 0, $buf.Length) } catch { $n = 0 }
      $req = [Text.Encoding]::ASCII.GetString($buf, 0, $n)
      $line = ($req -split "`r`n")[0]
      $method = 'GET'; $target = '/'
      if ($line -match '^([A-Z]+)\s+(\S+)') { $method = $matches[1]; $target = $matches[2] }

      if ($method -eq 'OPTIONS') {
        $head = "HTTP/1.1 204 No Content`r`nAccess-Control-Allow-Origin: *`r`n" +
                "Access-Control-Allow-Private-Network: true`r`nAccess-Control-Allow-Methods: GET, OPTIONS`r`n" +
                "Access-Control-Allow-Headers: *`r`nContent-Length: 0`r`nConnection: close`r`n`r`n"
        $hb = [Text.Encoding]::ASCII.GetBytes($head)
        $st.Write($hb, 0, $hb.Length); $st.Flush()
      } elseif ($target -match '^/apex/cmd') {
        if ($target -match '[?&]size=([sml])') { Set-Size $matches[1] }
        if ($target -match '[?&]lock=([01])') { Set-Lock ($matches[1] -eq '1') }
        if ($target -match '[?&]show=([01])') {
          if ($matches[1] -eq '1') { Show-ByUser } else { Hide-ByUser }
        }
        Write-Response $st (State-Json)
      } elseif ($target -match '^/apex/state') {
        Write-Response $st (State-Json)
      } else {
        Write-Response $st '{"ok":false}'
      }
      $st.Close(); $cli.Close()
    }
  } catch { }
}

# ---------------------------------------------------------------- tray + menu
$menu = New-Object System.Windows.Forms.ContextMenuStrip
$miShow = $menu.Items.Add((T 'tray.show'))
$miHide = $menu.Items.Add((T 'tray.hide'))
$menu.Items.Add('-') | Out-Null
$miLock = $menu.Items.Add((T 'tray.lock'))
$menu.Items.Add('-') | Out-Null
$miS = $menu.Items.Add((T 'tray.s'))
$miM = $menu.Items.Add((T 'tray.m'))
$miL = $menu.Items.Add((T 'tray.l'))
$menu.Items.Add('-') | Out-Null
$miShortcut = $menu.Items.Add((T 'tray.shortcut'))
$menu.Items.Add('-') | Out-Null
$miStartup = $menu.Items.Add((T 'tray.startup'))
$miStartup.CheckOnClick = $true
$miQuit = $menu.Items.Add((T 'tray.quit'))

$miShow.Add_Click({ Show-ByUser })
$miHide.Add_Click({ Hide-ByUser })
$miLock.Add_Click({ Toggle-Lock })
$miS.Add_Click({ Set-Size 's' })
$miM.Add_Click({ Set-Size 'm' })
$miL.Add_Click({ Set-Size 'l' })
$miQuit.Add_Click({ $tray.Visible = $false; $form.Close() })

# A web page cannot start a process, but it can navigate to a URI scheme the OS has
# registered - WebView2 raises LaunchingExternalUriScheme for that and, unless the host
# cancels it, the shell launches the handler. Registering "apexoverlay:" under HKCU is what
# turns the button in the Apex window into a real launch; per-user, no admin, no elevation.
$ProtoKey = 'HKCU:\Software\Classes\apexoverlay'
function Test-Proto { Test-Path $ProtoKey }
function Set-Proto([bool]$on) {
  try {
    if ($on) {
      New-Item -Path $ProtoKey -Force | Out-Null
      New-ItemProperty -Path $ProtoKey -Name '(default)' -Value 'URL:Apex Overlay' -PropertyType String -Force | Out-Null
      New-ItemProperty -Path $ProtoKey -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
      New-Item -Path ($ProtoKey + '\shell\open\command') -Force | Out-Null
      $cmd = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' +
             $PSCommandPath + '" "%1"'
      New-ItemProperty -Path ($ProtoKey + '\shell\open\command') -Name '(default)' `
        -Value $cmd -PropertyType String -Force | Out-Null
    } else {
      Remove-Item -Path $ProtoKey -Recurse -Force -ErrorAction SilentlyContinue
    }
    return $true
  } catch { return $false }
}

$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$RunName = 'ApexOverlay'
function Test-Startup {
  try { return $null -ne (Get-ItemProperty -Path $RunKey -Name $RunName -ErrorAction SilentlyContinue) } catch { return $false }
}
function Set-Startup([bool]$on) {
  try {
    if ($on) {
      $cmd = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $PSCommandPath + '"'
      New-ItemProperty -Path $RunKey -Name $RunName -Value $cmd -PropertyType String -Force | Out-Null
    } else {
      Remove-ItemProperty -Path $RunKey -Name $RunName -ErrorAction SilentlyContinue
    }
  } catch { }
}
$miShortcut.Add_Click({
  try {
    $desk = [Environment]::GetFolderPath('Desktop')
    $lnkPath = Join-Path $desk 'Apex Overlay.lnk'
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($lnkPath)
    $sc.TargetPath = (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
    $sc.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $PSCommandPath + '"'
    $sc.WorkingDirectory = $PSScriptRoot
    $exe = Join-Path $PSScriptRoot 'Apex.exe'
    if (Test-Path $exe) { $sc.IconLocation = $exe + ',0' }
    $sc.WindowStyle = 7
    $sc.Description = 'Apex Overlay - HUD for Assetto Corsa / ACC'
    $sc.Save()
    $tray.ShowBalloonTip(3000, 'Apex Overlay', ((T 'msg.shortcut') + $lnkPath), 'Info')
  } catch {
    $tray.ShowBalloonTip(3000, 'Apex Overlay', ((T 'msg.fail') + $_.Exception.Message), 'Warning')
  }
})

if (-not $Shot -and -not $Diag -and -not (Test-Proto)) { Set-Proto $true | Out-Null }

$miProto = $menu.Items.Add((T 'tray.proto'))
$miProto.CheckOnClick = $true
$miProto.Checked = Test-Proto
$miProto.Add_Click({ Set-Proto ([bool]$miProto.Checked) | Out-Null; $miProto.Checked = Test-Proto })

$miStartup.Checked = Test-Startup
$miStartup.Add_Click({ Set-Startup ([bool]$miStartup.Checked); $miStartup.Checked = Test-Startup })

$ico = $null
try { $ico = [System.Drawing.Icon]::ExtractAssociatedIcon((Join-Path $PSScriptRoot 'Apex.exe')) } catch { }
if (-not $ico) { $ico = [System.Drawing.SystemIcons]::Application }
$tray = New-Object System.Windows.Forms.NotifyIcon
$tray.Icon = $ico
$tray.Text = 'Apex Overlay'
$tray.ContextMenuStrip = $menu
$tray.Visible = $true
$tray.Add_MouseDoubleClick({ Show-ByUser })

$form.ContextMenuStrip = $menu

# ---------------------------------------------------------------- drag + paint
$script:dragOff = $null
$script:hover = ''
$script:press = ''
$script:toast = ''
$script:toastUntil = 0.0
$script:userHidden = [bool]$State.hidden

$form.Add_MouseDown({
  param($s, $e)
  if ($e.Button -ne [System.Windows.Forms.MouseButtons]::Left) { return }
  $hit = Icon-At $e.X $e.Y
  if ($hit) {
    # press feedback only; the action fires on release, so sliding off cancels it
    $script:press = $hit
    Render-Frame
    return
  }
  if ($State.lock) { Toast (T 'toast.locked'); Render-Frame; return }
  $p = [System.Windows.Forms.Cursor]::Position
  $script:dragOff = @{ x = $p.X - $form.Left; y = $p.Y - $form.Top }
})
$form.Add_MouseMove({
  param($s, $e)
  if ($script:dragOff) {
    $p = [System.Windows.Forms.Cursor]::Position
    $form.Location = [Drawing.Point]::new([int]($p.X - $script:dragOff.x), [int]($p.Y - $script:dragOff.y))
    Render-Frame
    return
  }
  $hit = Icon-At $e.X $e.Y
  if ($hit -ne $script:hover) {
    $script:hover = $hit
    Update-Cursor $hit
    Render-Frame
  }
})
$form.Add_MouseLeave({
  param($s, $e)
  if ($script:hover -ne '' -or $script:press -ne '') {
    $script:hover = ''
    Render-Frame
  }
})
$form.Add_MouseUp({
  param($s, $e)
  if ($script:dragOff) {
    $script:dragOff = $null
    $State.x = $form.Left; $State.y = $form.Top; Save-State
    return
  }
  $pressed = $script:press
  $script:press = ''
  if (-not $pressed) { return }
  if ((Icon-At $e.X $e.Y) -ne $pressed) { Render-Frame; return }
  if ($pressed -eq 'lock') {
    Toggle-Lock
    Toast $(if ($State.lock) { T 'toast.locked' } else { T 'toast.unlocked' })
  } else {
    # The X closes the panel, not the program. Killing the process here is what made the
    # next click in the Apex window look broken - it reported "not running" and the only way
    # back was relaunching by hand.
    Hide-ByUser
    try { $tray.ShowBalloonTip(2500, 'Apex Overlay', (T 'msg.hidden'), 'Info') } catch { }
  }
  Render-Frame
})
# No Paint handler: a layered window shows the bitmap handed to the compositor, and drawing
# into the window DC would only burn CPU. Every change calls Render-Frame instead.

# ---------------------------------------------------------------- tick
$script:timer = New-Object System.Windows.Forms.Timer
$script:timer.Interval = 80
function Update-All {
  $script:now = $script:sw.Elapsed.TotalSeconds
    $d = Read-Game
    $script:data = $d

    if ($d -and $d.ok) {
      $k = "$($d.car)|$($d.track)"
      if ($k -ne $script:carKey) {
        $script:carKey = $k
        $script:lpl = 0.0
        if ($State.fuel.ContainsKey($k) -and $State.fuel[$k].lpl) { $script:lpl = [double]$State.fuel[$k].lpl }
        $script:lastLaps = $d.laps
        $script:lapStartFuel = $d.fuel
        $script:run = @{ active = $false; armed = $true; t0 = 0.0; t100 = 0.0; t200 = 0.0; stoppedAt = 0.0 }
      }

      # Best lap, remembered per car and track. The game only publishes iBestTime for the
      # session that is running, so a fresh session would leave the Apex stint card without a
      # pace figure until a lap is finished; this keeps the last known one on hand.
      if ($d.best -gt 0) {
        $bk = "$($d.car)|$($d.track)"
        $prevBest = [double](Get-LapBest $bk)
        if ($prevBest -le 0 -or $d.best -lt $prevBest - 1) {
          $State.lapBest[$bk] = [int]$d.best
          Save-State
        }
      }

      # fuel per lap, measured at each lap boundary - this is the number AC's own fuel app shows
      if ($d.laps -ne $script:lastLaps) {
        if ($script:lastLaps -ge 0 -and $script:lapStartFuel -gt 0 -and $d.laps -eq $script:lastLaps + 1) {
          $used = $script:lapStartFuel - $d.fuel
          if ($used -gt 0.05 -and $used -lt 30) {
            if ($script:lpl -le 0.05) { $script:lpl = $used } else { $script:lpl = 0.7 * $script:lpl + 0.3 * $used }
            $State.fuel[$script:carKey] = @{ lpl = [math]::Round($script:lpl, 3) }
            Save-State
          }
        }
        $script:lastLaps = $d.laps
        $script:lapStartFuel = $d.fuel
      }

      # Acceleration timing, sampled at 12.5 Hz - finer than the host's 1.2 s push.
      # Standing still ends the run: coming to a stop is what puts the car back on the line, so
      # the three numbers clear there and the next launch is timed from zero. The 0.3 s hold
      # keeps one noisy speed sample at the line from wiping a run that has just finished.
      $sp = $d.speed
      if ($sp -lt 1.0) {
        if ($script:run.stoppedAt -le 0) { $script:run.stoppedAt = $script:now }
        if (($script:now - $script:run.stoppedAt) -ge 0.3) {
          $script:run.active = $false
          $script:run.armed = $true
          $script:run.t100 = 0.0
          $script:run.t200 = 0.0
        }
      } else {
        $script:run.stoppedAt = 0.0
        if ($script:run.armed -and -not $script:run.active) {
          $script:run.active = $true; $script:run.armed = $false
          $script:run.t0 = $script:now; $script:run.t100 = 0.0; $script:run.t200 = 0.0
        }
      }
      if ($script:run.active) {
        $el = $script:now - $script:run.t0
        if ($script:run.t100 -le 0 -and $sp -ge 100) { $script:run.t100 = $el }
        if ($script:run.t200 -le 0 -and $sp -ge 200) {
          $script:run.t200 = $el; $script:run.active = $false
          $State.pb[$script:carKey] = @{ a = $script:run.t100; s = ($script:run.t200 - $script:run.t100); t = $script:run.t200 }
          Save-State
        }
        if ($el -gt 60) { $script:run.active = $false }
      }

      # The HUD exists only while there is a session to describe - no "waiting" box parked in
      # the corner of the desktop. The tray can force it open at any time.
      if (-not $form.Visible -and -not $script:userHidden -and -not $State.hidden) { Show-Hud }
    } else {
      if (-not $State.forceShow -and $form.Visible) { Hide-Hud }
    }

    if (-not $script:listener -and ($script:now - $script:lastBindTry) -gt 5) {
      $script:lastBindTry = $script:now
      $script:listener = Open-Control
    }
    Serve-Control
    Render-Frame
}

# A window with no console has nowhere to report a failure, and a timer callback that throws
# leaves the process alive with a dead HUD and a dead control channel - indistinguishable from
# "the overlay did not start". So every tick is guarded and the error is written to disk.
$script:timer = New-Object System.Windows.Forms.Timer
$script:timer.Interval = 80
$script:timer.Add_Tick({
  try {
    Update-All
  } catch {
    try {
      $msg = '[' + (Get-Date -Format 'HH:mm:ss') + '] ' + $_.Exception.Message + "`n" + $_.ScriptStackTrace
      Add-Content -Path (Join-Path $StateDir 'overlay-error.log') -Value $msg
    } catch { }
  }
})
$script:timer.Start()

# The data tick above is 80 ms, which is right for numbers and wrong for a colour transition:
# a 0.7 s fade lands in nine frames. This second timer only runs while Draw-Hud reports the
# accent still moving, and renders nothing otherwise, so the extra work lasts exactly as long
# as the fade does. Both timers fire on the UI thread, so they cannot overlap.
$script:fading = $false
$script:fadeTimer = New-Object System.Windows.Forms.Timer
# 40 ms = 25 fps. A frame costs about 11-12 ms to compose in PowerShell, so this is the
# fastest rate that still leaves the machine mostly free while the game is running.
$script:fadeTimer.Interval = 40
$script:fadeTimer.Add_Tick({
  if (-not $script:fading -or -not $form.Visible) { return }
  try {
    $script:now = $script:sw.Elapsed.TotalSeconds
    Render-Frame
  } catch { }
})
$script:fadeTimer.Start()

$form.Add_Shown({
  $L = Get-Layout
  $form.Size = [Drawing.Size]::new([int]$L.w, [int]$L.h)
  try {
    [ApexLayer]::MakeLayered($form.Handle)
    $script:layered = $true
  } catch {
    try { Add-Content -Path (Join-Path $StateDir 'overlay-layer.log') -Value ('[' + (Get-Date -Format 'HH:mm:ss') + '] MakeLayered failed: ' + $_.Exception.Message) } catch { }
  }
  $screen = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
  # Use the actual HWND size: at 125% DPI the form is larger than the logical $L.w/$L.h,
  # so clamping with the layout size left the bottom of the HUD below the screen.
  $fw = $form.Width; $fh = $form.Height
  if ($State.x -ge 0 -and $State.y -ge 0) {
    $x = [math]::Max($screen.Left + 4, [math]::Min([int]$State.x, $screen.Right - $fw - 4))
    $y = [math]::Max($screen.Top + 4,  [math]::Min([int]$State.y, $screen.Bottom - $fh - 4))
    $form.Location = [Drawing.Point]::new([int]$x, [int]$y)
  } else {
    $form.Location = [Drawing.Point]::new([int]($screen.Right - $fw - 24), [int]($screen.Bottom - $fh - 24))
  }
  if ($Uri -and -not $State.forceShow) { $State.forceShow = $true; Save-State }
  if (-not $State.forceShow) { Hide-Hud }
  try {
    Add-Content -Path (Join-Path $StateDir 'overlay-geom.log') -Value (
      '[' + (Get-Date -Format 'HH:mm:ss') + '] screen=' + $screen + ' form=' + $form.Width + 'x' + $form.Height +
      ' loc=' + $form.Left + ',' + $form.Top + ' dpi=' + $form.DeviceDpi + ' state=' + $State.x + ',' + $State.y)
  } catch { }
  Render-Frame
})

Read-Game | Out-Null

if ($Diag) {
  $okG = $null -ne (Open-Page 'acpmf_graphics' 768)
  $okP = $null -ne (Open-Page 'acpmf_physics' 256)
  $okS = $null -ne (Open-Page 'acpmf_static' 512)
  "pages: graphics=$okG physics=$okP static=$okS  (control port $($script:port))"
  if ($script:lastErr) { "last error: $($script:lastErr)" }
  $d = Read-Game
  if ($null -eq $d) { "no data (game not exposing shared memory - start a session)"; return }
  $d.GetEnumerator() | Sort-Object Name | ForEach-Object { '  {0} = {1}' -f $_.Key, $_.Value }
  return
}

if ($Shot) {
  if ($Demo) {
    $script:data = @{
      packet = 1; status = 2; session = 1; laps = 7; cur = 41200; last = 101800; best = 101200
      left = 541.0; inPit = 0; numLaps = 20; fuel = 32.4; gear = 4; rpm = 7200; speed = 0.0
      car = 'ks_porsche_911_gt3_r'; track = 'ks_barcelona'; maxRpm = 9000; maxFuel = 120.0; ok = $true
    }
    $script:lpl = 3.5
    $script:run = @{ active = $false; armed = $true; t0 = 0.0; t100 = 3.42; t200 = 9.29; stoppedAt = 0.0 }
  } else {
    $script:data = Read-Game
  }
  $L = Get-Layout
  # Same bitmap the compositor receives: 32bpp with alpha, so the PNG shows the real edge.
  $bmp = New-Object Drawing.Bitmap ([int]$L.w), ([int]$L.h), ([Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [Drawing.Graphics]::FromImage($bmp)
  $g.Clear([Drawing.Color]::FromArgb(0, 0, 0, 0))
  $g.SmoothingMode = 'AntiAlias'
  $g.TextRenderingHint = [Drawing.Text.TextRenderingHint]::AntiAliasGridFit
  Draw-Hud $g
  $bmp.Save($Shot, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  "saved $Shot ($($L.w)x$($L.h))"
  return
}

[System.Windows.Forms.Application]::Run($form)
