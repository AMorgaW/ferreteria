@echo off
setlocal
cd /d "%~dp0"
set DB_MODE=local
python local_sync.py
pause
