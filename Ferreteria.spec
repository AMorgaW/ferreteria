# -*- mode: python ; coding: utf-8 -*-
"""
Spec de PyInstaller para FERREPRO (Sistema de Ferretería).

Genera una carpeta portable (onedir) sin consola, con TODAS las dependencias
incluidas: PySide6 (+plugins Qt: platforms, styles, imageformats,
printsupport), psycopg2, openpyxl, cryptography, y todos los módulos del
proyecto. No requiere Python ni ninguna herramienta instalada en el equipo
destino.

Construir:  python -m PyInstaller --noconfirm Ferreteria.spec
Salida:     dist/Ferreteria/Ferreteria.exe
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
PROJECT_DIR = os.path.abspath(os.getcwd())


# ── Recursos de datos (se embeben en el .exe) ─────────────────────────────
# Solo se incluyen si existen, para que el build no falle en otra máquina.
datas = []
for _src, _dst in [
    ("ferreteria.db", "."),
    (".env", "."),
    ("config", "config"),
    ("version.py", "."),
    # Coordinator SQL used to be embedded in inventory_coordinator.py.
    # After externalization it must ship as a data file or frozen apply fails.
    ("supabase_inventory_coordinator.sql", "."),
]:
    if os.path.exists(os.path.join(PROJECT_DIR, _src)):
        datas.append((_src, _dst))

binaries = []

# ── Imports ocultos ───────────────────────────────────────────────────────
# Módulos del proyecto que se importan de forma dinámica (dentro de funciones)
# y que el analizador estático podría no seguir.
hiddenimports = [
    # PostgreSQL / Supabase
    "psycopg2", "psycopg2.extras", "psycopg2._psycopg",
    # Qt que se usa pero conviene forzar (impresión de facturas)
    "PySide6.QtPrintSupport", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
    # Módulos propios de nivel superior (importados dinámicamente)
    "main", "client_app", "local_server", "local_server_manager",
    "local_sync", "local_first_db", "local_first_config",
    "pg_compat", "database", "models", "auth", "security",
    "exportar", "formato", "backup_manager", "cert_manager",
    "app_logging", "version", "unidades_venta_manager", "ui_config",
]
# Paquetes del proyecto: incluir TODOS sus submódulos.
hiddenimports += collect_submodules("ui")
hiddenimports += collect_submodules("services")
hiddenimports += collect_submodules("repositories")

# ── Dependencias con datos/binarios propios ───────────────────────────────
for _pkg in ("openpyxl", "cryptography", "psycopg2"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# ── Exclusiones ───────────────────────────────────────────────────────────
# Módulos Qt pesados que el proyecto NO usa (reducen tamaño y evitan plugins
# innecesarios) y otros frameworks que podrían colarse transitivamente.
excludes = [
    # Qt no usado
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngine",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtTest",
    # Otros frameworks / dev tools que no forman parte de la app
    "PyQt5", "PyQt6", "tkinter", "matplotlib", "numpy", "pandas", "scipy",
    "PIL", "IPython", "pytest", "notebook", "jupyter", "sphinx",
]

a = Analysis(
    ["launcher.py"],
    pathex=[PROJECT_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="Ferreteria",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX off: evita falsos positivos de antivirus
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,             # aplicación gráfica: sin ventana de terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=(os.path.join(PROJECT_DIR, "app.ico")
          if os.path.exists(os.path.join(PROJECT_DIR, "app.ico")) else None),
    exclude_binaries=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Ferreteria",
)
