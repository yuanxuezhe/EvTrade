@echo off
rem Start EvTrade backend (uvicorn)
rem This script is called by dev.ps1; paths are relative to project root.
set "ROOT=%~dp0.."
cd /d "%ROOT%\server"
python -m uvicorn main:app --host 0.0.0.0 --port %EVTRADE_API_PORT% --reload > "%ROOT%\scripts\.logs\backend.log" 2>&1
