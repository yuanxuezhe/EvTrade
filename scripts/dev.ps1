<#
.SYNOPSIS
  One-shot start/stop script for EvTrade backend (uvicorn:8000),
  frontend (Vite:50998), and hqserver (WebSocket:8765).

.USAGE
  powershell -File scripts\dev.ps1 -Action start|stop|restart|status

.NOTES
  - Vite proxies /api and /ws to 8000, frontend at :50998.
  - hqserver serves real-time quotes on ws://host:8765/quote_update.
  - Logs go to scripts\.logs\, pids to scripts\.pids\.
  - Environment variables EVTRADE_API_PORT / EVTRADE_FRONTEND_PORT override ports.
#>

param(
  [ValidateSet('start','stop','restart','status')]
  [string]$Action = 'start'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot   = Split-Path -Parent $PSScriptRoot
$LogsDir       = Join-Path $PSScriptRoot '.logs'
$PidsDir       = Join-Path $PSScriptRoot '.pids'
$BackendPort   = if ($env:EVTRADE_API_PORT)    { [int]$env:EVTRADE_API_PORT }    else { 8000 }
$FrontendPort  = if ($env:EVTRADE_FRONTEND_PORT) { [int]$env:EVTRADE_FRONTEND_PORT } else { 50998 }
$HqserverPort  = 8765
$BackendLog    = Join-Path $LogsDir 'backend.log'
$FrontendLog   = Join-Path $LogsDir 'frontend.log'
$HqserverLog   = Join-Path $LogsDir 'hqserver.log'
$BackendPidF   = Join-Path $PidsDir 'backend.pid'
$FrontendPidF  = Join-Path $PidsDir 'frontend.pid'
$HqserverPidF  = Join-Path $PidsDir 'hqserver.pid'
$EnvBlock      = "EVTRADE_API_PORT=$BackendPort", "EVTRADE_FRONTEND_PORT=$FrontendPort"

function Ensure-Dirs {
  if (-not (Test-Path $LogsDir)) { New-Item -ItemType Directory -Path $LogsDir | Out-Null }
  if (-not (Test-Path $PidsDir)) { New-Item -ItemType Directory -Path $PidsDir | Out-Null }
}

function Get-PortOwner([int]$Port) {
  $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($conn) { return [int]$conn[0].OwningProcess }
  return $null
}

function Stop-ByPort([int]$Port, [string]$Tag) {
  $pidOwner = Get-PortOwner $Port
  if ($null -eq $pidOwner) {
    Write-Host "[$Tag] port $Port is free"
    return
  }
  try {
    $proc = Get-Process -Id $pidOwner -ErrorAction SilentlyContinue
    if ($proc) {
      Write-Host "[$Tag] killing process tree PID $pidOwner ($($proc.ProcessName))"
      $null = cmd.exe /c "taskkill /F /T /PID $pidOwner" 2>&1
    } else {
      Write-Host "[$Tag] PID $pidOwner already gone (zombie)"
    }
  } catch {
    Write-Host "[$Tag] kill PID $pidOwner failed: $_"
  }
  Start-Sleep -Milliseconds 1200
  $pid2 = Get-PortOwner $Port
  if ($pid2) {
    Write-Host "[$Tag] port still held by PID $pid2, sweeping children"
    $children = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                  Where-Object { $_.ParentProcessId -eq $pid2 -or $_.ParentProcessId -eq $pidOwner } |
                  Select-Object -ExpandProperty ProcessId
    foreach ($c in $children) {
      Write-Host "[$Tag] killing child PID $c"
      $null = cmd.exe /c "taskkill /F /T /PID $c" 2>&1
    }
  }
  Start-Sleep -Seconds 1
  $pid3 = Get-PortOwner $Port
  if ($pid3) {
    Write-Host "[$Tag] WARNING port $Port still held by PID $pid3" -ForegroundColor Yellow
  }
}

function Start-Backend {
  Ensure-Dirs
  if (Get-PortOwner $BackendPort) {
    Write-Host "[backend] port $BackendPort already in use, skip"
    return
  }
  $script = Join-Path $PSScriptRoot '_start_backend.cmd'
  # Set env var so .cmd picks up the port
  $proc = Start-Process -FilePath "cmd.exe" `
                        -ArgumentList '/c', "set EVTRADE_API_PORT=$BackendPort && `"$script`"" `
                        -WindowStyle Hidden `
                        -PassThru
  Set-Content -Path $BackendPidF -Value $proc.Id
  Write-Host "[backend] started PID $($proc.Id) -> http://localhost:$BackendPort  log: $BackendLog"
}

function Start-Frontend {
  Ensure-Dirs
  if (Get-PortOwner $FrontendPort) {
    Write-Host "[frontend] port $FrontendPort already in use, skip"
    return
  }
  $script = Join-Path $PSScriptRoot '_start_frontend.cmd'
  $proc = Start-Process -FilePath "cmd.exe" `
                        -ArgumentList '/c', "set EVTRADE_FRONTEND_PORT=$FrontendPort && `"$script`"" `
                        -WindowStyle Hidden `
                        -PassThru
  Set-Content -Path $FrontendPidF -Value $proc.Id
  Write-Host "[frontend] started PID $($proc.Id) -> http://localhost:$FrontendPort  log: $FrontendLog"
}

function Start-Hqserver {
  Ensure-Dirs
  $hqDir = Join-Path $ProjectRoot 'hq'
  if (-not (Test-Path $hqDir)) {
    Write-Host "[hqserver] hq/ directory not found, skip"
    return
  }
  if (Get-PortOwner $HqserverPort) {
    Write-Host "[hqserver] port $HqserverPort already in use, skip"
    return
  }
  $script = Join-Path $PSScriptRoot '_start_hqserver.cmd'
  $proc = Start-Process -FilePath "cmd.exe" `
                        -ArgumentList '/c', "`"$script`"" `
                        -WindowStyle Hidden `
                        -PassThru
  Set-Content -Path $HqserverPidF -Value $proc.Id
  Write-Host "[hqserver] started PID $($proc.Id) -> ws://localhost:$HqserverPort  log: $HqserverLog"
}

function Test-Backend {
  try {
    $r = Invoke-WebRequest -Uri "http://localhost:$BackendPort/api/health" -UseBasicParsing -TimeoutSec 3
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

function Show-Status {
  Write-Host "--- ports ---"
  foreach ($p in @($BackendPort, $FrontendPort, $HqserverPort)) {
    $owner = Get-PortOwner $p
    if ($owner) {
      $proc = Get-Process -Id $owner -ErrorAction SilentlyContinue
      $name = if ($proc) { $proc.ProcessName } else { '(zombie)' }
      Write-Host ("  {0,-6} LISTEN  PID={1,-6} {2}" -f $p, $owner, $name)
    } else {
      Write-Host "  $p free"
    }
  }
  Write-Host "--- backend health ---"
  if (Test-Backend) {
    Write-Host "  GET /api/health -> 200 OK"
  } else {
    Write-Host "  GET /api/health -> FAIL"
  }
  Write-Host "--- logs ---"
  Write-Host "  $BackendLog"
  Write-Host "  $FrontendLog"
  Write-Host "  $HqserverLog"
}

switch ($Action) {
  'start' {
    Write-Host "=== START ==="
    Start-Backend
    Start-Frontend
    Start-Hqserver
    Write-Host ""
    Write-Host "Waiting 5s for services to come up..."
    Start-Sleep -Seconds 5
    Show-Status
  }
  'stop' {
    Write-Host "=== STOP ==="
    Stop-ByPort $FrontendPort 'frontend'
    Stop-ByPort $BackendPort  'backend'
    Stop-ByPort $HqserverPort 'hqserver'
    foreach ($f in @($BackendPidF, $FrontendPidF, $HqserverPidF)) {
      if (Test-Path $f) { Remove-Item $f -Force -ErrorAction SilentlyContinue }
    }
    Start-Sleep -Seconds 1
    Show-Status
  }
  'restart' {
    Write-Host "=== RESTART ==="
    & $PSCommandPath -Action stop
    Start-Sleep -Seconds 2
    & $PSCommandPath -Action start
  }
  'status' {
    Show-Status
  }
}
