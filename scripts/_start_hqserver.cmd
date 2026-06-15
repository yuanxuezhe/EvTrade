@echo off
rem Start EvTrade HQ server (WebSocket quotes on :8765)
rem This script is called by dev.ps1; paths are relative to project root.
set "ROOT=%~dp0.."
cd /d "%ROOT%\hq"
python hqserver.py > "%ROOT%\scripts\.logs\hqserver.log" 2>&1
