@echo off
rem 停掉抓地力后端：先让它把轮胎曲线还原成原厂，再退出。
powershell -NoProfile -ExecutionPolicy Bypass -Command "try{Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 'http://127.0.0.1:7798/quit' | Out-Null; Write-Host '已还原并退出'}catch{Write-Host '服务没在运行'}"
timeout /t 2 >nul
