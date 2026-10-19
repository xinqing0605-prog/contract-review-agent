$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host '首次运行：创建 .venv 并安装依赖（约 1 分钟）…'
    $base = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $base) { throw '找不到 python，请先安装 Python 3.10+ 并加入 PATH' }
    & $base -m venv $venv
    & $python -m pip install --quiet --upgrade pip
    & $python -m pip install --quiet -r (Join-Path $root 'backend\requirements.txt')
}

Write-Host 'ClauseGuard API: http://127.0.0.1:8103'
& $python -m uvicorn backend.app:app --host 127.0.0.1 --port 8103 --app-dir $root
