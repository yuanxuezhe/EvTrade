@echo off
REM 一键启停前后端服务（包装 PowerShell 脚本）
REM 用法： dev.cmd [start^|stop^|restart^|status]

if "%~1"=="" set "ACTION=start" else set "ACTION=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" -Action %ACTION%
