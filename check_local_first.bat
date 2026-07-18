@echo off
setlocal
cd /d "%~dp0"
python scripts\check_local_first.py
pause
