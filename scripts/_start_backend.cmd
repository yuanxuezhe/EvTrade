@echo off
cd /d D:\workspace\EvTrade\server
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload > D:\workspace\EvTrade\scripts\.logs\backend.log 2>&1
