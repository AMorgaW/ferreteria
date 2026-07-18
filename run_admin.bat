@echo off
setlocal
cd /d "%~dp0"
set DB_MODE=local
set APP_MODE=admin
python main.py
pause
