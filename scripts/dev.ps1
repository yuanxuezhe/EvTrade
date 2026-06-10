<#
.SYNOPSIS
  One-shot start/stop script for EvTrade frontend (Vite:3000) and backend (uvicorn:8001).

.USAGE
  powershell -File scripts\dev.ps1 -Action start|stop|restart|status

.NOTES
  - 8000 is occupied by an unkillable process owned by another user; we use 8001.
  - Vite proxies /api and /ws to 8001, so the frontend still works at :3000.
  - Logs go to scripts\.logs\, pids to scripts\.pids\.
#>

param(
  [ValidateSet('start','stop','restart','status')]
  [string]$Action = 'start'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot   = Split-Path -Parent $PSScriptRoot
$LogsDir       = Join-Path $PSScriptRoot '.logs'
$PidsDir       = Join-Path $PSScriptRoot '.pids'
$BackendPort   = 8002
$FrontendPort  = 3000
$BackendLog    = Join-Path $LogsDir 'backend.log'
$FrontendLog   = Join-Path $LogsDir 'frontend.log'
$BackendPidF   = Join-Path $PidsDir 'backend.pid'
$FrontendPidF  = Join-Path $PidsDir 'frontend.pid'

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
      Write-Host "[$Tag] killing process tree at PID $pidOwner ($($proc.ProcessName))"
      # taskkill /T kills the process and all its children (uvicorn reloader + worker)
      # /F is force. We invoke cmd.exe to avoid bash escaping issues with slashes.
      $null = cmd.exe /c "taskkill /F /T /PID $pidOwner" 2>&1
    } else {
      Write-Host "[$Tag] PID $pidOwner already gone (zombie), port may still be held by a child"
    }
  } catch {
    Write-Host "[$Tag] kill PID $pidOwner failed: $_"
  }
  # Sweep up any remaining children that may still hold the socket
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
    Write-Host "[$Tag] WARNING port $Port still held by PID $pid3 (Windows kernel may need time to release)" -ForegroundColor Yellow
  }
}

function Start-Backend {
  Ensure-Dirs
  if (Get-PortOwner $BackendPort) {
    Write-Host "[backend] port $BackendPort already in use, skip"
    return
  }
  $script = Join-Path $PSScriptRoot '_start_backend.cmd'
  $proc = Start-Process -FilePath "cmd.exe" `
                        -ArgumentList '/c', $script `
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
                        -ArgumentList '/c', $script `
                        -WindowStyle Hidden `
                        -PassThru
  Set-Content -Path $FrontendPidF -Value $proc.Id
  Write-Host "[frontend] started PID $($proc.Id) -> http://localhost:$FrontendPort  log: $FrontendLog"
}

function Test-Backend {
  try {
    $r = Invoke-WebRequest -Uri "http://localhost:$BackendPort/api/health" -UseBasicParsing -TimeoutSec 3
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

function Show-Status {
  Write-Host "--- ports ---"
  foreach ($p in @($BackendPort, $FrontendPort)) {
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
}

switch ($Action) {
  'start' {
    Write-Host "=== START ==="
    Start-Backend
    Start-Frontend
    Write-Host ""
    Write-Host "Waiting 5s for services to come up..."
    Start-Sleep -Seconds 5
    Show-Status
  }
  'stop' {
    Write-Host "=== STOP ==="
    Stop-ByPort $FrontendPort 'frontend'
    Stop-ByPort $BackendPort  'backend'
    if (Test-Path $BackendPidF)  { Remove-Item $BackendPidF  -Force -ErrorAction SilentlyContinue }
    if (Test-Path $FrontendPidF) { Remove-Item $FrontendPidF -Force -ErrorAction SilentlyContinue }
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
