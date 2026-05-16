@echo off
echo ============================================
echo   Sistema de Ferreteria - Iniciando...
echo ============================================
echo.

REM Verificar si Python esta instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no esta instalado
    echo Por favor instale Python 3.8 o superior desde python.org
    pause
    exit /b 1
)

echo Python detectado correctamente
echo.
echo Iniciando el sistema...
echo.

REM Ejecutar el programa y guardar errores
python main.py > error_log.txt 2>&1

REM Si hay un error, mostrar mensaje
if errorlevel 1 (
    echo.
    echo ERROR: El programa se cerro inesperadamente
    echo Revise los mensajes de error anteriores
    echo Los errores se guardaron en: error_log.txt
    type error_log.txt
    pause
)

exit /b 0