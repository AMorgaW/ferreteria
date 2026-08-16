@echo off
REM ============================================================
REM   FERREPRO - Construccion del ejecutable portable + instalador
REM ============================================================
cd /d "%~dp0"

echo [1/2] Construyendo ejecutable portable (PyInstaller desde Ferreteria.spec)...
REM Se usa el .spec como UNICA fuente de verdad: incluye todos los recursos,
REM plugins de Qt, DLLs y modulos, y compila sin consola (aplicacion grafica).
if not exist "Ferreteria.spec" (
  echo ERROR: falta Ferreteria.spec
  pause & exit /b 1
)
findstr /C:"supabase_inventory_coordinator.sql" Ferreteria.spec >nul
if errorlevel 1 (
  echo ERROR: Ferreteria.spec debe incluir supabase_inventory_coordinator.sql en datas.
  echo El SQL del coordinador ya no va embebido en inventory_coordinator.py.
  pause & exit /b 1
)
python -m PyInstaller --noconfirm --clean Ferreteria.spec
if errorlevel 1 ( echo ERROR al construir el ejecutable & pause & exit /b 1 )

echo.
echo Aplicacion portable lista en: dist\Ferreteria\Ferreteria.exe
echo Para distribuir, copie o comprima la carpeta completa: dist\Ferreteria
echo.
echo [2/2] (Opcional) Compilando instalador con Inno Setup...
where iscc >nul 2>&1
if errorlevel 1 (
  echo Inno Setup ^(iscc^) no esta instalado. Es OPCIONAL.
  echo Para distribuir basta con copiar o comprimir la carpeta completa dist\Ferreteria
  echo Si desea un instalador, descargue Inno Setup de https://jrsoftware.org/isdl.php
  pause & exit /b 0
)
iscc installer.iss
echo.
echo Listo. Instalador en: dist_installer\FERREPRO-Setup-4.0.0.exe
pause
