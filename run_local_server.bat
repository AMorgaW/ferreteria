@echo off
setlocal
cd /d "%~dp0"

if "%LOCAL_SERVER_HOST%"=="" set LOCAL_SERVER_HOST=0.0.0.0
if "%LOCAL_SERVER_PORT%"=="" set LOCAL_SERVER_PORT=8000
if "%DB_MODE%"=="" set DB_MODE=local

echo ============================================
echo   Servidor local Ferreteria
echo ============================================
echo Host: %LOCAL_SERVER_HOST%
echo Puerto: %LOCAL_SERVER_PORT%
echo.
echo En PCs trabajadoras usar:
echo   http://IP_DE_ESTE_PC:%LOCAL_SERVER_PORT%
echo.

python local_server.py --host %LOCAL_SERVER_HOST% --port %LOCAL_SERVER_PORT%

pause
