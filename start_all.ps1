<#
  ClauseGuard 一键启动 / 停止

  .\start_all.ps1          启动后端(8103) + 前端(5173)
  .\start_all.ps1 -Open    启动并打开浏览器
  .\start_all.ps1 -Stop    停止两个服务
#>
param(
    [switch]$Stop,
    [switch]$Open
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$web = Join-Path $root 'web'
$logs = Join-Path $root '.logs'

function Get-Listener([int]$Port) {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
}

function Stop-Port([int]$Port) {
    foreach ($conn in @(Get-Listener $Port)) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

function Wait-Http([string]$Url, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return $true }
        } catch {
            Start-Sleep -Milliseconds 700
        }
    }
    return $false
}

if ($Stop) {
    Stop-Port 8103
    Stop-Port 5173
    Write-Host '已停止：8103 / 5173' -ForegroundColor Yellow
    return
}

if (-not (Test-Path $python)) {
    throw "缺少 Python 环境。先运行一次 .\run_local.ps1，它会自动创建 .venv 并装依赖。"
}
if (-not (Test-Path (Join-Path $web 'node_modules'))) {
    throw "缺少前端依赖。先执行：cd web; npm install"
}

New-Item -ItemType Directory -Force -Path $logs | Out-Null
Stop-Port 8103
Stop-Port 5173

Write-Host '启动后端 8103 ...' -ForegroundColor Cyan
Start-Process -FilePath $python `
    -ArgumentList '-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8103','--app-dir',$root `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logs 'backend.out.log') `
    -RedirectStandardError (Join-Path $logs 'backend.err.log')

Write-Host '启动前端 5173 ...' -ForegroundColor Cyan
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','npm run dev' `
    -WorkingDirectory $web -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logs 'web.out.log') `
    -RedirectStandardError (Join-Path $logs 'web.err.log')

$apiOk = Wait-Http 'http://127.0.0.1:8103/api/health' 30
$webOk = Wait-Http 'http://127.0.0.1:5173/' 25

Write-Host ''
if ($apiOk -and $webOk) {
    Write-Host 'ClauseGuard 已启动' -ForegroundColor Green
} else {
    Write-Host '有服务没起来，检查日志：' -ForegroundColor Red
    if (-not $apiOk) { Write-Host "  $logs\backend.err.log" -ForegroundColor Red }
    if (-not $webOk) { Write-Host "  $logs\web.err.log" -ForegroundColor Red }
}
Write-Host '  前端      http://127.0.0.1:5173'
Write-Host '  接口文档  http://127.0.0.1:8103/docs'
Write-Host "  日志      $logs"
Write-Host '  停止      .\start_all.ps1 -Stop'
Write-Host ''

if ($Open -and $webOk) {
    Start-Process 'http://127.0.0.1:5173'
}
