# Downloads a static ffmpeg for the "import my own intro" feature.
#
#   powershell -ExecutionPolicy Bypass -File tools\get_ffmpeg.ps1
#
# The app itself does not need ffmpeg; only the import does (it re-encodes any video into the
# WMV2/WMAV2/ASF file ACC can actually play). Roughly 80 MB, unpacked to tools\ffmpeg\.

$ErrorActionPreference = 'Stop'
$tools = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = Join-Path $tools 'ffmpeg'
$exe = Join-Path $dest 'ffmpeg.exe'

if (Test-Path $exe) {
    Write-Output ("already present: {0}" -f $exe)
    & $exe -version | Select-Object -First 1
    exit 0
}

New-Item -ItemType Directory -Path $dest -Force | Out-Null
$zip = Join-Path $env:TEMP 'apex-ffmpeg.zip'
$url = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
Write-Output ("downloading {0}" -f $url)
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing

Write-Output 'unpacking'
$tmp = Join-Path $env:TEMP 'apex-ffmpeg'
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
$found = Get-ChildItem $tmp -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1
if (-not $found) { Write-Output 'ffmpeg.exe not found in the archive'; exit 1 }
Copy-Item $found.FullName $exe -Force
Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue

Write-Output ("installed: {0}" -f $exe)
& $exe -version | Select-Object -First 1
