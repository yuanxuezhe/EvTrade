@echo off
rem Start EvTrade frontend (Vite)
rem This script is called by dev.ps1; paths are relative to project root.
set "ROOT=%~dp0.."
cd /d "%ROOT%\client"
call npm run dev > "%ROOT%\scripts\.logs\frontend.log" 2>&1
