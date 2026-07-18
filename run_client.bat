@echo off
setlocal
cd /d "%~dp0"
set APP_MODE=client
python client_app.py
pause
